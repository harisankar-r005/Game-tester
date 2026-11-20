"""The test checklist: everything a session was meant to check, each marked
passed / failed / not tested / skipped / needs a person.

"Not tested" is explicit, so a stopped or cut-short session never looks like a clean pass.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

END_REASONS = {
    "completed": "Finished – every planned step ran",
    "stopped": "Stopped by you before the end",
    "phone_lost": "Phone disconnected before the end",
    "time_limit": "Time limit reached before all steps ran",
    "section_complete": "Section complete – ready for the next section",
    "section_time_limit": "Section paused at the time limit – resume to continue",
    "stuck": "Paused for help – exploration stayed on the same screen",
    "recovered": "Saved progress restored – ready to continue",
    "input_unconfirmed": "Run includes an input whose delivery could not be confirmed",
    "app_kept_closing": "Ended early – the game kept closing",
    "too_many_crashes": "Ended early – too many crashes",
    "ended_early": "Ended before all planned steps ran",
}

INTERRUPT_NAMES = {
    "background": "Leave the game and come back",
    "rotate": "Turn the phone sideways",
    "lock": "Lock and unlock the phone",
    "airplane": "Lose internet",
    "memory": "Phone low on memory",
    "kill_restore": "Android closes the game in the background",
}


def exploration_coverage(payload: Dict[str, Any]) -> tuple[int, int, str]:
    summary = payload.get("summary") or {}
    config = payload.get("config") or {}
    plan = (payload.get("meta") or {}).get("plan") or {}
    steps_run = int(summary.get("steps_run") or 0)
    steps_planned = int(summary.get("steps_requested") or config.get("steps") or plan.get("steps") or steps_run or 0)
    reason = summary.get("end_reason") or (
        "phone_lost" if summary.get("device_lost") else "stopped" if summary.get("stopped_by_user")
        else "completed" if steps_planned and steps_run >= steps_planned else "ended_early")
    if reason == "completed" and summary.get("unconfirmed_inputs"):
        reason = "input_unconfirmed"
    elif reason == "completed" and steps_run < steps_planned:
        reason = "ended_early"
    return steps_run, steps_planned, reason


def test_checklist(payload: Dict[str, Any], cases: Sequence[Dict[str, Any]] = (),
                   product: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    summary = payload.get("summary") or {}
    config = payload.get("config") or {}
    plan = (payload.get("meta") or {}).get("plan") or {}
    findings = list(payload.get("crashes") or [])
    steps_run, steps_planned, reason = exploration_coverage(payload)
    ended_early = reason != "completed"
    resumable = bool(summary.get("resume_available", reason.startswith("section_")))
    cut = f"pending – paused at step {steps_run}" if resumable else (
        f"not reached – the test ended at step {steps_run}" if ended_early else "not part of this test")
    game = (product or {}).get("kind", "game") == "game"
    items: List[Dict[str, Any]] = []

    def add(group: str, name: str, status: str, detail: str = "") -> None:
        items.append({"group": group, "name": name, "status": status, "detail": detail})

    # 1. opening the game
    startup_runs = summary.get("startup_runs", config.get("startup_runs", plan.get("startup_runs", 0))) or 0
    cold = summary.get("cold_start_ms")
    limit = 5000 if game else 2000
    if cold:
        add("Opening the game", "Opens fast enough", "passed" if cold <= limit else "failed",
            f"{cold / 1000:.1f} s (target under {limit / 1000:.0f} s)")
    else:
        add("Opening the game", "Opens fast enough", "not_run",
            "could not be measured on this phone" if startup_runs else "not measured in this test")

    # 2. playing
    pct = int(round(100 * steps_run / steps_planned)) if steps_planned else 0
    add("Playing the game", f"Play {steps_planned} steps", "partial" if ended_early else "passed",
        f"{steps_run} of {steps_planned} steps done ({pct}%)")
    kinds = Counter(str(f.get("kind")) for f in findings)
    crashes = kinds["java_crash"] + kinds["native_crash"]
    part = " (only part of the game was played)" if ended_early else ""
    clean = ("partial" if ended_early else "passed") if steps_run else "not_run"
    add("Playing the game", "No crashes", "failed" if crashes else clean,
        f"{crashes} crash type(s) found" if crashes else "none while playing" + part)
    add("Playing the game", "No freezes", "failed" if kinds["anr"] else clean,
        f"{kinds['anr']} freeze(s)" if kinds["anr"] else "none" + part)
    deaths = kinds["process_death"]
    add("Playing the game", "Game never disappears", "failed" if deaths else clean,
        f"disappeared {deaths} time(s)" if deaths else "never" + part)
    screens = summary.get("screens_explored") or 0
    add("Playing the game", "Reaches different screens",
        "passed" if screens >= 3 else ("partial" if ended_early and steps_run else "failed" if steps_run else "not_run"),
        f"{screens} screens visited")

    # 3. real-life events
    events = list(payload.get("interruptions") or [])
    planned = list(summary.get("planned_interruptions") or config.get("interruptions") or plan.get("interruptions") or [])
    for kind in planned or list(dict.fromkeys(e.get("kind") for e in events)):
        mine = [e for e in events if e.get("kind") == kind]
        done = [e for e in mine if not e.get("skipped")]
        name = INTERRUPT_NAMES.get(kind, kind)
        failed = [e for e in done if not e.get("survived")]
        if failed:
            add("Real-life events", name, "failed", f"the game did not survive it (step {failed[0].get('step')})")
        elif done:
            add("Real-life events", name, "passed", f"survived {len(done)} time(s)")
        elif mine:
            add("Real-life events", name, "skipped", "this phone does not allow this test")
        else:
            add("Real-life events", name, "not_run", cut)

    # 4. speed, memory, battery
    fps, low = summary.get("avg_fps"), summary.get("min_fps")
    add("Speed & battery", "Smooth to play", "not_run" if fps is None else ("passed" if fps >= 30 else "failed"),
        "could not be measured" if fps is None else f"{fps:.0f} fps (target 30+)")
    add("Speed & battery", "No big stutters", "not_run" if low is None else ("passed" if low >= 15 else "failed"),
        "could not be measured" if low is None else f"worst moment {low:.0f} fps (target 15+)")
    peak = summary.get("peak_pss_kb")
    mem_limit = 1_500_000 if game else 600_000
    add("Speed & battery", "Memory use OK", "not_run" if not peak else ("passed" if peak <= mem_limit else "failed"),
        "could not be measured" if not peak else f"{peak / 1024:.0f} MB (target under {mem_limit / 1024:.0f} MB)")
    growth = summary.get("mem_growth_kb_per_min")
    add("Speed & battery", "No memory leak",
        "not_run" if growth is None else ("passed" if growth <= (20000 if game else 8000) else "failed"),
        "the test was too short to tell (needs 1+ minute of play)" if growth is None else f"{growth / 1024:+.0f} MB per minute")
    temp = summary.get("max_battery_temp_c")
    add("Speed & battery", "Phone does not overheat", "not_run" if temp is None else ("passed" if temp <= 43 else "failed"),
        "could not be measured" if temp is None else f"{temp} °C (target under 43 °C)")

    # 5. requirements document
    for case in cases:
        status = {"PASS": "passed", "FAIL": "failed", "NOT_VERIFIED": "not_run", "MANUAL": "manual"}.get(
            str(case.get("auto_status")), "not_run")
        add("From your requirements", str(case.get("title") or case.get("id") or ""), status, str(case.get("reason") or ""))

    counts = Counter(item["status"] for item in items)
    return {
        "end_reason": reason,
        "end_text": END_REASONS.get(reason, reason),
        "ended_early": ended_early,
        "resumable": resumable,
        "steps_run": steps_run,
        "steps_planned": steps_planned,
        "percent": pct,
        "items": items,
        "counts": {"passed": counts["passed"], "failed": counts["failed"],
                   "not_tested": counts["not_run"] + counts["partial"], "skipped": counts["skipped"],
                   "manual": counts["manual"]},
    }
