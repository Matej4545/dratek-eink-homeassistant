"""Departures for the 2.9" BWRY label: stop name band + the next 4 departures.

Live data from Transitous (CZ/SK GTFS, the same source the panel's departures
template uses). Find your stop_id with the dratek_eink.find_transit_stop action.

Shows departure *times*, not "in 3 min": a countdown changes every minute, and
redrawing a coin-cell label every minute empties it fast. The list still moves
on as buses leave, at most every INTERVAL / minimum refresh gap.
"""

from __future__ import annotations

from dratek_screen import filter_departures, truncate

TITLE = "Odjezdy (2,9\")"
SDK_TYPE = 46
INTERVAL = 600
OPTIONS = {
    "stop_id": "", "title": "", "limit": 4,
    "destinations": "",   # keep only these directions (end stops), e.g. ["Lehovec"]
    "exclude": "",        # drop these directions
    "lines": "",          # keep only these lines, e.g. ["8", "3"]
    "min_minutes": 5,     # hide departures leaving in less than this many minutes
}


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font
    stop_id = str(ctx.options["stop_id"]).strip()

    if not stop_id:
        d.text((W // 2, H // 2 - 9), "Nastav option stop_id", font=f(15, 700), fill=ink, anchor="mm")
        d.text((W // 2, H // 2 + 11), "(akce dratek_eink.find_transit_stop)", font=f(11), fill=ink, anchor="mm")
        return img

    o = ctx.options
    board = ctx.transit(stop_id, 12)  # fetch extra, then filter down to what you take
    title = str(o["title"] or board.get("stop_name") or "Odjezdy")

    d.rectangle((0, 0, W, 21), fill=ink)
    d.text((5, 11), truncate(d, title, f(15, 700), W - 10), font=f(15, 700), fill=ctx.WHITE, anchor="lm")

    rows = filter_departures(board.get("departures"), destinations=o["destinations"], exclude=o["exclude"],
                             lines=o["lines"], min_minutes=int(o["min_minutes"] or 0))
    if not rows:
        d.text((W // 2, 74), "Žádné odjezdy", font=f(14, 600), fill=ink, anchor="mm")
        return img

    row_h, y = 26, 23
    for dep in rows[: int(ctx.options["limit"])]:
        mid = y + row_h // 2
        d.text((5, mid), str(dep.get("line") or "–"), font=f(17, 800), fill=ink, anchor="lm")
        dest = str(dep.get("destination") or "")
        dest_font = f(14, 500)
        while dest and d.textlength(dest, font=dest_font) > W - 44 - 64:
            dest = dest[:-1]
        d.text((48, mid), dest, font=dest_font, fill=ink, anchor="lm")
        when = str(dep.get("departure") or "")
        colour = ctx.accent if dep.get("realtime") else ink  # red = live time, black = timetable
        d.text((W - 5, mid), when, font=f(17, 700), fill=colour, anchor="rm")
        y += row_h
        if y < H - 2:
            d.line((5, y, W - 5, y), fill=ctx.GRAY)
    return img
