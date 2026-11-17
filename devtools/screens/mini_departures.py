"""Departure board for the 2.9" BWRY label (296x128): stop name band + 4 rows."""

from __future__ import annotations

from departures import SENSOR, _rows

SDK_TYPE = 46
INTERVAL = 60


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font

    d.rectangle((0, 0, W, 21), fill=ink)
    d.text((5, 11), ctx.attr(SENSOR, "friendly_name", "Odjezdy"), font=f(15, 700), fill=ctx.WHITE, anchor="lm")
    d.text((W - 5, 11), f"{ctx.now:%H:%M}", font=f(13, 600), fill=ctx.YELLOW if ctx.panel.has_yellow else ctx.WHITE,
           anchor="rm")

    row_h, y = 26, 23
    for dep in _rows(ctx)[:4]:
        mid = y + row_h // 2
        d.text((5, mid), str(dep["line"]), font=f(17, 800), fill=ink, anchor="lm")
        d.text((44, mid), str(dep["destination"]), font=f(14, 500), fill=ink, anchor="lm")
        delay = int(dep.get("delay_min") or 0)
        if delay:
            badge = f"+{delay}"
            bw = d.textlength(badge, font=f(12, 700)) + 8
            d.rectangle((W - 62 - bw, mid - 8, W - 62, mid + 8), fill=ctx.accent)
            d.text((W - 62 - bw / 2, mid), badge, font=f(12, 700), fill=ctx.WHITE, anchor="mm")
        minutes = dep["minutes"]
        d.text((W - 5, mid), "teď" if minutes == 0 else f"{minutes}′", font=f(17, 700), fill=ink, anchor="rm")
        y += row_h
        if y < H - 2:
            d.line((5, y, W - 5, y), fill=ctx.GRAY)
    return img
