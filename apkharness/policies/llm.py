"""LLM-backed explorer for any OpenAI-compatible chat completions endpoint.

The model never gets direct device access: it only picks the next action from a
text (optionally image) description of the screen, and every reply is validated
against the same :class:`Action` rules as the scripted and heuristic policies.
Anything malformed, slow or off-screen falls back to the heuristic explorer, so
a flaky network can never wedge a test session.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from ..actions import Action, ActionError
from ..device import Observation
from ..ui import describe
from .base import BasePolicy, Memory, SessionContext
from .heuristic import HeuristicPolicy

DEFAULT_BASE_URL = os.environ.get("APKHARNESS_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
DEFAULT_MODEL = os.environ.get("APKHARNESS_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"

SYSTEM_PROMPT = """You are the exploration brain of an automated Android game QA harness.
Your goal: {goal}.
You see a text description of the current screen (accessibility tree summary), the recent
input history, recent logcat lines and whether the app process is still alive.
Pick ONE next input that is likely to reach new screens, exercise gameplay and expose crashes.

Reply with a single JSON object and nothing else:
{{"reasoning": "<one short sentence>", "action": {{...}}}}

Allowed actions (pixel coordinates inside the screen):
  {{"type": "tap", "x": 540, "y": 960}}
  {{"type": "long_press", "x": 540, "y": 960, "duration_ms": 900}}
  {{"type": "swipe", "x": 540, "y": 1400, "x2": 540, "y2": 600, "duration_ms": 300}}
  {{"type": "key", "keycode": 4}}
  {{"type": "back"}} / {{"type": "home"}}
  {{"type": "wait", "duration_ms": 500}}
  {{"type": "text", "text": "player1"}}
Avoid repeating the exact same tap more than twice in a row; if the screen looks like a game
surface with no controls, explore the play area and try gestures.
Screen size: {width}x{height}."""


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit https endpoint
        return json.loads(response.read().decode("utf-8"))


Transport = Callable[[str, Dict[str, str], Dict[str, Any], float], Dict[str, Any]]


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of a model reply (fences, prose, etc.)."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_action(text: str) -> Optional[Action]:
    """Validate a model reply into an :class:`Action`, or ``None``."""
    data = extract_json_object(text)
    if not data:
        return None
    candidate = data.get("action") if isinstance(data.get("action"), dict) else data
    if not isinstance(candidate, dict) or "type" not in candidate:
        return None
    try:
        return Action.from_dict(candidate)
    except (ActionError, TypeError):
        return None


class LLMPolicy(BasePolicy):
    name = "llm"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        vision: bool = False,
        temperature: float = 0.5,
        max_retries: int = 2,
        transport: Optional[Transport] = None,
        fallback: Optional[BasePolicy] = None,
        seed: int = 7,
        history_turns: int = 6,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else (os.environ.get("APKHARNESS_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
        self.timeout = timeout
        self.vision = vision
        self.temperature = temperature
        self.max_retries = max_retries
        self.transport = transport or _post_json
        self.fallback = fallback or HeuristicPolicy(seed=seed)
        self.history_turns = history_turns
        self.history: List[Dict[str, Any]] = []
        self.context = SessionContext()
        self.last_reasoning = ""
        self.failures = 0
        self.calls = 0
        self.latency_ms: List[float] = []

    def begin(self, context: SessionContext) -> None:
        self.context = context
        self.history = []
        self.fallback.begin(context)

    # -- prompt building ---------------------------------------------------
    def _system_prompt(self, width: int, height: int) -> str:
        return SYSTEM_PROMPT.format(goal=self.context.goal, width=width or 1080, height=height or 1920)

    def _state_text(self, observation: Observation, memory: Memory) -> str:
        screen_list = memory.visited_count
        recent = ", ".join(a.label for a in list(memory.recent)[-6:]) or "none"
        crashes = ", ".join(sorted({c.kind for c in memory.crashes})) or "none yet"
        lines = [
            f"Step {observation.step}/{self.context.max_steps}. Screen size "
            f"{observation.width}x{observation.height}. Distinct screens seen: {screen_list}.",
            f"App alive: {'yes' if observation.alive else 'NO - it just died'}. "
            f"Crashes/ANRs so far: {crashes}.",
            f"Last actions: {recent}.",
            "",
            "Current screen elements:",
            describe(observation.ui_nodes, observation.width, observation.height),
            "",
            "Recent logcat:",
            observation.log_excerpt(10),
        ]
        return "\n".join(lines)

    def _messages(self, observation: Observation, memory: Memory) -> List[Dict[str, Any]]:
        user_content: Any = self._state_text(observation, memory)
        if self.vision and observation.screenshot:
            encoded = base64.b64encode(observation.screenshot).decode("ascii")
            user_content = [
                {"type": "text", "text": self._state_text(observation, memory)},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(observation.width, observation.height)}
        ]
        messages.extend(self.history[-self.history_turns * 2 :])
        messages.append({"role": "user", "content": user_content})
        return messages

    # -- policy ------------------------------------------------------------
    def act(self, observation: Observation, memory: Memory) -> Action:
        if not self.api_key:
            self.failures += 1
            action = self.fallback.act(observation, memory)
            return replace(action, note="llm:no-api-key fallback")

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": self._messages(observation, memory),
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        messages = payload["messages"]
        last_error = ""
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                response = self.transport(
                    f"{self.base_url}/chat/completions", headers, payload, self.timeout
                )
                self.calls += 1
                self.latency_ms.append(round((time.monotonic() - started) * 1000, 1))
                content = ""
                try:
                    content = response["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, TypeError):
                    last_error = "unexpected response shape"
                    content = ""
                action = parse_action(content)
                if action is not None:
                    clamped = action.clamped(observation.width, observation.height)
                    parsed = extract_json_object(content) or {}
                    self.last_reasoning = str(parsed.get("reasoning", ""))[:200]
                    self.history.append({"role": "user", "content": self._state_text(observation, memory)})
                    self.history.append({"role": "assistant", "content": content})
                    self.history = self.history[-self.history_turns * 2 :]
                    return clamped
                last_error = "unparseable action"
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = str(exc)[:160]
            if attempt < self.max_retries:
                time.sleep(0.8 * (attempt + 1))

        self.failures += 1
        action = self.fallback.act(observation, memory)
        note = f"llm:fallback ({last_error or 'invalid reply'})"
        return replace(action, note=note[:120])

    def end(self, memory: Memory) -> None:
        self.fallback.end(memory)

    def stats(self) -> Dict[str, Any]:
        latency = sorted(self.latency_ms)
        return {
            "model": self.model,
            "calls": self.calls,
            "failures": self.failures,
            "median_latency_ms": latency[len(latency) // 2] if latency else None,
            "vision": self.vision,
        }
