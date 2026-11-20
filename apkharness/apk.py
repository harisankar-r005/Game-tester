"""Offline APK inspection: read the binary AndroidManifest.xml without aapt.

The harness needs the package name and the launcher activity before it can drive
an app. Installing the APK and diffing ``pm list packages`` works, but that needs
a device and a round trip; parsing the manifest is instant and works on any
machine:

    >>> info = inspect_apk("game.apk")
    >>> info.package, info.launch_activity
    ('com.example.game', 'com.example.game/.MainActivity')

The binary XML ("AXML") reader below only understands the subset Android uses in
``AndroidManifest.xml``: a string pool, a resource map and element start/end
chunks with typed attribute values.
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

AXML_MAGIC = 0x0003
CHUNK_STRING_POOL = 0x0001
CHUNK_RESOURCE_MAP = 0x0180
CHUNK_START_ELEMENT = 0x0102
CHUNK_END_ELEMENT = 0x0103
CHUNK_CDATA = 0x0104

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_BOOLEAN = 0x12

NO_ENTRY = 0xFFFFFFFF

MAIN_ACTION = "android.intent.action.MAIN"
LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"


class ApkError(ValueError):
    """Raised when an APK or its manifest cannot be read."""


@dataclass
class XmlNode:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List["XmlNode"] = field(default_factory=list)

    def find_all(self, tag: str) -> List["XmlNode"]:
        return [child for child in self.children if child.tag == tag]

    def iter(self) -> Iterable["XmlNode"]:
        yield self
        for child in self.children:
            yield from child.iter()


@dataclass
class ApkInfo:
    path: str = ""
    package: str = ""
    version_name: str = ""
    version_code: str = ""
    launch_activity: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    permissions: List[str] = field(default_factory=list)
    abis: List[str] = field(default_factory=list)
    size_bytes: int = 0
    sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "package": self.package,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "launch_activity": self.launch_activity,
            "min_sdk": self.min_sdk,
            "target_sdk": self.target_sdk,
            "permissions": list(self.permissions),
            "abis": list(self.abis),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


# -- binary XML ------------------------------------------------------------
def _decode_utf8_length(data: bytes, pos: int) -> tuple:
    """UTF-8 pool strings store two lengths, each 1 or 2 bytes (high bit = long)."""
    first = data[pos]
    if first & 0x80:
        if pos + 1 >= len(data):
            return 0, pos + 1
        return ((first & 0x7F) << 8) | data[pos + 1], pos + 2
    return first, pos + 1


def _decode_utf16_length(data: bytes, pos: int) -> tuple:
    """UTF-16 pool strings store one 16-bit length (32-bit when bit 15 is set)."""
    if pos + 2 > len(data):
        return 0, pos
    (first,) = struct.unpack_from("<H", data, pos)
    if first & 0x8000:
        if pos + 4 > len(data):
            return first & 0x7FFF, pos + 2
        (second,) = struct.unpack_from("<H", data, pos + 2)
        return ((first & 0x7FFF) << 16) | second, pos + 4
    return first, pos + 2


def parse_string_pool(data: bytes, offset: int) -> List[str]:
    """Decode an AXML string pool chunk located at ``offset``."""
    try:
        _type, header_size, _size = struct.unpack_from("<HHI", data, offset)
        string_count, _style_count, flags, strings_start, _styles_start = struct.unpack_from(
            "<IIIII", data, offset + 8
        )
    except struct.error as exc:
        raise ApkError(f"truncated string pool: {exc}") from exc

    utf8 = bool(flags & 0x100)
    offsets_at = offset + header_size
    base = offset + strings_start
    strings: List[str] = []
    for index in range(string_count):
        try:
            (string_offset,) = struct.unpack_from("<I", data, offsets_at + index * 4)
        except struct.error as exc:
            raise ApkError(f"truncated string offset table: {exc}") from exc
        pos = base + string_offset
        if pos >= len(data):
            strings.append("")
            continue
        if utf8:
            _chars, pos = _decode_utf8_length(data, pos)
            byte_len, pos = _decode_utf8_length(data, pos)
            raw = data[pos : pos + byte_len]
            strings.append(raw.decode("utf-8", "replace"))
        else:
            char_len, pos = _decode_utf16_length(data, pos)
            raw = data[pos : pos + char_len * 2]
            strings.append(raw.decode("utf-16-le", "replace"))
    return strings


def _typed_value(data: bytes, pos: int, strings: List[str]) -> str:
    """Resolve one attribute value: raw string index or typed scalar."""
    try:
        ns, name, raw_value, size, _res0, data_type, value = struct.unpack_from("<IIIHBBI", data, pos)
    except struct.error:
        return ""
    del ns, name, size
    if raw_value != NO_ENTRY and raw_value < len(strings):
        return strings[raw_value]
    if data_type == TYPE_STRING:
        return strings[value] if value < len(strings) else ""
    if data_type == TYPE_BOOLEAN:
        return "true" if value else "false"
    if data_type in (TYPE_INT_DEC, TYPE_INT_HEX):
        return str(value)
    if data_type == TYPE_REFERENCE:
        return f"@{value:#010x}"
    return ""


def parse_axml(data: bytes) -> XmlNode:
    """Parse binary Android XML into a tree; returns a synthetic root node."""
    if len(data) < 8:
        raise ApkError("manifest is too short")
    (chunk_type,) = struct.unpack_from("<H", data, 0)
    if chunk_type != AXML_MAGIC:
        raise ApkError("not a binary Android XML document")

    strings: List[str] = []
    root = XmlNode(tag="#document")
    stack: List[XmlNode] = [root]
    pos = 8  # skip the XML file header

    while pos + 8 <= len(data):
        try:
            kind, header_size, size = struct.unpack_from("<HHI", data, pos)
        except struct.error:
            break
        if size <= 0 or pos + size > len(data):
            break
        if kind == CHUNK_STRING_POOL:
            strings = parse_string_pool(data, pos)
        elif kind == CHUNK_START_ELEMENT:
            try:
                _line, _comment, _ns, name_index = struct.unpack_from("<IIII", data, pos + 8)
                attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, pos + 24)
            except struct.error:
                break
            tag = strings[name_index] if name_index < len(strings) else ""
            node = XmlNode(tag=tag)
            # attributeStart is relative to the start of ResXMLTree_attrExt, which
            # itself begins right after the node header.
            attr_pos = pos + header_size + attr_start
            for _ in range(attr_count):
                try:
                    (_ns_ref, name_ref) = struct.unpack_from("<II", data, attr_pos)
                except struct.error:
                    break
                attr_name = strings[name_ref] if name_ref < len(strings) else ""
                node.attrs[attr_name] = _typed_value(data, attr_pos, strings)
                attr_pos += attr_size or 20
            stack[-1].children.append(node)
            stack.append(node)
        elif kind == CHUNK_END_ELEMENT:
            if len(stack) > 1:
                stack.pop()
        elif kind in (CHUNK_RESOURCE_MAP, CHUNK_CDATA):
            pass
        pos += size
    return root


# -- manifest interpretation ------------------------------------------------
def _is_launcher(activity: XmlNode) -> bool:
    for intent_filter in activity.find_all("intent-filter"):
        actions = {node.attrs.get("name", "") for node in intent_filter.find_all("action")}
        categories = {node.attrs.get("name", "") for node in intent_filter.find_all("category")}
        if MAIN_ACTION in actions and LAUNCHER_CATEGORY in categories:
            return True
    return False


def _full_activity_name(package: str, name: str) -> str:
    if not name:
        return ""
    if name.startswith("."):
        return f"{package}/{package}{name}"
    if "." not in name:
        return f"{package}/{package}.{name}"
    return f"{package}/{name}"


def manifest_info(manifest: bytes, package_hint: str = "") -> Dict[str, object]:
    """Extract the fields the harness cares about from a binary manifest."""
    document = parse_axml(manifest)
    manifests = document.find_all("manifest")
    if not manifests:
        raise ApkError("no <manifest> element found")
    root = manifests[0]
    package = root.attrs.get("package", "") or package_hint

    info: Dict[str, object] = {
        "package": package,
        "version_name": root.attrs.get("versionName", ""),
        "version_code": root.attrs.get("versionCode", ""),
        "min_sdk": "",
        "target_sdk": "",
        "launch_activity": "",
        "permissions": [],
    }

    for uses_sdk in root.find_all("uses-sdk"):
        info["min_sdk"] = uses_sdk.attrs.get("minSdkVersion", "") or info["min_sdk"]
        info["target_sdk"] = uses_sdk.attrs.get("targetSdkVersion", "") or info["target_sdk"]

    permissions = []
    for node in root.iter():
        if node.tag in ("uses-permission", "uses-permission-sdk-23"):
            permission = node.attrs.get("name", "")
            if permission:
                permissions.append(permission)
    info["permissions"] = sorted(set(permissions))

    for application in root.find_all("application"):
        candidates = application.find_all("activity") + application.find_all("activity-alias")
        for activity in candidates:
            if _is_launcher(activity):
                info["launch_activity"] = _full_activity_name(package, activity.attrs.get("name", ""))
                break
        if info["launch_activity"]:
            break
    return info


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_apk(path: str, with_hash: bool = True) -> ApkInfo:
    """Read package, version, launcher activity, ABIs and hash from an APK."""
    info = ApkInfo(path=path)
    try:
        info.size_bytes = __import__("os").path.getsize(path)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "AndroidManifest.xml" not in names:
                raise ApkError("APK has no AndroidManifest.xml")
            manifest = archive.read("AndroidManifest.xml")
            info.abis = sorted({name.split("/")[1] for name in names if name.startswith("lib/") and name.count("/") > 1})
    except FileNotFoundError as exc:
        raise ApkError(f"APK not found: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise ApkError(f"not a valid APK/zip: {path}") from exc

    fields = manifest_info(manifest, package_hint="")
    info.package = str(fields["package"])
    info.version_name = str(fields["version_name"])
    info.version_code = str(fields["version_code"])
    info.launch_activity = str(fields["launch_activity"])
    info.min_sdk = str(fields["min_sdk"])
    info.target_sdk = str(fields["target_sdk"])
    info.permissions = list(fields["permissions"])  # type: ignore[arg-type]
    if with_hash:
        info.sha256 = file_sha256(path)
    return info
