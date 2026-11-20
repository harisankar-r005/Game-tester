"""Parsers for the ``dumpsys`` output the harness samples while running."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, Optional

_NUM = r"-?\d+(?:\.\d+)?"


def _int(text: str, group: str, default: Optional[int] = None) -> Optional[int]:
    match = re.search(rf"{group}\s*[:=]\s*({_NUM})", text)
    if not match:
        return default
    try:
        return int(float(match.group(1)))
    except ValueError:
        return default


def _float(text: str, pattern: str) -> Optional[float]:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (IndexError, ValueError):
        return None


def parse_gfxinfo(text: str) -> Dict[str, Optional[float]]:
    """Frame statistics from ``dumpsys gfxinfo <pkg>``.

    Only the aggregate section matters here; per-frame rows are ignored.
    """
    out: Dict[str, Optional[float]] = {
        "total_frames": None,
        "janky_frames": None,
        "janky_percent": None,
        "p50_ms": None,
        "p90_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "missed_vsync": None,
        "slow_ui_thread": None,
        "deadline_missed": None,
    }
    if not text:
        return out

    total = _int(text, r"Total frames rendered")
    if total is None:
        total = _int(text, r"Total frames")
    out["total_frames"] = total

    match = re.search(r"Janky frames(?:\s*\(legacy\))?\s*:\s*(\d+)\s*(?:\(([\d.]+)%)?\)?", text)
    if match:
        out["janky_frames"] = int(match.group(1))
        if match.group(2):
            out["janky_percent"] = float(match.group(2))

    for pct, key in ((50, "p50_ms"), (90, "p90_ms"), (95, "p95_ms"), (99, "p99_ms")):
        value = _float(text, rf"{pct}(?:st|nd|rd|th) percentile:\s*({_NUM})ms")
        out[key] = value

    out["missed_vsync"] = _int(text, r"Number Missed Vsync")
    out["slow_ui_thread"] = _int(text, r"Number Slow UI thread")
    out["deadline_missed"] = _int(text, r"Number Frame deadline missed")
    return out


def parse_meminfo(text: str) -> Dict[str, Optional[int]]:
    """Total PSS plus heap split (kB) from ``dumpsys meminfo <pkg>``."""
    out: Dict[str, Optional[int]] = {
        "total_pss_kb": None,
        "java_heap_kb": None,
        "native_heap_kb": None,
        "graphics_kb": None,
    }
    if not text:
        return out

    # Legacy single line: "TOTAL PSS: 12345"
    legacy = re.search(r"TOTAL PSS:\s*(\d+)", text)
    if legacy:
        out["total_pss_kb"] = int(legacy.group(1))

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 2:
            continue
        two_word = fields[0] in ("Native", "Dalvik", "Java", "Gfx", "GL")
        head = " ".join(fields[:2]) if two_word else fields[0]
        index = 2 if two_word else 1
        try:
            value = int(fields[index])
        except (IndexError, ValueError):
            continue
        if head == "TOTAL" and out["total_pss_kb"] is None:
            out["total_pss_kb"] = value
        elif head == "Java Heap":
            out["java_heap_kb"] = value
        elif head == "Dalvik Heap":
            out["java_heap_kb"] = value
        elif head == "Native Heap":
            out["native_heap_kb"] = value
        elif head in ("Gfx dev", "GL mtrack"):
            out["graphics_kb"] = value
    return out


def parse_cpuinfo(text: str, package: str) -> Dict[str, Optional[float]]:
    """CPU share of the tested package from ``dumpsys cpuinfo``.

    Input looks like::

        CPU usage from 0ms to 5013ms later (...):
          43% 1234/com.example.game: 30% user + 13% kernel / faults: 12 minor
    """
    out: Dict[str, Optional[float]] = {"cpu_percent": None, "cpu_user": None, "cpu_kernel": None}
    if not text or not package:
        return out
    pattern = re.compile(
        rf"(\d+(?:\.\d+)?)%\s+(\d+)/({re.escape(package)}[^:]*):\s*"
        r"(\d+(?:\.\d+)?)%\s*user\s*\+\s*(\d+(?:\.\d+)?)%\s*kernel",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if match:
        out["cpu_percent"] = float(match.group(1))
        out["cpu_user"] = float(match.group(4))
        out["cpu_kernel"] = float(match.group(5))
        return out
    loose = re.search(rf"(\d+(?:\.\d+)?)%\s+\d+/{re.escape(package)}", text)
    if loose:
        out["cpu_percent"] = float(loose.group(1))
    return out


def parse_surfaceflinger_latency(text: str) -> Dict[str, Optional[float]]:
    """Frame pacing from ``dumpsys SurfaceFlinger --latency <layer>``.

    Games render through GL and expose nothing in ``gfxinfo``; SurfaceFlinger still
    knows when each frame was presented::

        16666666                       # refresh period, ns
        0 0 0                          # idle slot
        1234567890123 1234567891123 1234567891200
        ...

    Returns the median frame interval converted to fps, plus jank from late frames.
    """
    out: Dict[str, Optional[float]] = {"fps_estimate": None, "frame_ms": None, "jank_percent": None}
    rows = []
    period = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 1 and parts[0].isdigit() and period is None:
            period = int(parts[0])
            continue
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            desired, actual, ready = (int(part) for part in parts)
            if actual > 0 and ready > 0:
                rows.append((actual, ready))
    if len(rows) < 2:
        return out
    rows.sort()
    intervals = [
        (rows[i + 1][0] - rows[i][0]) / 1e6  # ms
        for i in range(len(rows) - 1)
        if rows[i + 1][0] > rows[i][0]
    ]
    if not intervals:
        return out
    intervals.sort()
    median = intervals[len(intervals) // 2]
    if median <= 0:
        return out
    out["frame_ms"] = round(median, 2)
    out["fps_estimate"] = round(1000.0 / median, 1)
    # Deliberately no jank figure here: a presentation timestamp is not a
    # frame-deadline miss, and calling every 100 ms menu frame "100% janky" would
    # be misleading. gfxinfo keeps providing jank for apps that report it.
    return out


def parse_battery(text: str) -> Dict[str, Optional[float]]:
    """Battery level / temperature from ``dumpsys battery``."""
    level = _int(text, r"level")
    temp = _float(text, r"temperature:\s*(-?\d+)")
    return {
        "battery_level": level,
        "battery_temp_c": (temp / 10.0) if temp is not None else None,
    }


@dataclass
class MetricsSample:
    """One point in the performance timeline."""

    step: int = 0
    elapsed_s: float = 0.0
    fps_estimate: Optional[float] = None
    total_frames: Optional[int] = None
    janky_percent: Optional[float] = None
    p50_ms: Optional[float] = None
    p90_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    p99_ms: Optional[float] = None
    total_pss_kb: Optional[int] = None
    native_heap_kb: Optional[int] = None
    java_heap_kb: Optional[int] = None
    cpu_percent: Optional[float] = None
    battery_level: Optional[float] = None
    battery_temp_c: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def fill_sample(sample: MetricsSample, **fields: object) -> MetricsSample:
    for key, value in fields.items():
        if value is not None and hasattr(sample, key):
            setattr(sample, key, value)
    return sample


def frame_rate(prev_frames: Optional[int], frames: Optional[int], seconds: float) -> Optional[float]:
    """Frame rate between two gfxinfo snapshots (reset counters yield None)."""
    if prev_frames is None or frames is None or seconds <= 0:
        return None
    delta = frames - prev_frames
    if delta < 0:  # counter reset (activity restart) - skip this interval
        return None
    return round(delta / seconds, 1)
