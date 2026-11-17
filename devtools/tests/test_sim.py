"""Tests for the eInk simulator: run with  .venv/Scripts/python -m pytest devtools/tests"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

DEVTOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVTOOLS))

from eink_sim import dither, panel  # noqa: E402
from eink_sim.pipeline import render_frame, screen_sdk_type  # noqa: E402
from eink_sim.simulate import run, seconds  # noqa: E402
from eink_sim.state import StateSource, load_state_file  # noqa: E402

SPECS = panel.supported_types()


def _random_panel_image(spec, orientation, seed=0):
    w, h = spec.canvas_size(orientation)
    colours = [c for c in spec.colors if spec.four_colour_packing or c != panel.YELLOW]
    pal = np.array(colours, dtype=np.uint8)
    rng = np.random.default_rng(seed)
    return Image.fromarray(pal[rng.integers(0, len(pal), (h, w))], "RGB")


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: str(s.sdk_type))
@pytest.mark.parametrize("orientation", ["landscape", "portrait"])
@pytest.mark.parametrize("framed", [False, True])
def test_every_panel_round_trips_exactly(spec, orientation, framed):
    """The real packer's output decodes back to the same pixels, rotation and all."""
    image = _random_panel_image(spec, orientation)
    decoded, _payload, _wire = panel.roundtrip(spec.sdk_type, image, orientation, framed=framed)
    expected = np.asarray(image).copy()
    if not spec.has_red:  # a B/W panel prints the red plane as black
        expected[(expected == panel.RED).all(-1)] = 0
    assert decoded.warnings == []
    assert (np.asarray(decoded.image) == expected).all()


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: str(s.sdk_type))
def test_quantized_palette_survives_the_integrations_classifier(spec):
    """Pigment colours from dither.quantize are classified unchanged by bwr_masks/BWRY packing."""
    gradient = Image.linear_gradient("L").resize(spec.canvas_size()).convert("RGB")
    quantized = dither.quantize(gradient, spec.colors)
    decoded, _, _ = panel.roundtrip(spec.sdk_type, quantized)
    assert (np.asarray(decoded.image) == np.asarray(quantized)).all()


def test_grey_dithers_to_black_and_white_only_even_on_a_red_panel():
    grey = Image.new("RGB", (64, 64), (128, 128, 128))
    out = np.asarray(dither.quantize(grey, (panel.BLACK, panel.WHITE, panel.RED)))
    assert not (out == panel.RED).all(-1).any()
    assert 0.4 < (out == panel.WHITE).all(-1).mean() < 0.6


def test_exact_pigments_are_not_dithered():
    img = Image.new("RGB", (32, 32), panel.RED)
    out = np.asarray(dither.quantize(img, (panel.BLACK, panel.WHITE, panel.RED)))
    assert (out == panel.RED).all()


def test_entities_read_by_a_screen_are_tracked(tmp_path):
    screen = tmp_path / "s.py"
    screen.write_text(
        "def render(ctx):\n"
        "    img, d = ctx.canvas()\n"
        "    d.text((5, 5), str(ctx.num('sensor.a')), font=ctx.font(20), fill=ctx.BLACK)\n"
        "    ctx.attr('weather.home', 'temperature')\n"
        "    return img\n",
        encoding="utf-8",
    )
    frame = render_frame(screen, StateSource({"states": {"sensor.a": 1}}), 299)
    assert frame.ok, frame.error
    assert frame.accessed == {"sensor.a", "weather.home"}


def test_a_screen_may_return_svg(tmp_path):
    screen = tmp_path / "s.py"
    screen.write_text(
        "def render(ctx):\n"
        "    return f'<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{ctx.width}\" height=\"{ctx.height}\">'"
        " '<rect x=\"0\" y=\"0\" width=\"400\" height=\"480\" fill=\"#000\"/></svg>'\n",
        encoding="utf-8",
    )
    frame = render_frame(screen, StateSource(), 299)
    assert frame.ok, frame.error
    px = np.asarray(frame.panel_image)
    assert (px[:, :390] == 0).all() and (px[:, 410:] == 255).all()


def test_wrong_canvas_size_is_an_error_not_a_silent_resize(tmp_path):
    screen = tmp_path / "s.py"
    screen.write_text("from PIL import Image\ndef render(ctx):\n    return Image.new('RGB', (10, 10), 'white')\n")
    frame = render_frame(screen, StateSource(), 299)
    assert "panel canvas is 800x480" in frame.error


@pytest.mark.parametrize(
    "name,sdk",
    [("weather", 299), ("departures", 299), ("mini_weather", 46), ("mini_departures", 46), ("test_pattern", 46)],
)
def test_example_screens_render_on_the_panel_they_declare(name, sdk):
    path = DEVTOOLS / "screens" / f"{name}.py"
    assert screen_sdk_type(path) == sdk
    frame = render_frame(path, load_state_file(DEVTOOLS / "states" / "demo.yaml"), sdk)
    assert frame.ok, frame.error
    assert frame.warnings == []


def test_bwry_label_uses_all_four_pigments():
    """The 2.9" BWRY test pattern must reach the wire with yellow and red intact."""
    frame = render_frame(DEVTOOLS / "screens" / "test_pattern.py", StateSource(), 46)
    colours = {tuple(c) for c in np.asarray(frame.panel_image).reshape(-1, 3)}
    assert colours == {panel.BLACK, panel.WHITE, panel.RED, panel.YELLOW}
    assert len(frame.wire) == 296 * 128 // 4  # 2 bits per pixel


def test_bright_colours_do_not_dither_with_black():
    orange = Image.new("RGB", (64, 64), (232, 108, 6))
    out = np.asarray(dither.quantize(orange, (panel.BLACK, panel.WHITE, panel.RED, panel.YELLOW)))
    assert not (out == panel.BLACK).all(-1).any()


def test_weather_scenario_skips_redundant_writes(tmp_path):
    result = run(DEVTOOLS / "scenarios" / "weather_day.yaml", tmp_path)
    counts = result.counts()
    assert counts["sent"] == 5
    assert counts["unchanged"] == 3
    assert counts["deferred"] == 2
    assert counts["ignored"] == 1
    assert len(list(tmp_path.glob("*.png"))) == 5
    assert (tmp_path / "index.html").exists()


@pytest.mark.parametrize("text,expected", [("90", 90), ("10m", 600), ("1h30m", 5400), ("10m3s", 603), ("00:05:00", 300)])
def test_durations(text, expected):
    assert seconds(text) == expected
