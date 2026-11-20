"""Simulator behaviour: PNG output, screen changes, scheduled failures."""

import unittest

from apkharness.png import PNG_SIGNATURE, decode, perceptual_hash, hamming
from apkharness.simulator import CrashPlan, SimDevice


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.device = SimDevice(seed=1, plan=[CrashPlan(5, "java_crash")])
        self.device.install("game.apk")
        self.device.launch(self.device.package)

    def test_screenshots_are_valid_png(self):
        shot = self.device.screenshot()
        self.assertTrue(shot.startswith(PNG_SIGNATURE))
        raster = decode(shot)
        self.assertEqual((raster.width, raster.height), (self.device.width, self.device.height))

    def test_taps_change_screen_and_hash(self):
        before = self.device.screenshot()
        self.device.tap(self.device.width // 2, int(self.device.height * 0.88))  # bottom third -> race
        after = self.device.screenshot()
        self.assertNotEqual(before, after)
        distance = hamming(perceptual_hash(decode(before)), perceptual_hash(decode(after)))
        self.assertGreater(distance, 3)

    def test_ui_dump_has_buttons_on_menu(self):
        xml = self.device.ui_dump()
        self.assertIn("Play", xml)
        self.device.tap(self.device.width // 2, int(self.device.height * 0.88))
        self.assertEqual(self.device.screen, "race")
        self.assertNotIn("Button", self.device.ui_dump())

    def test_planned_crash_kills_process(self):
        self.assertTrue(self.device.alive(self.device.package))
        for _ in range(6):
            self.device.tick()
        self.assertFalse(self.device.alive(self.device.package))
        lines = self.device.poll_logs()
        text = "\n".join(line.msg for line in lines)
        self.assertIn("FATAL EXCEPTION", text)

    def test_relaunch_restores_pid_and_menu(self):
        for _ in range(6):
            self.device.tick()
        self.device.launch(self.device.package)
        self.assertTrue(self.device.alive(self.device.package))
        self.assertEqual(self.device.screen, "menu")

    def test_metrics_are_plausible(self):
        sample = self.device.metrics(self.device.package)
        self.assertIsNotNone(sample.total_frames)
        self.assertGreater(sample.total_pss_kb, 0)
        self.assertLessEqual(sample.fps_estimate, 120)

    def test_logs_are_parseable_threadtime(self):
        from apkharness.logs import parse_lines

        self.device.tap(10, 10)
        lines = parse_lines("\n".join(line.raw for line in self.device.poll_logs()))
        self.assertTrue(all(line.pid > 0 for line in lines))


if __name__ == "__main__":
    unittest.main()
