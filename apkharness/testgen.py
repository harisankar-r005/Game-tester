"""Deterministic requirement -> test case generation.

Templates are chosen from the requirement's feature and wording; the requirement text
itself is never paraphrased into a claim the document does not make. Every generated
case keeps a back-reference (``requirement_id``) so the report can prove traceability.

An LLM may *enrich* the wording later, but it is not required: the generator must work
offline and produce the same cases for the same document, which is what makes the
suite reviewable and diff-able.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from .requirements import Requirement

CASE_STATUSES = ("NOT_RUN", "PASS", "FAIL", "BLOCKED", "NOT_VERIFIED", "SKIPPED")

#: how deep the harness can go by itself
MODES = {
    "auto": "executed by the harness with a machine-checkable assertion",
    "assisted": "harness drives, tester/sandbox confirms the visible result",
    "manual": "needs a human or an instrumented build",
}

NUMBER_RE = re.compile(r"\b\d[\d,. ]*\b")


@dataclass
class TestCase:
    id: str
    requirement_id: str
    title: str
    feature: str
    preconditions: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    expected: str = ""
    priority: str = "P1"
    mode: str = "assisted"
    status: str = "NOT_RUN"
    actual: str = ""
    evidence: List[Dict[str, str]] = field(default_factory=list)
    notes: str = ""
    template: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "requirement_id": self.requirement_id,
            "title": self.title,
            "feature": self.feature,
            "preconditions": list(self.preconditions),
            "steps": list(self.steps),
            "expected": self.expected,
            "priority": self.priority,
            "mode": self.mode,
            "status": self.status,
            "actual": self.actual,
            "evidence": list(self.evidence),
            "notes": self.notes,
            "template": self.template,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        return cls(
            id=str(data["id"]),
            requirement_id=str(data.get("requirement_id", "")),
            title=str(data.get("title", "")),
            feature=str(data.get("feature", "other")),
            preconditions=[str(item) for item in data.get("preconditions") or []],
            steps=[str(item) for item in data.get("steps") or []],
            expected=str(data.get("expected", "")),
            priority=str(data.get("priority", "P1")),
            mode=str(data.get("mode", "assisted")),
            status=str(data.get("status", "NOT_RUN")),
            actual=str(data.get("actual", "")),
            evidence=[dict(item) for item in data.get("evidence") or []],
            notes=str(data.get("notes", "")),
            template=str(data.get("template", "")),
        )


TRUNCATE = 68


def _short(text: str, limit: int = TRUNCATE) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _numbers(text: str) -> List[str]:
    return [match.group(0).strip() for match in NUMBER_RE.finditer(text)]


def _expected(requirement: Requirement, extra: str = "") -> str:
    """Quote the requirement verbatim, then add the mechanical assertion if any."""
    base = f'The requirement states: "{_short(requirement.text, 240)}"'
    if extra:
        return f"{base} {extra}"
    return f"{base} The documented behaviour must be observable on screen."


def _template_cases(requirement: Requirement) -> List[dict]:
    """Return template dicts for one requirement, keyed by feature and wording."""
    text = requirement.text.lower()
    feature = requirement.feature
    numbers = _numbers(requirement.text)
    numeric_hint = (
        f"Use the documented value(s) {', '.join(numbers[:3])} as the expected figure."
        if numbers
        else ""
    )

    if feature == "stability":
        return [
            {
                "key": "stability-flow",
                "title": f"No crash/ANR while exercising: {_short(requirement.text)}",
                "pre": ["Game installed and launched", "Logcat and process monitor running"],
                "steps": [
                    "Launch the game from a clean state.",
                    "Exercise the documented flow repeatedly (at least 3 times).",
                    "Watch logcat for FATAL EXCEPTION / native signal / ANR in the package.",
                ],
                "expected": _expected(requirement, "No crash, native signal or ANR is recorded."),
                "mode": "auto",
                "template": "stability",
            }
        ]

    if feature == "performance":
        return [
            {
                "key": "performance-budget",
                "title": f"Performance budget for: {_short(requirement.text)}",
                "pre": ["Game launched", "Metrics sampling enabled"],
                "steps": [
                    "Launch the game and reach the documented screen or flow.",
                    "Sample FPS (SurfaceFlinger latency or gfxinfo) and total PSS for the flow.",
                    "Compare against the configured performance thresholds in the plan checks.",
                ],
                "expected": _expected(
                    requirement,
                    "Measured FPS/memory satisfy the plan thresholds; recorded as estimates, "
                    "not engine instrumentation.",
                ),
                "mode": "auto",
                "template": "performance",
            }
        ]

    if feature == "economy":
        cases = [
            {
                "key": "economy-balance",
                "title": f"Balance changes exactly as documented: {_short(requirement.text)}",
                "pre": ["Known starting balance visible in the HUD", "No pending transactions"],
                "steps": [
                    "Record the visible balance before the action.",
                    "Perform the documented earn/spend action once.",
                    "Record the visible balance again and compute the delta.",
                    "Relaunch the game and confirm the balance persisted.",
                ],
                "expected": _expected(
                    requirement,
                    "The delta matches the documented amount and survives a relaunch. "
                    "A screenshot alone does not prove arithmetic unless the numbers are read and differenced.",
                ),
                "mode": "assisted",
                "template": "economy",
            },
            {
                "key": "economy-guard",
                "title": f"No duplicate or negative balance: {_short(requirement.text)}",
                "pre": ["Balance recorded"],
                "steps": [
                    "Trigger the same reward/purchase twice as fast as possible.",
                    "Check the balance after each trigger.",
                    "Repeat with an unaffordable purchase to check the negative-balance guard.",
                ],
                "expected": _expected(requirement, "The reward is granted once; balance never goes below zero."),
                "mode": "assisted",
                "template": "economy-guard",
            },
        ]
        return cases

    if feature == "ads":
        cases = []
        if any(word in text for word in ("rewarded", "reward video", "rewarded video")):
            cases.append(
                {
                    "key": "ads-rewarded",
                    "title": f"Rewarded ad grants its reward once: {_short(requirement.text)}",
                    "pre": ["Test ad unit configured", "Reward entry point visible"],
                    "steps": [
                        "Open the documented rewarded placement.",
                        "Watch the ad through to completion (test ad unit only).",
                        "Verify the reward is granted exactly once and gameplay resumes.",
                        "Repeat the flow and confirm the reward is not duplicated.",
                    ],
                    "expected": _expected(
                        requirement,
                        "Ad displays, reward granted once, no duplicate on repeat. "
                        "A no-fill is recorded as BLOCKED, never as a placement failure.",
                    ),
                    "mode": "assisted",
                    "template": "ads-rewarded",
                }
            )
        if any(word in text for word in ("interstitial", "between levels", "after level")):
            cases.append(
                {
                    "key": "ads-interstitial",
                    "title": f"Interstitial shows at the documented trigger: {_short(requirement.text)}",
                    "pre": ["Test ad unit configured"],
                    "steps": [
                        "Reach the documented trigger point.",
                        "Verify an interstitial is requested and displayed.",
                        "Close it and verify navigation continues to the expected screen.",
                    ],
                    "expected": _expected(requirement, "Ad shows at the trigger and closing resumes the flow."),
                    "mode": "assisted",
                    "template": "ads-interstitial",
                }
            )
        if any(word in text for word in ("banner", "no ads", "remove ads")):
            cases.append(
                {
                    "key": "ads-suppression",
                    "title": f"Ad visibility matches entitlement: {_short(requirement.text)}",
                    "pre": ["Sandbox entitlement state known"],
                    "steps": [
                        "With no entitlement, verify the documented banner/interstitial behaviour.",
                        "Grant the No-Ads entitlement in the sandbox.",
                        "Verify banner and interstitial are suppressed while rewarded ads still work (if documented).",
                    ],
                    "expected": _expected(requirement, "Visibility follows the entitlement; no ad is faked."),
                    "mode": "assisted",
                    "template": "ads-suppression",
                }
            )
        if not cases:
            cases.append(
                {
                    "key": "ads-generic",
                    "title": f"Ad placement behaves as documented: {_short(requirement.text)}",
                    "pre": ["Test ad units configured"],
                    "steps": [
                        "Reach the documented placement trigger.",
                        "Capture the ad request, display and close sequence.",
                        "Record whether the game resumed correctly.",
                    ],
                    "expected": _expected(requirement),
                    "mode": "assisted",
                    "template": "ads-generic",
                }
            )
        return cases

    if feature == "iap":
        return [
            {
                "key": "iap-grant",
                "title": f"Purchase grants the documented entitlement: {_short(requirement.text)}",
                "pre": ["Play Billing test account", "License test response configured"],
                "steps": [
                    "Open the store and confirm the product id and price shown.",
                    "Complete a sandbox purchase.",
                    "Verify the entitlement/currency is granted exactly once.",
                    "Restart the game and confirm the entitlement persists.",
                ],
                "expected": _expected(
                    requirement,
                    "Entitlement granted once and persisted. Never a real-money purchase.",
                ),
                "mode": "assisted",
                "template": "iap-grant",
            },
            {
                "key": "iap-cancel",
                "title": f"Cancelled/failed purchase grants nothing: {_short(requirement.text)}",
                "pre": ["Sandbox purchase dialog reachable"],
                "steps": [
                    "Start a purchase and cancel it.",
                    "Repeat and force a declined test card.",
                    "Verify no entitlement and no currency change in either case.",
                ],
                "expected": _expected(requirement, "No entitlement, no currency change, no error dialog stuck."),
                "mode": "assisted",
                "template": "iap-cancel",
            },
        ]

    if feature == "levels":
        return [
            {
                "key": "levels-select",
                "title": f"Level selection/unlock follows the spec: {_short(requirement.text)}",
                "pre": ["At least one level completed previously"],
                "steps": [
                    "Open the level selection screen.",
                    "Verify locked/unlocked state matches progression.",
                    "Open the documented level and verify it loads.",
                ],
                "expected": _expected(requirement),
                "mode": "assisted",
                "template": "levels-select",
            },
            {
                "key": "levels-complete",
                "title": f"Level completion and progression: {_short(requirement.text)}",
                "pre": ["Level entry point reachable"],
                "steps": [
                    "Play the level until the documented outcome (win or fail).",
                    "Verify the result screen and rewards.",
                    "Verify the next level unlocks or the retry path works.",
                ],
                "expected": _expected(requirement, "Outcome, reward and progression match the document."),
                "mode": "assisted",
                "template": "levels-complete",
            },
        ]

    if feature == "navigation":
        return [
            {
                "key": "nav-reach",
                "title": f"Reach the documented screen: {_short(requirement.text)}",
                "pre": ["Game launched at the main menu"],
                "steps": [
                    "Follow the documented path from the main menu.",
                    "Verify the target screen is displayed with its expected controls.",
                    "Press Back and verify the previous screen returns.",
                ],
                "expected": _expected(requirement),
                "mode": "auto",
                "template": "nav-reach",
            },
            {
                "key": "nav-lifecycle",
                "title": f"Screen survives background/foreground: {_short(requirement.text)}",
                "pre": ["Target screen open"],
                "steps": [
                    "Send the game to the background (Home).",
                    "Bring it back to the foreground.",
                    "Verify the same screen is restored without a crash or data loss.",
                ],
                "expected": _expected(requirement, "State restored, process still alive, no ANR."),
                "mode": "auto",
                "template": "nav-lifecycle",
            },
        ]

    if feature == "gameplay":
        return [
            {
                "key": "gameplay-controls",
                "title": f"Player input behaves as documented: {_short(requirement.text)}",
                "pre": ["Gameplay session started"],
                "steps": [
                    "Start a gameplay session.",
                    "Send the documented control input and observe the immediate response.",
                    "Confirm the response is visible (movement, animation, value change, sound cue).",
                ],
                "expected": _expected(requirement, "The game reacts to the documented control."),
                "mode": "assisted",
                "template": "gameplay-controls",
            },
            {
                "key": "gameplay-outcome",
                "title": f"Win/lose outcome matches the rules: {_short(requirement.text)}",
                "pre": ["Gameplay session started"],
                "steps": [
                    "Play toward the documented success condition.",
                    "Play toward the documented failure condition.",
                    "Verify the result screen, reward and retry/next actions.",
                ],
                "expected": _expected(requirement, "Both outcomes occur with the documented screens and rewards."),
                "mode": "assisted",
                "template": "gameplay-outcome",
            },
        ]

    return [
        {
            "key": "generic-observable",
            "title": f"Documented behaviour is observable: {_short(requirement.text)}",
            "pre": ["Game launched"],
            "steps": [
                "Follow the documented steps for this requirement.",
                "Capture the screen and the relevant logcat lines.",
                "Compare against the documented expected result.",
            ],
            "expected": _expected(requirement, numeric_hint),
            "mode": "manual",
            "template": "generic",
        }
    ]


def generate(requirements: Sequence[Requirement], start_index: int = 1) -> List[TestCase]:
    """Build the test suite for a document, preserving its order."""
    cases: List[TestCase] = []
    counter = start_index
    for requirement in requirements:
        if requirement.status == "NOT_TESTABLE":
            cases.append(
                TestCase(
                    id=f"TC-{counter:03d}",
                    requirement_id=requirement.id,
                    title=f"Not automatable: {_short(requirement.text)}",
                    feature=requirement.feature,
                    preconditions=["None - requirement is outside black-box reach"],
                    steps=["Review the requirement manually."],
                    expected=_expected(requirement),
                    priority=requirement.priority,
                    mode="manual",
                    status="BLOCKED",
                    notes=requirement.note or "marked NOT_TESTABLE by the analyser",
                    template="not-testable",
                )
            )
            counter += 1
            continue
        if requirement.status == "NEEDS_CLARIFICATION":
            cases.append(
                TestCase(
                    id=f"TC-{counter:03d}",
                    requirement_id=requirement.id,
                    title=f"Clarify before testing: {_short(requirement.text)}",
                    feature=requirement.feature,
                    preconditions=["Requirement must be clarified by the product owner"],
                    steps=["Send the requirement back for clarification."],
                    expected=_expected(requirement, "A measurable acceptance criterion is required."),
                    priority=requirement.priority,
                    mode="manual",
                    status="NOT_VERIFIED",
                    notes=requirement.note,
                    template="needs-clarification",
                )
            )
            counter += 1
            continue

        for template in _template_cases(requirement):
            cases.append(
                TestCase(
                    id=f"TC-{counter:03d}",
                    requirement_id=requirement.id,
                    title=template["title"],
                    feature=requirement.feature,
                    preconditions=list(template["pre"]),
                    steps=list(template["steps"]),
                    expected=template["expected"],
                    priority=requirement.priority,
                    mode=template["mode"],
                    template=template["key"],
                )
            )
            counter += 1
    return cases


def regenerate(cases: Sequence[TestCase], requirements: Sequence[Requirement]) -> List[TestCase]:
    """Re-run generation while keeping the status/actual/evidence of unchanged cases."""
    by_key = {(case.requirement_id, case.template): case for case in cases}
    fresh = generate(requirements)
    for case in fresh:
        previous = by_key.get((case.requirement_id, case.template))
        if previous is not None:
            case.status = previous.status
            case.actual = previous.actual
            case.evidence = list(previous.evidence)
    return fresh
