"""Render dashboard to 1360×480 bitmap using Pillow (no browser needed).

Two stacked charts share the same day columns: solar production (top half,
full-black bars) above electricity consumption (bottom half, stacked HC/HP).
"""
import os
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1360
HEIGHT = 480

# Bundled Arial guarantees identical bitmap output on macOS and in Docker.
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_PATH = os.path.join(_FONT_DIR, "Arial.ttf")
FONT_BOLD_PATH = os.path.join(_FONT_DIR, "Arial-Bold.ttf")

BLACK = 0
RED = (255, 0, 0)

CHART_LEFT = 8
CHART_BOTTOM = 12
BAR_WIDTH = 28
BAR_GAP = 16
STATS_FONT_SIZE = 13
VALUE_FONT_SIZE = 13
LABEL_FONT_SIZE = 12
NA_THRESHOLD_KWH = 1.0
PROD_NA_THRESHOLD_KWH = 0.05
MAX_DAYS = 9  # reference column count for the stats banner width


def render_dashboard(data: dict) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"

    fonts = {
        "regular": ImageFont.truetype(FONT_PATH, STATS_FONT_SIZE),
        "bold": ImageFont.truetype(FONT_BOLD_PATH, STATS_FONT_SIZE),
        "value": ImageFont.truetype(FONT_BOLD_PATH, VALUE_FONT_SIZE),
        "label": ImageFont.truetype(FONT_PATH, LABEL_FONT_SIZE),
    }

    days = data.get("days", [])
    half = HEIGHT // 2

    # Solar production chart (top half) — full-black single bars.
    production_days = data.get("production_days", [])
    if production_days:
        _draw_chart(draw, fonts, production_days, data.get("production_stats", {}),
                    region_top=0, region_height=half, mode="production")

    # Consumption chart (bottom half) — stacked HC/HP bars.
    _draw_chart(draw, fonts, days, data.get("stats", {}),
                region_top=half, region_height=half, mode="consumption")

    # Title-style banners stacked in the empty top-right space.
    region_top = 0
    crypto = data.get("crypto")
    if crypto:
        region_top = _draw_crypto_banner(draw, fonts, crypto, region_top)
    cumulus = data.get("cumulus")
    if cumulus:
        _draw_cumulus_banner(draw, fonts, cumulus, region_top)

    return img


def _draw_right_banner(draw, fonts, items, region_top) -> int:
    """Draw a title-style banner (same look as the chart titles) right-aligned
    in the empty space beside the charts. Returns the y below its separator."""
    stats_top = region_top + 4
    separator_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    banner_width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    x = WIDTH - CHART_LEFT - banner_width
    _draw_stats_bar(draw, fonts, items, x, stats_top, banner_width, separator_y)
    return separator_y + 6


def _draw_crypto_banner(draw, fonts, crypto, region_top) -> int:
    pct_color = BLACK if crypto.get("profit_positive", True) else RED
    items = [
        [("Crypto", "bold", BLACK)],
        [(crypto.get("pct_text", "0"), "bold", pct_color), ("%", "regular", pct_color)],
        [(crypto.get("profit_text", ""), "bold", BLACK)],
        [(crypto.get("portfolio_text", ""), "bold", BLACK)],
    ]
    if crypto.get("sandbox"):
        items.append([("SANDBOX", "bold", BLACK)])
    return _draw_right_banner(draw, fonts, items, region_top)


def _draw_cumulus_banner(draw, fonts, cumulus, region_top) -> int:
    items = [
        [("Cumulus", "bold", BLACK)],
        [(cumulus.get("today_text", "0"), "bold", BLACK), ("kWh auj.", "regular", BLACK)],
        [(cumulus.get("avg_text", "0"), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(cumulus.get("trend_pct", 0), True)],
    ]
    return _draw_right_banner(draw, fonts, items, region_top)


def _bar_total(d: dict, mode: str) -> float:
    if mode == "production":
        return d.get("pv_kwh", 0)
    return d.get("hc_kwh", 0) + d.get("hp_kwh", 0)


def _draw_chart(draw, fonts, days, stats, region_top, region_height, mode):
    if not days:
        return

    font_value = fonts["value"]
    font_label = fonts["label"]
    na_threshold = PROD_NA_THRESHOLD_KWH if mode == "production" else NA_THRESHOLD_KWH

    for d in days:
        d["_na"] = _bar_total(d, mode) < na_threshold

    valid_days = [d for d in days if not d["_na"]]
    max_kwh = max((_bar_total(d, mode) for d in valid_days), default=1) or 1

    col_width = BAR_WIDTH + BAR_GAP
    chart_width = len(days) * col_width - BAR_GAP
    # Keep the stats banner a constant width so it stays readable and aligned
    # even when a chart has few columns (e.g. solar history early on).
    banner_width = max(chart_width, MAX_DAYS * col_width - BAR_GAP)

    label_h = draw.textbbox((0, 0), "lun", font=font_label)[3]
    baseline_y = region_top + region_height - CHART_BOTTOM - label_h - 4

    # Stats banner anchored at top of the region ("titre + bordure").
    value_h = draw.textbbox((0, 0), "0", font=font_value)[3]
    stats_top = region_top + 4
    separator_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    bar_max_height = max(20, baseline_y - separator_y - value_h - 14)

    # --- Bars ---
    for i, d in enumerate(days):
        cx = CHART_LEFT + i * col_width
        label_text = d.get("day", "").lower()

        lbox = draw.textbbox((0, 0), label_text, font=font_label)
        lw = lbox[2] - lbox[0]
        draw.text((cx + (BAR_WIDTH - lw) // 2, baseline_y + 4), label_text, fill=BLACK, font=font_label)

        if d["_na"]:
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
            na_box = draw.textbbox((0, 0), "N/A", font=font_value)
            na_w = na_box[2] - na_box[0]
            na_h = na_box[3] - na_box[1]
            draw.text((cx + (BAR_WIDTH - na_w) // 2, baseline_y - na_h - 6), "N/A", fill=BLACK, font=font_value)
            continue

        total = _bar_total(d, mode)
        total_h = round((total / max_kwh) * bar_max_height)

        if mode == "production":
            # Single full-black bar (no split data).
            if total_h > 0:
                draw.rectangle([cx, baseline_y - total_h, cx + BAR_WIDTH - 1, baseline_y - 1], fill=BLACK)
        else:
            # Stacked bar: HP at bottom (black), HC on top (2px top border).
            hp = d.get("hp_kwh", 0)
            hp_h = round((hp / max_kwh) * bar_max_height)
            hc_h = total_h - hp_h
            bar_bottom = baseline_y
            if hp_h > 0:
                draw.rectangle([cx, bar_bottom - hp_h, cx + BAR_WIDTH - 1, bar_bottom - 1], fill=BLACK)
                bar_bottom -= hp_h
            if hc_h > 0:
                hc_top = bar_bottom - hc_h
                draw.rectangle([cx, hc_top, cx + BAR_WIDTH - 1, hc_top + 1], fill=BLACK)

        val_text = f"{total:.1f}"
        vbox = draw.textbbox((0, 0), val_text, font=font_value)
        vw = vbox[2] - vbox[0]
        vh = vbox[3] - vbox[1]
        val_y = baseline_y - total_h - vh - 10
        draw.text((cx + (BAR_WIDTH - vw) // 2, val_y), val_text, fill=BLACK, font=font_value)

    # --- Stats banner ---
    if stats:
        items = _build_production_items(stats) if mode == "production" else _build_consumption_items(stats)
        if items:
            _draw_stats_bar(draw, fonts, items, CHART_LEFT, stats_top, banner_width, separator_y)


# Segment = (text, font_key, color). font_key is "bold" (values) or "regular"
# (labels and trends). Trends are regular weight, red when the trend is bad.
def _trend(pct, invert_bad):
    if pct == 0:
        return ("—", "regular", BLACK)
    arrow = "▲" if pct > 0 else "▼"
    bad = pct > 0 if invert_bad else pct < 0
    return (f"{arrow}{abs(pct)}%", "regular", RED if bad else BLACK)


def _build_consumption_items(stats):
    return [
        [("EDF", "bold", BLACK)],
        [(str(stats.get('avg_kwh', 0)), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(stats.get("avg_kwh_pct", 0), True)],
        [("HC ", "regular", BLACK), (str(stats.get('hc_ratio', 0)), "bold", BLACK), ("% ", "regular", BLACK),
         _trend(stats.get("hc_ratio_pct", 0), False)],
        [(str(stats.get('avg_price', 0)), "bold", BLACK), ("€/j ", "regular", BLACK),
         _trend(stats.get("avg_price_pct", 0), True)],
    ]


def _build_production_items(stats):
    # Solar: more is better, so a rising trend is good (black), falling is bad (red).
    return [
        [("Solaire", "bold", BLACK)],
        [(str(stats.get('avg_kwh', 0)), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(stats.get("avg_kwh_pct", 0), False)],
        [(str(stats.get('savings_eur', 0)), "bold", BLACK), ("€   ", "regular", BLACK),
         (str(stats.get('total_kwh', 0)), "bold", BLACK), ("kWh total", "regular", BLACK)],
    ]


def _draw_stats_bar(draw, fonts, items, x, y, width, line_y):
    rendered = []
    total_w = 0
    for segments in items:
        item_parts = []
        item_w = 0
        for text, font_key, color in segments:
            font = fonts[font_key]
            box = draw.textbbox((0, 0), text, font=font)
            w = box[2] - box[0]
            item_parts.append((text, font, color, w))
            item_w += w
        rendered.append((item_parts, item_w))
        total_w += item_w

    if len(rendered) > 1:
        gap = (width - total_w) // (len(rendered) - 1)
    else:
        gap = 0

    cx = x
    for item_parts, item_w in rendered:
        for text, font, color, w in item_parts:
            draw.text((cx, y), text, fill=color, font=font)
            cx += w
        cx += gap

    # 1px separator line under the banner.
    draw.line([(x, line_y), (x + width - 1, line_y)], fill=BLACK, width=1)
