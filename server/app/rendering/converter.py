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


def _pack_2bpp(codes: np.ndarray) -> bytes:
    """Pack a HEIGHT×WIDTH array of 2-bit color codes into the EPD buffer:
    4 pixels per byte, first pixel in the two most significant bits."""
    grouped = codes.reshape(-1, 4).astype(np.uint16)
    shifts = np.array([6, 4, 2, 0], dtype=np.uint16)
    return (grouped << shifts).sum(axis=1).astype(np.uint8).tobytes()


def _floyd_steinberg(gray: np.ndarray) -> np.ndarray:
    # Left as a per-pixel loop on purpose: error diffusion is sequential (each
    # pixel depends on its neighbours' propagated error) and this path is off
    # the production route (/display uses mode="4color").
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

    return _pack_2bpp((bw >= 128).astype(np.uint8))  # WHITE=1 / BLACK=0


def _convert_4color(img: Image.Image) -> bytes:
    rgb = np.asarray(img.convert("RGB"))
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    # float64 luma matches the scalar Python arithmetic bit for bit.
    luma = r * 0.299 + g * 0.587 + b * 0.114

    # Same classification priority as the original per-pixel chain (red wins
    # over white on a bright red): later assignments overwrite earlier ones.
    codes = np.full((HEIGHT, WIDTH), BLACK, dtype=np.uint8)
    codes[luma > 128] = WHITE
    codes[(r > 180) & (g > 180) & (b < 100)] = YELLOW
    codes[(r > 180) & (g < 100) & (b < 100)] = RED
    return _pack_2bpp(codes)
