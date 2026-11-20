"""Real-life interruptions and start-up timing, driven over plain adb.

Most crashes users hit are not caused by tapping - they come from the app being
paused, rotated, starved of memory, cut off from the network or killed by the OS
and restored. These are the lifecycle tests a senior QA engineer runs on every
build; here they are automated so every session includes them.

Every probe is best-effort: a command the device refuses (old Android, OEM
restrictions) is logged as ``skipped`` instead of failing the session.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

INTERRUPTIONS: Dict[str, str] = {
    "background": "Home → wait → bring the app back (onPause/onResume)",
    "rotate": "Force landscape then portrait (configuration change)",
    "lock": "Screen off → wake → unlock (onStop/onStart)",
    "airplane": "Airplane mode on for a few seconds, then off (network loss)",
    "memory": "System memory pressure signal (onTrimMemory RUNNING_CRITICAL)",
    "kill_restore": "OS kills the app in background → user returns (state restore)",
}

KEY_HOME, KEY_POWER, KEY_MENU, KEY_WAKEUP = 3, 26, 82, 224


def _sh(adb: Any, command: str, timeout: float = 20.0) -> str:
    try:
        return adb.shell(command, timeout=timeout) or ""
    except Exception as exc:  # adb refusal must never end the session
        return f"ERROR {exc}"


def _bring_back(adb: Any, package: str, activity: str) -> None:
    if activity:
        _sh(adb, f"am start -n {activity}")
    else:
        _sh(adb, f"monkey -p {package} -c android.intent.category.LAUNCHER 1")


def adb_interrupt(adb: Any, kind: str, package: str, activity: str = "") -> str:
    """Perform one interruption on a real device; returns a short detail string."""
    if kind == "background":
        _sh(adb, f"input keyevent {KEY_HOME}")
        time.sleep(2.0)
        _bring_back(adb, package, activity)
        return "home 2s → resumed"
    if kind == "rotate":
        auto = _sh(adb, "settings get system accelerometer_rotation").strip()
        _sh(adb, "settings put system accelerometer_rotation 0")
        _sh(adb, "settings put system user_rotation 1")
        time.sleep(1.8)
        _sh(adb, "settings put system user_rotation 0")
        time.sleep(1.0)
        if auto in ("0", "1"):
            _sh(adb, f"settings put system accelerometer_rotation {auto}")
        return "landscape 1.8s → portrait"
    if kind == "lock":
        _sh(adb, f"input keyevent {KEY_POWER}")
        time.sleep(2.0)
        _sh(adb, f"input keyevent {KEY_WAKEUP}")
        time.sleep(0.6)
        _sh(adb, "wm dismiss-keyguard")
        _sh(adb, f"input keyevent {KEY_MENU}")
        time.sleep(0.8)
        return "screen off 2s → unlocked"
    if kind == "airplane":
        out = _sh(adb, "cmd connectivity airplane-mode enable")
        if "ERROR" in out or "Unknown" in out or "Exception" in out:
            _sh(adb, "settings put global airplane_mode_on 1")
            _sh(adb, "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true")
        time.sleep(4.0)
        out2 = _sh(adb, "cmd connectivity airplane-mode disable")
        if "ERROR" in out2 or "Unknown" in out2 or "Exception" in out2:
            _sh(adb, "settings put global airplane_mode_on 0")
            _sh(adb, "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false")
        time.sleep(1.0)
        return "offline 4s → online"
    if kind == "memory":
        out = _sh(adb, f"am send-trim-memory {package} RUNNING_CRITICAL")
        if "ERROR" in out or "Error" in out:
            return "skipped: device refused send-trim-memory"
        time.sleep(1.0)
        return "onTrimMemory(RUNNING_CRITICAL) sent"
    if kind == "kill_restore":
        _sh(adb, f"input keyevent {KEY_HOME}")
        time.sleep(1.2)
        _sh(adb, f"am kill {package}")  # kills only a backgrounded process, like the OS does
        time.sleep(1.0)
        _bring_back(adb, package, activity)
        time.sleep(1.5)
        return "killed in background → relaunched from recents"
    return f"skipped: unknown interruption {kind!r}"


_TOTAL = re.compile(r"TotalTime:\s*(\d+)")
_WAIT = re.compile(r"WaitTime:\s*(\d+)")


def _start_ms(output: str) -> Optional[int]:
    match = _TOTAL.search(output) or _WAIT.search(output)
    return int(match.group(1)) if match else None


def adb_startup(adb: Any, package: str, activity: str = "", runs: int = 3) -> Dict[str, Any]:
    """Cold and warm start times via ``am start -W`` (what Play Console vitals measure)."""
    if not activity:
        try:
            activity = adb.resolve_launch_activity(package)
        except Exception:
            activity = ""
    if not activity:
        return {"error": "launcher activity unknown - start time not measured"}
    cold: List[int] = []
    warm: List[int] = []
    for _ in range(max(1, runs)):
        _sh(adb, f"am force-stop {package}")
        time.sleep(1.0)
        ms = _start_ms(_sh(adb, f"am start -W -n {activity}", timeout=60))
        if ms is not None:
            cold.append(ms)
        time.sleep(2.5)
        _sh(adb, f"input keyevent {KEY_HOME}")
        time.sleep(1.2)
        ms = _start_ms(_sh(adb, f"am start -W -n {activity}", timeout=60))
        if ms is not None:
            warm.append(ms)
        time.sleep(1.5)
    return summarize_startup(cold, warm)


def summarize_startup(cold: List[int], warm: List[int]) -> Dict[str, Any]:
    def avg(values: List[int]) -> Optional[int]:
        return int(sum(values) / len(values)) if values else None

    return {"cold_ms": cold, "warm_ms": warm, "cold_avg_ms": avg(cold), "warm_avg_ms": avg(warm),
            "cold_max_ms": max(cold) if cold else None}


MIN_TREND_SPAN_S = 60


def memory_trend(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Least-squares slope of PSS over time: a steady climb is the classic leak signature."""
    points = [(float(s["elapsed_s"]), float(s["total_pss_kb"])) for s in samples
              if s.get("elapsed_s") is not None and s.get("total_pss_kb")]
    if len(points) < 4:
        return {"samples": len(points), "growth_kb_per_min": None}
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    var = sum((p[0] - mean_x) ** 2 for p in points)
    if var <= 0:
        return {"samples": n, "growth_kb_per_min": None}
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / var  # kB per second
    span = points[-1][0] - points[0][0]
    if span < MIN_TREND_SPAN_S:  # a short warm-up climb is not a leak; don't extrapolate it
        return {"samples": n, "growth_kb_per_min": None, "span_s": round(span, 1),
                "note": f"session too short for a leak verdict (needs {MIN_TREND_SPAN_S}s of samples)"}
    return {"samples": n, "growth_kb_per_min": round(slope * 60, 1), "span_s": round(span, 1),
            "start_kb": int(points[0][1]), "end_kb": int(points[-1][1])}
