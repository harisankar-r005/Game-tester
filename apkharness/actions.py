"""Input actions the harness can send to a device."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict

ACTION_TYPES = (
    "tap",
    "long_press",
    "swipe",
    "key",
    "text",
    "wait",
    "back",
    "home",
)

#: Android key codes the harness may need by name.
KEYCODES = {
    "back": 4,
    "home": 3,
    "menu": 82,
    "enter": 66,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
}


class ActionError(ValueError):
    """Raised when an action is malformed."""


@dataclass(frozen=True)
class Action:
    """A single device input.

    Coordinate fields are screen pixels in the native orientation.
    """

    type: str
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    duration_ms: int = 0
    keycode: int = 0
    text: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ActionError(f"unknown action type {self.type!r}")
        for name in ("x", "y", "x2", "y2", "duration_ms", "keycode"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ActionError(f"{name} must be an int, got {value!r}")
            if value < 0:
                raise ActionError(f"{name} must be >= 0, got {value}")
        if self.type in ("tap", "long_press") and self.duration_ms == 0:
            object.__setattr__(self, "duration_ms", 900 if self.type == "long_press" else 60)
        if self.type == "wait" and self.duration_ms == 0:
            object.__setattr__(self, "duration_ms", 500)

    @property
    def label(self) -> str:
        """Short human readable form, used in reports and prompts."""
        if self.type in ("tap", "long_press"):
            base = f"{self.type}({self.x},{self.y})"
        elif self.type == "swipe":
            base = f"swipe({self.x},{self.y}->{self.x2},{self.y2},{self.duration_ms}ms)"
        elif self.type == "text":
            base = f"text({self.text[:24]!r})"
        elif self.type == "wait":
            base = f"wait({self.duration_ms}ms)"
        else:
            base = f"{self.type}({self.keycode})" if self.keycode else self.type
        return f"{base} [{self.note}]" if self.note else base

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", 0)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Action":
        if not isinstance(data, dict):
            raise ActionError(f"action must be an object, got {type(data).__name__}")
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(data) - allowed
        if unknown:
            raise ActionError(f"unknown action field(s): {', '.join(sorted(unknown))}")
        payload = dict(data)
        payload.setdefault("type", "tap")
        if payload["type"] == "back":
            payload.setdefault("keycode", KEYCODES["back"])
        if payload["type"] == "home":
            payload.setdefault("keycode", KEYCODES["home"])
        if payload.get("keycode") is None:
            payload["keycode"] = 0
        if payload.get("text") is None:
            payload["text"] = ""
        return cls(**payload)

    def clamped(self, width: int, height: int) -> "Action":
        """Return a copy whose coordinates stay inside a ``width x height`` screen."""
        if not width or not height:
            return self
        max_x, max_y = max(width - 1, 0), max(height - 1, 0)
        return Action(
            type=self.type,
            x=min(max(self.x, 0), max_x),
            y=min(max(self.y, 0), max_y),
            x2=min(max(self.x2, 0), max_x),
            y2=min(max(self.y2, 0), max_y),
            duration_ms=self.duration_ms,
            keycode=self.keycode,
            text=self.text,
            note=self.note,
        )


def back() -> Action:
    return Action(type="back", keycode=KEYCODES["back"])


def home() -> Action:
    return Action(type="home", keycode=KEYCODES["home"])


def wait(ms: int = 500) -> Action:
    return Action(type="wait", duration_ms=ms)


def tap(x: int, y: int, note: str = "") -> Action:
    return Action(type="tap", x=int(x), y=int(y), note=note)


def swipe(x: int, y: int, x2: int, y2: int, duration_ms: int = 300, note: str = "") -> Action:
    return Action(type="swipe", x=int(x), y=int(y), x2=int(x2), y2=int(y2), duration_ms=duration_ms, note=note)
