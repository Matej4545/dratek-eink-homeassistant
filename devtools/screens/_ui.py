"""Small helpers shared by the example screens. Plain Pillow - copy, change, extend."""

from __future__ import annotations

import math

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
