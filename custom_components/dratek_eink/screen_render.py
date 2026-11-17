"""Screens as code: load screen files, render one, and decide when to redraw.

Pure (no Home Assistant imports). Home Assistant's runtime (screen_runtime.py)
and the local simulator (devtools/) both use exactly these three pieces:

* ``scan_screens`` - find screen files and read their metadata;
* ``render_screen`` - screen + data source + options -> panel-ready image;
* ``UpdatePolicy`` - debounce, minimum gap between panel writes, interval.

A screen is a Python file::

    TITLE = "Weather"                 # optional, shown in Home Assistant
    SDK_TYPE = 46                     # optional: the panel it is laid out for
    OPTIONS = {"weather": "weather.home"}   # per-display settings + defaults
    INTERVAL = 3600                   # optional: also redraw every N seconds
    ORIENTATION = "landscape"         # or "portrait"
    DITHER = "ordered"                # ordered | floyd | none | threshold

    def render(ctx):
        img, draw = ctx.canvas()
        ...
        return img                    # PIL image of ctx.size, or an SVG string
"""

from __future__ import annotations

import importlib.util
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image

from . import screen_ui
from .const import SDK_MODELS
from .dither import quantize
from .render import display_size
from .screen_context import RenderContext, Source
from .screen_image import canvas_size, panel_palette

HELPER_MODULE = "dratek_screen"  # `from dratek_screen import num, WEATHER_ICONS` in screen files
OFF = "off"


# ---------------------------------------------------------------- library


@dataclass
class ScreenInfo:
    id: str
    path: Path
    title: str = ""
    description: str = ""
    sdk_type: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    interval: float | None = None
    orientation: str = "landscape"
    dither: str = "ordered"
    bundled: bool = False
    module: ModuleType | None = None
    error: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title or self.id, "description": self.description,
            "sdk_type": self.sdk_type, "options": dict(self.options), "interval": self.interval,
            "source": "bundled" if self.bundled else str(self.path), "error": self.error,
        }


def load_screen_module(path: Path, module_name: str | None = None) -> ModuleType:
    """Execute a screen file as a fresh module (blocking: run in an executor)."""
    sys.modules[HELPER_MODULE] = screen_ui
    name = module_name or f"dratek_screen_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load screen {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "render", None)):
        raise AttributeError(f"{path.name} has no render(ctx) function")
    return module


def read_screen(path: Path, bundled: bool = False) -> ScreenInfo:
    info = ScreenInfo(id=path.stem, path=path, bundled=bundled)
    try:
        module = load_screen_module(path, f"dratek_screen_{'b' if bundled else 'u'}_{path.stem}")
    except Exception:
        info.error = traceback.format_exc(limit=3)
        return info
    info.module = module
    info.title = str(getattr(module, "TITLE", "") or path.stem)
    info.description = str(getattr(module, "DESCRIPTION", "") or (module.__doc__ or "").strip().split("\n")[0])
    sdk = getattr(module, "SDK_TYPE", None)
    info.sdk_type = int(sdk) if sdk else None
    info.options = dict(getattr(module, "OPTIONS", {}) or {})
    interval = getattr(module, "INTERVAL", None)
    info.interval = float(interval) if interval else None
    info.orientation = str(getattr(module, "ORIENTATION", "landscape"))
    info.dither = str(getattr(module, "DITHER", "ordered"))
    return info


def scan_screens(folders: list[tuple[Path, bool]]) -> dict[str, ScreenInfo]:
    """Screens from (folder, bundled) pairs; a later folder overrides an earlier id.

    Files starting with "_" are helpers, not screens. Blocking: run in an executor.
    """
    screens: dict[str, ScreenInfo] = {}
    for folder, bundled in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            if not path.name.startswith("_"):
                screens[path.stem] = read_screen(path, bundled)
    return screens


def is_compatible(info: ScreenInfo, sdk_type: int | None) -> bool:
    """A screen laid out for one panel size only fits panels of that size."""
    if info.sdk_type is None or not sdk_type:
        return True
    try:
        return sorted(display_size(info.sdk_type)) == sorted(display_size(int(sdk_type)))
    except ValueError:
        return False


def resolve_options(info: ScreenInfo, stored: dict[str, Any] | None) -> dict[str, Any]:
    return {**info.options, **{k: v for k, v in (stored or {}).items() if k in info.options}}


def check_options(info: ScreenInfo, options: dict[str, Any]) -> None:
    unknown = sorted(set(options) - set(info.options))
    if unknown:
        known = ", ".join(sorted(info.options)) or "none"
        raise ValueError(f"Screen {info.id!r} has no option(s) {', '.join(unknown)}; it accepts: {known}.")


# ----------------------------------------------------------------- render


@dataclass
class Panel:
    sdk_type: int
    model: str
    has_red: bool
    has_yellow: bool


def panel_info(sdk_type: int) -> Panel:
    palette = panel_palette(sdk_type)
    return Panel(int(sdk_type), SDK_MODELS.get(int(sdk_type), "unknown"), (220, 20, 12) in palette,
                 (244, 196, 0) in palette)


@dataclass
class RenderResult:
    drawn: Image.Image | None = None  # what render() returned
    image: Image.Image | None = None  # reduced to the panel's pigments, ready to pack
    orientation: str = "landscape"
    accessed: set[str] = field(default_factory=set)  # entities read -> redraw triggers
    requested: set[tuple] = field(default_factory=set)  # forecasts/history/departures asked for
    missing: set[tuple] = field(default_factory=set)  # ...of which the source had no answer
    render_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def render_screen(
    module: ModuleType,
    source: Source,
    sdk_type: int,
    now: datetime,
    *,
    options: dict[str, Any] | None = None,
    tz: tzinfo | None = None,
    font_dirs: tuple[Path, ...] = (),
    icon_dirs: tuple[Path, ...] = (),
    dither_mode: str | None = None,
) -> RenderResult:
    """Run one screen. Never raises: a failure comes back as ``error``. Blocking."""
    result = RenderResult()
    try:
        orientation = str(getattr(module, "ORIENTATION", "landscape"))
        size = canvas_size(sdk_type, orientation)
        result.orientation = orientation
        ctx = RenderContext(
            panel_info(sdk_type), size, source, now,
            options=options, tz=tz, font_dirs=font_dirs, icon_dirs=icon_dirs,
        )
        started = time.perf_counter()
        try:
            drawn = module.render(ctx)
        finally:
            result.accessed = set(ctx.accessed) | set(getattr(module, "ENTITIES", []) or [])
            result.requested, result.missing = set(ctx.requested), set(ctx.missing)
        if isinstance(drawn, str):
            layer = ctx.svg(drawn)
            drawn = Image.new("RGB", size, (255, 255, 255))
            drawn.paste(layer, (0, 0), layer)
        if not isinstance(drawn, Image.Image):
            raise TypeError(f"render() returned {type(drawn).__name__}, expected a PIL image or SVG string")
        if drawn.size != size:
            raise ValueError(f"render() returned {drawn.size[0]}x{drawn.size[1]}, panel canvas is {size[0]}x{size[1]}")
        result.drawn = drawn.convert("RGB")
        mode = dither_mode or str(getattr(module, "DITHER", "ordered"))
        result.image = quantize(result.drawn, panel_palette(sdk_type), mode)
        result.render_ms = (time.perf_counter() - started) * 1000
    except Exception:
        result.error = traceback.format_exc(limit=6)
    return result


# ----------------------------------------------------------------- policy


@dataclass
class UpdatePolicy:
    """When to redraw. Driven by events and a clock (seconds, any monotonic base).

    * a watched entity changed -> redraw ``debounce`` seconds later (bursts coalesce);
    * every ``interval`` seconds if the screen asks for it;
    * never write the panel twice within ``min_gap`` - postpone, never drop;
    * ``force`` (a manual refresh) skips the gap.
    """

    debounce: float = 5.0
    min_gap: float = 600.0
    interval: float | None = None
    last_send_at: float | None = None
    due_at: float | None = None
    reason: str = ""
    forced: bool = False
    next_tick: float | None = None

    def start(self, now: float) -> None:
        self.request(now, "startup", immediate=True)
        self.next_tick = now + self.interval if self.interval else None

    def request(self, now: float, reason: str, *, immediate: bool = False, force: bool = False) -> None:
        when = now if immediate or force else now + self.debounce
        if self.due_at is None or when < self.due_at:
            self.due_at, self.reason = when, reason
        self.forced = self.forced or force

    def on_change(self, now: float, entity_id: str) -> None:
        self.request(now, f"{entity_id} changed")

    def next_wakeup(self) -> float | None:
        times = [t for t in (self.due_at, self.next_tick) if t is not None]
        return min(times) if times else None

    def decide(self, now: float) -> str | None:
        """None (nothing yet), "defer" (moved due_at to the gap's end) or "render"."""
        if self.next_tick is not None and now >= self.next_tick:
            while self.next_tick <= now:
                self.next_tick += self.interval  # type: ignore[operator]
            self.request(now, "interval", immediate=True)
        if self.due_at is None or now < self.due_at:
            return None
        if not self.forced and self.last_send_at is not None and now < self.last_send_at + self.min_gap:
            self.due_at = self.last_send_at + self.min_gap
            return "defer"
        return "render"

    def done(self, now: float, *, sent: bool) -> None:
        self.due_at, self.reason, self.forced = None, "", False
        if sent:
            self.last_send_at = now
