"""Orientation + colour check for a real panel. Send the PNG once, compare with the preview.

Select "test_pattern" as the display's screen (or render it with
devtools/sim.py). If the physical panel matches the simulator's "Panel" view
(TOP arrow up, corners where labelled, the swatches in the right colours), the
packing/orientation model holds for your model.
"""

from __future__ import annotations

TITLE = "Testovací obrazec"


def render(ctx):
    img, d = ctx.canvas()
    W, H = ctx.size
    ink, f = ctx.BLACK, ctx.font

    d.rectangle((0, 0, W - 1, H - 1), outline=ink)  # 1 px frame: every edge pixel visible?
    for label, xy, anchor in (("TL", (3, 2), "la"), ("TR", (W - 3, 2), "ra"),
                              ("BL", (3, H - 3), "ls"), ("BR", (W - 3, H - 3), "rs")):
        d.text(xy, label, font=f(12, 700), fill=ink, anchor=anchor)

    # arrow pointing to the top edge
    cx = W // 2
    d.polygon([(cx, 4), (cx - 9, 18), (cx + 9, 18)], fill=ctx.accent)
    d.rectangle((cx - 3, 18, cx + 3, 30), fill=ctx.accent)
    d.text((cx, 33), "TOP", font=f(12, 700), fill=ink, anchor="ma")

    # pigment swatches + a 50 % grey (dithered) + a red→yellow ramp (dithered)
    swatches = [("black", ctx.BLACK), ("white", ctx.WHITE), ("red", ctx.RED), ("yellow", ctx.YELLOW),
                ("50% grey", ctx.GRAY)]
    sw, sx, sy = 46, 6, 48
    for name, colour in swatches:
        d.rectangle((sx, sy, sx + sw - 4, sy + 30), fill=colour, outline=ink)
        d.text((sx + (sw - 4) / 2, sy + 33), name, font=f(10), fill=ink, anchor="ma")
        sx += sw
    for i in range(50):
        t = i / 49
        d.line((sx + i, sy, sx + i, sy + 30), fill=(int(220 + 24 * t), int(20 + 176 * t), int(12 * (1 - t))))
    d.text((sx + 25, sy + 33), "red→yel", font=f(10), fill=ink, anchor="ma")

    # text legibility ladder
    x = 30
    for size in (8, 10, 12, 14):
        d.text((x, H - 6), f"{size}px Aa", font=f(size), fill=ink, anchor="ls")
        x += 6 + d.textlength(f"{size}px Aa", font=f(size))
    return img
