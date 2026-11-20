import unittest

from apkharness.checklist import test_checklist as build_checklist


class ChecklistTests(unittest.TestCase):
    def payload(self, steps_run, reason, events):
        return {
            "summary": {"steps_run": steps_run, "steps_requested": 400, "end_reason": reason,
                        "planned_interruptions": ["background", "rotate", "kill_restore"],
                        "avg_fps": 50, "min_fps": 20, "screens_explored": 5},
            "interruptions": events,
            "crashes": [],
        }

    def test_stopped_test_marks_unreached_items_not_tested(self):
        result = build_checklist(self.payload(30, "stopped", [
            {"kind": "background", "step": 25, "survived": True}]))
        self.assertTrue(result["ended_early"])
        self.assertEqual(result["percent"], 8)
        status = {item["name"]: item["status"] for item in result["items"]}
        self.assertEqual(status["Leave the game and come back"], "passed")
        self.assertEqual(status["Turn the phone sideways"], "not_run")
        self.assertEqual(status["Play 400 steps"], "partial")
        self.assertGreaterEqual(result["counts"]["not_tested"], 3)

    def test_failed_lifecycle_is_failed(self):
        result = build_checklist(self.payload(400, "completed", [
            {"kind": "kill_restore", "step": 75, "survived": False}]))
        status = {item["name"]: item["status"] for item in result["items"]}
        self.assertEqual(status["Android closes the game in the background"], "failed")
        self.assertFalse(result["ended_early"])


if __name__ == "__main__":
    unittest.main()
