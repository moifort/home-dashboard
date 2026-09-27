"""The "Matrice" UI: a dot-matrix, rule-free alternative to the classic layout.

Selected with DASHBOARD_UI=matrice (see app.system.config). Everything is drawn
from one vocabulary, pixel-exact so nothing gets re-thresholded on the e-paper:
a filled dot (a value, a peak-hour half-hour), a ring (off-peak, or today's
partial day) and a lone 1px pixel (an unlit cell of a grid). Groups are separated
by whitespace only, never by lines. Red is reserved for alerts and bad trends.

Layout (1360×480, 32px margins):
  top line   date · refresh schedule · battery
  4 heroes   big dot-matrix figure + one sub line + its 9-day dot history
             (électricité, eau, crypto, talon; absent domains leave their slot out)
  bottom     today's 48 half-hours as a dot matrix · alerts · "maison" meters
"""
import re

from PIL import Image, ImageDraw, ImageFont

from app.rendering.renderer import (
    FONT_BOLD_PATH, FONT_PATH, HEIGHT, INTRADAY_MAX_W, RED, WIDTH,
)

M = 32  # screen margin (left/right)
HERO_XS = (32, 364, 696, 1028)
HERO_W = 296
HERO_TOP = 56
BOTTOM_TOP = 290

# 5×7 dot-matrix glyphs. A char missing here is skipped; "," reuses ".".
GLYPHS = {
    "0": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ".": ["0", "0", "0", "0", "0", "0", "1"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    " ": ["00", "00", "00", "00", "00", "00", "00"],
}
GLYPHS[","] = GLYPHS["."]

_SPRITES: dict = {}


def _disc(d: int) -> list:
    """Pixel offsets of a d-pixel disc (cached)."""
    if d not in _SPRITES:
        r = d / 2
        _SPRITES[d] = [(x, y) for y in range(d) for x in range(d)
                       if (x + .5 - r) ** 2 + (y + .5 - r) ** 2 <= r * r + .3]
    return _SPRITES[d]


def _dot(draw, x, y, d, fill, hollow=False):
    """A filled disc (or a 2px ring) with its top-left corner at (x, y)."""
    pts = _disc(d)
    if hollow:
        inner = {(ix + 2, iy + 2) for ix, iy in _disc(d - 4)}
        pts = [p for p in pts if p not in inner]
    draw.point([(x + px, y + py) for px, py in pts], fill=fill)


def _glyph_cols(text: str) -> list:
    """Dot columns (each a list of 7 booleans) for text, one blank column between chars."""
    chars = [c for c in text if c in GLYPHS]
    cols = []
    for i, ch in enumerate(chars):
        g = GLYPHS[ch]
        cols += [[row[c] == "1" for row in g] for c in range(len(g[0]))]
        if i < len(chars) - 1:
            cols.append([False] * 7)
    return cols


def _dm_text(draw, x, y, text, pitch, d, fill) -> int:
    """Draw text in dot-matrix glyphs; returns the width drawn."""
    cols = _glyph_cols(text)
    o = (pitch - d) // 2
    for cx, col in enumerate(cols):
        for cy, on in enumerate(col):
            if on:
                _dot(draw, x + cx * pitch + o, y + cy * pitch + o, d, fill)
    return len(cols) * pitch


def _dot_cols(draw, x, y, values, rows, pitch, d, ink, vmax=None, hollow=None, fill_at=None):
    """Vertical dot histogram: one column per value, lit from the bottom. None or
    0 lights nothing; unlit cells keep a 1px pixel so the grid stays visible."""
    known = [v for v in values if v is not None]
    vmax = vmax or (max(known) if known else 0) or 1
    o, mid = (pitch - d) // 2, pitch // 2
    for i, v in enumerate(values):
        lit = 0 if not v else max(1, round(min(1, v / vmax) * rows))
        for j in range(rows):
            cx, cy = x + i * pitch, y + (rows - 1 - j) * pitch
            if j < lit:
                _dot(draw, cx + o, cy + o, d, (fill_at and fill_at(i)) or ink,
                     hollow=bool(hollow and hollow(i)))
            else:
                draw.point((cx + mid, cy + mid), fill=ink)


def _meter(draw, x, y, frac, n, pitch, d, ink, fill):
    """n-dot gauge: the first round(frac·n) dots filled, the rest as rings."""
    lit = round(max(0.0, min(1.0, frac or 0)) * n)
    o = (pitch - d) // 2
    for i in range(n):
        _dot(draw, x + i * pitch + o, y + o, d, fill if i < lit else ink, hollow=i >= lit)


class _Pen:
    """Text helpers bound to one draw + theme: glued segments, spaced labels."""

    def __init__(self, draw, ink):
        self.draw, self.ink = draw, ink
        self.f = {
            "mic": ImageFont.truetype(FONT_PATH, 12),
            "micb": ImageFont.truetype(FONT_BOLD_PATH, 12),
            "r": ImageFont.truetype(FONT_PATH, 14),
            "b": ImageFont.truetype(FONT_BOLD_PATH, 14),
            "r13": ImageFont.truetype(FONT_PATH, 13),
            "b13": ImageFont.truetype(FONT_BOLD_PATH, 13),
        }

    def label(self, x, y, text, fill=None, bold=False, spacing=1) -> int:
        """Small label with 1px letter spacing; returns its right edge."""
        font = self.f["micb" if bold else "mic"]
        for ch in text:
            self.draw.text((x, y), ch, font=font, fill=fill or self.ink)
            x += round(self.draw.textlength(ch, font=font)) + spacing
        return x

    def seg_w(self, segs) -> int:
        return round(sum(self.draw.textlength(t, font=self.f[k]) for t, k, _ in segs))

    def segs(self, x, y, segs, right=False) -> int:
        """Glued (text, font_key, color) runs; right=True right-aligns them on x."""
        if right:
            x -= self.seg_w(segs)
        for t, k, c in segs:
            self.draw.text((round(x), y), t, font=self.f[k], fill=c or self.ink)
            x += self.draw.textlength(t, font=self.f[k])
        return round(x)

    def fit(self, text, key, max_w) -> str:
        if self.draw.textlength(text, font=self.f[key]) <= max_w:
            return text
        while text and self.draw.textlength(text + "…", font=self.f[key]) > max_w:
            text = text[:-1]
        return text + "…"


def _num(value, unit, size="", ink=None):
    """House rule: number bold, unit regular, glued."""
    return [(str(value), "b" + size, ink), (unit, "r" + size, ink)]


def _trend(pct, bad_when_up, ink, size=""):
    """▲/▼ + whole percent, red when it goes the bad way (em dash at 0)."""
    if pct is None:
        return []
    pct = round(pct)
    if pct == 0:
        return [("—", "r" + size, ink)]
    bad = pct > 0 if bad_when_up else pct < 0
    return [(f"{'▲' if pct > 0 else '▼'}{abs(pct)}%", "b" + size, RED if bad else ink)]


GAP = [("  ", "r", None)]


def _hc_slots(home) -> set:
    """Half-hour slots (0..47) inside an HC window, from the Home tariff lines."""
    def mins(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    windows, period = [], ""
    for line in (home or {}).get("tariff") or []:
        period = line.get("period") or period
        if period == "HC":
            windows.append((mins(line["start_text"]), mins(line["end_text"])))
    slots = set()
    for i in range(48):
        mid = i * 30 + 15
        for a, b in windows:
            if (a <= mid < b) if a < b else (mid >= a or mid < b):
                slots.add(i)
    return slots


def _now_slot(home):
    m = re.match(r"(\d+):(\d+)", (home or {}).get("last_text") or "")
    return (int(m.group(1)) * 2 + int(m.group(2)) // 30) if m else None


def _heroes(data, ink):
    """(label, figure, sub segments, history values, history caption, last is today)
    per present domain, in slot order."""
    out = []
    stats, days = data.get("stats") or {}, data.get("days") or []
    avg = stats.get("avg_kwh")
    sub = _trend(stats.get("avg_kwh_pct"), True, ink) + GAP
    if stats.get("avg_price") is not None:
        sub += _num(stats["avg_price"], "€/j") + GAP
    if stats.get("hc_ratio") is not None:
        sub += [("HC ", "r", None)] + _num(round(stats["hc_ratio"]), "% ") + _trend(stats.get("hc_ratio_pct"), False, ink)
    hist = [(d.get("hc_kwh") or 0) + (d.get("hp_kwh") or 0) for d in days]
    out.append(("électricité · kWh/j", "--" if avg is None else str(avg), sub, hist,
                f"{len(hist)} jours", bool(days and days[-1].get("today"))))

    water_days, ws = data.get("water_days"), data.get("water_stats") or {}
    if water_days:
        sub = _trend(ws.get("avg_pct"), True, ink) + GAP
        if ws.get("month_total_text"):
            sub += _num(ws["month_total_text"], "m³") + GAP
        if ws.get("cost_text"):
            sub += _num(ws["cost_text"], "€")
        out.append(("eau · L/j", ws.get("avg_text") or "--", sub,
                    [d.get("liters") for d in water_days],
                    f"{len(water_days)} jours", bool(water_days[-1].get("today"))))

    crypto = data.get("crypto")
    if crypto:
        sub = [(crypto.get("portfolio_text", ""), "b", None)] + GAP
        if crypto.get("profit_text"):
            sub += [(crypto["profit_text"], "b", None if crypto.get("profit_positive", True) else RED)] + GAP
        if crypto.get("alpha_text"):
            sub += [("alpha ", "r", None), (crypto["alpha_text"], "b", None if crypto.get("alpha_positive", True) else RED), ("%", "r", None)]
        grid = data.get("crypto_grid") or {}
        lo = grid.get("lower") or 0
        prices = [max(0, p - lo) for _, p in grid.get("points") or []]
        out.append(("crypto · profits", f"{crypto.get('pct_text', '')}%", sub, prices, "prix", False))

    talon, net = data.get("talon"), (data.get("home") or {}).get("net_cost")
    if talon and talon.get("avg_w") is not None:
        sub = []
        if talon.get("annual_text"):
            sub += _num(talon["annual_text"], "€/an") + GAP
        if net:
            sub += [("mois ", "r", None)] + _num(net["mtd_text"], "€")
            if net.get("proj_text"):
                sub += [(" ► ~", "r", None)] + _num(net["proj_text"], "€")
        spark = [v for v in talon.get("spark") or [] if v is not None]
        base = min(spark) * .9 if spark else 0
        hist = [None if v is None else v - base for v in talon.get("spark") or []]
        out.append(("talon · W", talon.get("avg_text", "--"), sub, hist, f"{len(hist)} jours", False))
    return out


def _draw_today(pen, data, ink):
    days, home = data.get("days") or [], data.get("home")
    today = next((d for d in days if d.get("today")), None)
    x, y = M, BOTTOM_TOP
    right = [("aujourd'hui · ", "mic", None)]
    if today:
        right += [(f"{(today.get('hc_kwh') or 0) + (today.get('hp_kwh') or 0):.1f}", "micb", None), ("kWh", "mic", None)]
    right += [("     ● heures pleines   ○ heures creuses", "mic", None)]
    pen.segs(x, y, right)
    values = (today or {}).get("intraday") or [None] * 48
    hc = _hc_slots(home)
    p, rows, top = 14, 8, y + 26
    _dot_cols(pen.draw, x, top, values, rows, p, 8, ink, vmax=INTRADAY_MAX_W,
              hollow=lambda i: i in hc)
    ly = top + rows * p + 6
    for h in (0, 6, 12, 18, 24):
        t = f"{h}h"
        tx = x + h * 2 * p - (round(pen.draw.textlength(t, font=pen.f["mic"])) if h == 24 else 0)
        pen.label(tx, ly, t)
    now = _now_slot(home)
    if now is not None:
        pen.draw.text((x + now * p + p // 2 - 5, ly), "▲", font=pen.f["mic"], fill=ink)


def _draw_alerts(pen, data, ink):
    x, y, w = 760, BOTTOM_TOP, 250
    items = []
    for row in data.get("alert_board") or []:
        if row.get("alert"):
            items += [(msg, fig, positive) for msg, fig, _money, positive in row.get("items") or []]
    n_bad = sum(1 for *_, positive in items if not positive)
    pen.label(x, y, "alertes", fill=RED if n_bad else ink)
    if not items:
        pen.segs(x, y + 26, [("Tout va bien", "r", None)])
        return
    dw = _dm_text(pen.draw, x, y + 26, str(n_bad), 10, 7, RED if n_bad else ink)
    tx = x + dw + 22
    for i, (msg, fig, positive) in enumerate(items[:5]):
        color = ink if positive else RED
        fig_segs = [(" " + fig, "b13", color)] if fig else []
        msg = pen.fit(msg, "r13", x + w - tx - pen.seg_w(fig_segs))
        pen.segs(tx, y + 26 + i * 21, [(msg, "r13", color)] + fig_segs)


def _draw_house(pen, data, ink):
    x, y, w = 1040, BOTTOM_TOP, WIDTH - M - 1040
    pen.label(x, y, "maison")
    rows = []  # (name, value segs, fraction, dot color)
    ps = data.get("production_stats")
    if data.get("production_days") and ps:
        auto = ps.get("autonomy_pct")
        rows.append(("solaire", _num(ps.get("avg_kwh", 0), "kWh/j", "13"), (auto or 0) / 100, ink))
    unifi = data.get("unifi")
    if unifi and unifi.get("wifi_pct") is not None:
        rows.append(("wifi", _num(unifi["wifi_pct"], "%", "13"), unifi["wifi_pct"] / 100, ink))
    sensors = data.get("power_sensors") or []
    top_kwh = max([s.get("avg_kwh") or 0 for s in sensors] or [0]) or 1
    for s in sensors:
        rows.append((s.get("name", "").lower(), _num(s.get("cost_text", "--"), "€", "13"),
                     (s.get("avg_kwh") or 0) / top_kwh, ink))
    for p in data.get("plants") or []:
        color = RED if p.get("needs_water") else ink
        rows.append((p.get("name", "").lower(), [("hum ", "r13", None)] + _num(p.get("moisture_text", "--"), "%", "13"),
                     (p.get("moisture_pct") or 0) / 100, color))
    meter_w = 10 * 8
    for i, (name, segs, frac, color) in enumerate(rows[:8]):
        ry = y + 24 + i * 21
        pen.segs(x, ry, [(pen.fit(name, "r13", 110), "r13", None)])
        _meter(pen.draw, x + w - meter_w, ry + 3, frac, 10, 8, 6, ink, color)
        pen.segs(x + w - meter_w - 10, ry, segs, right=True)


def render_matrice(data: dict, theme: str = "light") -> Image.Image:
    dark = theme == "dark"
    paper, ink = ((0, 0, 0), (255, 255, 255)) if dark else ((255, 255, 255), (0, 0, 0))
    img = Image.new("RGB", (WIDTH, HEIGHT), paper)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    pen = _Pen(draw, ink)

    home = data.get("home") or {}
    x = pen.label(M, 24, home.get("date_text", ""), bold=True)
    pen.label(x + 16, 24, "maison")
    top_right = [("écran ", "mic", None), (home.get("last_text", ""), "micb", None),
                 (" ► ", "mic", None), (home.get("next_text", ""), "micb", None)]
    batt = home.get("battery") or {}
    if batt.get("percent") is not None:
        top_right += [("     batt. ", "mic", None), (str(batt["percent"]), "micb", None), ("%", "mic", None)]
    pen.segs(WIDTH - M, 24, top_right, right=True)

    for hx, (label, fig, sub, hist, caption, last_today) in zip(HERO_XS, _heroes(data, ink)):
        pen.label(hx, HERO_TOP, label)
        cols = len(_glyph_cols(fig)) or 1
        pitch = min(12, HERO_W // cols)
        _dm_text(draw, hx, HERO_TOP + 26, fig, pitch, pitch * 2 // 3, ink)
        pen.segs(hx, HERO_TOP + 26 + 7 * pitch + 14, sub)
        hist = hist[-20:]  # the history never outgrows its slot (20 × 10px)
        hy = HERO_TOP + 26 + 7 * pitch + 42
        _dot_cols(draw, hx, hy, hist, 6, 10, 6, ink,
                  hollow=lambda i, n=len(hist): last_today and i == n - 1)
        pen.label(hx + len(hist) * 10 + 12, hy + 60 - 14, caption)

    _draw_today(pen, data, ink)
    _draw_alerts(pen, data, ink)
    _draw_house(pen, data, ink)
    return img
