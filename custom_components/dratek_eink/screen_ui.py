"""Small helpers shared by the example screens. Plain Pillow - copy, change, extend."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

WEATHER_ICONS = {
    "sunny": "weather-sunny",
    "clear-night": "weather-night",
    "partlycloudy": "weather-partly-cloudy",
    "cloudy": "weather-cloudy",
    "rainy": "weather-rainy",
    "pouring": "weather-pouring",
    "snowy": "weather-snowy",
    "snowy-rainy": "weather-snowy-rainy",
    "fog": "weather-fog",
    "hail": "weather-hail",
    "lightning": "weather-lightning",
    "lightning-rainy": "weather-lightning-rainy",
    "windy": "weather-windy",
    "windy-variant": "weather-windy",
    "exceptional": "alert-circle-outline",
}
CONDITIONS_CZ = {
    "sunny": "Slunečno", "clear-night": "Jasno", "partlycloudy": "Polojasno", "cloudy": "Zataženo",
    "rainy": "Déšť", "pouring": "Liják", "snowy": "Sníh", "snowy-rainy": "Déšť se sněhem",
    "fog": "Mlha", "hail": "Kroupy", "lightning": "Bouřky", "lightning-rainy": "Bouřky",
    "windy": "Větrno", "windy-variant": "Větrno", "exceptional": "Výstraha",
}
DAYS_CZ = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
DAYS_LONG_CZ = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
MONTHS_GEN_CZ = ["ledna", "února", "března", "dubna", "května", "června", "července",
                 "srpna", "září", "října", "listopadu", "prosince"]


def num(value, digits: int = 0, fallback: str = "–") -> str:
    """Czech number formatting: decimal comma."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value):
        return fallback
    text = f"{value:.{digits}f}"
    return "0" if text in ("-0", "-0.0") and digits == 0 else text.replace(".", ",")


def rain_fractions(hourly: list[dict]) -> list[float]:
    """0..1 per entry: precipitation_probability where the forecast provides it,
    otherwise the precipitation amount, scaled so 4 mm/h (or the wettest hour) is full."""
    if any(h.get("precipitation_probability") is not None for h in hourly):
        return [max(0.0, min(1.0, float(h.get("precipitation_probability") or 0) / 100)) for h in hourly]
    amounts = [max(0.0, float(h.get("precipitation") or 0)) for h in hourly]
    top = max([4.0, *amounts])
    return [a / top for a in amounts]


def dotted_hline(draw, x0: float, x1: float, y: float, fill, step: int = 4) -> None:
    for x in range(int(x0), int(x1), step):
        draw.point((x, int(y)), fill=fill)


def nice_range(lo: float, hi: float, ticks: int = 4) -> tuple[float, float, float]:
    """Round an axis range out to a friendly step."""
    span = max(hi - lo, 1e-6)
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


# ------------------------------------------------------------ text fitting


def truncate(draw, text: str, font, max_width: float) -> str:
    """Shorten text with an ellipsis until it fits max_width."""
    text = str(text or "")
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return (text.rstrip() + "…") if text else ""


def fit_font(draw, text: str, make_font, max_width: float, start: int, minimum: int = 9):
    """The largest make_font(size) <= start in which text fits max_width."""
    size = start
    font = make_font(size)
    while size > minimum and draw.textlength(str(text), font=font) > max_width:
        size -= 1
        font = make_font(size)
    return font


# ------------------------------------------------------------- departures


def as_list(value) -> list[str]:
    """Option value -> list: accepts a YAML list or a comma-separated string."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else str(value).replace(";", ",").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def fold(text) -> str:
    """Lower-case and strip diacritics, so "Ústřední dílny" matches "ustredni"."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def filter_departures(departures, *, destinations=(), exclude=(), lines=(), min_minutes: int = 0) -> list[dict]:
    """Keep the departures you care about.

    destinations: keep only these directions (end stops); part of the name is
    enough and diacritics/case do not matter. exclude: drop these directions.
    lines: keep only these line numbers. min_minutes: drop departures leaving
    in less than this many minutes (you would not make it to the stop).
    """
    wanted = [fold(d) for d in as_list(destinations)]
    unwanted = [fold(d) for d in as_list(exclude)]
    line_set = {fold(line) for line in as_list(lines)}
    kept = []
    for dep in departures or []:
        destination = fold(dep.get("destination"))
        if wanted and not any(w in destination for w in wanted):
            continue
        if unwanted and any(u in destination for u in unwanted):
            continue
        if line_set and fold(dep.get("line")) not in line_set:
            continue
        if int(dep.get("minutes") or 0) < int(min_minutes or 0):
            continue
        kept.append(dep)
    return kept


# ---------------------------------------------------------- day outlook


@dataclass
class Outlook:
    """The next few hours of an hourly forecast, digested for a glance at the door."""

    hours: list[dict] = field(default_factory=list)  # {when, temp, rain (0..1), mm, prob, wet, condition}
    hi: float | None = None
    lo: float | None = None
    rain_windows: list[tuple] = field(default_factory=list)  # (start, end, peak 0..1)
    snow: bool = False
    storm: bool = False
    wind_max: float | None = None
    uv_max: float | None = None
    has_amounts: bool = False  # the forecast gives precipitation in mm
    has_probability: bool = False  # ...and/or a probability in %
    total_mm: float = 0.0  # summed over the outlook's hours
    max_mm: float = 0.0  # wettest single hour
    max_prob: float = 0.0

    @property
    def wet(self) -> bool:
        return bool(self.rain_windows)


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def day_outlook(hourly: list[dict], now: datetime, *, hours: int = 12, to_local=None,
                current_temperature=None) -> Outlook:
    """Digest an hourly forecast from `now` for `hours` hours.

    An hour counts as wet when its precipitation probability is >= 40 %, or -
    for forecasts that only give amounts, like met.no - when >= 0.2 mm falls.
    """
    parse = to_local or (lambda v: datetime.fromisoformat(str(v)).replace(tzinfo=None))
    entries = []
    first = now.replace(minute=0, second=0, microsecond=0)  # `hours` slots, starting with the current one
    for h in hourly or []:
        try:
            when = parse(h["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if first <= when < first + timedelta(hours=hours):
            entries.append((when, h))
    out = Outlook()
    current = _float(current_temperature)
    if not entries:
        out.hi = out.lo = current
        return out
    fractions = rain_fractions([h for _, h in entries])
    has_probability = any(h.get("precipitation_probability") is not None for _, h in entries)
    temps = [t for t in (_float(h.get("temperature")) for _, h in entries) if t is not None]
    if current is not None:
        temps.append(current)
    out.hi, out.lo = (max(temps), min(temps)) if temps else (None, None)
    winds = [w for w in (_float(h.get("wind_speed")) for _, h in entries) if w is not None]
    uvs = [u for u in (_float(h.get("uv_index")) for _, h in entries) if u is not None]
    out.wind_max = max(winds) if winds else None
    out.uv_max = max(uvs) if uvs else None
    window = None
    for (when, h), fraction in zip(entries, fractions):
        condition = str(h.get("condition") or "")
        if has_probability:
            wet = (_float(h.get("precipitation_probability")) or 0) >= 40
        else:
            wet = (_float(h.get("precipitation")) or 0) >= 0.2
        out.snow |= condition in ("snowy", "snowy-rainy") and wet
        out.storm |= condition.startswith("lightning")
        mm = _float(h.get("precipitation"))
        prob = _float(h.get("precipitation_probability"))
        if mm is not None:
            out.has_amounts = True
            out.total_mm += max(0.0, mm)
            out.max_mm = max(out.max_mm, mm)
        if prob is not None:
            out.has_probability = True
            out.max_prob = max(out.max_prob, prob)
        out.hours.append({"when": when, "temp": _float(h.get("temperature")), "rain": fraction, "mm": mm,
                          "prob": prob, "wet": wet, "condition": condition})
        if wet:
            if window is None:
                window = [when, when + timedelta(hours=1), fraction]
            else:
                window[1], window[2] = when + timedelta(hours=1), max(window[2], fraction)
        elif window is not None:
            out.rain_windows.append(tuple(window))
            window = None
    if window is not None:
        out.rain_windows.append(tuple(window))
    return out


def describe_rain(outlook: Outlook, now: datetime) -> str:
    """'Prší do 9 h', 'Déšť 15–18 h', 'Déšť od 15 h' or 'Bez deště'."""
    if not outlook.wet:
        return "Bez deště"
    start, end, _peak = outlook.rain_windows[0]
    if start <= now:
        return f"{'Sněží' if outlook.snow else 'Prší'} do {end:%H} h"
    word = "Sníh" if outlook.snow else "Déšť"
    if outlook.hours and end > outlook.hours[-1]["when"]:
        return f"{word} od {start:%H} h"
    return f"{word} {start:%H}–{end:%H} h"


def clothing_advice(outlook: Outlook, feels_like=None) -> list[tuple[str, bool]]:
    """What to put on, as (text, important) - from the coldest of now and the next hours."""
    candidates = [v for v in (_float(feels_like), outlook.lo) if v is not None]
    advice: list[tuple[str, bool]] = []
    if candidates:
        cold = min(candidates)
        if cold <= -5:
            advice += [("Zimní bunda", False), ("Čepice, rukavice", False)]
        elif cold <= 3:
            advice += [("Teplá bunda", False), ("Čepice", False)]
        elif cold <= 10:
            advice.append(("Bunda", False))
        elif cold <= 16:
            advice.append(("Lehká bunda", False))
        elif cold <= 21:
            advice.append(("Mikina", False))
        else:
            advice.append(("Nalehko", False))
    if outlook.wet:
        advice.insert(0, ("Deštník", True))
    if outlook.lo is not None and outlook.lo <= 1 and (outlook.snow or outlook.wet):
        advice.append(("Pozor, kluzko", True))
    if outlook.storm:
        advice.append(("Bouřky", True))
    if outlook.wind_max is not None and outlook.wind_max >= 40:
        advice.append(("Silný vítr", False))
    if outlook.uv_max is not None and outlook.uv_max >= 6:
        advice.append(("Opalovací krém", False))
    if outlook.hi is not None and outlook.hi >= 28:
        advice.append(("Voda s sebou", False))
    return advice


# --------------------------------------------------------------- alerts


ACTIVE_STATES = {"on", "open", "opening", "unlocked", "true", "detected", "problem"}


def active_alerts(ctx, entities) -> list[str]:
    """Friendly names of the given entities that are on / open / unlocked right now."""
    names = []
    for entity_id in as_list(entities):
        state = str(ctx.state(entity_id, "") or "").casefold()
        if state in ACTIVE_STATES:
            names.append(str(ctx.attr(entity_id, "friendly_name", entity_id)))
    return names
