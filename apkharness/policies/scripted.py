"""Replay a fixed action list from JSON - the reproducible regression mode."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..actions import Action, ActionError, wait
from ..device import Observation
from .base import BasePolicy, Memory, SessionContext


class ScriptedPolicy(BasePolicy):
    name = "scripted"

    def __init__(self, actions: Optional[List[Action]] = None, loop: bool = False) -> None:
        self.actions: List[Action] = list(actions or [])
        self.loop = loop
        self.index = 0

    def begin(self, context: SessionContext) -> None:
        super().begin(context)
        self.index = 0

    def act(self, observation: Observation, memory: Memory) -> Action:
        if not self.actions:
            return wait(250)
        if self.index >= len(self.actions):
            if not self.loop:
                return wait(250)
            self.index = 0
        action = self.actions[self.index]
        self.index += 1
        return action.clamped(observation.width, observation.height) if observation.width else action

    @property
    def exhausted(self) -> bool:
        return not self.loop and self.index >= len(self.actions)

    def end(self, memory: Memory) -> None:
        return None


def load_script(path: str) -> tuple:
    """Load an action script, returning ``(actions, loop)``."""
    with open(path, "r", encoding="utf-8") as handle:
        data: Any = json.load(handle)
    loop = False
    raw_actions: Any = data
    if isinstance(data, dict):
        raw_actions = data.get("actions", [])
        loop = bool(data.get("loop", False))
    if not isinstance(raw_actions, list):
        raise ActionError(f"{path}: expected a JSON list of actions or {{'actions': [...]}}")
    actions: List[Action] = []
    for index, entry in enumerate(raw_actions):
        if isinstance(entry, str):
            entry = {"type": entry}
        if not isinstance(entry, dict):
            raise ActionError(f"{path}: action #{index + 1} is not an object")
        try:
            actions.append(Action.from_dict(entry))
        except ActionError as exc:
            raise ActionError(f"{path}: action #{index + 1}: {exc}") from exc
    return actions, loop


def script_from_dict(data: Dict[str, Any]) -> ScriptedPolicy:
    raw = data.get("actions", []) if isinstance(data, dict) else []
    actions = [Action.from_dict(item if isinstance(item, dict) else {"type": str(item)}) for item in raw]
    return ScriptedPolicy(actions=actions, loop=bool(data.get("loop", False)) if isinstance(data, dict) else False)
