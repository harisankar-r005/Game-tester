"""Real device screen recording through ``adb shell screenrecord``.

Frame-by-frame ``screencap`` is fine for evidence, but it is slow (each capture
costs 100-400 ms) and cannot show motion. For a real game on a real phone the
harness can ask the device itself to encode H.264 while it is being driven:

    recorder = ScreenRecorder(adb, remote="/sdcard/apkharness_screen.mp4")
    recorder.start()          # runs in the background
    ... run the test ...
    path = recorder.stop_and_pull("session.mp4")   # finalise + pull

``screenrecord`` stops itself after ``--time-limit`` seconds (180 is the maximum
the platform accepts), so long sessions are split into numbered segments which
are concatenated only if ``ffmpeg`` is available; otherwise the first segment is
kept and the UI reports the truncation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import List, Optional

from .adb import Adb, AdbError

MAX_SEGMENT_SECONDS = 180


class ScreenRecorder:
    """Background screenrecord on a device, with a safe stop/pull."""

    def __init__(
        self,
        adb: Adb,
        remote: str = "/sdcard/apkharness_screen.mp4",
        bitrate: int = 8_000_000,
        time_limit: int = MAX_SEGMENT_SECONDS,
        size: str = "",
    ) -> None:
        self.adb = adb
        self.remote = remote
        self.bitrate = bitrate
        self.time_limit = max(5, min(int(time_limit), MAX_SEGMENT_SECONDS))
        self.size = size
        self.process: Optional[subprocess.Popen] = None
        self.started_at: float = 0.0
        self.segments: List[str] = []
        self.error: str = ""

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        """Kick off the recording; returns False when the device refuses."""
        try:
            self.adb.rm(self.remote)
            args = [
                "shell", "screenrecord",
                "--bit-rate", str(self.bitrate),
                "--time-limit", str(self.time_limit),
            ]
            if self.size:
                args += ["--size", self.size]
            args.append(self.remote)
            self.process = self.adb.popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.started_at = time.time()
            self.segments = [self.remote]
            # screenrecord exits immediately when the device cannot record
            time.sleep(1.2)
            if self.process.poll() is not None and self.process.returncode not in (0, None):
                self.error = f"screenrecord exited with code {self.process.returncode}"
                self.process = None
                return False
            return True
        except (AdbError, OSError) as exc:
            self.error = str(exc)
            self.process = None
            return False

    def stop(self, timeout: float = 20.0) -> None:
        """Ask the device to finalise the file (SIGINT), then reap the adb shell."""
        if self.process is None:
            return
        try:
            self.adb.shell("pkill -INT screenrecord")
        except AdbError:
            pass
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:  # pragma: no cover - device dependent
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        finally:
            self.process = None

    def stop_and_pull(self, local_path: str) -> Optional[str]:
        """Finalise, pull the file and clean up the device copy."""
        self.stop()
        if not self.remote:
            return None
        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        try:
            self.adb.pull(self.remote, local_path)
        except AdbError as exc:
            self.error = f"pull failed: {exc}"
            return None
        finally:
            self.adb.rm(self.remote)
        if not os.path.exists(local_path) or os.path.getsize(local_path) < 4096:
            self.error = "screenrecord produced no usable video"
            return None
        return local_path

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def describe(self) -> dict:
        return {
            "remote": self.remote,
            "bitrate": self.bitrate,
            "time_limit": self.time_limit,
            "running": self.running,
            "error": self.error,
        }


def container_ready() -> bool:
    """True when ffmpeg can mux segments (optional)."""
    return shutil.which("ffmpeg") is not None
