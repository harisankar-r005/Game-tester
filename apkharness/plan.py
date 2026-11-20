"""Test plans: the editable "check logic" a QA engineer works with.

A plan is plain JSON so it can live in an editor, in git, or in an API call::

    {
      "name": "Neon Drift smoke test",
      "target": "device",
      "policy": "heuristic",
      "steps": 300,
      "checks": [
        {"id": "no-crash", "type": "no_findings", "kinds": ["java_crash", "native_crash"]},
        {"id": "fps", "type": "min_metric", "metric": "avg_fps", "value": 45, "severity": "warning"}
      ],
      "ignore": ["libc.*harmless.*"]
    }

The same plan drives the CLI (``run --plan``), the HTTP studio and the JUnit
verdict, so "what was checked" is never implicit.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .policies import POLICIES

SEVERITIES = ("blocker", "warning")
CAPTURE_MODES = ("frames", "screenrecord", "both")

FINDING_KINDS = (
    "java_crash",
    "native_crash",
    "anr",
    "process_death",
    "low_memory",
    "exception",
)

#: Summary metrics a check may reference, with a human label and unit.
METRICS: Dict[str, Dict[str, str]] = {
    "unique_crashes": {"label": "unique findings", "unit": ""},
    "total_crash_events": {"label": "crash events", "unit": ""},
    "anr_count": {"label": "ANRs", "unit": ""},
    "java_crashes": {"label": "Java crashes", "unit": ""},
    "native_crashes": {"label": "native crashes", "unit": ""},
    "screens_explored": {"label": "screens explored", "unit": ""},
    "steps_run": {"label": "steps run", "unit": ""},
    "relaunches": {"label": "relaunches", "unit": ""},
    "avg_fps": {"label": "average FPS", "unit": "fps"},
    "min_fps": {"label": "minimum FPS", "unit": "fps"},
    "avg_jank_percent": {"label": "janky frames", "unit": "%"},
    "peak_pss_kb": {"label": "peak memory", "unit": "kB"},
    "duration_s": {"label": "duration", "unit": "s"},
    "interruptions_run": {"label": "interruptions run", "unit": ""},
    "interruptions_failed": {"label": "interruptions the app did not survive", "unit": ""},
    "cold_start_ms": {"label": "cold start", "unit": "ms"},
    "warm_start_ms": {"label": "warm start", "unit": "ms"},
    "avg_cpu_percent": {"label": "average CPU", "unit": "%"},
    "max_cpu_percent": {"label": "peak CPU", "unit": "%"},
    "max_battery_temp_c": {"label": "peak battery temperature", "unit": "°C"},
    "mem_growth_kb_per_min": {"label": "memory growth (leak trend)", "unit": "kB/min"},
}

INTERRUPTION_KINDS = ("background", "rotate", "lock", "airplane", "memory", "kill_restore")

CHECK_TYPES = {
    "no_findings": "No finding of the listed kinds may occur (default: any kind).",
    "max_findings": "The number of findings of the listed kinds must not exceed `value`.",
    "min_metric": "Summary metric `metric` must be >= `value`.",
    "max_metric": "Summary metric `metric` must be <= `value`.",
    "require_metric": "Summary metric `metric` must have been measured at all.",
    "require_screens": "At least `value` distinct screens must have been reached.",
}

MAX_STEPS = 100_000


def _num(value: float) -> str:
    """Render 1500000 as 1500000, not 1.5e+06."""
    try:
        return f"{value:.0f}" if float(value).is_integer() else f"{value:g}"
    except (TypeError, ValueError):
        return str(value)


class PlanError(ValueError):
    """Raised when a plan is structurally invalid."""

    def __init__(self, errors: List[str]) -> None:
        super().__init__("; ".join(errors) if errors else "invalid plan")
        self.errors = errors


@dataclass
class Check:
    id: str
    type: str
    kinds: List[str] = field(default_factory=list)
    metric: str = ""
    value: float = 0
    severity: str = "blocker"

    def to_dict(self) -> Dict[str, Any]:
        payload = {"id": self.id, "type": self.type, "severity": self.severity}
        if self.kinds:
            payload["kinds"] = list(self.kinds)
        if self.metric:
            payload["metric"] = self.metric
        if self.type in ("min_metric", "max_metric", "require_screens", "max_findings"):
            payload["value"] = self.value
        return payload

    @property
    def title(self) -> str:
        if self.type == "no_findings":
            kinds = ", ".join(self.kinds) if self.kinds else "any finding"
            return f"no {kinds}"
        if self.type == "max_findings":
            kinds = ", ".join(self.kinds) if self.kinds else "findings"
            return f"at most {_num(self.value)} x {kinds}"
        if self.type in ("min_metric", "max_metric"):
            label = METRICS.get(self.metric, {}).get("label", self.metric)
            sign = ">=" if self.type == "min_metric" else "<="
            return f"{label} {sign} {_num(self.value)}"
        if self.type == "require_metric":
            return f"{METRICS.get(self.metric, {}).get('label', self.metric)} is measured"
        if self.type == "require_screens":
            return f"at least {_num(self.value)} screens explored"
        return self.id


@dataclass
class Plan:
    name: str = "QA plan"
    target: str = "simulator"
    policy: str = "heuristic"
    steps: int = 160
    minutes: float = 20.0
    seed: int = 7
    record_video: bool = True
    video_fps: int = 6
    capture: str = "frames"
    install: bool = True
    checks: List[Check] = field(default_factory=list)
    ignore: List[str] = field(default_factory=list)
    notes: str = ""
    interruptions: List[str] = field(default_factory=list)
    interrupt_every: int = 25
    startup_runs: int = 0

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "target": self.target,
            "policy": self.policy,
            "steps": self.steps,
            "minutes": self.minutes,
            "seed": self.seed,
            "record_video": self.record_video,
            "video_fps": self.video_fps,
            "capture": self.capture,
            "install": self.install,
            "checks": [check.to_dict() for check in self.checks],
            "ignore": list(self.ignore),
        }
        if self.notes:
            payload["notes"] = self.notes
        if self.interruptions:
            payload["interruptions"] = list(self.interruptions)
            payload["interrupt_every"] = self.interrupt_every
        if self.startup_runs:
            payload["startup_runs"] = self.startup_runs
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    # -- parsing -----------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        if not isinstance(data, dict):
            raise PlanError(["plan must be a JSON object"])
        errors = validate_plan_dict(data)
        if errors:
            raise PlanError(errors)
        checks = [
            Check(
                id=str(item["id"]),
                type=str(item["type"]),
                kinds=[str(kind) for kind in item.get("kinds", [])],
                metric=str(item.get("metric", "")),
                value=float(item.get("value", 0)),
                severity=str(item.get("severity", "blocker")),
            )
            for item in data.get("checks", [])
        ]
        return cls(
            name=str(data.get("name", "QA plan")),
            target=str(data.get("target", "simulator")),
            policy=str(data.get("policy", "heuristic")),
            steps=int(data.get("steps", 160)),
            minutes=float(data.get("minutes", 20.0)),
            seed=int(data.get("seed", 7)),
            record_video=bool(data.get("record_video", True)),
            video_fps=int(data.get("video_fps", 6)),
            capture=str(data.get("capture", "frames")),
            install=bool(data.get("install", True)),
            checks=checks,
            ignore=[str(pattern) for pattern in data.get("ignore", [])],
            notes=str(data.get("notes", "")),
            interruptions=[str(kind) for kind in data.get("interruptions", [])],
            interrupt_every=int(data.get("interrupt_every", 25)),
            startup_runs=int(data.get("startup_runs", 0)),
        )

    @classmethod
    def from_json(cls, text: str) -> "Plan":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanError([f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]) from exc
        return cls.from_dict(data)

    @property
    def targets(self) -> List[str]:
        return ["simulator", "device"]


def default_plan(target: str = "simulator", package: str = "") -> Plan:
    """A sensible starting plan for a game APK."""
    plan = Plan(
        name="Game smoke test",
        target=target,
        policy="heuristic",
        steps=160,
        minutes=20.0,
        seed=7,
        record_video=True,
        capture="screenrecord" if target == "device" else "frames",
        checks=[
            Check(id="no-crash", type="no_findings", kinds=["java_crash", "native_crash"],
                  severity="blocker"),
            Check(id="no-anr", type="no_findings", kinds=["anr", "low_memory"], severity="blocker"),
            Check(id="no-silent-death", type="no_findings", kinds=["process_death"], severity="warning"),
            Check(id="smooth", type="min_metric", metric="avg_fps", value=30, severity="warning"),
            Check(id="memory", type="max_metric", metric="peak_pss_kb", value=1_500_000, severity="warning"),
            Check(id="explore", type="require_screens", value=2, severity="warning"),
        ],
        notes="Defaults tuned for a 2-5 minute session on a mid-range device.",
    )
    return plan


# -- validation ------------------------------------------------------------
def validate_plan_dict(data: Dict[str, Any]) -> List[str]:
    """Return a list of human readable problems; empty means valid."""
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["plan must be a JSON object"]

    known_top = {
        "name", "target", "policy", "steps", "minutes", "seed", "record_video",
        "video_fps", "capture", "install", "checks", "ignore", "notes",
        "interruptions", "interrupt_every", "startup_runs",
    }
    for key in data:
        if key not in known_top:
            errors.append(f"unknown field '{key}' (allowed: {', '.join(sorted(known_top))})")

    if "name" in data and not isinstance(data["name"], str):
        errors.append("'name' must be a string")

    target = data.get("target", "simulator")
    if target not in ("simulator", "device"):
        errors.append("'target' must be 'simulator' or 'device'")

    policy = data.get("policy", "heuristic")
    if policy not in POLICIES:
        errors.append(f"'policy' must be one of {', '.join(POLICIES)}")

    steps = data.get("steps", 160)
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= MAX_STEPS:
        errors.append(f"'steps' must be an integer between 1 and {MAX_STEPS}")

    minutes = data.get("minutes", 20.0)
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        errors.append("'minutes' must be a positive number")

    seed = data.get("seed", 7)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        errors.append("'seed' must be a non-negative integer")

    video_fps = data.get("video_fps", 6)
    if not isinstance(video_fps, int) or isinstance(video_fps, bool) or not 1 <= video_fps <= 30:
        errors.append("'video_fps' must be an integer between 1 and 30")

    capture = data.get("capture", "frames")
    if capture not in CAPTURE_MODES:
        errors.append(f"'capture' must be one of {', '.join(CAPTURE_MODES)}")

    if "install" in data and not isinstance(data["install"], bool):
        errors.append("'install' must be true or false")

    if "record_video" in data and not isinstance(data["record_video"], bool):
        errors.append("'record_video' must be true or false")

    interruptions = data.get("interruptions", [])
    if not isinstance(interruptions, list) or any(k not in INTERRUPTION_KINDS for k in interruptions):
        errors.append(f"'interruptions' must be a list of: {', '.join(INTERRUPTION_KINDS)}")
    every = data.get("interrupt_every", 25)
    if not isinstance(every, int) or isinstance(every, bool) or not 3 <= every <= 10_000:
        errors.append("'interrupt_every' must be an integer between 3 and 10000 (steps)")
    startup_runs = data.get("startup_runs", 0)
    if not isinstance(startup_runs, int) or isinstance(startup_runs, bool) or not 0 <= startup_runs <= 10:
        errors.append("'startup_runs' must be an integer between 0 and 10")

    ignore = data.get("ignore", [])
    if not isinstance(ignore, list) or any(not isinstance(item, str) for item in ignore):
        errors.append("'ignore' must be a list of regular expression strings")
    else:
        for pattern in ignore:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"ignore pattern {pattern!r} is not a valid regex: {exc}")

    checks = data.get("checks", [])
    if not isinstance(checks, list):
        errors.append("'checks' must be a list")
        return errors
    seen_ids = set()
    for index, item in enumerate(checks):
        where = f"checks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            errors.append(f"{where} needs a non-empty string 'id'")
        elif check_id in seen_ids:
            errors.append(f"{where} duplicate check id {check_id!r}")
        else:
            seen_ids.add(check_id)
        check_type = item.get("type")
        if check_type not in CHECK_TYPES:
            errors.append(f"{where} unknown type {check_type!r} (allowed: {', '.join(sorted(CHECK_TYPES))})")
            continue
        severity = item.get("severity", "blocker")
        if severity not in SEVERITIES:
            errors.append(f"{where} 'severity' must be one of {', '.join(SEVERITIES)}")

        if check_type in ("no_findings", "max_findings"):
            kinds = item.get("kinds", [])
            if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
                errors.append(f"{where} 'kinds' must be a list of strings")
            else:
                unknown = [kind for kind in kinds if kind not in FINDING_KINDS]
                if unknown:
                    errors.append(
                        f"{where} unknown finding kind(s) {', '.join(unknown)} "
                        f"(allowed: {', '.join(FINDING_KINDS)})"
                    )
            if check_type == "max_findings":
                value = item.get("value")
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    errors.append(f"{where} needs a non-negative number 'value'")

        if check_type in ("min_metric", "max_metric", "require_metric"):
            metric = item.get("metric")
            if metric not in METRICS:
                errors.append(f"{where} unknown metric {metric!r} (allowed: {', '.join(sorted(METRICS))})")

        if check_type in ("min_metric", "max_metric", "require_screens"):
            value = item.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{where} needs a numeric 'value'")
    return errors


def parse_plan(text: str) -> Plan:
    """Parse + validate plan JSON, raising :class:`PlanError` with all problems."""
    return Plan.from_json(text)


# -- evaluation ------------------------------------------------------------
@dataclass
class CheckResult:
    id: str
    type: str
    severity: str
    passed: bool
    title: str
    expected: str = ""
    actual: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _matches_ignore(finding: Dict[str, Any], patterns: Iterable[re.Pattern]) -> bool:
    haystack = f"{finding.get('signature', '')} {finding.get('message', '')}"
    return any(pattern.search(haystack) for pattern in patterns)


def filter_findings(
    findings: List[Dict[str, Any]], ignore: Iterable[str]
) -> List[Dict[str, Any]]:
    """Drop findings whose signature/message matches an ignore regex."""
    compiled = []
    for pattern in ignore:
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            continue
    if not compiled:
        return list(findings)
    return [finding for finding in findings if not _matches_ignore(finding, compiled)]


def evaluate(
    plan: Plan,
    summary: Dict[str, Any],
    findings: List[Dict[str, Any]],
) -> List[CheckResult]:
    """Evaluate every check in the plan against a finished session."""
    findings = filter_findings(findings, plan.ignore)
    results: List[CheckResult] = []

    for check in plan.checks:
        if check.type in ("no_findings", "max_findings"):
            matched = [
                finding
                for finding in findings
                if not check.kinds or finding.get("kind") in check.kinds
            ]
            count = len(matched)
            limit = 0 if check.type == "no_findings" else int(check.value)
            detail = ""
            if matched:
                detail = "; ".join(
                    f"step {finding.get('step')}: {finding.get('message', '')[:90]}"
                    for finding in matched[:4]
                )
                if len(matched) > 4:
                    detail += f"; +{len(matched) - 4} more"
            results.append(
                CheckResult(
                    id=check.id,
                    type=check.type,
                    severity=check.severity,
                    passed=count <= limit,
                    title=check.title,
                    expected=f"<= {limit}",
                    actual=str(count),
                    detail=detail,
                )
            )
            continue

        if check.type == "require_screens":
            actual = summary.get("screens_explored")
            results.append(
                CheckResult(
                    id=check.id,
                    type=check.type,
                    severity=check.severity,
                    passed=bool(actual is not None and actual >= check.value),
                    title=check.title,
                    expected=f">= {_num(check.value)}",
                    actual=str(actual),
                )
            )
            continue

        # metric checks
        actual = summary.get(check.metric)
        label = METRICS.get(check.metric, {}).get("label", check.metric)
        unit = METRICS.get(check.metric, {}).get("unit", "")
        if check.type == "require_metric":
            results.append(
                CheckResult(
                    id=check.id,
                    type=check.type,
                    severity=check.severity,
                    passed=actual is not None,
                    title=check.title,
                    expected=f"{label} measured",
                    actual=f"{actual}{unit}" if actual is not None else "not measured",
                )
            )
            continue

        if actual is None:
            results.append(
                CheckResult(
                    id=check.id,
                    type=check.type,
                    severity=check.severity,
                    passed=False,
                    title=check.title,
                    expected=f"{label} {'>=' if check.type == 'min_metric' else '<='} {_num(check.value)}{unit}",
                    actual="not measured",
                    detail="the session produced no sample for this metric",
                )
            )
            continue

        passed = actual >= check.value if check.type == "min_metric" else actual <= check.value
        results.append(
            CheckResult(
                id=check.id,
                type=check.type,
                severity=check.severity,
                passed=passed,
                title=check.title,
                expected=f"{'>= ' if check.type == 'min_metric' else '<= '}{_num(check.value)}{unit}",
                actual=f"{actual:g}{unit}" if isinstance(actual, (int, float)) else str(actual),
            )
        )
    return results


def verdict(results: List[CheckResult]) -> str:
    """'pass', 'warn' or 'fail' for a list of check results."""
    blockers = [result for result in results if result.severity == "blocker"]
    warnings = [result for result in results if result.severity != "blocker"]
    if any(not result.passed for result in blockers):
        return "fail"
    if any(not result.passed for result in warnings):
        return "warn"
    return "pass"


def summarize(results: List[CheckResult]) -> Dict[str, Any]:
    """Counts used by the UI and JUnit output."""
    return {
        "verdict": verdict(results),
        "total": len(results),
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed),
        "failed_blockers": sum(
            1 for result in results if not result.passed and result.severity == "blocker"
        ),
    }
