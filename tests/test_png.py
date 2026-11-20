"""PNG codec and perceptual hash tests."""

import unittest

from apkharness import png

SOLID_RED = bytes([255, 0, 0, 255]) * (9 * 8)


class PNGTests(unittest.TestCase):
    def test_roundtrip_rgba(self):
        pixels = bytearray()
        for y in range(6):
            for x in range(5):
                pixels += bytes([x * 40 % 256, y * 40 % 256, 100, 255])
        encoded = png.encode_rgba(5, 6, bytes(pixels))
        self.assertTrue(encoded.startswith(png.PNG_SIGNATURE))
        raster = png.decode(encoded)
        self.assertEqual((raster.width, raster.height), (5, 6))
        self.assertEqual(raster.rgba, bytes(pixels))

    def test_decode_rgb_source(self):
        import struct
        import zlib

        width, height = 2, 2
        raw = b"".join(b"\x00" + bytes([10, 20, 30]) * width for _ in range(height))
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(tag, payload):
            return (
                struct.pack(">I", len(payload))
                + tag
                + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
            )

        data = (
            png.PNG_SIGNATURE
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )
        raster = png.decode(data)
        self.assertEqual(raster.pixel(0, 0), (10, 20, 30, 255))

    def test_rejects_garbage(self):
        with self.assertRaises(png.PNGError):
            png.decode(b"not a png")
        with self.assertRaises(png.PNGError):
            png.decode(png.PNG_SIGNATURE + b"\x00" * 10)

    def test_hash_is_stable_for_same_image(self):
        first = png.perceptual_hash(png.decode(png.encode_rgba(9, 8, SOLID_RED)))
        second = png.perceptual_hash(png.decode(png.encode_rgba(9, 8, SOLID_RED)))
        self.assertEqual(first, second)

    def test_hash_changes_with_layout(self):
        def checker(flip: bool) -> bytes:
            buffer = bytearray()
            for y in range(32):
                for x in range(32):
                    light = ((x // 8) + (y // 8) + (1 if flip and x > 16 else 0)) % 2 == 0
                    value = 240 if light else 20
                    buffer += bytes([value, value, value, 255])
            return bytes(buffer)

        a = png.perceptual_hash(png.decode(png.encode_rgba(32, 32, checker(False))))
        b = png.perceptual_hash(png.decode(png.encode_rgba(32, 32, checker(True))))
        self.assertGreater(png.hamming(a, b), 0)

    def test_hash_from_invalid_bytes(self):
        self.assertIsNone(png.hash_from_bytes(b"nope"))


if __name__ == "__main__":
    unittest.main()
