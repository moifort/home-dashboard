"""Render dashboard to 1360×480 bitmap using Pillow (no browser needed).

Two stacked charts share the same day columns: solar production (top half,
full-black bars) above electricity consumption (bottom half, stacked HC/HP).
"""
import os
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1360
HEIGHT = 480

# Bundled Arial (co-located with the renderer) guarantees identical bitmap
# output on macOS and in Docker.
_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_PATH = os.path.join(_FONTS_DIR, "Arial.ttf")
FONT_BOLD_PATH = os.path.join(_FONTS_DIR, "Arial-Bold.ttf")

BLACK = 0
RED = (255, 0, 0)
YELLOW = (255, 255, 0)  # 4-color warning marker; always outlined in black on white

MARGIN = 2  # screen margin kept on every edge of the e-paper window
CHART_LEFT = MARGIN  # left origin; right-anchored banners use WIDTH - CHART_LEFT
CHART_TOP = MARGIN  # screen top margin
CHART_BOTTOM = MARGIN  # screen bottom margin
DIVIDER_GAP = 8  # spacing kept on each side of the mid-screen divider (not a screen margin)
BAR_WIDTH = 28
BAR_GAP = 16
STATS_FONT_SIZE = 13
VALUE_FONT_SIZE = 13
LABEL_FONT_SIZE = 12
NA_THRESHOLD_KWH = 1.0
PROD_NA_THRESHOLD_KWH = 0.05
MAX_DAYS = 9  # reference column count for the stats banner width
WARN_MARKER_W = 8  # base width of the yellow ▲ warning marker on the crypto grid
# Bottom strip under the EDF chart: a 3-column table (name | yesterday | avg+trend),
# all columns left-aligned, stacking the Cumulus and Talon rows under a single top
# separator line. Its height grows with the number of rows.
BOTTOM_ROW_H = 17  # vertical pitch between table rows
BOTTOM_TOP_GAP = 8  # gap between the chart's day labels and the top separator
BOTTOM_TEXT_GAP = 6  # first row below the separator
SOLAR_HEIGHT = HEIGHT // 2 - 24  # top (solar) chart height; EDF gets the rest (a bit taller)


def _bottom_table_height(n_rows: int) -> int:
    """Height of the bottom strip reserved for an n-row table (0 if empty)."""
    if n_rows == 0:
        return 0
    return BOTTOM_TOP_GAP + BOTTOM_TEXT_GAP + n_rows * BOTTOM_ROW_H + MARGIN


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

    # Bottom table rows (name | yesterday | avg+trend): Cumulus on top (if the
    # integration is enabled) then Talon below (core Linky, always shown). The
    # consumption chart shrinks by the strip height so they don't overlap.
    bottom_rows = _build_bottom_rows(data)
    bottom_h = _bottom_table_height(len(bottom_rows))

    # The split between the two charts sits a bit above mid-screen so the EDF
    # chart is slightly taller than the solar one.
    split = SOLAR_HEIGHT

    # Solar production chart (top) — full-black single bars.
    production_days = data.get("production_days", [])
    if production_days:
        _draw_chart(draw, fonts, production_days, data.get("production_stats", {}),
                    region_top=0, region_height=split, mode="production")

    # Consumption chart (bottom, minus the table strip) — stacked HC/HP bars.
    _draw_chart(draw, fonts, days, data.get("stats", {}),
                region_top=split, region_height=HEIGHT - split - bottom_h, mode="consumption")

    # Crypto title-style banner in the empty top-right space (aligned with the
    # solar title); the bottom table sits below the EDF chart, full chart width.
    crypto = data.get("crypto")
    crypto_bottom = 0
    if crypto:
        crypto_bottom = _draw_crypto_banner(draw, fonts, crypto, 0)

    # Grid snapshot chart under the Crypto title (top-right quadrant), down to
    # the gap above the chart divider. Drawn black & white.
    crypto_grid = data.get("crypto_grid")
    if crypto_grid:
        _draw_crypto_grid(draw, fonts, crypto_grid,
                          region_top=(crypto_bottom or 12) - 2,
                          region_bottom=split - DIVIDER_GAP)

    if bottom_rows:
        _draw_bottom_table(draw, fonts, bottom_rows, bottom_h)

    return img


def _draw_right_banner(draw, fonts, items, region_top) -> int:
    """Draw a title-style banner (same look as the chart titles) right-aligned
    in the empty space beside the charts. Returns the y below its separator."""
    stats_top = region_top + CHART_TOP
    separator_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    banner_width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    x = WIDTH - CHART_LEFT - banner_width
    _draw_stats_bar(draw, fonts, items, x, stats_top, banner_width, separator_y)
    return separator_y + 6


def _draw_crypto_banner(draw, fonts, crypto, region_top) -> int:
    profit_color = BLACK if crypto.get("profit_positive", True) else RED
    items = [
        [("Crypto", "bold", BLACK)],
        # Profit grouped behind a "Profits" label: signed % return + signed amount.
        [("Profits ", "regular", profit_color), (crypto.get("pct_text", "0"), "bold", profit_color),
         ("% ", "regular", profit_color), (crypto.get("profit_text", ""), "bold", profit_color)],
    ]
    # Alpha (excess return vs buy-and-hold): black when ahead, red when behind.
    alpha_text = crypto.get("alpha_text", "")
    if alpha_text:
        alpha_color = BLACK if crypto.get("alpha_positive", True) else RED
        items.append([("Alpha ", "regular", alpha_color), (alpha_text, "bold", alpha_color),
                      ("%", "regular", alpha_color)])
    items.append([(crypto.get("portfolio_text", ""), "bold", BLACK)])
    if crypto.get("sandbox"):
        items.append([("SANDBOX", "bold", BLACK)])
    return _draw_right_banner(draw, fonts, items, region_top)


def _dashed_h_line(draw, x0, x1, y, on=2, off=3, fill=BLACK):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + on, x1), y)], fill=fill, width=1)
        x += on + off


def _grid_label(price: float) -> str:
    """Price with a $ prefix and plain-space thousands separator (Arial-safe)."""
    return f"${price:,.0f}".replace(",", chr(32))


def _draw_crypto_grid(draw, fonts, grid, region_top, region_bottom) -> None:
    """Render the trading grid snapshot under the Crypto banner (top-right):
    horizontal dashed grid levels with left price labels, the price line over
    the period, and a 'now' marker dot with the current price. Black & white."""
    lower = grid.get("lower")
    upper = grid.get("upper")
    levels = grid.get("levels", 0)
    if lower is None or upper is None or upper <= lower or levels < 1:
        return

    label_font = fonts["label"]
    value_font = fonts["bold"]

    banner_width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    region_left = WIDTH - CHART_LEFT - banner_width
    region_right = WIDTH - CHART_LEFT

    # Level prices, top (upper) to bottom (lower).
    if levels > 1:
        step = (upper - lower) / (levels - 1)
        level_prices = [upper - i * step for i in range(levels)]
    else:
        level_prices = [lower]

    # Left gutter: the price label, sized to the widest one. A warning marker
    # (yellow ▲) sits right after the label; it only shortens its own level's
    # line (below), so the other grid lines keep their full width.
    skips = grid.get("skips") or []
    half = WARN_MARKER_W // 2
    mark_pad = 3
    label_x = region_left + 2
    max_label_w = max(draw.textlength(_grid_label(p), font=label_font) for p in level_prices)
    marker_cx = round(label_x + max_label_w + mark_pad + half)
    plot_left = round(label_x + max_label_w + 8)
    plot_right = region_right - 2

    label_h = draw.textbbox((0, 0), "0", font=label_font)[3]
    pad = label_h // 2 + 2
    plot_top = region_top + pad
    plot_bottom = region_bottom - pad
    if plot_bottom <= plot_top or plot_right <= plot_left:
        return

    span_y = upper - lower
    plot_h = plot_bottom - plot_top

    def price_y(p):
        return round(plot_bottom - (p - lower) / span_y * plot_h)

    # Levels carrying a warning marker: only that line starts after the marker,
    # so a skip never shifts the whole grid (the others keep their full width).
    marker_end = marker_cx + half + 5
    marked_ys = {min(plot_bottom, max(plot_top, price_y(s["price"])))
                 for s in skips if s.get("price") is not None}

    # --- Grid levels: fine dotted line + label (no marker dot) ---
    for p in level_prices:
        y = price_y(p)
        line_start = marker_end if y in marked_ys else plot_left
        _dashed_h_line(draw, line_start, plot_right, y, on=1, off=8)
        draw.text((label_x, y - label_h // 2 - 1), _grid_label(p), fill=BLACK, font=label_font)

    # --- Price line + 'now' marker ---
    points = grid.get("points") or []
    if points:
        t0 = points[0][0]
        t_last = points[-1][0]
        # 6% right buffer so the 'now' marker leaves room for its label.
        t_span = (t_last - t0) * 1.06 or 1
        plot_w = plot_right - plot_left

        def clamp_y(p):
            return min(plot_bottom, max(plot_top, price_y(p)))

        def time_x(t):
            return round(plot_left + (t - t0) / t_span * plot_w)

        line = [(time_x(t), clamp_y(p)) for t, p in points]
        if len(line) > 1:
            draw.line(line, fill=BLACK, width=1)

        current = grid.get("current_price")
        if current is not None:
            nx = time_x(t_last)
            ny = clamp_y(current)
            draw.ellipse([nx - 3, ny - 3, nx + 3, ny + 3], fill=BLACK)
            # Current price label, centered above the dot, kept inside the region.
            ctext = grid.get("current_price_text", "")
            if ctext:
                cw = draw.textlength(ctext, font=value_font)
                ch = draw.textbbox((0, 0), ctext, font=value_font)[3]
                cx = max(plot_left, min(round(nx - cw / 2), region_right - cw))
                cy = max(plot_top, ny - ch - 6)
                draw.text((cx, cy), ctext, fill=BLACK, font=value_font)

    # --- Warning markers: a full-yellow ▲ right after each skipped level's
    # Y-axis price label (insufficient-funds, half-spacing or max-orders —
    # mirrors the iOS grid badges). Flat fill, no outline.
    seen_y = set()
    for skip in skips:
        price = skip.get("price")
        if price is None:
            continue
        y = min(plot_bottom, max(plot_top, price_y(price)))
        if y in seen_y:  # one marker per level even if both sides were skipped
            continue
        seen_y.add(y)
        draw.polygon(
            [(marker_cx, y - half), (marker_cx - half, y + half), (marker_cx + half, y + half)],
            fill=YELLOW,
        )


def _build_bottom_rows(data) -> list:
    """Assemble the bottom table rows: Cumulus (if enabled) then Talon (core
    Linky, always shown). Each row is (name, yesterday, avg+trend) — a rising
    value reads as bad (red) for both consumption-style metrics."""
    rows = []
    cumulus = data.get("cumulus")
    if cumulus:
        rows.append((
            [("Cumulus", "bold", BLACK)],
            [(cumulus.get("yesterday_text", "0"), "bold", BLACK), ("kWh hier", "regular", BLACK)],
            [(cumulus.get("avg_text", "0"), "bold", BLACK), ("kWh/j ", "regular", BLACK),
             _trend(cumulus.get("trend_pct", 0), True)],
        ))
    talon = data.get("talon")
    if talon:
        rows.append((
            [("Talon", "bold", BLACK)],
            [(talon.get("yesterday_text", "0"), "bold", BLACK), ("W hier", "regular", BLACK)],
            [(talon.get("avg_text", "0"), "bold", BLACK), ("W ", "regular", BLACK),
             _trend(talon.get("trend_pct", 0), True)],
        ))
    return rows


def _draw_bottom_table(draw, fonts, rows, bottom_h) -> None:
    """Draw the bottom table below the EDF chart: a 3-column grid with one row per
    metric. The name and yesterday columns are left-aligned at fixed thirds; the
    average+trend column is right-aligned to the table's right edge. A single 1px
    separator line sits above the rows, dividing them from the chart's day labels
    (no surrounding box)."""
    width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    x = CHART_LEFT
    line_y = HEIGHT - bottom_h + BOTTOM_TOP_GAP
    y0 = line_y + BOTTOM_TEXT_GAP
    col_w = width // 3

    def seg_w(segments):
        return sum(draw.textbbox((0, 0), t, font=fonts[fk])[2]
                   - draw.textbbox((0, 0), t, font=fonts[fk])[0] for t, fk, _ in segments)

    def put(segments, sx, sy):
        cx = sx
        for text, font_key, color in segments:
            font = fonts[font_key]
            draw.text((cx, sy), text, fill=color, font=font)
            box = draw.textbbox((0, 0), text, font=font)
            cx += box[2] - box[0]

    for i, row in enumerate(rows):
        ry = y0 + i * BOTTOM_ROW_H
        left, mid, right = row
        put(left, x, ry)
        put(mid, x + col_w, ry)
        put(right, x + width - seg_w(right), ry)  # right-aligned to the table edge

    draw.line([(x, line_y), (x + width - 1, line_y)], fill=BLACK, width=1)


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

    # The top chart hugs the screen top and leaves a gap above the divider; the
    # bottom chart sits below the divider and hugs the screen bottom.
    is_top = region_top == 0
    label_h = draw.textbbox((0, 0), "lun", font=font_label)[3]
    bottom_pad = DIVIDER_GAP if is_top else CHART_BOTTOM
    baseline_y = region_top + region_height - bottom_pad - label_h - 4

    # Stats banner anchored at top of the region ("titre + bordure").
    value_h = draw.textbbox((0, 0), "0", font=font_value)[3]
    stats_top = region_top + (CHART_TOP if is_top else DIVIDER_GAP)
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
    items = [
        [("Solaire", "bold", BLACK)],
        [(str(stats.get('avg_kwh', 0)), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(stats.get("avg_kwh_pct", 0), False)],
        [("Total ", "regular", BLACK), (str(stats.get('total_kwh', 0)), "bold", BLACK),
         ("kWh   ", "regular", BLACK), (str(stats.get('savings_eur', 0)), "bold", BLACK),
         ("€", "regular", BLACK)],
    ]
    # Share of the base load (talon) the solar covers, when the talon is known.
    pct = stats.get("talon_cover_pct")
    if pct is not None:
        items.append([("Talon ", "regular", BLACK), (str(pct), "bold", BLACK), ("%", "regular", BLACK)])
    return items


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
