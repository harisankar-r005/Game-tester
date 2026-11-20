"""Logcat parsing and crash detection tests."""

import unittest

from apkharness.logs import CrashDetector, merge_crashes, normalise_signature, parse_lines

JAVA_CRASH = """\
11-11 11:30:00.100  1000  1000 I ActivityManager: Start proc 4242:com.example.game/u0a12 for activity com.example.game/.Main
11-11 11:30:01.200  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main
11-11 11:30:01.200  4242  4242 E AndroidRuntime: Process: com.example.game, PID: 4242
11-11 11:30:01.201  4242  4242 E AndroidRuntime: java.lang.NullPointerException: Attempt to invoke virtual method 'int Player.getHealth()' on a null object reference
11-11 11:30:01.201  4242  4242 E AndroidRuntime: \tat com.example.game.Race.update(Race.java:214)
11-11 11:30:01.201  4242  4242 E AndroidRuntime: \tat com.example.game.Loop.tick(Loop.java:88)
11-11 11:30:01.202  4242  4242 E AndroidRuntime: \tat android.os.Handler.dispatchMessage(Handler.java:106)
"""

PROCESS_DEATH = """\
11-11 11:30:02.000  1000  1000 I ActivityManager: Process com.example.game (pid 4242) has died: fg TOP
"""

NATIVE_CRASH = """\
11-11 11:31:00.500  4242  4310 F libc    : Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0 in tid 4310 (RenderThread), pid 4242 (game)
11-11 11:31:00.500  4310  4310 F DEBUG   : *** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
11-11 11:31:00.500  4310  4310 F DEBUG   : signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
11-11 11:31:00.501  4310  4310 F DEBUG   :       #00 pc 00000000001a2b3c  /data/app/libunity.so (Crash+28)
"""

ANR_LOG = """\
11-11 11:32:00.000  1000  1000 E ActivityManager: ANR in com.example.game (com.example.game/.Main)
11-11 11:32:00.001  1000  1000 E ActivityManager: PID: 4242
11-11 11:32:00.002  1000  1000 E ActivityManager: Reason: Input dispatching timed out
11-11 11:32:05.000  1000  1000 I ActivityManager: Force finishing activity com.example.game/.Main
"""

CLEAN_LOG = """\
11-11 11:30:00.100  1000  1000 I ActivityManager: Start proc 4242:com.example.game/u0a12 for activity com.example.game/.Main
11-11 11:30:00.200  4242  4242 I Unity   : Initialize engine version
11-11 11:30:00.300  4242  4242 W Choreographer: Skipped 32 frames!  The application may be doing too much work on its main thread.
"""


class ParseTests(unittest.TestCase):
    def test_parse_threadtime(self):
        lines = parse_lines(JAVA_CRASH)
        self.assertGreaterEqual(len(lines), 5)
        first = lines[0]
        self.assertEqual(first.pid, 1000)
        self.assertEqual(first.level, "I")
        self.assertEqual(first.tag, "ActivityManager")

    def test_parse_skips_non_log_lines(self):
        self.assertEqual(parse_lines("random text\n\n"), [])
        self.assertEqual(parse_lines("--------- beginning of main\n"), [])

    def test_signature_normalises_numbers(self):
        a = normalise_signature("Fatal signal 11 in tid 4310 pid 4242")
        b = normalise_signature("Fatal signal 12 in tid 9999 pid 1111")
        self.assertEqual(a, b)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.detector = CrashDetector("com.example.game")

    def test_java_crash_with_stack(self):
        crashes = self.detector.feed(parse_lines(JAVA_CRASH), step=7)
        self.assertEqual(len(crashes), 1)
        crash = crashes[0]
        self.assertEqual(crash.kind, "java_crash")
        self.assertEqual(crash.message, "java.lang.NullPointerException")
        self.assertEqual(crash.step, 7)
        self.assertTrue(any("Race.update" in frame for frame in crash.stack))

    def test_native_crash(self):
        crashes = self.detector.feed(parse_lines(NATIVE_CRASH))
        self.assertEqual(len(crashes), 1)
        self.assertEqual(crashes[0].kind, "native_crash")
        self.assertIn("SIGSEGV", crashes[0].message)

    def test_anr(self):
        crashes = self.detector.feed(parse_lines(ANR_LOG))
        kinds = [c.kind for c in crashes]
        self.assertIn("anr", kinds)
        # "Force finishing" must not add a second ANR when no ANR marker is present.
        self.assertEqual(kinds.count("anr"), 1)

    def test_force_finishing_alone_is_not_an_anr(self):
        line = "11-11 11:33:00.000  1000  1000 I ActivityManager: Force finishing activity com.example.game/.Main\n"
        crashes = self.detector.feed(parse_lines(line))
        self.assertEqual(crashes, [])

    def test_clean_log_has_no_crashes(self):
        self.assertEqual(self.detector.feed(parse_lines(CLEAN_LOG)), [])

    def test_other_package_ignored(self):
        other = (
            "11-11 11:34:00.000  1000  1000 E ActivityManager: ANR in com.other.app "
            "(com.other.app/.Main)\n"
        )
        self.assertEqual(self.detector.feed(parse_lines(other)), [])

    def test_process_death(self):
        crashes = self.detector.feed(parse_lines(PROCESS_DEATH))
        self.assertEqual([c.kind for c in crashes], ["process_death"])

    def test_merge_dedupes_by_signature(self):
        crashes = self.detector.feed(parse_lines(JAVA_CRASH))
        first = crashes[0]
        merged = merge_crashes(crashes, self.detector.feed(parse_lines(JAVA_CRASH)))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].count, 2)
        self.assertIs(merged[0], first)


if __name__ == "__main__":
    unittest.main()
