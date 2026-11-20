"""Run written test cases on a phone: automatically where possible, with a person when needed.

For every test case:

1. optionally restart the game so each case starts clean;
2. do each step – the AI player tries it (a few inputs at most); if there is no AI, the step is
   marked [human], the AI says a person is needed, or it gets stuck, the tester **asks you** on the
   page ("please do this on the phone, then press Done");
3. watch the phone log the whole time – a crash, freeze or the game disappearing is an
   automatic **Failed**, whatever anyone says;
4. check the expected result – the AI judges from the screen; when it is unsure (or there is no
   AI) **you** decide Passed / Failed;
5. record **PASSED / FAILED / NOT PASSED** with the reason, who decided, and a screenshot.

"Not passed" means the case could not be completed: a step was skipped or blocked, you stopped
the run, nobody answered in time, or the phone disconnected.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import logs as logmod
from .casefile import fill
from .device import Device, DeviceUnavailable, apply_action, observe

PASSED, FAILED, NOT_PASSED = "PASSED", "FAILED", "NOT PASSED"


@dataclass
class Question:
    """Something the tester needs a person for. Shown on the page until answered."""

    kind: str                    # "do" (do a step) | "judge" (pass/fail) | "input"
    case_id: str
    title: str
    text: str
    options: List[str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    asked_at: float = field(default_factory=time.time)
    answer: str = ""
    note: str = ""
    event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "case_id": self.case_id, "title": self.title,
                "text": self.text, "options": list(self.options), "asked_at": self.asked_at}


class HumanDesk:
    """The hand-off point between the runner thread and the web page."""

    def __init__(self) -> None:
        self.current: Optional[Question] = None
        self.lock = threading.Lock()

    def ask(self, question: Question, should_stop: Callable[[], bool], timeout_s: float) -> str:
        with self.lock:
            self.current = question
        deadline = time.monotonic() + timeout_s
        try:
            while not question.event.wait(0.3):
                if should_stop():
                    return "stopped"
                if time.monotonic() > deadline:
                    return "timeout"
            return question.answer
        finally:
            with self.lock:
                if self.current is question:
                    self.current = None

    def answer(self, question_id: str, answer: str, note: str = "") -> bool:
        with self.lock:
            q = self.current
            if q is None or q.id != question_id or answer not in q.options:
                return False
            q.answer, q.note = answer, note[:500]
            q.event.set()
            return True


@dataclass
class CaseResult:
    id: str
    title: str
    status: str = NOT_PASSED
    reason: str = ""
    decided_by: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    screenshot: str = ""
    expected: str = ""
    seconds: float = 0.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class CaseRunner:
    def __init__(self, device: Device, package: str, activity: str, cases: List[Dict[str, Any]],
                 inputs: Dict[str, str], out_dir: str, desk: HumanDesk, ai_config: Optional[Dict[str, Any]] = None,
                 should_stop: Callable[[], bool] = lambda: False,
                 on_event: Callable[[str, str], None] = lambda level, msg: None,
                 on_update: Callable[[Dict[str, Any]], None] = lambda state: None,
                 on_frame: Optional[Callable[[int, bytes, str, bool], None]] = None,
                 max_actions_per_step: int = 8, human_timeout_s: float = 900.0, simulate: bool = False) -> None:
        self.device, self.package, self.activity = device, package, activity
        self.cases, self.inputs, self.out_dir, self.desk = cases, inputs, out_dir, desk
        self.should_stop, self.on_event, self.on_update, self.on_frame = should_stop, on_event, on_update, on_frame
        self.max_actions = max_actions_per_step
        self.human_timeout = human_timeout_s
        self.simulate = simulate
        self.detector = logmod.CrashDetector(package)
        self.log_lines: List[str] = []
        self.results: List[CaseResult] = []
        self.tick = 0
        self.started = time.monotonic()
        self.ai = None
        if ai_config:
            from .policies.agent import AIClient, AIConfig

            known = {k: v for k, v in ai_config.items() if k in AIConfig.__dataclass_fields__}
            self.ai = AIClient(AIConfig(**known))
        self.ai_off_reason = "" if self.ai else "no AI player chosen – you do the steps, the tester watches"
        os.makedirs(os.path.join(out_dir, "cases"), exist_ok=True)

    # -- helpers --------------------------------------------------------------
    def _look(self, want_ui: bool = True):
        self.tick += 1
        tick = getattr(self.device, "tick", None)
        if callable(tick):
            tick()
        obs = observe(self.device, self.tick, time.monotonic() - self.started, self.package,
                      want_screenshot=True, want_ui=want_ui, want_metrics=False)
        if self.on_frame and obs.screenshot:
            try:
                self.on_frame(self.tick, obs.screenshot, "", False)
            except Exception:
                pass
        return obs

    def _new_problems(self, case: CaseResult) -> List[Dict[str, Any]]:
        lines = self.device.poll_logs()
        for line in lines:
            self.log_lines.append(line.raw or f"{line.ts} {line.level} {line.tag}: {line.msg}")
        found = [c.to_dict() for c in self.detector.feed(lines, self.tick)]
        alive = True
        try:
            alive = self.device.alive(self.package)
        except DeviceUnavailable:
            raise
        if not alive and not found:
            found = [{"kind": "process_death", "message": "the game closed without an error message",
                      "signature": "process vanished", "step": self.tick}]
        for item in found:
            case.findings.append(item)
            self.on_event("error", f"{case.id}: {item.get('kind', 'problem').replace('_', ' ')} – "
                                   f"{str(item.get('message', ''))[:120]}")
        return found

    def _save_shot(self, case: CaseResult, png: Optional[bytes], tag: str) -> str:
        if not png:
            return ""
        name = f"cases/{case.id}_{tag}.png".replace(" ", "_")
        with open(os.path.join(self.out_dir, name), "wb") as handle:
            handle.write(png)
        return name

    def _state(self, extra: Dict[str, Any]) -> None:
        state = {"done": len(self.results), "total": len(self.cases),
                 "results": [r.to_dict() for r in self.results], "ai": bool(self.ai)}
        state.update(extra)
        self.on_update(state)

    def _ask(self, case: Dict[str, Any], kind: str, text: str, options: List[str]) -> str:
        title = f"{case['id']} · {fill(case.get('title', ''), self.inputs)}"
        q = Question(kind=kind, case_id=case["id"], title=title, text=text, options=options)
        self.on_event("warn", f"{case['id']}: your help is needed – {text[:140]}")
        self._state({"current": case["id"], "phase": "waiting for you"})
        answer = self.desk.ask(q, self.should_stop, self.human_timeout)
        if q.note:
            self._last_note = q.note
        return answer

    # -- one step -------------------------------------------------------------
    def _do_step(self, case: Dict[str, Any], result: CaseResult, index: int, step: str) -> str:
        """Returns "done", "failed", "skipped", "stopped", "timeout" or "crash"."""
        human_step = case.get("mode") == "human" or index in (case.get("human_steps") or [])
        record = {"n": index + 1, "text": step, "by": "", "outcome": "", "actions": []}
        result.steps.append(record)
        if not human_step and self.ai is not None:
            from .policies.agent import STEP_SYSTEM, AIUnavailable, make_view, to_phone
            from .policies.llm import parse_action

            for attempt in range(self.max_actions):
                if self.should_stop():
                    record["outcome"] = "stopped"
                    return "stopped"
                obs = self._look()
                view = make_view(obs, self.ai.config.vision)
                inputs = "".join(f"- {k}: {v}\n" for k, v in self.inputs.items())
                system = STEP_SYSTEM.format(step=step, width=view.width, height=view.height,
                                            inputs=f"Test data you may type:\n{inputs}" if inputs else "")
                context = (f"Test case: {fill(case.get('title', ''), self.inputs)}\n"
                           f"Step {index + 1} of {len(case['steps'])}: {step}\n"
                           f"Actions already tried for this step: {', '.join(record['actions']) or 'none'}\n"
                           f"Labelled controls on screen:\n{view.controls}")
                try:
                    data = self.ai.ask_json(system, context, view.image)
                except AIUnavailable as exc:
                    self.on_event("warn", f"{case['id']}: AI unavailable ({exc}) – asking you")
                    break
                if data.get("done"):
                    record.update(by="AI", outcome="done")
                    self.on_event("info", f"{case['id']} step {index + 1}: done by the AI – {str(data.get('thought', ''))[:100]}")
                    return "done"
                if data.get("needs_human"):
                    record["ai_said"] = str(data.get("thought", ""))[:160]
                    break
                action = parse_action(json.dumps(data))
                if action is None:
                    continue
                action = to_phone(action, view, obs)
                record["actions"].append(action.label)
                self._state({"current": case["id"], "step": index + 1, "phase": f"AI: {action.label}"})
                try:
                    apply_action(self.device, action)
                except Exception as exc:
                    self.on_event("warn", f"input failed: {exc}")
                time.sleep(0.15 if self.simulate else 0.9)
                if self._new_problems(result):
                    record["outcome"] = "crash"
                    return "crash"
        # a person does it
        why = record.get("ai_said") or ("this step is marked for a person" if human_step else
                                        "the AI could not finish it" if self.ai else "")
        text = f"Please do this on the phone: “{step}”." + (f" ({why})" if why else "") + \
               " Then press Done. Press Failed if it cannot be done because the game is wrong."
        answer = self._ask(case, "do", text, ["Done", "Failed", "Skip"])
        record["by"] = "you"
        outcome = {"Done": "done", "Failed": "failed", "Skip": "skipped"}.get(answer, answer)
        record["outcome"] = outcome
        if outcome == "done" and self._new_problems(result):
            record["outcome"] = "crash"
            return "crash"
        return outcome

    # -- one case -------------------------------------------------------------
    def _run_case(self, case: Dict[str, Any]) -> CaseResult:
        started = time.monotonic()
        expected = fill(case.get("expected", ""), self.inputs)
        result = CaseResult(id=case["id"], title=fill(case.get("title", ""), self.inputs), expected=expected)
        self.on_event("info", f"▶ {case['id']}: {result.title}")
        self._state({"current": case["id"], "step": 0, "phase": "starting"})
        if case.get("fresh", True):
            try:
                self.device.force_stop(self.package)
                time.sleep(0.3 if self.simulate else 1.0)
                self.device.launch(self.package, self.activity)
                time.sleep(0.5 if self.simulate else 3.0)
            except Exception as exc:
                self.on_event("warn", f"could not restart the game: {exc}")
        self.device.poll_logs()  # forget older log lines
        for index, step in enumerate(case.get("steps") or []):
            step_text = fill(step, self.inputs)
            self._state({"current": case["id"], "step": index + 1, "phase": step_text[:80]})
            outcome = self._do_step(case, result, index, step_text)
            if outcome == "crash":
                result.status, result.decided_by = FAILED, "crash detector"
                kinds = ", ".join(sorted({f.get('kind', '?').replace('_', ' ') for f in result.findings}))
                result.reason = f"the game had a problem at step {index + 1} ({kinds})"
                break
            if outcome == "failed":
                result.status, result.decided_by = FAILED, "you"
                result.reason = f"step {index + 1} could not be done: “{step_text}”"
                break
            if outcome != "done":
                result.status = NOT_PASSED
                result.decided_by = "you" if outcome == "skipped" else "tester"
                result.reason = {"skipped": f"step {index + 1} was skipped",
                                 "stopped": "you stopped the run during this case",
                                 "timeout": f"nobody answered for step {index + 1} in time"}.get(outcome, outcome)
                break
        else:
            self._judge(case, result, expected)
        obs = None
        try:
            obs = self._look(want_ui=False)
        except DeviceUnavailable:
            raise
        except Exception:
            pass
        result.screenshot = self._save_shot(result, obs.screenshot if obs else None, result.status.replace(" ", "_").lower())
        result.seconds = round(time.monotonic() - started, 1)
        icon = {"PASSED": "✅", "FAILED": "❌"}.get(result.status, "⚠️")
        self.on_event("info" if result.status == PASSED else "error" if result.status == FAILED else "warn",
                      f"{icon} {case['id']} {result.status} – {result.reason}")
        return result

    def _judge(self, case: Dict[str, Any], result: CaseResult, expected: str) -> None:
        if self._new_problems(result):
            result.status, result.decided_by = FAILED, "crash detector"
            result.reason = "the game had a problem at the end of the case"
            return
        if expected and self.ai is not None and case.get("mode") != "human":
            from .policies.agent import JUDGE_SYSTEM, AIUnavailable, make_view

            obs = self._look()
            view = make_view(obs, self.ai.config.vision)
            try:
                data = self.ai.ask_json(JUDGE_SYSTEM, f"Expected result: {expected}\n\nLabelled controls on screen:\n{view.controls}",
                                        view.image)
                verdict = str(data.get("verdict", "unsure")).lower()
                if verdict in ("pass", "fail"):
                    result.status = PASSED if verdict == "pass" else FAILED
                    result.decided_by = "AI"
                    result.reason = str(data.get("reason") or ("expected result seen" if verdict == "pass" else "expected result not seen"))[:200]
                    return
                hint = str(data.get("reason") or "")[:140]
            except AIUnavailable as exc:
                hint = str(exc)[:100]
        else:
            hint = ""
        question = (f"Look at the phone. Expected: “{expected}”. Is that what you see?" if expected
                    else "This case has no expected result written. Did the game behave correctly?")
        if hint:
            question += f" (AI note: {hint})"
        answer = self._ask(case, "judge", question, ["Passed", "Failed", "Not sure"])
        result.decided_by = "you"
        if answer == "Passed":
            result.status, result.reason = PASSED, "you confirmed the expected result"
        elif answer == "Failed":
            result.status, result.reason = FAILED, "you said the expected result did not happen"
        else:
            result.status = NOT_PASSED
            result.reason = {"Not sure": "you could not confirm the result", "timeout": "nobody judged the result in time",
                             "stopped": "you stopped the run during this case"}.get(answer, answer)
        note = getattr(self, "_last_note", "")
        if note:
            result.note, self._last_note = note, ""

    # -- the whole run --------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        phone_lost = False
        for case in self.cases:
            if self.should_stop():
                break
            try:
                self.results.append(self._run_case(case))
            except DeviceUnavailable as exc:
                phone_lost = True
                self.results.append(CaseResult(id=case["id"], title=fill(case.get("title", ""), self.inputs),
                                               status=NOT_PASSED, reason="the phone disconnected during this case",
                                               decided_by="tester", expected=fill(case.get("expected", ""), self.inputs)))
                self.on_event("error", f"the phone disconnected: {str(exc)[:100]}")
                break
            self._state({"current": "", "phase": "next case"})
        done_ids = {r.id for r in self.results}
        for case in self.cases:
            if case["id"] not in done_ids:
                self.results.append(CaseResult(id=case["id"], title=fill(case.get("title", ""), self.inputs),
                                               status=NOT_PASSED, decided_by="tester",
                                               reason="not run – the run ended before this case",
                                               expected=fill(case.get("expected", ""), self.inputs)))
        counts = {s: sum(1 for r in self.results if r.status == s) for s in (PASSED, FAILED, NOT_PASSED)}
        verdict = "fail" if counts[FAILED] else ("warn" if counts[NOT_PASSED] else "pass")
        summary = {
            "kind": "test_cases", "cases_total": len(self.results), "passed": counts[PASSED], "failed": counts[FAILED],
            "not_passed": counts[NOT_PASSED], "verdict": verdict, "stopped_by_user": self.should_stop(),
            "device_lost": phone_lost, "duration_s": round(time.monotonic() - self.started, 1),
            "ai": self.ai.config.public() if self.ai else None, "ai_note": self.ai_off_reason,
        }
        payload = {"summary": summary, "results": [r.to_dict() for r in self.results], "inputs_used": sorted(self.inputs)}
        with open(os.path.join(self.out_dir, "case_results.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        with open(os.path.join(self.out_dir, "logcat.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(self.log_lines))
        findings = [f for r in self.results for f in r.findings]
        with open(os.path.join(self.out_dir, "session.json"), "w", encoding="utf-8") as handle:
            json.dump({"meta": {"package": self.package, "kind": "test_cases",
                                "backend": "simulator" if self.simulate else "adb"},
                       "summary": {"steps_run": len(self.results), "steps_requested": len(self.cases),
                                   "unique_crashes": len(findings), "verdict": verdict,
                                   "check_summary": {"verdict": verdict, "total": len(self.results),
                                                     "passed": counts[PASSED], "failed": counts[FAILED] + counts[NOT_PASSED]},
                                   **summary},
                       "crashes": findings, "case_run": payload}, handle, indent=2)
        write_case_report(payload, self.out_dir, self.package)
        return payload


def write_case_report(payload: Dict[str, Any], out_dir: str, package: str) -> str:
    import html

    s = payload["summary"]
    color = {"PASSED": "#15803d", "FAILED": "#c62828", "NOT PASSED": "#a15c00"}
    rows = "".join(
        f"<tr><td><b>{html.escape(r['id'])}</b><br>{html.escape(r['title'])}</td>"
        f"<td style='color:{color.get(r['status'], '#555')};font-weight:800'>{r['status']}</td>"
        f"<td>{html.escape(r['reason'])}<br><small>decided by {html.escape(r['decided_by'] or '-')}"
        f"{' · ' + html.escape(r['note']) if r.get('note') else ''}</small>"
        f"<details><summary>steps</summary><ol>{''.join(f'<li>{html.escape(st['text'])} – <i>{html.escape(st.get('outcome') or '')}</i> ({html.escape(st.get('by') or '')})</li>' for st in r['steps'])}</ol></details></td>"
        f"<td>{html.escape(r.get('expected') or '')}</td>"
        f"<td>{f'<img src=\"{html.escape(r['screenshot'])}\" style=\"max-width:140px\">' if r.get('screenshot') else ''}</td></tr>"
        for r in payload["results"])
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Test case report</title>
<style>body{{font:15px/1.5 Segoe UI,Arial,sans-serif;margin:24px;color:#18202b}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}}.k{{display:inline-block;margin-right:18px;font-size:20px;font-weight:800}}</style></head>
<body><h1>Test case report – {html.escape(package)}</h1>
<p><span class="k" style="color:#15803d">✅ {s['passed']} passed</span><span class="k" style="color:#c62828">❌ {s['failed']} failed</span>
<span class="k" style="color:#a15c00">⚠️ {s['not_passed']} not passed</span> of {s['cases_total']} · {s['duration_s']} s</p>
<table><tr><th>Test case</th><th>Result</th><th>Why</th><th>Expected</th><th>Screen</th></tr>{rows}</table></body></html>"""
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return path
