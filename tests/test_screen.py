"""Screen recording tests with a stubbed adb transport (no device needed)."""

import os
import shutil
import unittest
from unittest import mock

from apkharness.screen import MAX_SEGMENT_SECONDS, ScreenRecorder

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(SCRATCH, exist_ok=True)


class FakeProc:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode or 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakeAdb:
    """Records commands; simulates a device that has a video file."""

    def __init__(self, video_bytes=b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192, fail=False):
        self.calls = []
        self.remote_payload = video_bytes
        self.fail = fail
        self.removed = []

    def rm(self, remote):
        self.calls.append(("rm", remote))
        self.removed.append(remote)

    def shell(self, cmd):
        self.calls.append(("shell", cmd))
        return ""

    def popen(self, args, stdout=None, stderr=None):
        self.calls.append(("popen", list(args)))
        return FakeProc(returncode=1 if self.fail else None)

    def pull(self, remote, local):
        self.calls.append(("pull", remote, local))
        if not self.remote_payload:
            raise AssertionError("nothing to pull")
        os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
        with open(local, "wb") as handle:
            handle.write(self.remote_payload)
        return "1 file pulled"


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(SCRATCH, f"rec_{os.getpid()}")
        os.makedirs(self.dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_start_builds_screenrecord_command(self):
        adb = FakeAdb()
        recorder = ScreenRecorder(adb, time_limit=90, bitrate=6_000_000)
        with mock.patch("apkharness.screen.time.sleep"):
            self.assertTrue(recorder.start())
        popen_args = next(args for kind, args in adb.calls if kind == "popen")
        self.assertIn("screenrecord", popen_args)
        self.assertIn("--time-limit", popen_args)
        self.assertIn("90", popen_args)
        self.assertIn("6000000", popen_args)
        self.assertTrue(recorder.running)

    def test_time_limit_is_clamped(self):
        recorder = ScreenRecorder(FakeAdb(), time_limit=9999)
        self.assertEqual(recorder.time_limit, MAX_SEGMENT_SECONDS)

    def test_start_reports_device_refusal(self):
        recorder = ScreenRecorder(FakeAdb(fail=True))
        with mock.patch("apkharness.screen.time.sleep"):
            self.assertFalse(recorder.start())
        self.assertIn("screenrecord exited", recorder.error)
        self.assertIsNone(recorder.process)

    def test_stop_sends_sigint(self):
        adb = FakeAdb()
        recorder = ScreenRecorder(adb)
        with mock.patch("apkharness.screen.time.sleep"):
            recorder.start()
        recorder.stop()
        self.assertTrue(any("pkill -INT screenrecord" in str(cmd) for kind, *rest in adb.calls
                            for cmd in rest))
        self.assertFalse(recorder.running)

    def test_stop_and_pull_produces_file(self):
        adb = FakeAdb()
        recorder = ScreenRecorder(adb)
        target = os.path.join(self.dir, "session.mp4")
        with mock.patch("apkharness.screen.time.sleep"):
            recorder.start()
            path = recorder.stop_and_pull(target)
        self.assertEqual(path, target)
        self.assertTrue(os.path.exists(target))
        self.assertGreater(os.path.getsize(target), 4096)
        self.assertIn(recorder.remote, adb.removed)

    def test_stop_and_pull_detects_empty_recording(self):
        adb = FakeAdb(video_bytes=b"\x00" * 100)
        recorder = ScreenRecorder(adb)
        target = os.path.join(self.dir, "empty.mp4")
        with mock.patch("apkharness.screen.time.sleep"):
            recorder.start()
            path = recorder.stop_and_pull(target)
        self.assertIsNone(path)
        self.assertIn("no usable video", recorder.error)

    def test_describe(self):
        recorder = ScreenRecorder(FakeAdb(), time_limit=30)
        payload = recorder.describe()
        self.assertEqual(payload["time_limit"], 30)
        self.assertFalse(payload["running"])


if __name__ == "__main__":
    unittest.main()
