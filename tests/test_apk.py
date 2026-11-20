"""Tests for offline APK / binary AndroidManifest parsing."""

import os
import struct
import unittest
import zipfile

from apkharness.apk import (
    ApkError,
    inspect_apk,
    manifest_info,
    parse_axml,
    parse_string_pool,
)

#: Optional real-world APK for a full end-to-end manifest parse.
REAL_APK = os.environ.get("APKHARNESS_TEST_APK", "")

NO_ENTRY = 0xFFFFFFFF
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10


def _pool(strings, utf8=False) -> bytes:
    """Build a minimal AXML string pool chunk."""
    offsets = []
    blob = bytearray()
    for text in strings:
        offsets.append(len(blob))
        if utf8:
            raw = text.encode("utf-8")
            blob += bytes([len(text), len(raw)]) + raw + b"\x00"
        else:
            raw = text.encode("utf-16-le")
            blob += struct.pack("<H", len(text)) + raw + b"\x00\x00"
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    body = b"".join(struct.pack("<I", off) for off in offsets) + bytes(blob)
    size = strings_start + len(blob)
    flags = 0x100 if utf8 else 0x0
    return (
        struct.pack("<HHI", 0x0001, header_size, size)
        + struct.pack("<IIIII", len(strings), 0, flags, strings_start, 0)
        + body
    )


def _start_element(name_index, attrs, utf8=False) -> bytes:
    """Build a start-element chunk; ``attrs`` are (name_index, value_index) or (name, value) tuples."""
    attr_size = 20
    attributes = b""
    for attr in attrs:
        name_idx, value_idx = attr
        if isinstance(value_idx, str):
            raise TypeError("use string indexes")
        attributes += struct.pack("<IIIHBBI", NO_ENTRY, name_idx, value_idx, 8, 0, TYPE_STRING, value_idx)
    header_size = 16
    attr_start = 20
    size = header_size + attr_start + len(attributes)
    return (
        struct.pack("<HHI", 0x0102, header_size, size)
        + struct.pack("<IIII", 1, NO_ENTRY, NO_ENTRY, name_index)
        + struct.pack("<HHHHHH", attr_start, attr_size, len(attrs), 0, 0, 0)
        + attributes
    )


def _end_element() -> bytes:
    return struct.pack("<HHIIIII", 0x0103, 16, 24, 1, NO_ENTRY, NO_ENTRY, NO_ENTRY)


def _document(strings, elements, utf8=False) -> bytes:
    pool = _pool(strings, utf8=utf8)
    body = pool + b"".join(elements)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def build_manifest(package="com.example.game", version_name="1.2.3", activity=".MainActivity",
                   utf8=False) -> bytes:
    strings = [
        "package", package, "versionName", version_name, "versionCode", "42",
        "manifest", "application", "activity", "name", activity,
        "intent-filter", "action", "category",
        "android.intent.action.MAIN", "android.intent.category.LAUNCHER",
        "uses-permission", "android.permission.INTERNET",
    ]
    idx = {value: i for i, value in enumerate(strings)}
    elements = [
        _start_element(idx["manifest"], [
            (idx["package"], idx[package]),
            (idx["versionName"], idx[version_name]),
            (idx["versionCode"], idx["42"]),
        ]),
        _start_element(idx["uses-permission"], [(idx["name"], idx["android.permission.INTERNET"])]),
        _end_element(),
        _start_element(idx["application"], []),
        _start_element(idx["activity"], [(idx["name"], idx[activity])]),
        _start_element(idx["intent-filter"], []),
        _start_element(idx["action"], [(idx["name"], idx["android.intent.action.MAIN"])]),
        _end_element(),
        _start_element(idx["category"], [(idx["name"], idx["android.intent.category.LAUNCHER"])]),
        _end_element(),
        _end_element(),
        _end_element(),
        _end_element(),
        _end_element(),
        _end_element(),
    ]
    return _document(strings, elements, utf8=utf8)


class StringPoolTests(unittest.TestCase):
    def test_utf16_pool(self):
        data = _pool(["alpha", "beta", "com.example"])
        strings = parse_string_pool(data, 0)
        self.assertEqual(strings, ["alpha", "beta", "com.example"])

    def test_utf8_pool(self):
        data = _pool(["alpha", "beta", "héllo"], utf8=True)
        strings = parse_string_pool(data, 0)
        self.assertEqual(strings, ["alpha", "beta", "héllo"])

    def test_empty_string(self):
        data = _pool(["", "x"])
        self.assertEqual(parse_string_pool(data, 0), ["", "x"])

    def test_truncated_pool(self):
        with self.assertRaises(ApkError):
            parse_string_pool(b"\x01\x00", 0)


class ManifestTests(unittest.TestCase):
    def test_parse_manifest_fields(self):
        info = manifest_info(build_manifest())
        self.assertEqual(info["package"], "com.example.game")
        self.assertEqual(info["version_name"], "1.2.3")
        self.assertEqual(info["version_code"], "42")
        self.assertEqual(info["launch_activity"], "com.example.game/com.example.game.MainActivity")
        self.assertEqual(info["permissions"], ["android.permission.INTERNET"])

    def test_utf8_manifest(self):
        info = manifest_info(build_manifest(utf8=True))
        self.assertEqual(info["package"], "com.example.game")

    def test_relative_activity_name(self):
        info = manifest_info(build_manifest(activity=".ui.Splash"))
        self.assertEqual(info["launch_activity"], "com.example.game/com.example.game.ui.Splash")

    def test_no_launcher_activity(self):
        strings = ["manifest", "package", "com.example.game"]
        elements = [
            _start_element(0, [(1, 2)]),
            _end_element(),
        ]
        info = manifest_info(_document(strings, elements))
        self.assertEqual(info["launch_activity"], "")

    def test_tree_shape(self):
        root = parse_axml(build_manifest())
        manifest = root.find_all("manifest")[0]
        self.assertEqual(manifest.attrs["package"], "com.example.game")
        self.assertEqual(len(manifest.find_all("uses-permission")), 1)

    def test_rejects_non_axml(self):
        with self.assertRaises(ApkError):
            parse_axml(b"<?xml version='1.0'?><manifest/>")
        with self.assertRaises(ApkError):
            parse_axml(b"")


class InspectApkTests(unittest.TestCase):
    def _write_apk(self, path: str, manifest: bytes, extra=("lib/arm64-v8a/libunity.so",)) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AndroidManifest.xml", manifest)
            for name in extra:
                archive.writestr(name, b"\x00" * 16)

    def test_inspect_synthetic_apk(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "synthetic.apk")
        self._write_apk(path, build_manifest(package="com.acme.runner"))
        try:
            info = inspect_apk(path)
        finally:
            os.remove(path)
        self.assertEqual(info.package, "com.acme.runner")
        self.assertEqual(info.version_name, "1.2.3")
        self.assertIn("arm64-v8a", info.abis)
        self.assertEqual(len(info.sha256), 64)

    def test_not_a_zip(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "broken.apk")
        with open(path, "wb") as handle:
            handle.write(b"not a zip")
        try:
            with self.assertRaises(ApkError):
                inspect_apk(path)
        finally:
            os.remove(path)

    def test_missing_manifest(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "empty.apk")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("classes.dex", b"x")
        try:
            with self.assertRaises(ApkError):
                inspect_apk(path)
        finally:
            os.remove(path)

    @unittest.skipUnless(os.path.exists(REAL_APK), "real APK fixture not available")
    def test_real_apk(self):
        info = inspect_apk(REAL_APK, with_hash=False)
        self.assertEqual(info.package, "com.woolfun.wool.yarn.puzzle.game")
        self.assertTrue(info.version_name)
        self.assertIn("/", info.launch_activity)


if __name__ == "__main__":
    unittest.main()
