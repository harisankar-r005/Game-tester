"""logcat parsing and crash / ANR detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

THREADTIME_RE = re.compile(
    r"^(?P<ts>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFA])\s+"
    r"(?P<tag>.*?)\s*:\s?(?P<msg>.*)$"
)

JAVA_FRAME_RE = re.compile(r"^\s+at\s+[\w$.]+\(.*\)\s*$")
JAVA_EXC_RE = re.compile(r"^([\w$.]+(?:Exception|Error|Throwable))\b")
NATIVE_SIGNAL_RE = re.compile(r"Fatal signal (\d+) \((\w+)\)")
HEX_RE = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{8,}\b")
NUMBER_RE = re.compile(r"\b\d+\b")

CRASH_KINDS = (
    "java_crash",
    "native_crash",
    "anr",
    "process_death",
    "low_memory",
    "exception",
)


@dataclass(frozen=True)
class LogLine:
    ts: str
    pid: int
    tid: int
    level: str
    tag: str
    msg: str
    raw: str = ""

    @property
    def is_error(self) -> bool:
        return self.level in ("E", "F", "A")


@dataclass
class Crash:
    """One crash, ANR or abnormal termination found in the log stream."""

    kind: str
    signature: str
    message: str
    ts: str = ""
    stack: List[str] = field(default_factory=list)
    step: int = 0
    screenshot: str = ""
    count: int = 1

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "signature": self.signature,
            "message": self.message,
            "ts": self.ts,
            "stack": self.stack,
            "step": self.step,
            "screenshot": self.screenshot,
            "count": self.count,
        }

    @property
    def label(self) -> str:
        names = {
            "java_crash": "Java crash",
            "native_crash": "Native crash",
            "anr": "ANR / not responding",
            "process_death": "Process death",
            "low_memory": "Low memory kill",
            "exception": "Uncaught exception",
        }
        return names.get(self.kind, self.kind)


def parse_lines(text: str) -> List[LogLine]:
    """Parse ``logcat -v threadtime`` output, skipping lines we cannot place."""
    lines: List[LogLine] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        match = THREADTIME_RE.match(raw)
        if not match:
            continue
        try:
            pid = int(match.group("pid"))
            tid = int(match.group("tid"))
        except ValueError:
            continue
        lines.append(
            LogLine(
                ts=match.group("ts"),
                pid=pid,
                tid=tid,
                level=match.group("level"),
                tag=match.group("tag").strip(),
                msg=match.group("msg"),
                raw=raw,
            )
        )
    return lines


def normalise_signature(text: str) -> str:
    """Strip addresses/numbers so the same bug dedupes across occurrences."""
    cleaned = HEX_RE.sub("0x?", text)
    cleaned = NUMBER_RE.sub("N", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:220]


def _java_block(lines: Sequence[LogLine], index: int, limit: int = 60) -> tuple:
    """Extract (exception class, stack frames) from the AndroidRuntime block.

    Android splits one crash over many log lines that all share the
    ``AndroidRuntime`` tag and pid::

        E/AndroidRuntime: FATAL EXCEPTION: main
        E/AndroidRuntime: Process: com.foo, PID: 123
        E/AndroidRuntime: java.lang.NullPointerException: boom
        E/AndroidRuntime:     at com.foo.Bar.baz(Bar.java:12)
    """
    origin = lines[index]
    exc = ""
    stack: List[str] = []
    for line in lines[index + 1 : index + 1 + limit]:
        same_tag = line.tag == origin.tag or line.tag in ("AndroidRuntime", "System.err")
        same_pid = line.pid == origin.pid
        body = line.msg.rstrip()
        stripped = body.strip()
        if not stripped:
            continue
        is_frame = stripped.startswith("at ") or stripped.startswith("Caused by:")
        if not (same_tag and (same_pid or is_frame or line.tag == origin.tag)):
            break
        if line.tag == "AndroidRuntime" and not same_pid:
            break
        if is_frame:
            stack.append(stripped)
            continue
        if stripped.startswith("..."):
            stack.append(stripped)
            continue
        if stripped.startswith("Process:") or stripped.startswith("PID:"):
            continue
        if exc and not is_frame:
            # A second, non-frame message after the exception line ends the block.
            break
        match = JAVA_EXC_RE.search(stripped)
        if match:
            exc = match.group(1)
            stack.append(stripped)
    return exc, stack


def _stack_after(lines: Sequence[LogLine], index: int, limit: int = 60) -> List[str]:
    """Collect the indented stack trace that follows a fatal exception line."""
    stack: List[str] = []
    for line in lines[index + 1 : index + 1 + limit]:
        body = line.msg
        if not body.strip():
            continue
        stripped = body.strip()
        if JAVA_FRAME_RE.match(body) or stripped.startswith("Caused by:"):
            stack.append(stripped)
            continue
        if stripped.startswith("..."):  # ellipsis frame
            stack.append(stripped)
            continue
        if line.is_error and stack:
            break
        if stack and not stripped.startswith("at "):
            break
    return stack


class CrashDetector:
    """Stateful detector: feed it successive log windows, get new crashes back.

    Kept free of device knowledge so it can be unit tested from fixtures.
    """

    def __init__(self, package: str, min_level: str = "E") -> None:
        self.package = package
        self.min_level = min_level

    def feed(self, lines: Iterable[LogLine], step: int = 0) -> List[Crash]:
        lines = list(lines)
        found: List[Crash] = []
        for index, line in enumerate(lines):
            crash = self._classify(lines, index, step)
            if crash is not None:
                found.append(crash)
        return found

    # -- internals ---------------------------------------------------------
    def _mentions_package(self, text: str) -> bool:
        return bool(self.package) and self.package in text

    def _classify(self, lines: Sequence[LogLine], index: int, step: int) -> Optional[Crash]:
        line = lines[index]
        msg = line.msg.strip()

        if "FATAL EXCEPTION" in msg:
            if not (self._mentions_package(msg) or line.tag == "AndroidRuntime"):
                return None
            exc, stack = _java_block(lines, index)
            if not exc:
                for follower in lines[index + 1 : index + 4]:
                    match = JAVA_EXC_RE.search(follower.msg.strip())
                    if match:
                        exc = match.group(1)
                        break
            message = exc or msg
            return Crash(
                kind="java_crash",
                signature=normalise_signature(f"{exc or 'FATAL EXCEPTION'} | {msg}"),
                message=message,
                ts=line.ts,
                stack=stack,
                step=step,
            )

        match = NATIVE_SIGNAL_RE.search(msg)
        if match:
            signal_no, signal_name = match.group(1), match.group(2)
            return Crash(
                kind="native_crash",
                signature=normalise_signature(f"signal {signal_no} ({signal_name}) {msg}"),
                message=f"Fatal signal {signal_no} ({signal_name})",
                ts=line.ts,
                stack=[msg] if msg else [],
                step=step,
            )

        if line.tag == "ActivityManager" and msg.startswith("ANR in "):
            subject = msg.split("ANR in ", 1)[1].split()[0] if len(msg.split()) > 2 else ""
            if subject and self.package and not subject.startswith(self.package):
                return None
            return Crash(
                kind="anr",
                signature=normalise_signature(f"ANR {msg}"),
                message=msg,
                ts=line.ts,
                stack=[],
                step=step,
            )

        if msg.startswith("Process ") and " has died" in msg and self._mentions_package(msg):
            return Crash(
                kind="process_death",
                signature="process death",
                message=msg,
                ts=line.ts,
                step=step,
            )

        if msg.startswith("Force finishing activity") and (
            "Application Not Responding" in msg or "anr" in msg.lower()
        ):
            return Crash(
                kind="anr",
                signature=normalise_signature(msg),
                message=msg,
                ts=line.ts,
                step=step,
            )

        if line.tag == "lowmemorykiller" or (
            "lowmemorykiller" in msg.lower() and self._mentions_package(msg)
        ):
            return Crash(
                kind="low_memory",
                signature=normalise_signature(msg),
                message="Process killed by lowmemorykiller",
                ts=line.ts,
                step=step,
            )

        # Uncaught exceptions logged outside AndroidRuntime (Unity, Unreal, RN).
        if line.level in ("E", "F") and "uncaught" in msg.lower() and "exception" in msg.lower():
            if self._mentions_package(msg) or not self.package:
                return Crash(
                    kind="exception",
                    signature=normalise_signature(msg),
                    message=msg,
                    ts=line.ts,
                    stack=_stack_after(lines, index),
                    step=step,
                )
        return None


def merge_crashes(existing: List[Crash], incoming: List[Crash]) -> List[Crash]:
    """Deduplicate by signature while keeping the first example and a count."""
    index = {c.signature: c for c in existing}
    for crash in incoming:
        known = index.get(crash.signature)
        if known is None:
            existing.append(crash)
            index[crash.signature] = crash
        else:
            known.count += 1
            if not known.stack and crash.stack:
                known.stack = crash.stack
    return existing


def format_for_prompt(lines: Sequence[LogLine], limit: int = 12) -> str:
    """Compact recent log excerpt for an LLM prompt."""
    interesting = [ln for ln in lines if ln.is_error or ln.level == "W"]
    chosen = (interesting or list(lines))[-limit:]
    return "\n".join(f"{ln.level}/{ln.tag}: {ln.msg[:180]}" for ln in chosen)
