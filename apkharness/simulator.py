"""A deterministic fake device so the harness can be demoed and tested without
a phone, an emulator or an APK.

``SimDevice`` implements exactly the same interface as the adb backend: it
renders PNG screens, answers ``uiautomator`` dumps, streams threadtime logcat
lines and schedules a few realistic failures (Java crash, native crash, ANR).
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from typing import Deque, List, Optional, Tuple
from collections import deque

from . import logs as logmod
from . import metrics as metricmod
from .device import Device
from .png import encode_rgba

DEFAULT_PACKAGE = "com.example.neondrift"

SCREEN_COLORS = {
    "menu": (18, 24, 48),
    "garage": (30, 18, 52),
    "race": (10, 40, 44),
    "results": (44, 26, 12),
    "shop": (40, 12, 34),
    "settings": (16, 34, 26),
    "dead": (8, 8, 10),
    "anr": (30, 10, 12),
}

BUTTON_COLORS = [(240, 196, 64), (86, 204, 242), (236, 100, 120)]


@dataclass
class CrashPlan:
    """A scripted failure: (global step, kind, screen)."""

    step: int
    kind: str
    screen: str = ""


DEFAULT_PLAN = (
    CrashPlan(32, "java_crash", "garage"),
    CrashPlan(96, "native_crash", "race"),
    CrashPlan(150, "anr", "race"),
)


class SimDevice(Device):
    """Synthetic Android game with a seeded failure schedule."""

    name = "simulator"
    _CHECKPOINT_FIELDS = ("installed", "running", "screen", "pid", "step", "race_ticks", "anr_ticks",
                          "last_tap", "tap_step", "fired", "deaths", "_seq", "_tid", "_frames")

    def __init__(
        self,
        package: str = DEFAULT_PACKAGE,
        seed: int = 7,
        width: int = 270,
        height: int = 480,
        plan: Optional[List[CrashPlan]] = None,
        fps: float = 58.0,
    ) -> None:
        self.package = package
        self.random = random.Random(seed)
        self.width = width
        self.height = height
        self.plan = list(plan if plan is not None else DEFAULT_PLAN)
        self.fps = fps
        self.installed = False
        self.running = False
        self.screen = "menu"
        self.pid = 0
        self.step = 0
        self.race_ticks = 0
        self.anr_ticks = 0
        self.last_tap: Optional[Tuple[int, int]] = None
        self.tap_step = -99
        self.fired: List[str] = []
        self.deaths = 0
        self._buffer: Deque[logmod.LogLine] = deque(maxlen=4000)
        self._seq = 0
        self._tid = 4200
        self._started_at = time.time()
        self._frames = 0.0
        self._last_metrics_at: Optional[float] = None
        self._launch_at = time.monotonic()

    # -- Device interface --------------------------------------------------
    def checkpoint_state(self) -> dict:
        return {"state": {name: getattr(self, name) for name in self._CHECKPOINT_FIELDS},
                "random": self.random.getstate(), "logs": [asdict(line) for line in self._buffer]}

    def restore_checkpoint(self, checkpoint: dict) -> None:
        for name in self._CHECKPOINT_FIELDS:
            setattr(self, name, checkpoint["state"][name])
        if self.last_tap is not None:
            self.last_tap = tuple(self.last_tap)
        version, state, extra = checkpoint["random"]
        self.random.setstate((version, tuple(state), extra))
        self._buffer.extend(logmod.LogLine(**line) for line in checkpoint.get("logs", []))

    @property
    def serial(self) -> str:
        return f"simulator-{self.package.split('.')[-1]}"

    def check_input(self):
        return True, ""

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "serial": self.serial,
            "model": "Simulated Pixel 7",
            "android": "14 (simulated)",
            "screen": f"{self.width}x{self.height}",
        }

    def install(self, apk: str) -> str:
        self.installed = True
        self._log("PackageManager", "I", f"Installing {apk} (simulated)")
        self._log("PackageManager", "I", "Success")
        return "Success (simulated)"

    def launch(self, package: str, activity: str = "") -> str:
        if not self.installed:
            raise RuntimeError("simulated app is not installed")
        self.package = package or self.package
        self.running = True
        self.screen = "menu"
        self.race_ticks = 0
        self.anr_ticks = 0
        self.pid = 4000 + self.random.randint(1, 900)
        self._tid = self.pid + 100
        self._frames = 0.0
        self._last_metrics_at = None
        self._log("ActivityManager", "I", f"Start proc {self.pid}:{self.package}/u0a142 for activity "
                                           f"{self.package}/.MainActivity")
        self._log("ActivityTaskManager", "I", f"Displayed {self.package}/.MainActivity: +412ms")
        self._log("Unity", "I", "Initialize engine version: 2022.3.18f1 (simulated)")
        self._log("Choreographer", "I", "Skipped 12 frames!  The application may be doing too much work "
                                        "on its main thread.")
        return f"Starting: Intent {{ cmp={self.package}/.MainActivity }} (simulated)"

    def force_stop(self, package: str) -> None:
        if self.running:
            self._log("ActivityManager", "I", f"Force stopping {package} user=0: from pid 1000")
        self.running = False
        self.pid = 0

    def alive(self, package: str) -> bool:
        return self.running and self.pid > 0

    def screen_size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def screenshot(self) -> Optional[bytes]:
        if not self.running:
            return encode_rgba(self.width, self.height, self._paint_dead())
        if self.anr_ticks > 0:
            return encode_rgba(self.width, self.height, self._paint_anr())
        return encode_rgba(self.width, self.height, self._paint())

    def ui_dump(self) -> str:
        if not self.running:
            return ""
        if self.screen == "race":
            # Games draw an opaque surface: only the root view is exposed.
            return (
                '<hierarchy rotation="0"><node index="0" text="" resource-id="" '
                'class="android.widget.FrameLayout" package="' + self.package + '" '
                f'content-desc="" clickable="false" enabled="true" bounds="[0,0][{self.width},{self.height}]" '
                '/></hierarchy>'
            )
        labels = {
            "menu": [("Play", 0, 1), ("Garage", 1, 2), ("Shop", 2, 3)],
            "garage": [("Back", 0, 1), ("Race", 2, 3)],
            "shop": [("Buy", 1, 2)],
            "settings": [("Back", 0, 1)],
            "results": [("Continue", 1, 2), ("Menu", 2, 3)],
        }.get(self.screen, [])
        nodes = []
        for index, (label, col, row) in enumerate(labels):
            x1 = int(self.width * 0.08) + col * int(self.width * 0.3)
            y1 = int(self.height * 0.09) + row * int(self.height * 0.12)
            nodes.append(
                f'<node index="{index}" text="{label}" resource-id="{self.package}:id/'
                f'{label.lower()}" class="android.widget.Button" package="{self.package}" '
                f'content-desc="{label} button" clickable="true" enabled="true" '
                f'focused="false" scrollable="false" '
                f'bounds="[{x1},{y1}][{x1 + int(self.width * 0.22)},{y1 + int(self.height * 0.06)}]" />'
            )
        return '<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"

    def poll_logs(self) -> List[logmod.LogLine]:
        lines = list(self._buffer)
        self._buffer.clear()
        return lines

    def metrics(self, package: str) -> metricmod.MetricsSample:
        sample = metricmod.MetricsSample()
        now = time.monotonic()
        dt = now - self._last_metrics_at if self._last_metrics_at else 0.0
        self._last_metrics_at = now
        target = self.fps - (min(12.0, self.race_ticks * 0.5) if self.screen == "race" else 0.0)
        self._frames += max(0.0, dt) * target
        sample.total_frames = int(self._frames)
        sample.janky_percent = round(1.5 + (self.race_ticks * 1.1 if self.screen == "race" else 0.0), 1)
        base_fps = target
        sample.fps_estimate = round(max(18.0, base_fps + self.random.uniform(-2.5, 2.5)), 1)
        sample.p50_ms = round(1000.0 / max(sample.fps_estimate, 1), 1)
        sample.p90_ms = round(sample.p50_ms * 1.8, 1)
        sample.p95_ms = round(sample.p50_ms * 2.4, 1)
        sample.p99_ms = round(sample.p50_ms * 4.0, 1)
        sample.total_pss_kb = 180_000 + self.step * 640 + self.race_ticks * 900
        sample.native_heap_kb = 92_000 + self.step * 210
        sample.java_heap_kb = 41_000 + self.step * 40
        sample.cpu_percent = round(min(96.0, 22.0 + self.race_ticks * 2.2), 1)
        sample.battery_level = 87 - self.step // 40
        sample.battery_temp_c = round(31.0 + self.race_ticks * 0.25, 1)
        return sample

    # -- input -------------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self.step += 1
        self.last_tap = (x, y)
        self.tap_step = self.step
        if not self.running:
            return
        if self.anr_ticks > 0:
            self._log("InputDispatcher", "W", f"Window {self.package}/.MainActivity is unresponsive: "
                                              f"dropping event at ({x},{y})")
            return
        if self.screen == "menu":
            ratio = y / max(self.height, 1)
            if ratio > 0.62:
                self.screen = "race"
                self.race_ticks = 0
                self._log("Unity", "I", "Loading scene: Race")
            elif ratio > 0.32:
                self.screen = "garage"
                self._log("Unity", "I", "Loading scene: Garage")
            else:
                self.screen = "shop"
                self._log("Unity", "I", "Loading scene: Shop")
        elif self.screen == "garage":
            if x > self.width * 0.66:
                self.screen = "race"
                self.race_ticks = 0
                self._log("Unity", "I", "Loading scene: Race")
            else:
                self.screen = "menu"
        elif self.screen == "race":
            self.race_ticks += 1
            if self.race_ticks % 5 == 0:
                self._log("Choreographer", "I", f"Skipped {self.race_ticks * 3} frames!  The application "
                                                "may be doing too much work on its main thread.")
        elif self.screen == "shop":
            self.screen = "menu"
        elif self.screen == "settings":
            self.screen = "menu"
        elif self.screen == "results":
            self.screen = "menu"

    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None:
        self.tap(x, y)

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.step += 1
        self.last_tap = (x2, y2)
        self.tap_step = self.step
        if not self.running or self.anr_ticks > 0:
            return
        if self.screen == "race":
            self.race_ticks += 1
        elif abs(y2 - y) > self.height // 4:
            self._log("Unity", "I", "Scroll gesture handled")

    def key(self, keycode: int) -> None:
        self.step += 1
        if not self.running:
            return
        if keycode == 4:  # back
            if self.screen == "menu":
                # Android keeps the process alive when the last activity is popped.
                self._log("ActivityTaskManager", "I", "Activity pause timeout: no activity to resume")
                self._log("ActivityManager", "I", "Move to background: back key")
            else:
                self.screen = "menu"
                self._log("Unity", "I", "Loading scene: Menu")
        elif keycode == 3:
            self._log("ActivityManager", "I", "Move to background: home key")

    def text_input(self, value: str) -> None:
        self._log("InputMethod", "I", f"Commit text: {value[:32]!r}")

    # -- failure schedule --------------------------------------------------
    def tick(self) -> None:
        """Advance simulated time; fires the next planned failure when due."""
        if not self.running:
            return
        self.step += 1
        if self.anr_ticks > 0:
            self.anr_ticks -= 1
            if self.anr_ticks == 0:
                self._log("ActivityManager", "I", f"Force finishing activity {self.package}/.MainActivity")
                self.screen = "menu"
        for plan in self.plan:
            token = f"{plan.kind}@{plan.step}"
            if plan.step <= self.step and token not in self.fired:
                self.fired.append(token)
                self._trigger(plan.kind)
                break

    def _trigger(self, kind: str) -> None:
        if kind == "java_crash":
            self._java_crash()
        elif kind == "native_crash":
            self._native_crash()
        elif kind == "anr":
            self._anr()
        elif kind == "process_death":
            self._log("ActivityManager", "I", f"Process {self.package} (pid {self.pid}) has died: "
                                              "fg TOP")
            self.running = False
            self.pid = 0

    def _java_crash(self) -> None:
        tid = self._tid
        self._emit(tid, "E", "AndroidRuntime", "FATAL EXCEPTION: main")
        self._emit(tid, "E", "AndroidRuntime", f"Process: {self.package}, PID: {self.pid}")
        self._emit(tid, "E", "AndroidRuntime",
                   "java.lang.NullPointerException: Attempt to invoke virtual method "
                   "'int com.neondrift.Player.getHealth()' on a null object reference")
        for frame in (
            "at com.neondrift.game.RaceController.update(RaceController.java:214)",
            "at com.neondrift.game.GameLoop.tick(GameLoop.java:88)",
            "at android.opengl.GLSurfaceView$GLThread.guardedRun(GLSurfaceView.java:1571)",
            "at android.opengl.GLSurfaceView$GLThread.run(GLSurfaceView.java:1270)",
        ):
            self._emit(tid, "E", "AndroidRuntime", "\t" + frame)
        self._emit(tid, "E", "AndroidRuntime", "Force finishing activity "
                                               f"{self.package}/.MainActivity")
        self.running = False
        self.deaths += 1
        self.pid = 0

    def _native_crash(self) -> None:
        tid = self._tid + 7
        self._emit(tid, "F", "libc", f"Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0 "
                                    f"in tid {tid} (RenderThread), pid {self.pid} (neondrift)")
        self._emit(tid, "F", "DEBUG", "*** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***")
        self._emit(tid, "F", "DEBUG", "Build fingerprint: 'google/sdk_gphone64_x86_64/"
                                      "sdk_gphone64_x86_64:14/UE1A.230829.036:userdebug/dev-keys'")
        self._emit(tid, "F", "DEBUG", "signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0")
        self._emit(tid, "F", "DEBUG", "backtrace:")
        for index, (pc, symbol) in enumerate(
            (
                ("00000000001a2b3c", "CrashInRenderThread+28"),
                ("00000000001a2f10", "RenderScene+96"),
                ("0000000000198e44", "GameLoop::Frame+412"),
                ("00000000000f2210", "UnityMain+1204"),
            )
        ):
            self._emit(tid, "F", "DEBUG",
                       f"      #{index:02d} pc {pc}  /data/app/~~x==/{self.package}-1/lib/arm64/"
                       f"libunity.so ({symbol})")
        self._emit(tid, "I", "Zygote", f"Process {self.pid} exited due to signal 11 (SIGSEGV)")
        self.running = False
        self.deaths += 1
        self.pid = 0

    def _anr(self) -> None:
        self.anr_ticks = 3
        self._emit(self._tid, "E", "ActivityManager",
                   f"ANR in {self.package} ({self.package}/.MainActivity)")
        self._emit(self._tid, "E", "ActivityManager", f"PID: {self.pid}")
        self._emit(self._tid, "E", "ActivityManager",
                   "Reason: Input dispatching timed out (Waiting to send key event because the "
                   "focused window has not finished processing all of the input events that were "
                   "previously delivered to it.)")
        self._emit(self._tid, "E", "ActivityManager", "Load: 3.42 / 3.11 / 2.87")
        self._emit(self._tid, "E", "ActivityManager", "----- Output of 'dumpsys activity activities' -----")

    # -- log plumbing ------------------------------------------------------
    def _emit(self, tid: int, level: str, tag: str, msg: str) -> None:
        self._seq += 1
        now = time.localtime()
        stamp = time.strftime("%m-%d %H:%M:%S", now) + f".{(int(time.time() * 1000) % 1000):03d}"
        raw = f"{stamp} {self.pid or 1000:5d} {tid:5d} {level} {tag:8s}: {msg}"
        self._buffer.append(
            logmod.LogLine(ts=stamp, pid=self.pid or 1000, tid=tid, level=level, tag=tag, msg=msg, raw=raw)
        )

    def _log(self, tag: str, level: str, msg: str) -> None:
        self._emit(self._tid, level, tag, msg)

    # -- rendering ---------------------------------------------------------
    def _paint_base(self, color: Tuple[int, int, int]) -> bytearray:
        width, height = self.width, self.height
        buffer = bytearray(width * height * 4)
        for y in range(height):
            shade = 1.0 - (y / height) * 0.35
            row = bytes(
                (
                    int(color[0] * shade),
                    int(color[1] * shade),
                    int(color[2] * shade),
                    255,
                )
            ) * width
            buffer[y * width * 4 : (y + 1) * width * 4] = row
        return buffer

    def _rect(self, buffer: bytearray, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int]) -> None:
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(self.width, x2), min(self.height, y2)
        if x2 <= x1 or y2 <= y1:
            return
        pixel = bytes((color[0], color[1], color[2], 255))
        for y in range(y1, y2):
            start = (y * self.width + x1) * 4
            end = start + (x2 - x1) * 4
            buffer[start:end] = pixel * (x2 - x1)

    def _layout(self) -> List[Tuple[int, int, int, int, Tuple[int, int, int]]]:
        """Per-screen widget layout; deliberately different between screens.

        Differences matter: the harness decides "new screen" from a 64-bit
        perceptual hash, so two screens must differ in *structure*, not just hue.
        """
        w, h = self.width, self.height
        if self.screen == "menu":
            return [
                (10, int(h * 0.30), w - 10, int(h * 0.30) + 26, BUTTON_COLORS[0]),
                (10, int(h * 0.50), w - 10, int(h * 0.50) + 26, BUTTON_COLORS[1]),
                (10, int(h * 0.70), w - 10, int(h * 0.70) + 26, BUTTON_COLORS[2]),
            ]
        if self.screen == "garage":
            return [
                (8, int(h * 0.22), int(w * 0.45), int(h * 0.22) + 30, BUTTON_COLORS[1]),
                (int(w * 0.55), int(h * 0.60), w - 8, int(h * 0.60) + 44, BUTTON_COLORS[0]),
            ]
        if self.screen == "shop":
            return [
                (10, 40, int(w * 0.45), 76, BUTTON_COLORS[2]),
                (int(w * 0.55), 40, w - 10, 76, BUTTON_COLORS[1]),
                (10, 100, int(w * 0.45), 136, BUTTON_COLORS[1]),
                (int(w * 0.55), 100, w - 10, 136, BUTTON_COLORS[0]),
            ]
        if self.screen == "settings":
            return [
                (10, 30, w - 10, 54, BUTTON_COLORS[1]),
                (10, 70, w - 30, 86, BUTTON_COLORS[0]),
                (10, 110, w - 30, 126, BUTTON_COLORS[0]),
            ]
        if self.screen == "results":
            return [
                (int(w * 0.2), int(h * 0.55), int(w * 0.8), int(h * 0.55) + 30, BUTTON_COLORS[0]),
                (int(w * 0.3), int(h * 0.78), int(w * 0.7), int(h * 0.78) + 18, BUTTON_COLORS[2]),
            ]
        return []

    def _paint(self) -> bytes:
        color = SCREEN_COLORS.get(self.screen, (20, 20, 20))
        buffer = self._paint_base(color)
        # header band
        self._rect(buffer, 0, 0, self.width, 12, (min(color[0] + 40, 255), min(color[1] + 40, 255), 90))
        for x1, y1, x2, y2, button_color in self._layout():
            self._rect(buffer, x1, y1, x2, y2, button_color)
            self._rect(buffer, x1, y1, x2, y1 + 3, (255, 255, 255))
        if self.screen == "race":
            self._rect(buffer, 0, self.height - 26, self.width, self.height, (14, 16, 18))
            for lane in range(4):
                x = 8 + lane * 24
                self._rect(buffer, x, self.height - 22, x + 12, self.height - 8, (240, 220, 90))
            car_x = 10 + (self.step * 9) % max(1, self.width - 24)
            self._rect(buffer, car_x, self.height - 56, car_x + 18, self.height - 32, (250, 120, 90))
        if self.last_tap and self.step - self.tap_step < 2:
            x, y = self.last_tap
            radius = max(6, self.width // 20)
            self._rect(buffer, max(0, x - radius), max(0, y - radius),
                       min(self.width, x + radius), min(self.height, y + radius), (255, 255, 255))
        return bytes(buffer)

    def _paint_dead(self) -> bytes:
        buffer = self._paint_base(SCREEN_COLORS["dead"])
        self._rect(buffer, self.width // 2 - 6, self.height - 14, self.width // 2 + 6, self.height - 6,
                   (60, 60, 70))
        return bytes(buffer)

    def _paint_anr(self) -> bytes:
        buffer = self._paint_base(SCREEN_COLORS["anr"])
        self._rect(buffer, 8, 40, self.width - 8, 120, (70, 22, 26))
        self._rect(buffer, 8, 40, self.width - 8, 44, (240, 80, 80))
        return bytes(buffer)

    def interrupt(self, kind: str, package: str, activity: str = "") -> str:
        """Simulated lifecycle events. The demo game mishandles state restore once,
        so a kill_restore shows what a real lifecycle bug looks like in the report."""
        if not self.running:
            return "skipped: app not running"
        self._log("ActivityManager", "I", f"interruption ({kind}) on {self.package} (simulated)")
        if kind == "kill_restore" and "restore" not in self.fired:
            self.fired.append("restore")
            self._emit(self._tid, "E", "AndroidRuntime", "FATAL EXCEPTION: main")
            self._emit(self._tid, "E", "AndroidRuntime", f"Process: {self.package}, PID: {self.pid}")
            self._emit(self._tid, "E", "AndroidRuntime",
                       "java.lang.IllegalStateException: Can not perform this action after onSaveInstanceState")
            self._emit(self._tid, "E", "AndroidRuntime",
                       "\tat com.neondrift.ui.ShopFragment.onResume(ShopFragment.java:57)")
            self.running = False
            self.pid = 0
            self.deaths += 1
            return "killed in background → crashed on restore (simulated)"
        if kind == "airplane":
            self._log("ConnectivityManager", "W", "Unable to resolve host \"api.neondrift.example\" (simulated)")
        return f"{kind} ok (simulated)"

    def startup_probe(self, package: str, activity: str = "", runs: int = 3) -> dict:
        from .stress import summarize_startup

        cold = [int(1450 + self.random.uniform(-120, 160)) for _ in range(max(1, runs))]
        warm = [int(380 + self.random.uniform(-40, 60)) for _ in range(max(1, runs))]
        return summarize_startup(cold, warm)

    def close(self) -> None:
        self.running = False
