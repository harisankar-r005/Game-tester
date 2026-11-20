"""dumpsys parser tests."""

import unittest

from apkharness.metrics import (
    fill_sample,
    frame_rate,
    MetricsSample,
    parse_battery,
    parse_cpuinfo,
    parse_gfxinfo,
    parse_meminfo,
)

GFXINFO = """
Applications Graphics Acceleration Info:
Uptime: 123456 Realtime: 123456

** Graphics info for pid 4242 [com.example.game] **

Stats since: 123456789ns
Total frames rendered: 1200
Janky frames: 24 (2.00%)
Janky frames (legacy): 40 (3.33%)
50th percentile: 8ms
90th percentile: 12ms
95th percentile: 16ms
99th percentile: 33ms
Number Missed Vsync: 3
Number High input latency: 1
Number Slow UI thread: 5
Number Slow bitmap uploads: 0
Number Slow issue draw commands: 2
Number Frame deadline missed: 7
"""

MEMINFO = """
** MEMINFO in pid 4242 [com.example.game] **
                   Pss  Private  Private  SwapPss      Heap      Heap      Heap
                 Total    Dirty    Clean    Dirty      Size     Alloc      Free
                ------   ------   ------   ------    ------    ------    ------
  Native Heap    92345    91800        0        0    131072    100000     31072
  Dalvik Heap    41200    40800        0        0     65536     50000     15536
        Stack       64       64        0        0
       Gfx dev     2048     2048        0        0
       TOTAL   142000   140000        0        0   400000    250000     150000
"""

CPUINFO = """
CPU usage from 0ms to 5013ms later (2024-01-01 00:00:00.000 to 2024-01-01 00:00:05.013):
  43% 4242/com.example.game: 30% user + 13% kernel / faults: 120 minor 4 major
  12% 1000/system_server: 8% user + 4% kernel
"""


class GfxinfoTests(unittest.TestCase):
    def test_totals_and_percentiles(self):
        stats = parse_gfxinfo(GFXINFO)
        self.assertEqual(stats["total_frames"], 1200)
        self.assertEqual(stats["janky_frames"], 24)
        self.assertEqual(stats["janky_percent"], 2.0)
        self.assertEqual(stats["p90_ms"], 12.0)
        self.assertEqual(stats["p99_ms"], 33.0)
        self.assertEqual(stats["missed_vsync"], 3)

    def test_empty_input(self):
        stats = parse_gfxinfo("")
        self.assertIsNone(stats["total_frames"])


class MeminfoTests(unittest.TestCase):
    def test_total_and_heaps(self):
        stats = parse_meminfo(MEMINFO)
        self.assertEqual(stats["total_pss_kb"], 142000)
        self.assertEqual(stats["native_heap_kb"], 92345)
        self.assertEqual(stats["java_heap_kb"], 41200)

    def test_legacy_total_format(self):
        stats = parse_meminfo("TOTAL PSS: 2048\n")
        self.assertEqual(stats["total_pss_kb"], 2048)

    def test_garbage_is_none(self):
        self.assertIsNone(parse_meminfo("nothing here")["total_pss_kb"])


class CpuinfoTests(unittest.TestCase):
    def test_package_line(self):
        stats = parse_cpuinfo(CPUINFO, "com.example.game")
        self.assertEqual(stats["cpu_percent"], 43.0)
        self.assertEqual(stats["cpu_user"], 30.0)
        self.assertEqual(stats["cpu_kernel"], 13.0)

    def test_unknown_package(self):
        self.assertIsNone(parse_cpuinfo(CPUINFO, "com.absent")["cpu_percent"])


class SurfaceFlingerTests(unittest.TestCase):
    LATENCY = "8333333\n" + "0\t0\t0\n" * 3 + "".join(
        f"{1000000 + i * 16666666}\t{1000100 + i * 16666666}\t{1000200 + i * 16666666}\n"
        for i in range(10)
    )

    def test_frame_rate(self):
        from apkharness.metrics import parse_surfaceflinger_latency

        stats = parse_surfaceflinger_latency(self.LATENCY)
        self.assertAlmostEqual(stats["fps_estimate"], 60.0, delta=1.0)
        self.assertIsNotNone(stats["frame_ms"])

    def test_all_zero_layers_are_ignored(self):
        from apkharness.metrics import parse_surfaceflinger_latency

        stats = parse_surfaceflinger_latency("8333333\n" + "0\t0\t0\n" * 5)
        self.assertIsNone(stats["fps_estimate"])

    def test_layer_name_parsing(self):
        from apkharness.adb import Adb

        listing = (
            "RequestedLayerState{Surface(name=abc com.example.game/MainActivity#12)/@0x1 - leash} \n"
            "RequestedLayerState{SurfaceView[com.example.game/MainActivity]#13 parentId=1 z=-2} \n"
        )
        names = Adb.parse_layer_names(listing)
        self.assertIn("abc com.example.game/MainActivity#12", names)
        self.assertIn("SurfaceView[com.example.game/MainActivity]#13", names)


class BatteryTests(unittest.TestCase):
    def test_level_and_temperature(self):
        stats = parse_battery("level: 87\ntemperature: 305\n")
        self.assertEqual(stats["battery_level"], 87)
        self.assertEqual(stats["battery_temp_c"], 30.5)


class SampleTests(unittest.TestCase):
    def test_frame_rate(self):
        self.assertEqual(frame_rate(100, 280, 2.0), 90.0)
        self.assertIsNone(frame_rate(None, 280, 2.0))
        self.assertIsNone(frame_rate(100, 280, 0))
        self.assertIsNone(frame_rate(300, 100, 2.0))  # counter reset

    def test_fill_sample_skips_none(self):
        sample = fill_sample(MetricsSample(), total_pss_kb=1024, janky_percent=None)
        self.assertEqual(sample.total_pss_kb, 1024)
        self.assertIsNone(sample.janky_percent)
        self.assertNotIn("total_pss_kb", MetricsSample().to_dict())


if __name__ == "__main__":
    unittest.main()
