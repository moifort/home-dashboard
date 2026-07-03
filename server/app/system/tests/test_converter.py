"""Unit tests for the vectorized EPD converter (rendering/converter.py).

The 4-color path is already proven byte-exact by the layer-2 render golden; the
bw path has no golden, so both are checked here against a scalar per-pixel
reference (the pre-vectorization implementation) on a synthetic image mixing
gradients, threshold-straddling grays and red/yellow patches.
"""
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw

from app.rendering.converter import (
    BLACK, BUFFER_SIZE, HEIGHT, RED, WHITE, WIDTH, YELLOW, png_to_epd_buffer,
)


def _synthetic_png() -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    # Horizontal gradient straddling the 128 luma threshold.
    for x in range(WIDTH):
        v = round(x / (WIDTH - 1) * 255)
        draw.line([(x, 0), (x, 99)], fill=(v, v, v))
    # Pure and near-threshold reds / yellows (the classification edge cases).
    draw.rectangle([0, 100, 199, 199], fill=(255, 0, 0))
    draw.rectangle([200, 100, 399, 199], fill=(181, 99, 99))    # barely red
    draw.rectangle([400, 100, 599, 199], fill=(180, 99, 99))    # not red (r not > 180)
    draw.rectangle([600, 100, 799, 199], fill=(255, 255, 0))
    draw.rectangle([800, 100, 999, 199], fill=(181, 181, 99))   # barely yellow
    draw.rectangle([0, 200, 399, 299], fill=(255, 99, 99))      # bright red, luma > 128
    draw.rectangle([400, 200, 799, 299], fill="black")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _reference_4color(img: Image.Image) -> bytes:
    pixels = img.convert("RGB").load()
    buf = bytearray(BUFFER_SIZE)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            if r > 180 and g < 100 and b < 100:
                color = RED
            elif r > 180 and g > 180 and b < 100:
                color = YELLOW
            elif r * 0.299 + g * 0.587 + b * 0.114 > 128:
                color = WHITE
            else:
                color = BLACK
            idx = (y * WIDTH + x) // 4
            shift = 6 - (x % 4) * 2
            buf[idx] |= color << shift
    return bytes(buf)


def _reference_bw(img: Image.Image) -> bytes:
    bw = ((np.array(img.convert("L")) >= 128) * 255).astype(np.uint8)
    buf = bytearray(BUFFER_SIZE)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            color = WHITE if bw[y, x] >= 128 else BLACK
            idx = (y * WIDTH + x) // 4
            shift = 6 - (x % 4) * 2
            buf[idx] |= color << shift
    return bytes(buf)


def test_4color_matches_scalar_reference():
    png = _synthetic_png()
    img = Image.open(BytesIO(png))
    assert png_to_epd_buffer(png, mode="4color") == _reference_4color(img)


def test_bw_matches_scalar_reference():
    png = _synthetic_png()
    img = Image.open(BytesIO(png))
    assert png_to_epd_buffer(png, mode="bw") == _reference_bw(img)
