"""Screen file -> panel image, via the integration's own code.

Rendering is ``screen_render.render_screen`` from custom_components/dratek_eink -
the exact function Home Assistant runs - followed by the real packer and an
independent decode of its bytes (panel.py) to show what the panel would print.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import panel
from .component import BUNDLED_SCREENS, load
from .state import StateSource

screen_render = load("screen_render")
DEFAULT_SDK_TYPE = 46  # EPA LCD 296x128 BWRY - the Drátek 2.9" 4-colour label
DEVTOOLS = Path(__file__).resolve().parents[1]


def resolve_screen_path(screen: str | Path) -> Path:
    """A path, or the id of a bundled screen ("mini_weather")."""
    path = Path(screen)
    if path.suffix == ".py" or path.exists():
        return path.resolve()
    return (BUNDLED_SCREENS / f"{screen}.py").resolve()


def load_screen(screen: str | Path):
    """Read a screen fresh (so edits are picked up). Raises if it fails to load."""
    info = screen_render.read_screen(resolve_screen_path(screen))
    if info.error:
        raise RuntimeError(info.error)
    return info


def screen_sdk_type(screen: Any) -> int:
    """The panel a screen was designed for (its SDK_TYPE), else the default."""
    try:
        info = screen if hasattr(screen, "module") else load_screen(screen)
        return int(info.sdk_type or DEFAULT_SDK_TYPE)
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
    screen: Any,
    source: StateSource,
    sdk_type: int,
    now: datetime | None = None,
    *,
    options: dict[str, Any] | None = None,
    transform: str | None = None,
    framed: bool = False,
    dither_mode: str | None = None,
) -> Frame:
    frame = Frame()
    try:
        info = screen if hasattr(screen, "module") else load_screen(screen)
    except Exception as exc:
        frame.error = str(exc)
        return frame
    unknown = sorted(set(options or {}) - set(info.options))
    if unknown:
        frame.warnings.append(f"Unknown option(s) {', '.join(unknown)}; {info.id} accepts: {', '.join(info.options) or 'none'}")
    result = screen_render.render_screen(
        info.module, source, sdk_type, now or source.now or datetime.now().replace(microsecond=0),
        options=screen_render.resolve_options(info, options),
        font_dirs=(DEVTOOLS / "fonts",), icon_dirs=(DEVTOOLS / "icons",), dither_mode=dither_mode,
    )
    frame.accessed, frame.render_ms = result.accessed, result.render_ms
    if not result.ok:
        frame.error = result.error
        return frame
    frame.drawn, frame.quantized = result.drawn, result.image
    try:
        frame.payload, frame.wire = panel.encode(sdk_type, frame.quantized, result.orientation, transform, framed)
        decoded = panel.decode(sdk_type, frame.wire, frame.quantized.size, result.orientation, transform, framed)
    except Exception as exc:
        frame.error = f"Packing failed: {exc}"
        return frame
    frame.panel_image = decoded.image
    frame.warnings += decoded.warnings
    frame.digest = hashlib.sha1(frame.payload).hexdigest()[:12]
    mismatch = int((np.asarray(decoded.image) != np.asarray(frame.quantized)).any(-1).sum())
    if mismatch and not decoded.warnings:
        frame.warnings.append(
            f"{mismatch} pixels differ between the quantized image and what the packer produced "
            "(the integration's classifier disagrees with the palette)."
        )
    return frame


def changed_box(previous: Image.Image | None, current: Image.Image) -> tuple[int, int, int, int] | None:
    if previous is None or previous.size != current.size:
        return (0, 0, current.width, current.height)
    diff = np.asarray(previous) != np.asarray(current)
    rows, cols = np.where(diff.any(-1))
    if not len(rows):
        return None
    return (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)
