"""Policy interface: decide the next input from an observation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Protocol
from collections import deque

from ..actions import Action
from ..logs import Crash
from ..png import hamming
from ..device import Observation


@dataclass
class SessionContext:
    """Static facts a policy may need before the first action."""

    package: str = ""
    width: int = 0
    height: int = 0
    seed: int = 7
    max_steps: int = 200
    goal: str = "explore the app and provoke crashes, ANRs and performance problems"
    gameplay_objective: str = ""


@dataclass
class Memory:
    """What happened so far; shared by every policy."""

    step: int = 0
    hashes: List[int] = field(default_factory=list)
    visits: Dict[int, int] = field(default_factory=dict)
    screens: List[int] = field(default_factory=list)
    recent: Deque[Action] = field(default_factory=lambda: deque(maxlen=8))
    crashes: List[Crash] = field(default_factory=list)
    last_action: Optional[Action] = None
    last_phash: Optional[int] = None
    relaunches: int = 0
    _pending: Optional[int] = None

    def screen_key(self, phash: Optional[int]) -> Optional[int]:
        """Snap a hash onto the nearest known screen, or register a new one.

        A candidate must be similar to the previous *unmatched* frame before it is
        registered. Games animate constantly; without this hysteresis every frame
        would look like a new screen.
        """
        if phash is None:
            return None
        for known in self.hashes:
            if hamming(known, phash) <= 8:
                self.visits[known] = self.visits.get(known, 0) + 1
                self._pending = None
                return known
        if self._pending is not None and hamming(self._pending, phash) <= 6:
            self._pending = None
            self.hashes.append(phash)
            self.visits[phash] = 1
            self.screens.append(phash)
            if len(self.hashes) > 200:  # keep memory bounded on endless animations
                self.hashes.pop(0)
            return phash
        self._pending = phash
        return None

    @property
    def visited_count(self) -> int:
        return len(self.screens)

    def visits_for(self, phash: Optional[int]) -> int:
        """Visit count of the nearest known screen, without registering anything."""
        if phash is None:
            return 0
        for known in self.hashes:
            if hamming(known, phash) <= 8:
                return self.visits.get(known, 0)
        return 0

    def novelty(self, phash: Optional[int]) -> int:
        """Hamming distance to the closest known screen (64 when unknown)."""
        if phash is None:
            return 64
        if not self.hashes:
            return 64
        return min(hamming(known, phash) for known in self.hashes)

    def is_new_screen(self, phash: Optional[int], threshold: int = 10) -> bool:
        return self.novelty(phash) > threshold

    def recent_coords(self, limit: int = 4) -> List[tuple]:
        return [(a.x, a.y) for a in list(self.recent)[-limit:] if a.type in ("tap", "long_press")]


class Policy(Protocol):
    """Everything a policy must provide."""

    name: str

    def begin(self, context: SessionContext) -> None: ...

    def act(self, observation: Observation, memory: Memory) -> Action: ...

    def end(self, memory: Memory) -> None: ...


class BasePolicy:
    """Common no-op lifecycle so subclasses only implement ``act``."""

    name = "base"

    def begin(self, context: SessionContext) -> None:
        self._context = context

    def act(self, observation: Observation, memory: Memory) -> Action:  # pragma: no cover - interface
        raise NotImplementedError

    def end(self, memory: Memory) -> None:
        return None
