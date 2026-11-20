"""Watch-only policy: launch the app, capture it, never touch it.

Some locked-down OEM builds (MIUI/HyperOS with `USB debugging (Security settings)`
off) revoke input injection entirely: ``input``, ``monkey`` and even ``sendevent``
are denied, and there is no root. The harness can still do a real, useful device
run in that situation - launch, record video, sample FPS/memory, watch logcat for
startup crashes and ANRs - it just cannot drive the game.
"""

from __future__ import annotations

from ..actions import Action
from ..device import Observation
from .base import BasePolicy, Memory, SessionContext


class ObservePolicy(BasePolicy):
    name = "observe"

    def __init__(self, delay_ms: int = 800) -> None:
        self.delay_ms = max(200, int(delay_ms))

    def act(self, observation: Observation, memory: Memory) -> Action:
        return Action(type="wait", duration_ms=self.delay_ms, note="observe:no-input")


def build(delay_ms: int = 800) -> ObservePolicy:
    return ObservePolicy(delay_ms=delay_ms)
