"""The "Arcade" UI: a pixel-art screen borrowed from video-game HUDs.

Selected with DASHBOARD_UI=arcade (see app.system.config). White pixels on a black
screen by default (DASHBOARD_THEME=light flips it). No frame and no rule: five
columns and whitespace. One vocabulary, drawn pixel-exact so nothing gets
re-thresholded on the e-paper:
  - big figures in 3×5 square glyphs,
  - columns of small squares for a history (an unlit cell stays a 1px dot),
  - segmented bars, like a life bar, for anything that is a gauge,
  - one 8×8 icon per domain, drops for a plant's moisture.
Red is reserved for alerts and bad trends.

Layout (1360×480, 48px margins, 5 columns of 216px every 262px):
  header   date · current tariff period · refresh schedule
  row A    counters: électricité (last 24 h), eau, solaire, crypto, alertes
  row B    the house: maison, prises, plantes, réseau, écran
  row C    home lab: one server per column, its last 24 hours (CPU, memory)
Absent domains leave their slot out; alertes, écran and the home lab title keep
their column.
"""
from PIL import Image, ImageDraw, ImageFont

from app.rendering.matrice import _hc_slots, _now_slot, _num, _Pen, _trend
from app.rendering.renderer import (
    FONT_BOLD_PATH, FONT_PATH, HEIGHT, INTRADAY_MAX_W, RED, WIDTH,
)

XS = (48, 310, 572, 834, 1096)
COL_W = 216
HEAD_Y, ROW_A, ROW_B, ROW_C = 16, 46, 198, 334
PITCH, SQUARE = 6, 5     # chart cell pitch / lit square size
LINE_H = 18              # one text row of the house columns
SPACE = 4                # width of a space between two words
LAB_MAX = 6              # servers the home lab row can show
LAB_PITCH = 167          # column pitch when more than four servers share the row
GAP = [("   ", "r", None)]

# 3×5 square glyphs for the big figures. "," reuses ".".
GLYPHS = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    ".": ["0", "0", "0", "0", "1"], "+": ["000", "010", "111", "010", "000"],
    "-": ["000", "000", "111", "000", "000"], "/": ["001", "001", "010", "100", "100"],
}
GLYPHS[","] = GLYPHS["."]

ICONS = {
    "bolt":   ["00001100", "00011000", "00110000", "01111110", "00001100", "00011000", "00110000", "01100000"],
    "drop":   ["00011000", "00011000", "00111100", "00111100", "01111110", "01111110", "01111110", "00111100"],
    "sun":    ["00011000", "01000010", "00111100", "10111101", "10111101", "00111100", "01000010", "00011000"],
    "coin":   ["00111100", "01000010", "10011001", "10100001", "10100001", "10011001", "01000010", "00111100"],
    "alert":  ["00011000", "00111100", "00111100", "00011000", "00011000", "00000000", "00011000", "00011000"],
    "house":  ["00011000", "00111100", "01111110", "11111111", "01111110", "01100110", "01100110", "01100110"],
    "plug":   ["00100100", "00100100", "01111110", "01111110", "01111110", "00111100", "00011000", "00011000"],
    "plant":  ["01100110", "01111110", "00111100", "00011000", "01111110", "01111110", "00111100", "00111100"],
    "wifi":   ["00111100", "01000010", "10011001", "00100100", "00011000", "00000000", "00011000", "00011000"],
    "screen": ["11111111", "10000001", "10000001", "10000001", "11111111", "00011000", "00111100", "00000000"],
    "rack":   ["11111111", "10000101", "11111111", "00000000", "11111111", "10000101", "11111111", "00000000"],
}
DROP_FULL = ["00100", "00100", "01110", "11111", "01110"]
DROP_EMPTY = ["00100", "00100", "01010", "10001", "01110"]


# ---- pixel primitives -------------------------------------------------------

def _bitmap(draw, x, y, rows, scale, fill):
    for ry, row in enumerate(rows):
        for rx, c in enumerate(row):
            if c == "1":
                draw.rectangle([x + rx * scale, y + ry * scale,
                                x + (rx + 1) * scale - 1, y + (ry + 1) * scale - 1], fill=fill)


def _figure(text) -> str:
    """A text the square glyphs can draw, else the "no value" figure."""
    text = str(text if text is not None else "")
    return text if text and all(c in GLYPHS for c in text) else "--"


def _pix_w(text, scale) -> int:
    return sum((len(GLYPHS[c][0]) + 1) * scale for c in text) - scale


def _pix(draw, x, y, text, scale, fill) -> int:
    """Draw text in 3×5 square glyphs; returns the width drawn."""
    cx = x
    for ch in text:
        _bitmap(draw, cx, y, GLYPHS[ch], scale, fill)
        cx += (len(GLYPHS[ch][0]) + 1) * scale
    return cx - x - scale


def _square(draw, x, y, size, fill, hollow=False):
    box = [x, y, x + size - 1, y + size - 1]
    if hollow:
        draw.rectangle(box, outline=fill)
    else:
        draw.rectangle(box, fill=fill)


def _blocks(draw, x, y, values, rows, ink, vmax=None, vmin=0, hollow=None, fill_at=None):
    """Columns of squares, lit from the bottom. None or 0 lights nothing; an
    unlit cell keeps a 1px dot so the grid stays readable."""
    known = [v for v in values if v is not None]
    vmax = vmax or (max(known) if known else 0) or 1
    span = (vmax - vmin) or 1
    for i, v in enumerate(values):
        lit = 0 if not v else max(1, min(rows, round((v - vmin) / span * rows)))
        for j in range(rows):
            cx, cy = x + i * PITCH, y + (rows - 1 - j) * PITCH
            if j < lit:
                _square(draw, cx, cy, SQUARE, (fill_at and fill_at(i)) or ink,
                        hollow=bool(hollow and hollow(i)))
            else:
                draw.point((cx + SQUARE // 2, cy + SQUARE // 2), fill=ink)


def _seg(draw, x, y, frac, n, ink, fill=None):
    """Life bar: n segments of 5×9, the first round(frac·n) filled."""
    lit = round(max(0.0, min(1.0, frac or 0)) * n)
    for i in range(n):
        box = [x + i * 6, y, x + i * 6 + 4, y + 8]
        if i < lit:
            draw.rectangle(box, fill=fill or ink)
        else:
            draw.rectangle(box, outline=ink)


def _seg_w(n) -> int:
    return n * 6 - 1


DROPS_W = 5 * 12 - 2


def _drops(draw, x, y, frac, ink, fill=None):
    """Five drops (the hearts of a life counter): full up to the moisture."""
    lit = round(max(0.0, min(1.0, frac or 0)) * 5)
    for i in range(5):
        _bitmap(draw, x + i * 12, y, DROP_FULL if i < lit else DROP_EMPTY, 2,
                (fill or ink) if i < lit else ink)


# ---- text helpers -----------------------------------------------------------

def _pen(draw, ink) -> _Pen:
    pen = _Pen(draw, ink)
    pen.f = {
        "r": ImageFont.truetype(FONT_PATH, 13), "b": ImageFont.truetype(FONT_BOLD_PATH, 13),
        "r12": ImageFont.truetype(FONT_PATH, 12), "b12": ImageFont.truetype(FONT_BOLD_PATH, 12),
    }
    return pen


def _word_w(pen, text, key) -> int:
    words = text.split(" ")
    return (sum(round(pen.draw.textlength(w, font=pen.f[key])) for w in words if w)
            + SPACE * (len(words) - 1))


def _segs_w(pen, segs) -> int:
    return sum(_word_w(pen, t, k) for t, k, _ in segs)


def _segs(pen, x, y, segs, right=False) -> int:
    """Glued (text, font_key, color) runs, drawn word by word on whole pixels with
    a fixed space: at 12px Arial's own 3px space reads as no space at all once
    thresholded. right=True right-aligns the runs on x. Returns the right edge."""
    if right:
        x -= _segs_w(pen, segs)
    for text, key, color in segs:
        for i, word in enumerate(text.split(" ")):
            x += SPACE if i else 0
            if word:
                pen.draw.text((x, y), word, font=pen.f[key], fill=color or pen.ink)
                x += round(pen.draw.textlength(word, font=pen.f[key]))
    return x


def _spaced(pen, x, y, segs, right=False, spacing=2) -> int:
    """Small 12px label with letter spacing, as (text, bold, color) runs.
    right=True right-aligns it on x. Returns the right edge."""
    def width(ch, bold):
        return round(pen.draw.textlength(ch, font=pen.f["b12" if bold else "r12"])) + spacing
    if right:
        x -= sum(width(ch, bold) for text, bold, _ in segs for ch in text) - spacing
    for text, bold, color in segs:
        for ch in text:
            pen.draw.text((x, y), ch, font=pen.f["b12" if bold else "r12"], fill=color or pen.ink)
            x += width(ch, bold)
    return x


def _title(pen, x, y, icon, label, color=None):
    _bitmap(pen.draw, x, y, ICONS[icon], 2, color or pen.ink)
    _spaced(pen, x + 24, y + 1, [(label, False, color)])


def _row(pen, x, y, left, right=None, bar=None, val_w=0):
    """One 18px row: left runs, right runs right-aligned on the column edge, and
    an optional (frac, n, color) life bar sitting left of the right value."""
    if left:
        _segs(pen, x, y + 1, left)
    edge = x + COL_W
    if right:
        _segs(pen, edge, y + 1, right, right=True)
        edge -= max(val_w, _segs_w(pen, right)) + 8
    if bar:
        frac, n, color = bar
        _seg(pen.draw, edge - _seg_w(n), y + 4, frac, n, pen.ink, color)


def _side(pen, x, y, line1, line2):
    """Two 12px lines beside a chart, bottom-aligned on it."""
    _segs(pen, x, y - 30, line1)
    _segs(pen, x, y - 15, line2)


def _t(text, key="r12", color=None):
    return [(str(text), key, color)]


# ---- data helpers -----------------------------------------------------------

def _clock_min(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _period_text(home):
    """("heures pleines, creuses à ", "23:32") from the tariff lines and the clock."""
    now_text = (home or {}).get("last_text") or ""
    windows, period = [], ""
    for line in (home or {}).get("tariff") or []:
        period = line.get("period") or period
        if period == "HC":
            windows.append((line["start_text"], line["end_text"]))
    if not windows or ":" not in now_text:
        return None
    now = _clock_min(now_text)
    for start, end in windows:
        a, b = _clock_min(start), _clock_min(end)
        if (a <= now < b) if a < b else (now >= a or now < b):
            return "heures creuses, pleines à ", end
    nxt = min(windows, key=lambda w: (_clock_min(w[0]) - now) % 1440)
    return "heures pleines, creuses à ", nxt[0]


def _last_24h(days, now_slot):
    """The 48 half-hour mean powers (W) ending at the last refresh, oldest first."""
    idx = next((i for i, d in enumerate(days) if d.get("today")), None)
    if idx is None:
        return []
    today = ((days[idx].get("intraday") or []) + [None] * 48)[:48]
    prev = ((days[idx - 1].get("intraday") or []) if idx else []) + [None] * 48
    if now_slot is None:
        now_slot = max((i + 1 for i, v in enumerate(today) if v is not None), default=0)
    now_slot = max(0, min(48, now_slot))
    return prev[now_slot:48] + today[:now_slot]


def _hourly_max(slots):
    """48 half-hours → 24 hours, each the higher of its two halves."""
    out = []
    for i in range(0, len(slots) - 1, 2):
        pair = [v for v in slots[i:i + 2] if v is not None]
        out.append(max(pair) if pair else None)
    return out


def _alert_items(data):
    return [(msg, fig, positive) for row in data.get("alert_board") or [] if row.get("alert")
            for msg, fig, _money, positive in row.get("items") or []]


def _has_bad_alert(data, label):
    return any(r.get("label") == label and r.get("n_bad") for r in data.get("alert_board") or [])


# ---- row A: the counters ----------------------------------------------------

def _hero(pen, x, icon, label, figure, unit, sub, color=None):
    """Title, big figure with its unit on the baseline, one sub line. Returns the
    y of the chart's bottom edge."""
    _title(pen, x, ROW_A, icon, label, color)
    figure = _figure(figure)
    w = _pix(pen.draw, x, ROW_A + 26, figure, 8, color or pen.ink)
    if unit:
        pen.draw.text((x + w + 6, ROW_A + 66), unit, font=pen.f["r"], fill=color or pen.ink, anchor="ls")
    _segs(pen, x, ROW_A + 76, sub)
    return ROW_A + 130


def _draw_electricity(pen, x, data):
    stats, days, home = data.get("stats") or {}, data.get("days") or [], data.get("home")
    today = next((d for d in days if d.get("today")), None)
    sub = _trend(stats.get("avg_kwh_pct"), True, pen.ink)
    if stats.get("avg_price") is not None:
        sub += GAP + _num(stats["avg_price"], "€/j")
    if today:
        sub += GAP + _t("auj. ", "r") + _num(f"{(today.get('hc_kwh') or 0) + (today.get('hp_kwh') or 0):.1f}", "kWh")
    bottom = _hero(pen, x, "bolt", "électricité", stats.get("avg_kwh"), "kWh/j", sub)
    slots = _last_24h(days, _now_slot(home))
    hours = _hourly_max(slots) or [None] * 24
    _blocks(pen.draw, x, bottom - 30, hours, 5, pen.ink, vmax=INTRADAY_MAX_W)
    known = [v for v in slots if v is not None]
    peak = _t("pic ") + _num(f"{max(known) / 1000:.1f}", "kW", "12") if known else []
    _side(pen, x + 24 * PITCH + 12, bottom, _t("24 h"), peak)


def _draw_water(pen, x, data):
    days, ws = data["water_days"], data.get("water_stats") or {}
    today = days[-1] if days[-1].get("today") else None
    sub = _trend(ws.get("avg_pct"), True, pen.ink)
    if today and today.get("liters") is not None:
        sub += GAP + _t("auj. ", "r") + _num(round(today["liters"]), "L")
    if ws.get("cost_text"):
        sub += GAP + _num(ws["cost_text"], "€")
    bottom = _hero(pen, x, "drop", "eau", ws.get("avg_text"), "L/j", sub)
    liters = [d.get("liters") for d in days]
    last_done = max((i for i, d in enumerate(days) if not d.get("today")), default=None)
    leak = last_done if _has_bad_alert(data, "Eau") else None
    _blocks(pen.draw, x, bottom - 30, liters, 5, pen.ink,
            hollow=lambda i: today is not None and i == len(days) - 1,
            fill_at=lambda i: RED if i == leak else None)
    known = [v for v in liters if v is not None]
    peak = _t("pic ") + _num(round(max(known)), "L", "12") if known else []
    _side(pen, x + len(days) * PITCH + 12, bottom, _t(f"{len(days)} jours"), peak)


def _draw_solar(pen, x, data):
    days, ps = data["production_days"], data.get("production_stats") or {}
    sub = _trend(ps.get("avg_kwh_pct"), False, pen.ink)
    if ps.get("autonomy_pct") is not None:
        sub += GAP + _t("autonomie ", "r") + _num(round(ps["autonomy_pct"]), "%")
    if ps.get("savings_eur") is not None:
        sub += GAP + _num(f"{ps['savings_eur']:.2f}", "€")
    bottom = _hero(pen, x, "sun", "solaire", ps.get("avg_kwh"), "kWh/j", sub)
    kwh = [d.get("pv_kwh") for d in days]
    _blocks(pen.draw, x, bottom - 30, kwh, 5, pen.ink,
            hollow=lambda i: bool(days[-1].get("today")) and i == len(days) - 1)
    known = [v for v in kwh if v]
    best = _t("max ") + _num(f"{max(known):.1f}", "kWh", "12") if known else []
    _side(pen, x + len(days) * PITCH + 12, bottom, _t(f"{len(days)} jours"), best)


def _draw_crypto(pen, x, data):
    crypto, grid = data["crypto"], data.get("crypto_grid") or {}
    bad = None if crypto.get("profit_positive", True) else RED
    sub = [(crypto.get("portfolio_text", ""), "b", None)]
    if crypto.get("profit_text"):
        sub += GAP + [(crypto["profit_text"], "b", bad)]
    if crypto.get("alpha_text"):
        sub += GAP + _t("alpha ", "r") + [(crypto["alpha_text"], "b", None if crypto.get("alpha_positive", True) else RED),
                                          ("%", "r", None)]
    label = "crypto · test" if crypto.get("sandbox") else "crypto"
    bottom = _hero(pen, x, "coin", label, crypto.get("pct_text"), "%", sub, color=bad)
    prices = [p for _, p in grid.get("points") or []][-24:]
    if prices:
        floor = min(prices) - (max(prices) - min(prices)) / 4
        _blocks(pen.draw, x, bottom - 30, prices, 5, pen.ink, vmin=floor)
        _side(pen, x + len(prices) * PITCH + 12, bottom, _t("prix"),
              _t(grid.get("current_price_text", ""), "b12"))


def _draw_alerts(pen, x, data):
    items = _alert_items(data)
    n_bad = sum(1 for *_, positive in items if not positive)
    color = RED if n_bad else None
    _title(pen, x, ROW_A, "alert", "alertes", color)
    _pix(pen.draw, x, ROW_A + 26, str(n_bad), 8, color or pen.ink)
    if not items:
        _segs(pen, x, ROW_A + 76, _t("Tout va bien", "r"))
        return
    shown = items if len(items) <= 4 else items[:3]
    for i, (msg, fig, positive) in enumerate(shown):
        c = None if positive else RED
        fig_segs = [(" " + fig, "b", c)] if fig else []
        msg = pen.fit(msg, "r", COL_W - _segs_w(pen, fig_segs))
        _segs(pen, x, ROW_A + 76 + i * LINE_H, [(msg, "r", c)] + fig_segs)
    if len(items) > 4:
        rest = items[3:]
        c = RED if any(not positive for *_, positive in rest) else None
        _segs(pen, x, ROW_A + 76 + 3 * LINE_H, [("+", "r", c), (str(len(rest)), "b", c), (" autres", "r", c)])


# ---- row B: the house -------------------------------------------------------

def _draw_house(pen, x, data):
    home, stats, talon = data.get("home") or {}, data.get("stats") or {}, data.get("talon") or {}
    _title(pen, x, ROW_B, "house", "maison")
    y = ROW_B + 24
    net = home.get("net_cost")
    if net:
        left = _t("mois ", "r") + _num(net["mtd_text"], "€")
        bar = None
        if net.get("proj_text"):
            left += _t(" ► ~", "r") + _num(net["proj_text"], "€")
            try:
                bar = (float(net["mtd_text"]) / float(net["proj_text"]), 10, None)
            except (ValueError, ZeroDivisionError):
                bar = None
        _row(pen, x, y, left, bar=bar)
        y += LINE_H
    if talon.get("avg_w") is not None:
        right = _num(talon["annual_text"], "€/an") if talon.get("annual_text") else None
        _row(pen, x, y, _t("talon ", "r") + _num(talon.get("avg_text", "--"), "W ")
             + _trend(talon.get("trend_pct"), True, pen.ink), right)
        y += LINE_H
    if stats.get("hc_ratio") is not None:
        _row(pen, x, y, _t("heures creuses ", "r") + _num(round(stats["hc_ratio"]), "% ")
             + _trend(stats.get("hc_ratio_pct"), False, pen.ink))
        y += LINE_H
    hc = _hc_slots(home)
    if not hc:
        return
    y += 5  # the day's tariff: 48 half-hours, hollow = off-peak
    for i in range(48):
        box = [x + i * 4, y, x + i * 4 + 2, y + 8]
        if i in hc:
            pen.draw.rectangle(box, outline=pen.ink)
        else:
            pen.draw.rectangle(box, fill=pen.ink)
    now = _now_slot(home)
    mark_x = None if now is None else x + now * 4 - 3
    for h in (0, 6, 12, 18):
        lx = x + h * 8
        if mark_x is None or lx + 22 < mark_x or lx > mark_x + 12:
            _segs(pen, lx, y + 12, _t(f"{h}h"))
    if mark_x is not None:
        pen.draw.text((mark_x, y + 12), "▲", font=pen.f["r12"], fill=pen.ink)


def _draw_plugs(pen, x, data):
    sensors = data["power_sensors"]
    _title(pen, x, ROW_B, "plug", "prises · €/mois")
    ranked = sorted(sensors, key=lambda s: -(s.get("avg_kwh") or 0))[:5]
    top = max([s.get("avg_kwh") or 0 for s in ranked] or [0]) or 1
    for i, s in enumerate(ranked):
        y = ROW_B + 24 + i * LINE_H
        _segs(pen, x, y + 1, [(pen.fit(s.get("name", ""), "r", 112), "r", None)])
        _seg(pen.draw, x + 120, y + 4, (s.get("avg_kwh") or 0) / top, 8, pen.ink)
        _segs(pen, x + COL_W, y + 1, _num(s.get("cost_text", "--"), "€"), right=True)


def _plant_status(p):
    flags = [t for t, on in (("à arroser", p.get("needs_water")), ("pile faible", p.get("low_battery"))) if on]
    return " · ".join(flags)


def _draw_plants(pen, x, data):
    plants = data["plants"]
    _title(pen, x, ROW_B, "plant", "plantes")
    two_lines = len(plants) <= 2
    for i, p in enumerate(plants[:5]):
        y = ROW_B + 24 + i * LINE_H * (2 if two_lines else 1)
        status = _plant_status(p)
        c = RED if status else None
        frac = (p.get("moisture_pct") or 0) / 100
        value = [(str(p.get("moisture_text", "--")), "b", c), ("%", "r", c)]
        _segs(pen, x, y + 1, [(pen.fit(p.get("name", ""), "b", 110), "b", c)])
        _segs(pen, x + COL_W, y + 1, value, right=True)
        _drops(pen.draw, x + COL_W - 34 - 8 - DROPS_W, y + 4, frac, pen.ink, c)
        if not two_lines:
            continue
        left = [(status, "r", RED)] if status else _t("lumière ", "r") + [(str(p.get("illuminance_text", "--")), "b", None)]
        right = _num(p["temperature_text"], "°") if p.get("temperature_text") else None
        _row(pen, x, y + LINE_H, left, right)


def _draw_network(pen, x, data):
    u = data["unifi"]
    _title(pen, x, ROW_B, "wifi", "réseau")
    rows = []  # (left, right, bar)
    if u.get("wifi_pct") is not None:
        c = RED if u.get("wifi_bad") else None
        score, _, out_of = str(u.get("wifi_exp_text") or u["wifi_pct"]).partition("/")
        value = [(score, "b", c)] + ([("/" + out_of, "r", c)] if out_of else [("%", "r", c)])
        rows.append((_t("wifi", "r", c), value, (u["wifi_pct"] / 100, 10, c)))
    if u.get("isp_bad"):
        rows.append((_t(u.get("isp_name") or "internet", "r", RED),
                     [(str(u.get("isp_pct", "--")), "b", RED), ("%", "r", RED)], None))
    if u.get("latency_val") is not None:
        rows.append((_t("latence", "r"), _num(u["latency_val"], "ms ") + _trend(u.get("latency_trend"), True, pen.ink), None))
    if u.get("usage_hier") is not None:
        rows.append((_t("données hier", "r"), _num(u["usage_hier"], "Go ") + _trend(u.get("usage_trend"), False, pen.ink), None))
    if u.get("usage_mois") is not None:
        rows.append((_t("30 jours", "r"), _num(u["usage_mois"], "Go"), None))
    count = sum((u.get(k) or {}).get("count") or 0 for k in ("main", "iot"))
    if count:
        rows.append((_t("appareils", "r"), [(str(count), "b", None)], None))
    for i, (left, right, bar) in enumerate(rows[:6]):
        _row(pen, x, ROW_B + 24 + i * LINE_H, left, right, bar=bar, val_w=44)


def _draw_screen(pen, x, data):
    home = data.get("home") or {}
    batt = home.get("battery") or {}
    _title(pen, x, ROW_B, "screen", "écran")
    rows = []
    if batt.get("percent") is not None:
        rows.append((_t("batterie", "r"), _num(batt["percent"], "%"), (batt["percent"] / 100, 10, None)))
        if batt.get("since_text"):
            rows.append((_t("depuis la charge", "r"), [(batt["since_text"], "b", None)], None))
    if home.get("last_text"):
        rows.append((_t("mise à jour", "r"), [(home["last_text"], "b", None)], None))
    if home.get("next_text"):
        rows.append((_t("prochaine", "r"), [(home["next_text"], "b", None)], None))
    for i, (left, right, bar) in enumerate(rows):
        _row(pen, x, ROW_B + 24 + i * LINE_H, left, right, bar=bar, val_w=44)


# ---- row C: the home lab ----------------------------------------------------

def _draw_homelab(pen, data):
    """One server per column with its last 24 hours: the hour's highest CPU and
    memory use, so a short spike stays visible. The disk is a figure. Up to four
    servers sit on the screen's columns, with the peak figures beside the charts;
    five or six get narrower columns, with the figures under the charts."""
    lab, home = data["homelab"], data.get("home") or {}
    nodes = (lab.get("nodes") or [])[:LAB_MAX]
    x, ink = XS[0], pen.ink
    online = lab.get("online", sum(1 for n in nodes if n.get("online", True)))
    total = lab.get("total", len(nodes))
    color = None if online == total else RED
    _title(pen, x, ROW_C, "rack", "home lab", color)
    w = _pix(pen.draw, x, ROW_C + 26, _figure(f"{online}/{total}"), 8, color or ink)
    pen.draw.text((x + w + 6, ROW_C + 66), "en ligne", font=pen.f["r"], fill=ink, anchor="ls")
    _segs(pen, x, ROW_C + 76, _t("24 dernières heures", "r"))

    compact = len(nodes) > len(XS) - 1
    chart_w = 24 * PITCH
    xs = [XS[1] + i * LAB_PITCH for i in range(LAB_MAX)] if compact else XS[1:]
    width = chart_w if compact else COL_W
    # (label, data key, rows, top of the chart)
    charts = ((("cpu", "cpu", 6, 24), ("mém.", "mem", 4, 80)) if compact
              else (("cpu", "cpu", 6, 26), ("mém.", "mem", 4, 72)))
    axis_y = ROW_C + (122 if compact else 100)
    now = _now_slot(home)
    now_hour = None if now is None else now // 2
    for node, x in zip(nodes, xs):
        up = node.get("online", True)
        _square(pen.draw, x, ROW_C + 6, SQUARE, ink if up else RED, hollow=not up)
        if not up:
            state = _t("hors ligne", "r12", RED)
        elif node.get("disk_pct") is not None:
            c = RED if node.get("disk_bad") else None
            state = _t("disque ", "r12", c) + [(str(node["disk_pct"]), "b12", c), ("%", "r12", c)]
        else:
            state = []
        name_w = width - 13 - _segs_w(pen, state) - 22  # the spaced label runs wider than its text
        _spaced(pen, x + 13, ROW_C + 2, [(pen.fit(node.get("name", ""), "b12", name_w), True, None if up else RED)])
        _segs(pen, x + width, ROW_C + 2, state, right=True)
        for label, key, rows, top in charts:
            values = ((node.get(key) or []) + [None] * 24)[:24]
            top += ROW_C
            _blocks(pen.draw, x, top, values, rows, ink, vmax=100)
            known = [v for v in values if v is not None]
            peak = _t("pic ") + _num(round(max(known)), "%", "12") if known else []
            bottom = top + rows * PITCH
            if compact:
                _segs(pen, x, bottom + 2, _t(label))
                _segs(pen, x + chart_w, bottom + 2, peak, right=True)
            else:
                _side(pen, x + chart_w + 12, bottom, _t(label), peak)
        if now_hour is not None:
            for col in (0, 6, 12, 18):
                _segs(pen, x + col * PITCH, axis_y, _t(f"{(now_hour + col) % 24}h"))
        pen.draw.text((x + chart_w - 10, axis_y), "▲", font=pen.f["r12"], fill=ink)


# ---- the screen -------------------------------------------------------------

def render_arcade(data: dict, theme: str = "dark") -> Image.Image:
    dark = theme != "light"
    paper, ink = ((0, 0, 0), (255, 255, 255)) if dark else ((255, 255, 255), (0, 0, 0))
    img = Image.new("RGB", (WIDTH, HEIGHT), paper)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    pen = _pen(draw, ink)

    home = data.get("home") or {}
    x = _spaced(pen, XS[0], HEAD_Y, [(home.get("date_text", ""), True, None)])
    period = _period_text(home)
    if period:
        _spaced(pen, x + 14, HEAD_Y, [(period[0], False, None), (period[1], True, None)])
    if home.get("last_text"):
        segs = [("maj ", False, None), (home["last_text"], True, None)]
        if home.get("next_text"):
            segs += [(" ► ", False, None), (home["next_text"], True, None)]
        _spaced(pen, WIDTH - XS[0], HEAD_Y, segs, right=True)

    counters = [_draw_electricity]
    if data.get("water_days"):
        counters.append(_draw_water)
    if data.get("production_days") and data.get("production_stats"):
        counters.append(_draw_solar)
    if data.get("crypto"):
        counters.append(_draw_crypto)
    for cx, fn in zip(XS, counters):
        fn(pen, cx, data)
    _draw_alerts(pen, XS[4], data)

    house = [_draw_house]
    if data.get("power_sensors"):
        house.append(_draw_plugs)
    if data.get("plants"):
        house.append(_draw_plants)
    if data.get("unifi"):
        house.append(_draw_network)
    for cx, fn in zip(XS, house):
        fn(pen, cx, data)
    _draw_screen(pen, XS[4], data)

    if (data.get("homelab") or {}).get("nodes"):
        _draw_homelab(pen, data)
    return img
