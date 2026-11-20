"""Read hand-written test cases (and the inputs they need) from a Markdown file.

Forgiving format – any of these work::

    ## Inputs
    - username: player1
    - level: 3

    ## TC-01: Change the music setting
    Steps:
    1. Tap the Settings button
    2. Turn Music off
    3. Enter {username} in the name box
    Expected: The music switch shows OFF
    Mode: auto            (auto = tester tries alone · human = always ask a person)

    ### Test 2 - Buy coins  [human]
    - Open the shop
    - Buy the 100 coins pack with the test card
    **Expected result:** 100 coins are added

Placeholders like ``{username}`` or ``<level>`` are filled from the Inputs section, or asked
for in the page before the run. The document is data: it is parsed, never executed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

HEADING = re.compile(r"^\s{0,3}#{1,4}\s+(.*\S)\s*$")
CASE_HEAD = re.compile(
    r"^(?:(?P<id>(?:TC|T|CASE|TEST)[-_ ]?\d+[A-Za-z]?)\s*[:.\-–)]\s*(?P<title>.*)"
    r"|(?:test\s*case|test|case|scenario)\s*#?\s*(?P<num>\d+)\s*[:.\-–)]?\s*(?P<title2>.*))$",
    re.IGNORECASE,
)
FIELD = re.compile(r"^\s*(?:[-*]\s*)?\**\s*(steps?|expected(?:\s*result)?|result|mode|type|precondition[s]?|"
                   r"pre-?conditions?|given|fresh\s*start|restart)\s*\**\s*[:：]\s*\**\s*(.*)$", re.IGNORECASE)
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+(.*\S)\s*$")
KV = re.compile(r"^\s*(?:[-*]\s*)?\**([A-Za-z][\w .-]{0,40}?)\**\s*[:=]\s*(.+?)\s*$")
PLACEHOLDER = re.compile(r"\{\s*([A-Za-z][\w-]{0,40})\s*\}|<\s*([A-Za-z][\w-]{0,40})\s*>")
HUMAN_WORDS = re.compile(r"\[(?:human|manual)\]|\((?:human|manual)\)", re.IGNORECASE)
INPUT_SECTIONS = ("inputs", "input", "test data", "data", "variables", "settings", "values")

FIRST_CUSTOMER_PACKAGE = "com.UnityTechnologies.com.unity.template.urpblank"
FIRST_CUSTOMER_OBJECTIVE = (
    "When the first-customer tutorial asks you to go to the till, use the on-screen joystick to enter the restaurant. "
    "Reach the till and observe whether the tutorial advances."
)
FIRST_CUSTOMER_WALKTHROUGH = """\
## TC-01: Open the first-customer objective [human]
Fresh start: no
Steps:
1. Open the tutorial from a save that is at or before the first-customer objective. Stop when the tutorial asks you to go to the till.
Expected: The game shows the first-customer prompt telling you to go to the till.

## TC-02: Walk to the till [human]
Fresh start: no
Steps:
1. Press and drag the on-screen joystick to walk into the restaurant and reach the till.
Expected: The character responds to the joystick and reaches the till inside the restaurant.

## TC-03: Check that the tutorial advances [human]
Fresh start: no
Steps:
1. If the tutorial is still asking you to go to the till, move into range and interact with the till if prompted. Check the current objective.
Expected: The go-to-the-till objective clears and the tutorial advances to the next instruction or interaction state.
"""


def _clean(text: str) -> str:
    text = re.sub(r"[`*_]{1,3}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_cases(text: str) -> Dict[str, Any]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    inputs: Dict[str, str] = {}
    cases: List[Dict[str, Any]] = []
    section = ""
    current: Dict[str, Any] = {}
    field_name = ""

    def flush() -> None:
        if current and (current.get("steps") or current.get("expected")):
            cases.append(dict(current))

    for raw in lines:
        heading = HEADING.match(raw)
        if heading:
            title = _clean(heading.group(1))
            match = CASE_HEAD.match(title)
            if match:
                flush()
                ident = match.group("id") or f"TC-{int(match.group('num')):02d}"
                name = match.group("title") or match.group("title2") or ""
                human = bool(HUMAN_WORDS.search(name))
                current = {"id": re.sub(r"[ _]", "-", ident.upper()), "title": _clean(HUMAN_WORDS.sub("", name)) or ident,
                           "steps": [], "expected": "", "mode": "human" if human else "auto",
                           "preconditions": "", "fresh": True}
                field_name, section = "steps", ""
            else:
                flush()
                current, field_name = {}, ""
                section = title.lower()
            continue
        if not raw.strip():
            continue
        if not current and section in INPUT_SECTIONS:
            kv = KV.match(raw)
            if kv:
                inputs[_clean(kv.group(1)).lower().replace(" ", "_")] = _clean(kv.group(2))
            continue
        if not current:
            continue
        field = FIELD.match(raw)
        if field:
            key, value = field.group(1).lower(), _clean(field.group(2))
            if key.startswith("step"):
                field_name = "steps"
                if value:
                    current["steps"].append(value)
            elif key.startswith(("expected", "result")):
                field_name = "expected"
                current["expected"] = value
            elif key in ("mode", "type"):
                current["mode"] = "human" if re.search(r"human|manual|person", value, re.I) else "auto"
                field_name = ""
            elif key.startswith(("fresh", "restart")):
                current["fresh"] = not re.match(r"\s*(no|false|0)", value, re.I)
                field_name = ""
            else:
                current["preconditions"] = value
                field_name = "preconditions"
            continue
        item = LIST_ITEM.match(raw)
        text_line = _clean(item.group(1) if item else raw)
        if field_name == "expected":
            current["expected"] = (current["expected"] + " " + text_line).strip()
        elif field_name == "preconditions":
            current["preconditions"] = (current["preconditions"] + " " + text_line).strip()
        elif item or field_name == "steps":
            current["steps"].append(text_line)
    flush()

    for index, case in enumerate(cases, 1):
        case.setdefault("id", f"TC-{index:02d}")
        case["steps"] = [s for s in case["steps"] if s][:40]
        case["human_steps"] = [i for i, s in enumerate(case["steps"]) if HUMAN_WORDS.search(s)]
        case["steps"] = [_clean(HUMAN_WORDS.sub("", s)) for s in case["steps"]]
    seen: Dict[str, int] = {}
    for case in cases:  # make ids unique
        n = seen.get(case["id"], 0)
        seen[case["id"]] = n + 1
        if n:
            case["id"] = f"{case['id']}-{n + 1}"

    needed = []
    for case in cases:
        for chunk in case["steps"] + [case["expected"], case.get("preconditions", "")]:
            for a, b in PLACEHOLDER.findall(chunk):
                name = (a or b).lower()
                if name not in needed:
                    needed.append(name)
    return {
        "cases": cases,
        "inputs": inputs,
        "required_inputs": needed,
        "missing_inputs": [n for n in needed if not inputs.get(n)],
        "warnings": [f"{c['id']} has no expected result – a person will be asked to judge it"
                     for c in cases if not c["expected"]],
    }


def first_customer_guide(package: str) -> Dict[str, Any]:
    if package == FIRST_CUSTOMER_PACKAGE:
        return {"name": "First-customer tutorial", "objective": FIRST_CUSTOMER_OBJECTIVE,
                **parse_cases(FIRST_CUSTOMER_WALKTHROUGH)}
    return {}


def fill(text: str, inputs: Dict[str, str]) -> str:
    """Replace {name} / <name> with the tester's values (unknown ones are left as-is)."""
    def sub(match: "re.Match[str]") -> str:
        name = (match.group(1) or match.group(2)).lower()
        return inputs.get(name, match.group(0))
    return PLACEHOLDER.sub(sub, text or "")
