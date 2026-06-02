"""Shared helpers for the golden tests: canonical JSON + EPD buffer diffing."""
import json

from PIL import Image

WIDTH, HEIGHT = 1360, 480
# 2-bit EPD colour codes -> RGB, for turning a buffer back into a viewable image.
_CODE_RGB = {0: (0, 0, 0), 1: (255, 255, 255), 2: (255, 255, 0), 3: (255, 0, 0)}


def canonical_json(obj) -> str:
    """Stable text form of a data dict: sorted keys, UTF-8, tuples -> arrays."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)


def epd_buffer_to_image(buf: bytes) -> Image.Image:
    """Decode a 4-colour EPD buffer (2 bits/pixel) back to an RGB image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    px = img.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            idx = (y * WIDTH + x) // 4
            shift = 6 - (x % 4) * 2
            code = (buf[idx] >> shift) & 0b11
            px[x, y] = _CODE_RGB[code]
    return img


def buffer_diff(actual: bytes, golden: bytes) -> tuple[int, float]:
    """(differing byte count, fraction of the buffer) between two EPD buffers."""
    n = min(len(actual), len(golden))
    diff = sum(1 for i in range(n) if actual[i] != golden[i])
    diff += abs(len(actual) - len(golden))
    return diff, diff / max(len(golden), 1)


def diff_image(actual: bytes, golden: bytes) -> Image.Image:
    """A red-on-white image highlighting pixels that differ between two buffers."""
    a = epd_buffer_to_image(actual)
    g = epd_buffer_to_image(golden)
    out = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    po, pa, pg = out.load(), a.load(), g.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if pa[x, y] != pg[x, y]:
                po[x, y] = (255, 0, 0)
    return out
