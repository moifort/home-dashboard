"""Render dashboard to 1360×480 bitmap using Pillow (no browser needed)."""
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1360
HEIGHT = 480

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

import os
if not os.path.exists(FONT_PATH):
    FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
    FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

BLACK = 0
RED = (255, 0, 0)

CHART_LEFT = 20
CHART_BOTTOM = 12
BAR_WIDTH = 28
BAR_GAP = 16
BAR_MAX_HEIGHT = 180
STATS_FONT_SIZE = 13
VALUE_FONT_SIZE = 13
LABEL_FONT_SIZE = 12
NA_THRESHOLD_KWH = 1.0


def render_dashboard(data: dict) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"

    font_regular = ImageFont.truetype(FONT_PATH, STATS_FONT_SIZE)
    font_bold = ImageFont.truetype(FONT_BOLD_PATH, STATS_FONT_SIZE)
    font_value = ImageFont.truetype(FONT_BOLD_PATH, VALUE_FONT_SIZE)
    font_label = ImageFont.truetype(FONT_PATH, LABEL_FONT_SIZE)

    days = data.get("days", [])
    stats = data.get("stats", {})

    for d in days:
        total = d.get("hc_kwh", 0) + d.get("hp_kwh", 0)
        d["_na"] = total < NA_THRESHOLD_KWH

    valid_days = [d for d in days if not d["_na"]]
    max_kwh = max((d.get("hc_kwh", 0) + d.get("hp_kwh", 0) for d in valid_days), default=1)
    if max_kwh == 0:
        max_kwh = 1

    col_width = BAR_WIDTH + BAR_GAP
    chart_width = len(days) * col_width - BAR_GAP

    # baseline_y = bottom of bars, labels go below
    label_h = draw.textbbox((0, 0), "lun", font=font_label)[3]
    baseline_y = HEIGHT - CHART_BOTTOM - label_h - 4

    # --- Bars ---
    for i, d in enumerate(days):
        cx = CHART_LEFT + i * col_width
        label_text = d.get("day", "").lower()

        # Day label (regular, 12px) — 4px below bar bottom
        lbox = draw.textbbox((0, 0), label_text, font=font_label)
        lw = lbox[2] - lbox[0]
        draw.text((cx + (BAR_WIDTH - lw) // 2, baseline_y + 4), label_text, fill=BLACK, font=font_label)

        if d["_na"]:
            # N/A day: thin line + "N/A" label
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
            na_box = draw.textbbox((0, 0), "N/A", font=font_value)
            na_w = na_box[2] - na_box[0]
            na_h = na_box[3] - na_box[1]
            draw.text((cx + (BAR_WIDTH - na_w) // 2, baseline_y - na_h - 6), "N/A", fill=BLACK, font=font_value)
            continue

        hc = d.get("hc_kwh", 0)
        hp = d.get("hp_kwh", 0)
        total = hc + hp
        total_h = round((total / max_kwh) * BAR_MAX_HEIGHT)
        hp_h = round((hp / max_kwh) * BAR_MAX_HEIGHT)
        hc_h = total_h - hp_h

        # Stacked bar: HP at bottom (black), HC on top (2px top border)
        bar_bottom = baseline_y
        if hp_h > 0:
            draw.rectangle([cx, bar_bottom - hp_h, cx + BAR_WIDTH - 1, bar_bottom - 1], fill=BLACK)
            bar_bottom -= hp_h
        if hc_h > 0:
            hc_top = bar_bottom - hc_h
            draw.rectangle([cx, hc_top, cx + BAR_WIDTH - 1, hc_top + 1], fill=BLACK)

        # Value above bar (bold, 13px) — 8px between bar top and underline
        val_text = f"{total:.1f}"
        vbox = draw.textbbox((0, 0), val_text, font=font_value)
        vw = vbox[2] - vbox[0]
        vh = vbox[3] - vbox[1]
        val_y = baseline_y - total_h - vh - 10
        draw.text((cx + (BAR_WIDTH - vw) // 2, val_y), val_text, fill=BLACK, font=font_value)

    # --- Stats bar (bold, 13px, space-between) ---
    if stats.get("avg_kwh") is not None:
        items = _build_stat_items(stats)

        # Position: above highest bar value
        highest_total = max((d.get("hc_kwh", 0) + d.get("hp_kwh", 0) for d in days), default=0)
        highest_h = round((highest_total / max_kwh) * BAR_MAX_HEIGHT)
        vbox = draw.textbbox((0, 0), "0", font=font_value)
        vh = vbox[3] - vbox[1]
        stats_bottom = baseline_y - highest_h - vh - 4 - 42

        _draw_stats_bar(draw, font_bold, font_regular, items, CHART_LEFT, stats_bottom, chart_width)

    return img


def _build_stat_items(stats):
    items = []

    def pct_info(pct, invert_bad):
        if pct == 0:
            return "—", False
        arrow = "▲" if pct > 0 else "▼"
        bad = pct > 0 if invert_bad else pct < 0
        return f"{arrow}{abs(pct)}%", bad

    avg_pct_text, avg_pct_bad = pct_info(stats.get("avg_kwh_pct", 0), True)
    items.append([(str(stats['avg_kwh']), True), ("kWh/j  ", False), (avg_pct_text, avg_pct_bad)])

    hc_pct_text, hc_pct_bad = pct_info(stats.get("hc_ratio_pct", 0), False)
    items.append([("HC ", False), (str(stats.get('hc_ratio', 0)), True), ("%  ", False), (hc_pct_text, hc_pct_bad)])

    price_pct_text, price_pct_bad = pct_info(stats.get("avg_price_pct", 0), True)
    items.append([(str(stats.get('avg_price', 0)), True), ("€/j  ", False), (price_pct_text, price_pct_bad)])

    return items


def _draw_stats_bar(draw, font_bold, font_regular, items, x, y, width):
    rendered = []
    total_w = 0
    for segments in items:
        item_parts = []
        item_w = 0
        for text, flag in segments:
            if flag is True:
                font = font_bold
                color = BLACK
            elif flag is False:
                font = font_regular
                color = BLACK
            else:
                font = font_bold
                color = RED if flag else BLACK
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

    # 2px separator line — 8px below text
    sbox = draw.textbbox((0, 0), "X", font=font_bold)
    line_y = y + (sbox[3] - sbox[1]) + 8
    draw.line([(x, line_y), (x + width - 1, line_y)], fill=BLACK, width=1)
