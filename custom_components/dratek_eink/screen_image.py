"""Turn an arbitrary picture into exactly what one DRATEK panel can show.

Pure Pillow, no Home Assistant imports, so it is unit-testable and shared with
the local simulator. The ``show_image`` service (image_service.py) is the HA
side: it fetches the picture, calls ``prepare_image`` and hands the result to
the existing transfer queue.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from .const import SDK_MODELS
from .dither import DITHER_MODES, quantize
from .render import BWR_RED, BWR_YELLOW, display_size

FIT_MODES = ("contain", "cover", "stretch", "none")
ORIENTATIONS = ("auto", "landscape", "portrait")
# A 40 MP source is far beyond any panel; the cap only stops a decompression bomb.
MAX_SOURCE_PIXELS = 40_000_000

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = tuple(BWR_RED)
YELLOW = tuple(BWR_YELLOW)

__all__ = [
    "DITHER_MODES", "FIT_MODES", "ORIENTATIONS", "canvas_size", "decode_image",
    "fit_image", "panel_palette", "prepare_image",
]


def panel_palette(sdk_type: int) -> tuple[tuple[int, int, int], ...]:
    """The pigments a model physically has, from its SDK model name."""
    model = SDK_MODELS.get(int(sdk_type), "").upper()
    if "BWRY" in model:
        return (BLACK, WHITE, RED, YELLOW)
    if "BWR" in model:
        return (BLACK, WHITE, RED)
    return (BLACK, WHITE)


def canvas_size(sdk_type: int, orientation: str = "landscape") -> tuple[int, int]:
    width, height = display_size(int(sdk_type))
    long_side, short_side = max(width, height), min(width, height)
    return (short_side, long_side) if orientation == "portrait" else (long_side, short_side)


def decode_image(data: bytes) -> Image.Image:
    """Bytes of any Pillow-readable format -> RGB, transparency flattened onto white."""
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Not a readable image ({exc.__class__.__name__}).") from exc
    if image.width * image.height > MAX_SOURCE_PIXELS:
        raise ValueError(f"Image is {image.width}x{image.height}; refusing anything over {MAX_SOURCE_PIXELS} pixels.")
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, WHITE)
        flat.paste(rgba, (0, 0), rgba)
        return flat
    return image.convert("RGB")


def choose_orientation(image: Image.Image, requested: str = "auto") -> str:
    if requested in ("landscape", "portrait"):
        return requested
    return "portrait" if image.height > image.width else "landscape"


def fit_image(image: Image.Image, size: tuple[int, int], fit: str = "contain") -> Image.Image:
    if image.size == size:
        return image
    if fit == "none":
        raise ValueError(
            f"Image is {image.width}x{image.height} but the panel canvas is {size[0]}x{size[1]}; "
            "render it at that size or use fit: contain / cover / stretch."
        )
    if fit == "stretch":
        return image.resize(size, Image.Resampling.LANCZOS)
    if fit == "cover":
        return ImageOps.fit(image, size, Image.Resampling.LANCZOS)
    scale = min(size[0] / image.width, size[1] / image.height)
    scaled = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGB", size, WHITE)
    canvas.paste(scaled, ((size[0] - scaled.width) // 2, (size[1] - scaled.height) // 2))
    return canvas


def prepare_image(
    image: Image.Image,
    sdk_type: int,
    *,
    fit: str = "contain",
    orientation: str = "auto",
    dither: str = "ordered",
) -> tuple[Image.Image, str]:
    """Fit to the panel canvas and reduce to its pigments. Returns (image, orientation)."""
    if fit not in FIT_MODES:
        raise ValueError(f"fit must be one of {', '.join(FIT_MODES)}")
    if dither not in DITHER_MODES:
        raise ValueError(f"dither must be one of {', '.join(DITHER_MODES)}")
    resolved = choose_orientation(image, orientation)
    fitted = fit_image(image.convert("RGB"), canvas_size(sdk_type, resolved), fit)
    return quantize(fitted, panel_palette(sdk_type), dither), resolved
