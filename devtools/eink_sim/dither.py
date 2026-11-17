"""The integration's own quantizer (custom_components/dratek_eink/dither.py).

Re-exported rather than copied, so the simulator dithers exactly like the
``show_image`` service does in Home Assistant.
"""

from __future__ import annotations

from .component import load

_dither = load("dither")
quantize = _dither.quantize
DITHER_MODES = _dither.DITHER_MODES
