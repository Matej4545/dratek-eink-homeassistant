"""What a screen's ``render(ctx)`` gets: data access, the canvas, fonts, icons.

Every entity a screen reads is recorded in ``ctx.accessed``. The simulator uses
that as the screen's dependency list (like HA's template engine does), so a
screen does not have to declare which entities should trigger a redraw.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .component import FONT_DIR, MDI_PATHS_JS
from .panel import BLACK, RED, WHITE, YELLOW, PanelSpec
from .state import StateSource, parse_dt

DEVTOOLS = Path(__file__).resolve().parents[1]
EXTRA_FONT_DIR = DEVTOOLS / "fonts"  # drop any .ttf/.otf here; family = file stem
EXTRA_ICON_DIR = DEVTOOLS / "icons"  # drop any .svg here; ctx.icon("file-stem")


@lru_cache(maxsize=1)
def _mdi_paths() -> dict[str, str]:
    if not MDI_PATHS_JS.exists():
        return {}
    text = MDI_PATHS_JS.read_text(encoding="utf-8")
    return dict(re.findall(r'^\s*"([a-z0-9-]+)":\s*"([^"]+)"', text, re.M))


def _font_file(family: str) -> Path:
    for folder in (EXTRA_FONT_DIR, FONT_DIR):
        for ext in (".ttf", ".otf"):
            candidate = folder / f"{family}{ext}"
            if candidate.exists():
                return candidate
    return FONT_DIR / "Arimo-wght.ttf"


@lru_cache(maxsize=256)
def _font(family: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_font_file(family)), size)
    try:
        axes = font.get_variation_axes()
        if axes:
            lo, hi = axes[0]["minimum"], axes[0]["maximum"]
            font.set_variation_by_axes([max(lo, min(hi, weight))])
    except OSError:
        pass  # static font: weight is whatever the file is
    return font


def rasterize_svg(svg: str, width: int, height: int) -> Image.Image:
    import resvg_py

    font = FONT_DIR / "Arimo-wght.ttf"
    extra = [str(p) for p in EXTRA_FONT_DIR.glob("*.[ot]tf")] if EXTRA_FONT_DIR.exists() else []
    png = resvg_py.svg_to_bytes(
        svg_string=svg,
        width=int(width),
        height=int(height),
        font_files=[str(font), *extra],
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
        panel: PanelSpec,
        size: tuple[int, int],
        source: StateSource,
        now: datetime,
        default_family: str = "Arimo-wght",
    ) -> None:
        self.panel = panel
        self.width, self.height = size
        self.size = size
        self.now = now
        self.source = source
        self.accessed: set[str] = set()
        self.default_family = default_family
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
        return (entity or {}).get("attributes", {}).get(name, default)

    def num(self, entity_id: str, default: float | None = None, attr: str | None = None) -> float | None:
        raw = self.attr(entity_id, attr) if attr else self.state(entity_id)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def forecast(self, entity_id: str, kind: str = "daily") -> list[dict[str, Any]]:
        self.accessed.add(entity_id)
        return self.source.forecast(entity_id, kind)

    def history(self, entity_id: str, hours: float = 24) -> list[tuple[datetime, float]]:
        self.accessed.add(entity_id)
        return self.source.history(entity_id, self.now - timedelta(hours=hours), self.now)

    @staticmethod
    def dt(value: Any) -> datetime:
        """Parse an HA timestamp to naive local time."""
        when = parse_dt(value)
        return when.astimezone().replace(tzinfo=None) if when.tzinfo else when

    # --------------------------------------------------------------- drawing
    def canvas(self, color: tuple[int, int, int] = WHITE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGB", self.size, color)
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"  # no anti-aliasing: crisp glyphs instead of dithered fuzz
        return image, draw

    def font(self, size: int, weight: int = 400, family: str | None = None) -> ImageFont.FreeTypeFont:
        return _font(family or self.default_family, int(size), int(weight))

    def icon(self, name: str, size: int, color: tuple[int, int, int] = BLACK) -> Image.Image:
        """An RGBA icon: an MDI name (subset in tests/vendor/mdi) or devtools/icons/<name>.svg."""
        custom = EXTRA_ICON_DIR / f"{name}.svg"
        if custom.exists():
            layer = rasterize_svg(custom.read_text(encoding="utf-8"), size, size)
        else:
            path = _mdi_paths().get(name)
            if not path:
                raise KeyError(f"Unknown icon {name!r} (add devtools/icons/{name}.svg)")
            layer = rasterize_svg(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path}"/></svg>',
                size,
                size,
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
        return rasterize_svg(svg, width or self.width, height or self.height)
