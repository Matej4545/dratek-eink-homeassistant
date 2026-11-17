"""Departure board, 800x480: line, destination, platform, time and countdown.

Live data from Transitous (CZ/SK GTFS). Find your stop_id with the
dratek_eink.find_transit_stop action. The countdown is only as fresh as the
last redraw - fine on a mains-powered 7.5" panel with INTERVAL = 300, a bad
idea on a coin cell (see mini_departures.py).
"""

from __future__ import annotations

TITLE = "Odjezdy (800×480)"
SDK_TYPE = 299  # designed for 800x480; see mini_departures.py for the 2.9" label
INTERVAL = 300
OPTIONS = {"stop_id": "", "title": "", "limit": 8}


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font
    stop_id = str(ctx.options["stop_id"]).strip()
    if not stop_id:
        d.text((W // 2, H // 2), "Nastav option stop_id (akce dratek_eink.find_transit_stop)",
               font=f(24, 600), fill=ink, anchor="mm")
        return img

    limit = int(ctx.options["limit"])
    board = ctx.transit(stop_id, limit)
    d.text((16, 10), str(ctx.options["title"] or board.get("stop_name") or "Odjezdy"), font=f(34, 700), fill=ink)
    d.text((W - 16, 14), f"{ctx.now:%H:%M}", font=f(28, 600), fill=ink, anchor="ra")
    d.line((0, 58, W, 58), fill=ink, width=3)

    row_h, y = 50, 62
    for dep in (board.get("departures") or [])[:limit]:
        mid = y + row_h // 2
        d.text((16, mid), str(dep.get("line") or "–"), font=f(30, 800), fill=ink, anchor="lm")
        d.text((110, mid), str(dep.get("destination") or ""), font=f(22, 500), fill=ink, anchor="lm")
        if dep.get("platform"):
            d.text((520, mid), f"nást. {dep['platform']}", font=f(16), fill=ink, anchor="lm")
        d.text((W - 130, mid), str(dep.get("departure") or ""), font=f(24, 700),
               fill=ctx.accent if dep.get("realtime") else ink, anchor="rm")
        minutes = int(dep.get("minutes") or 0)
        d.text((W - 16, mid), "teď" if minutes == 0 else f"{minutes} min", font=f(24, 500), fill=ink, anchor="rm")
        y += row_h
        d.line((16, y, W - 16, y), fill=ctx.GRAY, width=1)
    return img
