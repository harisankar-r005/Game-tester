"""Policy registry."""

from __future__ import annotations

from typing import Any, Dict

from .base import BasePolicy, Memory, Policy, SessionContext
from .heuristic import HeuristicPolicy
from .llm import LLMPolicy
from .observe import ObservePolicy
from .scripted import ScriptedPolicy, load_script

POLICIES = ("heuristic", "agent", "llm", "scripted", "observe")

__all__ = [
    "BasePolicy",
    "HeuristicPolicy",
    "LLMPolicy",
    "ObservePolicy",
    "Memory",
    "POLICIES",
    "Policy",
    "ScriptedPolicy",
    "SessionContext",
    "build_policy",
    "load_script",
]


def build_policy(name: str, **kwargs: Any) -> BasePolicy:
    """Instantiate a policy by name, ignoring options it does not take."""
    if name == "heuristic":
        allowed = {k: v for k, v in kwargs.items() if k in ("seed", "novelty_threshold")}
        return HeuristicPolicy(**allowed)
    if name == "llm":
        allowed = {
            k: v
            for k, v in kwargs.items()
            if k in ("model", "base_url", "api_key", "timeout", "vision", "temperature", "seed")
        }
        return LLMPolicy(**allowed)
    if name == "observe":
        allowed = {k: v for k, v in kwargs.items() if k in ("delay_ms",)}
        return ObservePolicy(**allowed)
    if name == "scripted":
        allowed = {k: v for k, v in kwargs.items() if k in ("actions", "loop")}
        return ScriptedPolicy(**allowed)
    raise ValueError(f"unknown policy {name!r}; choose from {', '.join(POLICIES)}")
