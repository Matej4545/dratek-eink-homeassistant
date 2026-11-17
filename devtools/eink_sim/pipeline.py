"""Screen file -> drawn image -> panel pigments -> wire bytes -> what the panel prints.

A *screen* is a plain Python file::

    ORIENTATION = "landscape"   # optional: landscape | portrait
    DITHER = "ordered"          # optional: ordered | floyd | none
    INTERVAL = 900              # optional: also redraw every N seconds (clocks, "x min ago")
    ENTITIES = [...]            # optional: extra triggers; entities read in render() are tracked anyway

    def render(ctx):
        img, draw = ctx.canvas()
        draw.text((10, 10), f"{ctx.num('sensor.outside_temperature'):.1f} °C", font=ctx.font(48, 700), fill=ctx.BLACK)
        return img               # a PIL image of ctx.size - or an SVG string
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType

import numpy as np
from PIL import Image

from . import dither, panel
from .context import RenderContext
from .state import StateSource


def load_screen(path: str | Path) -> ModuleType:
    """Import a screen file fresh every call (so edits are picked up live)."""
    path = Path(path).resolve()
    # Forget helper modules imported from the screen's folder, too.
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None) or ""
        if file and Path(file).resolve().parent == path.parent:
            del sys.modules[name]
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"eink_screen_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load screen {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "render", None)):
        raise AttributeError(f"{path.name} has no render(ctx) function")
    return module


DEFAULT_SDK_TYPE = 46  # EPA LCD 296x128 BWRY - the Drátek 2.9" 4-colour label


def screen_sdk_type(screen: ModuleType | str | Path) -> int:
    """The panel a screen was designed for (its SDK_TYPE), else the default."""
    try:
        module = screen if isinstance(screen, ModuleType) else load_screen(screen)
        return int(getattr(module, "SDK_TYPE", DEFAULT_SDK_TYPE))
    except Exception:  # a broken screen still gets a panel; the error shows on render
        return DEFAULT_SDK_TYPE


@dataclass
class Frame:
    drawn: Image.Image | None = None  # what render() returned
    quantized: Image.Image | None = None  # reduced to the panel's pigments
    panel_image: Image.Image | None = None  # decoded back from the wire bytes
    payload: bytes = b""
    wire: bytes = b""
    digest: str = ""
    accessed: set[str] = field(default_factory=set)
    render_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def render_frame(
    screen: ModuleType | str | Path,
    source: StateSource,
    sdk_type: int,
    now: datetime | None = None,
    *,
    transform: str | None = None,
    framed: bool = False,
    dither_mode: str | None = None,
) -> Frame:
    frame = Frame()
    try:
        module = screen if isinstance(screen, ModuleType) else load_screen(screen)
        spec = panel.panel_spec(sdk_type)
        orientation = getattr(module, "ORIENTATION", "landscape")
        size = spec.canvas_size(orientation)
        ctx = RenderContext(spec, size, source, now or source.now or datetime.now().replace(microsecond=0))
        started = time.perf_counter()
        result = module.render(ctx)
        if isinstance(result, str):
            layer = ctx.svg(result)
            result = Image.new("RGB", size, panel.WHITE)
            result.paste(layer, (0, 0), layer)
        if not isinstance(result, Image.Image):
            raise TypeError(f"render() returned {type(result).__name__}, expected a PIL image or SVG string")
        if result.size != size:
            raise ValueError(f"render() returned {result.size[0]}x{result.size[1]}, panel canvas is {size[0]}x{size[1]}")
        frame.render_ms = (time.perf_counter() - started) * 1000
        frame.accessed = set(ctx.accessed) | set(getattr(module, "ENTITIES", []) or [])
        frame.drawn = result.convert("RGB")

        mode = dither_mode or getattr(module, "DITHER", "ordered")
        # Four-colour packing can carry yellow even where the model name says BWR.
        frame.quantized = dither.quantize(frame.drawn, spec.colors, mode)

        frame.payload, frame.wire = panel.encode(sdk_type, frame.quantized, orientation, transform, framed)
        decoded = panel.decode(sdk_type, frame.wire, size, orientation, transform, framed)
        frame.panel_image = decoded.image
        frame.warnings += decoded.warnings
        frame.digest = hashlib.sha1(frame.payload).hexdigest()[:12]

        mismatch = int((np.asarray(decoded.image) != np.asarray(frame.quantized)).any(-1).sum())
        if mismatch and not decoded.warnings:
            frame.warnings.append(
                f"{mismatch} pixels differ between the quantized image and what the packer produced "
                "(the integration's classifier disagrees with the palette)."
            )
    except Exception:  # surfaced in the UI/report, never fatal for the server
        frame.error = traceback.format_exc()
    return frame


def changed_box(previous: Image.Image | None, current: Image.Image) -> tuple[int, int, int, int] | None:
    if previous is None or previous.size != current.size:
        return (0, 0, current.width, current.height)
    diff = np.asarray(previous) != np.asarray(current)
    rows, cols = np.where(diff.any(-1))
    if not len(rows):
        return None
    return (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)
