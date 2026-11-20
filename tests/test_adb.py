"""adb layer tests with a stubbed transport (no device required)."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from apkharness.adb import Adb, AdbError, AdbNotFound
from apkharness.device import AdbDevice, observe
from apkharness.png import encode_rgba

DEVICES = """List of devices attached
R58M1234ABC          device product:beyond1lte model:SM_G973F device:beyond1 transport_id:1
emulator-5554        offline product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 transport_id:2
"""

WM_SIZE = "Physical size: 1440x3040\nOverride size: 1080x2280\n"

LOGCAT_A = """\
11-11 12:00:00.100  1000  1000 I ActivityManager: Start proc 4242:com.example.game/u0a1
11-11 12:00:01.500  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main
11-11 12:00:01.500  4242  4242 E AndroidRuntime: java.lang.IllegalStateException: boom
"""

LOGCAT_B = """\
11-11 12:00:00.100  1000  1000 I ActivityManager: Start proc 4242:com.example.game/u0a1
11-11 12:00:01.500  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main
11-11 12:00:01.500  4242  4242 E AndroidRuntime: java.lang.IllegalStateException: boom
11-11 12:00:02.000  4242  4242 I Unity: frame 120
"""


def _result(stdout=b"", stderr=b"", code=0):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class DeviceListTests(unittest.TestCase):
    def test_parses_devices(self):
        with mock.patch.object(Adb, "text", autospec=True, return_value=DEVICES):
            devices = Adb.list_devices("adb")
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].serial, "R58M1234ABC")
        self.assertTrue(devices[0].online)
        self.assertEqual(devices[0].model, "SM_G973F")
        self.assertFalse(devices[1].online)

    def test_empty_list(self):
        with mock.patch.object(Adb, "text", autospec=True, return_value="List of devices attached\n\n"):
            self.assertEqual(Adb.list_devices("adb"), [])


class ScreenTests(unittest.TestCase):
    def test_override_size_wins(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "shell", autospec=True, return_value=WM_SIZE):
            self.assertEqual(adb.screen_size(), (1080, 2280))

    def test_physical_only(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "shell", autospec=True, return_value="Physical size: 720x1280\n"):
            self.assertEqual(adb.screen_size(), (720, 1280))

    def test_unparseable_size(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "shell", autospec=True, return_value="garbage"):
            self.assertEqual(adb.screen_size(), (0, 0))


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class ScreencapTests(unittest.TestCase):

    def test_exec_out_path(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "run", autospec=True, return_value=_result(stdout=PNG_BYTES)):
            self.assertEqual(adb.screencap(), PNG_BYTES)

    def test_falls_back_to_pull(self):
        adb = Adb(path="adb")
        calls = []
        scratch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
        os.makedirs(scratch, exist_ok=True)

        def fake_run(self, args, timeout=None, binary=False):
            calls.append(args)
            return _result(stdout=b"")

        def fake_text(self, args, timeout=None):
            calls.append(args)
            if args[0] == "pull":
                with open(args[2], "wb") as handle:
                    handle.write(PNG_BYTES)
                return ""
            return ""

        with mock.patch.object(Adb, "run", autospec=True, side_effect=fake_run), \
                mock.patch.object(Adb, "text", autospec=True, side_effect=fake_text), \
                mock.patch("apkharness.adb.os.getcwd", return_value=scratch):
            data = adb.screencap()
        self.assertEqual(data, PNG_BYTES)
        self.assertTrue(any(call[0] == "pull" for call in calls))

    def test_pull_returns_garbage_raises(self):
        adb = Adb(path="adb")
        scratch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
        os.makedirs(scratch, exist_ok=True)

        def fake_run(self, args, timeout=None, binary=False):
            return _result(stdout=b"")

        def fake_text(self, args, timeout=None):
            if args[0] == "pull":
                with open(args[2], "wb") as handle:
                    handle.write(b"jpeg-ish")
            return ""

        with mock.patch.object(Adb, "run", autospec=True, side_effect=fake_run), \
                mock.patch.object(Adb, "text", autospec=True, side_effect=fake_text), \
                mock.patch("apkharness.adb.os.getcwd", return_value=scratch):
            with self.assertRaises(AdbError):
                adb.screencap()


class InstallTests(unittest.TestCase):
    def test_install_failure_message(self):
        adb = Adb(path="adb")
        failure = _result(stdout=b"", stderr=b"Failure [INSTALL_FAILED_NO_MATCHING_ABIS]", code=1)
        with mock.patch.object(Adb, "run", autospec=True, return_value=failure):
            with self.assertRaises(AdbError) as ctx:
                adb.install(__file__)
        self.assertIn("NO_MATCHING_ABIS", str(ctx.exception))

    def test_success(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "run", autospec=True, return_value=_result(stdout=b"Success\n")):
            self.assertIn("Success", adb.install(__file__))

    def test_missing_apk_rejected_before_adb(self):
        adb = Adb(path="adb")
        with self.assertRaises(AdbError):
            adb.install("does-not-exist.apk")


class MissingAdbTests(unittest.TestCase):
    def test_clear_error_when_not_on_path(self):
        adb = Adb(path="definitely-not-adb-binary")
        with self.assertRaises(AdbNotFound) as ctx:
            adb.shell("true")
        self.assertIn("platform-tools", str(ctx.exception))


class PackageTests(unittest.TestCase):
    def test_list_packages(self):
        adb = Adb(path="adb")
        output = "package:com.android.settings\npackage:com.example.game\n"
        with mock.patch.object(Adb, "shell", autospec=True, return_value=output):
            self.assertEqual(adb.list_packages(), ["com.android.settings", "com.example.game"])

    def test_pidof(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "shell", autospec=True, return_value="4242\n"):
            self.assertEqual(adb.pidof("com.example.game"), 4242)
        with mock.patch.object(Adb, "shell", autospec=True, return_value=""):
            self.assertIsNone(adb.pidof("com.example.game"))

    def test_resolve_launch_activity(self):
        adb = Adb(path="adb")
        output = "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
        output += "com.example.game/.MainActivity\n"
        with mock.patch.object(Adb, "shell", autospec=True, return_value=output):
            self.assertEqual(adb.resolve_launch_activity("com.example.game"), "com.example.game/.MainActivity")

    def test_resolve_launch_activity_empty(self):
        adb = Adb(path="adb")
        with mock.patch.object(Adb, "shell", autospec=True, return_value="No activity found\n"):
            self.assertEqual(adb.resolve_launch_activity("com.example.game"), "")


class AdbDeviceTests(unittest.TestCase):
    def _device(self):
        adb = Adb(path="adb", serial="R58M1234ABC")
        return AdbDevice(adb=adb, serial="R58M1234ABC")

    def test_logcat_poll_deduplicates(self):
        device = self._device()
        responses = [LOGCAT_A, LOGCAT_B]
        with mock.patch.object(Adb, "logcat_dump", autospec=True, side_effect=lambda self, **kw: responses.pop(0)):
            first = device.poll_logs()
            second = device.poll_logs()
        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 1)  # only the new Unity line
        self.assertEqual(second[0].msg, "frame 120")

    def test_metrics_use_dumpsys(self):
        device = self._device()
        gfx = "Total frames rendered: 900\nJanky frames: 9 (1.00%)\n90th percentile: 11ms\n"
        mem = "  Native Heap    1000       0        0        0\n       TOTAL    5000       0        0        0\n"
        cpu = "  35% 4242/com.example.game: 25% user + 10% kernel\n"
        battery = "level: 66\ntemperature: 300\n"
        with mock.patch.object(Adb, "gfxinfo", autospec=True, return_value=gfx), \
                mock.patch.object(Adb, "meminfo", autospec=True, return_value=mem), \
                mock.patch.object(Adb, "cpuinfo", autospec=True, return_value=cpu), \
                mock.patch.object(Adb, "battery", autospec=True, return_value=battery):
            sample = device.metrics("com.example.game")
        self.assertEqual(sample.total_frames, 900)
        self.assertEqual(sample.total_pss_kb, 5000)
        self.assertEqual(sample.native_heap_kb, 1000)
        self.assertEqual(sample.cpu_percent, 35.0)
        self.assertEqual(sample.battery_level, 66)

    def test_screen_size_cached(self):
        device = self._device()
        with mock.patch.object(Adb, "screen_size", autospec=True, return_value=(1080, 1920)) as probe:
            self.assertEqual(device.screen_size(), (1080, 1920))
            self.assertEqual(device.screen_size(), (1080, 1920))
        self.assertEqual(probe.call_count, 1)

    def test_screencap_updates_cached_size_after_rotation(self):
        device = self._device()
        pixels = bytes(4 * 8 * 4)
        landscape = encode_rgba(8, 4, pixels)
        portrait = encode_rgba(4, 8, pixels)
        with mock.patch.object(Adb, "screen_size", return_value=(4, 8)) as probe, \
                mock.patch.object(Adb, "screencap", side_effect=[landscape, AdbError("capture failed"), portrait]):
            self.assertEqual(device.screen_size(), (4, 8))
            self.assertEqual(device.screenshot(), landscape)
            self.assertEqual(device.screen_size(), (8, 4))
            self.assertIsNone(device.screenshot())
            self.assertEqual(device.screen_size(), (8, 4))
            self.assertEqual(device.screenshot(), portrait)
            self.assertEqual(device.screen_size(), (4, 8))
        probe.assert_called_once()

    def test_observation_updates_orientation_between_saved_frames(self):
        adb = mock.Mock(spec=Adb)
        adb.pidof.return_value = 4242
        pixels = bytes(4 * 8 * 4)
        adb.screencap.side_effect = [encode_rgba(4, 8, pixels), encode_rgba(8, 4, pixels)]
        device = AdbDevice(adb=adb, serial="phone")

        before = observe(device, 1, 0.0, "com.example.game", want_ui=False, want_metrics=False)
        after = observe(device, 2, 1.0, "com.example.game", want_screenshot=False,
                        want_ui=False, want_metrics=False)

        self.assertEqual(before.screen_size, (4, 8))
        self.assertEqual(after.screen_size, (8, 4))
        self.assertIsNone(after.screenshot)
        self.assertIsNone(after.phash)

    def test_alive_uses_pidof(self):
        device = self._device()
        with mock.patch.object(Adb, "pidof", autospec=True, return_value=4242):
            self.assertTrue(device.alive("com.example.game"))
        with mock.patch.object(Adb, "pidof", autospec=True, return_value=None):
            self.assertFalse(device.alive("com.example.game"))


if __name__ == "__main__":
    unittest.main()
