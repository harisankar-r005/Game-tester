"""AI game player in the style of GamingAgent's "harness":

    perception  -> what is on the screen (picture + labelled controls + recent log)
    memory      -> what I tried, what happened, and my running notes
    reflection  -> every few steps, or when stuck, rethink the strategy
    reasoning   -> pick ONE next input, as JSON, validated like every other policy

Works with a **local** model (Ollama, offline, free) or a **cloud** model
(Anthropic Claude, OpenAI, or any OpenAI-compatible server). Every reply is
validated; anything slow, malformed or off-screen falls back to the heuristic
explorer, so the AI can never wedge a test. API keys are never written to disk
by this module and never put in logs or reports.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Callable, Deque, Dict, List, Optional

from ..actions import Action
from ..device import Observation
from ..png import dimensions
from ..ui import describe
from .base import BasePolicy, Memory, SessionContext
from .heuristic import HeuristicPolicy
from .llm import extract_json_object, parse_action

PROVIDERS = {
    "ollama": {"label": "Local – Ollama (offline, free)", "base_url": "http://127.0.0.1:11434",
               "model": "qwen2.5vl:7b", "needs_key": False},
    "anthropic": {"label": "Cloud – Anthropic Claude", "base_url": "https://api.anthropic.com",
                  "model": "claude-sonnet-5-5", "needs_key": True},
    "openai": {"label": "Cloud – OpenAI", "base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini", "needs_key": True},
    "custom": {"label": "Other OpenAI-compatible server (LM Studio, vLLM…)", "base_url": "http://127.0.0.1:1234/v1",
               "model": "local-model", "needs_key": False},
}

Transport = Callable[[str, Dict[str, str], Dict[str, Any], float], Dict[str, Any]]


def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-chosen endpoint
        return json.loads(response.read().decode("utf-8"))


def _get(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def shrink_png(png: Optional[bytes], max_width: int = 448) -> Optional[bytes]:
    """Downscale a phone screenshot so a local model answers in seconds, not minutes."""
    if not png:
        return None
    try:
        from ..png import decode, encode_rgba

        raster = decode(png)
        if raster.width <= max_width:
            return png
        scale = raster.width / float(max_width)
        width = max_width
        height = max(1, int(raster.height / scale))
        src, out = raster.rgba, bytearray(width * height * 4)
        for y in range(height):
            sy = min(raster.height - 1, int(y * scale)) * raster.width
            row = y * width * 4
            for x in range(width):
                i = (sy + min(raster.width - 1, int(x * scale))) * 4
                out[row + x * 4: row + x * 4 + 4] = src[i:i + 4]
        return encode_rgba(width, height, bytes(out))
    except Exception:  # an odd PNG must not stop the test
        return png


@dataclass
class View:
    """What the AI sees: a (shrunken) picture and controls, all in the picture's own pixels."""

    image: Optional[bytes]
    width: int
    height: int
    controls: str


def make_view(obs: Observation, vision: bool = True, max_width: int = 448) -> View:
    from ..ui import Node  # local import keeps module load light

    phone_w, phone_h = (obs.width, obs.height) if obs.width and obs.height else dimensions(obs.screenshot) or (1080, 1920)
    image = shrink_png(obs.screenshot, max_width) if (vision and obs.screenshot) else None
    view_w, view_h = dimensions(image) or (phone_w, phone_h)
    scales = (view_w / phone_w, view_h / phone_h) * 2
    nodes = [replace(n, bounds=tuple(round(value * scale) for value, scale in zip(n.bounds, scales)))
             for n in obs.ui_nodes if isinstance(n, Node)]
    return View(image, view_w, view_h, describe(nodes, view_w, view_h) or "(none)")


def to_phone(action: Action, view: View, obs: Observation) -> Action:
    phone_w, phone_h = (obs.width, obs.height) if obs.width and obs.height else dimensions(obs.screenshot) or (1080, 1920)
    action = action.clamped(view.width, view.height)
    sx, sy = phone_w / view.width, phone_h / view.height
    return replace(action, x=round(action.x * sx), y=round(action.y * sy),
                   x2=round(action.x2 * sx), y2=round(action.y2 * sy)).clamped(phone_w, phone_h)


@dataclass
class AIConfig:
    provider: str = "ollama"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout: float = 60.0
    vision: bool = True

    def resolved(self) -> "AIConfig":
        spec = PROVIDERS.get(self.provider, PROVIDERS["custom"])
        return replace(self, model=self.model or spec["model"], base_url=(self.base_url or spec["base_url"]).rstrip("/"))

    def public(self) -> Dict[str, Any]:
        """Safe to show in the UI or save in a report: never includes the key."""
        r = self.resolved()
        return {"provider": r.provider, "model": r.model, "base_url": r.base_url, "vision": r.vision,
                "has_key": bool(self.api_key), "label": PROVIDERS.get(r.provider, {}).get("label", r.provider)}


class AIClient:
    """One tiny chat call (system + user text + optional screenshot) for every provider."""

    def __init__(self, config: AIConfig, transport: Optional[Transport] = None) -> None:
        self.config = config.resolved()
        self.transport = transport or _post
        self.calls = 0
        self.failures = 0
        self.latency_ms: List[float] = []

    def chat(self, system: str, text: str, image_png: Optional[bytes] = None, max_tokens: int = 500) -> str:
        cfg = self.config
        image_b64 = base64.b64encode(image_png).decode("ascii") if (image_png and cfg.vision) else ""
        started = time.monotonic()
        try:
            if cfg.provider == "ollama":
                message: Dict[str, Any] = {"role": "user", "content": text}
                if image_b64:
                    message["images"] = [image_b64]
                reply = self.transport(f"{cfg.base_url}/api/chat", {"Content-Type": "application/json"}, {
                    "model": cfg.model, "stream": False, "format": "json", "options": {"temperature": 0.4},
                    "messages": [{"role": "system", "content": system}, message]}, cfg.timeout)
                content = (reply.get("message") or {}).get("content") or ""
            elif cfg.provider == "anthropic":
                blocks: List[Dict[str, Any]] = []
                if image_b64:
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}})
                blocks.append({"type": "text", "text": text})
                reply = self.transport(f"{cfg.base_url}/v1/messages", {
                    "Content-Type": "application/json", "x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"}, {
                    "model": cfg.model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": blocks}]}, cfg.timeout)
                content = "".join(b.get("text", "") for b in reply.get("content") or [] if b.get("type") == "text")
            else:  # openai + any OpenAI-compatible server
                user: Any = text
                if image_b64:
                    user = [{"type": "text", "text": text},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}]
                headers = {"Content-Type": "application/json"}
                if cfg.api_key:
                    headers["Authorization"] = f"Bearer {cfg.api_key}"
                reply = self.transport(f"{cfg.base_url}/chat/completions", headers, {
                    "model": cfg.model, "temperature": 0.4, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, cfg.timeout)
                content = ((reply.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            self.calls += 1
            self.latency_ms.append(round((time.monotonic() - started) * 1000))
            return content
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            self.failures += 1
            raise AIUnavailable(_friendly_error(cfg, exc)) from exc

    def ask_json(self, system: str, text: str, image_png: Optional[bytes] = None) -> Dict[str, Any]:
        reply = self.chat(system, text, image_png)
        data = extract_json_object(reply)
        if data is None:
            self.failures += 1
            raise AIUnavailable("the AI answered, but not in the expected format")
        return data


class AIUnavailable(RuntimeError):
    pass


def _friendly_error(cfg: AIConfig, exc: BaseException) -> str:
    text = str(exc)
    if cfg.provider == "ollama" and ("refused" in text.lower() or "10061" in text):
        return "Ollama is not running on this computer - install it from ollama.com and start it"
    if "404" in text and cfg.provider == "ollama":
        return f"Ollama does not have the model '{cfg.model}' yet - run: ollama pull {cfg.model}"
    if "401" in text or "403" in text:
        return "the API key was refused - check it in the AI settings"
    if "timed out" in text.lower():
        return "the AI took too long to answer"
    return text[:200]


def check_connection(config: AIConfig, transport: Optional[Transport] = None) -> Dict[str, Any]:
    """Used by the settings panel's 'Test connection' button."""
    cfg = config.resolved()
    info: Dict[str, Any] = {"ok": False, "models": [], "message": ""}
    if PROVIDERS.get(cfg.provider, {}).get("needs_key") and not cfg.api_key:
        info["message"] = "enter your API key first"
        return info
    if cfg.provider == "ollama":
        try:
            tags = _get(f"{cfg.base_url}/api/tags")
            info["models"] = [m.get("name") for m in tags.get("models") or []]
        except Exception as exc:
            info["message"] = _friendly_error(cfg, exc)
            return info
        if cfg.model not in info["models"] and f"{cfg.model}:latest" not in info["models"]:
            info["message"] = f"Ollama is running, but the model '{cfg.model}' is missing - run: ollama pull {cfg.model}"
            return info
    try:
        client = AIClient(cfg, transport)
        data = client.ask_json('Reply only with JSON like {"ok": true}.', 'Say {"ok": true}.')
        info["ok"] = bool(data)
        info["message"] = f"connected – {cfg.model} answered in {client.latency_ms[-1] / 1000:.1f} s"
    except AIUnavailable as exc:
        info["message"] = str(exc)
    return info


AGENT_SYSTEM = """You are an expert mobile-game QA tester controlling an Android phone.
Your goal: {goal}
You see a screenshot (if provided), the labelled controls on screen, the recent phone log,
your notes, and what your last actions did. Choose ONE next input.

Reply with JSON only:
{{"thought": "<one short sentence>", "action": {{...}}{extra}}}

Actions (pixel coordinates on a {width}x{height} screen):
  {{"type": "tap", "x": 20, "y": 20}}
  {{"type": "long_press", "x": 20, "y": 20, "duration_ms": 900}}
  {{"type": "swipe", "x": 20, "y": 40, "x2": 20, "y2": 20, "duration_ms": 300}}
  {{"type": "back"}}   {{"type": "wait", "duration_ms": 800}}   {{"type": "text", "text": "player1"}}
Use the visible controls and prioritize the provided gameplay objective when present. For a visible
virtual joystick, start a longer swipe at its center and move toward the intended direction within
the joystick area. Check the next screenshot for movement before choosing another direction.
Rules: never tap the same spot more than twice in a row when nothing changes; close ads/pop-ups
with their X or Back; never buy anything with real money; prefer unexplored buttons."""

REFLECT_SYSTEM = """You are reviewing your own progress as a mobile-game QA tester.
Reply with JSON only: {"notes": "<what you learned about this game, max 4 short lines>",
"strategy": "<what to try next, one sentence>", "stuck": true|false}"""


class AgentPolicy(BasePolicy):
    """GamingAgent-style harness: perception + memory + reflection + reasoning."""

    name = "agent"

    def __init__(self, config: AIConfig, seed: int = 7, think_every: int = 1, reflect_every: int = 15,
                 stuck_after: int = 5, max_failures: int = 6, transport: Optional[Transport] = None,
                 fallback: Optional[BasePolicy] = None) -> None:
        self.client = AIClient(config, transport)
        self.fallback = fallback or HeuristicPolicy(seed=seed)
        self.think_every = max(1, think_every)
        self.reflect_every = max(3, reflect_every)
        self.stuck_after = max(2, stuck_after)
        self.max_failures = max_failures
        self.context = SessionContext()
        self.journal: Deque[Dict[str, Any]] = deque(maxlen=10)
        self.notes = ""
        self.strategy = ""
        self.goal_override = ""
        self.reflections = 0
        self.same_screen = 0
        self.last_key: Optional[int] = None
        self.disabled_reason = ""
        self.fail_streak = 0
        self.last_thought = ""

    # lifecycle ---------------------------------------------------------------
    def begin(self, context: SessionContext) -> None:
        self.context = context
        self.fallback.begin(context)

    def end(self, memory: Memory) -> None:
        self.fallback.end(memory)

    def checkpoint_state(self) -> Dict[str, Any]:
        return {"notes": self.notes, "strategy": self.strategy, "journal": list(self.journal),
                "same_screen": self.same_screen, "last_key": self.last_key, "reflections": self.reflections}

    def restore_checkpoint(self, state: Dict[str, Any]) -> None:
        self.notes, self.strategy = state["notes"], state["strategy"]
        self.journal.extend(state["journal"])
        self.same_screen, self.last_key, self.reflections = state["same_screen"], state["last_key"], state["reflections"]

    # perception -------------------------------------------------------------
    def _perceive(self, obs: Observation, memory: Memory, view: Optional[View] = None) -> str:
        view = view or make_view(obs, self.client.config.vision)
        journal = "\n".join(f"- step {j['step']}: {j['action']} → {j.get('outcome', '?')}" for j in self.journal) or "- nothing yet"
        crashes = ", ".join(sorted({c.kind for c in memory.crashes})) or "none"
        return "\n".join([
            f"Step {obs.step} of {self.context.max_steps}. Screens discovered so far: {memory.visited_count}.",
            f"Game running: {'yes' if obs.alive else 'NO - it just closed'}. Problems found so far: {crashes}.",
            f"Same screen for the last {self.same_screen} step(s).",
            "Gameplay objective: " + (self.context.gameplay_objective or "Open exploration"),
            "", "Your notes: " + (self.notes or "(none yet)"),
            "Your current strategy: " + (self.strategy or "explore everything and play the game"),
            "", "What your last actions did:", journal,
            "", "Labelled controls on screen (games often show none):",
            view.controls,
            "", "Recent phone log:", obs.log_excerpt(8) or "(quiet)",
        ])

    # memory -----------------------------------------------------------------
    def _remember_outcome(self, obs: Observation, memory: Memory) -> None:
        key = obs.screen_key
        self.same_screen = self.same_screen + 1 if (key is not None and key == self.last_key) else 0
        if self.journal and "outcome" not in self.journal[-1]:
            if not obs.alive:
                outcome = "the game CLOSED"
            elif key is None:
                outcome = "screen change could not be determined"
            elif key is not None and memory.visits.get(key, 0) <= 1:
                outcome = "a NEW screen appeared"
            elif key == self.last_key:
                outcome = "nothing changed"
            else:
                outcome = "went to a screen seen before"
            self.journal[-1]["outcome"] = outcome
        self.last_key = key

    def _record_action(self, obs: Observation, action: Action) -> Action:
        self.journal.append({"step": obs.step, "action": action.label})
        return action

    # reflection -------------------------------------------------------------
    def _reflect(self, obs: Observation, memory: Memory) -> None:
        try:
            view = make_view(obs, self.client.config.vision)
            data = self.client.ask_json(REFLECT_SYSTEM, self._perceive(obs, memory, view), view.image)
        except AIUnavailable:
            return
        self.notes = str(data.get("notes") or self.notes)[:500]
        self.strategy = str(data.get("strategy") or self.strategy)[:200]
        self.reflections += 1

    # reasoning --------------------------------------------------------------
    def act(self, obs: Observation, memory: Memory) -> Action:
        self._remember_outcome(obs, memory)
        if self.disabled_reason or obs.step % self.think_every:
            action = self.fallback.act(obs, memory)
            return self._record_action(obs, replace(action, note=action.note or "explore"))
        if obs.step % self.reflect_every == 0 or (self.same_screen and self.same_screen % self.stuck_after == 0):
            self._reflect(obs, memory)
        view = make_view(obs, self.client.config.vision)
        system = AGENT_SYSTEM.format(goal=self.goal_override or self.context.goal, width=view.width, height=view.height, extra="")
        try:
            data = self.client.ask_json(system, self._perceive(obs, memory, view), view.image)
            action = parse_action(json.dumps(data))
            if action is None:
                raise AIUnavailable("no valid action in the AI reply")
            action = to_phone(action, view, obs)  # the AI worked in picture pixels
            self.fail_streak = 0
            self.last_thought = str(data.get("thought") or "")[:160]
            return self._record_action(obs, replace(action, note=("ai: " + self.last_thought)[:120]))
        except AIUnavailable as exc:
            self.fail_streak += 1
            if self.fail_streak >= self.max_failures:
                self.disabled_reason = str(exc)
            action = self.fallback.act(obs, memory)
            return self._record_action(obs, replace(action, note=f"ai unavailable ({str(exc)[:60]})"))

    def stats(self) -> Dict[str, Any]:
        lat = sorted(self.client.latency_ms)
        return {"ai": self.client.config.public(), "calls": self.client.calls, "failures": self.client.failures,
                "median_latency_ms": lat[len(lat) // 2] if lat else None, "reflections": self.reflections,
                "notes": self.notes, "disabled": self.disabled_reason}


JUDGE_SYSTEM = """You are a careful mobile-game QA tester checking ONE expected result on an Android phone.
Look at the screenshot, labelled controls and log. Reply with JSON only:
{"verdict": "pass" | "fail" | "unsure", "reason": "<one short sentence a non-technical person understands>"}
Say "unsure" whenever the picture does not clearly prove pass or fail."""

STEP_SYSTEM = """You are a mobile-game QA tester doing ONE step of a written test case on an Android phone.
Step to do: {step}
{inputs}Reply with JSON only:
{{"done": true|false, "needs_human": true|false, "thought": "<one short sentence>", "action": {{...}}}}
Set "done": true (and no action) when the step is already complete on screen.
Set "needs_human": true when a person must do it (real payment, login with a code, captcha,
physical action, or you are clearly stuck). Actions are as before, on a {width}x{height} screen:
tap/long_press/swipe/back/wait/text. Never buy anything with real money."""
