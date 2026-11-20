import json
import os
import shutil
import tempfile
import unittest

from apkharness.autoqa import expert_plan, expert_review
from apkharness.dashboard import compare_runs, find_baseline
from apkharness.plan import validate_plan_dict
from apkharness.run import RunConfig, Session
from apkharness.stress import memory_trend, summarize_startup


class StressSessionTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="apkharness_stress_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_simulated_lifecycle_and_startup(self):
        config = RunConfig(simulate=True, steps=60, out_root=self.out, step_delay_s=0.0, seed=3,
                           interruptions=["background", "rotate", "kill_restore"], interrupt_every=10,
                           startup_runs=2, sim_crash_at=0)
        result = Session(config).run()
        kinds = [event["kind"] for event in result.interruptions]
        self.assertIn("kill_restore", kinds)
        restore = next(event for event in result.interruptions if event["kind"] == "kill_restore")
        self.assertFalse(restore["survived"])  # the simulator mishandles state restore once
        self.assertGreaterEqual(result.summary["interruptions_failed"], 1)
        self.assertTrue(result.summary["cold_start_ms"])
        self.assertTrue(result.summary["warm_start_ms"])
        review = expert_review(result.to_dict(), {"kind": "game", "engine": "sim"})
        self.assertTrue(any(issue["kind"] == "lifecycle" for issue in review["issues"]))
        self.assertEqual(review["decision"], "NO-GO")


class HelperTests(unittest.TestCase):
    def test_memory_trend_detects_growth(self):
        samples = [{"elapsed_s": t, "total_pss_kb": 100_000 + t * 500} for t in range(0, 120, 10)]
        self.assertAlmostEqual(memory_trend(samples)["growth_kb_per_min"], 30_000, delta=1)

    def test_startup_summary(self):
        self.assertEqual(summarize_startup([1000, 1200], [300])["cold_avg_ms"], 1100)

    def test_expert_plan_valid_with_interruptions(self):
        plan = expert_plan("app")
        self.assertTrue(plan.interruptions and plan.startup_runs)
        self.assertEqual(validate_plan_dict(plan.to_dict()), [])

    def test_bad_interruption_rejected(self):
        self.assertTrue(validate_plan_dict({"interruptions": ["explode"]}))


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.runs = tempfile.mkdtemp(prefix="apkharness_cmp_")

    def tearDown(self):
        shutil.rmtree(self.runs, ignore_errors=True)

    def _run(self, run_id, version, fps, crashes, budget=100, completed=None):
        os.makedirs(os.path.join(self.runs, run_id))
        with open(os.path.join(self.runs, run_id, "session.json"), "w") as handle:
            json.dump({"meta": {"package": "com.x", "apk": {"version_name": version, "version_code": "1"}},
                       "summary": {"avg_fps": fps, "peak_pss_kb": 300000, "steps_requested": budget,
                                   "steps_run": budget if completed is None else completed},
                       "crashes": [{"signature": c} for c in crashes]}, handle)

    def test_regression_and_new_crash(self):
        self._run("20260101_100000_com.x", "1.0", 60, ["old crash"])
        self._run("20260102_100000_com.x", "1.1", 40, ["new crash"])
        base = find_baseline(self.runs, "20260102_100000_com.x")
        self.assertEqual(base, "20260101_100000_com.x")
        result = compare_runs(self.runs, "20260102_100000_com.x", base)
        self.assertEqual(result["new_crashes"], ["new crash"])
        self.assertEqual(result["fixed_crashes"], ["old crash"])
        self.assertTrue(any(r["metric"] == "avg_fps" for r in result["regressions"]))

    def test_baseline_matches_the_exploration_budget(self):
        self._run("20260101_100000_com.x", "1.0", 60, [], budget=50)
        self._run("20260102_100000_com.x", "1.1", 60, [], budget=400)
        self._run("20260103_100000_com.x", "1.2", 60, [], budget=50)
        self.assertEqual(find_baseline(self.runs, "20260103_100000_com.x"), "20260101_100000_com.x")

    def test_partial_reports_are_excluded_from_comparisons(self):
        complete = "20260101_100000_com.x"
        partial = "20260102_100000_com.x"
        latest = "20260103_100000_com.x"
        self._run(complete, "1.0", 60, [])
        self._run(partial, "1.1", 12, [], completed=20)
        self._run(latest, "1.2", 60, [])
        self.assertEqual(find_baseline(self.runs, latest), complete)
        self.assertEqual(find_baseline(self.runs, partial), "")
        with self.assertRaisesRegex(ValueError, "completed exploration runs"):
            compare_runs(self.runs, latest, partial)


if __name__ == "__main__":
    unittest.main()
