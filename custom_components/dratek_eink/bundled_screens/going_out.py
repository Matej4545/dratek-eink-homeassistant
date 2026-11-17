"""Going out, 2.9" BWRY: what to wear, umbrella or not, and what the next hours bring.

* top: feels-like temperature and clothing advice from the coldest of now and
  the next ``hours`` hours (umbrella, slippery, storms, wind and UV in red);
* middle: the next hours - red temperature line over yellow rain bars;
* bottom: when it gets dark and your first calendar event - or, when any of
  ``alerts`` is on/open, a red band naming them (windows, lights, iron...).
"""

from __future__ import annotations

from datetime import timedelta

from dratek_screen import (WEATHER_ICONS, active_alerts, clothing_advice, day_outlook, nice_range, num,
                           truncate)

TITLE = "Odchod z domu (2,9\")"
SDK_TYPE = 46
INTERVAL = 1800  # the chart's hours move on; data changes redraw it anyway
OPTIONS = {
    "weather": "weather.forecast_home",
    "hours": 12,
    "calendar": "",       # e.g. "calendar.family" - shows the next event within `hours`
    "sun": "sun.sun",     # for "tma v 16:15"
    "alerts": "",         # e.g. ["binary_sensor.bedroom_window", "light.hallway"]
}


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f, o = ctx.BLACK, ctx.font, ctx.options
    weather = str(o["weather"])
    if ctx.entity(weather) is None:
        d.text((W // 2, H // 2), f"{weather} nenalezeno", font=f(14, 600), fill=ink, anchor="mm")
        return img

    condition = ctx.state(weather, "cloudy")
    temp = ctx.num(weather, attr="temperature")
    feels = ctx.num(weather, attr="apparent_temperature")
    outlook = day_outlook(ctx.forecast(weather, "hourly"), ctx.now, hours=int(o["hours"]), to_local=ctx.dt,
                          current_temperature=temp)

    # ------------------------------------------------- feels-like + range
    ctx.paste_icon(img, WEATHER_ICONS.get(condition, "weather-cloudy"), (2, 3), 30, ctx.accent)
    shown = feels if feels is not None else temp
    big = f(34, 700)
    d.text((36, -4), f"{num(shown)}°", font=big, fill=ink)
    d.text((4, 38), "pocitově" if feels is not None else "teplota", font=f(10), fill=ink)
    if outlook.hi is not None:
        hi = f"{num(outlook.hi)}°"
        d.text((4, 51), hi, font=f(13, 700), fill=ctx.accent)
        d.text((6 + d.textlength(hi, font=f(13, 700)), 51), f"/ {num(outlook.lo)}°", font=f(13, 700), fill=ink)

    # ---------------------------------------------------------- advice
    advice = clothing_advice(outlook, feels if feels is not None else temp)
    x, y = 104, 3
    d.line((98, 4, 98, 66), fill=ctx.GRAY)
    for i, (text, important) in enumerate(advice[:3]):
        icon = "umbrella" if text == "Deštník" else ("coat" if i == (1 if advice[0][0] == "Deštník" else 0) else None)
        colour = ctx.accent if important else ink
        size = 17 if i == 0 else 15
        if icon:
            ctx.paste_icon(img, icon, (x, y + 1), size, colour)
        tx = x + (size + 4 if icon else 0)
        d.text((tx, y), truncate(d, text, f(size, 700), W - tx - 3), font=f(size, 700), fill=colour)
        y += size + 6
    if len(advice) > 3:
        extra = ", ".join(t for t, _ in advice[3:])
        d.text((x, y), truncate(d, "+ " + extra, f(11), W - x - 3), font=f(11), fill=ink)

    # ---------------------------------------------------- hours chart
    alerts = active_alerts(ctx, o["alerts"])
    footer_top = H - 17
    _chart(ctx, d, (22, 72, W - 3, footer_top - 11), outlook)

    # ---------------------------------------------------------- footer
    if alerts:
        d.rectangle((0, footer_top, W, H), fill=ctx.accent)
        ctx.paste_icon(img, "alert-circle-outline", (3, footer_top + 2), 13, ctx.WHITE)
        text = truncate(d, "Otevřeno: " + ", ".join(alerts), f(12, 700), W - 24)
        d.text((20, footer_top + 9), text, font=f(12, 700), fill=ctx.WHITE, anchor="lm")
        return img
    parts = []
    setting = ctx.attr(str(o["sun"]), "next_setting") if o["sun"] else None
    if setting:
        dark = ctx.dt(setting)
        if dark - ctx.now < timedelta(hours=20):
            parts.append(f"tma {dark:%H:%M}")
    if o["calendar"]:
        upcoming = [e for e in ctx.calendar(str(o["calendar"]), float(o["hours"])) if e["end"] > ctx.now]
        # Appointments with a time first (soonest first), then all-day reminders.
        upcoming.sort(key=lambda e: (e["all_day"], e["start"]))
        for event in upcoming[:2]:
            when = "" if event["all_day"] else f"{event['start']:%H:%M} "
            parts.append(f"{when}{event.get('summary') or ''}".strip())
    d.line((0, footer_top, W, footer_top), fill=ink)
    if parts:
        d.text((3, footer_top + 9), truncate(d, "  ·  ".join(parts), f(12, 700), W - 6), font=f(12, 700),
               fill=ink, anchor="lm")
    return img


def _chart(ctx, d, box, outlook):
    x0, y0, x1, y1 = box
    ink, f = ctx.BLACK, ctx.font
    hours = outlook.hours
    if len(hours) < 2:
        d.text(((x0 + x1) // 2, (y0 + y1) // 2), "předpověď není k dispozici", font=f(11), fill=ink, anchor="mm")
        return
    slot = (x1 - x0) / len(hours)
    rain_ink = ctx.YELLOW if ctx.panel.has_yellow else ctx.LIGHT_GRAY
    for i, hour in enumerate(hours):
        if hour["rain"] > 0:
            d.rectangle((x0 + i * slot, y1 - (y1 - y0) * hour["rain"], x0 + (i + 1) * slot - 1, y1), fill=rain_ink)
    temps = [h["temp"] for h in hours if h["temp"] is not None]
    if len(temps) >= 2:
        lo, hi, _ = nice_range(min(temps), max(temps), ticks=2)
        points = [(x0 + (i + 0.5) * slot, y1 - (h["temp"] - lo) / (hi - lo) * (y1 - y0))
                  for i, h in enumerate(hours) if h["temp"] is not None]
        d.line(points, fill=ctx.accent, width=2)
        d.text((x0 - 3, y0), f"{num(hi)}°", font=f(9, 600), fill=ink, anchor="ra")
        d.text((x0 - 3, y1), f"{num(lo)}°", font=f(9, 600), fill=ink, anchor="rs")
    d.line((x0, y1, x1, y1), fill=ink)
    for i, hour in enumerate(hours):
        if i % 3 == 0:
            cx = x0 + (i + 0.5) * slot
            d.line((cx, y1, cx, y1 + 2), fill=ink)
            d.text((cx, y1 + 2), f"{hour['when']:%H}", font=f(9), fill=ink, anchor="ma")
