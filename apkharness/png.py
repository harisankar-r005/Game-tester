"""Minimal PNG encode/decode plus a perceptual hash, standard library only.

``perceptual_hash`` is what lets the harness decide "this is a new screen" on a
game, where the accessibility tree is usually empty and frame-by-frame pixel
noise makes exact image hashes useless.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def dimensions(data: Optional[bytes]) -> Optional[Tuple[int, int]]:
    """Read the PNG viewport without decoding the pixels."""
    if data and len(data) >= 33 and data.startswith(PNG_SIGNATURE + b"\x00\x00\x00\x0dIHDR"):
        width, height = struct.unpack_from(">II", data, 16)
        if width and height:
            return width, height
    return None


class PNGError(ValueError):
    """Raised for unsupported or corrupt PNG data."""


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode 8-bit RGBA pixels (row-major, 4 bytes per pixel) as a PNG."""
    expected = width * height * 4
    if len(rgba) != expected:
        raise PNGError(f"expected {expected} bytes of RGBA, got {len(rgba)}")
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)  # filter type: none
        start = row * stride
        raw += rgba[start : start + stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            PNG_SIGNATURE,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
            _chunk(b"IEND", b""),
        ]
    )


@dataclass
class Raster:
    """Decoded image: 8-bit RGBA, row-major."""

    width: int
    height: int
    rgba: bytes

    def pixel(self, x: int, y: int) -> Tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        return (self.rgba[i], self.rgba[i + 1], self.rgba[i + 2], self.rgba[i + 3])

    def to_rgb(self) -> bytes:
        out = bytearray(self.width * self.height * 3)
        for i in range(self.width * self.height):
            src = i * 4
            dst = i * 3
            out[dst : dst + 3] = self.rgba[src : src + 3]
        return bytes(out)


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytes:
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for row in range(height):
        if pos >= len(raw):
            raise PNGError("truncated image data")
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        if len(line) != stride:
            raise PNGError("truncated scanline")
        pos += stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise PNGError(f"unsupported PNG filter type {ftype}")
        out[row * stride : (row + 1) * stride] = line
        prev = line
    return bytes(out)


def decode(data: bytes) -> Raster:
    """Decode an 8-bit non-interlaced PNG (gray, RGB, RGBA or palette)."""
    if not data.startswith(PNG_SIGNATURE):
        raise PNGError("not a PNG (bad signature)")
    pos = len(PNG_SIGNATURE)
    width = height = 0
    bit_depth = 8
    color_type = 6
    interlace = 0
    palette: List[Tuple[int, int, int]] = []
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif tag == b"PLTE":
            for i in range(0, len(payload) - 2, 3):
                palette.append((payload[i], payload[i + 1], payload[i + 2]))
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    if bit_depth != 8:
        raise PNGError(f"unsupported bit depth {bit_depth}")
    if interlace != 0:
        raise PNGError("interlaced PNG is not supported")
    if not width or not height:
        raise PNGError("missing IHDR")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PNGError(f"unsupported color type {color_type}")
    raw = _unfilter(zlib.decompress(bytes(idat)), width, height, channels)

    if color_type == 6:
        return Raster(width, height, raw)
    out = bytearray(width * height * 4)
    for i in range(width * height):
        if color_type == 0:
            v = raw[i]
            rgba = (v, v, v, 255)
        elif color_type == 4:
            v, a = raw[i * 2], raw[i * 2 + 1]
            rgba = (v, v, v, a)
        elif color_type == 2:
            rgba = (raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2], 255)
        else:  # palette
            idx = raw[i]
            if idx >= len(palette):
                raise PNGError("palette index out of range")
            r, g, b = palette[idx]
            rgba = (r, g, b, 255)
        out[i * 4 : i * 4 + 4] = bytes(rgba)
    return Raster(width, height, bytes(out))


def perceptual_hash(raster: Raster, cols: int = 9, rows: int = 8) -> int:
    """64-bit difference hash: bright/dark comparison of neighbouring cells.

    Robust to scaling and small animation noise, sensitive to layout changes,
    which is exactly what "a new screen appeared" means.
    """
    if raster.width < 1 or raster.height < 1:
        return 0
    cells = []
    for row in range(rows):
        y0 = row * raster.height // rows
        y1 = max(y0 + 1, (row + 1) * raster.height // rows)
        line = []
        for col in range(cols):
            x0 = col * raster.width // cols
            x1 = max(x0 + 1, (col + 1) * raster.width // cols)
            total = 0
            count = 0
            step_y = max(1, (y1 - y0) // 4)
            step_x = max(1, (x1 - x0) // 4)
            for y in range(y0, y1, step_y):
                base = y * raster.width * 4
                for x in range(x0, x1, step_x):
                    i = base + x * 4
                    total += (
                        raster.rgba[i] * 299
                        + raster.rgba[i + 1] * 587
                        + raster.rgba[i + 2] * 114
                    ) // 1000
                    count += 1
            line.append(total // max(count, 1))
        cells.append(line)
    bits = 0
    shift = 0
    for row in range(rows):
        for col in range(cols - 1):
            if cells[row][col] > cells[row][col + 1]:
                bits |= 1 << shift
            shift += 1
    return bits


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes."""
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def hash_from_bytes(data: bytes) -> Optional[int]:
    """Perceptual hash of PNG bytes, or ``None`` when decoding fails."""
    try:
        return perceptual_hash(decode(data))
    except (PNGError, zlib.error, struct.error, ValueError):
        return None
