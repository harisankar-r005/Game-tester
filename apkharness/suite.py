"""The reviewed test suite: coverage, traceability and the overall QA verdict.

The verdict is a rule, not an opinion:

* ``FAIL``       - at least one mandatory (P0) case failed;
* ``INCOMPLETE`` - a mandatory case is not PASS (unexecuted, blocked, unverified, skipped);
* ``WARN``       - all mandatory cases passed, but advisory cases failed or were not run;
* ``PASS``       - every mandatory and advisory case passed.

This is why the platform can never report PASS while mandatory requirements are
untested, which is the most common way QA dashboards lie.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .testgen import CASE_STATUSES, TestCase

VERDICTS = ("PASS", "FAIL", "WARN", "INCOMPLETE")
MANDATORY = "P0"
DECIDED = ("PASS", "FAIL", "BLOCKED", "NOT_VERIFIED")


@dataclass
class Suite:
    id: str
    doc_name: str = ""
    apk_package: str = ""
    apk_version: str = ""
    approved: bool = False
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    cases: List[TestCase] = field(default_factory=list)
    requirements: List[Dict] = field(default_factory=list)

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "doc_name": self.doc_name,
            "apk_package": self.apk_package,
            "apk_version": self.apk_version,
            "approved": self.approved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cases": [case.to_dict() for case in self.cases],
            "requirements": list(self.requirements),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Suite":
        return cls(
            id=str(data.get("id", "suite")),
            doc_name=str(data.get("doc_name", "")),
            apk_package=str(data.get("apk_package", "")),
            apk_version=str(data.get("apk_version", "")),
            approved=bool(data.get("approved", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            cases=[TestCase.from_dict(item) for item in data.get("cases") or []],
            requirements=[dict(item) for item in data.get("requirements") or []],
        )

    # -- queries -----------------------------------------------------------
    def case(self, case_id: str) -> Optional[TestCase]:
        return next((case for case in self.cases if case.id == case_id), None)

    def mandatory_cases(self) -> List[TestCase]:
        return [case for case in self.cases if case.priority == MANDATORY]

    def status_counts(self) -> Dict[str, int]:
        counts = {status: 0 for status in CASE_STATUSES}
        for case in self.cases:
            counts[case.status] = counts.get(case.status, 0) + 1
        return counts

    def coverage(self) -> Dict[str, object]:
        counts = self.status_counts()
        total = len(self.cases)
        decided = sum(counts.get(status, 0) for status in DECIDED)
        mandatory = self.mandatory_cases()
        mandatory_passed = sum(1 for case in mandatory if case.status == "PASS")
        return {
            "total": total,
            "decided": decided,
            "percent": round(100.0 * decided / total, 1) if total else 0.0,
            "pass": counts.get("PASS", 0),
            "fail": counts.get("FAIL", 0),
            "blocked": counts.get("BLOCKED", 0),
            "not_verified": counts.get("NOT_VERIFIED", 0),
            "skipped": counts.get("SKIPPED", 0),
            "not_run": counts.get("NOT_RUN", 0),
            "mandatory_total": len(mandatory),
            "mandatory_passed": mandatory_passed,
        }

    def by_feature(self) -> List[Dict[str, object]]:
        buckets: Dict[str, Dict[str, object]] = {}
        for case in self.cases:
            bucket = buckets.setdefault(
                case.feature,
                {"feature": case.feature, "total": 0, "pass": 0, "fail": 0,
                 "blocked": 0, "not_run": 0},
            )
            bucket["total"] = int(bucket["total"]) + 1
            key = {"PASS": "pass", "FAIL": "fail", "BLOCKED": "blocked"}.get(case.status, "not_run")
            bucket[key] = int(bucket[key]) + 1
        return sorted(buckets.values(), key=lambda item: (-int(item["total"]), str(item["feature"])))

    def requirement_coverage(self) -> List[Dict[str, object]]:
        """Which requirements have no case at all (should stay empty)."""
        covered = {case.requirement_id for case in self.cases}
        return [req for req in self.requirements if req.get("id") not in covered]

    def verdict(self) -> str:
        if not self.cases:
            return "INCOMPLETE"
        mandatory = self.mandatory_cases()
        if any(case.status == "FAIL" for case in mandatory):
            return "FAIL"
        if any(case.status != "PASS" for case in mandatory):
            return "INCOMPLETE"
        advisory = [case for case in self.cases if case.priority != MANDATORY]
        if any(case.status in ("FAIL", "BLOCKED") for case in advisory):
            return "WARN"
        if any(case.status in ("NOT_RUN", "NOT_VERIFIED", "SKIPPED") for case in advisory):
            return "WARN"
        return "PASS"

    def verdict_reason(self) -> str:
        verdict = self.verdict()
        coverage = self.coverage()
        if verdict == "FAIL":
            failed = [case.id for case in self.mandatory_cases() if case.status == "FAIL"]
            return f"mandatory case(s) failed: {', '.join(failed[:5])}"
        if verdict == "INCOMPLETE":
            pending = [case.id for case in self.mandatory_cases() if case.status != "PASS"]
            return (
                f"{len(pending)} mandatory case(s) not passed "
                f"({coverage['mandatory_passed']}/{coverage['mandatory_total']}): "
                f"{', '.join(pending[:5])}"
            )
        if verdict == "WARN":
            advisory = [
                case.id for case in self.cases
                if case.priority != MANDATORY and case.status != "PASS"
            ]
            return f"advisory case(s) not passed: {', '.join(advisory[:5])}"
        return "all mandatory and advisory cases passed"

    # -- mutation ----------------------------------------------------------
    def update_case(self, case_id: str, **fields) -> TestCase:
        case = self.case(case_id)
        if case is None:
            raise KeyError(f"unknown test case {case_id!r}")
        allowed = {"title", "expected", "actual", "status", "priority", "notes",
                   "preconditions", "steps", "mode"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot edit field(s): {', '.join(sorted(unknown))}")
        if "status" in fields and fields["status"] not in CASE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(CASE_STATUSES)}")
        if "priority" in fields and fields["priority"] not in ("P0", "P1", "P2"):
            raise ValueError("priority must be P0, P1 or P2")
        for key, value in fields.items():
            setattr(case, key, value)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return case

    def add_evidence(self, case_id: str, kind: str, path: str, note: str = "") -> TestCase:
        case = self.case(case_id)
        if case is None:
            raise KeyError(f"unknown test case {case_id!r}")
        case.evidence.append({"kind": kind, "path": path, "note": note,
                              "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        return case

    def summary(self) -> Dict[str, object]:
        coverage = self.coverage()
        counts = self.status_counts()
        return {
            "id": self.id,
            "doc_name": self.doc_name,
            "approved": self.approved,
            "verdict": self.verdict(),
            "reason": self.verdict_reason(),
            "coverage": coverage,
            "statuses": counts,
            "features": self.by_feature(),
            "uncovered_requirements": self.requirement_coverage(),
        }


class SuiteStore:
    """JSON persistence next to the other studio artifacts."""

    def __init__(self, directory: str) -> None:
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, exist_ok=True)

    def path(self, suite_id: str = "current") -> str:
        return os.path.join(self.directory, f"{suite_id}.json")

    def save(self, suite: Suite, suite_id: str = "current") -> str:
        path = self.path(suite_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(suite.to_dict(), handle, indent=2)
        os.replace(tmp, path)
        return path

    def load(self, suite_id: str = "current") -> Optional[Suite]:
        path = self.path(suite_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return Suite.from_dict(json.load(handle))

    def history(self) -> List[Dict[str, object]]:
        """Every stored suite, newest first (used by the dashboard KPIs)."""
        entries: List[Dict[str, object]] = []
        for name in os.listdir(self.directory):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.directory, name), "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            suite = Suite.from_dict(data)
            entries.append(
                {
                    "id": suite.id,
                    "doc_name": suite.doc_name,
                    "approved": suite.approved,
                    "updated_at": suite.updated_at,
                    "verdict": suite.verdict(),
                    "cases": len(suite.cases),
                    "coverage": suite.coverage(),
                }
            )
        return sorted(entries, key=lambda item: str(item.get("updated_at", "")), reverse=True)


def merge_statuses(suite: Suite, results: Dict[str, str]) -> Suite:
    """Apply ``{case_id: status}`` from an execution run."""
    for case_id, status in results.items():
        if status not in CASE_STATUSES:
            continue
        case = suite.case(case_id)
        if case is not None:
            case.status = status
    suite.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return suite
