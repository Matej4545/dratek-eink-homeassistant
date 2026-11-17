"""Front door, 2.9" BWRY: next trams (line + time) in a narrow column, weather in the rest.

Departures are filtered to what you actually take: ``destinations`` keeps only
those directions (end stops; part of a name is enough, diacritics and case do
not matter), ``lines`` only those lines, and ``min_minutes`` hides departures
leaving in less than that many minutes. Times are clock times (red = live).

Weather fills the rest, every number with its unit: the temperature now and
feels-like in °C, the day's max/min, and a chart of the next ``hours`` hours -
red temperature line (°C, left axis) over yellow precipitation bars (mm per
hour, right axis; % chance if the forecast has no amounts) - and a summary of
when it rains and how much. ``alerts`` entities (windows, doors, lights) show
in a red band while they are on or open.
"""

from __future__ import annotations

import math

from dratek_screen import (WEATHER_ICONS, active_alerts, day_outlook, filter_departures, nice_range, num,
                           truncate)

TITLE = "Dveře: tramvaje + počasí (2,9\")"
SDK_TYPE = 46
INTERVAL = 600
OPTIONS = {
    "stop_id": "",
    "title": "",
    "destinations": "",   # e.g. ["Lehovec", "Starý Hloubětín"] - empty = all directions
    "exclude": "",
    "lines": "",          # e.g. ["8", "3"] - empty = all lines
    "min_minutes": 5,     # do not show departures leaving in less than this many minutes
    "weather": "weather.forecast_home",
    "hours": 12,
    "alerts": "",         # e.g. ["binary_sensor.balcony_door", "light.hallway"]
}

DEP_W = 70  # departures column width


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    alerts = active_alerts(ctx, ctx.options["alerts"])
    bottom = H - 18 if alerts else H

    _departures(ctx, img, d, DEP_W, bottom)
    d.line((DEP_W + 2, 2, DEP_W + 2, bottom - 3), fill=ctx.BLACK)
    _weather(ctx, img, d, DEP_W + 6, W - 1, bottom)

    if alerts:
        f = ctx.font
        d.rectangle((0, H - 17, W, H), fill=ctx.accent)
        ctx.paste_icon(img, "alert-circle-outline", (3, H - 15), 13, ctx.WHITE)
        text = truncate(d, "Otevřeno: " + ", ".join(alerts), f(12, 700), W - 24)
        d.text((20, H - 9), text, font=f(12, 700), fill=ctx.WHITE, anchor="lm")
    return img


def _departures(ctx, img, d, width, bottom):
    o, ink, f = ctx.options, ctx.BLACK, ctx.font
    d.rectangle((0, 0, width, 15), fill=ink)
    ctx.paste_icon(img, "tram", (1, 1), 13, ctx.WHITE)
    stop_id = str(o["stop_id"]).strip()
    if not stop_id:
        d.text((16, 8), "stop_id?", font=f(10, 700), fill=ctx.WHITE, anchor="lm")
        return
    board = ctx.transit(stop_id, 12)
    title = str(o["title"] or board.get("stop_name") or "")
    d.text((16, 8), truncate(d, title, f(10, 700), width - 17), font=f(10, 700), fill=ctx.WHITE, anchor="lm")

    rows = filter_departures(board.get("departures"), destinations=o["destinations"], exclude=o["exclude"],
                             lines=o["lines"], min_minutes=int(o["min_minutes"] or 0))
    if not rows:
        d.text((width // 2, (16 + bottom) // 2), "–", font=f(16, 700), fill=ink, anchor="mm")
        return
    count = max(1, min(5, (bottom - 17) // 21))
    row_h = (bottom - 17) / count
    for i, dep in enumerate(rows[:count]):
        mid = round(17 + (i + 0.5) * row_h)
        line = str(dep.get("line") or "–")
        line_font = f(13, 800) if len(line) <= 2 else f(11, 800)
        d.rectangle((0, mid - 9, 23, mid + 8), fill=ink)
        d.text((12, mid), line, font=line_font, fill=ctx.WHITE, anchor="mm")
        d.text((width, mid), str(dep.get("departure") or ""), font=f(16, 700),
               fill=ctx.accent if dep.get("realtime") else ink, anchor="rm")


def _weather(ctx, img, d, x0, x1, bottom):
    o, ink, f = ctx.options, ctx.BLACK, ctx.font
    weather = str(o["weather"])
    if ctx.entity(weather) is None:
        d.text(((x0 + x1) // 2, bottom // 2), f"{weather}?", font=f(12, 600), fill=ink, anchor="mm")
        return
    condition = ctx.state(weather, "cloudy")
    temp = ctx.num(weather, attr="temperature")
    feels = ctx.num(weather, attr="apparent_temperature")
    outlook = day_outlook(ctx.forecast(weather, "hourly"), ctx.now, hours=int(o["hours"]), to_local=ctx.dt,
                          current_temperature=temp)

    # --------------------------------------------------- now: 4 °C, max/min
    ctx.paste_icon(img, WEATHER_ICONS.get(condition, "weather-cloudy"), (x0, 2), 30, ctx.accent)
    value = num(temp)
    big = f(36, 700)
    d.text((x0 + 33, 33), value, font=big, fill=ink, anchor="ls")
    d.text((x0 + 35 + d.textlength(value, font=big), 33), "°C", font=f(15, 700), fill=ink, anchor="ls")
    if feels is not None:
        d.text((x1, 1), f"pocitově {num(feels)} °C", font=f(10), fill=ink, anchor="ra")
    if outlook.hi is not None:
        d.text((x1, 13), f"max {num(outlook.hi)} °C", font=f(11, 700), fill=ctx.accent, anchor="ra")
        d.text((x1, 25), f"min {num(outlook.lo)} °C", font=f(11, 700), fill=ink, anchor="ra")

    # --------------------------------------------- chart: °C line, mm bars
    labels_y = bottom - 26
    _chart(ctx, d, (x0 + 26, 42, x1 - 32, labels_y - 2), outlook)

    # ---------------------------------------------- summary: when + how much
    y = bottom - 7
    if outlook.wet:
        start, end, _peak = outlook.rain_windows[0]
        when = f"do {end:%H} h" if start <= ctx.now else f"{start:%H}–{end:%H} h"
        word = "Sníh" if outlook.snow else "Déšť"
        if outlook.has_amounts:
            amount = f" · celkem {num(outlook.total_mm, 1)} mm"
        elif outlook.has_probability:
            amount = f" · šance {num(outlook.max_prob)} %"
        else:
            amount = ""
        text = f"{word} {when}{amount}"
        ctx.paste_icon(img, "umbrella", (x0, y - 7), 13, ctx.accent)
        d.text((x0 + 15, y), truncate(d, text, f(12, 700), x1 - x0 - 15), font=f(12, 700), fill=ctx.accent,
               anchor="lm")
    else:
        d.text((x0, y), f"Bez srážek příštích {len(outlook.hours) or int(o['hours'])} h", font=f(12, 700),
               fill=ink, anchor="lm")


def _chart(ctx, d, box, outlook):
    x0, y0, x1, y1 = box
    ink, f = ctx.BLACK, ctx.font
    hours = outlook.hours
    if len(hours) < 2:
        d.text(((x0 + x1) // 2, (y0 + y1) // 2), "předpověď není k dispozici", font=f(11), fill=ink, anchor="mm")
        return
    slot = (x1 - x0) / len(hours)

    # precipitation: mm per hour when the forecast has amounts, else % chance
    rain_ink = ctx.YELLOW if ctx.panel.has_yellow else ctx.LIGHT_GRAY
    if outlook.has_amounts:
        top = max(1, math.ceil(outlook.max_mm))
        values = [(h["mm"] or 0) / top for h in hours]
        top_label, unit = f"{top}", "mm/h"
    else:
        values = [(h["prob"] or 0) / 100 for h in hours]
        top_label, unit = "100", "%"
    for i, value in enumerate(values):
        if value > 0:
            bar_top = y1 - (y1 - y0) * min(1.0, value)
            d.rectangle((x0 + i * slot, bar_top, x0 + (i + 1) * slot - 1, y1), fill=rain_ink)
    d.text((x1 + 3, y0 - 1), top_label, font=f(10, 700), fill=ink, anchor="la")
    d.text((x1 + 3, y0 + 10), unit, font=f(10, 700), fill=ink, anchor="la")
    d.text((x1 + 3, y1), "0", font=f(10, 700), fill=ink, anchor="ls")

    # temperature: red line on its own °C scale
    temps = [h["temp"] for h in hours if h["temp"] is not None]
    if len(temps) >= 2:
        lo, hi, _ = nice_range(min(temps), max(temps), ticks=2)
        points = [(x0 + (i + 0.5) * slot, y1 - (h["temp"] - lo) / (hi - lo) * (y1 - y0))
                  for i, h in enumerate(hours) if h["temp"] is not None]
        d.line(points, fill=ctx.accent, width=2)
        d.text((x0 - 3, y0 - 1), f"{num(hi)}°C", font=f(10, 700), fill=ctx.accent, anchor="ra")
        d.text((x0 - 3, y1), f"{num(lo)}°C", font=f(10, 700), fill=ctx.accent, anchor="rs")

    d.line((x0, y1, x1, y1), fill=ink)
    for i, hour in enumerate(hours):
        if i % 3 == 0:
            cx = x0 + i * slot
            d.line((cx, y1, cx, y1 + 2), fill=ink)
            d.text((cx, y1 + 3), f"{hour['when']:%H}h", font=f(10), fill=ink, anchor="ma")
