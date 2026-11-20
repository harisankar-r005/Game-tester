"""QA dashboard: every past session under ``<workdir>/runs`` at a glance.

Reads only the files a run already writes (``session.json``, ``checks.json``),
so it works for runs started from the studio *and* from the CLI.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from .checklist import exploration_coverage

RUN_ARTIFACTS = ("report.html", "junit.xml", "session.json", "checks.json", "logcat.txt",
                 "metrics.json", "session.gif", "session.mp4", "qa_review.md", "qa_review.json")
RECORDING_PART = re.compile(r"session-part-\d+\.mp4")


def _load(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def summarize_run(run_dir: str) -> Dict[str, Any]:
    name = os.path.basename(run_dir.rstrip("/\\"))
    session = _load(os.path.join(run_dir, "session.json")) or {}
    summary = session.get("summary") or {}
    meta = session.get("meta") or {}
    config = session.get("config") or {}
    checks = _load(os.path.join(run_dir, "checks.json"))
    if not isinstance(checks, list):
        checks = session.get("checks") if isinstance(session.get("checks"), list) else []
    check_summary = summary.get("check_summary") or {}
    verdict = check_summary.get("verdict") or summary.get("verdict") or ("incomplete" if not session else "unknown")
    if meta.get("kind") != "test_cases" and exploration_coverage(session)[2] != "completed":
        verdict = "incomplete"
    stamp, _, package = name.partition("_")
    time_part, _, package = package.partition("_")
    when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}" \
        if len(stamp) == 8 and len(time_part) == 6 else ""
    findings = session.get("crashes") if isinstance(session.get("crashes"), list) else []
    return {
        "id": name,
        "when": when,
        "package": meta.get("package") or config.get("package") or package or "",
        "target": "simulator" if "simulator" in json.dumps(meta).lower() else (config.get("target") or ""),
        "verdict": str(verdict).lower(),
        "checks_total": check_summary.get("total", len(checks)),
        "checks_failed": check_summary.get("failed", sum(1 for c in checks if not c.get("passed"))),
        "failed_checks": [c.get("title") or c.get("id") for c in checks if not c.get("passed")],
        "steps": summary.get("steps_run"),
        "duration_s": summary.get("duration_s"),
        "unique_crashes": summary.get("unique_crashes", len(findings)),
        "java_crashes": summary.get("java_crashes"),
        "native_crashes": summary.get("native_crashes"),
        "anr_count": summary.get("anr_count"),
        "screens": summary.get("screens_explored"),
        "avg_fps": summary.get("avg_fps"),
        "peak_pss_kb": summary.get("peak_pss_kb"),
        "signatures": sorted({str(f.get("signature") or f.get("message") or "")[:160] for f in findings} - {""}),
        "artifacts": [a for a in RUN_ARTIFACTS if os.path.exists(os.path.join(run_dir, a))]
        + sorted(a for a in os.listdir(run_dir) if RECORDING_PART.fullmatch(a)),
    }


PRACTICE_PACKAGES = ("com.example.neondrift",)


def list_games(runs_dir: str) -> Dict[str, Any]:
    """One card per game: how often it was tested, how it did last time, and the trend."""
    runs = list_runs(runs_dir)["runs"]  # newest first
    games: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        package = run.get("package") or "unknown"
        game = games.setdefault(package, {
            "package": package, "practice": package in PRACTICE_PACKAGES, "tests": 0,
            "pass": 0, "warn": 0, "fail": 0, "unfinished": 0, "trend": [], "last": None,
            "crash_types": set(), "fps": [], "versions": set(),
        })
        game["tests"] += 1
        verdict = run.get("verdict")
        key = verdict if verdict in ("pass", "warn", "fail") else "unfinished"
        game[key] += 1
        if len(game["trend"]) < 8:
            game["trend"].append(key)
        if run.get("avg_fps"):
            game["fps"].append(run["avg_fps"])
        for sig in run.get("signatures") or []:
            game["crash_types"].add(sig[:80])
        if game["last"] is None:
            review = _load(os.path.join(runs_dir, run["id"], "qa_review.json")) or {}
            session = _load(os.path.join(runs_dir, run["id"], "session.json")) or {}
            game["last"] = {
                "id": run["id"], "when": run.get("when"), "verdict": key,
                "decision": review.get("decision") or "",
                "version": _version(session),
                "on": "practice phone" if run.get("target") == "simulator" else "real phone",
            }
    out = []
    for game in games.values():
        fps = game.pop("fps")
        game["avg_fps"] = round(sum(fps) / len(fps), 1) if fps else None
        game["crash_types"] = len(game["crash_types"])
        game.pop("versions")
        game["trend"].reverse()  # oldest → newest for drawing
        out.append(game)
    out.sort(key=lambda g: (g["practice"], -(g["tests"])))
    return {"games": out}


def list_runs(runs_dir: str) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = []
    if os.path.isdir(runs_dir):
        for entry in sorted(os.listdir(runs_dir), reverse=True):
            path = os.path.join(runs_dir, entry)
            if os.path.isdir(path):
                runs.append(summarize_run(path))
    totals = {"runs": len(runs), "pass": 0, "warn": 0, "fail": 0, "other": 0}
    for run in runs:
        key = run["verdict"] if run["verdict"] in ("pass", "warn", "fail") else "other"
        totals[key] += 1
    # recurring crash signatures across runs = the QA team's bug list
    seen: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        for sig in run["signatures"]:
            item = seen.setdefault(sig, {"signature": sig, "runs": 0, "first": run["id"], "last": run["id"]})
            item["runs"] += 1
            item["first"] = run["id"]  # runs are newest first, so the last write is the oldest
    issues = sorted(seen.values(), key=lambda item: -item["runs"])
    return {"totals": totals, "runs": runs, "issues": issues}


CASE_SHOT = re.compile(r"^cases/[A-Za-z0-9._-]{1,120}\.png$")


def run_artifact_path(runs_dir: str, run_id: str, name: str) -> str:
    # fixed report files, the test-case results, or a per-case screenshot – nothing else
    if name not in RUN_ARTIFACTS and name != "case_results.json" and not CASE_SHOT.match(name) and not RECORDING_PART.fullmatch(name):
        raise ValueError(f"unknown artifact {name!r}")
    if ".." in name:
        raise ValueError("bad artifact name")
    if not run_id or run_id != os.path.basename(run_id) or run_id in (".", ".."):
        raise ValueError("bad run id")
    path = os.path.join(runs_dir, run_id, name)
    if not os.path.isfile(path):
        raise ValueError(f"{name} not found for run {run_id}")
    return path


def _run_dir(runs_dir: str, run_id: str) -> str:
    if not run_id or run_id != os.path.basename(run_id) or run_id in (".", ".."):
        raise ValueError("bad run id")
    path = os.path.join(runs_dir, run_id)
    if not os.path.isdir(path):
        raise ValueError(f"run {run_id} not found")
    return path


def _log_lines(run_dir: str) -> List[str]:
    try:
        with open(os.path.join(run_dir, "logcat.txt"), encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def run_log(runs_dir: str, run_id: str, tail: int = 800) -> Dict[str, Any]:
    lines = _log_lines(_run_dir(runs_dir, run_id))
    return {"run": run_id, "total": len(lines), "lines": lines[-tail:]}


def run_review(runs_dir: str, run_id: str, suite: Any = None) -> Dict[str, Any]:
    """Stored expert review, or one computed now for runs made before the engine existed."""
    from .autoqa import classify_apk, expert_review
    from .run import CHECKPOINT_FILE

    run_dir = _run_dir(runs_dir, run_id)
    cases = _load(os.path.join(run_dir, "case_results.json"))
    if isinstance(cases, dict) and cases.get("results") is not None:  # a run of written test cases
        return dict(cases, kind="test_cases", run=run_id)
    session = _load(os.path.join(run_dir, "session.json")) or {}
    stored = _load(os.path.join(run_dir, "qa_review.json"))
    summary = session.get("summary") or {}
    old_pause = summary.get("resume_available", str(summary.get("end_reason", "")).startswith("section_"))
    if old_pause and not os.path.isfile(os.path.join(run_dir, CHECKPOINT_FILE)):
        session["summary"] = dict(summary, resume_available=False)
        product = stored.get("product") if isinstance(stored, dict) else None
        return expert_review(session, product, suite, _log_lines(run_dir))
    if (isinstance(stored, dict) and stored.get("decision") != "INCOMPLETE"
            and exploration_coverage(session)[2] != "completed"):
        return expert_review(session, stored.get("product"), suite, _log_lines(run_dir))
    if isinstance(stored, dict):
        if "checklist" not in stored:  # saved before the checklist existed
            from .checklist import test_checklist

            stored["checklist"] = test_checklist(session, stored.get("cases") or [], stored.get("product"))
        return stored
    package = str((session.get("meta") or {}).get("package") or "")
    apk = str((session.get("config") or {}).get("apk") or "")
    product = classify_apk(apk, package) if apk and os.path.exists(apk) else {"kind": "game", "engine": "unknown",
                                                                            "evidence": []}
    comparison = None
    baseline = find_baseline(runs_dir, run_id)
    if baseline:
        try:
            comparison = compare_runs(runs_dir, run_id, baseline)
        except ValueError:
            comparison = None
    review = expert_review(session, product, suite, _log_lines(run_dir), comparison)
    review["computed_later"] = True
    return review


#: metric → (label, unit, which direction is better, % change that counts as a regression)
COMPARE_METRICS = (
    ("avg_fps", "average FPS", "fps", "higher", 10),
    ("min_fps", "minimum FPS", "fps", "higher", 15),
    ("avg_jank_percent", "janky frames", "%", "lower", 25),
    ("peak_pss_kb", "peak memory", "kB", "lower", 10),
    ("mem_growth_kb_per_min", "memory growth", "kB/min", "lower", 50),
    ("cold_start_ms", "cold start", "ms", "lower", 15),
    ("warm_start_ms", "warm start", "ms", "lower", 20),
    ("avg_cpu_percent", "average CPU", "%", "lower", 20),
    ("max_battery_temp_c", "peak battery temp", "°C", "lower", 8),
    ("screens_explored", "screens reached", "", "higher", 30),
    ("interruptions_failed", "interruptions not survived", "", "lower", 0),
)


def _version(session: Dict[str, Any]) -> str:
    meta = session.get("meta") or {}
    apk = meta.get("apk") or {}
    name = apk.get("version_name") or ""
    code = apk.get("version_code") or ""
    return f"{name} ({code})" if name else (apk.get("sha256", "")[:10] or "")


def compare_runs(runs_dir: str, new_id: str, base_id: str) -> Dict[str, Any]:
    new = _load(os.path.join(_run_dir(runs_dir, new_id), "session.json")) or {}
    base = _load(os.path.join(_run_dir(runs_dir, base_id), "session.json")) or {}
    scope = _comparison_scope(new)
    if scope is None or scope != _comparison_scope(base):
        raise ValueError("Comparison requires completed exploration runs with matching game, device type, test length and phone checks.")
    ns, bs = new.get("summary") or {}, base.get("summary") or {}
    rows, regressions, improvements = [], [], []
    for key, label, unit, better, tolerance in COMPARE_METRICS:
        a, b = bs.get(key), ns.get(key)
        row = {"metric": key, "label": label, "unit": unit, "base": a, "new": b, "change_pct": None, "status": "same"}
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if a:
                row["change_pct"] = round((b - a) * 100.0 / abs(a), 1)
            worse = (b < a) if better == "higher" else (b > a)
            delta = abs(row["change_pct"]) if row["change_pct"] is not None else (abs(b - a) * 100)
            if b != a and delta > tolerance:
                row["status"] = "worse" if worse else "better"
                text = f"{label} {a:g} → {b:g}{(' ' + unit) if unit else ''}" + \
                    (f" ({row['change_pct']:+.0f}%)" if row["change_pct"] is not None else "")
                if worse:
                    sev = "S1 critical" if key == "interruptions_failed" else (
                        "S2 major" if delta > tolerance * 2 else "S3 minor")
                    regressions.append({"metric": key, "text": text, "severity": sev})
                else:
                    improvements.append(text)
        rows.append(row)
    sig = lambda s: {str(c.get("signature") or c.get("message") or "")[:160] for c in s.get("crashes") or []}
    new_sigs, base_sigs = sig(new), sig(base)
    new_crashes = sorted(new_sigs - base_sigs - {""})
    fixed = sorted(base_sigs - new_sigs - {""})
    for crash in new_crashes:
        silent = crash.startswith(("process vanished", "died after"))
        regressions.insert(0, {"metric": "crash", "text": f"NEW crash: {crash}",
                               "severity": "S2 major" if silent else "S1 critical"})
    verdict_new = ((ns.get("check_summary") or {}).get("verdict") or ns.get("verdict") or "")
    verdict_base = ((bs.get("check_summary") or {}).get("verdict") or bs.get("verdict") or "")
    return {
        "new": {"id": new_id, "version": _version(new), "verdict": verdict_new},
        "base": {"id": base_id, "version": _version(base), "verdict": verdict_base},
        "baseline_label": f"{_version(base) or base_id}",
        "rows": rows,
        "new_crashes": new_crashes,
        "fixed_crashes": fixed,
        "regressions": regressions,
        "improvements": improvements,
        "headline": (f"{len(new_crashes)} new crash(es), {len(fixed)} fixed, "
                     f"{len([r for r in regressions if r['metric'] != 'crash'])} metric regression(s), "
                     f"{len(improvements)} improvement(s)"),
    }


def _comparison_scope(session: Dict[str, Any]) -> tuple | None:
    meta, summary = session.get("meta") or {}, session.get("summary") or {}
    _steps, planned, reason = exploration_coverage(session)
    if reason != "completed" or not planned or not meta.get("package") or meta.get("kind") == "test_cases":
        return None
    config = session.get("config") or {}
    events = tuple((event.get("step"), event.get("kind"), bool(event.get("skipped")))
                   for event in session.get("interruptions") or [])
    return (meta["package"], meta.get("backend"), meta.get("model"), meta.get("policy") or config.get("policy"),
            planned, config.get("gameplay_objective") or "", summary.get("startup_runs") or config.get("startup_runs"), events)


def find_baseline(runs_dir: str, run_id: str) -> str:
    """Most recent earlier finished run of the same package - preferring a different build."""
    try:
        current = _load(os.path.join(_run_dir(runs_dir, run_id), "session.json")) or {}
    except ValueError:
        return ""
    scope = _comparison_scope(current)
    if scope is None:
        return ""
    build = _build_id(current)
    same_build = ""
    for entry in sorted(os.listdir(runs_dir), reverse=True):
        if entry >= run_id or not os.path.isdir(os.path.join(runs_dir, entry)):
            continue
        other = _load(os.path.join(runs_dir, entry, "session.json")) or {}
        if _comparison_scope(other) != scope:
            continue
        if build and _build_id(other) and _build_id(other) != build:
            return entry
        same_build = same_build or entry
    return same_build


def _build_id(session: Dict[str, Any]) -> str:
    """APK hash identifies a build exactly; version name is the fallback."""
    apk = (session.get("meta") or {}).get("apk") or {}
    return str(apk.get("sha256") or apk.get("version_code") or apk.get("version_name") or "")


from .dashboard_ui import DASHBOARD_HTML  # noqa: E402,F401  (page lives in its own module)
