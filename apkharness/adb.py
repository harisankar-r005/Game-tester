"""Thin, dependency-free wrapper around the Android Debug Bridge."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

PNG_SIG = b"\x89PNG\r\n\x1a\n"


class AdbError(RuntimeError):
    """Raised when adb is missing or a command fails."""


class AdbNotFound(AdbError):
    """Raised when no adb executable can be located."""


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    product: str = ""

    @property
    def online(self) -> bool:
        return self.state == "device"

    def to_dict(self) -> Dict[str, str]:
        return {"serial": self.serial, "state": self.state, "model": self.model, "product": self.product}


class Adb:
    """One adb endpoint (host or a specific device serial)."""

    def __init__(self, path: str = "adb", serial: Optional[str] = None, timeout: float = 120.0) -> None:
        self.path = path
        self.serial = serial or ""
        self.timeout = timeout

    # -- process plumbing --------------------------------------------------
    def _command(self) -> List[str]:
        resolved = self.path
        if os.path.sep not in resolved:
            found = shutil.which(resolved)
            if not found:
                raise AdbNotFound(
                    "adb was not found on PATH. Install Android platform-tools, or "
                    "pass --adb C:\\path\\to\\adb.exe (device testing only; the "
                    "simulator needs no adb)."
                )
            resolved = found
        elif not os.path.exists(resolved):
            raise AdbNotFound(f"adb executable not found: {resolved}")
        command = [resolved]
        if self.serial:
            command += ["-s", self.serial]
        return command

    def run(
        self, args: Sequence[str], timeout: Optional[float] = None, binary: bool = False
    ) -> subprocess.CompletedProcess:
        command = self._command() + list(args)
        try:
            return subprocess.run(
                command,
                capture_output=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover - platform dependent
            raise AdbNotFound(f"cannot execute adb: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb timed out after {timeout or self.timeout}s: {' '.join(args)[:120]}") from exc

    def text(self, args: Sequence[str], timeout: Optional[float] = None) -> str:
        result = self.run(args, timeout=timeout)
        out = result.stdout.decode("utf-8", "replace")
        err = result.stderr.decode("utf-8", "replace").strip()
        if result.returncode != 0 and err:
            raise AdbError(f"adb {' '.join(args)[:80]} failed: {err[:300]}")
        return out

    def popen(self, args: Sequence[str], stdout=None, stderr=None) -> subprocess.Popen:
        """Start a long-running adb command (used by screenrecord)."""
        command = self._command() + list(args)
        return subprocess.Popen(command, stdout=stdout, stderr=stderr)

    def pull(self, remote: str, local: str, timeout: float = 180.0) -> str:
        """Copy a file from the device."""
        return self.text(["pull", remote, local], timeout=timeout)

    def rm(self, remote: str) -> None:
        try:
            self.shell(f"rm -f {remote}")
        except AdbError:
            pass

    # -- host level --------------------------------------------------------
    @classmethod
    def version(cls, path: str = "adb") -> str:
        probe = cls(path=path)
        return probe.text(["version"]).strip()

    @classmethod
    def list_devices(cls, path: str = "adb") -> List[DeviceInfo]:
        probe = cls(path=path)
        raw = probe.text(["devices", "-l"])
        devices: List[DeviceInfo] = []
        for line in raw.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            fields = line.split()
            serial, state = fields[0], fields[1] if len(fields) > 1 else "unknown"
            model = product = ""
            for field in fields[2:]:
                if field.startswith("model:"):
                    model = field.split(":", 1)[1]
                elif field.startswith("product:"):
                    product = field.split(":", 1)[1]
            devices.append(DeviceInfo(serial=serial, state=state, model=model, product=product))
        return devices

    def wait_for_device(self, timeout: float = 120.0) -> None:
        self.run(["wait-for-device"], timeout=timeout)

    def shell(self, command: str, timeout: Optional[float] = None) -> str:
        return self.text(["shell", command], timeout=timeout)

    def dumpsys(self, service: str, *args: str) -> str:
        return self.shell(" ".join(["dumpsys", service, *args]))

    # -- package management ------------------------------------------------
    def install(self, apk: str, reinstall: bool = True, grant: bool = True) -> str:
        if not os.path.exists(apk):
            raise AdbError(f"APK not found: {apk}")
        args = ["install"]
        if reinstall:
            args.append("-r")
        if grant:
            args.append("-g")
        args.append(apk)
        result = self.run(args, timeout=max(self.timeout, 300))
        out = (result.stdout + result.stderr).decode("utf-8", "replace")
        if result.returncode != 0 or "Failure" in out or "Error" in out:
            raise AdbError(f"install failed: {out.strip()[:400]}")
        return out.strip()

    def installed_version(self, package: str) -> Dict[str, str]:
        """versionName/versionCode of the copy already on the phone ({} if not installed)."""
        try:
            raw = self.shell(f"dumpsys package {package}")
        except AdbError:
            return {}
        name = re.search(r"versionName=(\S+)", raw)
        code = re.search(r"versionCode=(\d+)", raw)
        if not code:
            return {}
        return {"version_name": name.group(1) if name else "", "version_code": code.group(1)}

    def uninstall(self, package: str) -> str:
        return self.text(["uninstall", package])

    def list_packages(self, user_only: bool = True) -> List[str]:
        flag = "-3" if user_only else ""
        raw = self.shell(f"pm list packages {flag}".strip())
        packages = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.split(":", 1)[1].strip())
        return sorted(packages)

    def resolve_launch_activity(self, package: str) -> str:
        """Best-effort launcher activity for a package."""
        for command in (
            f"cmd package resolve-activity --brief {package}",
            f"pm resolve-activity --brief {package}",
        ):
            try:
                raw = self.shell(command).strip().splitlines()
            except AdbError:
                continue
            for line in reversed(raw):
                candidate = line.strip()
                if "/" in candidate and " " not in candidate:
                    return candidate
        return ""

    def start_app(self, package: str, activity: str = "") -> str:
        """Launch an app; falls back to a monkey intent when no activity is known."""
        if not activity:
            activity = self.resolve_launch_activity(package)
        if activity:
            return self.shell(f"am start -W -n {activity}")
        return self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    def force_stop(self, package: str) -> str:
        return self.shell(f"am force-stop {package}")

    def pidof(self, package: str) -> Optional[int]:
        raw = self.shell(f"pidof {package}").strip()
        if not raw:
            return None
        first = raw.split()[0]
        try:
            return int(first)
        except ValueError:
            return None

    # -- logs --------------------------------------------------------------
    def clear_logcat(self) -> None:
        self.run(["logcat", "-c"])

    def logcat_dump(self, tail: int = 6000) -> str:
        return self.text(["logcat", "-d", "-v", "threadtime", "-t", str(tail)], timeout=max(self.timeout, 120))

    # -- screen ------------------------------------------------------------
    def screencap(self) -> bytes:
        """PNG of the current screen, with a pull fallback for flaky exec-out."""
        try:
            result = self.run(["exec-out", "screencap", "-p"], timeout=90)
            if result.returncode == 0 and result.stdout.startswith(PNG_SIG):
                return result.stdout
        except AdbError:
            pass
        remote = "/sdcard/apkharness_shot.png"
        self.shell(f"screencap -p {remote}", timeout=90)
        # A pull fallback needs a local file; keep it next to the caller's cwd
        # instead of the system temp dir, which some hardened environments block.
        staging = os.path.join(os.getcwd(), f".apkharness_tmp_{os.getpid()}_{int(time.time() * 1000)}")
        os.makedirs(staging, exist_ok=True)
        try:
            local = os.path.join(staging, "shot.png")
            self.text(["pull", remote, local], timeout=90)
            with open(local, "rb") as handle:
                data = handle.read()
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if not data.startswith(PNG_SIG):
            raise AdbError("screencap did not return a PNG")
        return data

    def screen_size(self) -> Tuple[int, int]:
        raw = self.shell("wm size")
        # "Physical size: 1080x2400" possibly followed by "Override size: 720x1600"
        size = (0, 0)
        for line in raw.splitlines():
            if ":" in line and "x" in line:
                value = line.split(":", 1)[1].strip()
                try:
                    width, height = value.split("x", 1)
                    size = (int(width), int(height))
                except ValueError:
                    continue
        return size

    # -- input -------------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None:
        self.shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}")

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(f"input swipe {int(x)} {int(y)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def key(self, keycode: int) -> None:
        self.shell(f"input keyevent {int(keycode)}")

    def text_input(self, value: str) -> None:
        escaped = value.replace(" ", "%s").replace("'", "\\'")
        self.shell(f"input text '{escaped}'")

    # -- ui ----------------------------------------------------------------
    def ui_dump(self, timeout: float = 12.0) -> str:
        """Accessibility tree of the current screen.

        ``--compressed`` skips the "wait for idle" dance that makes plain
        ``uiautomator dump`` hang for tens of seconds on animated game screens.
        Each call uses a fresh file so a timed-out dump can never return the
        previous screen's tree.
        """
        remote = f"/sdcard/apkharness_ui_{os.getpid()}_{int(time.time() * 1000)}.xml"
        try:
            self.shell(f"rm -f {remote}", timeout=10)
            result = self.shell(f"uiautomator dump --compressed {remote}", timeout=timeout)
            if "ERROR" in (result or "").upper():
                return ""
            return self.shell(f"cat {remote}", timeout=timeout)
        except AdbError:
            return ""
        finally:
            try:
                self.shell(f"rm -f {remote}", timeout=10)
            except AdbError:
                pass

    # -- misc --------------------------------------------------------------
    def model(self) -> str:
        try:
            return self.shell("getprop ro.product.model").strip()
        except AdbError:
            return ""

    def android_version(self) -> str:
        try:
            return self.shell("getprop ro.build.version.release").strip()
        except AdbError:
            return ""

    def battery(self) -> str:
        try:
            return self.dumpsys("battery")
        except AdbError:
            return ""

    def cpuinfo(self) -> str:
        try:
            return self.dumpsys("cpuinfo")
        except AdbError:
            return ""

    def gfxinfo(self, package: str) -> str:
        try:
            return self.dumpsys("gfxinfo", package)
        except AdbError:
            return ""

    def meminfo(self, package: str) -> str:
        try:
            return self.dumpsys("meminfo", package)
        except AdbError:
            return ""

    @staticmethod
    def parse_layer_names(listing: str) -> List[str]:
        """Extract real layer names from ``dumpsys SurfaceFlinger --list``.

        Modern Android wraps entries in ``RequestedLayerState{...}``; the name that
        ``--latency`` accepts is either ``Surface(name=...)`` or the raw
        ``SurfaceView[...]#id`` token.
        """
        names: List[str] = []
        for line in listing.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.search(r"Surface\(name=([^)]*)\)", line)
            if match:
                names.append(match.group(1))
                continue
            if "SurfaceView[" in line:
                token = line.split("RequestedLayerState{")[-1].split("}")[0]
                token = token.split(" parentId")[0].strip()
                if token:
                    names.append(token)
        return names

    def surfaceflinger_layers(self) -> List[str]:
        try:
            raw = self.shell("dumpsys SurfaceFlinger --list")
        except AdbError:
            return []
        return self.parse_layer_names(raw)

    def surfaceflinger_latency(self, package: str) -> str:
        """Latency data for the app surface that is actually presenting frames.

        A GL game exposes nothing useful through ``gfxinfo``; the ``(BLAST)``
        SurfaceView layer is the one with real presentation timestamps, so every
        candidate is probed and the richest one wins.
        """
        candidates = [layer for layer in self.surfaceflinger_layers() if package in layer]
        if not candidates:
            return ""
        best_text, best_rows = "", 0
        for layer in candidates:
            try:
                raw = self.shell(f'dumpsys SurfaceFlinger --latency "{layer}"')
            except AdbError:
                continue
            rows = 0
            for line in raw.splitlines()[1:]:
                parts = line.split()
                if len(parts) == 3 and parts[0].isdigit() and int(parts[1]) > 0:
                    rows += 1
            if rows > best_rows:
                best_text, best_rows = raw, rows
        return best_text

    def current_focus(self) -> str:
        try:
            raw = self.dumpsys("window")
        except AdbError:
            return ""
        for line in raw.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                return line.strip()
        return ""


def find_adb() -> Optional[str]:
    """Locate adb: PATH first, then the usual Android SDK install locations."""
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe") if local else "",
        os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
        os.path.join(os.environ.get("ANDROID_SDK_ROOT", ""), "platform-tools", "adb.exe"),
        r"C:\Android\platform-tools\adb.exe",
        r"C:\platform-tools\adb.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def wait_until(predicate, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Poll ``predicate`` until it is true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
