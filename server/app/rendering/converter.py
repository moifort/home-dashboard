"""Convert a rendered PNG to the e-Paper display buffer (4-color or B/W)."""
import numpy as np
from PIL import Image
from io import BytesIO

WIDTH = 1360
HEIGHT = 480
BUFFER_SIZE = WIDTH * HEIGHT // 4  # 2 bits/pixel, 4 pixels/byte = 163,200

BLACK, WHITE, YELLOW, RED = 0, 1, 2, 3


def png_to_epd_buffer(png_bytes: bytes, mode: str = "bw", dither: str = "none") -> bytes:
    """Convert PNG to EPD buffer.

    dither: "none" (threshold), "floyd-steinberg", "bayer"
    """
    img = Image.open(BytesIO(png_bytes))
    if img.size == (WIDTH * 2, HEIGHT * 2):
        img = img.resize((WIDTH, HEIGHT), Image.NEAREST)
    if img.size != (WIDTH, HEIGHT):
        raise ValueError(f"Expected {WIDTH}x{HEIGHT} (or 2x), got {img.size[0]}x{img.size[1]}")

    if mode == "bw":
        return _convert_bw(img, dither)
    return _convert_4color(img)


def _floyd_steinberg(gray: np.ndarray) -> np.ndarray:
    img = gray.astype(np.float32)
    h, w = img.shape
    for y in range(h):
        for x in range(w):
            old = img[y, x]
            new = 255.0 if old >= 128 else 0.0
            img[y, x] = new
            err = old - new
            if x + 1 < w:
                img[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    img[y + 1, x - 1] += err * 3 / 16
                img[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    img[y + 1, x + 1] += err * 1 / 16
    return (img >= 128).astype(np.uint8) * 255


def _bayer_dither(gray: np.ndarray) -> np.ndarray:
    bayer4 = np.array([
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ], dtype=np.float32) / 16.0 * 255.0
    h, w = gray.shape
    threshold = np.tile(bayer4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    return ((gray.astype(np.float32) > threshold) * 255).astype(np.uint8)


def _convert_bw(img: Image.Image, dither: str = "none") -> bytes:
    gray = np.array(img.convert("L"))

    if dither == "floyd-steinberg":
        bw = _floyd_steinberg(gray)
    elif dither == "bayer":
        bw = _bayer_dither(gray)
    else:
        bw = ((gray >= 128) * 255).astype(np.uint8)

    buf = bytearray(BUFFER_SIZE)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            color = WHITE if bw[y, x] >= 128 else BLACK
            idx = (y * WIDTH + x) // 4
            shift = 6 - (x % 4) * 2
            buf[idx] |= color << shift
    return bytes(buf)


def _convert_4color(img: Image.Image) -> bytes:
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
