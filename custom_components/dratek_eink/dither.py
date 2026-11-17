"""Reduce a full-colour picture to the panel's pigments.

Draw with any colour - greys, light red, orange - and this turns it into the
2-4 colours the panel has. Exact pigment colours (crisp text, lines) pass
through untouched; everything else is dithered.

``ordered`` (Bayer 8x8) is the default because it is *local*: changing one
number only changes the pixels around it. Error diffusion (``floyd``) looks
smoother on photos, but one changed pixel can ripple across the whole image.
``threshold`` leaves the image alone and lets the packer's own black/white/red
rule (render.bwr_masks) classify each pixel - the integration's old behaviour.

numpy is imported lazily: if it is missing, ``ordered`` falls back to Pillow's
Floyd-Steinberg so the integration still loads and still sends.

Shared verbatim with the local simulator (devtools/eink_sim), so a screen
previewed on a PC is quantized exactly like the one sent from Home Assistant.
"""

from __future__ import annotations

import logging

from PIL import Image

_LOGGER = logging.getLogger(__name__)

DITHER_MODES = ("ordered", "floyd", "none", "threshold")
SNAP_DISTANCE = 24.0  # pixels this close to a pigment are treated as that pigment
_WEIGHTS = (38 / 128, 75 / 128, 15 / 128)  # same luma split as render.py
_BAYER_CACHE: dict[int, object] = {}


def _pil_quantize(image: Image.Image, palette, dither: Image.Dither) -> Image.Image:
    pal_img = Image.new("P", (1, 1))
    flat = [c for colour in palette for c in colour]
    pal_img.putpalette(flat + flat[:3] * (256 - len(palette)))
    return image.quantize(palette=pal_img, dither=dither).convert("RGB")


def _bayer(np, n: int = 8):
    if n not in _BAYER_CACHE:
        m = np.array([[0, 2], [3, 1]])
        while m.shape[0] < n:
            m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
        _BAYER_CACHE[n] = (m + 0.5) / m.size - 0.5  # -0.5 .. 0.5, mean 0
    return _BAYER_CACHE[n]


def quantize(
    image: Image.Image,
    palette: tuple[tuple[int, int, int], ...],
    mode: str = "ordered",
) -> Image.Image:
    rgb_img = image.convert("RGB")
    if mode == "threshold":
        return rgb_img
    if mode == "floyd":
        return _pil_quantize(rgb_img, palette, Image.Dither.FLOYDSTEINBERG)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy ships with HA, but never fail a send over it
        _LOGGER.warning("numpy unavailable; using Floyd-Steinberg instead of %s dithering", mode)
        dither = Image.Dither.NONE if mode == "none" else Image.Dither.FLOYDSTEINBERG
        return _pil_quantize(rgb_img, palette, dither)

    weights = np.array(_WEIGHTS, dtype=np.float32)
    pal = np.array(palette, dtype=np.float32)

    def nearest(rgb, candidates):
        diff = rgb[..., None, :] - candidates[None, None, :, :]
        dist = (diff * diff * weights).sum(-1)
        return dist.argmin(-1), dist.min(-1)

    rgb = np.asarray(rgb_img, dtype=np.float32)
    index, dist = nearest(rgb, pal)
    if mode == "ordered":
        h, w = rgb.shape[:2]
        bayer = _bayer(np)
        threshold = np.tile(bayer, (h // 8 + 1, w // 8 + 1))[:h, :w]
        # Spread = full black-white distance, so a 50 % grey becomes a 50 % pattern.
        shifted = rgb + threshold[..., None] * 255.0
        dithered, _ = nearest(shifted, pal)
        chroma = rgb.max(-1) - rgb.min(-1)
        # Greys must stay grey: in plain RGB distance a mid-grey is closer to red
        # than to black or white, which would stipple every grey fill with red.
        achromatic = [i for i, c in enumerate(palette) if max(c) - min(c) < 16]
        if len(achromatic) >= 2:
            grey, _ = nearest(shifted, pal[achromatic])
            dithered = np.where(chroma < 48, np.array(achromatic)[grey], dithered)
        # Likewise a bright colour (orange between red and yellow, pink) must not
        # pick up black specks: mix it from the non-black pigments only.
        not_black = [i for i, c in enumerate(palette) if sum(c) > 0]
        if len(not_black) < len(palette):
            bright, _ = nearest(shifted, pal[not_black])
            luma = (rgb * weights).sum(-1)
            dithered = np.where((chroma >= 48) & (luma >= 96), np.array(not_black)[bright], dithered)
        index = np.where(dist <= SNAP_DISTANCE**2, index, dithered)
    return Image.fromarray(pal.astype(np.uint8)[index], "RGB")
