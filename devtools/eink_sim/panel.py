"""A simulated DRATEK panel: turn wire bytes back into the picture it would print.

``encode`` runs the integration's real packer (and optional QuickLZ framing);
``decode`` is an independent reader of that byte format written from the
protocol notes in render.py / quicklz.py:

* three-colour types: two 1-bit planes (white, red), MSB first, row-major over
  the *hardware* buffer; 800x480 "BWR" types 299/315 invert the first plane and
  are flipped vertically;
* four-colour (BWRY) types: 2 bits per pixel, black=0 white=1 yellow=2 red=3.

Orientation (rotations, flips, padding into the hardware buffer) is undone by
probing ``prepare_image_for_display`` with an image whose every pixel has a
unique colour: rotations/flips/padding move pixels without changing them, so
the probe yields an exact hardware->canvas permutation. If the integration
resized instead (lossy), the probe is not a permutation and we say so.

What this does NOT prove: that the physical panel interprets the bytes this
way. Packing and orientation here reflect this repo's understanding of the
vendor protocol; only real hardware confirms it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from .component import const, load, quicklz, render

screen_image = load("screen_image")

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = tuple(render.BWR_RED)
YELLOW = tuple(render.BWR_YELLOW)

# Colour index used by decode(): matches the BWRY wire values.
_INDEX_COLORS = np.array([BLACK, WHITE, YELLOW, RED], dtype=np.uint8)
I_BLACK, I_WHITE, I_YELLOW, I_RED = 0, 1, 2, 3

# Types whose packer uses the "flip + inverted first plane" variant. 302/310/318
# are also in BWRY_CODES, which pack_bwr_image tests first, so they never get here.
_FLIPPED_BWR = set(render.BWR_800X480_CODES) - set(render.BWRY_CODES)


@dataclass(frozen=True)
class PanelSpec:
    sdk_type: int
    width: int  # native canvas width (landscape as listed in DEVICE_SIZES)
    height: int
    model: str
    colors: tuple[tuple[int, int, int], ...]  # pigments the panel physically has
    four_colour_packing: bool

    @property
    def has_red(self) -> bool:
        return RED in self.colors

    @property
    def has_yellow(self) -> bool:
        return YELLOW in self.colors

    def canvas_size(self, orientation: str = "landscape") -> tuple[int, int]:
        long_side, short_side = max(self.width, self.height), min(self.width, self.height)
        if orientation == "portrait":
            return (short_side, long_side)
        if orientation == "native":
            return (self.width, self.height)
        return (long_side, short_side)


def panel_spec(sdk_type: int) -> PanelSpec:
    code = int(sdk_type)
    width, height = render.display_size(code)
    model = const.SDK_MODELS.get(code, "unknown model")
    colors = screen_image.panel_palette(code)  # same rule the show_image service uses
    return PanelSpec(code, width, height, model, colors, code in render.BWRY_CODES)


def supported_types() -> list[PanelSpec]:
    """Panel types whose packing this simulator understands (B/W, BWR, BWRY)."""
    specs = []
    for code in sorted(const.DEVICE_SIZES):
        spec = panel_spec(code)
        if "COLOR" in spec.model.upper() or "BWRG" in spec.model.upper():
            continue  # multi-colour ACeP-style panels are not packed by this integration
        specs.append(spec)
    return specs


# --------------------------------------------------------------------------- wire


def encode(
    sdk_type: int,
    image: Image.Image,
    orientation: str = "landscape",
    transform: str | None = None,
    framed: bool = False,
) -> tuple[bytes, bytes]:
    """Return (packed planes, bytes on the wire) exactly as the integration builds them."""
    payload = render.pack_bwr_image(int(sdk_type), image.convert("RGB"), transform, orientation)
    wire = quicklz.frame_payload(payload, int(sdk_type)) if framed else payload
    return payload, wire


def unframe(stream: bytes, sdk_type: int) -> bytes:
    """Reverse quicklz.frame_payload (stored blocks only, which is all it emits)."""
    plane_size = int.from_bytes(stream[:4], "little")
    planes = 2 if quicklz.uses_split_planes(int(sdk_type)) else 1
    pos, out = 4, bytearray()
    for _ in range(planes):
        got = 0
        while got < plane_size:
            flags, block_len, data_len = stream[pos], stream[pos + 1], stream[pos + 2]
            if flags != quicklz.STORED_BLOCK_FLAGS:
                raise ValueError(f"Unexpected QuickLZ block flags 0x{flags:02x} at offset {pos}")
            chunk = stream[pos + 3 : pos + block_len]
            if len(chunk) != data_len:
                raise ValueError(f"Truncated QuickLZ block at offset {pos}")
            out += chunk
            got += data_len
            pos += block_len
    if pos != len(stream):
        raise ValueError(f"{len(stream) - pos} trailing bytes after QuickLZ stream")
    return bytes(out)


def decode_hardware(sdk_type: int, payload: bytes) -> np.ndarray:
    """Packed planes -> (h, w) array of colour indices in hardware-buffer order."""
    code = int(sdk_type)
    hw_w, hw_h = render.expected_buffer_size(code)
    n = hw_w * hw_h
    data = np.frombuffer(payload, dtype=np.uint8)
    if code in render.BWRY_CODES:
        if len(data) != n // 4:
            raise ValueError(f"BWRY payload is {len(data)} bytes, expected {n // 4}")
        values = np.stack([(data >> 6) & 3, (data >> 4) & 3, (data >> 2) & 3, data & 3], axis=1)
        return values.reshape(-1)[:n].reshape(hw_h, hw_w).astype(np.uint8)

    plane = n // 8
    if len(data) != plane * 2:
        raise ValueError(f"Two-plane payload is {len(data)} bytes, expected {plane * 2}")
    first = np.unpackbits(data[:plane])[:n].astype(bool)
    red = np.unpackbits(data[plane:])[:n].astype(bool)
    white = ~first if code in _FLIPPED_BWR else first
    out = np.where(red, I_RED, np.where(white, I_WHITE, I_BLACK)).astype(np.uint8)
    out = out.reshape(hw_h, hw_w)
    if code in _FLIPPED_BWR:
        out = out[::-1, :]
    return out


@lru_cache(maxsize=32)
def _hardware_to_canvas(
    sdk_type: int, canvas_w: int, canvas_h: int, orientation: str, transform: str | None
) -> tuple[np.ndarray, np.ndarray, bool]:
    """(canvas index per hardware pixel, valid mask, is_exact_permutation)."""
    n = canvas_w * canvas_h
    idx = np.arange(n, dtype=np.uint32)
    probe = np.stack([(idx >> 16) & 255, (idx >> 8) & 255, idx & 255], axis=1).astype(np.uint8)
    probe_img = Image.fromarray(probe.reshape(canvas_h, canvas_w, 3), "RGB")
    hw = np.asarray(
        render.prepare_image_for_display(int(sdk_type), probe_img, transform, orientation).convert("RGB"),
        dtype=np.uint32,
    )
    hw_idx = (hw[..., 0] << 16) | (hw[..., 1] << 8) | hw[..., 2]
    valid = hw_idx < n  # padding is white (0xFFFFFF), always >= n
    exact = len(np.unique(hw_idx[valid])) == n and int(valid.sum()) == n
    return hw_idx, valid, exact


@dataclass
class Decoded:
    image: Image.Image  # canvas orientation, colours as the panel prints them
    hardware: Image.Image  # raw hardware buffer orientation
    warnings: list[str]


def decode(
    sdk_type: int,
    wire: bytes,
    canvas_size: tuple[int, int],
    orientation: str = "landscape",
    transform: str | None = None,
    framed: bool = False,
) -> Decoded:
    spec = panel_spec(sdk_type)
    payload = unframe(wire, sdk_type) if framed else wire
    hw = decode_hardware(sdk_type, payload)
    warnings: list[str] = []

    # What the physical pigments make of each value.
    if not spec.has_red and (hw == I_RED).any():
        hw = np.where(hw == I_RED, I_BLACK, hw)  # a B/W panel ignores the red plane
    if not spec.has_yellow and (hw == I_YELLOW).any():
        warnings.append(
            f"{spec.model} has no yellow pigment but the payload contains yellow pixels "
            "(four-colour packing on a three-colour model) - real result unknown."
        )

    hardware_img = Image.fromarray(_INDEX_COLORS[hw], "RGB")
    cw, ch = canvas_size
    hw_idx, valid, exact = _hardware_to_canvas(int(sdk_type), cw, ch, orientation, transform)
    if not exact:
        warnings.append(
            "prepare_image_for_display resized the canvas instead of only rotating/flipping it, "
            "so the canvas view is approximate. Check the canvas size for this SDK type."
        )
        return Decoded(hardware_img.resize(canvas_size), hardware_img, warnings)
    canvas = np.full(cw * ch, I_WHITE, dtype=np.uint8)
    canvas[hw_idx[valid]] = hw[valid]
    image = Image.fromarray(_INDEX_COLORS[canvas.reshape(ch, cw)], "RGB")
    return Decoded(image, hardware_img, warnings)


def roundtrip(
    sdk_type: int,
    image: Image.Image,
    orientation: str = "landscape",
    transform: str | None = None,
    framed: bool = False,
) -> tuple[Decoded, bytes, bytes]:
    payload, wire = encode(sdk_type, image, orientation, transform, framed)
    return decode(sdk_type, wire, image.size, orientation, transform, framed), payload, wire
