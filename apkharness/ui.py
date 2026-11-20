"""Accessibility tree (``uiautomator dump``) parsing and node selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

#: Resource-id fragments that belong to system chrome rather than the game.
NOISE_IDS = (
    "android:id/",
    "com.android.systemui",
    "navigation_bar",
    "status_bar",
)


@dataclass(frozen=True)
class Node:
    text: str = ""
    desc: str = ""
    cls: str = ""
    rid: str = ""
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)
    clickable: bool = False
    enabled: bool = True
    scrollable: bool = False
    focused: bool = False
    selected: bool = False
    depth: int = 0

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])

    @property
    def center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def label(self) -> str:
        return self.desc or self.text or self.short_id or self.cls.rsplit(".", 1)[-1]

    @property
    def short_id(self) -> str:
        return self.rid.split("/", 1)[-1] if "/" in self.rid else self.rid

    @property
    def is_noise(self) -> bool:
        return any(fragment in self.rid for fragment in NOISE_IDS)

    def contains(self, x: int, y: int) -> bool:
        x1, y1, x2, y2 = self.bounds
        return x1 <= x <= x2 and y1 <= y <= y2

    def to_dict(self) -> dict:
        payload = {
            "text": self.text,
            "desc": self.desc,
            "class": self.cls,
            "id": self.rid,
            "bounds": list(self.bounds),
            "clickable": self.clickable,
        }
        if self.scrollable:
            payload["scrollable"] = True
        return payload


def parse_ui(xml: str) -> List[Node]:
    """Tolerant parser: returns ``[]`` for anything that is not a hierarchy."""
    if not xml or "<" not in xml:
        return []
    start = xml.find("<")
    end = xml.rfind(">")
    if start < 0 or end <= start:
        return []
    payload = xml[start : end + 1]
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    nodes: List[Node] = []

    def walk(element: ET.Element, depth: int) -> None:
        if element.tag == "node":
            nodes.append(_to_node(element, depth))
        for child in list(element):
            walk(child, depth + 1 if element.tag == "node" else depth)

    walk(root, 0)
    return nodes


def _to_node(element: ET.Element, depth: int) -> Node:
    attrs = element.attrib
    match = BOUNDS_RE.search(attrs.get("bounds", ""))
    bounds = tuple(int(v) for v in match.groups()) if match else (0, 0, 0, 0)
    return Node(
        text=attrs.get("text", "") or "",
        desc=attrs.get("content-desc", "") or "",
        cls=attrs.get("class", "") or "",
        rid=attrs.get("resource-id", "") or "",
        bounds=bounds,  # type: ignore[arg-type]
        clickable=_bool(attrs.get("clickable")),
        enabled=_bool(attrs.get("enabled"), default=True),
        scrollable=_bool(attrs.get("scrollable")),
        focused=_bool(attrs.get("focused")),
        selected=_bool(attrs.get("selected")),
        depth=depth,
    )


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


def screen_area(nodes: Sequence[Node]) -> Tuple[int, int]:
    width = max((n.bounds[2] for n in nodes), default=0)
    height = max((n.bounds[3] for n in nodes), default=0)
    return width, height


def usable(nodes: Iterable[Node], width: int = 0, height: int = 0) -> List[Node]:
    """Nodes worth tapping: on screen, enabled, visible and not the background."""
    result: List[Node] = []
    for node in nodes:
        if not node.enabled or node.width < 8 or node.height < 8:
            continue
        if node.is_noise:
            continue
        if width and height and node.width >= width * 0.95 and node.height >= height * 0.95:
            continue  # full-screen container, tapping it is meaningless
        result.append(node)
    return result


def rank_candidates(nodes: Sequence[Node], width: int = 0, height: int = 0) -> List[Node]:
    """Best-first ordering for exploration.

    Labelled buttons beat unlabelled ones: if a human can read it, an
    explorer has a better chance of finding a new screen by tapping it.
    """
    pool = usable(nodes, width, height)

    def score(node: Node) -> tuple:
        has_text = bool(node.text.strip())
        has_desc = bool(node.desc.strip())
        return (
            0 if (node.clickable and (has_text or has_desc)) else 1,
            0 if node.clickable else 1,
            0 if has_text else 1,
            0 if has_desc else 1,
            node.depth,
            -node.width * node.height,
        )

    return sorted(pool, key=score)


def describe(nodes: Sequence[Node], width: int = 0, height: int = 0, limit: int = 24) -> str:
    """Plain-text screen summary for prompts and logs."""
    picked = rank_candidates(nodes, width, height)[:limit]
    if not picked:
        return "no accessible elements (game surface renders without a view tree)"
    lines = []
    for node in picked:
        cx, cy = node.center
        tag = "button" if node.clickable else "element"
        lines.append(f"- {node.label!r} ({tag}) at ({cx},{cy}) size {node.width}x{node.height}")
    return "\n".join(lines)


def find_by_label(nodes: Iterable[Node], query: str) -> Optional[Node]:
    """First node whose text/desc/id contains ``query`` (case-insensitive)."""
    needle = query.strip().lower()
    if not needle:
        return None
    for node in nodes:
        haystack = f"{node.text} {node.desc} {node.rid}".lower()
        if needle in haystack:
            return node
    return None
