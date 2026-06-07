"""Render dashboard to 1360×480 bitmap using Pillow (no browser needed).

The EDF consumption chart (stacked HC/HP) fills the left column; the center
column stacks the Eau chart over the solar production chart (full-black bars);
the right column stacks the Crypto panel over the UniFi "Réseau" panel.
"""
import os
import re
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
# No energy threshold anywhere: a chart day is N/A only when it carries no data
# at all (null/zero total — a meter gap, a day the inverter never reported).
MAX_DAYS = 9  # reference column count for the stats banner width
WARN_MARKER_W = 8  # base width of the yellow ▲ warning marker on the crypto grid
# Table under the EDF chart: a section-title header row (Hier | Moy. | HC)
# above the separator line — same band as the Solaire title opposite — then
# a grid (name | yesterday | avg | trend | HC% | sparkline), stacking the
# Cumulus/Lave-linge/Talon rows below. Anchored at the center-column mid-height
# split, mirroring the solar banner geometry.
BOTTOM_ROW_H = 17  # vertical pitch between table rows
BOTTOM_TEXT_GAP = 6  # first row below the separator
# Per-row 7-day sparkline, hugging the table's right edge: 7 thin black bars
# normalised to that row's own max (we read each metric's shape, not cross-row
# magnitudes). The avg+trend column right-aligns just left of this block.
SPARK_BARS = 7
SPARK_BAR_W = 3
SPARK_BAR_GAP = 2
SPARK_W = SPARK_BARS * (SPARK_BAR_W + SPARK_BAR_GAP) - SPARK_BAR_GAP  # = 33
# The sparkline column is a touch wider than the bars themselves, so the graph
# sits inside it with a small margin on each side (never flush to the table edge).
SPARK_COL_W = SPARK_W + 12  # = 45
SPARK_MAX_H = 11  # tallest bar (px), grown up from the row's text baseline
# Bottom-table column anchors as fractions of the table width: name (left),
# yesterday kWh (left), kWh/j (right edge), trend (left, glued to kWh/j),
# HC % (left); the sparkline owns the right edge. The columns are spread out
# except avg+trend, which read as one glued block.
BOTTOM_COL_HIER = 0.30   # left edge of the yesterday-kWh column
BOTTOM_COL_AVG_R = 0.60   # right edge of the "kWh/j" column (right-aligned)
BOTTOM_COL_TREND = 0.615  # left edge of the trend column (glued after kWh/j)
BOTTOM_COL_HC = 0.78     # left edge of the HC % column
# Intraday strip under each chart bar (EDF, Solaire, Eau): a bar-wide (28px)
# mini bar-graph of the day's 48 half-hour slots (mean PAPP / mean PV watts /
# litres), squeezed between the bars' baseline and the day labels. 48 slots
# resampled to 6 sparkline-style bars (4h each) — mean for powers, sum for
# litres; empty buckets leave gaps. Heights are normalised to each chart's
# fixed ceiling so the scales never move — day profiles compare to each other
# and across renders; higher peaks clip.
INTRADAY_BARS = 6  # 6 × (SPARK_BAR_W + SPARK_BAR_GAP) - SPARK_BAR_GAP = 28 = BAR_WIDTH
INTRADAY_H = 14   # tallest intraday bar (px)
INTRADAY_GAP = 4  # gap between the bars' baseline and the strip
INTRADAY_MAX_W = int(os.environ.get("INTRADAY_MAX_W", "3000"))  # W (mean PAPP) at full height
INTRADAY_SOLAR_MAX_W = int(os.environ.get("INTRADAY_SOLAR_MAX_W", "800"))  # W (mean PV) at full height
INTRADAY_WATER_MAX_L = int(os.environ.get("INTRADAY_WATER_MAX_L", "150"))  # L per 4h bucket at full height
SOLAR_HEIGHT = HEIGHT // 2 - 24  # divider for the right column (Crypto top / Réseau bottom)
WATER_SPLIT = HEIGHT // 2  # center column split: Eau (top half) over Solaire (bottom half)

COL_GAP = 8  # écart horizontal entre les colonnes packées (Solaire/EDF, Eau, Crypto)
# Les trois colonnes (largeur de référence MAX_DAYS) sont collées au bord droit,
# l'espace libre est donc reporté tout à gauche au lieu d'être coincé entre Eau et Crypto.
PANEL_LEFT = WIDTH - CHART_LEFT - 3 * (MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP) - 2 * COL_GAP
# = 1360 - 2 - 3*380 - 16 = 202


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

    # Bottom table rows (name | yesterday | avg+trend): Cumulus then Lave-linge
    # (each if enabled) then Talon (core Linky, always shown). It sits directly
    # under the EDF chart, at the center-column mid-height split.
    bottom_rows = _build_bottom_rows(data)

    # Right column (Crypto / Réseau) keeps its own divider, a bit above mid-screen.
    split = SOLAR_HEIGHT
    # Center column (Eau / Solaire) splits at exactly mid-height.
    banner_width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    center_left = PANEL_LEFT + banner_width + COL_GAP

    # EDF consumption chart in the left column, its baseline aligned with the
    # Eau chart's to its right (region bottom = WATER_SPLIT + the top-chart
    # bottom pad). The bottom table opens its own section below, with a title
    # row + separator mirroring the Solaire banner opposite.
    _draw_chart(draw, fonts, days, data.get("stats", {}),
                region_top=0, region_height=WATER_SPLIT + DIVIDER_GAP,
                mode="consumption")

    # Solar production chart in the bottom half of the center column, under the
    # Eau chart — full-black single bars. Sits right at the mid-height split (the
    # chart adds its own small top inset) so the gap to the Eau chart stays tight.
    production_days = data.get("production_days", [])
    if production_days:
        _draw_chart(draw, fonts, production_days, data.get("production_stats", {}),
                    region_top=WATER_SPLIT,
                    region_height=HEIGHT - CHART_BOTTOM - WATER_SPLIT,
                    mode="production", region_left=center_left)

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

    # Water consumption chart in the top half of the center column, above the
    # Solar chart — its own stats banner + daily-litres bars. Sits in its own
    # column so it never overlaps Crypto.
    water_days = data.get("water_days")
    if water_days:
        _draw_water_chart(draw, fonts, water_days, data.get("water_stats", {}),
                          region_top=0, region_bottom=WATER_SPLIT)

    if bottom_rows:
        _draw_bottom_table(draw, fonts, bottom_rows, WATER_SPLIT)

    # "Home" panel in the empty top-left gutter (left of the packed columns):
    # a title banner over the last/next refresh times, then the "Alertes" panel
    # stacked just below it (same gutter).
    home = data.get("home")
    if home:
        home_bottom = _draw_home_panel(draw, fonts, home, region_top=0)
        _draw_alerts_panel(draw, fonts, data.get("alert_board") or [], region_top=home_bottom + 10)

    # UniFi "Réseau" panel in the empty bottom-right column, directly under the
    # crypto grid (same right column), down to the screen bottom.
    unifi = data.get("unifi")
    if unifi:
        _draw_unifi_panel(draw, fonts, unifi,
                          region_top=split + 2,
                          region_bottom=HEIGHT - CHART_BOTTOM)

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


def _draw_water_chart(draw, fonts, water_days, water_stats, region_top, region_bottom) -> None:
    """Draw the dedicated water chart in the top half of the center column, above
    the Solar chart: a stats banner ("Eau" + avg L/j, month total m³, cost €) over
    daily-litres bars (single full-black bars, value in L on top, day label below).
    Mirrors the EDF/Solar look; sits in its own column so it never overlaps the
    Crypto panel anchored to the right edge."""
    font_value = fonts["value"]
    font_label = fonts["label"]

    banner_width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    # Butt up against the Solar chart (which hugs the left edge for banner_width)
    # with a small gap, leaving the right column free for the Crypto panel.
    region_left = PANEL_LEFT + banner_width + COL_GAP

    # Stats banner anchored at the top of the region (same look as chart titles).
    stats_top = region_top + CHART_TOP
    separator_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    items = [[("Eau", "bold", BLACK)],
             [(water_stats.get("avg_text", "N/A"), "bold", BLACK), ("L/j ", "regular", BLACK),
              _trend(water_stats.get("avg_pct", 0), True)],
             [(water_stats.get("month_total_text", "N/A"), "bold", BLACK), ("m³", "regular", BLACK)]]
    cost = water_stats.get("cost_text")
    if cost:
        items.append([(cost, "bold", BLACK), ("€", "regular", BLACK)])
    _draw_stats_bar(draw, fonts, items, region_left, stats_top, banner_width, separator_y)

    # Bars: hug the bottom of the region, day labels below the baseline. The
    # intraday strip is squeezed between the bars' baseline and the labels —
    # same always-reserved space as the EDF chart (litres per 4h bucket, summed,
    # normalised to the fixed INTRADAY_WATER_MAX_L ceiling).
    label_h = draw.textbbox((0, 0), "lun", font=font_label)[3]
    value_h = draw.textbbox((0, 0), "0", font=font_value)[3]
    strip_baseline = region_bottom - label_h - 4
    baseline_y = strip_baseline - INTRADAY_H - INTRADAY_GAP
    bar_max_height = max(20, baseline_y - separator_y - value_h - 14)

    valid = [d["liters"] for d in water_days if d.get("liters") is not None]
    max_l = max(valid, default=1) or 1
    col_width = BAR_WIDTH + BAR_GAP

    for i, d in enumerate(water_days):
        cx = region_left + i * col_width
        label_text = "Auj." if d.get("today") else d.get("day", "").lower()
        lbox = draw.textbbox((0, 0), label_text, font=font_label)
        draw.text((cx + (BAR_WIDTH - (lbox[2] - lbox[0])) // 2, strip_baseline + 4),
                  label_text, fill=BLACK, font=font_label)

        # The day's intraday profile, bar-wide under the bar (drawn even on an
        # N/A day — a daily-total gap can still have samples).
        buckets = _intraday_buckets(d.get("intraday") or [], agg="sum")
        if buckets:
            _draw_intraday(draw, cx, strip_baseline, buckets, INTRADAY_WATER_MAX_L,
                           today=bool(d.get("today")))

        litres = d.get("liters")
        if litres is None:
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
            nbox = draw.textbbox((0, 0), "N/A", font=font_value)
            draw.text((cx + (BAR_WIDTH - (nbox[2] - nbox[0])) // 2, baseline_y - (nbox[3] - nbox[1]) - 6),
                      "N/A", fill=BLACK, font=font_value)
            continue

        bar_h = round((litres / max_l) * bar_max_height)
        if bar_h > 0:
            draw.rectangle([cx, baseline_y - bar_h, cx + BAR_WIDTH - 1, baseline_y - 1], fill=BLACK)
        else:
            # Zero value: draw a baseline line, same marker as N/A.
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
        val_text = f"{litres:.0f}"
        vbox = draw.textbbox((0, 0), val_text, font=font_value)
        draw.text((cx + (BAR_WIDTH - (vbox[2] - vbox[0])) // 2, baseline_y - bar_h - (vbox[3] - vbox[1]) - 10),
                  val_text, fill=BLACK, font=font_value)


def _short_name(name: str, limit: int = 15) -> str:
    name = (name or "").strip()
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _build_bottom_rows(data) -> list:
    """Assemble the bottom table rows: each configured power sensor (Cumulus,
    Lave-linge, …) then Talon (core Linky, always shown). Each row is a 6-column
    tuple (name, yesterday, avg, trend, spark, hc_pct) — a rising value reads as
    bad (red) for these consumption-style metrics; `spark` is the row's 7-day
    series; `hc_pct` is the off-peak share (None hides the cell, always for Talon)."""
    def _sensor_avg(sensor):
        v = sensor.get("avg_kwh")
        return v if v is not None else float("-inf")  # "N/A" (pas d'historique) → en bas

    rows = []
    sensors = sorted(data.get("power_sensors", []), key=_sensor_avg, reverse=True)
    for sensor in sensors:
        hc_pct = sensor.get("hc_pct")
        # A sensor without HC history yet shows an em dash — the value exists
        # but isn't initialised; the Talon row (None below) never gets one.
        hc_seg = ([(f"{hc_pct}", "bold", BLACK), ("%", "regular", BLACK)]
                  if hc_pct is not None else [("—", "regular", BLACK)])
        rows.append((
            [(_short_name(sensor.get("name", "")), "bold", BLACK)],
            [(sensor.get("yesterday_text", "0"), "bold", BLACK), (sensor.get("yesterday_unit", "kWh"), "regular", BLACK)],
            [(sensor.get("avg_text", "0"), "bold", BLACK), (sensor.get("avg_unit", "kWh/j"), "regular", BLACK)],
            [_trend(sensor.get("trend_pct", 0), True)],
            sensor.get("spark"),
            hc_seg,
        ))
    talon = data.get("talon")
    if talon:
        rows.append((
            [("Talon", "bold", BLACK)],
            [(talon.get("yesterday_text", "0"), "bold", BLACK), ("W", "regular", BLACK)],
            [(talon.get("avg_text", "0"), "bold", BLACK), ("W", "regular", BLACK)],
            [_trend(talon.get("trend_pct", 0), True)],
            talon.get("spark"),
            None,
        ))
    return rows


def _draw_bottom_table(draw, fonts, rows, region_top) -> None:
    """Draw the table under the EDF chart as its own section: a title row naming
    the columns (Hier / Moy. / HC) above a 1px separator — same band and
    separator y as the Solaire banner opposite (`region_top` is the mid-height
    split) — then a 6-column grid with one row per metric: name (left),
    yesterday kWh (left), kWh/j (right), trend (left, glued to kWh/j), HC %
    (left), and a 7-day sparkline hugging the right edge (no surrounding box)."""
    width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    x = PANEL_LEFT
    # Mirror _draw_chart's bottom-banner geometry so the title row and separator
    # line up exactly with the Solaire title and its separator.
    header_y = region_top + DIVIDER_GAP
    line_y = header_y + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    y0 = line_y + BOTTOM_TEXT_GAP
    # Sparkline column owns the table's right edge; the bars are centred inside
    # it, leaving a small margin on each side (the column is wider than the graph).
    spark_left = x + width - SPARK_COL_W + (SPARK_COL_W - SPARK_W) // 2
    hier_x = x + round(width * BOTTOM_COL_HIER)
    avg_r = x + round(width * BOTTOM_COL_AVG_R)  # right edge of the kWh/j column
    trend_x = x + round(width * BOTTOM_COL_TREND)
    hc_x = x + round(width * BOTTOM_COL_HC)  # left edge of the HC % column
    text_h = draw.textbbox((0, 0), "Xg", font=fonts["bold"])[3]

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

    def spark(values, sy):
        """7 thin bars normalised to this row's own max, grown up from the text
        baseline. Missing days leave a gap; present days draw at least a 1px tick."""
        if not values:
            return
        present = [v for v in values if v is not None]
        max_v = max(present) if present else 0
        baseline = sy + text_h
        for j, v in enumerate(values):
            if v is None:
                continue
            bx = spark_left + j * (SPARK_BAR_W + SPARK_BAR_GAP)
            h = max(1, round(v / max_v * SPARK_MAX_H)) if max_v > 0 else 1
            draw.rectangle([bx, baseline - h, bx + SPARK_BAR_W - 1, baseline - 1], fill=BLACK)

    # Title row above the separator (section-title band): abbreviated column
    # names, capitalised, each sharing its column's anchor and alignment.
    # Nothing over the name column, the trend or the sparkline.
    put([("Hier", "regular", BLACK)], hier_x, header_y)
    moy = [("Moy.", "regular", BLACK)]
    put(moy, avg_r - seg_w(moy), header_y)
    put([("HC", "regular", BLACK)], hc_x, header_y)

    for i, row in enumerate(rows):
        ry = y0 + i * BOTTOM_ROW_H
        name, hier, avg, trend, series, hc_seg = row
        put(name, x, ry)                      # col 1: name, left
        put(hier, hier_x, ry)                 # col 2: yesterday kWh, left
        put(avg, avg_r - seg_w(avg), ry)      # col 3: kWh/j, right
        put(trend, trend_x, ry)               # col 4: trend, left (glued)
        if hc_seg:                            # col 5: HC %, left (None on Talon)
            put(hc_seg, hc_x, ry)
        spark(series, ry)                     # col 6: sparkline, right edge

    draw.line([(x, line_y), (x + width - 1, line_y)], fill=BLACK, width=1)


def _draw_home_panel(draw, fonts, home, region_top) -> int:
    """Draw the "Home" panel in the empty top-left gutter (left of the packed
    Solar/EDF column): a title banner with a 1px separator, then one line per
    item — label (regular) left, value right-aligned. Line 1: the screen-refresh
    schedule as "HH:MM ► HH:MM" (this refresh and the next, bold times, regular
    arrow). Line 2 (when a live HC<->HP switch has been observed): the current
    tariff period and its switch time left ("HC 15:02", bold time), the other
    period's last switch right ("HP 05:32") once it has been seen too — the
    left side is always the period in effect now. Mirrors the other panels."""
    width = PANEL_LEFT - CHART_LEFT - COL_GAP
    x = CHART_LEFT
    right = x + width

    def put(segments, sx, sy):
        cx = sx
        for text, fk, color in segments:
            draw.text((round(cx), sy), text, fill=color, font=fonts[fk])
            cx += draw.textlength(text, font=fonts[fk])

    def row(left, right_segs, sy):  # label left, value right-aligned to the edge
        put(left, x, sy)
        rw = sum(draw.textlength(t, font=fonts[fk]) for t, fk, _ in right_segs)
        put(right_segs, right - rw, sy)

    line_h = draw.textbbox((0, 0), "Xg", font=fonts["bold"])[3]

    stats_top = region_top + CHART_TOP
    sep_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    _draw_stats_bar(draw, fonts, [[("Home", "bold", BLACK)]], x, stats_top, width, sep_y)

    y = sep_y + 6
    schedule = [
        (home.get("last_text", ""), "bold", BLACK),
        (" ► ", "regular", BLACK),
        (home.get("next_text", ""), "bold", BLACK),
    ]
    row([("Écran", "regular", BLACK)], schedule, y)
    tariff = home.get("tariff")
    if tariff:
        y += line_h
        other = []
        if tariff.get("other_since_text"):
            other = [(tariff["other_period"] + " ", "regular", BLACK),
                     (tariff["other_since_text"], "bold", BLACK)]
        row([(tariff["period"] + " ", "regular", BLACK),
             (tariff["since_text"], "bold", BLACK)], other, y)
    return y + line_h  # bottom of the panel content (for the Alerts panel below)


def _draw_alerts_panel(draw, fonts, rows, region_top) -> None:
    """Draw the alert status board in the top-left gutter, under the Home panel.
    Each monitored domain is its own section: a bold title with a 1px separator
    (same look as the other panel titles) over its lines — one per active item
    (label + unit black, the ▲/▼ arrow + number bold, red for a problem, black
    for a positive note), or a discreet "ok" when the domain is quiet. Domains
    with problems come first (most severe on top). Capped by the screen bottom so
    it never writes out of the region; falls back to a "Tout va bien" section if
    no domain is monitored."""
    width = PANEL_LEFT - CHART_LEFT - COL_GAP
    x = CHART_LEFT

    title_h = draw.textbbox((0, 0), "X", font=fonts["bold"])[3]
    line_h = draw.textbbox((0, 0), "Xg", font=fonts["bold"])[3]
    row_h = line_h + 3
    max_y = HEIGHT - CHART_BOTTOM - line_h
    space_w = draw.textlength(" ", font=fonts["regular"])

    def section_title(label, y):
        """Draw a domain title + its 1px separator; return the y of the first row."""
        draw.text((x, y), label, fill=BLACK, font=fonts["bold"])
        sep = y + title_h + 4
        draw.line([(x, sep), (x + width - 1, sep)], fill=BLACK, width=1)
        return sep + 5

    def num_atom(word):
        """Split a word into a bold numeric part + its glued regular unit, e.g.
        '240 L' -> [('240','bold'),('L','regular')], '0,39€/j' -> [('0,39','bold'),
        ('€/j','regular')]. House rule: numbers bold, unit regular, glued. A word
        with no leading number stays regular."""
        m = re.match(r"^([+\-]?[\d.,]+)\s*(.*)$", word)
        if not m:
            return [(word, "regular")]
        atom = [(m.group(1), "bold")]
        if m.group(2):
            atom.append((m.group(2), "regular"))
        return atom

    def wrap_atoms(atoms, color, y):
        """Draw atoms (each a list of glued (text, font_key) sub-tokens) word-wrapped
        to the panel width in `color`; return the y below the last line drawn."""
        cx = x
        first = True
        for atom in atoms:
            w = sum(draw.textlength(t, font=fonts[fk]) for t, fk in atom)
            if not first and cx + space_w + w > x + width:
                y += row_h
                cx = x
                first = True
                if y > max_y:
                    return y
            if not first:
                cx += space_w
            for t, fk in atom:
                draw.text((round(cx), y), t, fill=color, font=fonts[fk])
                cx += draw.textlength(t, font=fonts[fk])
            first = False
        return y + row_h

    if not rows:
        y = section_title("Alertes", region_top)
        wrap_atoms([[(w, "regular")] for w in "Tout va bien".split()], BLACK, y)
        return

    y = region_top
    for r in rows:
        if y > max_y:
            break
        y = section_title(r["label"], y)
        if r.get("alert"):
            for message, figure, money, good in r["items"]:
                if y > max_y:
                    break
                # A negative alert is written entirely in red; a positive note is
                # all black. Figures follow the house rule (bold number, regular
                # glued unit) via num_atom.
                color = BLACK if good else RED
                atoms = [[(w, "regular")] for w in message.split()]
                if figure:
                    atoms.append(num_atom(figure))
                atoms += [num_atom(w) for w in money.split()]
                y = wrap_atoms(atoms, color, y)
        else:
            y = wrap_atoms([[(w, "regular")] for w in "Rien à signaler".split()], BLACK, y)
        y += 6  # gap before the next domain section


def _draw_unifi_panel(draw, fonts, unifi, region_top, region_bottom) -> None:
    """Draw the "Réseau" panel in the bottom-right column (under the crypto grid):
    a title banner with internet/Wi-Fi health (each with a ▲▼ trend), detail rows
    (latency, Wi-Fi signal, data usage — values with their unit in regular weight,
    glued to the bold number), then a top-4 clients mini-table per
    network (main Wi-Fi first, then IoT) with its client count."""
    width = MAX_DAYS * (BAR_WIDTH + BAR_GAP) - BAR_GAP
    x = WIDTH - CHART_LEFT - width
    right = x + width

    def seg_w(segments):
        return sum(draw.textlength(t, font=fonts[fk]) for t, fk, _ in segments)

    def put(segments, sx, sy):
        cx = sx
        for text, fk, color in segments:
            draw.text((round(cx), sy), text, fill=color, font=fonts[fk])
            cx += draw.textlength(text, font=fonts[fk])

    def row(left, right_segs, sy):  # label left, value right-aligned to the edge
        put(left, x, sy)
        put(right_segs, right - seg_w(right_segs), sy)

    line_h = draw.textbbox((0, 0), "Xg", font=fonts["bold"])[3]
    row_h = line_h + 3

    # --- Title banner: "Réseau" + the two health figures (name + %, with a ▲▼
    # trend), distributed across the width with a 1px separator below it.
    def health(name, pct, color, trend_pct, invert_bad):
        segs = []
        if name:
            segs.append((name + " ", "regular", color))
        segs.append((str(pct), "bold", color))
        segs.append(("%", "regular", color))
        if trend_pct:
            segs += [(" ", "regular", BLACK), _trend(trend_pct, invert_bad)]
        return segs

    isp_color = RED if unifi.get("isp_bad") else BLACK
    wifi_color = RED if unifi.get("wifi_bad") else BLACK
    sep_y = region_top + line_h + 5
    title_items = [
        [("Réseau", "bold", BLACK)],
        health(unifi.get("isp_name", ""), unifi.get("isp_pct", 0), isp_color,
               unifi.get("isp_trend"), invert_bad=False),
        health("WiFi", unifi.get("wifi_pct", 0), wifi_color,
               unifi.get("wifi_trend"), invert_bad=False),
    ]
    _draw_stats_bar(draw, fonts, title_items, x, region_top, width, sep_y)

    # --- Detail rows: label (regular) left, value (bold number + regular unit,
    # no space) right, with an optional ▲▼ trend.
    def value_row(label, value_segs, sy, trend_pct=None, invert_bad=False, neutral=False):
        rs = list(value_segs)
        if trend_pct:
            t = _trend(trend_pct, invert_bad)
            if neutral:  # keep the arrow but force black (no good/bad colour)
                t = (t[0], t[1], BLACK)
            rs += [(" ", "regular", BLACK), t]
        row([(label, "regular", BLACK)], rs, sy)

    y = sep_y + 6
    value_row("Latence", [(unifi.get("latency_val", ""), "bold", BLACK), ("ms", "regular", BLACK)],
              y, unifi.get("latency_trend"), invert_bad=True)
    y += row_h
    value_row("Signal Wi-Fi", [(unifi.get("wifi_exp_text", ""), "bold", BLACK)], y)
    y += row_h
    value_row("Données hier/30j",
              [(unifi.get("usage_hier", ""), "bold", BLACK), ("/", "regular", BLACK),
               (unifi.get("usage_mois", ""), "bold", BLACK), ("Go", "regular", BLACK)],
              y, unifi.get("usage_trend"), neutral=True)
    y += row_h + 4

    # --- Top-4 clients per network (main Wi-Fi first, then IoT): a header
    # (name + "· aujourd'hui" period tag + count) over a separator, then up to
    # four "name … traffic" rows. The traffic is each client's current-session
    # rx+tx, so it reads as today's usage — hence the "aujourd'hui" tag.
    for key in ("main", "iot"):
        net = unifi.get(key) or {}
        rows = net.get("top") or []
        if y + line_h > region_bottom:
            break
        count = net.get("count", 0)
        row([(net.get("label", ""), "bold", BLACK), (" · aujourd'hui", "regular", BLACK)],
            [(str(count), "bold", BLACK), (" clients", "regular", BLACK)], y)
        hdr_y = y + line_h + 3
        draw.line([(x, hdr_y), (right - 1, hdr_y)], fill=BLACK, width=1)
        y = hdr_y + 5
        for name, traffic in rows[:4]:
            if y + line_h > region_bottom:
                break
            row([(name, "regular", BLACK)], [(traffic, "bold", BLACK), ("Go", "regular", BLACK)], y)
            y += row_h
        y += 4


def _bar_total(d: dict, mode: str) -> float:
    if mode == "production":
        return d.get("pv_kwh", 0)
    return d.get("hc_kwh", 0) + d.get("hp_kwh", 0)


def _intraday_buckets(values, agg="mean"):
    """Resample a day's 48 half-hour slots to INTRADAY_BARS buckets (4h each):
    mean for power profiles, sum for volume (litres) profiles. A bucket with
    no sample at all yields None (a gap in the strip)."""
    n = len(values)
    if not n:
        return []
    out = []
    for i in range(INTRADAY_BARS):
        bucket = [v for j, v in enumerate(values)
                  if j * INTRADAY_BARS // n == i and v is not None]
        if not bucket:
            out.append(None)
        else:
            out.append(sum(bucket) if agg == "sum" else sum(bucket) / len(bucket))
    return out


def _draw_intraday(draw, cx, strip_baseline, buckets, ceiling, today=False):
    """One day's intraday mini bar-graph: INTRADAY_BARS sparkline-style bars
    (same 3px/2px geometry as the bottom-table sparklines) grown up from
    `strip_baseline`. Any present value draws at least a 1px tick; a None
    bucket draws the same zero tick (a quiet slot — water meter silent, PV
    asleep — is a zero, not a hole). Only today's buckets after the last
    sample (not elapsed yet) keep a gap. Heights are normalised to the
    chart's fixed `ceiling`; values above it clip to the full INTRADAY_H."""
    last = max((i for i, v in enumerate(buckets) if v is not None), default=-1)
    if last < 0:
        return
    fill_until = last if today else len(buckets) - 1
    for i, v in enumerate(buckets):
        if v is None and i > fill_until:
            continue
        h = max(1, round(min(v or 0.0, ceiling) / ceiling * INTRADAY_H))
        x = cx + i * (SPARK_BAR_W + SPARK_BAR_GAP)
        draw.rectangle([x, strip_baseline - h, x + SPARK_BAR_W - 1, strip_baseline - 1], fill=BLACK)


def _draw_chart(draw, fonts, days, stats, region_top, region_height, mode, region_left=PANEL_LEFT):
    if not days:
        return

    font_value = fonts["value"]
    font_label = fonts["label"]
    # No energy threshold: every positive value draws its bar, however small —
    # only a null day (no data) shows the N/A marker.
    for d in days:
        d["_na"] = _bar_total(d, mode) <= 0

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

    # Intraday strip: squeezed between the bars' baseline and the day labels —
    # the labels keep their y, the bars give up the strip height. The space is
    # always reserved so the layout never jumps as profiles accumulate day
    # after day. Each chart has its own fixed ceiling (W of mean PAPP for
    # consumption, W of mean PV for production).
    has_intraday = mode in ("consumption", "production")
    intraday_ceiling = INTRADAY_MAX_W if mode == "consumption" else INTRADAY_SOLAR_MAX_W
    strip_baseline = baseline_y
    if has_intraday:
        baseline_y -= INTRADAY_H + INTRADAY_GAP
        for d in days:
            d["_intraday_buckets"] = _intraday_buckets(d.get("intraday") or [])

    # Stats banner anchored at top of the region ("titre + bordure").
    value_h = draw.textbbox((0, 0), "0", font=font_value)[3]
    stats_top = region_top + (CHART_TOP if is_top else DIVIDER_GAP)
    separator_y = stats_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    bar_max_height = max(20, baseline_y - separator_y - value_h - 14)

    # --- Bars ---
    for i, d in enumerate(days):
        cx = region_left + i * col_width
        label_text = "Auj." if d.get("today") else d.get("day", "").lower()

        lbox = draw.textbbox((0, 0), label_text, font=font_label)
        lw = lbox[2] - lbox[0]
        draw.text((cx + (BAR_WIDTH - lw) // 2, strip_baseline + 4), label_text, fill=BLACK, font=font_label)

        # The day's intraday profile, bar-wide under the bar (drawn even on an
        # N/A day — a daily-total gap can still have samples).
        if has_intraday and d.get("_intraday_buckets"):
            _draw_intraday(draw, cx, strip_baseline, d["_intraday_buckets"], intraday_ceiling,
                           today=bool(d.get("today")))

        if d["_na"]:
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
            na_box = draw.textbbox((0, 0), "N/A", font=font_value)
            na_w = na_box[2] - na_box[0]
            na_h = na_box[3] - na_box[1]
            draw.text((cx + (BAR_WIDTH - na_w) // 2, baseline_y - na_h - 6), "N/A", fill=BLACK, font=font_value)
            continue

        total = _bar_total(d, mode)
        total_h = round((total / max_kwh) * bar_max_height)

        if total_h <= 0:
            # Zero value: draw a baseline line, same marker as N/A.
            draw.line([(cx, baseline_y - 1), (cx + BAR_WIDTH - 1, baseline_y - 1)], fill=BLACK, width=1)
        elif mode == "production":
            # Single full-black bar (no split data).
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

        val_text = f"{total:.2f}" if mode == "production" else f"{total:.1f}"
        vbox = draw.textbbox((0, 0), val_text, font=font_value)
        vw = vbox[2] - vbox[0]
        vh = vbox[3] - vbox[1]
        val_y = baseline_y - total_h - vh - 10
        draw.text((cx + (BAR_WIDTH - vw) // 2, val_y), val_text, fill=BLACK, font=font_value)

    # --- Stats banner ---
    if stats:
        items = _build_production_items(stats) if mode == "production" else _build_consumption_items(stats)
        if items:
            _draw_stats_bar(draw, fonts, items, region_left, stats_top, banner_width, separator_y)


# Segment = (text, font_key, color). font_key is "bold" (values) or "regular"
# (labels and trends). Trends are regular weight, red when the trend is bad.
def _trend(pct, invert_bad):
    pct = round(pct)  # trends always display whole percents
    if pct == 0:
        return ("—", "regular", BLACK)
    arrow = "▲" if pct > 0 else "▼"
    bad = pct > 0 if invert_bad else pct < 0
    return (f"{arrow}{abs(pct)}%", "regular", RED if bad else BLACK)


def _build_consumption_items(stats):
    # A missing value renders as an em dash with its unit kept — it signals a
    # figure that exists but isn't initialised yet (no data so far).
    def _v(key):
        v = stats.get(key, 0)
        return "—" if v is None else str(v)

    return [
        [("EDF", "bold", BLACK)],
        [(_v('avg_kwh'), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(stats.get("avg_kwh_pct", 0), True)],
        [("HC ", "regular", BLACK), (_v('hc_ratio'), "bold", BLACK), ("% ", "regular", BLACK),
         _trend(stats.get("hc_ratio_pct", 0), False)],
        [(_v('avg_price'), "bold", BLACK), ("€/j ", "regular", BLACK),
         _trend(stats.get("avg_price_pct", 0), True)],
    ]


def _build_production_items(stats):
    # Share of the base load (talon) the solar covers. Always shown — falls back
    # to N/A when the talon has no value yet (no talon_w on the recent days).
    pct = stats.get("talon_cover_pct")
    if pct is not None:
        talon = [("Talon ", "regular", BLACK), (str(pct), "bold", BLACK), ("%", "regular", BLACK)]
    else:
        talon = [("Talon ", "regular", BLACK), ("N/A", "bold", BLACK)]

    # Solar: more is better, so a rising trend is good (black), falling is bad (red).
    # Talon sits to the left of Total.
    return [
        [("Solaire", "bold", BLACK)],
        [(str(stats.get('avg_kwh', 0)), "bold", BLACK), ("kWh/j ", "regular", BLACK),
         _trend(stats.get("avg_kwh_pct", 0), False)],
        talon,
        [("Total ", "regular", BLACK), (str(stats.get('total_kwh', 0)), "bold", BLACK),
         ("kWh   ", "regular", BLACK), (str(stats.get('savings_eur', 0)), "bold", BLACK),
         ("€", "regular", BLACK)],
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
