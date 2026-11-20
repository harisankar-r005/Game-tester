"""QA Studio: a local web app for upload -> test -> watch -> judge.

Run it with::

    python -m apkharness serve

It binds 127.0.0.1 only, keeps every artifact on disk, and needs no third-party
packages: the HTTP layer is :mod:`http.server`, the UI is one static page, and the
"video" is either an H.264 file recorded by the phone itself (``screenrecord``)
or an animated GIF built from the captured frames.

Architecture
------------
``Studio`` owns all mutable state behind one lock: the uploaded APK, the plan, the
selected device, the live frame buffer, the per-step decision log and the finished
session. The HTTP handler is a thin translation layer from the JSON API to those
methods; the test itself runs in a worker thread so the page stays responsive and
can stream frames and decisions while the game is being driven.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import stat
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, video
from .adb import Adb, AdbError, AdbNotFound, find_adb
from .apk import ApkError, inspect_apk
from .casefile import first_customer_guide
from .checklist import exploration_coverage
from .requirements import RequirementError, extract_text, parse_document
from .testgen import generate, regenerate
from .suite import Suite, SuiteStore
from .plan import (
    CheckResult,
    Plan,
    default_plan,
    evaluate,
    summarize,
    validate_plan_dict,
)
from .report import write_html, write_junit
from .run import CHECKPOINT_FILE, RunConfig, Session
from .device import INPUT_HINT, AdbDevice, DeviceUnavailable
from .screen import ScreenRecorder
from .autoqa import classify_apk, probe_installed, expert_plan, expert_review, review_markdown
from .suite import merge_statuses

MAX_UPLOAD_BYTES = 800 * 1024 * 1024  # 800 MB, plenty for a big Unity build
LIVE_FRAMES = 600
STEP_LOG_LIMIT = 3000
AUTOQA_SECTION_SIZE = 100
AUTOQA_PRESETS = {"quick": 50, "standard": 150, "extended": 400}
OBJECTIVE_LIMIT = 300
STUCK_INPUTS = 18
SAVED_RUN_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[A-Za-z0-9_.-]+")
STATE_POLL_HINT_MS = 700
DEVICE_CACHE_SECONDS = 2.0


class StudioError(RuntimeError):
    """User-facing error shown in the UI (HTTP 4xx with a message)."""


@dataclass
class LiveFrame:
    index: int
    step: int
    action: str
    finding: bool
    path: str
    at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "step": self.step, "action": self.action, "finding": self.finding}


class Studio:
    """Holds the uploaded APK, the plan, devices, the live session and results."""

    def __init__(self, workdir: str = "studio", adb_path: str = "", port: int = 0) -> None:
        self.workdir = os.path.abspath(workdir)
        self.uploads_dir = os.path.join(self.workdir, "uploads")
        self.runs_dir = os.path.join(self.workdir, "runs")
        self.live_dir = os.path.join(self.workdir, "live")
        for directory in (self.uploads_dir, self.runs_dir, self.live_dir):
            os.makedirs(directory, exist_ok=True)

        self.lock = threading.RLock()
        self.plan: Plan = default_plan()
        self.plan_errors: List[str] = []
        self.apk: Optional[Dict[str, Any]] = None
        self.apk_path: str = ""
        self.status: str = "idle"  # idle | running | done | error
        self.error: str = ""
        self.progress: Dict[str, Any] = {"step": 0, "total": self.plan.steps, "action": "", "elapsed": 0.0}
        self.findings: List[Dict[str, Any]] = []
        self.checks: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}
        self.video_meta: Dict[str, Any] = {}
        self.session_dir: str = ""
        self.artifacts: Dict[str, str] = {}
        self.live_frames: Deque[LiveFrame] = deque(maxlen=LIVE_FRAMES)
        self.step_log: Deque[Dict[str, Any]] = deque(maxlen=STEP_LOG_LIMIT)
        self.step_interruptions: Dict[int, Dict[str, Any]] = {}
        self._frame_seq = 0
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.adb_path = adb_path or find_adb() or ""
        self.serial: str = ""
        self._target_pinned = False
        self._auto_switched = False
        self.port = port
        self._devices: List[Dict[str, Any]] = []
        self._devices_at = 0.0
        self._recorder: Optional[ScreenRecorder] = None
        self.requirements_dir = os.path.join(self.workdir, "requirements")
        os.makedirs(self.requirements_dir, exist_ok=True)
        self.suite_store = SuiteStore(self.requirements_dir)
        self.doc: Optional[Dict[str, Any]] = None
        self.doc_text: str = ""
        self.suite: Optional[Suite] = None  # fresh start: nothing from an earlier session is pre-selected
        self._readiness: Dict[str, Any] = {}
        self._readiness_at = 0.0
        # -- auto QA engine state
        self.events: Deque[Dict[str, Any]] = deque(maxlen=2000)
        self._event_seq = 0
        self.product: Optional[Dict[str, Any]] = None
        self.qa_review: Optional[Dict[str, Any]] = None
        self._session: Any = None
        self._paused_session: Optional[Session] = None
        self.autoqa: Dict[str, Any] = {"enabled": True, "use_spec": True, "preset": "quick", "last_trigger": "",
                                       "watching": False}
        self._watch_stop = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None
        # -- written test cases + AI player
        from .caserun import HumanDesk

        self.case_doc: Optional[Dict[str, Any]] = None      # parsed .md: cases, inputs, missing inputs
        self.case_run: Dict[str, Any] = {}                    # live state of a test-case run
        self.case_result: Optional[Dict[str, Any]] = None     # last finished test-case run
        self.desk = HumanDesk()
        self.mode = "explore"                                  # what the last/current run was
        self.ai_settings: Dict[str, Any] = self._load_ai_settings()
        self._restore_saved_run()
        self.log("info", "studio started")

    # -- event log ---------------------------------------------------------
    def log(self, level: str, message: str) -> None:
        with self.lock:
            self._event_seq += 1
            self.events.append({"seq": self._event_seq, "ts": time.strftime("%H:%M:%S"),
                                "level": level, "msg": message})
        if os.environ.get("APKHARNESS_DEBUG") or level in ("error",):
            print(f"[{level}] {message}", flush=True)

    def events_since(self, since: int = 0, limit: int = 500) -> Dict[str, Any]:
        with self.lock:
            items = [e for e in self.events if e["seq"] > since][-limit:]
            return {"events": items, "last": self._event_seq}

    def live_log(self, tail: int = 300, only_game: bool = False) -> Dict[str, Any]:
        """Logcat while a test runs; otherwise straight from the connected phone.

        ``only_game`` keeps just the lines written by the chosen game's process.
        """
        session = self._session
        package = (self.apk or {}).get("package", "") or ""
        lines: List[str] = []
        source = "none"
        if session is not None and getattr(session, "_log_lines", None) is not None:
            lines = list(session._log_lines)[-max(tail * 4, 2000):]
            source = "test"
            package = getattr(getattr(session, "config", None), "package", "") or package
        else:
            serial = self.serial if self.adb_path else ""
            if self.adb_path and not serial:
                serial = self._pick_serial()
            if serial:
                try:
                    adb = Adb(path=self.adb_path, serial=serial, timeout=20)
                    lines = adb.logcat_dump(tail=max(tail * 4, 2000)).splitlines()
                    source = "phone"
                except AdbError as exc:
                    return {"status": self.status, "lines": [], "source": "none", "hint": str(exc)}
        pid = ""
        if only_game and package:
            if source == "phone":
                try:
                    pid = str(Adb(path=self.adb_path, serial=self.serial, timeout=10).pidof(package) or "")
                except AdbError:
                    pid = ""
            else:
                found = [ln for ln in lines if package in ln and ("Start proc" in ln or "pid" in ln.lower())]
                match = re.search(r"Start proc (\d+):" + re.escape(package), "\n".join(found))
                pid = match.group(1) if match else ""
            if pid:
                lines = [ln for ln in lines if re.match(rf"^\S+\s+\S+\s+{pid}\s", ln) or package in ln]
            else:
                lines = [ln for ln in lines if package in ln]
        hint = ""
        if source == "none":
            hint = "connect a phone to see its log"
        elif only_game and not package:
            hint = "choose a game first to filter its lines"
        elif only_game and not lines:
            hint = "the game is not running on the phone right now - open it, or untick 'Only this game'"
        return {"status": self.status, "lines": lines[-tail:], "source": source, "package": package, "hint": hint}

    # -- auto QA -------------------------------------------------------------
    def _autoload_latest_apk(self) -> None:
        try:
            apks = sorted(f for f in os.listdir(self.uploads_dir) if f.lower().endswith(".apk"))
        except OSError:
            return
        if apks:
            name = apks[-1]
            try:
                self._adopt_apk(os.path.join(self.uploads_dir, name), name.split("_", 2)[-1])
            except Exception:  # pragma: no cover - a broken upload must not stop the studio
                pass

    def _has_target(self) -> bool:
        return bool(self.apk_path or (self.apk or {}).get("installed_only"))

    def clear_apk(self) -> Dict[str, Any]:
        with self.lock:
            if self.status == "running":
                raise StudioError("stop the running test first")
            self._discard_paused_run()
            self.apk = None
            self.apk_path = ""
            self.product = None
            self.qa_review = None
        self.log("info", "game removed - choose a game on the phone or add an .apk")
        return {"ok": True}

    def phone_apps(self) -> Dict[str, Any]:
        """Apps the user installed on the connected phone (system apps hidden)."""
        serial = self._pick_serial() if self.adb_path else ""
        if not serial:
            return {"serial": "", "apps": [], "hint": "connect a phone to see its games"}
        adb = Adb(path=self.adb_path, serial=serial)
        try:
            packages = adb.list_packages(user_only=True)
        except AdbError as exc:
            return {"serial": serial, "apps": [], "hint": str(exc)}
        skip = ("com.google.", "com.android.", "com.qualcomm.", "com.coloros.", "com.oplus.", "com.heytap.",
                "com.realme.", "com.oppo.", "com.miui.", "com.xiaomi.", "com.samsung.", "com.sec.",
                "com.facebook.services", "com.facebook.system", "com.facebook.appmanager")
        apps = []
        for package in packages:
            if package.startswith(skip):
                continue
            words = [w for w in package.split(".")[1:] if w not in ("com", "game", "games", "app", "android", "mobile")]
            label = " ".join(w.capitalize() for w in words[-3:]) or package
            product = classify_apk("", package)
            apps.append({"package": package, "label": label, "kind": product["kind"]})
        apps.sort(key=lambda a: (a["kind"] != "game", a["label"].lower()))
        return {"serial": serial, "apps": apps, "hint": "" if apps else "no downloaded apps found on this phone"}

    def phone_current(self) -> Dict[str, Any]:
        """The app that is on the phone's screen right now (so the tester can just open the game)."""
        serial = self._pick_serial() if self.adb_path else ""
        if not serial:
            return {"package": "", "hint": "connect a phone first"}
        adb = Adb(path=self.adb_path, serial=serial)
        package = ""
        for command, pattern in (
            ("dumpsys activity activities", r"(?:topResumedActivity|mResumedActivity|ResumedActivity)[=:]\s*ActivityRecord\{\S+ \S+ ([\w.]+)/"),
            ("dumpsys window", r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)/"),
        ):
            try:
                match = re.search(pattern, adb.shell(command))
            except AdbError:
                match = None
            if match:
                package = match.group(1)
                break
        home = ("launcher", "systemui", "com.android.settings", "nexuslauncher", "com.miui.home", "com.sec.android.app.launcher")
        if not package or any(word in package for word in home):
            return {"package": "", "hint": "open the game on the phone first, then press this button again"}
        return {"package": package}

    def choose_installed(self, package: str) -> Dict[str, Any]:
        """Test an app that is already on the phone - no .apk file needed."""
        package = (package or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+", package):
            raise StudioError("not a valid app id")
        serial = self._pick_serial()
        if not serial:
            raise StudioError("connect a phone first")
        adb = Adb(path=self.adb_path, serial=serial)
        version = adb.installed_version(package)
        if not version:
            raise StudioError(f"{package} is not installed on the phone")
        product = probe_installed(adb, package)
        info = {
            "name": package, "path": "", "size": 0, "package": package,
            "version": f"{version.get('version_name') or '?'} ({version.get('version_code')})",
            "activity": "", "abis": [], "error": "", "installed_only": True, "product": product,
        }
        with self.lock:
            if self.status == "running":
                raise StudioError("stop the running test first")
            if (self.apk or {}).get("package") != package or (self.apk or {}).get("version") != info["version"] or self.apk_path:
                self._discard_paused_run()
            self.apk = info
            self.apk_path = ""
            self.product = product
            self.qa_review = None
            self.plan.install = False
            self.plan.name = f"{package} test"
        self.log("info", f"game chosen from the phone: {package} {info['version']} → "
                 f"{product['kind'].upper()} ({product['engine']})")
        return info

    def set_autoqa(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if "preset" in payload:
                preset = payload["preset"]
                if not isinstance(preset, str) or preset not in AUTOQA_PRESETS:
                    raise StudioError("Choose Quick, Standard or Extended.")
                self.autoqa["preset"] = preset
            for key in ("enabled", "use_spec"):
                if key in payload:
                    self.autoqa[key] = bool(payload[key])
        self.log("info", f"auto QA {'ON' if self.autoqa['enabled'] else 'OFF'}"
                 f"{' (spec-driven)' if self.autoqa['use_spec'] else ''}")
        return dict(self.autoqa)

    def auto_start(self, serial: str = "", reason: str = "manual trigger", where: str = "",
                   preset: Optional[str] = None, objective: str = "") -> Dict[str, Any]:
        """Pick the expert plan for this product + spec and start it.

        ``where`` is the tester's explicit choice: "phone", "practice" or "" (decide automatically).
        """
        with self.lock:
            if self._paused_session:
                return self.resume()
            if preset is None:
                preset = self.autoqa["preset"]
            if not isinstance(preset, str) or preset not in AUTOQA_PRESETS:
                raise StudioError("Choose Quick, Standard or Extended.")
            if not isinstance(objective, str) or len(objective.strip()) > OBJECTIVE_LIMIT:
                raise StudioError(f"Keep the gameplay objective to {OBJECTIVE_LIMIT} characters or fewer.")
            objective = objective.strip()
        kind = (self.product or {}).get("kind", "game")
        if where == "practice":
            serial, on_device = "", False
        elif where == "phone":
            serial = serial or (self._pick_serial() if self.adb_path else "")
            if not serial:
                raise StudioError("no phone is connected - plug it in (USB debugging on) or choose Practice phone")
            on_device = True
        else:
            on_device = bool(serial) or self._has_device()
        if on_device and not self._has_target():
            raise StudioError("choose which game to test on the device first: pick one on the phone or add an .apk file")
        suite = self.suite if self.autoqa.get("use_spec") else None
        plan = expert_plan(kind, suite, base=self.plan, on_device=on_device, step_budget=AUTOQA_PRESETS[preset])
        if self._ai_config_for_run():
            plan.policy = "agent"
        elif objective:
            raise StudioError("Enable the AI player before setting a gameplay objective.")
        target_name = (self.apk or {}).get("package") or f"{kind} build"
        plan.name = f"Auto QA - {preset.title()} - {target_name}"
        with self.lock:
            self.plan = plan
            self.plan_errors = []
            if serial:
                self.serial = serial
            self.autoqa["preset"] = preset
            self.autoqa["last_trigger"] = f"{time.strftime('%H:%M:%S')} {reason}"
        self.log("info", f"AUTO QA: {reason} → {preset.title()} {kind} profile, {plan.steps} steps, {len(plan.checks)} checks"
                 + (f", spec '{self.suite.doc_name}' ({len(self.suite.cases)} cases)" if suite else ""))
        for note in plan.notes.split(". "):
            if note.strip():
                self.log("info", "  plan: " + note.strip().rstrip("."))
        return self.start(section_size=AUTOQA_SECTION_SIZE, objective=objective)

    def start_watcher(self) -> None:
        if self._watch_thread is not None:
            return
        self._watch_thread = threading.Thread(target=self._watch_loop, name="apkharness-autoqa", daemon=True)
        self._watch_thread.start()

    def stop_watcher(self) -> None:
        self._watch_stop.set()

    def _watch_loop(self) -> None:
        known: Dict[str, str] = {}
        self.autoqa["watching"] = True
        while not self._watch_stop.wait(3.0):
            if not self.adb_path:
                continue
            try:
                info = self.device_list(refresh=True)
            except Exception:  # pragma: no cover - adb hiccup
                continue
            states = {d["serial"]: d.get("state", "") for d in info.get("devices") or []}
            for serial, state in states.items():
                if known.get(serial) != state:
                    model = self._device_model(serial) or serial
                    level = "info" if state == "device" else "warn"
                    hint = {"unauthorized": " - accept 'Allow USB debugging' on the phone",
                            "offline": " - replug the cable"}.get(state, "")
                    self.log(level, f"phone {model} ({serial}): {state}{hint}")
            for serial in set(known) - set(states):
                self.log("warn", f"phone disconnected: {serial}")
            newly_online = [s for s, st in states.items() if st == "device" and known.get(s) != "device"]
            first_scan = not getattr(self, "_watch_seeded", False)
            self._watch_seeded = True
            known = states
            with self.lock:
                paused = self._paused_session
                if paused and self.status != "running":
                    if (paused.device_lost and not paused.at_section_boundary and not self.stop_event.is_set()
                            and states.get(paused.config.serial) == "device"):
                        try:
                            self.resume()
                        except StudioError as exc:
                            self.log("warn", f"could not resume: {exc}")
                    continue
            if first_scan and newly_online:
                # phones already attached when the tester starts: say so, but wait for the user
                self.log("info", "phone already connected - press Start testing (auto start reacts to new plugs)")
                continue
            if not newly_online or not self.autoqa.get("enabled"):
                continue
            if self.status == "running":
                active = self._session
                if not active or active.config.serial not in newly_online:
                    self.log("warn", "another phone connected while a test is running")
                continue
            if not self._has_target():
                self.log("warn", "phone connected - now choose which game to test (step 2)")
                continue
            try:
                with self.lock:
                    if self.status == "running" or self._paused_session:
                        continue
                    self.auto_start(newly_online[0], reason=f"phone {newly_online[0]} connected")
            except StudioError as exc:
                self.log("error", f"auto QA could not start: {exc}")
        self.autoqa["watching"] = False

    # -- devices -----------------------------------------------------------
    def device_list(self, refresh: bool = False) -> Dict[str, Any]:
        if not self.adb_path:
            return {"adb": "", "devices": [], "hint": "adb was not found; install Android platform-tools",
                    "selected": self.serial}
        auto = False
        with self.lock:
            fresh = self._devices and (time.time() - self._devices_at) < DEVICE_CACHE_SECONDS
            if fresh and not refresh:
                devices = list(self._devices)
                hint = "" if devices else "no device connected"
            else:
                try:
                    devices = [device.to_dict() for device in Adb.list_devices(self.adb_path)]
                    hint = "" if devices else "no device connected - enable Developer options + USB debugging"
                except (AdbError, AdbNotFound) as exc:
                    return {"adb": self.adb_path, "devices": [], "hint": str(exc), "selected": self.serial}
                self._devices = devices
                self._devices_at = time.time()
            online = [d for d in devices if d.get("state") == "device"]
            if not self.serial or not any(d["serial"] == self.serial for d in devices):
                self.serial = online[0]["serial"] if online else (devices[0]["serial"] if devices else "")
            if online and self.apk_path and not self._target_pinned and not self._auto_switched:
                # A phone just appeared: test it, that is what the tester plugged it in for.
                self.plan.target = "device"
                if self.plan.capture == "frames":
                    self.plan.capture = "screenrecord"
                self._auto_switched = True
                auto = True
        return {"adb": self.adb_path, "devices": devices, "hint": hint,
                "selected": self.serial, "auto_switched": auto}

    def select_device(self, serial: str) -> Dict[str, Any]:
        serial = (serial or "").strip()
        info = self.device_list(refresh=True)
        serials = {device["serial"] for device in info["devices"]}
        if serial and serial not in serials:
            raise StudioError(f"device {serial!r} is not connected")
        with self.lock:
            self.serial = serial
        return self.device_list(refresh=False)

    # -- requirements / test cases ----------------------------------------
    def _requirements_payload(self) -> Optional[Dict[str, Any]]:
        if not self.doc:
            return None
        return {
            "name": self.doc["name"],
            "kind": self.doc["kind"],
            "counts": self.doc["counts"],
            "warnings": list(self.doc.get("warnings") or []),
            "sections": list(self.doc.get("sections") or []),
            "requirements": list(self.doc.get("requirements") or [])[:400],
        }

    def receive_document(self, filename: str, payload: bytes) -> Dict[str, Any]:
        """Parse an uploaded spec and generate a traceable, reviewable suite."""
        if not payload:
            raise StudioError("empty document")
        from .casefile import parse_cases

        try:
            text_for_cases = extract_text(filename, payload)[1]
        except Exception:
            text_for_cases = ""
        parsed_cases = parse_cases(text_for_cases)
        if parsed_cases["cases"]:
            with self.lock:
                parsed_cases["name"] = os.path.basename(filename or "test-cases.md")
                self.case_doc = parsed_cases
                self.case_result = None
        try:
            document = parse_document(filename, payload)
        except RequirementError as exc:
            if parsed_cases["cases"]:
                return self._cases_loaded(parsed_cases)
            raise StudioError(str(exc)) from exc
        if parsed_cases["cases"]:
            self.doc = document.to_dict(with_text=False)
            self.doc_text = document.text
            return self._cases_loaded(parsed_cases)
        if not document.requirements:
            reason = document.warnings[0] if document.warnings else "no requirements found"
            raise StudioError(reason)
        cases = generate(document.requirements)
        with self.lock:
            suite_id = "current"
            suite = Suite(
                id=suite_id,
                doc_name=document.name,
                apk_package=(self.apk or {}).get("package", "") or "",
                apk_version=(self.apk or {}).get("version", "") or "",
                cases=cases,
                requirements=[req.to_dict() for req in document.requirements],
            )
            self.doc = document.to_dict(with_text=False)
            self.doc_text = document.text
            self.suite = suite
            self.suite_store.save(suite)
        self.log("info", f"spec loaded: {document.name} → {len(document.requirements)} requirements, "
                 f"{len(cases)} test cases")
        return {
            "requirements": self._requirements_payload(),
            "suite": suite.summary(),
            "testcases": [case.to_dict() for case in suite.cases][:600],
        }

    def _cases_loaded(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        self.log("info", f"test cases loaded: {parsed['name']} → {len(parsed['cases'])} test case(s)"
                 + (f", inputs still needed: {', '.join(parsed['missing_inputs'])}" if parsed["missing_inputs"] else ""))
        return {"cases": self.cases_payload()}

    def cases_payload(self) -> Optional[Dict[str, Any]]:
        doc = self.case_doc
        if not doc:
            return None
        return {"name": doc.get("name", ""), "cases": doc["cases"], "inputs": doc["inputs"],
                "required_inputs": doc["required_inputs"],
                "missing_inputs": [n for n in doc["required_inputs"] if not doc["inputs"].get(n)],
                "warnings": doc.get("warnings", [])}

    def set_case_inputs(self, values: Dict[str, Any]) -> Dict[str, Any]:
        if not self.case_doc:
            raise StudioError("upload a test-case file first")
        with self.lock:
            for key, value in (values or {}).items():
                key = str(key).strip().lower().replace(" ", "_")[:40]
                if key:
                    self.case_doc["inputs"][key] = str(value)[:500]
        return self.cases_payload() or {}

    def clear_cases(self) -> Dict[str, Any]:
        with self.lock:
            self.case_doc = None
        return {"ok": True}

    # -- AI player settings (key kept in memory; never written to reports) --------
    def _ai_file(self) -> str:
        return os.path.join(self.workdir, "ai_settings.json")

    def _load_ai_settings(self) -> Dict[str, Any]:
        settings: Dict[str, Any] = {"enabled": False, "provider": "ollama", "model": "", "base_url": "", "api_key": ""}
        try:
            with open(self._ai_file(), encoding="utf-8") as handle:
                saved = json.load(handle)
            settings.update({k: saved[k] for k in ("enabled", "provider", "model", "base_url") if k in saved})
        except (OSError, ValueError):
            pass
        env_key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(settings["provider"])
        if env_key and os.environ.get(env_key):
            settings["api_key"] = os.environ[env_key]
        return settings

    def ai_public(self) -> Dict[str, Any]:
        from .policies.agent import PROVIDERS, AIConfig

        cfg = AIConfig(**{k: self.ai_settings.get(k, "") for k in ("provider", "model", "base_url", "api_key")})
        out = cfg.public()
        out["enabled"] = bool(self.ai_settings.get("enabled"))
        out["providers"] = {k: {"label": v["label"], "model": v["model"], "needs_key": v["needs_key"]} for k, v in PROVIDERS.items()}
        return out

    def set_ai(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from .policies.agent import PROVIDERS

        with self.lock:
            if "provider" in payload and payload["provider"] in PROVIDERS:
                if payload["provider"] != self.ai_settings.get("provider"):
                    self.ai_settings["model"] = ""
                    self.ai_settings["base_url"] = ""
                self.ai_settings["provider"] = payload["provider"]
            for key in ("model", "base_url"):
                if key in payload:
                    self.ai_settings[key] = str(payload[key] or "").strip()[:200]
            if "api_key" in payload and payload["api_key"] is not None:
                self.ai_settings["api_key"] = str(payload["api_key"]).strip()[:300]
            if "enabled" in payload:
                self.ai_settings["enabled"] = bool(payload["enabled"])
            try:  # remember the choice, never the key
                with open(self._ai_file(), "w", encoding="utf-8") as handle:
                    json.dump({k: v for k, v in self.ai_settings.items() if k != "api_key"}, handle)
            except OSError:
                pass
        self.log("info", f"AI player {'ON' if self.ai_settings['enabled'] else 'OFF'}: {self.ai_public()['label']} "
                 f"({self.ai_public()['model']})")
        return self.ai_public()

    def test_ai(self) -> Dict[str, Any]:
        from .policies.agent import AIConfig, check_connection

        cfg = AIConfig(**{k: self.ai_settings.get(k, "") for k in ("provider", "model", "base_url", "api_key")})
        return check_connection(cfg)

    def _ai_config_for_run(self) -> Dict[str, Any]:
        if not self.ai_settings.get("enabled"):
            return {}
        return {k: self.ai_settings.get(k, "") for k in ("provider", "model", "base_url", "api_key")}

    # -- running written test cases ----------------------------------------------
    def start_cases(self, where: str = "", only: Optional[List[str]] = None, guided: bool = False) -> Dict[str, Any]:
        from .caserun import CaseRunner
        from .simulator import SimDevice

        with self.lock:
            if self.status == "running":
                raise StudioError("a test is already running")
            if self._paused_session:
                raise StudioError("resume the paused exploration or choose Start over first")
            case_doc = self.case_doc
            if guided:
                case_doc = first_customer_guide((self.apk or {}).get("package", ""))
                if not case_doc or where == "practice":
                    raise StudioError("Choose the Unity first-customer game on your phone to run this walkthrough.")
                where = "phone"
            if not case_doc or not case_doc.get("cases"):
                raise StudioError("upload a .md file with test cases first (step 3)")
            inputs = dict(case_doc["inputs"])
            missing = [name for name in case_doc["required_inputs"] if not inputs.get(name)]
            if missing:
                self.log("warn", f"running without these inputs: {', '.join(missing)}")
            cases = [case for case in case_doc["cases"] if not only or case["id"] in only]
            practice = where == "practice" or (where != "phone" and not self._has_device())
            serial = ""
            if not practice:
                if not self._has_target():
                    raise StudioError("choose which game to test on the device first: pick one on the phone or add an .apk file")
                serial = self._pick_serial()
                if not serial:
                    raise StudioError("no phone is connected - plug it in (USB debugging on) or choose Practice phone")
            package = "com.example.neondrift" if practice else (self.apk or {}).get("package", "")
            activity = "" if practice else (self.apk or {}).get("activity", "")
            stamp = time.strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join(self.runs_dir, f"{stamp}_cases_{package}")
            self.status, self.error, self.mode = "running", "", "cases"
            self.qa_review = None
            self.session_dir = out_dir
            self.case_result = None
            ai = {} if guided else self._ai_config_for_run()
            self.case_run = {"done": 0, "total": len(cases), "results": [], "current": "", "phase": "starting",
                             "ai": bool(ai), "guided": guided, "where": "practice" if practice else "phone"}
            self.live_frames.clear()
            self._frame_seq = 0
            self.stop_event.clear()
            self.progress = {"step": 0, "total": len(cases), "action": "starting", "phase": "cases", "elapsed": 0.0}

        def worker() -> None:
            try:
                if practice:
                    device = SimDevice(package=package, seed=self.plan.seed)
                    device.install("practice.apk")
                    device.launch(package)
                else:
                    device = AdbDevice(serial=serial, adb_path=self.adb_path)
                    if self.apk_path and self.plan.install:
                        self.log("info", "installing the game file on the phone…")
                        try:
                            device.install(self.apk_path)
                        except AdbError as exc:
                            self.log("warn", f"install skipped ({str(exc)[:80]}) - testing the version on the phone")
                    device.launch(package, activity)
                runner = CaseRunner(device, package, activity, cases, inputs, out_dir, self.desk, ai_config=ai,
                                    should_stop=self.stop_event.is_set, on_event=self.log,
                                    on_update=self._on_case_update, on_frame=self._on_frame, simulate=practice)
                self.log("info", f"TEST CASES started on {'the practice phone' if practice else 'phone ' + serial}: "
                         f"{len(cases)} case(s), " + ("AI player " + self.ai_public()['model'] if ai else "you do the steps, the tester watches"))
                payload = runner.run()
                s = payload["summary"]
                self.log("info" if not s["failed"] else "error",
                         f"TEST CASES finished: ✅ {s['passed']} passed · ❌ {s['failed']} failed · ⚠️ {s['not_passed']} not passed")
                with self.lock:
                    self.case_result = dict(payload, run=os.path.basename(out_dir), guided=guided)
                    self.status = "done"
                    self.progress.update(phase="done", action="finished")
            except Exception as exc:  # surface everything on the page
                traceback.print_exc()
                self.log("error", f"test cases stopped: {type(exc).__name__}: {exc}")
                with self.lock:
                    self.status, self.error = "error", f"{type(exc).__name__}: {exc}"

        self.thread = threading.Thread(target=worker, name="apkharness-cases", daemon=True)
        self.thread.start()
        return {"status": "running", "cases": len(cases)}

    def _on_case_update(self, state: Dict[str, Any]) -> None:
        with self.lock:
            self.case_run.update(state)
            self.progress.update(step=state.get("done", 0), total=state.get("total", 0),
                                 action=str(state.get("phase", ""))[:100])

    def answer_question(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.desk.answer(str(payload.get("id", "")), str(payload.get("answer", "")), str(payload.get("note", "")))
        if not ok:
            raise StudioError("that question is no longer open")
        self.log("info", f"you answered: {payload.get('answer')}")
        return {"ok": True}

    def update_case(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.suite is None:
            raise StudioError("upload a requirements document first")
        case_id = str(payload.get("id", ""))
        fields = {key: value for key, value in payload.items() if key != "id"}
        try:
            case = self.suite.update_case(case_id, **fields)
        except KeyError as exc:
            raise StudioError(str(exc)) from exc
        except ValueError as exc:
            raise StudioError(str(exc)) from exc
        self.suite_store.save(self.suite)
        return {"case": case.to_dict(), "suite": self.suite.summary()}

    def approve_suite(self, approved: bool = True) -> Dict[str, Any]:
        if self.suite is None:
            raise StudioError("nothing to approve yet")
        with self.lock:
            self.suite.approved = approved
            self.suite_store.save(self.suite)
            return {"suite": self.suite.summary()}

    def regenerate_cases(self) -> Dict[str, Any]:
        if self.suite is None or self.doc is None:
            raise StudioError("upload a requirements document first")
        document = parse_document(self.doc["name"], (self.doc_text or "").encode("utf-8"))
        self.suite.cases = regenerate(self.suite.cases, document.requirements)
        self.suite_store.save(self.suite)
        return {"suite": self.suite.summary(), "testcases": [case.to_dict() for case in self.suite.cases][:600]}

    def readiness(self, refresh: bool = False) -> Dict[str, Any]:
        """Human-readable device checklist shown on the dashboard."""
        with self.lock:
            if not refresh and self._readiness and (time.time() - self._readiness_at) < 20:
                return dict(self._readiness)
        info = self.device_list(refresh=refresh)
        devices = info.get("devices") or []
        online = [device for device in devices if device.get("state") == "device"]
        unauthorized = [device for device in devices if device.get("state") == "unauthorized"]
        checks: List[Dict[str, Any]] = [
            {"id": "adb", "label": "adb installed", "ok": bool(self.adb_path),
             "hint": "set ANDROID_HOME or install Android platform-tools"},
            {"id": "device", "label": "phone connected", "ok": bool(online),
             "hint": "plug in the phone, enable Developer options + USB debugging"},
            {"id": "authorized", "label": "authorised", "ok": not unauthorized,
             "hint": "accept the 'Allow USB debugging' prompt on the phone"},
        ]
        serial = self.serial or (online[0]["serial"] if online else "")
        input_ok, input_hint = True, ""
        if serial:
            device = AdbDevice(serial=serial, adb_path=self.adb_path or "adb")
            input_ok, input_hint = device.check_input()
        checks.append({"id": "input", "label": "input injection", "ok": input_ok,
                       "hint": input_hint or "the phone accepts taps and swipes"})
        payload = {
            "checks": checks,
            "ready": all(check["ok"] for check in checks),
            "serial": serial,
            "hint": input_hint if not input_ok else ("" if online else info.get("hint", "")),
            "at": time.time(),
        }
        with self.lock:
            self._readiness = payload
            self._readiness_at = time.time()
        return dict(payload)

    # -- state -------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            recent = list(self.live_frames)[-10:]
            steps = list(self.step_log)[-250:]
            return {
                "version": __version__,
                "status": self.status,
                "error": self.error,
                "apk": self.apk,
                "plan": self.plan.to_dict(),
                "plan_errors": list(self.plan_errors),
                "progress": dict(self.progress),
                "frames": {
                    "count": len(self.live_frames),
                    "latest": self.live_frames[-1].index if self.live_frames else -1,
                    "recent": [frame.to_dict() for frame in recent],
                },
                "steps": steps,
                "steps_total": len(self.step_log),
                "findings": list(self.findings),
                "checks": list(self.checks),
                "check_summary": summarize([CheckResult(**check) for check in self.checks]) if self.checks else {},
                "summary": dict(self.summary),
                "video": dict(self.video_meta),
                "artifacts": dict(self.artifacts),
                "adb": {"path": self.adb_path, "found": bool(self.adb_path)},
                "device": {"selected": self.serial, "model": self._device_model(self.serial)},
                "readiness": dict(self._readiness) or self.readiness(),
                "requirements": self._requirements_payload(),
                "suite": self.suite.summary() if self.suite else None,
                "testcases": [case.to_dict() for case in (self.suite.cases if self.suite else [])][:600],
                "product": self.product,
                "qa_review": self.qa_review,
                "autoqa": dict(self.autoqa),
                "poll_hint_ms": STATE_POLL_HINT_MS,
                "workdir": self.workdir,
            }

    def _device_model(self, serial: str) -> str:
        for device in self._devices:
            if device.get("serial") == serial:
                return str(device.get("model") or "")
        return ""

    # -- upload / plan -----------------------------------------------------
    def receive_apk(self, filename: str, stream, length: int) -> Dict[str, Any]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename or "upload.apk"))
        if not safe_name.lower().endswith(".apk"):
            safe_name += ".apk"
        target = os.path.join(self.uploads_dir, f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name}")
        remaining = length
        with open(target, "wb") as handle:
            while remaining > 0:
                chunk = stream.read(min(1 << 20, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            os.remove(target)
            raise StudioError("upload was interrupted")
        return self._adopt_apk(target, safe_name)

    def _adopt_apk(self, target: str, safe_name: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "name": safe_name,
            "path": target,
            "size": os.path.getsize(target),
            "package": "",
            "version": "",
            "activity": "",
            "abis": [],
            "error": "",
        }
        try:
            parsed = inspect_apk(target)
            info.update(
                package=parsed.package,
                version=f"{parsed.version_name} ({parsed.version_code})" if parsed.version_name else "",
                activity=parsed.launch_activity,
                abis=parsed.abis,
                min_sdk=parsed.min_sdk,
                target_sdk=parsed.target_sdk,
                sha256=parsed.sha256[:32],
                permissions=len(parsed.permissions),
            )
        except (ApkError, OSError) as exc:
            info["error"] = f"could not read the manifest: {exc}"
        product = classify_apk(target, str(info.get("package") or ""))
        info["product"] = product

        with self.lock:
            if self.status == "running":
                raise StudioError("stop the running test first")
            self._discard_paused_run()
            self.apk = info
            self.apk_path = target
            self.status = "idle"
            self.error = ""
            self.checks = []
            self.findings = []
            self.summary = {}
            self.video_meta = {}
            self.artifacts = {}
            self.step_log.clear()
            self.step_interruptions.clear()
            if info.get("package"):
                self.plan.name = f"{info['package']} smoke test"
            self.progress = {"step": 0, "total": self.plan.steps, "action": "", "elapsed": 0.0}
            self.product = product
            self.qa_review = None
        if hasattr(self, "events"):
            self.log("info", f"APK loaded: {info.get('package') or safe_name} {info.get('version') or ''} → "
                     f"{product['kind'].upper()} ({product['engine']})")
        return info

    def set_plan(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                errors = [f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
                with self.lock:
                    self.plan_errors = errors
                raise StudioError("; ".join(errors)) from exc
        if not isinstance(payload, dict):
            raise StudioError("plan must be a JSON object")
        errors = validate_plan_dict(payload)
        with self.lock:
            self.plan_errors = errors
        if errors:
            raise StudioError("; ".join(errors))
        plan = Plan.from_dict(payload)
        with self.lock:
            self.plan = plan
            if self.status == "idle":
                self.progress["total"] = plan.steps
        return plan.to_dict()

    def set_target(self, target: str) -> Dict[str, Any]:
        """Explicit target choice from the dashboard; pins it against auto-switch."""
        if target not in ("device", "simulator"):
            raise StudioError("target must be 'device' or 'simulator'")
        with self.lock:
            self._target_pinned = True
            self.plan.target = target
            if target == "device" and self.plan.capture == "frames":
                self.plan.capture = "screenrecord"
            if target == "simulator" and self.plan.capture == "screenrecord":
                self.plan.capture = "frames"
            return self.plan.to_dict()

    def restart(self) -> Dict[str, Any]:
        """Clear the previous session but keep the APK, plan and device."""
        with self.lock:
            if self.status == "running":
                raise StudioError("stop the running test first")
            self._discard_paused_run()
            self.status = "idle"
            self.error = ""
            self.findings = []
            self.checks = []
            self.summary = {}
            self.video_meta = {}
            self.artifacts = {}
            self.session_dir = ""
            self.step_log.clear()
            self.step_interruptions.clear()
            self.live_frames.clear()
            self._frame_seq = 0
            self.progress = {"step": 0, "total": self.plan.steps, "action": "", "phase": "idle", "elapsed": 0.0}
            return {"status": "idle", "plan": self.plan.to_dict()}

    def reset_plan(self) -> Dict[str, Any]:
        with self.lock:
            target = "device" if self._has_device() else "simulator"
            self.plan = default_plan(target=target)
            self.plan_errors = []
            if self.status == "idle":
                self.progress["total"] = self.plan.steps
            return self.plan.to_dict()

    # -- run ---------------------------------------------------------------
    def _has_device(self) -> bool:
        try:
            return any(device.online for device in Adb.list_devices(self.adb_path))
        except (AdbError, AdbNotFound, OSError):
            return False

    def _pick_serial(self) -> str:
        info = self.device_list(refresh=True)
        online = [device for device in info["devices"] if device.get("state") == "device"]
        if self.serial:
            for device in online:
                if device["serial"] == self.serial:
                    return self.serial
        if online:
            self.serial = online[0]["serial"]
            return self.serial
        return ""

    def start(self, section_size: int = 0, objective: str = "") -> Dict[str, Any]:
        with self.lock:
            if self.status == "running":
                raise StudioError("a test is already running")
            if self._paused_session:
                return self.resume()
            plan = self.plan
            serial = ""
            if plan.target == "device":
                if not self.adb_path:
                    raise StudioError("adb was not found; set ANDROID_HOME or install platform-tools")
                if not self._has_target():
                    raise StudioError("choose which game to test on the device first: pick one on the phone or add an .apk file")
                serial = self._pick_serial()
                if not serial:
                    raise StudioError(
                        "no device is connected. Enable Developer options + USB debugging, "
                        "accept the RSA prompt on the phone, then press Refresh."
                    )
                ready = self.readiness(refresh=True)
                if plan.policy == "observe":
                    ready = {"checks": ready["checks"], "ready": True, "hint": ready.get("hint", "")}
                if not ready["ready"]:
                    failing = [check for check in ready["checks"] if not check["ok"]]
                    detail = "; ".join(f"{check['label']}: {check['hint']}" for check in failing)
                    raise StudioError(detail or "device is not ready")
            if plan.target == "simulator" and not self.apk_path:
                pass  # the simulator does not need a real APK

            self.status = "running"
            self.error = ""
            self.findings = []
            self.checks = []
            self.summary = {}
            self.video_meta = {}
            self.artifacts = {}
            self.session_dir = ""
            self.step_log.clear()
            self.live_frames.clear()
            self._frame_seq = 0
            shutil.rmtree(self.live_dir, ignore_errors=True)
            os.makedirs(self.live_dir, exist_ok=True)
            self.stop_event.clear()
            self.step_interruptions.clear()
            self.progress = {"step": 0, "total": plan.steps, "action": "starting",
                             "phase": "preparing", "elapsed": 0.0,
                             "section": 1, "section_size": section_size,
                             "policy": plan.policy, "gameplay_objective": objective,
                             "schedule": {"startup_runs": plan.startup_runs, "interruptions": list(plan.interruptions),
                                          "interrupt_every": plan.interrupt_every} if plan.policy != "observe" else {}}

            config = RunConfig(
                apk=self.apk_path,
                package=(self.apk or {}).get("package", "") or "",
                activity=(self.apk or {}).get("activity", "") or "",
                serial=serial,
                adb_path=self.adb_path or "adb",
                policy=plan.policy,
                steps=plan.steps,
                time_budget_s=plan.minutes * 60,
                section_size=section_size,
                step_delay_s=0.35 if plan.target == "device" else 0.25,
                metrics_every=5,
                screenshot_every=1,
                ui_every=2 if plan.target == "device" else 1,
                out_root=self.runs_dir,
                seed=plan.seed,
                simulate=plan.target == "simulator",
                no_install=(not plan.install) or not self.apk_path,
                ignore_patterns=list(plan.ignore),
                plan=plan.to_dict(),
                label="studio",
                interruptions=list(plan.interruptions),
                ai_config=self._ai_config_for_run() if plan.policy == "agent" else {},
                gameplay_objective=objective,
                interrupt_every=plan.interrupt_every,
                startup_runs=plan.startup_runs,
                stuck_after=STUCK_INPUTS,
            )
            self.thread = threading.Thread(
                target=self._worker, args=(plan, config, serial), name="apkharness-run", daemon=True
            )
            self.qa_review = None
            self.mode = "explore"
            self.case_run = {}
            self.thread.start()
        self.log("info", f"test started on {'phone ' + serial if serial else 'simulator'}: "
                 f"{plan.name}, {plan.steps} steps / {plan.minutes:g} min")
        return {"status": "running", "plan": plan.to_dict(), "serial": serial}

    def resume(self, expected_run: str = "", after_step: Optional[int] = None) -> Dict[str, Any]:
        with self.lock:
            if self.status == "running":
                raise StudioError("a test is already running")
            session = self._paused_session
            if session is None:
                raise StudioError("there is no paused exploration to resume")
            if expected_run and (os.path.basename(session.out_dir) != expected_run or session.memory.step != after_step):
                raise StudioError("The paused run changed. Check the current section before continuing.")
            config = session.config
            if not config.simulate and session.memory.step < config.steps:
                devices = self.device_list(refresh=True)["devices"]
                if not any(d["serial"] == config.serial and d["state"] == "device" for d in devices):
                    raise StudioError("reconnect the same phone to resume this test")
                self.serial = config.serial
                if session.restored_from_disk:
                    try:
                        ready = session.device.alive(config.package)
                    except DeviceUnavailable:
                        ready = False
                    if not ready:
                        raise StudioError("Open the game on the same phone before continuing the saved run.")
            plan = Plan.from_dict(config.plan)
            self.stop_event.clear()
            self.status = "running"
            self.error = ""
            section = min(session.memory.step, config.steps - 1) // config.section_size + 1 if config.section_size else 1
            self.progress.update(phase="running", action="resuming", section=section)
            self.thread = threading.Thread(target=self._worker, args=(plan, config, config.serial, session),
                                           name="apkharness-run", daemon=True)
            self.thread.start()
            self.log("info", f"test resumed at step {session.memory.step + 1}")
            return {"status": "running", "resumed": True, "serial": config.serial}

    def _discard_paused_run(self) -> None:
        if self._paused_session:
            self._paused_session.clear_checkpoint()
            self._paused_session.close()
            self._paused_session = None

    def _restore_saved_run(self) -> None:
        root = os.path.join(os.path.realpath(self.workdir), "runs")
        if os.path.normcase(os.path.realpath(self.runs_dir)) != os.path.normcase(root):
            return
        for name in sorted(os.listdir(root), reverse=True):
            out_dir = os.path.join(root, name)
            checkpoint = os.path.join(out_dir, CHECKPOINT_FILE)
            if (not SAVED_RUN_ID.fullmatch(name) or os.path.normcase(os.path.realpath(checkpoint)) != os.path.normcase(checkpoint)
                    or not os.path.isfile(checkpoint)):
                continue
            try:
                with open(checkpoint, encoding="utf-8") as handle:
                    data = json.load(handle)
                if data.get("version") != 1:
                    continue
                config = RunConfig(**data["config"])
                config.out_root, config.adb_path = self.runs_dir, self.adb_path or "adb"
                if config.policy == "agent":
                    config.ai_config["api_key"] = self.ai_settings.get("api_key", "")
                state = data["studio"]
                plan = Plan.from_dict(config.plan)
                session = Session(config, on_frame=self._on_frame, on_step=self._on_step, on_phase=self._on_phase,
                                  should_stop=self.stop_event.is_set, allow_resume=True, checkpoint_context=state)
                session.restore_checkpoint(out_dir, data)
                if not session.resumable or not 0 <= session.memory.step <= config.steps:
                    continue
                session.write_recovered_report()
                payload, findings, checks = self._write_session_checks(session, plan)
                suite = self.suite_store.load() if state.get("suite") else None
                if suite and suite.summary() != state["suite"]:
                    suite = None
                review = expert_review(payload, state.get("product"), suite, session._log_lines)
                self._write_review(out_dir, review)
            except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
                self.log("warn", f"could not restore {name}: {exc}")
                continue

            self.apk, self.apk_path, self.product = state.get("apk"), config.apk, state.get("product")
            self.suite, self.plan, self.serial = suite, plan, config.serial
            if state.get("preset") in AUTOQA_PRESETS:
                self.autoqa["preset"] = state["preset"]
            self.stop_event.set()  # reopening the tester requires an explicit resume
            self.status, self.session_dir, self._paused_session = "done", out_dir, session
            self.qa_review, self.summary, self.findings = review, payload["summary"], findings
            self.checks = [check.to_dict() for check in checks]
            self.artifacts = {"report": "report.html", "junit": "junit.xml", "session": "session.json",
                              "checks": "checks.json", "logcat": "logcat.txt", "metrics": "metrics.json"}
            step = session.memory.step
            # At a boundary the preceding section is the one shown as complete.
            shown_step = step - int(session.at_section_boundary or step == config.steps)
            section = shown_step // config.section_size + 1 if config.section_size else 1
            self.progress = {"step": step, "total": config.steps, "elapsed": payload["summary"]["duration_s"],
                             "phase": "done", "action": "restored", "policy": config.policy, "section": section,
                             "section_size": config.section_size, "gameplay_objective": config.gameplay_objective,
                             "schedule": {"startup_runs": config.startup_runs, "interruptions": config.interruptions,
                                          "interrupt_every": config.interrupt_every} if config.policy != "observe" else {}}
            self.step_log.extend(dict(row, elapsed=row["time"], new_screen=row["new"]) for row in session.result.timeline)
            self.step_interruptions = {entry["step"]: {"alive": entry["survived"], "skipped": entry["skipped"]}
                                       for entry in session.result.interruptions}
            frames = list(session.result.timeline[-LIVE_FRAMES:])
            if session.stuck.get("screenshot"):
                frames.append({"step": step, "shot": session.stuck["screenshot"], "action": "Waiting for gameplay help"})
            for row in frames:
                shot = os.path.join(session.screenshots_dir, os.path.basename(row.get("shot") or ""))
                if os.path.isfile(shot) and os.path.normcase(os.path.realpath(shot)) == os.path.normcase(shot):
                    self._frame_seq += 1
                    self.live_frames.append(LiveFrame(self._frame_seq, row["step"], row["action"], bool(row.get("crashes")), shot))
            self.log("info", f"restored saved exploration at step {step}")
            return

    def stop(self) -> Dict[str, Any]:
        with self.lock:
            if self.status == "running" and not self.stop_event.is_set():
                self.log("warn", "STOP pressed - finishing the current action and writing the report")
            self.stop_event.set()
        return {"stopping": True}

    def start_over(self) -> Dict[str, Any]:
        """Stop whatever runs and clear the screen; the chosen game and document stay."""
        with self.lock:
            self.stop()
            thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=30)
            if thread.is_alive():
                raise StudioError("the phone is still busy finishing a command - try again in a few seconds")
        with self.lock:
            if self.thread is not thread and self.status == "running":
                raise StudioError("a test just started - stop it before clearing the run")
            self._discard_paused_run()
            self.status = "idle"
            self.error = ""
            self.findings, self.checks, self.summary = [], [], {}
            self.video_meta, self.artifacts = {}, {}
            self.session_dir = ""
            self.qa_review = None
            self.step_log.clear()
            self.step_interruptions.clear()
            self.live_frames.clear()
            self._frame_seq = 0
            self.progress = {"step": 0, "total": self.plan.steps, "action": "", "phase": "idle", "elapsed": 0.0}
            self.events.clear()
        self.log("info", "started over - ready for a new test")
        return {"status": "idle"}

    def clear_requirements(self) -> Dict[str, Any]:
        with self.lock:
            self.suite = None
            self.doc = None
            self.doc_text = ""
        self.log("info", "requirements document removed")
        return {"ok": True}

    def _protected_run_dirs(self) -> set[str]:
        directories = []
        if self.status == "running":
            directories.append(self.session_dir)
            if self._session is not None:
                directories.append(self._session.out_dir)
        if self._paused_session is not None:
            directories.append(self._paused_session.out_dir)
        return {os.path.normcase(os.path.realpath(path)) for path in directories if path}

    def run_history(self) -> Dict[str, Any]:
        from .dashboard import list_runs

        with self.lock:
            history = list_runs(self.runs_dir)
            protected = self._protected_run_dirs()
            for run in history["runs"]:
                path = os.path.join(self.runs_dir, run["id"])
                run["deletable"] = (SAVED_RUN_ID.fullmatch(run["id"]) is not None
                                    and os.path.normcase(os.path.realpath(path)) not in protected)
        return history

    def delete_saved_runs(self, run_ids: Any) -> Dict[str, Any]:
        if not isinstance(run_ids, list) or not run_ids or any(
            not isinstance(run_id, str) or not SAVED_RUN_ID.fullmatch(run_id) or run_id.endswith(".")
            for run_id in run_ids
        ):
            raise StudioError("Select one or more saved test runs.")

        deleted, errors = [], []
        with self.lock:
            workdir = os.path.realpath(self.workdir)
            root = os.path.join(workdir, "runs")
            if os.path.normcase(os.path.realpath(self.runs_dir)) != os.path.normcase(root):
                raise StudioError("The saved tests folder must be inside the Game Tester work folder.")
            protected = self._protected_run_dirs()
            paths = {}
            for run_id in dict.fromkeys(run_ids):
                path = os.path.join(root, run_id)
                resolved = os.path.normcase(os.path.realpath(path))
                if resolved != os.path.normcase(path) or resolved in protected:
                    raise StudioError(f"Cannot delete a running, paused or linked test ({run_id}).")
                try:
                    info = os.lstat(path)
                except FileNotFoundError:
                    continue
                reparse_point = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                if not stat.S_ISDIR(info.st_mode) or reparse_point:
                    raise StudioError(f"Not a saved test folder: {run_id}")
                paths[run_id] = path

            last_run = os.path.normcase(os.path.realpath(self.session_dir)) if self.session_dir else ""
            for run_id, path in paths.items():
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    errors.append({"run": run_id, "error": exc.strerror or str(exc)})
                    continue
                deleted.append(run_id)
                if os.path.normcase(path) == last_run:
                    live_dir = os.path.normcase(os.path.join(workdir, "live"))
                    for frame in self.live_frames:
                        if os.path.normcase(os.path.realpath(os.path.dirname(frame.path))) != live_dir:
                            continue
                        try:
                            os.unlink(frame.path)
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            errors.append({"run": run_id, "error": f"Could not remove a cached frame: {exc.strerror or exc}"})
                    self.restart()
                    self.qa_review = self.case_result = None
                    self.case_run = {}
        if deleted:
            self.log("info", f"deleted {len(deleted)} saved test run(s)")
        return {"deleted": deleted, "errors": errors}

    # -- worker ------------------------------------------------------------
    def _on_frame(self, step: int, png: bytes, action: str, finding: bool) -> None:
        self._frame_seq += 1
        path = os.path.join(self.live_dir, f"frame_{self._frame_seq:05d}.png")
        try:
            with open(path, "wb") as handle:
                handle.write(png)
        except OSError:
            return
        with self.lock:
            self.live_frames.append(
                LiveFrame(index=self._frame_seq, step=step, action=action, finding=finding, path=path)
            )
            self.progress.update(step=step, action=action)

    def _on_phase(self, phase: str) -> None:
        if phase == "phone-lost":
            self.log("error", "the phone stopped answering - check the USB cable; waiting 20 s for it to come back")
        if phase == "using-installed":
            self.log("warn", "the phone already has a NEWER version of this game - testing that version "
                     "(your phone's game and its saved progress were not touched)")
        previous = str(self.progress.get("phase") or "")
        if not phase.startswith("interrupt:") and not (phase == "running" and previous.startswith("interrupt:")):
            self.log("info", f"phase: {phase}")
        with self.lock:
            self.progress["phase"] = phase
            self.progress["action"] = {
                "installing": "installing APK on device",
                "launching": "launching the game",
                "running": "running",
                "reporting": "writing report",
            }.get(phase, phase)

    def _on_step(self, record: Dict[str, Any]) -> None:
        if record.get("kind") == "interrupt":
            with self.lock:
                self.step_interruptions[record["step"]] = {
                    "alive": record.get("alive"), "skipped": record.get("skipped"),
                }
            self.log("info" if record.get("alive") else "error",
                     f"step {record.get('step')}: {record.get('action')} → {record.get('note')}"
                     + ("" if record.get("alive") else "  ✗ APP DIED"))
            return
        for crash in record.get("crashes") or []:
            self.log("error", f"step {record.get('step')}: FINDING {crash}")
        if record.get("alive") is False:
            self.log("warn", f"step {record.get('step')}: app process is not alive - relaunching")
        with self.lock:
            self.step_log.append(record)
            self.progress["step"] = int(record.get("step") or self.progress.get("step") or 0)
            self.progress["action"] = str(record.get("action") or "")
            self.progress["elapsed"] = float(record.get("elapsed") or self.progress.get("elapsed") or 0.0)

    def _write_session_checks(self, session: Session, plan: Plan):
        result = session.result
        findings = [dict(item) for item in result.crashes]
        check_results = evaluate(plan, result.summary, findings)
        check_summary = summarize(check_results)
        payload = result.to_dict()
        payload["checks"] = [check.to_dict() for check in check_results]
        complete = exploration_coverage(payload)[2] == "completed"
        payload["summary"]["verdict"] = check_summary["verdict"] if complete else "incomplete"
        payload["summary"]["check_summary"] = check_summary
        write_html(payload, session.out_dir)
        write_junit(payload, os.path.join(session.out_dir, "junit.xml"))
        with open(os.path.join(session.out_dir, "checks.json"), "w", encoding="utf-8") as handle:
            json.dump(payload["checks"], handle, indent=2)
        with open(os.path.join(session.out_dir, "session.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return payload, findings, check_results

    def _write_review(self, out_dir: str, review: Dict[str, Any]) -> None:
        with open(os.path.join(out_dir, "qa_review.json"), "w", encoding="utf-8") as handle:
            json.dump(review, handle, indent=2)
        with open(os.path.join(out_dir, "qa_review.md"), "w", encoding="utf-8") as handle:
            handle.write(review_markdown(review))

    def _worker(self, plan: Plan, config: RunConfig, serial: str, session: Optional[Session] = None) -> None:
        recorder: Optional[ScreenRecorder] = None
        video_meta: Dict[str, Any] = dict(self.video_meta) if session else {
            "available": False, "backend": "", "frames": 0, "path": "", "kind": "", "error": "",
        }
        try:
            if (plan.target == "device" and plan.capture in ("screenrecord", "both")
                    and (session is None or session.memory.step < config.steps)):
                recorder = ScreenRecorder(Adb(path=self.adb_path or "adb", serial=serial or None))
                if not recorder.start():
                    video_meta["error"] = f"screenrecord unavailable: {recorder.error}"
                    recorder = None
                else:
                    with self.lock:
                        self._recorder = recorder

            if session is None:
                session = Session(
                    config,
                    on_frame=self._on_frame,
                    on_step=self._on_step,
                    on_phase=self._on_phase,
                    should_stop=self.stop_event.is_set,
                    allow_resume=True,
                    checkpoint_context={"apk": self.apk, "product": self.product, "preset": self.autoqa["preset"],
                                        "suite": self.suite.summary() if self.suite and self.autoqa.get("use_spec") else None},
                )
            self._session = session
            result = session.run()
            self.session_dir = session.out_dir
            if session.end_reason == "section_complete":
                self.log("info", f"section complete at step {session.memory.step}")
            elif session.end_reason == "section_time_limit":
                self.log("warn", f"section paused at step {session.memory.step} after reaching its time limit")
            elif session.end_reason == "stuck":
                self.log("warn", f"exploration needs help after step {session.memory.step}: the same screen remained")
            if getattr(session, "device_lost", False):
                self.log("error", f"the PHONE DISCONNECTED at step {result.summary.get('steps_run')} - "
                         "reconnect the same phone to continue")
            if session.stopped_by_user:
                message = "resume testing to continue" if session.resumable else "the result covers what ran"
                self.log("warn", f"test stopped by you at step {result.summary.get('steps_run')} - {message}")

            payload, findings, check_results = self._write_session_checks(session, plan)
            review = None
            try:
                from .dashboard import compare_runs, find_baseline

                comparison = None
                run_id = os.path.basename(session.out_dir)
                baseline = find_baseline(self.runs_dir, run_id)
                if baseline and not session.resumable:
                    try:
                        comparison = compare_runs(self.runs_dir, run_id, baseline)
                        self.log("warn" if comparison["regressions"] else "info",
                                 f"COMPARE vs {comparison['baseline_label']}: {comparison['headline']}")
                    except Exception as exc:  # comparison is a bonus
                        self.log("warn", f"build comparison skipped: {exc}")
                for event in payload.get("interruptions") or []:
                    if not event.get("skipped"):
                        self.log("info" if event.get("survived") else "error",
                                 f"  lifecycle step {event['step']}: {event['kind']} → "
                                 f"{'survived' if event.get('survived') else 'APP DIED'} ({event.get('detail')})")
                st = payload.get("startup") or {}
                if st.get("cold_avg_ms"):
                    self.log("info", f"  start-up: cold {st['cold_avg_ms']} ms, warm {st.get('warm_avg_ms')} ms "
                             f"(runs {st.get('cold_ms')})")
                review = expert_review(payload, self.product, self.suite if self.autoqa.get("use_spec") else None,
                                       list(getattr(session, "_log_lines", []) or []), comparison)
                self._write_review(session.out_dir, review)
                auto = {c["id"]: c["auto_status"] for c in review["cases"] if c["auto_status"] != "MANUAL"}
                if auto and self.suite is not None and review["decision"] != "INCOMPLETE":
                    merge_statuses(self.suite, auto)
                    self.suite_store.save(self.suite)
                self.log("error" if review["decision"] == "NO-GO" else
                         ("warn" if review["decision"] == "CONDITIONAL" else "info"),
                         f"QA REVIEW: {review['decision']} (risk {review['risk_score']}/100) - "
                         f"{review['decision_reason']}")
                for issue in review["issues"][:5]:
                    self.log("warn", f"  [{issue['severity']}] {issue['title'][:140]} → {issue['cause']}")
                if auto:
                    self.log("info", f"  spec cases auto-marked: {len(auto)} "
                             f"({sum(1 for v in auto.values() if v == 'FAIL')} FAIL)")
            except Exception as exc:  # the review must never lose a finished run
                traceback.print_exc()
                self.log("error", f"QA review failed: {exc}")

            if recorder is not None:
                first_video = os.path.join(session.out_dir, "session.mp4")
                part = (f"session-part-{time.time_ns()}.mp4" if os.path.isfile(first_video) else "session.mp4")
                mp4 = recorder.stop_and_pull(os.path.join(session.out_dir, part))
                if mp4:
                    video_meta = {
                        "available": True,
                        "backend": "screenrecord/mp4",
                        "path": mp4,
                        "kind": "video/mp4",
                        "frames": None,
                        "error": "",
                    }
                    duration = float(result.summary.get("duration_s") or 0)
                    if duration > recorder.time_limit:
                        video_meta["note"] = (
                            f"Android caps one screenrecord file at {recorder.time_limit}s; "
                            f"this session ran {duration:.0f}s"
                        )
                else:
                    video_meta["error"] = recorder.error or "screenrecord produced no video"
                recorder = None
                with self.lock:
                    self._recorder = None

            if plan.record_video and plan.capture in ("frames", "both"):
                frames = video.frames_from_timeline(result.timeline, session.screenshots_dir) or [
                    video.Frame(step=frame.step, path=frame.path, action=frame.action, finding=frame.finding)
                    for frame in list(self.live_frames)
                ]
                built = video.build(frames, session.out_dir, fps=plan.video_fps)
                if built.get("path") and video_meta.get("path"):
                    video_meta["gif"] = str(built["path"])
                elif built.get("path"):
                    video_meta = built
                elif not video_meta.get("path"):
                    video_meta = built

            artifacts = {
                "report": "report.html",
                "junit": "junit.xml",
                "session": "session.json",
                "checks": "checks.json",
                "logcat": "logcat.txt",
                "metrics": "metrics.json",
            }
            if video_meta.get("path"):
                artifacts["video"] = os.path.basename(str(video_meta["path"]))
            if video_meta.get("gif"):
                artifacts["gif"] = os.path.basename(str(video_meta["gif"]))
            if not session.resumable:
                session.clear_checkpoint()

            with self.lock:
                self._paused_session = session if session.resumable else None
                self.qa_review = review
                self.findings = findings
                self.checks = [check.to_dict() for check in check_results]
                self.summary = dict(payload["summary"])
                self.video_meta = video_meta
                self.artifacts = artifacts
                self.status = "done"
                self._session = None
                self.progress["action"] = "finished"
                self.progress["phase"] = "done"
                self.progress["elapsed"] = result.summary["duration_s"]
        except Exception as exc:  # anything here must surface in the UI
            traceback.print_exc()
            self.log("error", f"run failed: {type(exc).__name__}: {exc}")
            if "INSTALL_FAILED_VERSION_DOWNGRADE" in str(exc):
                self.log("warn", "the phone has a NEWER version of this game installed. Either upload the newer "
                         "APK, untick 'reinstall APK' to test the installed one, or uninstall it from the phone "
                         "(this deletes the game's saved data).")
            elif "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in str(exc):
                self.log("warn", "the installed app is signed with a different key - uninstall it from the phone "
                         "first (this deletes its saved data), or untick 'reinstall APK'.")
            with self.lock:
                self._session = None
                self._paused_session = session if session is not None and session.resumable else None
                self.status = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                self.progress["action"] = "error"
        finally:
            if recorder is not None:
                try:
                    recorder.stop()
                except Exception:  # pragma: no cover - defensive
                    pass
                with self.lock:
                    self._recorder = None

    # -- files -------------------------------------------------------------
    def artifact_path(self, name: str) -> str:
        allowed = {"report.html", "junit.xml", "session.json", "checks.json", "logcat.txt",
                   "metrics.json", "session.gif", "session.mp4", "qa_review.json", "qa_review.md"}
        if name not in allowed and not re.fullmatch(r"session-part-\d+\.mp4", name):
            raise StudioError(f"unknown artifact {name!r}")
        with self.lock:
            if not self.session_dir:
                raise StudioError("no finished session yet")
            path = os.path.join(self.session_dir, name)
        if not os.path.exists(path):
            raise StudioError(f"{name} was not produced by this session")
        return path

    def frame_path(self, index: str) -> str:
        with self.lock:
            if not self.live_frames:
                raise StudioError("no frames yet")
            if index in ("latest", "", "last"):
                frame = self.live_frames[-1]
            else:
                try:
                    wanted = int(index)
                except ValueError as exc:
                    raise StudioError("frame index must be an integer or 'latest'") from exc
                frame = next((item for item in self.live_frames if item.index == wanted), None)
                if frame is None:
                    frame = self.live_frames[-1]
        if not os.path.exists(frame.path):
            raise StudioError("frame file is gone")
        return frame.path


# -- HTTP plumbing ---------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = f"apkharness-studio/{__version__}"
    studio: Studio = None  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("APKHARNESS_DEBUG"):
            super().log_message(fmt, *args)

    # -- helpers -----------------------------------------------------------
    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status=status)

    def _file(self, path: str, download: bool = False) -> None:
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def _body(self, limit: int = 8 * 1024 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise StudioError("request body too large")
        return self.rfile.read(length) if length else b""

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in ("/studio", "/studio.html"):
                from .webui import UI_HTML

                body = UI_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path in ("/", "/index.html", "/dashboard", "/dashboard.html"):
                from .dashboard import DASHBOARD_HTML

                body = DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/games":
                from .dashboard import list_games

                self._json(list_games(self.studio.runs_dir))
                return
            if parsed.path == "/api/runs":
                self._json(self.studio.run_history())
                return
            if parsed.path == "/api/runs/artifact":
                from .dashboard import run_artifact_path

                try:
                    path = run_artifact_path(self.studio.runs_dir, (query.get("run") or [""])[0],
                                             (query.get("name") or [""])[0])
                except ValueError as exc:
                    self._error(str(exc), 404)
                    return
                self._file(path)
                return
            if parsed.path == "/api/events":
                since = int((query.get("since") or ["0"])[0] or 0)
                self._json(self.studio.events_since(since))
                return
            if parsed.path == "/api/live-log":
                tail = max(10, min(3000, int((query.get("tail") or ["300"])[0] or 300)))
                only = (query.get("game") or ["0"])[0] == "1"
                self._json(self.studio.live_log(tail, only_game=only))
                return
            if parsed.path == "/api/autoqa":
                with self.studio.lock:
                    status, mode = self.studio.status, self.studio.mode
                    progress = dict(self.studio.progress)
                    step_actions = {row["step"]: row["action"] for row in self.studio.step_log} if mode == "explore" else {}
                    step_interruptions = dict(self.studio.step_interruptions) if mode == "explore" else {}
                    session = self.studio._paused_session
                    paused = {"run": os.path.basename(session.out_dir), "serial": session.config.serial, "step": session.memory.step,
                              "reason": session.end_reason, "next_section": session.at_section_boundary,
                              "restored": session.restored_from_disk, "stuck": session.stuck or None} if session and status != "running" else None
                    guide = first_customer_guide((self.studio.apk or {}).get("package", ""))
                self._json({"autoqa": dict(self.studio.autoqa), "product": self.studio.product,
                            "presets": AUTOQA_PRESETS, "guide": guide or None,
                            "apk": self.studio.apk, "status": status, "error": self.studio.error,
                            "progress": progress, "step_actions": step_actions, "step_interruptions": step_interruptions,
                            "paused": paused,
                            "suite": self.studio.suite.summary() if self.studio.suite else None,
                            "doc": (self.studio.suite.doc_name if self.studio.suite else ""),
                            "device": {"selected": self.studio.serial,
                                       "model": self.studio._device_model(self.studio.serial)},
                            "review": self.studio.qa_review,
                            "mode": mode,
                            "cases": self.studio.cases_payload(),
                            "case_run": dict(self.studio.case_run),
                            "case_result": self.studio.case_result,
                            "question": self.studio.desk.current.public() if self.studio.desk.current else None,
                            "ai": self.studio.ai_public()})
                return
            if parsed.path == "/api/ai":
                self._json(self.studio.ai_public())
                return
            if parsed.path == "/api/cases":
                self._json(self.studio.cases_payload() or {})
                return
            if parsed.path == "/api/phone/current":
                self._json(self.studio.phone_current())
                return
            if parsed.path == "/api/phone/apps":
                self._json(self.studio.phone_apps())
                return
            if parsed.path == "/api/runs/compare":
                from .dashboard import compare_runs, find_baseline

                new_id = (query.get("new") or [""])[0]
                base_id = (query.get("base") or [""])[0] or find_baseline(self.studio.runs_dir, new_id)
                try:
                    if not base_id:
                        raise ValueError("No earlier completed run matches this test's coverage.")
                    self._json(compare_runs(self.studio.runs_dir, new_id, base_id))
                except ValueError as exc:
                    self._error(str(exc), 404)
                return
            if parsed.path in ("/api/runs/review", "/api/runs/log"):
                from .dashboard import run_log, run_review

                run_id = (query.get("run") or [""])[0]
                try:
                    if parsed.path.endswith("review"):
                        self._json(run_review(self.studio.runs_dir, run_id, self.studio.suite))
                    else:
                        tail = max(10, min(5000, int((query.get("tail") or ["800"])[0] or 800)))
                        self._json(run_log(self.studio.runs_dir, run_id, tail))
                except ValueError as exc:
                    self._error(str(exc), 404)
                return
            if parsed.path == "/api/schema":
                from .plan import CHECK_TYPES, FINDING_KINDS, METRICS, SEVERITIES

                self._json({"check_types": CHECK_TYPES, "kinds": list(FINDING_KINDS),
                            "metrics": METRICS, "severities": list(SEVERITIES)})
                return
            if parsed.path == "/api/state":
                self._json(self.studio.snapshot())
                return
            if parsed.path == "/api/device":
                refresh = (query.get("refresh") or ["0"])[0] == "1"
                self._json(self.studio.device_list(refresh=refresh))
                return
            if parsed.path == "/api/frame":
                index = (query.get("i") or ["latest"])[0]
                self._file(self.studio.frame_path(index))
                return
            if parsed.path == "/api/artifact":
                name = unquote((query.get("name") or [""])[0])
                download = (query.get("download") or ["0"])[0] == "1"
                self._file(self.studio.artifact_path(name), download=download)
                return
            if parsed.path == "/api/health":
                self._json({"ok": True, "version": __version__})
                return
            self._error("not found", 404)
        except StudioError as exc:
            self._error(str(exc), 404 if "not found" in str(exc) else 400)
        except BrokenPipeError:  # pragma: no cover - browser navigated away
            pass
        except Exception as exc:  # pragma: no cover - defensive
            traceback.print_exc()
            self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/runs/delete":
                host = self.headers.get("Host", "").lower()
                if not re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", host) or self.headers.get(
                    "Origin", f"http://{host}"
                ) != f"http://{host}":
                    self._error("Delete saved tests from the local Game Tester page.", 403)
                    return
                if self.headers.get_content_type() != "application/json":
                    self._error("Expected a JSON request.", 415)
                    return
                payload = json.loads(self._body().decode("utf-8") or "null")
                self._json(self.studio.delete_saved_runs(payload.get("runs") if isinstance(payload, dict) else None))
                return
            if parsed.path == "/api/upload":
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    raise StudioError("empty upload")
                if length > MAX_UPLOAD_BYTES:
                    raise StudioError("APK is larger than the 800 MB limit")
                name = self.headers.get("X-Filename") or "upload.apk"
                info = self.studio.receive_apk(name, self.rfile, length)
                self._json({"apk": info})
                return
            if parsed.path == "/api/requirements":
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    raise StudioError("empty document")
                if length > 8 * 1024 * 1024:
                    raise StudioError("document is larger than 8 MB")
                name = self.headers.get("X-Filename") or "requirements.md"
                self._json(self.studio.receive_document(name, self.rfile.read(length)))
                return
            if parsed.path == "/api/testcases/update":
                payload = json.loads(self._body().decode("utf-8") or "{}")
                self._json(self.studio.update_case(payload))
                return
            if parsed.path == "/api/requirements/approve":
                payload = json.loads(self._body().decode("utf-8") or "{}")
                self._json(self.studio.approve_suite(bool(payload.get("approved", True))))
                return
            if parsed.path == "/api/requirements/regenerate":
                self._json(self.studio.regenerate_cases())
                return
            if parsed.path == "/api/plan":
                payload = json.loads(self._body().decode("utf-8") or "{}")
                self._json({"plan": self.studio.set_plan(payload), "plan_errors": []})
                return
            if parsed.path == "/api/plan/default":
                self._json({"plan": self.studio.reset_plan()})
                return
            if parsed.path == "/api/target":
                payload = json.loads(self._body().decode("utf-8") or "{}")
                self._json({"plan": self.studio.set_target(str(payload.get("target", "")))})
                return
            if parsed.path == "/api/restart":
                self._json(self.studio.restart())
                return
            if parsed.path == "/api/device/select":
                payload = json.loads(self._body().decode("utf-8") or "{}")
                self._json(self.studio.select_device(str(payload.get("serial", ""))))
                return
            if parsed.path == "/api/run":
                self._json(self.studio.start(), status=202)
                return
            if parsed.path == "/api/run/resume":
                payload = json.loads(self._body().decode("utf-8") or "null")
                if (not isinstance(payload, dict) or not isinstance(payload.get("run"), str) or not payload["run"]
                        or type(payload.get("step")) is not int or payload["step"] < 0):
                    raise StudioError("Select the paused run and step to continue.")
                self._json(self.studio.resume(expected_run=payload["run"], after_step=payload["step"]), status=202)
                return
            if parsed.path == "/api/autoqa":
                raw = self._body() or b"{}"
                self._json(self.studio.set_autoqa(json.loads(raw.decode("utf-8") or "{}")))
                return
            if parsed.path == "/api/ai":
                raw = self._body() or b"{}"
                self._json(self.studio.set_ai(json.loads(raw.decode("utf-8") or "{}")))
                return
            if parsed.path == "/api/ai/test":
                self._json(self.studio.test_ai())
                return
            if parsed.path == "/api/cases/inputs":
                raw = self._body() or b"{}"
                self._json(self.studio.set_case_inputs(json.loads(raw.decode("utf-8") or "{}")))
                return
            if parsed.path == "/api/cases/clear":
                self._json(self.studio.clear_cases())
                return
            if parsed.path == "/api/cases/run":
                raw = self._body() or b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
                self._json(self.studio.start_cases(str(body.get("where", "")), body.get("only"),
                                                   guided=body.get("guided") is True))
                return
            if parsed.path == "/api/question/answer":
                raw = self._body() or b"{}"
                self._json(self.studio.answer_question(json.loads(raw.decode("utf-8") or "{}")))
                return
            if parsed.path == "/api/apk/clear":
                self._json(self.studio.clear_apk())
                return
            if parsed.path == "/api/phone/choose":
                raw = self._body() or b"{}"
                self._json(self.studio.choose_installed(str(json.loads(raw.decode("utf-8") or "{}").get("package", ""))))
                return
            if parsed.path == "/api/autoqa/run":
                raw = self._body() or b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
                where = str(body.get("where", ""))
                serial = self.studio._pick_serial() if (self.studio.adb_path and where != "practice") else ""
                self._json(self.studio.auto_start(serial, reason="Start testing pressed", where=where,
                                                  preset=body.get("preset"), objective=body.get("objective", "")))
                return
            if parsed.path == "/api/start-over":
                self._json(self.studio.start_over())
                return
            if parsed.path == "/api/requirements/clear":
                self._json(self.studio.clear_requirements())
                return
            if parsed.path == "/api/stop":
                self._json(self.studio.stop())
                return
            self._error("not found", 404)
        except StudioError as exc:
            self._error(str(exc), 400)
        except json.JSONDecodeError as exc:
            self._error(f"invalid JSON: {exc}", 400)
        except Exception as exc:  # pragma: no cover - defensive
            traceback.print_exc()
            self._error(f"{type(exc).__name__}: {exc}", 500)


class _ExclusiveServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets a second copy bind the same port and steal requests;
    refuse instead so there is only ever one tester per port."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        import socket

        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(studio: Studio, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"studio": studio})
    httpd = _ExclusiveServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def serve(workdir: str = "studio", host: str = "127.0.0.1", port: int = 8765,
          adb_path: str = "", open_browser: bool = False) -> int:
    """Blocking entry point used by ``apkharness serve``."""
    try:
        probe = _ExclusiveServer((host, port), BaseHTTPRequestHandler)
        probe.server_close()
    except OSError:
        url = f"http://{host}:{port}/"
        print(f"The Game Tester is ALREADY RUNNING at {url} - open that address in your browser.", flush=True)
        if open_browser:
            import webbrowser

            webbrowser.open(url)
        return 0
    studio = Studio(workdir=workdir, adb_path=adb_path, port=port)
    httpd = make_server(studio, host=host, port=port)
    studio.start_watcher()
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"apkharness studio {__version__}", flush=True)
    print(f"  url      : {url}", flush=True)
    print(f"  workdir  : {studio.workdir}", flush=True)
    print(f"  adb      : {studio.adb_path or 'not found (simulator still works)'}", flush=True)
    ffmpeg_ok, backend = video.available()
    print(f"  video    : {backend if ffmpeg_ok else 'no frames backend (install ffmpeg or Pillow)'}", flush=True)
    print(f"  open     : {url}   (simple tester - start here)", flush=True)
    print(f"  advanced : {url}studio", flush=True)
    print("  stop     : Ctrl+C", flush=True)
    if open_browser:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0
