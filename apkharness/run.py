"""Session orchestration: install, drive, watch, collect, report."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import __version__, logs as logmod, metrics as metricmod
from .actions import Action
from .adb import Adb, AdbError
from .apk import ApkError, file_sha256, inspect_apk
from .device import (
    AdbDevice,
    Device,
    DeviceUnavailable,
    InputBlocked,
    Observation,
    apply_action,
    observe,
    phone_gone,
)
from .policies import (
    BasePolicy,
    HeuristicPolicy,
    LLMPolicy,
    Memory,
    ObservePolicy,
    ScriptedPolicy,
    SessionContext,
    load_script,
)
from .policies.llm import DEFAULT_BASE_URL as DEFAULT_LLM_BASE_URL, DEFAULT_MODEL as DEFAULT_LLM_MODEL
from .simulator import DEFAULT_PACKAGE, CrashPlan, SimDevice

log = logging.getLogger("apkharness")

DEFAULT_STEPS = 200
PHONE_RECONNECT_GRACE_S = 20
CHECKPOINT_FILE = ".resume.json"
CHECKPOINT_LOG = ".resume.log"
PAUSE_REASONS = ("stopped", "phone_lost", "section_complete", "section_time_limit", "stuck", "recovered")


@dataclass
class RunConfig:
    """Everything the CLI can tweak about one run."""

    apk: str = ""
    package: str = ""
    activity: str = ""
    serial: str = ""
    adb_path: str = "adb"
    policy: str = "heuristic"
    steps: int = DEFAULT_STEPS
    time_budget_s: float = 1800.0
    section_size: int = 0
    step_delay_s: float = 0.4
    metrics_every: int = 5
    screenshot_every: int = 1
    ui_every: int = 2
    out_root: str = "runs"
    seed: int = 7
    novelty_threshold: int = 10
    relaunch_on_crash: bool = True
    max_relaunches: int = 3
    stop_after_crashes: int = 0
    simulate: bool = False
    sim_crash_at: int = 0
    no_install: bool = False
    llm_model: str = ""
    llm_base_url: str = ""
    llm_vision: bool = False
    actions_file: str = ""
    label: str = ""
    ignore_patterns: List[str] = field(default_factory=list)
    plan: Dict[str, Any] = field(default_factory=dict)
    interruptions: List[str] = field(default_factory=list)
    interrupt_every: int = 0
    startup_runs: int = 0
    stuck_after: int = 0
    ai_config: Dict[str, Any] = field(default_factory=dict)  # provider/model/url/key for the "agent" policy
    gameplay_objective: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = {k: v for k, v in asdict(self).items() if v not in (None, "", 0, False)}
        if isinstance(payload.get("ai_config"), dict):  # never store a secret in session.json / reports
            payload["ai_config"] = {k: v for k, v in payload["ai_config"].items() if k != "api_key"}
        if not payload.get("ignore_patterns"):
            payload.pop("ignore_patterns", None)
        return payload


@dataclass
class StepRecord:
    step: int
    elapsed_s: float
    action: str
    alive: bool
    screen: str = ""
    new_screen: bool = False
    visits: int = 0
    fps: Optional[float] = None
    pss_kb: Optional[int] = None
    crashes: List[str] = field(default_factory=list)
    screenshot: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", None, False, [])}


@dataclass
class SessionResult:
    config: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    crashes: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    screenshots: Dict[str, str] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    interruptions: List[Dict[str, Any]] = field(default_factory=list)
    startup: Dict[str, Any] = field(default_factory=dict)
    perf: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _ignored(crash: logmod.Crash, patterns: List[str]) -> bool:
    """True when a finding matches one of the plan's ignore regexes."""
    haystack = f"{crash.signature} {crash.message}"
    for pattern in patterns:
        try:
            if re.search(pattern, haystack):
                return True
        except re.error:
            continue
    return False


class Session:
    """One test run against one device."""

    def __init__(
        self,
        config: RunConfig,
        device: Optional[Device] = None,
        policy: Optional[BasePolicy] = None,
        on_frame: Optional[Callable[[int, bytes, str, bool], None]] = None,
        on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_phase: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        allow_resume: bool = False,
        checkpoint_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.config = config
        self.should_stop = should_stop or (lambda: False)
        self.allow_resume = allow_resume
        self.stopped_by_user = False
        self.device_lost = False
        self.end_reason = "completed"
        self.on_frame = on_frame
        self.on_step = on_step
        self.on_phase = on_phase
        self.device = device or self._make_device()
        self.policy = policy or self._make_policy()
        self.detector = logmod.CrashDetector(config.package or DEFAULT_PACKAGE)
        self.memory = Memory()
        self.result = SessionResult()
        self.out_dir = ""
        self._shot_dir = ""
        self._shot_names: Dict[str, str] = {}
        self._shot_counter = 0
        self._log_lines: List[str] = []
        self._metrics: List[metricmod.MetricsSample] = []
        self._prev_frames: Optional[int] = None
        self._prev_frames_at: Optional[float] = None
        self._device_failures = 0
        self._meta: Dict[str, Any] = {}
        self._activity = ""
        self._steps: List[StepRecord] = []
        self._crashes: List[logmod.Crash] = []
        self._active_time = 0.0
        self._section_started_at = 0.0
        self._section_end = 0
        self.checkpoint_context = checkpoint_context
        self._checkpoint_log_count = 0
        self._checkpoint_log_size = 0
        self.stuck: Dict[str, Any] = {}
        self.restored_from_disk = False

    @property
    def resumable(self) -> bool:
        return (self.allow_resume and bool(self._meta) and self.end_reason in PAUSE_REASONS
                and (self.memory.step < self.config.steps or self.end_reason == "recovered"))

    @property
    def at_section_boundary(self) -> bool:
        return 0 < self.memory.step == self._section_end < self.config.steps

    def _save_checkpoint(self, elapsed: float, pending_input: bool = False) -> None:
        if self.checkpoint_context is None:
            return
        log_tail = self._log_lines[self._checkpoint_log_count:]
        if log_tail:
            with open(os.path.join(self.out_dir, CHECKPOINT_LOG), "ab") as handle:
                handle.write(("\n".join(log_tail) + "\n").encode("utf-8"))
                self._checkpoint_log_size = handle.tell()
            self._checkpoint_log_count = len(self._log_lines)
        config = asdict(self.config)
        config["ai_config"].pop("api_key", None)
        memory = self.memory
        heuristic = getattr(self.policy, "fallback", self.policy)
        data = {"version": 1, "config": config, "studio": self.checkpoint_context,
                "meta": self._meta, "activity": self._activity, "elapsed": elapsed,
                "section_started_at": self._section_started_at, "section_end": self._section_end,
                "reason": self.end_reason, "pending_input": pending_input, "log_size": self._checkpoint_log_size,
                "stuck": self.stuck, "memory": {"step": memory.step, "hashes": memory.hashes,
                    "visits": memory.visits, "screens": memory.screens, "relaunches": memory.relaunches,
                    "recent": [action.to_dict() for action in memory.recent]},
                "steps": [asdict(step) for step in self._steps], "timeline": self.result.timeline,
                "crashes": [crash.to_dict() for crash in self._crashes],
                "metrics": [sample.to_dict() for sample in self._metrics], "screenshots": self._shot_names,
                "interruptions": self.result.interruptions, "startup": self.result.startup}
        if isinstance(heuristic, HeuristicPolicy):
            data["random"] = heuristic.random.getstate()
        if isinstance(self.policy, ScriptedPolicy):
            data["script_index"] = self.policy.index
        snapshot_policy = getattr(self.policy, "checkpoint_state", None)
        if callable(snapshot_policy):
            data["policy_memory"] = snapshot_policy()
        if isinstance(self.device, SimDevice):
            data["simulator"] = self.device.checkpoint_state()
        path = os.path.join(self.out_dir, CHECKPOINT_FILE)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
        os.replace(path + ".tmp", path)

    def restore_checkpoint(self, out_dir: str, data: Dict[str, Any]) -> None:
        self.restored_from_disk = True
        self.out_dir = out_dir
        self._shot_dir = os.path.join(out_dir, "screenshots")
        self._meta, self._activity = data["meta"], data["activity"]
        self._active_time = data["elapsed"]
        self._section_started_at, self._section_end = data["section_started_at"], data["section_end"]
        self.end_reason = data["reason"] if data["reason"] in PAUSE_REASONS else "recovered"
        self.stopped_by_user = self.end_reason == "stopped"
        self.device_lost = self.end_reason == "phone_lost"
        self.stuck = data.get("stuck") or {}
        self._steps = [StepRecord(**row) for row in data["steps"]]
        self._crashes = [logmod.Crash(**row) for row in data["crashes"]]
        self._metrics = [metricmod.MetricsSample(**sample) for sample in data["metrics"]]
        self._shot_names = data["screenshots"]
        self.result.timeline, self.result.interruptions, self.result.startup = data["timeline"], data["interruptions"], data["startup"]
        saved = data["memory"]
        self.memory = Memory(step=saved["step"], hashes=saved["hashes"], screens=saved["screens"],
                             visits={int(key): value for key, value in saved["visits"].items()},
                             relaunches=saved["relaunches"], crashes=self._crashes)
        self.memory.recent.extend(Action.from_dict(action) for action in saved["recent"])
        if self.memory.recent:
            self.memory.last_action = self.memory.recent[-1]
        if data["pending_input"] and self._steps:
            # The phone may have received this action before shutdown. Keep the evidence and avoid sending it twice.
            detail = " [delivery unconfirmed]"
            self._steps[-1].action += detail
            self.result.timeline[-1]["action"] += detail
            self.result.timeline[-1]["input_unconfirmed"] = True
        self.detector.package = self.config.package
        log_path = os.path.join(out_dir, CHECKPOINT_LOG)
        if data["log_size"] or os.path.isfile(log_path):
            if os.path.normcase(os.path.realpath(log_path)) != os.path.normcase(log_path):
                raise ValueError("checkpoint log must be inside the saved run")
            with open(log_path, "r+b") as handle:
                raw = handle.read(data["log_size"])
                handle.truncate(len(raw))
            self._log_lines = raw.decode("utf-8", errors="replace").splitlines()
            self._checkpoint_log_size, self._checkpoint_log_count = len(raw), len(self._log_lines)
        if isinstance(self.device, SimDevice):
            self.device.restore_checkpoint(data["simulator"])
        elif isinstance(self.device, AdbDevice):
            self.device.remember_logged_lines(logmod.parse_lines("\n".join(self._log_lines[-6000:])))
        self.policy.begin(SessionContext(package=self.config.package, seed=self.config.seed, max_steps=self.config.steps,
                                         gameplay_objective=self.config.gameplay_objective))
        heuristic = getattr(self.policy, "fallback", self.policy)
        if isinstance(heuristic, HeuristicPolicy) and "random" in data:
            version, state, extra = data["random"]
            heuristic.random.setstate((version, tuple(state), extra))
        if isinstance(self.policy, ScriptedPolicy):
            self.policy.index = data["script_index"]
        restore_policy = getattr(self.policy, "restore_checkpoint", None)
        if callable(restore_policy) and "policy_memory" in data:
            restore_policy(data["policy_memory"])

    def clear_checkpoint(self) -> None:
        if not self.out_dir:
            return
        for name in (CHECKPOINT_FILE, CHECKPOINT_FILE + ".tmp", CHECKPOINT_LOG):
            try:
                os.unlink(os.path.join(self.out_dir, name))
            except FileNotFoundError:
                pass

    def write_recovered_report(self) -> SessionResult:
        return self._finish(self._meta, self._crashes, self._steps, self._active_time, True, self.memory.step)

    # -- setup -------------------------------------------------------------
    def _make_device(self) -> Device:
        cfg = self.config
        if cfg.simulate:
            plan = None
            if cfg.sim_crash_at:
                plan = [CrashPlan(cfg.sim_crash_at, "java_crash", "garage")]
            return SimDevice(package=cfg.package or DEFAULT_PACKAGE, seed=cfg.seed, plan=plan)
        serial = cfg.serial
        if not serial:
            devices = Adb.list_devices(cfg.adb_path)
            online = [d for d in devices if d.online]
            if not online:
                raise DeviceUnavailable(
                    "no online Android device/emulator found. Start an emulator, plug in a "
                    "phone with USB debugging enabled, or use `apkharness demo` to run the "
                    "built-in simulator."
                )
            serial = online[0].serial
            if len(online) > 1:
                log.info("multiple devices online, using %s (pass --serial to choose)", serial)
        return AdbDevice(serial=serial, adb_path=cfg.adb_path)

    def _make_policy(self) -> BasePolicy:
        cfg = self.config
        if cfg.policy == "agent":
            from .policies.agent import AgentPolicy, AIConfig

            known = {k: v for k, v in (cfg.ai_config or {}).items() if k in AIConfig.__dataclass_fields__}
            return AgentPolicy(AIConfig(**known), seed=cfg.seed,
                               fallback=HeuristicPolicy(seed=cfg.seed, novelty_threshold=cfg.novelty_threshold))
        if cfg.policy == "llm":
            return LLMPolicy(
                model=cfg.llm_model or DEFAULT_LLM_MODEL,
                base_url=cfg.llm_base_url or DEFAULT_LLM_BASE_URL,
                vision=cfg.llm_vision,
                seed=cfg.seed,
                fallback=HeuristicPolicy(seed=cfg.seed, novelty_threshold=cfg.novelty_threshold),
            )
        if cfg.policy == "observe":
            return ObservePolicy()
        if cfg.policy == "scripted":
            if not cfg.actions_file:
                raise ValueError("--policy scripted needs --actions <file.json>")
            actions, loop = load_script(cfg.actions_file)
            return ScriptedPolicy(actions=actions, loop=loop)
        return HeuristicPolicy(seed=cfg.seed, novelty_threshold=cfg.novelty_threshold)

    @property
    def screenshots_dir(self) -> str:
        """Directory holding the PNG frames of the current session."""
        return self._shot_dir

    def _prepare(self) -> str:
        cfg = self.config
        stamp = time.strftime("%Y%m%d_%H%M%S")
        slug = (cfg.package or cfg.label or (os.path.basename(cfg.apk) if cfg.apk else "session")).replace(os.sep, "_")
        self.out_dir = os.path.abspath(os.path.join(cfg.out_root, f"{stamp}_{slug}"))
        os.makedirs(cfg.out_root, exist_ok=True)
        try:
            os.mkdir(self.out_dir)
        except FileExistsError:
            self.out_dir += f"_{time.time_ns()}"
            os.mkdir(self.out_dir)
        self._shot_dir = os.path.join(self.out_dir, "screenshots")
        os.makedirs(self._shot_dir, exist_ok=True)
        return self.out_dir

    def _save_screenshot(self, png: Optional[bytes], step: int, tag: str = "") -> str:
        if not png:
            return ""
        self._shot_counter += 1
        name = f"step_{step:05d}{('_' + tag) if tag else ''}.png"
        path = os.path.join(self._shot_dir, name)
        try:
            with open(path, "wb") as handle:
                handle.write(png)
        except OSError:
            return ""
        rel = os.path.join("screenshots", name).replace(os.sep, "/")
        self._shot_names[name] = rel
        return rel

    # -- session -----------------------------------------------------------
    def _setup(self) -> None:
        cfg = self.config
        self._prepare()
        meta = {"tool": f"apkharness {__version__}", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        meta.update(self.device.describe())
        meta["policy"] = self.policy.name
        if cfg.plan:
            meta["plan"] = cfg.plan

        apk_info = None
        if cfg.apk and not cfg.simulate:
            try:
                apk_info = inspect_apk(cfg.apk)
                log.info(
                    "APK manifest: %s %s, launcher %s",
                    apk_info.package,
                    apk_info.version_name or "?",
                    apk_info.launch_activity or "(none declared)",
                )
            except ApkError as exc:
                log.warning("could not read the APK manifest offline (%s); will detect the package after install", exc)

        if cfg.package:
            package = cfg.package
        elif cfg.simulate:
            package = DEFAULT_PACKAGE
        elif apk_info is not None and apk_info.package:
            package = apk_info.package
        elif cfg.apk and not cfg.no_install:
            package = self._resolve_package()
        else:
            raise ValueError("--package is required when --no-install is used")
        cfg.package = package
        self.detector.package = package
        meta["package"] = package

        if cfg.simulate:
            self.device.install(cfg.apk or "simulated-game.apk")
        elif cfg.apk and not cfg.no_install:
            self._phase("installing")
            log.info("installing %s", os.path.basename(cfg.apk))
            try:
                self.device.install(cfg.apk)
            except AdbError as exc:
                text = str(exc)
                adb = getattr(self.device, "adb", None)
                installed = adb.installed_version(package) if adb is not None else {}
                reason = ("newer" if "VERSION_DOWNGRADE" in text else
                          "signed with a different key" if "UPDATE_INCOMPATIBLE" in text else "")
                if not (reason and installed):
                    raise
                # Never wipe the user's game: test the copy that is already on the phone instead.
                note = (f"phone already has version {installed.get('version_name') or '?'} "
                        f"({installed.get('version_code')}) which is {reason} than the uploaded file - "
                        f"tested the version on the phone instead")
                log.warning(note)
                meta["install_note"] = note
                meta["tested_installed"] = installed
                apk_info = None  # results belong to the installed build, not the uploaded file
                self._phase("using-installed")
        elif cfg.no_install:
            log.info("skipping install (--no-install)")

        if meta.get("tested_installed"):
            meta["apk"] = dict(meta["tested_installed"], source="already installed on the phone")
        elif apk_info is not None:
            meta["apk"] = apk_info.to_dict()
        elif cfg.apk and os.path.exists(cfg.apk):
            meta["apk"] = {
                "path": os.path.abspath(cfg.apk),
                "size_bytes": os.path.getsize(cfg.apk),
                "sha256": file_sha256(cfg.apk),
            }
        elif not cfg.simulate and getattr(self.device, "adb", None) is not None:
            # a game picked straight from the phone: remember which version was tested
            try:
                installed = self.device.adb.installed_version(package)
            except Exception:
                installed = {}
            if installed:
                meta["apk"] = dict(installed, source="already installed on the phone")

        activity = cfg.activity or (apk_info.launch_activity if apk_info else "")
        if not activity and not cfg.simulate:
            activity = self._resolve_activity()
        self._phase("launching")
        log.info("launching %s %s", package, activity or "(launcher intent)")
        try:
            self.device.launch(package, activity)
        except (AdbError, RuntimeError) as exc:
            log.warning("launch failed: %s", exc)
        time.sleep(min(1.0, max(0.0, cfg.step_delay_s)))

        if self.policy.name != "observe":
            ok, detail = self.device.check_input()
            if not ok:
                raise InputBlocked(detail)
        else:
            log.info("watch-only mode: no input will be sent to the device")

        if cfg.startup_runs and self.policy.name != "observe" and not self.should_stop():
            self._phase("startup")
            log.info("measuring cold/warm start (%d runs)", cfg.startup_runs)
            try:
                self.result.startup = self.device.startup_probe(package, activity, cfg.startup_runs) or {}
            except Exception as exc:  # timing is a bonus; never block the session
                self.result.startup = {"error": str(exc)}
            if not self.device.alive(package):
                try:
                    self.device.launch(package, activity)
                except (AdbError, RuntimeError):
                    pass

        width, height = self.device.screen_size()
        context = SessionContext(
            package=package, width=width, height=height, seed=cfg.seed, max_steps=cfg.steps,
            gameplay_objective=cfg.gameplay_objective,
        )
        self.policy.begin(context)
        self._meta, self._activity = meta, activity

    def run(self) -> SessionResult:
        cfg = self.config
        started = time.monotonic() - self._active_time
        if not self.resumable:
            self._setup()
        else:
            self._prev_frames = self._prev_frames_at = None
            if self.at_section_boundary or self.end_reason == "section_time_limit":
                self._section_started_at = self._active_time
        self.end_reason = "completed"
        self.stopped_by_user = self.device_lost = False
        self._device_failures = 0
        self.stuck = {}
        self.restored_from_disk = False
        self._phase("running")

        package, activity = cfg.package, self._activity
        crashes, steps = self._crashes, self._steps
        relaunches = self.memory.relaunches
        interrupted = False
        step = self.memory.step
        section_size = cfg.section_size if self.allow_resume else 0
        self._section_end = min(cfg.steps, (step // section_size + 1) * section_size) if section_size else cfg.steps
        disconnected_at = None
        last_screen, attempts = None, 0
        check_stuck = self.allow_resume and cfg.stuck_after > 0 and self.policy.name in ("heuristic", "agent", "llm")

        try:
            self._save_checkpoint(time.monotonic() - started)
            while step < self._section_end:
                if self.should_stop():
                    self.stopped_by_user = True
                    if self._device_failures:
                        self.device_lost = True  # stopped while the phone was gone: say both
                    log.info("stopped by the tester at step %d", step)
                    self.end_reason = "stopped"
                    break
                if disconnected_at is None and time.monotonic() - started - self._section_started_at > cfg.time_budget_s:
                    log.warning("time budget of %.0fs exhausted at step %d", cfg.time_budget_s, step)
                    self.end_reason = "section_time_limit" if section_size else "time_limit"
                    break
                step += 1
                tick = getattr(self.device, "tick", None)
                if callable(tick):
                    tick()

                want_shot = (step - 1) % max(1, cfg.screenshot_every) == 0
                want_ui = (step - 1) % max(1, cfg.ui_every) == 0
                want_metrics = (step - 1) % max(1, cfg.metrics_every) == 0
                try:
                    obs = observe(
                        self.device,
                        step,
                        time.monotonic() - started,
                        package,
                        want_screenshot=want_shot,
                        want_ui=want_ui,
                        want_metrics=want_metrics,
                    )
                except DeviceUnavailable:
                    self._device_failures += 1
                    if self._device_failures == 1:
                        disconnected_at = time.monotonic()
                        log.warning("step %d: the phone stopped answering (cable or USB debugging) - waiting for it", step)
                        self._phase("phone-lost")
                    step -= 1
                    if self.should_stop() or time.monotonic() - disconnected_at >= PHONE_RECONNECT_GRACE_S:
                        self.device_lost = True
                        self.stopped_by_user = self.should_stop()
                        log.warning("the phone is offline - saving the results so far")
                        self.end_reason = "phone_lost"
                        break
                    self._sleep_plain(0.5)
                    continue
                if self._device_failures:
                    started += time.monotonic() - disconnected_at
                    obs.elapsed_s = time.monotonic() - started
                    disconnected_at = None
                    self._device_failures = 0
                    self._prev_frames = self._prev_frames_at = None
                    log.info("the phone is back - continuing")
                    self._phase("running")

                new_lines = self.device.poll_logs()
                for line in new_lines:
                    self._log_lines.append(line.raw or f"{line.ts} {line.level} {line.tag}: {line.msg}")
                detected = self.detector.feed(new_lines, step)
                if detected and cfg.ignore_patterns:
                    detected = [
                        crash
                        for crash in detected
                        if not _ignored(crash, cfg.ignore_patterns)
                    ]
                if detected:
                    logmod.merge_crashes(crashes, detected)
                    for crash in detected:
                        log.warning("step %d: %s - %s", step, crash.label, crash.message[:120])

                if not obs.alive and not detected:
                    crash = logmod.Crash(
                        kind="process_death",
                        signature="process vanished",
                        message="process was gone without a matching crash log",
                        ts=time.strftime("%m-%d %H:%M:%S"),
                        step=step,
                    )
                    logmod.merge_crashes(crashes, [crash])
                    log.warning("step %d: process vanished", step)

                key = obs.screen_key = self.memory.screen_key(obs.phash)
                if check_stuck:
                    if key is None or key != last_screen or not obs.alive or detected:
                        attempts = 0
                    elif self.memory.last_action and self.memory.last_action.type in ("tap", "swipe", "long_press", "back"):
                        attempts += 1
                    last_screen = key
                    if attempts >= cfg.stuck_after:
                        step = self.memory.step
                        self.stuck = {"attempts": attempts, "actions": [action.label for action in list(self.memory.recent)[-5:]],
                                      "screenshot": self._save_screenshot(obs.screenshot, step, "stuck")}
                        self.end_reason = "stuck"
                        if self.on_frame is not None and obs.screenshot:
                            try:
                                self.on_frame(step, obs.screenshot, "Waiting for gameplay help", False)
                            except Exception:
                                log.debug("frame listener failed", exc_info=True)
                        log.warning("step %d: the same screen remained after %d inputs; waiting for help", step, attempts)
                        break

                sample = self._sample_metrics(obs, step, time.monotonic() - started)
                new_screen = key is not None and self.memory.visits.get(key, 0) == 1
                try:
                    action = self.policy.act(obs, self.memory)
                except Exception as exc:  # a broken policy must not kill the session
                    log.error("policy error at step %d: %s", step, exc)
                    action = Action(type="wait", duration_ms=300, note="policy-error")

                shot_rel = ""
                interesting = bool(detected) or new_screen
                if obs.screenshot and (want_shot or interesting):
                    shot_rel = self._save_screenshot(
                        obs.screenshot, step, "crash" if detected else ("new" if new_screen else "")
                    )
                if shot_rel and crashes:
                    for crash in crashes:
                        if crash.step == step and not crash.screenshot:
                            crash.screenshot = shot_rel

                record = StepRecord(
                    step=step,
                    elapsed_s=round(obs.elapsed_s, 3),
                    action=action.label,
                    alive=obs.alive,
                    screen=f"{key:016x}" if key else "",
                    new_screen=bool(new_screen),
                    visits=self.memory.visits.get(key, 0) if key else 0,
                    fps=sample.fps_estimate,
                    pss_kb=sample.total_pss_kb,
                    crashes=[c.signature[:60] for c in detected],
                    screenshot=shot_rel,
                )
                steps.append(record)
                self.result.timeline.append(
                    {
                        "step": step,
                        "time": round(obs.elapsed_s, 1),
                        "action": action.label,
                        "screen": record.screen,
                        "new": bool(new_screen),
                        "alive": obs.alive,
                        "shot": shot_rel,
                        "fps": sample.fps_estimate,
                        "pss_kb": sample.total_pss_kb,
                        "crashes": [c.signature[:60] for c in detected],
                    }
                )

                if self.on_step is not None:
                    try:
                        self.on_step(
                            {
                                "step": step,
                                "action": action.label,
                                "note": action.note,
                                "kind": action.type,
                                "screen": record.screen,
                                "new_screen": bool(new_screen),
                                "visits": record.visits,
                                "alive": obs.alive,
                                "fps": record.fps,
                                "pss_kb": record.pss_kb,
                                "crashes": [crash.kind for crash in detected],
                                "elapsed": round(obs.elapsed_s, 1),
                            }
                        )
                    except Exception:
                        log.debug("step listener failed", exc_info=True)

                if self.on_frame is not None and obs.screenshot:
                    try:
                        self.on_frame(step, obs.screenshot, action.label, bool(detected))
                    except Exception:  # a broken UI must never kill a test
                        log.debug("frame listener failed", exc_info=True)

                self.memory.recent.append(action)
                self.memory.last_action = action
                self.memory.step = step
                self.memory.crashes = crashes
                self._save_checkpoint(time.monotonic() - started, pending_input=action.type != "wait")
                try:
                    apply_action(self.device, action)
                except (AdbError, RuntimeError) as exc:
                    log.warning("input failed: %s", exc)
                    if isinstance(exc, DeviceUnavailable) or (isinstance(exc, AdbError) and phone_gone(exc)):
                        self.device_lost = True
                        self.end_reason = "phone_lost"
                        record.action += " [delivery unconfirmed]"
                        self.result.timeline[-1].update(action=record.action, input_unconfirmed=True)
                self._save_checkpoint(time.monotonic() - started)
                if self.device_lost:
                    break  # the command may have reached the phone; do not send it twice

                if (cfg.interruptions and cfg.interrupt_every and step % cfg.interrupt_every == 0
                        and obs.alive and self.policy.name != "observe"):
                    index = (step // cfg.interrupt_every - 1) % len(cfg.interruptions)
                    kind = cfg.interruptions[index]
                    self._phase(f"interrupt:{kind}")
                    try:
                        detail = self.device.interrupt(kind, package, activity)
                    except Exception as exc:
                        detail = f"skipped: {exc}"
                    time.sleep(0.4 if cfg.simulate else 1.0)
                    try:
                        survived = self.device.alive(package)
                    except DeviceUnavailable:
                        self.device_lost = True
                        log.warning("the phone disconnected during the %s test - ending the test", kind)
                        self.end_reason = "phone_lost"
                        break
                    entry = {"step": step, "kind": kind, "detail": detail, "survived": survived,
                             "skipped": str(detail).startswith("skipped")}
                    self.result.interruptions.append(entry)
                    self._save_checkpoint(time.monotonic() - started)
                    log.info("step %d: interruption %s → %s (%s)", step, kind, detail,
                             "survived" if survived else "APP DIED")
                    if self.on_step is not None:
                        try:
                            self.on_step({"step": step, "action": f"interrupt:{kind}", "kind": "interrupt",
                                          "note": detail, "alive": survived, "skipped": entry["skipped"], "crashes": [],
                                          "elapsed": round(time.monotonic() - started, 1)})
                        except Exception:
                            log.debug("step listener failed", exc_info=True)
                    self._phase("running")
                    if not survived:
                        more = self.device.poll_logs()
                        for line in more:
                            self._log_lines.append(line.raw or f"{line.ts} {line.level} {line.tag}: {line.msg}")
                        found = self.detector.feed(more, step)
                        if not found:
                            found = [logmod.Crash(kind="process_death", signature=f"died after {kind}",
                                                  message=f"app process died after the {kind} interruption",
                                                  ts=time.strftime("%m-%d %H:%M:%S"), step=step)]
                        for crash in found:
                            crash.message = f"[after {kind}] {crash.message}"
                        logmod.merge_crashes(crashes, found)
                        entry["finding"] = found[0].message[:160]
                        if cfg.relaunch_on_crash and relaunches < cfg.max_relaunches:
                            relaunches += 1
                            self.memory.relaunches = relaunches
                            try:
                                self.device.launch(package, activity)
                            except (AdbError, RuntimeError) as exc:
                                log.warning("relaunch failed: %s", exc)
                            continue

                if cfg.stop_after_crashes and len(crashes) >= cfg.stop_after_crashes:
                    log.info("stopping: reached %d distinct crashes", len(crashes))
                    self.end_reason = "too_many_crashes"
                    break

                if not obs.alive:
                    if cfg.relaunch_on_crash and relaunches < cfg.max_relaunches:
                        relaunches += 1
                        self.memory.relaunches = relaunches
                        log.info("relaunching app (%d/%d)", relaunches, cfg.max_relaunches)
                        time.sleep(0.8)
                        try:
                            self.device.launch(package, activity)
                        except (AdbError, RuntimeError) as exc:
                            log.warning("relaunch failed: %s", exc)
                        continue
                    log.info("app is not running and relaunch budget is spent, stopping at step %d", step)
                    self.end_reason = "app_kept_closing"
                    break

                self._sleep(cfg.step_delay_s)
            else:
                if self._section_end < cfg.steps:
                    self.end_reason = "section_complete"
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            interrupted = True
            log.warning("interrupted, writing report with the data collected so far")
        finally:
            if not self.resumable:
                self.close()

        self._active_time = (time.monotonic() if disconnected_at is None else disconnected_at) - started
        self._save_checkpoint(self._active_time)
        return self._finish(self._meta, crashes, steps, self._active_time, interrupted, step)

    def close(self) -> None:
        try:
            self.policy.end(self.memory)
        except Exception:
            log.debug("policy cleanup failed", exc_info=True)
        try:
            self.device.close()
        except Exception:
            log.debug("device cleanup failed", exc_info=True)

    # -- helpers -----------------------------------------------------------
    def _phase(self, name: str) -> None:
        if self.on_phase is not None:
            try:
                self.on_phase(name)
            except Exception:
                log.debug("phase listener failed", exc_info=True)

    def _sleep_plain(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.should_stop():
            time.sleep(0.1)

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        # The simulator has no real device latency; keep demo runs quick.
        end = time.monotonic() + seconds * (0.15 if self.config.simulate else 1.0)
        while time.monotonic() < end and not self.should_stop():
            time.sleep(min(0.1, max(0.0, end - time.monotonic())))

    def _sample_metrics(self, obs: Observation, step: int, elapsed: float) -> metricmod.MetricsSample:
        sample = obs.metrics
        sample.step = step
        sample.elapsed_s = round(elapsed, 3)
        if sample.total_frames is not None:
            window = elapsed - (self._prev_frames_at or 0.0)
            if self._prev_frames is not None and self._prev_frames_at is not None and window >= 0.3:
                fps = metricmod.frame_rate(self._prev_frames, sample.total_frames, window)
                if fps:
                    sample.fps_estimate = fps
                self._prev_frames = sample.total_frames
                self._prev_frames_at = elapsed
            elif self._prev_frames is None:
                self._prev_frames = sample.total_frames
                self._prev_frames_at = elapsed
        self._metrics.append(sample)
        return sample

    def _resolve_package(self) -> str:
        cfg = self.config
        adb = Adb(path=cfg.adb_path, serial=cfg.serial or None)
        before = set(adb.list_packages())
        adb.install(cfg.apk)
        after = set(adb.list_packages())
        new = sorted(after - before)
        if new:
            log.info("detected package %s from install", new[0])
            return new[0]
        raise ValueError(
            "--package is required: could not infer the package name from the APK "
            "(pass --package com.example.game)"
        )

    def _resolve_activity(self) -> str:
        cfg = self.config
        try:
            adb = getattr(self.device, "adb", None)
            if adb is not None:
                return adb.resolve_launch_activity(cfg.package)
        except AdbError:
            pass
        return ""

    def _finish(
        self,
        meta: Dict[str, Any],
        crashes: List[logmod.Crash],
        steps: List[StepRecord],
        duration: float,
        interrupted: bool,
        last_step: int,
    ) -> SessionResult:
        cfg = self.config
        fps_values = [s.fps_estimate for s in self._metrics if s.fps_estimate]
        pss_values = [s.total_pss_kb for s in self._metrics if s.total_pss_kb]
        jank_values = [s.janky_percent for s in self._metrics if s.janky_percent is not None]

        summary = {
            "steps_requested": cfg.steps,
            "steps_run": len(steps),
            "unconfirmed_inputs": sum(bool(row.get("input_unconfirmed")) for row in self.result.timeline),
            "resume_available": self.resumable,
            "duration_s": round(duration, 1),
            "interrupted": interrupted or self.stopped_by_user,
            "stopped_by_user": self.stopped_by_user,
            "device_lost": self.device_lost,
            "end_reason": "phone_lost" if self.device_lost and self.end_reason == "stopped" else self.end_reason,
            "planned_interruptions": list(cfg.interruptions),
            "interrupt_every": cfg.interrupt_every,
            "startup_runs": cfg.startup_runs,
            "time_budget_s": cfg.time_budget_s,
            "unique_crashes": len(crashes),
            "total_crash_events": sum(c.count for c in crashes),
            "anr_count": sum(1 for c in crashes if c.kind == "anr"),
            "native_crashes": sum(1 for c in crashes if c.kind == "native_crash"),
            "java_crashes": sum(1 for c in crashes if c.kind == "java_crash"),
            "screens_explored": self.memory.visited_count,
            "relaunches": self.memory.relaunches,
            "avg_fps": round(sum(fps_values) / len(fps_values), 1) if fps_values else None,
            "min_fps": round(min(fps_values), 1) if fps_values else None,
            "avg_jank_percent": round(sum(jank_values) / len(jank_values), 2) if jank_values else None,
            "peak_pss_kb": max(pss_values) if pss_values else None,
            "verdict": "crashes-found" if crashes else "no-failures-observed",
            "last_step": last_step,
        }
        cpu_values = [s.cpu_percent for s in self._metrics if getattr(s, "cpu_percent", None) is not None]
        temp_values = [s.battery_temp_c for s in self._metrics if getattr(s, "battery_temp_c", None) is not None]
        from .stress import memory_trend

        trend = memory_trend([m.to_dict() for m in self._metrics])
        done = [i for i in self.result.interruptions if not i.get("skipped")]
        startup = self.result.startup or {}
        summary.update({
            "interruptions_run": len(done),
            "interruptions_failed": sum(1 for i in done if not i.get("survived")),
            "cold_start_ms": startup.get("cold_avg_ms"),
            "warm_start_ms": startup.get("warm_avg_ms"),
            "avg_cpu_percent": round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
            "max_cpu_percent": max(cpu_values) if cpu_values else None,
            "max_battery_temp_c": max(temp_values) if temp_values else None,
            "mem_growth_kb_per_min": trend.get("growth_kb_per_min"),
        })
        self.result.perf = {"memory_trend": trend,
                            "fps_series": [[m.elapsed_s, m.fps_estimate] for m in self._metrics if m.fps_estimate],
                            "pss_series": [[m.elapsed_s, m.total_pss_kb] for m in self._metrics if m.total_pss_kb],
                            "cpu_series": [[m.elapsed_s, m.cpu_percent] for m in self._metrics
                                           if getattr(m, "cpu_percent", None) is not None]}
        if isinstance(self.policy, LLMPolicy):
            summary["llm"] = self.policy.stats()
        if getattr(self.policy, "name", "") == "agent":
            summary["ai"] = self.policy.stats()

        self.result.config = cfg.to_dict()
        self.result.meta = meta
        self.result.summary = summary
        self.result.steps = [s.to_dict() for s in steps]
        self.result.crashes = [c.to_dict() for c in crashes]
        self.result.screenshots = dict(self._shot_names)
        self.result.artifacts = {
            "session_json": "session.json",
            "logcat": "logcat.txt",
            "report": "report.html",
            "junit": "junit.xml",
            "screenshots": "screenshots",
        }

        os.makedirs(self.out_dir, exist_ok=True)  # never lose a finished session because the folder went missing
        os.makedirs(self.screenshots_dir, exist_ok=True)
        with open(os.path.join(self.out_dir, "logcat.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(self._log_lines))
        with open(os.path.join(self.out_dir, "metrics.json"), "w", encoding="utf-8") as handle:
            json.dump([m.to_dict() for m in self._metrics], handle, indent=2)
        with open(os.path.join(self.out_dir, "session.json"), "w", encoding="utf-8") as handle:
            json.dump(self.result.to_dict(), handle, indent=2)

        self._phase("reporting")
        from .report import write_html, write_junit

        write_html(self.result, self.out_dir)
        write_junit(self.result, os.path.join(self.out_dir, "junit.xml"))
        log.info("artifacts written to %s", self.out_dir)
        return self.result


def run_session(config: RunConfig, device: Optional[Device] = None, policy: Optional[BasePolicy] = None) -> SessionResult:
    return Session(config, device=device, policy=policy).run()
