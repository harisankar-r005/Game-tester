"""Heuristic explorer: novelty-driven taps with a game-friendly fallback.

The accessibility tree is used when it exists (menus, shops, settings). Games
usually draw a single opaque surface, so the policy falls back to a weighted
mix of taps, swipes and waits, guided by the perceptual hash of the frame.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from ..actions import Action, back, wait
from ..device import Observation
from ..ui import Node, rank_candidates
from .base import BasePolicy, Memory, SessionContext


class HeuristicPolicy(BasePolicy):
    name = "heuristic"

    def __init__(
        self,
        seed: int = 7,
        novelty_threshold: int = 10,
        ui_bias: float = 0.7,
        stuck_screens: int = 14,
    ) -> None:
        self.seed = seed
        self.novelty_threshold = novelty_threshold
        self.ui_bias = ui_bias
        self.stuck_screens = stuck_screens
        self.random = random.Random(seed)
        self.width = 1080
        self.height = 1920
        self._last_labels: List[str] = []

    def begin(self, context: SessionContext) -> None:
        super().begin(context)
        self.random = random.Random(self.seed)
        self.width = context.width or self.width
        self.height = context.height or self.height

    # -- helpers -----------------------------------------------------------
    def _too_close(self, x: int, y: int, memory: Memory) -> bool:
        threshold = max(24, int(min(self.width, self.height) * 0.07))
        for px, py in memory.recent_coords(limit=3):
            if abs(px - x) <= threshold and abs(py - y) <= threshold:
                return True
        return False

    def _pick_node(self, nodes: List[Node], memory: Memory) -> Optional[Node]:
        if not nodes:
            return None
        pool = [n for n in nodes if n.enabled and n.clickable]
        if not pool:
            pool = list(nodes)
        unseen = [n for n in pool if n.label not in self._last_labels]
        candidates = unseen or pool
        candidates = sorted(candidates, key=lambda n: n.depth)
        head = candidates[: max(3, len(candidates) // 3)]
        return self.random.choice(head)

    def _random_point(self, memory: Memory) -> Tuple[int, int]:
        margin_x = max(1, self.width // 10)
        margin_y = max(1, self.height // 8)
        for _ in range(12):
            x = self.random.randint(margin_x, max(margin_x + 1, self.width - margin_x))
            y = self.random.randint(margin_y, max(margin_y + 1, self.height - margin_y))
            if not self._too_close(x, y, memory):
                return x, y
        return (self.width // 2, self.height // 2)

    def _swipe(self) -> Action:
        direction = self.random.choice(("up", "down", "left", "right"))
        cx, cy = self.width // 2, self.height // 2
        span_x, span_y = int(self.width * 0.3), int(self.height * 0.25)
        if direction == "up":
            return Action(type="swipe", x=cx, y=cy + span_y, x2=cx, y2=cy - span_y,
                          duration_ms=self.random.choice((180, 260, 400)), note="scroll")
        if direction == "down":
            return Action(type="swipe", x=cx, y=cy - span_y, x2=cx, y2=cy + span_y,
                          duration_ms=self.random.choice((180, 260, 400)), note="scroll")
        if direction == "left":
            return Action(type="swipe", x=cx + span_x, y=cy, x2=cx - span_x, y2=cy,
                          duration_ms=self.random.choice((160, 240)), note="scroll")
        return Action(type="swipe", x=cx - span_x, y=cy, x2=cx + span_x, y2=cy,
                      duration_ms=self.random.choice((160, 240)), note="scroll")

    # -- policy ------------------------------------------------------------
    def act(self, observation: Observation, memory: Memory) -> Action:
        width, height = observation.screen_size
        if width and height:
            self.width, self.height = width, height

        visits = memory.visits_for(observation.phash)
        new_screen = memory.is_new_screen(observation.phash, self.novelty_threshold)
        candidates = rank_candidates(observation.ui_nodes, self.width, self.height)

        # A screen we have not seen: try its labelled controls first.
        if candidates and (new_screen or self.random.random() < self.ui_bias):
            node = self._pick_node(candidates, memory)
            if node is not None:
                self._last_labels = [n.label for n in candidates]
                x, y = node.center
                if not (0 <= x < self.width and 0 <= y < self.height):
                    x, y = self.width // 2, self.height // 2
                return Action(type="tap", x=x, y=y, note=f"ui:{node.label[:28]}")

        # Stuck on one screen for far too long: escape the current activity.
        if visits > self.stuck_screens:
            self._last_labels = []
            if self.random.random() < 0.5:
                return back()
            return Action(type="swipe", x=self.width // 2, y=int(self.height * 0.35),
                          x2=self.width // 2, y2=int(self.height * 0.75),
                          duration_ms=260, note="escape scroll")

        roll = self.random.random()
        if roll < 0.58 or not observation.ui_nodes:
            x, y = self._random_point(memory)
            note = "explore:new-screen" if new_screen else "explore"
            if roll < 0.06:
                return Action(type="long_press", x=x, y=y, duration_ms=self.random.choice((700, 1200)),
                              note=note + ":hold")
            return Action(type="tap", x=x, y=y, note=note)
        if roll < 0.78:
            return self._swipe()
        if roll < 0.9:
            return back()
        return wait(self.random.choice((250, 500, 900)))

    def end(self, memory: Memory) -> None:
        return None
