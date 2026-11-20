"""Automatic QA engine: the judgement a senior QA lead applies to every build.

Three jobs, all offline and standard-library only:

1. :func:`classify_apk` - is this a **game** or an **app**, and on which engine?
   (native libraries and asset layout give it away: libunity.so, libUE4.so, libflutter.so…)
2. :func:`expert_plan` - a test plan tuned for that kind of product *and* for what the
   requirements document (the uploaded ``.md`` spec) says matters.
3. :func:`expert_review` - after a session: triage every finding the way an experienced
   tester would (severity, priority, likely root cause, reproduction steps), scan logcat
   for warning signs that are not crashes yet, map results onto the spec's test cases
   and give a release recommendation (GO / CONDITIONAL / NO-GO) with a risk score.

The rules are deliberately explicit so a QA team can read and argue with them.
"""

from __future__ import annotations

import os
import re
import time
import zipfile
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .checklist import exploration_coverage, test_checklist
from .plan import Check, Plan

# -- 1. product classification ------------------------------------------------

#: (substring in a zip entry name, engine, is_game)
ENGINE_MARKERS = (
    ("libunity.so", "Unity", True),
    ("libil2cpp.so", "Unity (IL2CPP)", True),
    ("assets/bin/Data/", "Unity", True),
    ("libUE4.so", "Unreal Engine 4", True),
    ("libUnreal.so", "Unreal Engine 5", True),
    ("libcocos2dcpp.so", "Cocos2d-x", True),
    ("libcocos", "Cocos", True),
    ("libgodot_android.so", "Godot", True),
    ("libgdx.so", "libGDX", True),
    ("libGameMaker", "GameMaker", True),
    ("libdefold", "Defold", True),
    ("libsolar2d", "Solar2D", True),
    ("libflutter.so", "Flutter", False),
    ("assets/index.android.bundle", "React Native", False),
    ("libreactnativejni.so", "React Native", False),
    ("libhermes.so", "React Native", False),
    ("assets/www/index.html", "Cordova / Capacitor", False),
    ("libmonodroid.so", "Xamarin / .NET MAUI", False),
)

GAME_HINT_WORDS = ("game", "puzzle", "racing", "rpg", "arcade", "casual", "shooter", "slots",
                   "match3", "match-3", "idle", "runner", "strategy", "quest", "battle", "play")


def classify_apk(path: str, package: str = "") -> Dict[str, Any]:
    """Return ``{"kind": "game"|"app", "engine": str, "evidence": [...]}``."""
    evidence: List[str] = []
    engine = ""
    is_game: Optional[bool] = None
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        names = []
    for marker, name, game in ENGINE_MARKERS:
        hit = next((entry for entry in names if marker in entry), None)
        if hit:
            evidence.append(f"{os.path.basename(hit.rstrip('/')) or hit} → {name}")
            if not engine:
                engine, is_game = name, game
    lowered = (package or "").lower()
    words = [word for word in GAME_HINT_WORDS if word in lowered]
    if words:
        evidence.append(f"package name mentions {', '.join(words)}")
    if is_game is None:
        is_game = bool(words)
        engine = engine or ("native Android (Java/Kotlin)" if names else "unknown")
    if any("libGLESv" in entry or "vulkan" in entry.lower() for entry in names) and not is_game:
        evidence.append("ships its own GL/Vulkan code")
    return {"kind": "game" if is_game else "app", "engine": engine, "evidence": evidence[:8]}


def probe_installed(adb: Any, package: str) -> Dict[str, Any]:
    """Game or app, for an app already on the phone: look at its native libraries there."""
    evidence: List[str] = []
    names: List[str] = []
    try:
        paths = [line.split(":", 1)[1].strip() for line in adb.shell(f"pm path {package}").splitlines()
                 if line.startswith("package:")]
        for apk_path in paths[:1]:
            folder = apk_path.rsplit("/", 1)[0]
            names += adb.shell(f"ls -R {folder}/lib 2>/dev/null").split()
            listing = adb.shell(f"unzip -l {apk_path} 2>/dev/null | grep -E 'lib/|assets/(bin|index)' | head -200")
            names += listing.split()
    except Exception:  # best effort; fall back to the package name
        names = []
    for marker, name, game in ENGINE_MARKERS:
        if any(marker.split("/")[-1] and marker.split("/")[-1] in entry for entry in names):
            evidence.append(f"{marker} on the phone → {name}")
            return {"kind": "game" if game else "app", "engine": name, "evidence": evidence}
    guess = classify_apk("", package)
    guess["evidence"] = guess.get("evidence", []) + ["engine libraries not readable on this phone; guessed from the app id"]
    return guess


# -- 2. plan tuned like a senior tester would --------------------------------

def _features(suite: Any) -> Counter:
    counts: Counter = Counter()
    for case in getattr(suite, "cases", None) or []:
        counts[getattr(case, "feature", "other")] += 1
    return counts


def expert_plan(kind: str, suite: Any = None, base: Optional[Plan] = None, on_device: bool = True,
                step_budget: Optional[int] = None) -> Plan:
    """Build the plan a QA lead would start from for this product."""
    plan = Plan(**{k: getattr(base, k) for k in ("seed", "install", "record_video", "video_fps")}) \
        if base else Plan()
    features = _features(suite)
    plan.target = "device" if on_device else "simulator"
    plan.capture = "both" if on_device else "frames"
    plan.policy = "heuristic"
    checks: List[Check] = [
        Check(id="no-crash", type="no_findings", kinds=["java_crash", "native_crash"]),
        Check(id="no-anr", type="no_findings", kinds=["anr"]),
        Check(id="no-silent-death", type="no_findings", kinds=["process_death"], severity="warning"),
        Check(id="no-low-memory", type="no_findings", kinds=["low_memory"], severity="warning"),
    ]
    if kind == "game":
        plan.name = "Auto QA - game build"
        plan.steps, plan.minutes = 400, 15
        checks += [
            Check(id="fps-avg", type="min_metric", metric="avg_fps", value=30, severity="warning"),
            Check(id="fps-floor", type="min_metric", metric="min_fps", value=15, severity="warning"),
            Check(id="jank", type="max_metric", metric="avg_jank_percent", value=20, severity="warning"),
            Check(id="memory", type="max_metric", metric="peak_pss_kb", value=1_500_000, severity="warning"),
            Check(id="coverage", type="require_screens", value=4, severity="warning"),
        ]
        checks += [
            Check(id="cold-start", type="max_metric", metric="cold_start_ms", value=5000, severity="warning"),
            Check(id="leak", type="max_metric", metric="mem_growth_kb_per_min", value=20000, severity="warning"),
        ]
        notes = ["Game profile: frame-rate and memory budgets enforced."]
    else:
        plan.name = "Auto QA - app build"
        plan.steps, plan.minutes = 300, 12
        checks += [
            Check(id="exceptions", type="max_findings", kinds=["exception"], value=3, severity="warning"),
            Check(id="jank", type="max_metric", metric="avg_jank_percent", value=10, severity="warning"),
            Check(id="memory", type="max_metric", metric="peak_pss_kb", value=600_000, severity="warning"),
            Check(id="coverage", type="require_screens", value=8, severity="warning"),
        ]
        checks += [
            Check(id="cold-start", type="max_metric", metric="cold_start_ms", value=2000, severity="warning"),
            Check(id="warm-start", type="max_metric", metric="warm_start_ms", value=800, severity="warning"),
            Check(id="leak", type="max_metric", metric="mem_growth_kb_per_min", value=8000, severity="warning"),
        ]
        notes = ["App profile: breadth-first UI coverage, strict jank and memory budgets."]
    # what the spec says matters raises the bar
    if features.get("performance"):
        for check in checks:
            if check.id == "fps-avg":
                check.value, check.severity = 45, "blocker"
            if check.id == "jank":
                check.severity = "blocker"
        notes.append(f"Spec has {features['performance']} performance case(s): perf checks are blockers.")
    if step_budget is not None:
        plan.steps = step_budget
    elif features.get("stability"):
        plan.steps = int(plan.steps * 1.5)
        notes.append(f"Spec has {features['stability']} stability case(s): session lengthened 50%.")
    if features.get("navigation") or features.get("levels"):
        for check in checks:
            if check.id == "coverage":
                check.value = max(check.value, 6 if kind == "game" else 10)
        notes.append("Spec covers navigation/levels: higher screen-coverage target.")
    if not features:
        notes.append("No requirements document loaded: generic risk-based checks only.")
    # real-life interruptions + start-up timing on every build
    plan.interruptions = ["background", "rotate", "lock", "memory", "airplane", "kill_restore"]
    plan.interrupt_every = 20 if kind == "app" else 25
    plan.startup_runs = 3 if on_device else 2
    checks += [
        Check(id="survive-interruptions", type="max_metric", metric="interruptions_failed", value=0),
        Check(id="interruptions-ran", type="require_metric", metric="interruptions_run", severity="warning"),
        Check(id="battery-heat", type="max_metric", metric="max_battery_temp_c", value=43, severity="warning"),
    ]
    notes.append(f"Lifecycle: {len(plan.interruptions)} interruption types every {plan.interrupt_every} steps; "
                 f"cold/warm start measured {plan.startup_runs}x.")
    plan.checks = checks
    plan.notes = " ".join(notes)
    return plan


# -- 3. expert review ----------------------------------------------------------

#: (regex on message/stack, likely cause, what a developer should look at)
ROOT_CAUSES = (
    (r"NullPointerException", "null reference", "an object used before it was initialised or after it was released; check lifecycle (onPause/onResume) and async callbacks"),
    (r"OutOfMemoryError|low_memory|lowmemorykiller|onTrimMemory", "memory pressure", "texture/bitmap budget, leaked activities or unbounded caches"),
    (r"SIGSEGV|SEGV_MAPERR|SIGABRT|SIGBUS", "native crash", "native plugin or engine code dereferenced bad memory; symbolicate the tombstone with the build's .so symbols"),
    (r"RenderThread|libGLES|vulkan|EGL", "graphics driver / render thread", "GPU driver or render-thread contention; reproduce on another GPU family (Mali/Adreno)"),
    (r"ANR|Input dispatching timed out|not responding", "main thread blocked", "disk, network or heavy work on the UI thread; capture /data/anr/traces.txt"),
    (r"IllegalStateException", "illegal state", "a fragment/activity transaction or API call in the wrong lifecycle state"),
    (r"IndexOutOfBounds|ArrayIndexOutOfBounds", "index out of range", "list/array bounds - often a race between data refresh and UI"),
    (r"ClassCastException", "type mismatch", "wrong cast, often from serialised/cached data"),
    (r"NetworkOnMainThread|UnknownHost|SocketTimeout|SSLHandshake", "network handling", "missing offline/timeout handling"),
    (r"SecurityException|Permission Denial", "permission", "runtime permission not requested or revoked"),
    (r"Firebase|FirebaseMessaging|google\.firebase", "Firebase SDK", "SDK initialisation order or missing google-services config"),
    (r"Unity|il2cpp|libunity", "Unity runtime", "managed exception surfaced through Unity; check Player.log and script stack"),
)

#: logcat warning signs that are not crashes (yet)
LOG_SIGNALS = (
    (r"Choreographer.*Skipped (\d+) frames", "UI thread skipped frames", "performance"),
    (r"StrictMode", "StrictMode violation", "quality"),
    (r"GC_|Background concurrent copying GC|Waiting for a blocking GC", "garbage-collector pressure", "performance"),
    (r"OutOfMemory|Failed to allocate", "allocation failure", "stability"),
    (r"Davey! duration=(\d+)ms", "long frame (Davey)", "performance"),
    (r"(SocketTimeout|UnknownHost|ECONNREFUSED|Unable to resolve host)", "network failure", "network"),
    (r"(SSLHandshake|CertPathValidator)", "TLS/certificate error", "network"),
    (r"(Ads?|AdMob|AppLovin|IronSource|LevelPlay).*(fail|error|no fill)", "ad load failure", "ads"),
    (r"(Billing|IAP|purchase).*(error|fail)", "billing error", "iap"),
    (r"(leak|LeakCanary)", "possible memory leak", "stability"),
    (r"Accessing hidden (method|field)", "hidden API use", "compatibility"),
    (r"(deprecated|Deprecated)", "deprecated API", "compatibility"),
)

DEDICATED_METRICS = ("interruptions_failed", "mem_growth_kb_per_min", "cold_start_ms")

DEDICATED_CHECK_IDS = ("survive-interruptions", "leak", "cold-start")

SEVERITY_ORDER = ("S1 critical", "S2 major", "S3 minor", "S4 trivial")

INTERRUPT_HELP = {
    "background": "press Home, wait 2 s, reopen the app",
    "rotate": "rotate to landscape and back",
    "lock": "press Power, wait 2 s, unlock",
    "airplane": "turn airplane mode on for 4 s, then off",
    "memory": "trigger low memory (adb shell am send-trim-memory <pkg> RUNNING_CRITICAL)",
    "kill_restore": "press Home, run adb shell am kill <pkg>, reopen from recents",
}


def _severity(kind: str, count: int, step: int, steps_run: int) -> str:
    early = steps_run and step and step <= max(10, steps_run * 0.1)
    if kind in ("native_crash", "java_crash"):
        return "S1 critical"
    if kind == "anr":
        return "S1 critical" if count > 1 or early else "S2 major"
    if kind in ("process_death", "low_memory"):
        return "S2 major"
    return "S3 minor"


def _root_cause(text: str) -> Dict[str, str]:
    for pattern, cause, advice in ROOT_CAUSES:
        if re.search(pattern, text, re.IGNORECASE):
            return {"cause": cause, "advice": advice}
    return {"cause": "unclassified", "advice": "attach logcat and the video around this step to the bug"}


def _repro(timeline: Sequence[Dict[str, Any]], step: int, depth: int = 6) -> List[str]:
    before = [entry for entry in timeline if int(entry.get("step") or 0) <= step][-depth:]
    lines = [f"Install the build and launch it (fresh start)."]
    for entry in before:
        lines.append(f"Step {entry.get('step')}: {entry.get('action') or 'wait'}"
                     + (" (new screen)" if entry.get("new") else ""))
    lines.append("Observe: the failure appears at the last step above.")
    return lines


def scan_logcat(lines: Iterable[str], package: str = "") -> Dict[str, Any]:
    levels: Counter = Counter()
    tags: Counter = Counter()
    signals: Dict[str, Dict[str, Any]] = {}
    total = 0
    tag_re = re.compile(r"\b([VDIWEF])[/ ]\s*([^:(\s]+)")
    for raw in lines:
        total += 1
        match = tag_re.search(raw)
        if match:
            levels[match.group(1)] += 1
            if match.group(1) in ("E", "F"):
                tags[match.group(2)] += 1
        for pattern, label, area in LOG_SIGNALS:
            if re.search(pattern, raw, re.IGNORECASE):
                item = signals.setdefault(label, {"signal": label, "area": area, "count": 0, "example": raw[:220]})
                item["count"] += 1
    return {
        "lines": total,
        "levels": dict(levels),
        "top_error_tags": tags.most_common(8),
        "signals": sorted(signals.values(), key=lambda s: -s["count"]),
    }


def _case_results(suite: Any, findings: Sequence[Dict[str, Any]], summary: Dict[str, Any],
                  checks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map the spec's test cases onto what an automatic session can prove."""
    if suite is None:
        return []
    crashes = [f for f in findings if f.get("kind") in ("java_crash", "native_crash", "process_death")]
    anrs = [f for f in findings if f.get("kind") == "anr"]
    failed_perf = [c for c in checks if not c.get("passed") and c.get("type") in ("min_metric", "max_metric")]
    screens = int(summary.get("screens_explored") or 0)
    out = []
    for case in getattr(suite, "cases", []) or []:
        feature, title = case.feature, case.title
        status, why = "MANUAL", "needs a human tester (business logic / content)"
        text = f"{title} {case.expected}".lower()
        if feature == "stability" or "crash" in text:
            status = "FAIL" if crashes else "PASS"
            why = f"{len(crashes)} crash finding(s) in the session" if crashes else "no crash during automatic session"
        elif "anr" in text or "respon" in text or "freeze" in text:
            status = "FAIL" if anrs else "PASS"
            why = f"{len(anrs)} ANR(s)" if anrs else "no ANR"
        elif feature == "performance":
            status = "FAIL" if failed_perf else "PASS"
            why = "; ".join(c.get("title", "") for c in failed_perf) or "performance budgets met"
        elif feature in ("navigation", "ui"):
            status = "PASS" if screens >= 3 and not crashes else "NOT_VERIFIED"
            why = f"{screens} distinct screens reached" + (" but the app crashed" if crashes else "")
        out.append({"id": case.id, "title": title, "feature": feature, "priority": case.priority,
                    "auto_status": status, "reason": why})
    return out


def expert_review(payload: Dict[str, Any], product: Optional[Dict[str, Any]] = None,
                  suite: Any = None, log_lines: Sequence[str] = (),
                  comparison: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Senior-QA style analysis of a finished session."""
    summary = payload.get("summary") or {}
    findings = list(payload.get("crashes") or [])
    checks = list(payload.get("checks") or [])
    timeline = list(payload.get("timeline") or [])
    meta = payload.get("meta") or {}
    steps_run = int(summary.get("steps_run") or 0)
    completed, planned, end_reason = exploration_coverage(payload)
    partial = end_reason != "completed"
    if partial:
        comparison = None
    package = str(meta.get("package") or "")

    issues = []
    for finding in findings:
        text = " ".join([str(finding.get("message") or ""), str(finding.get("signature") or ""),
                         " ".join(finding.get("stack") or [])])
        step = int(finding.get("step") or 0)
        severity = _severity(str(finding.get("kind")), int(finding.get("count") or 1), step, steps_run)
        issues.append({
            "title": f"{finding.get('kind', 'finding').replace('_', ' ')}: {str(finding.get('message') or '')[:120]}",
            "kind": finding.get("kind"),
            "severity": severity,
            "priority": "P0" if severity.startswith("S1") else ("P1" if severity.startswith("S2") else "P2"),
            "step": step,
            "occurrences": finding.get("count") or 1,
            **_root_cause(text),
            "repro": _repro(timeline, step),
            "evidence": [x for x in (finding.get("screenshot"), "logcat.txt") if x],
            "stack": list(finding.get("stack") or [])[:8],
        })
    for check in checks:
        if check.get("passed") or check.get("type") in ("no_findings", "max_findings"):
            continue
        if partial and (check.get("type") in ("require_screens", "require_metric") or check.get("actual") == "not measured"):
            continue
        if check.get("metric") in DEDICATED_METRICS or check.get("id") in DEDICATED_CHECK_IDS:  # reported by its own, more specific issue below
            continue
        issues.append({
            "title": f"budget missed: {check.get('title')} (expected {check.get('expected')}, got {check.get('actual')})",
            "kind": "performance" if "metric" in str(check.get("type")) else "coverage",
            "severity": "S2 major" if check.get("severity") == "blocker" else "S3 minor",
            "priority": "P1" if check.get("severity") == "blocker" else "P2",
            "step": None, "occurrences": 1,
            "cause": "budget", "advice": "profile the build (Android GPU Inspector / Perfetto) on the same device",
            "repro": ["Run the same plan on the same device and compare metrics.json."],
            "evidence": ["metrics.json"], "stack": [],
        })
    # lifecycle interruptions the app did not survive
    for event in payload.get("interruptions") or []:
        if event.get("skipped") or event.get("survived"):
            continue
        kind = event.get("kind")
        # the crash behind this event is the same bug: fold it into the lifecycle issue
        same = [i for i in issues if f"[after {kind}]" in i["title"] and i.get("step") == event.get("step")]
        for dup in same:
            issues.remove(dup)
        issues.append({
            "title": f"app did not survive '{kind}' interruption: {event.get('finding') or 'process died'}",
            "kind": "lifecycle", "severity": "S1 critical", "priority": "P0", "step": event.get("step"),
            "occurrences": 1, "cause": "lifecycle / state restore",
            "advice": {"rotate": "activity recreated on configuration change - save/restore state, avoid fragment commits after onSaveInstanceState",
                       "kill_restore": "process death not handled - restore from savedInstanceState / persisted data, never assume singletons survive",
                       "airplane": "network loss not handled - add timeouts, offline state and retry",
                       "memory": "onTrimMemory not handled - release caches/textures when asked",
                       "lock": "onStop/onStart path broken - check surface/GL context loss",
                       "background": "onPause/onResume path broken - check audio/GL/ads callbacks"}.get(kind, "check the lifecycle callbacks"),
            "repro": [f"Play to step {event.get('step')} (or any screen)", f"Interruption: {INTERRUPT_HELP.get(kind, kind)}",
                      "Observe: app crashes or is gone"],
            "evidence": ["logcat.txt", "session video"],
            "stack": [str(event.get("detail") or "")] + [line for dup in same for line in dup.get("stack") or []],
        })
    startup = payload.get("startup") or {}
    cold = summary.get("cold_start_ms")
    if cold:
        limit = 5000 if (product or {}).get("kind") == "game" else 2000
        if cold > limit:
            issues.append({
                "title": f"slow cold start: {cold} ms (budget {limit} ms)", "kind": "performance",
                "severity": "S2 major" if cold > limit * 1.5 else "S3 minor", "priority": "P1",
                "step": None, "occurrences": len(startup.get("cold_ms") or []), "cause": "start-up",
                "advice": "defer SDK init (ads/analytics) off the main thread, shrink first-scene assets",
                "repro": ["adb shell am force-stop <pkg>", "adb shell am start -W -n <activity>", "read TotalTime"],
                "evidence": ["session.json → startup"], "stack": [],
            })
    growth = summary.get("mem_growth_kb_per_min")
    if growth and growth > (20000 if (product or {}).get("kind") == "game" else 8000):
        issues.append({
            "title": f"memory keeps growing: +{growth:,.0f} kB/min (possible leak)", "kind": "performance",
            "severity": "S2 major", "priority": "P1", "step": None, "occurrences": 1, "cause": "memory pressure",
            "advice": "take two heap dumps minutes apart (Android Studio Profiler) and diff retained objects",
            "repro": ["Run a 30-minute soak and watch PSS in metrics.json"], "evidence": ["metrics.json"], "stack": [],
        })
    # regressions against the previous build
    for reg in (comparison or {}).get("regressions") or []:
        issues.append({
            "title": f"regression vs {comparison.get('baseline_label', 'previous build')}: {reg['text']}",
            "kind": "regression", "severity": reg.get("severity", "S2 major"),
            "priority": "P0" if reg.get("severity", "").startswith("S1") else "P1",
            "step": None, "occurrences": 1, "cause": "regression",
            "advice": "bisect the commits between the two builds; this got worse in the new build",
            "repro": ["Run the same auto QA plan on both builds on the same phone"],
            "evidence": ["Compare builds panel"], "stack": [],
        })
    issues.sort(key=lambda i: SEVERITY_ORDER.index(i["severity"]) if i["severity"] in SEVERITY_ORDER else 9)

    logscan = scan_logcat(log_lines, package)
    for signal in logscan["signals"][:6]:
        if signal["count"] >= 3 and signal["area"] in ("performance", "stability", "network", "ads", "iap"):
            issues.append({
                "title": f"log warning: {signal['signal']} ×{signal['count']}",
                "kind": "log_signal", "severity": "S3 minor", "priority": "P2", "step": None,
                "occurrences": signal["count"], "cause": signal["area"],
                "advice": "not a crash yet - watch it; it often precedes ANR/OOM on low-end devices",
                "repro": [], "evidence": ["logcat.txt"], "stack": [signal["example"]],
            })

    # risk score: weighted, capped at 100
    weights = {"S1 critical": 35, "S2 major": 15, "S3 minor": 4, "S4 trivial": 1}
    risk = min(100, sum(weights.get(i["severity"], 1) for i in issues))
    screens = int(summary.get("screens_explored") or 0)
    if steps_run and steps_run < 20:
        risk = min(100, risk + 10)  # too little exercise to trust a clean result
    s1 = sum(1 for i in issues if i["severity"].startswith("S1"))
    s2 = sum(1 for i in issues if i["severity"].startswith("S2"))
    if s1:
        decision, reason = "NO-GO", f"{s1} critical issue(s): a crash or repeated ANR blocks release."
    elif s2 or risk >= 30:
        decision, reason = "CONDITIONAL", f"{s2} major issue(s); ship only with sign-off and a fix plan."
    else:
        decision, reason = "GO", "no critical or major issue found in the automatic pass."
    if partial:
        decision = "INCOMPLETE"
        reason = (f"{completed} of {planned} planned steps ran. Findings reflect the coverage so far."
                  if not summary.get("unconfirmed_inputs") else "The run includes an input whose delivery could not be confirmed.")

    cases = _case_results(suite, findings, summary, checks)
    case_counts = Counter(c["auto_status"] for c in cases)

    confidence_notes = []
    if summary.get("device_lost"):
        confidence_notes.append("the phone disconnected during the test (USB cable / USB debugging) - "
                                "the result only covers the steps before that; fix the cable and test again")
    if summary.get("stopped_by_user"):
        confidence_notes.append(f"you stopped the test early, after {steps_run} steps")
    if summary.get("unconfirmed_inputs"):
        confidence_notes.append(f"delivery of {summary['unconfirmed_inputs']} input(s) could not be confirmed")
    if steps_run < 50:
        confidence_notes.append(f"only {steps_run} steps ran - extend the session before trusting a GO")
    if screens < 3:
        confidence_notes.append(f"only {screens} distinct screens reached - exploration was shallow")
    if (product or {}).get("kind") == "game" and summary.get("avg_fps") in (None, 0):
        confidence_notes.append("no FPS measured - gfxinfo is often empty for GL/Unity surfaces; verify by eye on the video")
    if case_counts.get("MANUAL"):
        confidence_notes.append(f"{case_counts['MANUAL']} spec case(s) still need a human tester")

    next_steps = []
    if s1:
        next_steps.append("File the S1 issues now (repro steps + video + logcat are attached below) and block the build.")
    if any(i["cause"] == "graphics driver / render thread" for i in issues):
        next_steps.append("Re-run on a second GPU family (Adreno vs Mali) to tell driver bugs from engine bugs.")
    if any(i["kind"] == "anr" for i in issues):
        next_steps.append("Pull /data/anr/traces.txt from the device and attach it to the ANR bug.")
    if any(i["kind"] == "lifecycle" for i in issues):
        next_steps.append("Lifecycle bugs are the #1 cause of 1-star reviews - fix before any release.")
    if (comparison or {}).get("regressions"):
        next_steps.append("This build is worse than the previous one - see the regressions; consider reverting.")
    if logscan["signals"]:
        next_steps.append("Review the log warnings: they predict field crashes on low-end phones.")
    if decision == "GO":
        next_steps.append("Run the manual cases (economy, ads, IAP, content) and a 30-minute soak before sign-off.")
    next_steps.append("Repeat on min-SDK device and on a low-RAM (≤3 GB) device.")

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "product": product or {},
        "decision": decision,
        "decision_reason": reason,
        "risk_score": risk,
        "issues": issues,
        "issue_counts": dict(Counter(i["severity"] for i in issues)),
        "logcat": logscan,
        "cases": cases,
        "case_counts": dict(case_counts),
        "confidence": confidence_notes,
        "next_steps": next_steps,
        "metrics": {k: summary.get(k) for k in ("steps_run", "duration_s", "screens_explored", "avg_fps",
                                                  "min_fps", "avg_jank_percent", "peak_pss_kb", "cold_start_ms",
                                                  "warm_start_ms", "avg_cpu_percent", "max_cpu_percent",
                                                  "max_battery_temp_c", "mem_growth_kb_per_min",
                                                  "interruptions_run", "interruptions_failed")},
        "interruptions": list(payload.get("interruptions") or []),
        "startup": startup,
        "comparison": comparison or {},
        "perf": payload.get("perf") or {},
        "checklist": test_checklist(payload, cases, product),
    }


def review_markdown(review: Dict[str, Any]) -> str:
    """The review as a bug-tracker-ready Markdown file."""
    p = review.get("product") or {}
    status = "Results so far" if review["decision"] == "INCOMPLETE" else review["decision"]
    out = [f"# QA review — {status} (risk {review['risk_score']}/100)", "",
           f"*{review['decision_reason']}*", "",
           f"- Product: **{p.get('kind', '?')}** on {p.get('engine', '?')}",
           f"- Generated: {review['generated_at']}", ""]
    out.append("## Issues")
    if not review["issues"]:
        out.append("None found by the automatic pass.")
    for n, issue in enumerate(review["issues"], 1):
        out += ["", f"### {n}. [{issue['severity']} / {issue['priority']}] {issue['title']}",
                f"- Likely cause: **{issue['cause']}** — {issue['advice']}"]
        if issue["repro"]:
            out.append("- Steps to reproduce:")
            out += [f"  {i}. {s}" for i, s in enumerate(issue["repro"], 1)]
        if issue["stack"]:
            out += ["", "```", *issue["stack"], "```"]
    if review["cases"]:
        out += ["", "## Spec test cases", "", "| Case | Feature | Auto status | Why |", "|---|---|---|---|"]
        out += [f"| {c['id']} {c['title'][:60]} | {c['feature']} | {c['auto_status']} | {c['reason']} |"
                for c in review["cases"]]
    out += ["", "## Confidence"] + [f"- {c}" for c in review["confidence"] or ["good"]]
    out += ["", "## Next steps"] + [f"- {s}" for s in review["next_steps"]]
    return "\n".join(out) + "\n"
