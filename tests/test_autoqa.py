import os
import tempfile
import unittest
import zipfile

from apkharness.autoqa import classify_apk, expert_plan, expert_review, review_markdown, scan_logcat
from apkharness.plan import validate_plan_dict


def _zip(names):
    handle = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    return handle.name


class ClassifyTests(unittest.TestCase):
    def test_unity_is_game(self):
        path = _zip(["AndroidManifest.xml", "lib/arm64-v8a/libunity.so"])
        try:
            result = classify_apk(path, "com.example.app")
        finally:
            os.remove(path)
        self.assertEqual(result["kind"], "game")
        self.assertIn("Unity", result["engine"])

    def test_flutter_is_app(self):
        path = _zip(["AndroidManifest.xml", "lib/arm64-v8a/libflutter.so"])
        try:
            self.assertEqual(classify_apk(path, "com.bank.mobile")["kind"], "app")
        finally:
            os.remove(path)

    def test_package_name_hint(self):
        path = _zip(["AndroidManifest.xml", "classes.dex"])
        try:
            self.assertEqual(classify_apk(path, "com.woolfun.wool.yarn.puzzle.game")["kind"], "game")
        finally:
            os.remove(path)


class PlanTests(unittest.TestCase):
    def test_plans_are_valid(self):
        for kind in ("game", "app"):
            plan = expert_plan(kind)
            self.assertEqual(validate_plan_dict(plan.to_dict()), [], kind)

    def test_game_has_fps_budget_app_does_not(self):
        self.assertTrue(any(c.metric == "avg_fps" for c in expert_plan("game").checks))
        self.assertFalse(any(c.metric == "avg_fps" for c in expert_plan("app").checks))


class ReviewTests(unittest.TestCase):
    def payload(self, crashes):
        return {
            "summary": {"steps_run": 120, "screens_explored": 6, "avg_fps": 50},
            "crashes": crashes,
            "checks": [],
            "timeline": [{"step": i, "action": f"tap {i}"} for i in range(1, 30)],
            "meta": {"package": "com.x"},
        }

    def test_crash_is_no_go_with_repro(self):
        review = expert_review(self.payload([{
            "kind": "java_crash", "message": "java.lang.NullPointerException", "step": 17,
            "stack": ["at a.b(C.java:1)"], "count": 1}]), {"kind": "game", "engine": "Unity"})
        self.assertEqual(review["decision"], "NO-GO")
        issue = review["issues"][0]
        self.assertEqual(issue["severity"], "S1 critical")
        self.assertEqual(issue["cause"], "null reference")
        self.assertTrue(any("Step 17" in line for line in issue["repro"]))
        self.assertIn("NO-GO", review_markdown(review))

    def test_clean_run_is_go(self):
        self.assertEqual(expert_review(self.payload([]))["decision"], "GO")

    def test_logcat_signals(self):
        scan = scan_logcat(["11-13 E/Choreographer: Skipped 45 frames!  The application may be doing too much work"])
        self.assertEqual(scan["signals"][0]["signal"], "UI thread skipped frames")


if __name__ == "__main__":
    unittest.main()
