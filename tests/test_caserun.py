import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from apkharness.casefile import FIRST_CUSTOMER_PACKAGE, first_customer_guide, parse_cases
from apkharness.caserun import FAILED, NOT_PASSED, PASSED, CaseRunner, HumanDesk
from apkharness.simulator import SimDevice
from apkharness.studio import Studio, StudioError

CASES_MD = """
## Inputs
- username: player1

## TC-01: Open settings
Steps:
1. Tap Settings
Expected: The settings screen is shown

## TC-02: Name change [human]
Steps:
1. Type {username} in the name box
Expected: The name shows {username}

## TC-03: Buy coins
Steps:
1. Open the shop
Expected: 100 coins are added
"""


def fake_ai(url, headers, payload, timeout):
    system = payload["messages"][0]["content"]
    if "expected result" in system.lower() and "verdict" in system:
        reply = {"verdict": "pass", "reason": "settings screen visible"}
    elif "ONE step" in system:
        user = payload["messages"][-1]["content"]
        reply = {"done": False, "needs_human": True, "thought": "needs a payment"} if "shop" in user else \
            {"done": True, "thought": "already there"}
    else:
        reply = {"ok": True}
    return {"message": {"content": json.dumps(reply)}}


class Person(threading.Thread):
    """Answers every question the runner asks, like a tester at the page."""

    def __init__(self, desk, answers):
        super().__init__(daemon=True)
        self.desk, self.answers, self.seen, self.stop = desk, answers, [], False

    def run(self):
        while not self.stop:
            q = self.desk.current
            if q is not None and q.id not in [s[0] for s in self.seen]:
                answer = self.answers.get((q.case_id, q.kind), q.options[0])
                self.seen.append((q.id, q.case_id, q.kind, answer))
                self.desk.answer(q.id, answer)
            time.sleep(0.02)


class CaseRunTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="apkharness_cases_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def make(self, ai, answers, stop=lambda: False):
        parsed = parse_cases(CASES_MD)
        device = SimDevice(package="com.example.neondrift", seed=3)
        device.install("x.apk")
        device.launch("com.example.neondrift")
        desk = HumanDesk()
        person = Person(desk, answers)
        person.start()
        runner = CaseRunner(device, "com.example.neondrift", "", parsed["cases"], parsed["inputs"], self.out, desk,
                            ai_config=ai, should_stop=stop, simulate=True, human_timeout_s=5)
        if ai:
            from apkharness.policies.agent import AIClient, AIConfig
            runner.ai = AIClient(AIConfig(provider="ollama"), transport=fake_ai)
        try:
            return runner.run(), person
        finally:
            person.stop = True

    def test_ai_plus_human(self):
        payload, person = self.make({"provider": "ollama"}, {("TC-02", "judge"): "Passed", ("TC-03", "do"): "Failed"})
        status = {r["id"]: r["status"] for r in payload["results"]}
        self.assertEqual(status["TC-01"], PASSED)            # AI did the step and judged it
        self.assertEqual(status["TC-02"], PASSED)            # [human] case: person did it and confirmed
        self.assertEqual(status["TC-03"], FAILED)            # AI handed over; person said it fails
        by = {r["id"]: r["decided_by"] for r in payload["results"]}
        self.assertEqual(by["TC-01"], "AI")
        self.assertIn("player1", payload["results"][1]["steps"][0]["text"])  # input filled in
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.html")))

    def test_without_ai_person_does_everything(self):
        payload, _ = self.make(None, {("TC-01", "judge"): "Passed", ("TC-02", "do"): "Skip",
                                      ("TC-03", "judge"): "Not sure"})
        status = {r["id"]: r["status"] for r in payload["results"]}
        self.assertEqual(status, {"TC-01": PASSED, "TC-02": NOT_PASSED, "TC-03": NOT_PASSED})

    def test_stop_marks_the_rest_not_passed(self):
        payload, _ = self.make(None, {}, stop=lambda: True)
        self.assertTrue(all(r["status"] == NOT_PASSED for r in payload["results"]))
        self.assertEqual(len(payload["results"]), 3)

    def test_builtin_walkthrough_uses_manual_verification_without_restarting_cases(self):
        studio = Studio(workdir=self.out)
        self.assertFalse(first_customer_guide("com.example.neondrift"))
        with self.assertRaisesRegex(StudioError, "Unity first-customer game"):
            studio.start_cases(guided=True)
        studio.apk = {"package": FIRST_CUSTOMER_PACKAGE, "installed_only": True}
        uploaded = parse_cases(CASES_MD)
        studio.case_doc = uploaded
        device = SimDevice(package=FIRST_CUSTOMER_PACKAGE, seed=3)
        device.install("game.apk")
        person = Person(studio.desk, {("TC-03", "judge"): "Failed"})
        person.start()
        try:
            with patch.object(studio, "_pick_serial", return_value="test-phone"), \
                    patch("apkharness.studio.AdbDevice", return_value=device), \
                    patch.object(device, "force_stop", wraps=device.force_stop) as force_stop:
                studio.start_cases(where="phone", guided=True)
                studio.thread.join(timeout=10)
                force_stop.assert_not_called()
        finally:
            person.stop = True
            person.join(timeout=2)
        self.assertEqual(studio.status, "done", studio.error)
        self.assertIs(studio.case_doc, uploaded)
        self.assertTrue(studio.case_result["guided"])
        self.assertEqual([result["status"] for result in studio.case_result["results"]], [PASSED, PASSED, FAILED])
        self.assertEqual(len(person.seen), 6)
        self.assertTrue(all(result["expected"] and result["screenshot"] for result in studio.case_result["results"]))


if __name__ == "__main__":
    unittest.main()
