"""Device abstraction shared by the adb backend and the built-in simulator."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from . import logs as logmod
from . import metrics as metricmod
from .actions import Action, ActionError
from .adb import Adb, AdbError
from .png import dimensions, hash_from_bytes
from .ui import Node, parse_ui


def phone_gone(exc: BaseException) -> bool:
    """True when an adb error means the phone is unplugged/offline, not that a command failed."""
    text = str(exc).lower()
    return any(word in text for word in ("not found", "no devices", "device offline", "error: closed",
                                         "unauthorized", "no emulators", "device disconnected", "transport error"))


class DeviceUnavailable(RuntimeError):
    """Raised when the device cannot be reached at all."""


class InputBlocked(RuntimeError):
    """Raised when the device refuses injected input events (e.g. MIUI)."""


INPUT_HINT = (
    "The phone refuses injected touches (SecurityException: INJECT_EVENTS). "
    "On Xiaomi/Redmi/POCO: Settings > Additional settings > Developer options > "
    "enable 'USB debugging (Security settings)' (it is a separate toggle from USB "
    "debugging and may ask you to sign in). Then unplug/replug the cable and press "
    "Refresh. On Samsung: enable 'USB debugging' and disable 'Secure input'. "
    "Alternatively run the test on an emulator."
)


@dataclass
class Observation:
    """Everything the policy gets to see at one step."""

    step: int = 0
    elapsed_s: float = 0.0
    screenshot: Optional[bytes] = None
    phash: Optional[int] = None
    ui_nodes: List[Node] = field(default_factory=list)
    logs: List[logmod.LogLine] = field(default_factory=list)
    metrics: metricmod.MetricsSample = field(default_factory=metricmod.MetricsSample)
    alive: bool = True
    focus: str = ""
    screen_size: Tuple[int, int] = (0, 0)
    screen_key: Optional[int] = None

    @property
    def width(self) -> int:
        return self.screen_size[0]

    @property
    def height(self) -> int:
        return self.screen_size[1]

    def log_excerpt(self, limit: int = 12) -> str:
        return logmod.format_for_prompt(self.logs, limit)


class Device(ABC):
    """Minimal surface the runner needs; two implementations ship today."""

    name = "device"

    @property
    @abstractmethod
    def serial(self) -> str: ...

    @abstractmethod
    def install(self, apk: str) -> str: ...

    @abstractmethod
    def launch(self, package: str, activity: str = "") -> str: ...

    @abstractmethod
    def force_stop(self, package: str) -> None: ...

    @abstractmethod
    def alive(self, package: str) -> bool: ...

    @abstractmethod
    def screenshot(self) -> Optional[bytes]: ...

    @abstractmethod
    def ui_dump(self) -> str: ...

    @abstractmethod
    def poll_logs(self) -> List[logmod.LogLine]: ...

    @abstractmethod
    def metrics(self, package: str) -> metricmod.MetricsSample: ...

    @abstractmethod
    def screen_size(self) -> Tuple[int, int]: ...

    @abstractmethod
    def tap(self, x: int, y: int) -> None: ...

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None: ...

    @abstractmethod
    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...

    @abstractmethod
    def key(self, keycode: int) -> None: ...

    @abstractmethod
    def text_input(self, value: str) -> None: ...

    def describe(self) -> Dict[str, str]:
        return {"backend": self.name, "serial": self.serial}

    def check_input(self) -> Tuple[bool, str]:
        """Can the harness actually send taps to this device?"""
        return True, ""

    def interrupt(self, kind: str, package: str, activity: str = "") -> str:
        """Perform a real-life interruption (see :mod:`apkharness.stress`)."""
        return f"skipped: {self.name} does not support interruptions"

    def startup_probe(self, package: str, activity: str = "", runs: int = 3) -> dict:
        """Cold/warm start timing; empty when the backend cannot measure it."""
        return {}

    def close(self) -> None:
        """Release resources; safe to call twice."""


class AdbDevice(Device):
    """Device backed by a real adb connection."""

    name = "adb"

    def __init__(self, adb: Optional[Adb] = None, serial: str = "", adb_path: str = "adb") -> None:
        self.adb = adb or Adb(path=adb_path, serial=serial or None)
        self._serial = serial or getattr(self.adb, "serial", "") or "default"
        self._seen: Deque[Tuple[str, int, int, str]] = deque(maxlen=20000)
        self._size: Optional[Tuple[int, int]] = None
        self._model = ""
        self._ui_failures = 0
        self.ui_enabled = True

    @property
    def serial(self) -> str:
        return self._serial

    def install(self, apk: str) -> str:
        return self.adb.install(apk)

    def launch(self, package: str, activity: str = "") -> str:
        self.adb.clear_logcat()
        return self.adb.start_app(package, activity)

    def force_stop(self, package: str) -> None:
        self.adb.force_stop(package)

    def alive(self, package: str) -> bool:
        try:
            return self.adb.pidof(package) is not None
        except AdbError as exc:
            if phone_gone(exc):
                # the cable/phone is gone - that is not the game dying
                raise DeviceUnavailable(str(exc)) from exc
            return False

    def screenshot(self) -> Optional[bytes]:
        try:
            shot = self.adb.screencap()
        except (AdbError, DeviceUnavailable):
            return None
        # wm size can report portrait dimensions even when the game is in landscape.
        self._size = dimensions(shot) or self._size
        return shot

    def ui_dump(self) -> str:
        if not self.ui_enabled:
            return ""
        # Unity/GL screens return a layout with no buttons, and a dump costs ~4 s on many
        # phones. After 3 empty layouts in a row, only look every 6th time (menus still found).
        self._ui_calls = getattr(self, "_ui_calls", 0) + 1
        empty_streak = getattr(self, "_ui_empty", 0)
        if empty_streak >= 3 and self._ui_calls % 6:
            return ""
        try:
            xml = self.adb.ui_dump()
        except (AdbError, DeviceUnavailable, OSError):
            xml = ""
        if xml and "<hierarchy" in xml:
            self._ui_failures = 0
            useful = 'clickable="true"' in xml or re.search(r'text="[^"]+"', xml)
            self._ui_empty = 0 if useful else empty_streak + 1
            return xml
        self._ui_failures += 1
        if self._ui_failures >= 4:
            # Games often expose nothing; stop paying the dump timeout every step.
            self.ui_enabled = False
        return ""

    def poll_logs(self) -> List[logmod.LogLine]:
        try:
            raw = self.adb.logcat_dump()
        except AdbError:
            return []
        fresh: List[logmod.LogLine] = []
        for line in logmod.parse_lines(raw):
            key = (line.ts, line.pid, line.tid, line.msg)
            if key in self._seen:
                continue
            self._seen.append(key)
            fresh.append(line)
        return fresh

    def remember_logged_lines(self, lines: List[logmod.LogLine]) -> None:
        self._seen.extend((line.ts, line.pid, line.tid, line.msg) for line in lines)

    def metrics(self, package: str) -> metricmod.MetricsSample:
        sample = metricmod.MetricsSample()
        try:
            metricmod.fill_sample(sample, **metricmod.parse_gfxinfo(self.adb.gfxinfo(package)))
            metricmod.fill_sample(sample, **metricmod.parse_meminfo(self.adb.meminfo(package)))
            metricmod.fill_sample(sample, **metricmod.parse_cpuinfo(self.adb.cpuinfo(), package))
            metricmod.fill_sample(sample, **metricmod.parse_battery(self.adb.battery()))
            if sample.fps_estimate is None:
                latency = self.adb.surfaceflinger_latency(package)
                if latency:
                    metricmod.fill_sample(sample, **metricmod.parse_surfaceflinger_latency(latency))
        except AdbError:
            pass
        return sample

    def screen_size(self) -> Tuple[int, int]:
        if self._size is None or self._size == (0, 0):
            try:
                self._size = self.adb.screen_size()
            except AdbError:
                self._size = (1080, 1920)
        return self._size

    def tap(self, x: int, y: int) -> None:
        self.adb.tap(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None:
        self.adb.long_press(x, y, duration_ms)

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.adb.swipe(x, y, x2, y2, duration_ms)

    def key(self, keycode: int) -> None:
        self.adb.key(keycode)

    def text_input(self, value: str) -> None:
        self.adb.text_input(value)

    def check_input(self) -> Tuple[bool, str]:
        """Probe input injection; MIUI and some OEMs block it by default."""
        try:
            result = self.adb.run(["shell", "input", "keyevent", "0"], timeout=15)
        except AdbError as exc:
            return False, f"could not probe input: {exc}"
        stderr = result.stderr.decode("utf-8", "replace")
        if "INJECT_EVENTS" in stderr or "SecurityException" in stderr:
            return False, INPUT_HINT
        if result.returncode != 0 and "Unknown" not in stderr:
            return False, f"input probe failed: {stderr.strip()[:200]}"
        return True, ""

    def interrupt(self, kind: str, package: str, activity: str = "") -> str:
        from .stress import adb_interrupt

        return adb_interrupt(self.adb, kind, package, activity)

    def startup_probe(self, package: str, activity: str = "", runs: int = 3) -> dict:
        from .stress import adb_startup

        return adb_startup(self.adb, package, activity, runs)

    def describe(self) -> Dict[str, str]:
        info = {"backend": self.name, "serial": self._serial}
        try:
            self._model = self._model or self.adb.model()
            info["model"] = self._model
            info["android"] = self.adb.android_version()
        except AdbError:
            pass
        width, height = self.screen_size()
        info["screen"] = f"{width}x{height}"
        return info


def apply_action(device: Device, action: Action) -> None:
    """Translate an :class:`Action` into device input."""
    if action.type == "tap":
        device.tap(action.x, action.y)
    elif action.type == "long_press":
        device.long_press(action.x, action.y, action.duration_ms or 900)
    elif action.type == "swipe":
        device.swipe(action.x, action.y, action.x2, action.y2, action.duration_ms or 300)
    elif action.type == "key":
        device.key(action.keycode)
    elif action.type == "back":
        device.key(action.keycode or 4)
    elif action.type == "home":
        device.key(action.keycode or 3)
    elif action.type == "text":
        device.text_input(action.text)
    elif action.type == "wait":
        time.sleep(max(0, action.duration_ms) / 1000.0)
    else:  # pragma: no cover - Action validates already
        raise ActionError(f"cannot apply action type {action.type!r}")


def observe(
    device: Device,
    step: int,
    elapsed_s: float,
    package: str,
    want_screenshot: bool = True,
    want_ui: bool = True,
    want_metrics: bool = True,
) -> Observation:
    """Grab one full observation from a device."""
    alive = device.alive(package)
    # Real devices can rotate between saved frames, so refresh the touch bounds on every step.
    frame = device.screenshot() if want_screenshot or isinstance(device, AdbDevice) else None
    shot = frame if want_screenshot else None
    ui_xml = device.ui_dump() if want_ui else ""
    nodes = parse_ui(ui_xml)
    samples = device.metrics(package) if want_metrics else metricmod.MetricsSample()
    return Observation(
        step=step,
        elapsed_s=elapsed_s,
        screenshot=shot,
        phash=hash_from_bytes(shot) if shot else None,
        ui_nodes=nodes,
        metrics=samples,
        alive=alive,
        screen_size=device.screen_size(),
    )
