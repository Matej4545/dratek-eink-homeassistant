# Screens: displays that Home Assistant draws and keeps up to date

A **screen** is a small Python file that draws a picture from Home Assistant
data. Assign one to a display and Home Assistant renders it, sends it, and
redraws it whenever the data it shows changes. The panel's designer isn't
involved.

## Using it

Every display gets two new entities on its device page:

| Entity | What it does |
|---|---|
| `select.<display>_obrazovka` (Screen) | Which screen the display shows, or `off`. It only lists screens that fit the display. Its attributes show the current options, the last result, any error, and the entities being watched. |
| `button.<display>_prekreslit_obrazovku` (Redraw screen) | Redraws now, ignoring the minimum refresh gap. |

Bundled screens:

| Screen id | Panel | Options (defaults) |
|---|---|---|
| `door` | 2.9" 296×128 | Front door: a narrow column of the next trams (line + time, filtered), and the rest for weather: temperature now / feels-like / max / min in °C, and a chart of the next hours with temperature (°C axis) and precipitation (mm/h axis, or % chance), plus when it rains and how much. Red band for open windows/doors. `stop_id`, `destinations`, `exclude`, `lines`, `min_minutes: 5`, `title`, `weather`, `hours: 12`, `alerts` |
| `going_out` | 2.9" 296×128 | What to wear, umbrella, slippery/storm/wind/UV warnings, the next hours as a chart, when it gets dark, the next calendar events, red band for `alerts`. `weather`, `hours: 12`, `calendar`, `sun: sun.sun`, `alerts` |
| `mini_weather` | 2.9" 296×128 | `weather: weather.forecast_home` |
| `mini_departures` | 2.9" 296×128 | `stop_id`, `title` (stop name), `limit: 4`, plus the same `destinations` / `exclude` / `lines` / `min_minutes` filters as `door` |
| `mini_sensors` | 2.9" 296×128 | up to 3 tiles: `sensor_1..3`, `label_1..3` (default: the sensor's name), `icon_1..3` (MDI name), `decimals_1..3`, `title` |
| `weather` | 7.5" 800×480 | `weather`, `indoor_temperature`, `indoor_humidity` |
| `departures` | 7.5" 800×480 | `stop_id`, `title`, `limit: 8` |
| `test_pattern` | any | none |

### Set a screen and its options

The select entity picks the screen. Options are set with the `dratek_eink.set_screen` action:

```yaml
action: dratek_eink.set_screen
data:
  address: "FF:FF:94:20:10:78"
  screen: mini_weather
  options:
    weather: weather.forecast_home
```

Options are stored per display and per screen, so switching between screens
keeps each screen's settings. `reset_options: true` restores the defaults, and
`min_refresh_seconds` changes the minimum gap between panel writes (default 600).

### Departures: find your stop

```yaml
action: dratek_eink.find_transit_stop
data:
  query: Letňany
```

The response lists stops with an `id`. Use that id as the screen's `stop_id`:

```yaml
action: dratek_eink.set_screen
data:
  address: "FF:FF:94:20:10:78"
  screen: mini_departures
  options:
    stop_id: "<id from the response>"
```

Departures come from Transitous (Czech and Slovak GTFS feeds), the same source
as the panel's departures template. The 2.9" screen shows departure **times**,
with live times in red, rather than countdowns. A countdown would mean
rewriting a coin-cell label every minute.

### Your tram stop, only your direction

`destinations` keeps only the trams going towards these end stops. Part of the
name is enough, and diacritics and case don't matter. `min_minutes` (default 5)
hides trams leaving in less than that many minutes, which you would not catch.

```yaml
action: dratek_eink.set_screen
data:
  address: "FF:FF:94:20:10:78"
  screen: door
  options:
    stop_id: "<id from find_transit_stop>"
    destinations: ["Lehovec", "Starý Hloubětín"]   # or "Lehovec, Starý Hloubětín"
    lines: ["3", "8"]                              # optional
    min_minutes: 5
    weather: weather.forecast_home
    alerts: ["binary_sensor.balcony_door", "binary_sensor.bedroom_window", "light.hallway"]
```

Times are clock times. A red time is a live (real-time) departure; a black time
comes from the timetable. The `alerts` entities appear in a red band only while
they are on, open or unlocked. That's useful for a window left open, a light
left on, or a door left unlocked.

`going_out` takes `calendar: calendar.family` and shows the next timed event,
then all-day reminders, next to the time it gets dark.

### Switch screens from an automation

```yaml
automation:
  - alias: Trams while I leave, the day ahead otherwise, nothing at night
    triggers:
      - trigger: time
        at: "06:30:00"
        id: door
      - trigger: time
        at: "09:00:00"
        id: going_out
      - trigger: time
        at: "22:30:00"
        id: "off"
    actions:
      - action: select.select_option
        target:
          entity_id: select.dratek_eink_ff_ff_94_20_10_78_obrazovka   # your entity id
        data:
          option: "{{ trigger.id }}"
```

`off` stops redrawing but leaves the last picture on the panel, so the label uses
no battery overnight. The tram screen (`INTERVAL` 600 s) is the most
battery-hungry; keeping it to the time you actually leave saves the most.

## When the display redraws

- When an entity the screen **read** changes. The screen doesn't have to list
  them: whatever it reads is watched automatically, like a template sensor.
  Forecasts are fetched again when the weather entity changes.
- Every `INTERVAL` seconds, if the screen sets one. The departures screens do,
  because buses leave without any entity changing.
- After switching screen, changing options, pressing Redraw, or a restart.

The redraws are paced like this:

- **Debounce:** several changes within 5 s become one redraw.
- **Minimum gap** (default 600 s): the panel is never rewritten more often than
  this. A change during the gap is drawn when the gap ends, not dropped. The gap
  carries over a restart.
- **Identical pictures are not sent.** If a temperature changes from 4.2° to
  4.3° but the screen rounds both to 4°, the display isn't touched. This also
  carries over a restart.
- **A failed send is retried after 5 minutes.**
- **The old designer refresh is paused.** If the display had an automatic
  refresh set up in the panel designer, it is paused (not deleted) when a screen
  takes over. To use the designer again, set the screen to `off` and resume the
  automation in the panel.

## Your own screens

Put `.py` files in `/config/dratek_screens/`, then run the
`dratek_eink.reload_screens` action. A file with the same name as a bundled
screen replaces it. Fonts go in `/config/dratek_screens/fonts/` (use the file
name as `family`), and SVG icons in `/config/dratek_screens/icons/`.

```python
from dratek_screen import num, WEATHER_ICONS   # helpers shipped with the integration

TITLE = "Living room"
SDK_TYPE = 46                       # laid out for the 2.9" label (omit = fits any panel)
OPTIONS = {"sensor": "sensor.living_room_temperature"}

def render(ctx):
    img, d = ctx.canvas()
    t = ctx.num(ctx.options["sensor"])
    d.text((8, 8), f"{num(t, 1)} °C", font=ctx.font(48, 700), fill=ctx.BLACK)
    return img
```

The `ctx` object provides:

- **Data:** `state`, `attr`, `num`, `entity`, `forecast(entity, "hourly"|"daily")`,
  `history(entity, hours)`, `transit(stop_id, limit)`, `calendar(entity, hours)`,
  `dt(timestamp)`, and `now` (in HA's time zone).
- **Helpers in `dratek_screen`:** `filter_departures`, `day_outlook` (highs and
  lows, rain windows), `describe_rain`, `clothing_advice`, `active_alerts`,
  `truncate`, `fit_font`, `num`, `as_list`, plus Czech day and condition names.
- **Drawing:** `canvas()`, `font(size, weight)`, `paste_icon(img, mdi_name, xy, size, colour)`,
  and `svg(markup)`.
- **Colours:** `BLACK`, `WHITE`, `RED`, `YELLOW`, the greys, and `accent`.

Draw in any colour: greys and in-between colours are dithered to the panel's
pigments. Design and test screens on a PC first, with the simulator in
`devtools/` (see `devtools/README.md`). It runs the same code as Home Assistant.

## Troubleshooting

- **The select entity's attributes** show `result` (`sent`, `unchanged`, `error`
  or `send_failed`), `error`, `reason`, `watched` and `last_render`.
- **The Home Assistant log** has the full traceback when a screen fails, and any
  screen file that failed to load.
- **"SDK type unknown"** means the display hasn't been seen advertising since
  HA started. It resolves once the display (or a gateway) reports it.

Security note: screens are Python code run by Home Assistant, the same trust
level as a custom integration. Only put files you trust in `/config/dratek_screens/`.
