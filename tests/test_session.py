"""End-to-end session test against the simulator."""

import contextlib
import itertools
import json
import logging
import os
import shutil
import unittest
from xml.etree import ElementTree

from apkharness.run import RunConfig, Session
from apkharness.simulator import CrashPlan, SimDevice

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


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger("apkharness").setLevel(logging.ERROR)
        cls.tmp = scratch_dir("session")
        cls.root = cls.tmp.__enter__()
        cls.device = SimDevice(seed=5, plan=[CrashPlan(6, "java_crash"), CrashPlan(14, "anr")])
        cls.config = RunConfig(
            simulate=True,
            package="com.example.game",
            steps=24,
            out_root=cls.root,
            seed=5,
            step_delay_s=0.0,
            metrics_every=2,
        )
        cls.session = Session(cls.config, device=cls.device)
        cls.result = cls.session.run()
        cls.out_dir = cls.session.out_dir

    @classmethod
    def tearDownClass(cls):
        cls.tmp.__exit__(None, None, None)

    def test_artifacts_exist(self):
        for name in ("session.json", "logcat.txt", "report.html", "junit.xml", "metrics.json"):
            path = os.path.join(self.out_dir, name)
            self.assertTrue(os.path.exists(path), name)
            self.assertGreater(os.path.getsize(path) if name != "session.json" else 1, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.out_dir, "screenshots")))

    def test_steps_were_run(self):
        self.assertGreaterEqual(self.result.summary["steps_run"], 10)
        self.assertGreater(len(self.result.steps), 0)

    def test_crashes_detected(self):
        kinds = {crash["kind"] for crash in self.result.crashes}
        self.assertIn("java_crash", kinds)
        self.assertIn("anr", kinds)
        self.assertEqual(self.result.summary["verdict"], "crashes-found")

    def test_relaunch_after_crash(self):
        self.assertGreaterEqual(self.result.summary["relaunches"], 1)

    def test_session_json_is_serialisable(self):
        with open(os.path.join(self.out_dir, "session.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["meta"]["package"], "com.example.game")
        self.assertIn("summary", data)
        self.assertEqual(len(data["steps"]), len(self.result.steps))

    def test_junit_is_valid_xml(self):
        tree = ElementTree.parse(os.path.join(self.out_dir, "junit.xml"))
        root = tree.getroot()
        self.assertEqual(root.tag, "testsuite")
        self.assertGreater(int(root.attrib["tests"]), 1)
        self.assertGreaterEqual(int(root.attrib["failures"]), 1)
        names = [case.attrib["classname"] for case in root.findall("testcase")]
        self.assertTrue(any(name.startswith("apkharness.java_crash") for name in names))

    def test_report_mentions_crash_and_package(self):
        with open(os.path.join(self.out_dir, "report.html"), "r", encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("com.example.game", html)
        self.assertIn("NullPointerException", html)
        self.assertIn("apkharness session report", html)

    def test_screenshots_saved(self):
        files = os.listdir(os.path.join(self.out_dir, "screenshots"))
        self.assertGreater(len(files), 0)
        with open(os.path.join(self.out_dir, "screenshots", files[0]), "rb") as handle:
            self.assertTrue(handle.read(8).startswith(b"\x89PNG"))

    def test_metrics_sampled(self):
        self.assertIsNotNone(self.result.summary["avg_fps"])
        with open(os.path.join(self.out_dir, "metrics.json"), "r", encoding="utf-8") as handle:
            metrics = json.load(handle)
        self.assertTrue(any(entry.get("total_pss_kb") for entry in metrics))


class SessionPolicyTests(unittest.TestCase):
    def test_scripted_policy_drives_session(self):
        from apkharness.actions import Action
        from apkharness.policies.scripted import ScriptedPolicy

        actions = [Action(type="tap", x=135, y=420), Action(type="tap", x=135, y=200)]
        with scratch_dir() as tmp:
            config = RunConfig(
                simulate=True,
                package="com.example.game",
                steps=4,
                out_root=tmp,
                step_delay_s=0.0,
            )
            policy = ScriptedPolicy(actions=actions)
            session = Session(config, device=SimDevice(seed=2), policy=policy)
            result = session.run()
            self.assertEqual(result.summary["steps_run"], 4)
            labels = [step["action"] for step in result.steps]
            self.assertTrue(labels[0].startswith("tap(135,420)"))


if __name__ == "__main__":
    unittest.main()
