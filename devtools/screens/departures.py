"""Public-transport departure board, 800x480.

Reads a sensor whose ``departures`` attribute is a list of
{line, destination, scheduled, expected, delay_min, accessible, air_conditioned}
(times as "HH:MM"). Adapt _rows() to whatever your PID/Golemio sensor exposes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SDK_TYPE = 299  # designed for 800x480; see mini_departures.py for the 2.9" label
SENSOR = "sensor.pid_avia_letnany"
INTERVAL = 60  # the "x min" countdown changes every minute


def _rows(ctx):
    rows = []
    for dep in ctx.attr(SENSOR, "departures", []) or []:
        hh, mm = (int(p) for p in str(dep["expected"]).split(":"))
        expected = ctx.now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if expected < ctx.now - timedelta(hours=12):
            expected += timedelta(days=1)
        minutes = int((expected - ctx.now).total_seconds() // 60)
        if minutes >= 0:
            rows.append({**dep, "minutes": minutes})
    return rows


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font

    d.text((16, 10), ctx.attr(SENSOR, "friendly_name", "Odjezdy"), font=f(34, 700), fill=ink)
    d.text((W - 16, 10), "pid", font=f(34, 800), fill=ink, anchor="ra")
    d.line((0, 58, W, 58), fill=ink, width=3)

    row_h, y = 50, 62
    for dep in _rows(ctx)[:8]:
        d.text((16, y + row_h // 2), str(dep["line"]), font=f(30, 800), fill=ink, anchor="lm")
        d.text((92, y + 9), str(dep["destination"]), font=f(22, 500), fill=ink)
        # tiny inverted tags: B = step-free, K = air-conditioned
        tx = 92
        for tag, on in (("B", dep.get("accessible")), ("K", dep.get("air_conditioned"))):
            if on:
                d.rectangle((tx, y + 34, tx + 13, y + 46), fill=ink)
                d.text((tx + 7, y + 40), tag, font=f(11, 700), fill=ctx.WHITE, anchor="mm")
                tx += 17

        delay = int(dep.get("delay_min") or 0)
        if delay > 0:
            sched_font = f(20)
            sx = 440
            d.text((sx, y + row_h // 2), dep["scheduled"], font=sched_font, fill=ink, anchor="lm")
            sw = d.textlength(dep["scheduled"], font=sched_font)
            d.line((sx - 2, y + row_h // 2 + 1, sx + sw + 2, y + row_h // 2 - 3), fill=ink, width=2)
            badge = f"+{delay} min"
            bx = 508
            bw = d.textlength(badge, font=f(18, 700)) + 16
            d.rectangle((bx, y + 12, bx + bw, y + row_h - 12), fill=ctx.accent)
            d.text((bx + bw / 2, y + row_h // 2), badge, font=f(18, 700), fill=ctx.WHITE, anchor="mm")

        d.text((W - 130, y + row_h // 2), dep["expected"], font=f(24, 700), fill=ink, anchor="rm")
        minutes = dep["minutes"]
        d.text((W - 16, y + row_h // 2), "teď" if minutes == 0 else f"{minutes} min",
               font=f(24, 500), fill=ink, anchor="rm")
        y += row_h
        d.line((16, y, W - 16, y), fill=ctx.GRAY, width=1)

    d.text((W - 16, H - 8), f"{ctx.now:%d. %m. %Y %H:%M}", font=f(14), fill=ink, anchor="rs")
    return img
