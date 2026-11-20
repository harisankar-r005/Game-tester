"""Report rendering tests (no device, synthetic session data)."""

import contextlib
import itertools
import os
import shutil
import unittest
from xml.etree import ElementTree

from apkharness.report import render_html, render_junit, write_html, write_junit

_SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(_SCRATCH, exist_ok=True)
_ids = itertools.count()


@contextlib.contextmanager
def scratch_dir(tag: str = "case"):
    """Workspace-local scratch dir; the system temp dir is blocked in some sandboxes."""
    path = os.path.join(_SCRATCH, f"{tag}_{next(_ids)}_{os.getpid()}")
    os.makedirs(path, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

SESSION = {
    "config": {"policy": "heuristic", "steps": 10},
    "meta": {"package": "com.example.<game>", "policy": "heuristic", "serial": "abc", "tool": "apkharness test"},
    "summary": {
        "steps_run": 10,
        "unique_crashes": 1,
        "anr_count": 0,
        "screens_explored": 3,
        "avg_fps": 59.4,
        "min_fps": 41.0,
        "avg_jank_percent": 2.5,
        "peak_pss_kb": 204800,
        "duration_s": 12.5,
        "verdict": "crashes-found",
        "relaunches": 1,
    },
    "crashes": [
        {
            "kind": "java_crash",
            "signature": "NullPointerException",
            "message": "java.lang.NullPointerException at <init>",
            "ts": "11-11 11:00:00.000",
            "stack": ["at com.example.Game.tick(Game.java:1)"],
            "step": 4,
            "screenshot": "",
            "count": 2,
        }
    ],
    "timeline": [
        {"step": 1, "time": 0.2, "action": "tap(10,20)", "screen": "aabb", "new": True,
         "alive": True, "shot": "", "fps": 60.0, "pss_kb": 100000},
        {"step": 2, "time": 0.5, "action": "swipe(1,2->3,4,300ms)", "screen": "aabb", "new": False,
         "alive": False, "shot": "", "fps": 55.0, "pss_kb": 120000},
    ],
    "screenshots": {},
}


class HtmlTests(unittest.TestCase):
    def test_contains_summary_and_crash(self):
        html = render_html(SESSION, "")
        self.assertIn("10", html)
        self.assertIn("NullPointerException", html)
        self.assertIn("crashes found", html)
        self.assertIn("Frame rate estimate", html)

    def test_escapes_user_content(self):
        html = render_html(SESSION, "")
        self.assertIn("com.example.&lt;game&gt;", html)
        self.assertNotIn("<game>", html)

    def test_no_crash_verdict(self):
        clean = dict(SESSION, crashes=[], summary=dict(SESSION["summary"], unique_crashes=0,
                                                       verdict="no-failures-observed"))
        html = render_html(clean, "")
        self.assertIn("no failures observed", html)
        self.assertIn("No crash, ANR or process death detected", html)

    def test_write_html(self):
        with scratch_dir() as tmp:
            path = write_html(SESSION, tmp)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 1000)


class JUnitTests(unittest.TestCase):
    def test_valid_xml_with_failure(self):
        xml = render_junit(SESSION)
        root = ElementTree.fromstring(xml)
        self.assertEqual(root.tag, "testsuite")
        self.assertEqual(root.attrib["tests"], "2")
        self.assertEqual(root.attrib["failures"], "1")
        case = root.findall("testcase")[1]
        self.assertIn("NullPointerException", case.attrib["name"])
        self.assertEqual(case.find("failure").attrib["type"], "java_crash")

    def test_clean_session_has_no_failures(self):
        clean = dict(SESSION, crashes=[])
        root = ElementTree.fromstring(render_junit(clean))
        self.assertEqual(root.attrib["failures"], "0")

    def test_write_junit(self):
        with scratch_dir() as tmp:
            path = write_junit(SESSION, os.path.join(tmp, "junit.xml"))
            self.assertTrue(os.path.exists(path))
            ElementTree.parse(path)


if __name__ == "__main__":
    unittest.main()
