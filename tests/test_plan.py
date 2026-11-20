"""Test-plan validation, check evaluation and the recording builder."""

import os
import shutil
import unittest

from apkharness.plan import (
    Check,
    CheckResult,
    Plan,
    PlanError,
    default_plan,
    evaluate,
    filter_findings,
    parse_plan,
    summarize,
    validate_plan_dict,
    verdict,
)
from apkharness import video
from apkharness.simulator import SimDevice

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(SCRATCH, exist_ok=True)


class PlanValidationTests(unittest.TestCase):
    def test_default_plan_is_valid(self):
        self.assertEqual(validate_plan_dict(default_plan().to_dict()), [])

    def test_roundtrip(self):
        plan = default_plan()
        restored = Plan.from_dict(plan.to_dict())
        self.assertEqual(restored.name, plan.name)
        self.assertEqual(len(restored.checks), len(plan.checks))
        self.assertEqual(plan.to_dict(), restored.to_dict())

    def test_unknown_field(self):
        errors = validate_plan_dict({"steps": 10, "wibble": 1})
        self.assertTrue(any("unknown field" in error for error in errors))

    def test_bad_policy_and_target(self):
        errors = validate_plan_dict({"policy": "magic", "target": "cloud"})
        self.assertTrue(any("policy" in error for error in errors))
        self.assertTrue(any("target" in error for error in errors))

    def test_steps_bounds(self):
        self.assertTrue(validate_plan_dict({"steps": 0}))
        self.assertTrue(validate_plan_dict({"steps": 10**7}))
        self.assertFalse(validate_plan_dict({"steps": 10}))

    def test_unknown_check_type_and_metric(self):
        errors = validate_plan_dict({"checks": [{"id": "a", "type": "teleport"},
                                                {"id": "b", "type": "min_metric", "metric": "magic"}]})
        self.assertTrue(any("unknown type" in error for error in errors))
        self.assertTrue(any("unknown metric" in error for error in errors))

    def test_unknown_kind(self):
        errors = validate_plan_dict({"checks": [{"id": "a", "type": "no_findings", "kinds": ["meteor"]}]})
        self.assertTrue(any("unknown finding kind" in error for error in errors))

    def test_duplicate_ids(self):
        errors = validate_plan_dict({"checks": [{"id": "x", "type": "no_findings"},
                                                {"id": "x", "type": "no_findings"}]})
        self.assertTrue(any("duplicate" in error for error in errors))

    def test_capture_mode(self):
        self.assertFalse(validate_plan_dict({"capture": "screenrecord"}))
        errors = validate_plan_dict({"capture": "magic"})
        self.assertTrue(any("capture" in error for error in errors))

    def test_bad_regex(self):
        errors = validate_plan_dict({"ignore": ["([unclosed"]})
        self.assertTrue(any("not a valid regex" in error for error in errors))

    def test_invalid_json(self):
        with self.assertRaises(PlanError) as ctx:
            parse_plan("{not json")
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_check_titles(self):
        self.assertIn("no java_crash", Check(id="a", type="no_findings", kinds=["java_crash"]).title)
        self.assertIn("average FPS", Check(id="b", type="min_metric", metric="avg_fps", value=30).title)


class CheckEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.plan = Plan(
            checks=[
                Check(id="no-crash", type="no_findings", kinds=["java_crash", "native_crash"]),
                Check(id="no-anr", type="no_findings", kinds=["anr"]),
                Check(id="fps", type="min_metric", metric="avg_fps", value=45, severity="warning"),
                Check(id="mem", type="max_metric", metric="peak_pss_kb", value=1048576),
                Check(id="screens", type="require_screens", value=3),
                Check(id="measured", type="require_metric", metric="min_fps"),
            ]
        )
        self.summary = {
            "avg_fps": 58.0,
            "min_fps": 51.0,
            "peak_pss_kb": 500_000,
            "screens_explored": 4,
        }

    def test_all_pass(self):
        results = evaluate(self.plan, self.summary, [])
        self.assertEqual(verdict(results), "pass")
        self.assertTrue(all(result.passed for result in results))
        self.assertEqual(summarize(results)["passed"], 6)

    def test_blocker_crash_fails(self):
        results = evaluate(self.plan, self.summary,
                           [{"kind": "native_crash", "message": "SIGSEGV", "step": 4}])
        self.assertEqual(verdict(results), "fail")
        crash_check = next(result for result in results if result.id == "no-crash")
        self.assertFalse(crash_check.passed)
        self.assertEqual(crash_check.actual, "1")

    def test_warning_only_is_warn(self):
        summary = dict(self.summary, avg_fps=20.0)
        results = evaluate(self.plan, summary, [])
        self.assertEqual(verdict(results), "warn")

    def test_failed_blocker_beats_warning(self):
        summary = dict(self.summary, avg_fps=10.0)
        results = evaluate(self.plan, summary, [{"kind": "anr", "message": "ANR", "step": 1}])
        self.assertEqual(verdict(results), "fail")
        self.assertEqual(summarize(results)["failed_blockers"], 1)

    def test_missing_metric_fails(self):
        results = evaluate(self.plan, {"screens_explored": 5}, [])
        mem = next(result for result in results if result.id == "mem")
        self.assertFalse(mem.passed)
        self.assertEqual(mem.actual, "not measured")

    def test_ignore_patterns_drop_findings(self):
        findings = [{"kind": "java_crash", "message": "known bug", "signature": "KnownBug boom", "step": 2}]
        results = evaluate(Plan(checks=[Check(id="c", type="no_findings")], ignore=["KnownBug"]),
                           {}, findings)
        self.assertTrue(results[0].passed)

    def test_filter_findings(self):
        findings = [{"signature": "keep me", "message": ""}, {"signature": "drop me", "message": ""}]
        kept = filter_findings(findings, ["drop"])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["signature"], "keep me")

    def test_invalid_ignore_is_ignored(self):
        self.assertEqual(len(filter_findings([{"signature": "x"}], ["(["])), 1)


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.row = os.path.join(SCRATCH, f"video_{os.getpid()}")
        os.makedirs(self.row, exist_ok=True)
        self.device = SimDevice(seed=3)
        self.device.install("game.apk")
        self.device.launch(self.device.package)

    def tearDown(self):
        shutil.rmtree(self.row, ignore_errors=True)

    def _frames(self, count=6):
        frames = []
        for index in range(count):
            self.device.tap(20 + index * 3, 60)
            path = os.path.join(self.row, f"frame_{index}.png")
            with open(path, "wb") as handle:
                handle.write(self.device.screenshot())
            frames.append(video.Frame(step=index + 1, path=path, action=f"tap({index})",
                                      finding=index == count - 1))
        return frames

    @unittest.skipUnless(video.available()[0], "no video backend available")
    def test_builds_a_recording(self):
        meta = video.build(self._frames(), self.row, fps=5, scale=2)
        self.assertTrue(meta["available"], meta)
        self.assertTrue(meta["path"], meta)
        self.assertTrue(os.path.exists(str(meta["path"])))
        self.assertGreater(os.path.getsize(str(meta["path"])), 1000)
        with open(str(meta["path"]), "rb") as handle:
            header = handle.read(6)
        self.assertIn(header, (b"GIF89a", b"GIF87a", b"\x00\x00\x00\x18ftyp"))

    def test_no_frames_reports_error(self):
        meta = video.build([], self.row)
        self.assertFalse(meta["available"])
        self.assertIn("no screenshots", meta["error"])

    def test_frames_from_timeline(self):
        shots = os.path.join(self.row, "screenshots")
        os.makedirs(shots, exist_ok=True)
        with open(os.path.join(shots, "step_00005.png"), "wb") as handle:
            handle.write(self.device.screenshot())
        timeline = [{"step": 5, "action": "tap(1,2)", "shot": "screenshots/step_00005.png"}]
        frames = video.frames_from_timeline(timeline, shots)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].step, 5)
        self.assertTrue(os.path.exists(frames[0].path))


if __name__ == "__main__":
    unittest.main()
