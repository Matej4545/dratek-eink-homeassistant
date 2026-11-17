# eInk simulator: design and test screens without Home Assistant or hardware

A screen is a Python file with a `render(ctx)` function that draws pixels however
you like (Pillow, SVG, your own helpers). The simulator runs it against fake or
live entity states and pushes the result through the integration's **real**
packer (`render.pack_bwr_image`, plus optional QuickLZ framing). It then decodes
the bytes back into the picture the panel would print.

## Setup (once)

```bash
uv venv .venv --python 3.13
```

```bash
uv pip install --python .venv -r requirements-dev.txt
```

## Live preview while you design

```bash
.venv/Scripts/python devtools/sim.py serve devtools/screens/mini_weather.py --state devtools/states/demo.yaml
```

The panel type comes from the screen's `SDK_TYPE`. If a screen doesn't set one,
the default is **46**, the Drátek 2.9" 4-colour BWRY label (296×128). Override
it with `--sdk`. The `mini_*` screens and `test_pattern.py` are 296×128;
`weather.py` and `departures.py` are 800×480 examples.

### Check the simulator against your real display (once)

```bash
.venv/Scripts/python devtools/sim.py render devtools/screens/test_pattern.py
```

Copy `devtools/out/test_pattern/quantized.png` to `/config/www/eink/test_pattern.png`
on your HA and call the new service (Developer tools → Actions, YAML mode):

```yaml
action: dratek_eink.show_image
data:
  address: "FF:FF:94:20:10:78"   # your display's BLE address
  image: www/eink/test_pattern.png
  fit: none                      # refuse anything that is not exactly 296x128
  dither: none                   # already quantized
  force: true
```

The panel's **Vlastní obrázek** (custom image) template works too. Compare the display with
`devtools/out/test_pattern/panel.png`: the TOP arrow, the corner labels, and the
four swatches (black, white, red, yellow). If they match, the simulator's
orientation and colour model is confirmed for your display.

Open http://127.0.0.1:8950. Save the screen file or the state YAML and the preview
updates within a second. The header lets you switch the panel type, the dither
mode and zoom, and choose which views to show:

* **Drawn**: exactly what `render()` returned.
* **Quantized**: reduced to the panel's 2–4 pigments (greys become dither patterns).
* **Panel**: decoded back from the bytes the integration would send.

Errors (a traceback, or a wrong canvas size) show up on the page instead of
killing the server.

### With your real Home Assistant data (read-only, untested so far)

> Not yet run against a real HA. The `/api/states` call is standard, but the
> shapes of the forecast (`weather.get_forecasts?return_response`) and history
> responses are written from the docs, not tested. Expect a small fix on first use.

Create `devtools/.env` (gitignored):

```
HA_URL=http://homeassistant.local:8123
HA_TOKEN=<long-lived access token from your HA profile>
```

```bash
.venv/Scripts/python devtools/sim.py serve devtools/screens/weather.py --live
```

Live mode only reads `/api/states` and history, and calls `weather.get_forecasts`.
Nothing is installed in or changed on your HA. To freeze real data into a fixture:

```bash
.venv/Scripts/python devtools/sim.py pull-state --entities weather.home sun.sun --forecast weather.home --out devtools/states/mine.yaml
```

## Simulate updates over time

```bash
.venv/Scripts/python devtools/sim.py simulate devtools/scenarios/weather_day.yaml
```

> This simulates the **proposed** screen runtime and update policy
> (`docs/ARCHITECTURE-PROPOSAL.md`), not the current fork's
> `EntityAutoUpdateManager` / binding refresh. Replaying the current refresh
> path offline is possible, because `render_automatic_refresh_image` is a plain
> function, but it isn't built.

This replays a timeline of state changes in simulated time and writes
`devtools/out/<scenario>/index.html`. The report shows every trigger and its outcome:

| outcome | meaning |
|---|---|
| `sent` | panel would be rewritten (thumbnail + changed bounding box) |
| `unchanged` | rendered, but bytes identical to what the panel shows → no write |
| `deferred` | inside `min_gap` since the last write → postponed, not dropped |
| `ignored` | the entity changed, but the screen never reads it |

Triggers are automatic: every entity the screen read last time is watched, the
same way HA template sensors work. Add `INTERVAL = <seconds>` for time-driven
screens such as countdowns. Anything clock-like on screen defeats the
"identical bytes" skip. `departures_rush.yaml` shows what a minute countdown
costs: one panel write per minute.

## Writing a screen

```python
ORIENTATION = "landscape"   # or "portrait"
DITHER = "ordered"          # ordered | floyd | none
INTERVAL = 60               # optional periodic redraw

def render(ctx):
    img, d = ctx.canvas()                       # white RGB canvas, crisp (non-AA) text
    t = ctx.num("sensor.outdoor_temperature")   # also ctx.state / ctx.attr / ctx.entity
    d.text((20, 20), f"{t:.1f}°", font=ctx.font(96, 700), fill=ctx.BLACK)
    ctx.paste_icon(img, "weather-rainy", (300, 20), 96, ctx.accent)
    d.rectangle((20, 200, 400, 260), fill=ctx.LIGHT_GRAY)   # becomes a stipple
    return img                                  # or return an SVG string
```

* `ctx.size`, `ctx.width`, `ctx.height`, `ctx.now`, and `ctx.panel` (model, `has_red`, `has_yellow`).
* `ctx.accent` is red on colour panels and black on B/W, so one screen works on both.
* `ctx.forecast(entity, "daily"|"hourly")` and `ctx.history(entity, hours)`.
* `ctx.font(size, weight, family=None)`: Arimo (bundled) by default. Drop any
  `.ttf`/`.otf` into `devtools/fonts/` and use its file stem as `family`.
* `ctx.icon(name, size, colour)` / `ctx.paste_icon(...)`: MDI names from the
  subset in `tests/vendor/mdi/paths.js`, or any `devtools/icons/<name>.svg`
  (for example Meteocons or Phosphor).
* `ctx.svg(markup, w, h)`: rasterise SVG (gradients, patterns, paths) to an RGBA layer.

Draw with any colours. Exact pigments (pure black, white, red) stay crisp, and
everything else is dithered. Greys only dither between black and white, even on
red panels.

## Other commands

```bash
.venv/Scripts/python devtools/sim.py render devtools/screens/departures.py --state devtools/states/demo.yaml --sdk 296
```

```bash
.venv/Scripts/python devtools/sim.py decode some_image.png --sdk 299 --dither integration
```

```bash
.venv/Scripts/python devtools/sim.py types
```

`decode` runs any PNG (for example a design exported from the current panel)
through the packer. `--dither integration` uses the integration's own threshold
instead of dithering.

## Tests

```bash
.venv/Scripts/python -m pytest devtools/tests -q
```

The tests round-trip every supported panel type, in both orientations, framed
and unframed, through the real packer. They also check the dither rules, entity
tracking and the scenario outcomes.

## What this does not prove

The decoder is written from this repo's own understanding of the vendor byte
format and orientation. A clean round trip shows the packer is self-consistent
and loses no pixels. It cannot show that a physical panel reads the bytes the
same way. Confirm a new panel type on hardware once.

## The existing panel UI

The browser panel (designer, templates) has its own fake-HA harness:

```bash
.venv/Scripts/python tests/serve_no_cache.py
```

Then open http://localhost:8940/tests/dratek-eink-panel-harness.html.
