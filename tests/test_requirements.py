"""Requirement parsing, test generation and suite verdict tests."""

import io
import json
import os
import shutil
import unittest
import zipfile

from apkharness.requirements import (
    Requirement,
    RequirementError,
    feature_summary,
    parse_document,
    parse_requirements,
    extract_text,
)
from apkharness.suite import Suite, SuiteStore
from apkharness.testgen import TestCase, generate, regenerate

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(SCRATCH, exist_ok=True)

SAMPLE_MD = """# Neon Drift — Game Requirements

## 1. Core loop
- The game must show a main menu with Play, Shop and Settings buttons.
- The player must be able to start a race from the Play button.
- The game shall show a game over screen when the player crashes into an obstacle.

## 2. Economy
- Collecting a coin must increase the coin balance by 10 coins.
- Upgrading a car must cost 200 coins and deduct them from the balance.
- The coin balance must persist after the game is closed and reopened.

## 3. Ads
- A rewarded video ad must be available on the revive screen.
- Watching the rewarded ad must grant exactly one revive.
- An interstitial ad must be shown after every third level completion.

## 4. IAP
- The coin pack product must grant 500 coins after a successful purchase.
- Cancelling a purchase must not grant any coins.
- Restore purchases must restore the no-ads entitlement.

## 5. Non functional
- The game must not crash during a 10 minute session.
- The game should run at 60 fps on a mid-range device.

## 6. Unclear / out of scope
- The settings screen should be user friendly.
- The backend must log every session to the analytics dashboard.
"""


class ParseTests(unittest.TestCase):
    def test_extracts_bullets_and_numbering(self):
        requirements = parse_requirements(SAMPLE_MD)
        self.assertGreaterEqual(len(requirements), 14)
        self.assertTrue(all(req.id.startswith("REQ-") for req in requirements))
        self.assertTrue(all(req.text for req in requirements))

    def test_ids_are_unique_and_sequential(self):
        requirements = parse_requirements(SAMPLE_MD)
        ids = [req.id for req in requirements]
        self.assertEqual(len(ids), len(set(ids)))

    def test_explicit_ids_are_kept(self):
        text = "- REQ-12: The shop must show the price of each item.\n"
        requirements = parse_requirements(text)
        self.assertEqual(requirements[0].id, "REQ-12")

    def test_source_path_recorded(self):
        requirements = parse_requirements(SAMPLE_MD)
        economy = [req for req in requirements if "coin" in req.text.lower()]
        self.assertTrue(economy)
        self.assertTrue(all(req.source for req in economy))

    def test_markdown_noise_stripped(self):
        text = "- **The game must show** a `Play` button [see mock](http://x/y).\n"
        requirements = parse_requirements(text)
        self.assertEqual(len(requirements), 1)
        self.assertNotIn("http", requirements[0].text)
        self.assertNotIn("**", requirements[0].text)
        self.assertNotIn("`", requirements[0].text)

    def test_code_fences_are_ignored(self):
        text = "- The menu must show Play.\n```\n- Not a requirement\n```\n"
        texts = [req.text for req in parse_requirements(text)]
        self.assertEqual(len(texts), 1)
        self.assertNotIn("Not a requirement", texts)

    def test_table_rows(self):
        table = "| ID | Requirement |\n| --- | --- |\n| AC-1 | The shop must list three coin packs. |\n"
        requirements = parse_requirements(table)
        self.assertEqual(len(requirements), 1)
        self.assertIn("coin packs", requirements[0].text)

    def test_blockquotes_are_notes_not_requirements(self):
        text = "# Spec\n\n> Note: this doc is a fixture.\n\n- The menu must show Play.\n"
        requirements = parse_requirements(text)
        self.assertEqual(len(requirements), 1)
        self.assertIn("Play", requirements[0].text)

    def test_priority_inference(self):
        text = (
            "- The game must show the score.\n"
            "- The game should show a hint.\n"
            "- The game may show a tip.\n"
        )
        priorities = [req.priority for req in parse_requirements(text)]
        self.assertEqual(priorities, ["P0", "P1", "P2"])

    def test_clarification_detection(self):
        text = "- The settings screen should be user friendly.\n"
        requirement = parse_requirements(text)[0]
        self.assertEqual(requirement.status, "NEEDS_CLARIFICATION")
        self.assertIn("vague", requirement.note)

    def test_question_marked_for_clarification(self):
        requirement = parse_requirements("- What should happen when the ad fails?\n")[0]
        self.assertEqual(requirement.status, "NEEDS_CLARIFICATION")

    def test_backend_requirement_is_not_testable(self):
        requirement = parse_requirements(
            "- The backend must log every session to the analytics dashboard.\n"
        )[0]
        self.assertEqual(requirement.status, "NOT_TESTABLE")

    def test_feature_classification(self):
        cases = {
            "- The player must jump over obstacles and collect power-ups.": "gameplay",
            "- Collecting a coin must increase the coin balance by 10.": "economy",
            "- A rewarded video ad must be available on the revive screen.": "ads",
            "- The coin pack product must grant 500 coins after purchase.": "iap",
            "- The next level must unlock after completion.": "levels",
            "- Pressing the settings icon must open the settings screen.": "navigation",
            "- The game must not crash during a 10 minute session.": "stability",
            "- The game should run at 60 fps on a mid-range device.": "performance",
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(parse_requirements(text + "\n")[0].feature, expected)

    def test_no_requirements_found(self):
        doc = parse_document("empty.md", b"# Title\n\nJust prose without bullets.\n")
        self.assertEqual(doc.requirements, [])
        self.assertTrue(doc.warnings)

    def test_feature_summary(self):
        requirements = parse_requirements(SAMPLE_MD)
        summary = feature_summary(requirements)
        self.assertTrue(summary)
        self.assertEqual(sum(item["total"] for item in summary), len(requirements))


class DocumentTests(unittest.TestCase):
    def test_docx_extraction(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>The menu must show Play.'
                "</w:t></w:r></w:p></w:body></w:document>",
            )
        kind, text = extract_text("spec.docx", buffer.getvalue())
        self.assertEqual(kind, "docx")
        self.assertIn("must show Play", text)

    def test_unsupported_extension(self):
        with self.assertRaises(RequirementError):
            extract_text("spec.exe", b"MZ")

    def test_pdf_without_optional_dependency(self):
        try:
            import pypdf  # noqa: F401
        except Exception:
            with self.assertRaises(RequirementError) as ctx:
                extract_text("spec.pdf", b"%PDF-1.4 broken")
            self.assertIn("pypdf", str(ctx.exception))
        else:
            self.skipTest("pypdf installed in this environment")

    def test_oversized_document(self):
        with self.assertRaises(RequirementError):
            extract_text("big.md", b"x" * (9 * 1024 * 1024))

    def test_empty_document(self):
        with self.assertRaises(RequirementError):
            parse_document("blank.md", b"   \n\n")


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = parse_document("spec.md", SAMPLE_MD.encode("utf-8"))
        cls.cases = generate(cls.doc.requirements)

    def test_every_requirement_is_traceable(self):
        covered = {case.requirement_id for case in self.cases}
        for requirement in self.doc.requirements:
            with self.subTest(requirement=requirement.id):
                self.assertIn(requirement.id, covered)

    def test_case_ids_unique(self):
        ids = [case.id for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(ids[0].startswith("TC-"))

    def test_stability_requirement_is_automatic(self):
        case = next(case for case in self.cases if case.feature == "stability")
        self.assertEqual(case.mode, "auto")
        self.assertIn("crash", case.expected.lower())

    def test_ads_requirement_has_reward_and_interstitial_cases(self):
        templates = {case.template for case in self.cases if case.feature == "ads"}
        self.assertIn("ads-rewarded", templates)
        self.assertIn("ads-interstitial", templates)

    def test_economy_cases_are_assisted_not_fake_pass(self):
        economy = [case for case in self.cases if case.feature == "economy"]
        self.assertTrue(economy)
        for case in economy:
            self.assertEqual(case.status, "NOT_RUN")
            self.assertEqual(case.mode, "assisted")
        balance = next(case for case in economy if case.template == "economy-balance")
        self.assertIn("screenshot alone does not prove", balance.expected.lower())

    def test_iap_cases_cover_grant_and_cancel(self):
        templates = {case.template for case in self.cases if case.feature == "iap"}
        self.assertEqual(templates, {"iap-grant", "iap-cancel"})

    def test_unclear_requirement_generates_not_verified_case(self):
        unclear = [case for case in self.cases if case.template == "needs-clarification"]
        self.assertTrue(unclear)
        self.assertEqual(unclear[0].status, "NOT_VERIFIED")

    def test_non_testable_requirement_is_blocked(self):
        blocked = [case for case in self.cases if case.template == "not-testable"]
        self.assertTrue(blocked)
        self.assertEqual(blocked[0].status, "BLOCKED")

    def test_expected_quotes_the_requirement(self):
        for case in self.cases:
            if case.template in ("needs-clarification", "not-testable"):
                continue
            self.assertIn("requirement states", case.expected.lower())

    def test_regenerate_preserves_results(self):
        self.cases[0].status = "PASS"
        self.cases[0].actual = "menu appeared"
        fresh = regenerate(self.cases, self.doc.requirements)
        self.assertEqual(fresh[0].status, "PASS")
        self.assertEqual(fresh[0].actual, "menu appeared")

    def test_regenerate_keeps_count(self):
        fresh = regenerate(self.cases, self.doc.requirements)
        self.assertEqual(len(fresh), len(self.cases))


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.suite = Suite(id="t1", doc_name="spec.md")
        self.suite.requirements = [{"id": "REQ-001"}, {"id": "REQ-002"}]
        self.suite.cases = [
            TestCase(id="TC-001", requirement_id="REQ-001", title="a", feature="navigation", priority="P0"),
            TestCase(id="TC-002", requirement_id="REQ-002", title="b", feature="economy", priority="P1"),
        ]

    def test_incomplete_when_nothing_run(self):
        self.assertEqual(self.suite.verdict(), "INCOMPLETE")
        self.assertIn("mandatory", self.suite.verdict_reason())

    def test_fail_on_mandatory_failure(self):
        self.suite.update_case("TC-001", status="FAIL")
        self.suite.update_case("TC-002", status="PASS")
        self.assertEqual(self.suite.verdict(), "FAIL")

    def test_pass_when_all_pass(self):
        self.suite.update_case("TC-001", status="PASS")
        self.suite.update_case("TC-002", status="PASS")
        self.assertEqual(self.suite.verdict(), "PASS")
        self.assertEqual(self.suite.coverage()["percent"], 100.0)

    def test_warn_when_advisory_fails(self):
        self.suite.update_case("TC-001", status="PASS")
        self.suite.update_case("TC-002", status="FAIL")
        self.assertEqual(self.suite.verdict(), "WARN")

    def test_mandatory_blocked_is_incomplete_not_pass(self):
        self.suite.update_case("TC-001", status="BLOCKED")
        self.suite.update_case("TC-002", status="PASS")
        self.assertEqual(self.suite.verdict(), "INCOMPLETE")

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            self.suite.update_case("TC-001", status="MAYBE")

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            self.suite.update_case("TC-001", sneaky="x")

    def test_unknown_case(self):
        with self.assertRaises(KeyError):
            self.suite.update_case("TC-999", status="PASS")

    def test_feature_rollup(self):
        self.suite.update_case("TC-001", status="PASS")
        features = {item["feature"]: item for item in self.suite.by_feature()}
        self.assertEqual(features["navigation"]["pass"], 1)

    def test_uncovered_requirements_reported(self):
        self.suite.cases = [self.suite.cases[0]]
        uncovered = self.suite.requirement_coverage()
        self.assertEqual([req["id"] for req in uncovered], ["REQ-002"])

    def test_persistence_roundtrip(self):
        directory = os.path.join(SCRATCH, f"suite_{os.getpid()}")
        shutil.rmtree(directory, ignore_errors=True)
        store = SuiteStore(directory)
        try:
            self.suite.update_case("TC-001", status="PASS", actual="opened")
            store.save(self.suite)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.case("TC-001").status, "PASS")
            self.assertEqual(loaded.verdict(), "WARN")
            self.assertEqual(len(store.history()), 1)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_evidence_appended(self):
        self.suite.add_evidence("TC-001", "screenshot", "shots/a.png", "main menu")
        self.assertEqual(len(self.suite.case("TC-001").evidence), 1)


if __name__ == "__main__":
    unittest.main()
