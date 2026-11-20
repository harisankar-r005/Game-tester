"""Requirement intelligence: turn an uploaded game spec into structured requirements.

Supported inputs (no mandatory third-party packages):

* ``.md`` / ``.markdown`` / ``.txt`` - parsed directly;
* ``.docx`` - a DOCX is a zip of XML, so ``word/document.xml`` is read with the stdlib;
* ``.pdf`` - only when :mod:`pypdf` or the ``pdftotext`` binary is available, otherwise
  the upload is rejected with an explanation instead of silently producing nothing.

The document is treated as *untrusted data*: it is parsed, never executed, and any
markup is stripped before a requirement reaches a prompt or a report.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_REQUIREMENTS = 2000

FEATURES = (
    "navigation",
    "gameplay",
    "levels",
    "economy",
    "ads",
    "iap",
    "stability",
    "performance",
    "ui",
    "other",
)

PRIORITIES = ("P0", "P1", "P2")

#: requirement statuses, in order of usefulness for the tester
REQUIREMENT_STATUSES = ("READY", "NEEDS_CLARIFICATION", "NOT_TESTABLE")

FEATURE_KEYWORDS: dict = {
    "navigation": (
        "menu", "button", "screen", "navigation", "back", "pause", "resume", "settings",
        "launch", "loading", "home", "exit", "restart", "background", "foreground",
        "renavigate", "transition", "popup", "dialog",
    ),
    "gameplay": (
        "player", "character", "move", "movement", "control", "jump", "shoot", "collision",
        "obstacle", "collect", "power-up", "powerup", "booster", "score", "distance", "timer",
        "gameplay", "objective", "win", "lose", "game over", "revive", "combo", "skill",
    ),
    "levels": (
        "level", "stage", "chapter", "unlock", "progression", "progress", "difficulty",
        "next level", "replay", "map",
    ),
    "economy": (
        "coin", "gem", "diamond", "cash", "currency", "balance", "wallet", "price", "cost",
        "reward", "purchase", "spend", "earn", "economy", "shop item", "upgrade",
    ),
    "ads": (
        "ad", "ads", "advert", "interstitial", "rewarded", "banner", "advertisement",
        "app open", "no ads", "impression", "fill rate", "ad network", "admob", "ironsource",
        "applovin", "unity ads",
    ),
    "iap": (
        "iap", "in-app purchase", "purchase", "billing", "subscription", "product id",
        "sku", "restore purchase", "entitlement", "sandbox", "google play billing",
        "coin pack", "gem pack", "bundle", "vip",
    ),
    "stability": (
        "crash", "anr", "not responding", "freeze", "black screen", "memory leak", "oom",
        "low memory", "restart loop", "stability", "robust", "no crash",
    ),
    "performance": (
        "fps", "frame", "jank", "lag", "performance", "memory", "ram", "cpu", "battery",
        "load time", "loading time", "startup time", "smooth", "60fps", "30fps",
    ),
    "ui": (
        "ui", "layout", "text", "font", "icon", "colour", "color", "resolution", "localization",
        "tooltip", "hud", "responsive", "safe area", "keyboard",
    ),
}

CLARITY_MARKERS = (
    "tbd", "tbc", "to be defined", "to be decided", "???", "etc.", "etc",
    "various", "appropriate", "reasonable", "user-friendly", "user friendly",
    "easy to use", "intuitive", "as needed", "some",
    "maybe", "possibly", "nice to have", "similar", "and so on",
)

NON_TESTABLE_MARKERS = (
    "backend", "server-side", "server side", "admin panel", "cms", "analytics dashboard",
    "database migration", "deployment", "third-party policy", "app store review",
    "marketing", "legal", "privacy policy", "terms of service",
)

OBSERVABLE_VERBS = (
    "show", "shows", "display", "displays", "open", "opens", "close", "closes", "increase",
    "decrease", "award", "awards", "grant", "grants", "unlock", "unlocks", "play", "plays",
    "start", "starts", "stop", "stops", "appear", "appears", "return", "returns", "resume",
    "resumes", "pause", "pauses", "enable", "enables", "disable", "disables", "trigger",
    "triggers", "redirect", "navigate", "loads", "load", "save", "saves", "persist",
    "persists", "remain", "remains", "must", "shall", "should",
)

EXPLICIT_ID_RE = re.compile(
    r"^(?P<id>(?:REQ|FR|AC|REQ-ID|TC)[-_ ]?\d+(?:\.\d+)*)\s*[:.)-]?\s*", re.IGNORECASE
)
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
MD_NOISE_RE = re.compile(
    r"(!\[[^\]]*\]\([^)]*\))|(\[[^\]]*\]\([^)]*\))|(https?://\S+)|(<[^>]+>)|(`{1,3})"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TOC_LINE_RE = re.compile(r"^\s*[-*]?\s*\[[^\]]*\]\(#[^)]*\)\s*$|\.{3,}\s*\d+\s*$")


class RequirementError(ValueError):
    """Raised when a document cannot be turned into text."""


@dataclass
class Requirement:
    id: str
    text: str
    feature: str = "other"
    priority: str = "P1"
    status: str = "READY"
    note: str = ""
    source: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    name: str
    kind: str
    text: str
    requirements: List[Requirement] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)

    def to_dict(self, with_text: bool = True) -> dict:
        payload = {
            "name": self.name,
            "kind": self.kind,
            "requirements": [req.to_dict() for req in self.requirements],
            "warnings": list(self.warnings),
            "sections": list(self.sections),
            "counts": count_by(self.requirements),
        }
        if with_text:
            payload["text"] = self.text
        return payload


def count_by(requirements: Sequence[Requirement]) -> dict:
    counts = {feature: 0 for feature in FEATURES}
    statuses = {status: 0 for status in REQUIREMENT_STATUSES}
    priorities = {priority: 0 for priority in PRIORITIES}
    for requirement in requirements:
        counts[requirement.feature] = counts.get(requirement.feature, 0) + 1
        statuses[requirement.status] = statuses.get(requirement.status, 0) + 1
        priorities[requirement.priority] = priorities.get(requirement.priority, 0) + 1
    return {
        "total": len(requirements),
        "features": {key: value for key, value in counts.items() if value},
        "statuses": statuses,
        "priorities": priorities,
    }


# -- text extraction -------------------------------------------------------
def extract_text(filename: str, payload: bytes) -> Tuple[str, str]:
    """Return ``(kind, text)`` for a supported upload, raising RequirementError."""
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise RequirementError("document is larger than 8 MB")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in (".md", ".markdown", ".txt", ""):
        return ("markdown" if suffix != ".txt" else "text"), _decode(payload)
    if suffix == ".docx":
        return "docx", _docx_text(payload)
    if suffix == ".pdf":
        return "pdf", _pdf_text(payload)
    raise RequirementError(f"unsupported document type {suffix or '(none)'}; use .md, .txt, .docx or .pdf")


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RequirementError("document is not valid UTF-8 text")


def _docx_text(payload: bytes) -> str:
    """A DOCX is a zip; the body text lives in word/document.xml."""
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise RequirementError("not a valid .docx file") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise RequirementError("corrupt DOCX document body") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: List[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        chunks = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        if chunks:
            lines.append("".join(chunks))
    return "\n".join(lines)


def _pdf_text(payload: bytes) -> str:
    try:  # optional dependency
        from pypdf import PdfReader  # type: ignore
    except Exception:
        PdfReader = None  # type: ignore
    if PdfReader is not None:
        import io

        try:
            reader = PdfReader(io.BytesIO(payload))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # pragma: no cover - depends on the PDF
            raise RequirementError(f"could not read the PDF: {exc}") from exc
    raise RequirementError(
        "PDF text extraction needs the optional 'pypdf' package (pip install pypdf); "
        "upload .md, .txt or .docx instead"
    )


# -- parsing ---------------------------------------------------------------
def _strip_markdown(line: str) -> str:
    text = MD_NOISE_RE.sub(" ", line)
    text = re.sub(r"[*_~]{1,3}", "", text)
    return re.sub(r"\s+", " ", text).strip(" \t|")


def _is_requirement_ish(section: str) -> bool:
    """Section titles that make plain paragraphs count as requirement statements.

    Deliberately narrow: "features" or "test" alone would turn prose notes into
    requirements, which is exactly the kind of invented coverage to avoid.
    """
    lowered = section.lower()
    return any(
        phrase in lowered
        for phrase in ("requirement", "acceptance", "criteria", "specification", "functional spec")
    )


def _classify_feature(text: str) -> str:
    lowered = text.lower()
    scores = {}
    for feature, keywords in FEATURE_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in lowered:
                # longer phrases are stronger signals
                score += 3 if len(keyword) > 6 else 1
        if score:
            scores[feature] = score
    if not scores:
        return "other"
    best = max(scores.values())
    # prefer a domain feature over generic ui/other on ties
    for feature in ("economy", "ads", "iap", "levels", "gameplay", "navigation",
                    "stability", "performance", "ui"):
        if scores.get(feature) == best:
            return feature
    return "other"


def _priority(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("must", "shall", "required", "critical", "mandatory")):
        return "P0"
    if any(word in lowered for word in ("should", "expected", "important")):
        return "P1"
    if any(word in lowered for word in ("may", "could", "optional", "nice to have")):
        return "P2"
    return "P1"


def _assess(text: str) -> Tuple[str, str]:
    """Return ``(status, note)`` for one requirement statement."""
    lowered = text.lower()
    for marker in NON_TESTABLE_MARKERS:
        if marker in lowered:
            return "NOT_TESTABLE", (
                f"mentions '{marker}', which cannot be verified by black-box UI testing"
            )
    words = re.findall(r"[A-Za-z]{2,}", text)
    if len(words) < 5:
        return "NEEDS_CLARIFICATION", "too short to define an observable behaviour"
    if "?" in text:
        return "NEEDS_CLARIFICATION", "the document itself asks a question here"
    for marker in CLARITY_MARKERS:
        if marker in lowered:
            return "NEEDS_CLARIFICATION", f"vague wording ('{marker}'); needs a measurable criterion"
    if not any(verb in lowered for verb in OBSERVABLE_VERBS):
        return "NEEDS_CLARIFICATION", "no observable verb (shows/opens/grants/...) found"
    return "READY", ""


def parse_requirements(text: str, document_name: str = "") -> List[Requirement]:
    """Extract requirement statements from Markdown-ish text.

    Rules, deliberately conservative: only list items, numbered items, table rows and
    paragraphs under a requirement-ish heading become requirements. Nothing is invented,
    and prose that does not look like a requirement is ignored.
    """
    requirements: List[Requirement] = []
    section_path: List[str] = []
    in_code = False
    used_ids: set = set()
    counter = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if CODE_FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code or not line.strip():
            continue
        if TOC_LINE_RE.match(line):
            continue
        if line.lstrip().startswith(">"):
            # blockquotes are editorial notes, not requirements
            continue
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            section_path = section_path[: level - 1]
            while len(section_path) < level - 1:
                section_path.append("")
            section_path.append(_strip_markdown(heading.group(2)))
            continue
        if line.strip().startswith(("|", "+-", "---")):
            table = TABLE_ROW_RE.match(line)
            if not table:
                continue
            cells = [cell.strip() for cell in table.group(1).split("|")]
            cells = [cell for cell in cells if cell and not re.fullmatch(r":?-{2,}:?", cell)]
            if len(cells) < 2:
                continue
            joined = " — ".join(cells)
            if joined.lower().startswith(("requirement", "id ", "no.", "test case")):
                continue
            candidate = joined
        elif LIST_MARKER_RE.match(line):
            candidate = LIST_MARKER_RE.sub("", line)
        elif _is_requirement_ish(" ".join(section_path)):
            candidate = line
        else:
            continue

        cleaned = _strip_markdown(candidate)
        if len(cleaned) < 8:
            continue
        explicit = EXPLICIT_ID_RE.match(cleaned)
        if explicit:
            requirement_id = explicit.group("id").replace(" ", "-").upper()
            cleaned = cleaned[explicit.end():].strip()
            if not cleaned:
                continue
        else:
            counter += 1
            requirement_id = f"REQ-{counter:03d}"
        while requirement_id in used_ids:
            counter += 1
            requirement_id = f"REQ-{counter:03d}"
        used_ids.add(requirement_id)

        status, note = _assess(cleaned)
        requirements.append(
            Requirement(
                id=requirement_id,
                text=cleaned[:1200],
                feature=_classify_feature(cleaned),
                priority=_priority(cleaned),
                status=status,
                note=note,
                source=" > ".join(part for part in section_path if part),
                line=number,
            )
        )
        if len(requirements) >= MAX_REQUIREMENTS:
            break
    return requirements


def parse_document(filename: str, payload: bytes) -> Document:
    kind, text = extract_text(filename, payload)
    if not text.strip():
        raise RequirementError("the document contains no readable text")
    requirements = parse_requirements(text, filename)
    warnings: List[str] = []
    if not requirements:
        warnings.append(
            "no requirement statements found — use bullet points, numbered steps or a "
            "'Requirements' section"
        )
    unclear = sum(1 for req in requirements if req.status != "READY")
    if unclear:
        warnings.append(f"{unclear} requirement(s) need clarification or cannot be automated")
    sections = sorted({req.source for req in requirements if req.source})
    return Document(
        name=filename,
        kind=kind,
        text=text,
        requirements=requirements,
        warnings=warnings,
        sections=sections,
    )


def feature_summary(requirements: Iterable[Requirement]) -> List[dict]:
    """Feature-wise rollup used by the dashboard."""
    buckets: dict = {}
    for requirement in requirements:
        bucket = buckets.setdefault(
            requirement.feature, {"feature": requirement.feature, "total": 0, "ready": 0,
                                  "blocked": 0}
        )
        bucket["total"] += 1
        if requirement.status == "READY":
            bucket["ready"] += 1
        else:
            bucket["blocked"] += 1
    return sorted(buckets.values(), key=lambda item: (-item["total"], item["feature"]))
