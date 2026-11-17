"""Weather dashboard, 800x480 - current conditions, 5-day strip, stats grid, 24 h chart.

Options pick the entities: the weather entity (plus its daily/hourly
forecasts), and optional indoor temperature/humidity sensors.
"""

from __future__ import annotations

from dratek_screen import (CONDITIONS_CZ, DAYS_CZ, DAYS_LONG_CZ, MONTHS_GEN_CZ, WEATHER_ICONS, dotted_hline,
                 nice_range, num, rain_fractions)

TITLE = "Počasí (800×480)"
SDK_TYPE = 299  # designed for 800x480; see mini_weather.py for the 2.9" label
OPTIONS = {
    "weather": "weather.forecast_home",
    "indoor_temperature": "",
    "indoor_humidity": "",
}
# No INTERVAL: redraw only when an entity read below changes. (The date in the
# corner still flips at midnight with the next data change; add INTERVAL = 3600
# if that matters - a tick that renders identical bytes costs no panel write.)


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, accent = ctx.BLACK, ctx.accent
    f = ctx.font
    WEATHER = ctx.options["weather"]

    # ------------------------------------------------------------ current
    condition = ctx.state(WEATHER, "cloudy")
    ctx.paste_icon(img, WEATHER_ICONS.get(condition, "weather-cloudy"), (14, 18), 150)
    temp = ctx.num(WEATHER, attr="temperature")
    big = f(118, 700)
    temp_text = num(temp)
    d.text((176, 10), temp_text, font=big, fill=ink)
    tw = d.textlength(temp_text, font=big)
    d.text((176 + tw + 4, 30), "°C", font=f(30, 500), fill=ink)
    feels = ctx.num(WEATHER, attr="apparent_temperature")
    d.text((180, 142), f"{CONDITIONS_CZ.get(condition, condition)} · pocitově {num(feels)}°", font=f(22), fill=ink)

    # ------------------------------------------------------- place & date
    now = ctx.now
    d.text((W - 16, 12), ctx.attr(WEATHER, "friendly_name", "Doma"), font=f(32, 600), fill=ink, anchor="ra")
    d.text((W - 16, 52), f"{DAYS_LONG_CZ[now.weekday()]} {now.day}. {MONTHS_GEN_CZ[now.month - 1]}",
           font=f(22), fill=ink, anchor="ra")

    # ------------------------------------------------------- 5-day strip
    days = ctx.forecast(WEATHER, "daily")[:5]
    col_w, x0, top = 68, W - 16 - 5 * 68, 88
    for i, day in enumerate(days):
        cx = x0 + i * col_w + col_w // 2
        when = ctx.dt(day["datetime"])
        d.text((cx, top), DAYS_CZ[when.weekday()], font=f(18, 600), fill=ink, anchor="ma")
        ctx.paste_icon(img, WEATHER_ICONS.get(day.get("condition"), "weather-cloudy"), (cx - 21, top + 22), 42)
        hi, lo = num(day.get("temperature")), num(day.get("templow"))
        d.text((cx, top + 70), f"{hi}°", font=f(18, 700), fill=accent, anchor="ra")
        d.text((cx, top + 70), f"|{lo}°", font=f(18), fill=ink, anchor="la")

    d.line((16, 196, W - 16, 196), fill=ink, width=1)

    # -------------------------------------------------------- stats grid
    rise = ctx.attr("sun.sun", "next_rising")
    sets = ctx.attr("sun.sun", "next_setting")
    stats = [
        ("weather-sunny", "Východ", ctx.dt(rise).strftime("%H:%M") if rise else "–", ""),
        ("weather-night", "Západ", ctx.dt(sets).strftime("%H:%M") if sets else "–", ""),
        ("weather-windy", "Vítr", num(ctx.num(WEATHER, attr="wind_speed")), "km/h"),
        ("water-percent", "Vlhkost", num(ctx.num(WEATHER, attr="humidity")), "%"),
        ("gauge", "Tlak", num(ctx.num(WEATHER, attr="pressure")), "hPa"),
        ("eye", "Viditelnost", num(ctx.num(WEATHER, attr="visibility")), "km"),
    ]
    if ctx.options["indoor_temperature"]:
        stats.append(("thermometer", "Doma", num(ctx.num(ctx.options["indoor_temperature"]), 1), "°C"))
    if ctx.options["indoor_humidity"]:
        stats.append(("home", "Doma vlhkost", num(ctx.num(ctx.options["indoor_humidity"])), "%"))
    for i, (icon, label, value, unit) in enumerate(stats):
        x = 16 + (i % 2) * 190
        y = 212 + (i // 2) * 62
        ctx.paste_icon(img, icon, (x, y + 8), 36)
        d.text((x + 46, y + 2), label, font=f(15), fill=ink)
        vf = f(28, 600)
        d.text((x + 46, y + 20), value, font=vf, fill=ink)
        d.text((x + 50 + d.textlength(value, font=vf), y + 32), unit, font=f(15), fill=ink)

    # -------------------------------------------------------- 24 h chart
    hourly = ctx.forecast(WEATHER, "hourly")[:24]
    if len(hourly) >= 2:
        _chart(ctx, d, (440, 222, W - 48, 440), hourly)

    # No "updated at HH:MM" footer on purpose: the render time differs on every
    # redraw, so the panel would be rewritten even when no value changed.
    return img


def _chart(ctx, d, box, hourly):
    x0, y0, x1, y1 = box
    ink, accent, f = ctx.BLACK, ctx.accent, ctx.font
    temps = [float(h["temperature"]) for h in hourly]
    rain = [100 * r for r in rain_fractions(hourly)]
    lo, hi, step = nice_range(min(temps) - 0.5, max(temps) + 0.5)
    n, slot = len(hourly), (x1 - x0) / len(hourly)

    def y_of(t):
        return y1 - (t - lo) / (hi - lo) * (y1 - y0)

    # precipitation probability: grey bars -> the dither turns them into a stipple
    for i, p in enumerate(rain):
        if p > 0:
            top = y1 - (y1 - y0) * p / 100
            d.rectangle((x0 + i * slot + 1, top, x0 + (i + 1) * slot - 1, y1), fill=ctx.LIGHT_GRAY)

    ticks = int(round((hi - lo) / step))
    for k in range(ticks + 1):
        t = lo + k * step
        y = y_of(t)
        dotted_hline(d, x0, x1, y, ink)
        d.text((x0 - 6, y), f"{num(t)}°", font=f(14), fill=ink, anchor="rm")
        d.text((x1 + 6, y), f"{round(100 * k / ticks)}%", font=f(12), fill=ink, anchor="lm")

    points = [(x0 + (i + 0.5) * slot, y_of(t)) for i, t in enumerate(temps)]
    d.line(points, fill=accent, width=3, joint="curve")
    d.line((x0, y1, x1, y1), fill=ink, width=2)
    for i, h in enumerate(hourly):
        if i % 4 == 0:
            x = x0 + (i + 0.5) * slot
            d.line((x, y1, x, y1 + 4), fill=ink)
            d.text((x, y1 + 6), ctx.dt(h["datetime"]).strftime("%H"), font=f(14), fill=ink, anchor="ma")
