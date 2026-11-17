"""Weather for the 2.9" BWRY label: reading on top, 24 h chart below.

Red temperature curve over yellow rain-probability bars - yellow is the
lightest pigment, so it works as a fill colour without dithering.
"""

from __future__ import annotations

from dratek_screen import CONDITIONS_CZ, DAYS_CZ, WEATHER_ICONS, nice_range, num, rain_fractions

TITLE = "Počasí (2,9\")"
SDK_TYPE = 46  # EPA LCD 296x128 BWRY (Drátek 2.9" 4-colour)
OPTIONS = {"weather": "weather.forecast_home"}


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font
    weather = ctx.options["weather"]
    rain_ink = ctx.YELLOW if ctx.panel.has_yellow else ctx.LIGHT_GRAY

    if ctx.entity(weather) is None:
        d.text((W // 2, H // 2), f"{weather} nenalezeno", font=f(14, 600), fill=ink, anchor="mm")
        return img

    # ------------------------------------------------------------ reading
    temp = num(ctx.num(weather, attr="temperature"))
    big = f(50, 700)
    d.text((3, -6), temp, font=big, fill=ink)
    x = 3 + d.textlength(temp, font=big)
    d.text((x + 1, 2), "°", font=f(26, 700), fill=ink)

    condition = ctx.state(weather, "cloudy")
    ctx.paste_icon(img, WEATHER_ICONS.get(condition, "weather-cloudy"), (int(x) + 20, 4), 38, ctx.accent)

    tx = int(x) + 64
    d.text((tx, 5), CONDITIONS_CZ.get(condition, condition), font=f(15, 700), fill=ink)
    feels = ctx.num(weather, attr="apparent_temperature")
    hum = num(ctx.num(weather, attr="humidity"))
    detail = f"pocitově {num(feels)}° · {hum} %" if feels is not None else f"vlhkost {hum} %"
    d.text((tx, 24), detail, font=f(12), fill=ink)
    d.text((W - 3, 5), f"{DAYS_CZ[ctx.now.weekday()]} {ctx.now.day}.{ctx.now.month}.", font=f(12, 600),
           fill=ink, anchor="ra")

    d.line((0, 46, W, 46), fill=ink)

    # -------------------------------------------------------------- chart
    hourly = ctx.forecast(weather, "hourly")[:24]
    if len(hourly) < 2:
        d.text((W // 2, 86), "předpověď není k dispozici", font=f(12), fill=ink, anchor="mm")
        return img

    x0, y0, x1, y1 = 24, 54, W - 3, 112
    temps = [float(h.get("temperature") or 0) for h in hourly]
    rain = rain_fractions(hourly)
    lo, hi, _ = nice_range(min(temps), max(temps), ticks=2)
    slot = (x1 - x0) / len(hourly)

    def y_of(t):
        return y1 - (t - lo) / (hi - lo) * (y1 - y0)

    for i, p in enumerate(rain):
        if p > 0:
            d.rectangle((x0 + i * slot, y1 - (y1 - y0) * p, x0 + (i + 1) * slot - 1, y1), fill=rain_ink)

    for i, h in enumerate(hourly):  # midnight separator, like the day lines in a wall-clock chart
        when = ctx.dt(h["datetime"])
        if when.hour == 0 and i:
            sx = x0 + i * slot
            d.line((sx, y0 - 4, sx, y1), fill=ink)
            d.text((sx + 2, y0 - 6), DAYS_CZ[when.weekday()], font=f(10, 700), fill=ink)

    d.line([(x0 + (i + 0.5) * slot, y_of(t)) for i, t in enumerate(temps)], fill=ctx.accent, width=2)
    d.line((x0, y1, x1, y1), fill=ink)
    d.text((x0 - 3, y0), f"{num(hi)}°", font=f(11, 600), fill=ink, anchor="ra")
    d.text((x0 - 3, y1), f"{num(lo)}°", font=f(11, 600), fill=ink, anchor="rs")
    for i, h in enumerate(hourly):
        if i % 6 == 0:
            cx = x0 + (i + 0.5) * slot
            d.line((cx, y1, cx, y1 + 2), fill=ink)
            d.text((cx, y1 + 3), ctx.dt(h["datetime"]).strftime("%H"), font=f(11), fill=ink, anchor="ma")
    return img
