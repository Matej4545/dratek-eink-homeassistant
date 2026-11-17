"""What a screen's ``render(ctx)`` gets: data access, the canvas, fonts, icons.

Pure Pillow, no Home Assistant imports. Home Assistant (screen_runtime.py) and
the local simulator (devtools/) both build a RenderContext around their own
*source* - an object with ``get``, ``forecast``, ``history`` and ``transit`` -
so a screen behaves identically in both.

Every entity a screen reads is recorded in ``ctx.accessed``; the runtime
redraws when one of them changes, the way HA template sensors work. Data that
needs a service call or a network request (forecasts, history, departures) is
read from what the source already fetched; a request it could not answer is
recorded in ``ctx.missing`` so the runtime can fetch it and render again.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageDraw, ImageFont

COMPONENT_DIR = Path(__file__).resolve().parent
BUNDLED_FONT_DIR = COMPONENT_DIR / "frontend" / "fonts"
MDI_PATHS_FILE = COMPONENT_DIR / "screen_assets" / "mdi-paths.json"
EXTRA_ICONS_FILE = COMPONENT_DIR / "screen_assets" / "extra-icons.json"
DEFAULT_FONT_FILE = BUNDLED_FONT_DIR / "Arimo-wght.ttf"

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (220, 20, 12)  # render.BWR_RED
YELLOW = (244, 196, 0)  # render.BWR_YELLOW


class Source(Protocol):
    def get(self, entity_id: str) -> dict[str, Any] | None: ...
    def forecast(self, entity_id: str, kind: str) -> list[dict[str, Any]] | None: ...
    def history(self, entity_id: str, hours: float, now: datetime) -> list[tuple[datetime, float]] | None: ...
    def transit(self, stop_id: str, limit: int) -> dict[str, Any] | None: ...
    def calendar(self, entity_id: str, hours: float) -> list[dict[str, Any]] | None: ...


class PanelInfo(Protocol):
    sdk_type: int
    model: str
    has_red: bool
    has_yellow: bool


@lru_cache(maxsize=1)
def _mdi_paths() -> dict[str, str]:
    """MDI subset (Pictogrammers, Apache-2.0) plus a few simple icons of our own."""
    paths: dict[str, str] = {}
    for file in (MDI_PATHS_FILE, EXTRA_ICONS_FILE):
        try:
            paths.update(json.loads(file.read_text(encoding="utf-8")))
        except OSError:
            pass
    return paths


def _find_font(family: str, font_dirs: tuple[Path, ...]) -> Path:
    for folder in font_dirs:
        for ext in (".ttf", ".otf"):
            candidate = folder / f"{family}{ext}"
            if candidate.exists():
                return candidate
    return DEFAULT_FONT_FILE


@lru_cache(maxsize=256)
def _font(path: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    try:
        axes = font.get_variation_axes()
        if axes:
            lo, hi = axes[0]["minimum"], axes[0]["maximum"]
            font.set_variation_by_axes([max(lo, min(hi, weight))])
    except OSError:
        pass  # static font: the weight is whatever the file is
    return font


def rasterize_svg(svg: str, width: int, height: int, font_dirs: tuple[Path, ...] = ()) -> Image.Image:
    import resvg_py

    extra = [str(p) for folder in font_dirs if folder.exists() for p in folder.glob("*.[ot]tf")]
    png = resvg_py.svg_to_bytes(
        svg_string=svg,
        width=int(width),
        height=int(height),
        font_files=[str(DEFAULT_FONT_FILE), *extra],
        font_family="Arimo",
        sans_serif_family="Arimo",
    )
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


class RenderContext:
    BLACK = BLACK
    WHITE = WHITE
    RED = RED
    YELLOW = YELLOW
    GRAY = (128, 128, 128)  # dithers to a 50 % pattern
    LIGHT_GRAY = (200, 200, 200)
    DARK_GRAY = (70, 70, 70)

    def __init__(
        self,
        panel: PanelInfo,
        size: tuple[int, int],
        source: Source,
        now: datetime,
        *,
        options: dict[str, Any] | None = None,
        tz: tzinfo | None = None,
        font_dirs: tuple[Path, ...] = (),
        icon_dirs: tuple[Path, ...] = (),
    ) -> None:
        self.panel = panel
        self.width, self.height = size
        self.size = size
        self.now = now  # naive, in the Home Assistant time zone
        self.options: dict[str, Any] = dict(options or {})
        self.source = source
        self.tz = tz
        self.accessed: set[str] = set()
        self.missing: set[tuple] = set()
        self.requested: set[tuple] = set()
        self._font_dirs = tuple(font_dirs) + (BUNDLED_FONT_DIR,)
        self._icon_dirs = tuple(icon_dirs)
        # The colour for highlights: red where the panel has it, black otherwise.
        self.accent = RED if panel.has_red else BLACK

    # ------------------------------------------------------------------ data
    def entity(self, entity_id: str) -> dict[str, Any] | None:
        self.accessed.add(entity_id)
        return self.source.get(entity_id)

    def state(self, entity_id: str, default: Any = None) -> Any:
        entity = self.entity(entity_id)
        if not entity or entity["state"] in ("unknown", "unavailable"):
            return default
        return entity["state"]

    def attr(self, entity_id: str, name: str, default: Any = None) -> Any:
        entity = self.entity(entity_id)
        value = (entity or {}).get("attributes", {}).get(name, default)
        return default if value is None else value

    def num(self, entity_id: str, default: float | None = None, attr: str | None = None) -> float | None:
        raw = self.attr(entity_id, attr) if attr else self.state(entity_id)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _ask(self, key: tuple, answer: Any, empty: Any) -> Any:
        self.requested.add(key)
        if answer is None:
            self.missing.add(key)
            return empty
        return answer

    def forecast(self, entity_id: str, kind: str = "daily") -> list[dict[str, Any]]:
        """What weather.get_forecasts returns: kind is daily, hourly or twice_daily."""
        self.accessed.add(entity_id)
        return list(self._ask(("forecast", entity_id, kind), self.source.forecast(entity_id, kind), []))

    def history(self, entity_id: str, hours: float = 24) -> list[tuple[datetime, float]]:
        """Numeric history of an entity as (local time, value) pairs."""
        self.accessed.add(entity_id)
        hours = float(hours)
        return list(self._ask(("history", entity_id, hours), self.source.history(entity_id, hours, self.now), []))

    def transit(self, stop_id: str, limit: int = 6) -> dict[str, Any]:
        """Live departures (transit.py, Transitous): {stop_name, departures: [...]}."""
        limit = int(limit)
        empty = {"stop_name": "", "departures": []}
        return dict(self._ask(("transit", str(stop_id), limit), self.source.transit(str(stop_id), limit), empty))

    def calendar(self, entity_id: str, hours: float = 24) -> list[dict[str, Any]]:
        """Upcoming events (calendar.get_events): [{summary, start, end, location}], soonest first.

        start/end are naive local datetimes; all-day events have ``all_day: True``.
        """
        self.accessed.add(entity_id)
        hours = float(hours)
        raw = self._ask(("calendar", entity_id, hours), self.source.calendar(entity_id, hours), [])
        events = []
        for event in raw or []:
            try:
                start_raw, end_raw = str(event.get("start")), str(event.get("end") or event.get("start"))
                all_day = len(start_raw) == 10  # "2026-11-17" - a date, not a time
                events.append({
                    **event,
                    "start": self.dt(start_raw), "end": self.dt(end_raw), "all_day": all_day,
                })
            except (TypeError, ValueError):
                continue
        return sorted(events, key=lambda e: e["start"])

    def dt(self, value: Any) -> datetime:
        """Parse an HA timestamp to naive time in the Home Assistant time zone."""
        when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if when.tzinfo is not None:
            when = when.astimezone(self.tz) if self.tz else when.astimezone()
            when = when.replace(tzinfo=None)
        return when

    def minutes_until(self, value: Any) -> int:
        return int((self.dt(value) - self.now) // timedelta(minutes=1))

    # --------------------------------------------------------------- drawing
    def canvas(self, color: tuple[int, int, int] = WHITE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGB", self.size, color)
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"  # no anti-aliasing: crisp glyphs instead of dithered fuzz
        return image, draw

    def font(self, size: int, weight: int = 400, family: str = "Arimo-wght") -> ImageFont.FreeTypeFont:
        return _font(str(_find_font(family, self._font_dirs)), int(size), int(weight))

    def icon(self, name: str, size: int, color: tuple[int, int, int] = BLACK) -> Image.Image:
        """An RGBA icon: an MDI name from the bundled subset, or <icons dir>/<name>.svg."""
        layer = None
        for folder in self._icon_dirs:
            custom = folder / f"{name}.svg"
            if custom.exists():
                layer = rasterize_svg(custom.read_text(encoding="utf-8"), size, size, self._font_dirs)
                break
        if layer is None:
            path = _mdi_paths().get(name)
            if not path:
                raise KeyError(f"Unknown icon {name!r}; add it as an .svg to your screens' icons folder")
            layer = rasterize_svg(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path}"/></svg>', size, size
            )
        alpha = layer.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        solid = Image.new("RGBA", layer.size, color + (0,))
        solid.putalpha(alpha)
        return solid

    def paste_icon(self, image: Image.Image, name: str, xy: tuple[int, int], size: int,
                   color: tuple[int, int, int] = BLACK) -> None:
        glyph = self.icon(name, size, color)
        image.paste(glyph, (int(xy[0]), int(xy[1])), glyph)

    def svg(self, svg: str, width: int | None = None, height: int | None = None) -> Image.Image:
        """Rasterise SVG markup (gradients, paths, patterns...) to an RGBA layer."""
        return rasterize_svg(svg, width or self.width, height or self.height, self._font_dirs)
