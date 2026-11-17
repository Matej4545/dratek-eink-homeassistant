# Architecture proposal: screens as code, integration as transport

Status: proposal (2026-11-16). Nothing here is implemented in the integration
yet. The `devtools/` simulator is a working prototype of the screen runtime and
update policy described below.

## TL;DR

**Keep the transport and replace the whole UI/automation layer, in place.** Not
a rewrite from scratch, and not more fixes to the current designer.

* **Keep:** BLE transfer, ESP32 gateways and firmware, queue and routing,
  discovery, packing (`pack_bwr_image` and friends). That is about 5k lines of
  hard-won code that you can't re-verify without the hardware. Its many
  hardware-fix releases are inferred from commit messages.
* **Replace:** the browser designer, templates, script templates, the binding and
  auto-refresh machinery, and the server-side re-implementations of the panel's
  drawing. That is about 7–8k lines of Python plus about 29k lines of panel
  JavaScript.
* **With:** screens as Python files (`render(ctx) -> image`) rendered **server-side**
  by the integration, plus a `show_image` service for pixels made anywhere else.

## Why the current design can't do what you want

What you asked for: full control over the UI, real graphics libraries, data
connected easily, and automatic updates.

1. **The UI is rendered in the browser.** The panel draws the design in a canvas
   or SVG and uploads a PNG (`websocket_send_design`). Script templates run in a
   browser Web Worker (`panel-template-script.mixin.js`). With no browser open,
   nothing can run your layout code.
2. **Auto-update therefore can't re-run your layout.** `EntityAutoUpdateManager`
   stores a captured background plus a list of "bindings" (value slots with
   recorded boxes). On a state change it redraws those slots server-side. See
   `render_automatic_refresh_image` and its four fallback tiers: clean
   background → SVG substitution → text-slot patch → PIL compositing. There
   *are* Python re-implementations for many slot types (text, chart, series,
   forecast, calendar, camera, the `svg_blocks` port). What never runs
   server-side is your script's own logic: anything it computes, filters or
   lays out from the data stays frozen at the last manual send. Your own
   example says it: *"the chart is redrawn on the next manual send"*.
   (This explanation comes from reading the code. I haven't reproduced your
   production symptom.)
3. **Every visual feature exists twice.** It exists once in JS for the designer,
   and again in Python (`render.py` binding renderers, `svg_blocks.py` "port")
   for refreshes. The two copies need regression tests to keep them
   pixel-identical (`test_bwr_packing.py` explains a 16.6 % disagreement). Each
   new widget costs double, and the row and block vocabulary is the ceiling on
   what you can draw.
4. **The fork changes sit in the most fragile layer.** The roughly 2.5k fork lines
   are all in the designer and automation layer. The suite shows 11 more
   failures than upstream 1.0.3 (upstream: 4, fork: 15):
   * 7 existing tests in `test_automation_bindings.py` fail with
     `'EntityAutoUpdateManager' object has no attribute '_layers'`, from PR #2.
   * 1 is expected (`test_hacs_uses_the_release_zip`), because the zip release
     was removed on purpose.
   * 1 is in a fork-added test (`test_script_template_auto_update.py`).
   * 2 are UI tests (translation coverage, unconfigured-template warning).

   *Update 2026-11-16:* the 7 `_layers` failures are fixed. They came from a test
   harness that builds the manager without `__init__`, plus two store-format
   assertions that predate PR #2. Production was never affected. The suite now
   has 8 failures, all pre-existing and unrelated to this work.

You can't patch your way out of this, because the root cause is where rendering
happens.

## Your example screens, and what they need

| Example | Needs |
|---|---|
| Weather frames (1, 3, 4) | custom fonts, icon sets, dense grids, a 24 h chart with bars plus a line, dithered greys |
| Temperature/precip chart (2) | line chart, hatched area fill, vertical day separators, free text placement |
| PID departures (5) | table rows, inverted badges, strikethrough times, countdown every minute |
| Calendar (6) | month grid, highlighted day, agenda list |

All of these are ordinary 2D drawing. `devtools/screens/weather.py` (about 130
lines) and `departures.py` (about 80 lines) reproduce examples 4 and 5 in plain
Pillow.

## Proposed architecture

```
 Home Assistant
 ┌──────────────────────────────────────────────────────────────────────┐
 │ state_changed ──► ScreenRunner (per display)                         │
 │                    • watches entities the screen READ last render    │
 │                    • + optional INTERVAL, debounce, min_gap          │
 │                    ▼                                                 │
 │   /config/dratek_screens/weather.py  render(ctx) → PIL image | SVG   │
 │                    ▼                                                 │
 │   quantize/dither to panel pigments → pack_bwr_image → bytes         │
 │                    ▼ (skip if bytes == what panel shows)             │
 │   existing TransferQueue → BLE or ESP32 gateway (unchanged)          │
 │                                                                      │
 │   service dratek_eink.show_image(address, image | url | camera)  ────┤ pixels from anywhere
 │   camera.<display>_preview  (what the panel shows now)               │
 └──────────────────────────────────────────────────────────────────────┘
 Your PC: devtools/sim.py serve|simulate runs the SAME screen file and runtime
```

### Screen contract (already implemented in the simulator)

```python
INTERVAL = 60            # optional
ORIENTATION = "landscape"
def render(ctx):
    img, d = ctx.canvas()
    ...                  # ctx.state/attr/num/forecast/history, ctx.font, ctx.icon, ctx.svg
    return img
```

Dependencies are tracked automatically: every entity `render()` reads is
subscribed, like HA template sensors. Screens stay portable between PC and HA
because the simulator and the integration share one `ctx` implementation and one
dither and update policy. In practice that means moving `devtools/eink_sim/{context,dither}.py`
plus the update loop into the integration package and having the simulator
import them from there.

### Update policy

The simulator runs this policy today (`devtools/eink_sim/simulate.py`):

* Debounce bursts of state changes (default 5 s).
* `min_gap` between panel writes: defer, never drop.
* Skip the write when the packed bytes are identical. Changed-box detection is
  already there for the one partial-update panel (SDK 2635).
* Lesson from the simulator: anything clock-like on screen ("updated 07:30",
  countdowns) changes the bytes on every render, which costs a panel refresh and
  battery each time. Design for it deliberately.

### Graphics in Home Assistant

| Option | Runs inside HA OS? | Verdict |
|---|---|---|
| **Pillow** | yes (HA core dependency) | primary drawing API |
| **SVG via resvg-py** | already a requirement of this integration (falls back when no wheel) | for vector art, patterns, icon sets |
| numpy | believed to ship with HA core; **verify**, and declare it in `manifest.json` anyway | dithering, fast pixel ops |
| matplotlib | heavy extra dependency, wheel availability on musl/ARM varies | avoid inside HA; fine in an external renderer |
| HTML/CSS via headless Chromium | not on HA OS | only as an external service feeding `show_image` |

Screens are Python in your config folder. That is the same trust level as
`custom_components` or pyscript: your own code, run as HA.

## Migration plan

Each step is shippable and testable with the simulator before it reaches production.

1. **`dratek_eink.show_image` service.** *Implemented 2026-11-16* in
   `image_service.py` (HA side) and `screen_image.py` / `dither.py` (pure,
   shared with the simulator). Covered by `tests/test_show_image.py`, but not yet
   run inside HA or against hardware.
   * It takes `address` plus exactly one of `image` (an allowed path), `url`,
     `camera_entity` or `data` (base64), and sends through
     `_async_submit_routed_transfer`, so gateways work.
   * It fits the picture to the panel (`fit`, `orientation`), dithers it to the
     panel's pigments, and updates the preview camera.
   * It skips the write when the display already shows those exact bytes, unless
     `force` is set.
   * It pauses the display's automatic refresh rather than deleting it, and
     returns a response on request.
2. **Screen runtime.** Move `context.py`, `dither.py` and the update loop into
   the integration. Add a mapping from display to screen file (options flow or
   YAML), and run on `state_changed` and the interval. The simulator imports the
   same modules.
3. **Delete the old layer:** the designer and templates, script templates,
   `automation.py` binding refresh, `svg_blocks.py`, the binding renderers in
   `render.py`, and the `ws_*` handlers they use. Keep a slim panel (or plain HA
   entities) for discovery, gateways, the queue and previews, or drop the panel
   entirely.
4. **Upstream sync.** Keep transport files (`transfer.py`, `gateway.py`,
   `queue.py`, `quicklz.py`, the packing part of `render.py`, firmware) as close
   to upstream as possible, so their frequent hardware fixes can be
   cherry-picked. Moving packing out of `render.py` into its own module is the
   one refactor worth doing early.

## Rejected alternatives

* **Rewrite from scratch:** this throws away transport fixes that took many
  releases (per the commit history) (BLE teardown, gateway failover, SDK 46
  acknowledgements, QuickLZ framing, OTA). The simulator can't verify those.
* **Keep fixing the designer:** see "Why the current design can't do what you
  want". Every capability has to be built twice, and auto-update stays a
  patch-over-captured-image approximation.
* **Only an external renderer** (AppDaemon or a container pushing PNGs via step 1):
  this is a valid choice if you prefer it, and step 1 enables it. It does mean a
  second moving part to run and monitor. In-integration screens keep it to one.

## Your setup (answered 2026-11-16)

* **Home Assistant OS.** HA runs in an Alpine (musl) container, and integrations
  install pip requirements from `manifest.json`.
  * Pillow ships with HA core.
  * resvg-py 0.5.0 (PyPI) and numpy 2.5.5 (cp313) both publish `musllinux_1_2`
    wheels for aarch64 and x86_64, so they install on HA OS whether it runs on
    a Raspberry Pi or x86 hardware.
  * No headless browser, so HTML rendering would have to run elsewhere.
* **Display: Drátek 2.9" BWRY, SDK type 46** ("EPA LCD 296x128 BWRY").
  * Packing: 2 bits per pixel, 9,472 bytes per frame.
  * Orientation: the vendor-specific quarter turn plus 180° (`BWRY_296X128_CODE`
    in `render.py`).
  * The simulator round-trips this path exactly. Whether the physical panel
    agrees is a one-time check with `devtools/screens/test_pattern.py`.
* **Consequences for the design:**
  * Partial refresh is only supported on SDK 2635, so every update of this
    display is a full refresh. Keep `min_gap` generous.
  * Avoid minute-level content such as countdowns or clocks. Four-colour panels
    are generally slower to refresh than black-and-white ones; that's general
    eInk behaviour, not measured on this unit.
  * At 296×128, text below about 10 px is not readable (see the ladder in the
    test pattern). Yellow is the lightest pigment and works well as a fill.
  * `devtools/screens/mini_weather.py` and `mini_departures.py` are worked
    examples at this size.
