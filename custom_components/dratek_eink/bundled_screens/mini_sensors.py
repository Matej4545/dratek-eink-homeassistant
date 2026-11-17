"""Up to three sensor values on the 2.9" BWRY label - temperatures, humidity, power...

Each tile: an MDI icon, a label (the sensor's name unless set) and the value
with its unit. Unused tiles are left out and the others share the width.
"""

from __future__ import annotations

from dratek_screen import num

TITLE = "Senzory (2,9\")"
SDK_TYPE = 46
OPTIONS = {
    "title": "",
    "sensor_1": "", "label_1": "", "icon_1": "thermometer", "decimals_1": 1,
    "sensor_2": "", "label_2": "", "icon_2": "water-percent", "decimals_2": 0,
    "sensor_3": "", "label_3": "", "icon_3": "home", "decimals_3": 1,
}


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f, o = ctx.BLACK, ctx.font, ctx.options
    tiles = [i for i in (1, 2, 3) if str(o[f"sensor_{i}"]).strip()]
    if not tiles:
        d.text((W // 2, H // 2), "Nastav options sensor_1 .. sensor_3", font=f(14, 700), fill=ink, anchor="mm")
        return img

    top = 0
    if o["title"]:
        d.rectangle((0, 0, W, 21), fill=ink)
        d.text((5, 11), str(o["title"]), font=f(15, 700), fill=ctx.WHITE, anchor="lm")
        top = 22

    width = W / len(tiles)
    for n, i in enumerate(tiles):
        entity_id = str(o[f"sensor_{i}"]).strip()
        x0 = round(n * width)
        cx = round(x0 + width / 2)
        if n:
            d.line((x0, top + 6, x0, H - 6), fill=ctx.GRAY)
        label = str(o[f"label_{i}"] or ctx.attr(entity_id, "friendly_name", entity_id))
        unit = str(ctx.attr(entity_id, "unit_of_measurement", "") or "")
        value = ctx.num(entity_id)
        text = num(value, int(o[f"decimals_{i}"])) if value is not None else str(ctx.state(entity_id, "–"))

        avail = H - top
        icon_size = 26 if avail > 100 else 20
        try:
            ctx.paste_icon(img, str(o[f"icon_{i}"]), (cx - icon_size // 2, top + 4), icon_size, ctx.accent)
        except KeyError:
            pass  # unknown icon name: leave the space empty rather than fail the screen
        label_font = f(12, 600)
        while label and d.textlength(label, font=label_font) > width - 8:
            label = label[:-1]
        d.text((cx, top + icon_size + 8), label, font=label_font, fill=ink, anchor="ma")

        size = 40 if len(tiles) == 1 else 32 if len(tiles) == 2 else 26
        value_font = f(size, 700)
        while size > 14 and d.textlength(text, font=value_font) + d.textlength(unit, font=f(13)) > width - 8:
            size -= 2
            value_font = f(size, 700)
        tw = d.textlength(text, font=value_font)
        uw = d.textlength(unit, font=f(13)) + 2 if unit else 0
        baseline = H - 12
        d.text((cx - (tw + uw) / 2, baseline), text, font=value_font, fill=ink, anchor="ls")
        if unit:
            d.text((cx - (tw + uw) / 2 + tw + 2, baseline), unit, font=f(13), fill=ink, anchor="ls")
    return img
