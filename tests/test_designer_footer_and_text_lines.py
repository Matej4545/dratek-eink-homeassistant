"""The three designer gaps closed in 1.0.9-beta.3.

1. A footer cell can read a Home Assistant entity, which means the footer has
   to refresh like any other binding - the backend rebuilds the captured bar's
   own <text> runs instead of leaving the value frozen at capture time.
2. Palette tiles are drawn at the viewport the designer is working in and
   rasterised through the send path's own painter, so a sample is the shape and
   the ink the display will actually print rather than a stretched SVG.
3. A text element may hold more than one line: Enter in the content field is a
   real newline, and both renderers lay the run out line by line.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"
PANEL = COMPONENT / "frontend" / "panel"


def _load(name: str, package_name: str):
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{name}", COMPONENT / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render = _load("render", "dratek_designer_footer_test")


def _binding(**overrides):
    binding = {
        "id": "designer-footer-0",
        "type": "footer",
        "x": 0,
        "y": 100,
        "w": 296,
        "h": 28,
        "rotation": 0,
        "cells": [
            {"label": "TEPLOTA", "value": "12,4 °C", "entityId": "sensor.venku"},
            {"label": "VLHKOST", "value": "41 %"},
        ],
        "slots": [{
            "id": "footer-value-0",
            "index": 0,
            "cx": 74.0,
            "cy": 19.6,
            "size": 13.0,
            "color": "#ffffff",
            "bold": True,
            "maxWidth": 133.0,
            "prefix": "",
        }],
        "svg_template": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="296" height="28"'
            ' viewBox="0 0 296 28">'
            '<rect x="0" y="0" width="296" height="28" fill="#e31b1b"></rect>'
            '<text id="footer-value-0" x="74.00" y="19.60" font-size="13.00"'
            ' fill="#ffffff" text-anchor="middle">12,4 °C</text>'
            "</svg>"
        ),
    }
    binding.update(overrides)
    return binding


class FooterBindingRenderTests(unittest.TestCase):
    """The captured bar keeps its artwork; only the bound run is rewritten."""

    def setUp(self) -> None:
        self._original = render.svg_render.rasterize_svg
        self.documents: list[str] = []

        def _capture(document, width, height, **kwargs):
            self.documents.append(document)
            return self._original(document, width, height, **kwargs)

        render.svg_render.rasterize_svg = _capture
        self.addCleanup(setattr, render.svg_render, "rasterize_svg", self._original)

    def test_live_value_replaces_the_captured_one(self) -> None:
        render._render_bound_footer(_binding(), json.dumps(["18,9 °C", "41 %"]))
        self.assertTrue(self.documents, "the captured document was never rasterised")
        document = self.documents[0]
        self.assertIn("18,9 °C", document)
        self.assertNotIn("12,4 °C", document)
        # The bar, its labels and the untouched second cell survive verbatim -
        # that is the whole point of rebuilding the capture rather than
        # repainting a red rectangle and guessing the rest.
        self.assertIn('fill="#e31b1b"', document)

    def test_a_cell_without_an_entity_keeps_its_designed_value(self) -> None:
        # Only cells that name an entity get a slot, so a shorter value list
        # (or none at all) must fall back to what the designer typed.
        render._render_bound_footer(_binding(), "not json at all")
        self.assertIn("12,4 °C", self.documents[0])

    def test_compact_floor_rides_along_with_the_slot(self) -> None:
        """The compact footer fits down to 9px; svg_text.py's own floor is 10.

        Without minSize on the slot the backend re-fits the same string against
        10 and picks a different font size than the panel drew - the one thing
        the svg_text port exists to prevent.
        """
        binding = _binding()
        binding["slots"][0]["minSize"] = 9
        binding["slots"][0]["maxWidth"] = 24.0
        render._render_bound_footer(binding, json.dumps(["18,9 °C"]))
        self.assertIn('font-size="9.00"', self.documents[0])

    def test_rotation_is_applied_to_the_finished_bar(self) -> None:
        upright = render._render_bound_footer(_binding(), json.dumps(["18,9 °C"]))
        turned = render._render_bound_footer(
            _binding(rotation=90), json.dumps(["18,9 °C"])
        )
        self.assertEqual(upright.size, (296, 28))
        self.assertEqual(turned.size, (28, 296))


class FooterBindingFallbackTests(unittest.TestCase):
    """Installations without an SVG runtime still get a readable bar."""

    def setUp(self) -> None:
        original = render.svg_render.rasterize_svg
        render.svg_render.rasterize_svg = lambda *_args, **_kwargs: None
        self.addCleanup(setattr, render.svg_render, "rasterize_svg", original)

    def test_a_run_centred_at_the_edge_is_not_dropped(self) -> None:
        # alpha_composite refuses a box that leaves the image, and a footer cell
        # centred near the left edge produces exactly that, so the run is
        # clamped into the bar instead of taking the whole refresh with it.
        binding = _binding()
        binding["slots"][0]["cx"] = 2.0
        binding["slots"][0]["cy"] = 1.0
        image = render._render_bound_footer(binding, json.dumps(["18,9 °C"]))
        self.assertEqual(image.size, (296, 28))

    def test_a_run_wider_than_the_bar_is_clamped(self) -> None:
        binding = _binding()
        binding["slots"][0]["maxWidth"] = 4000.0
        image = render._render_bound_footer(binding, json.dumps(["18,9 °C"]))
        self.assertEqual(image.size, (296, 28))


class FooterAutomationSourceTests(unittest.TestCase):
    """automation.py has to see the cells' entities, not the binding's own."""

    def setUp(self) -> None:
        self.source = (COMPONENT / "automation.py").read_text(encoding="utf-8")

    def test_binding_sources_reads_every_cell(self) -> None:
        self.assertIn('if binding.get("type") == "footer":', self.source)
        self.assertIn('for cell in binding.get("cells", [])', self.source)

    def test_the_footer_value_travels_as_a_list(self) -> None:
        # One binding, several cells: the values have to arrive as an ordered
        # list so each slot can pick its own by index.
        self.assertIn("return json.dumps(values, ensure_ascii=False)", self.source)

    def test_render_dispatches_the_new_type(self) -> None:
        source = (COMPONENT / "render.py").read_text(encoding="utf-8")
        self.assertIn('if binding.get("type") == "footer":', source)
        self.assertIn("return _render_bound_footer(binding, value)", source)


class FooterEntityPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = (PANEL / "panel-template-blocks.mixin.js").read_text(encoding="utf-8")
        self.svg = (PANEL / "panel-template-svg.mixin.js").read_text(encoding="utf-8")
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")

    def test_a_footer_cell_offers_an_entity_and_an_attribute(self) -> None:
        self.assertIn('{ key: "entityId", kind: "entity", label: "Entita Home Assistantu" }', self.blocks)
        self.assertIn('{ key: "entityAttribute", kind: "text", label: "Atribut (volitelné)" }', self.blocks)

    def test_the_picker_uses_the_panel_s_own_entity_selector(self) -> None:
        # Plain {entity:{}} would offer the displays' own diagnostic entities
        # back as design inputs, which _variableEntitySelector exists to hide.
        self.assertIn("picker.selector = this._variableEntitySelector();", self.blocks)
        self.assertNotIn("picker.selector = { entity: {} };", self.blocks)

    def test_a_bound_cell_shows_its_live_value(self) -> None:
        self.assertIn("if (cell.entityId) cell.value = this._templateElementEntityText(cell) ?? cell.value;", self.blocks)

    def test_bound_runs_are_addressable_in_the_captured_svg(self) -> None:
        self.assertIn("_layoutTemplateFooter(footerRow, width, height, footerHeight, collector, valueSlots = null)", self.svg)
        self.assertIn("const id = `footer-value-${index}`;", self.svg)
        # An empty fallback still needs an element to replace later.
        self.assertIn("this._svgText(\" \", x, y, size, options)", self.svg)

    def test_the_binding_is_measured_against_the_send_size(self) -> None:
        # request.width/height is the SDK's stock size; a display with a drafted
        # resolution renders at the draft, like every other binding here.
        self.assertIn("async _templateFooterAutomationBindings(request, width, height)", self.devices)
        self.assertIn("this._collectTemplateOverlayBoxes({ ...request, width, height })", self.devices)
        self.assertIn("this._templateFooterAutomationBindings(request, width, height)", self.devices)

    def test_a_footer_entity_wakes_the_live_preview(self) -> None:
        self.assertIn("for (const cell of item.block?.footer || []) if (cell.entityId) watched.add(cell.entityId);", self.devices)


class PalettePreviewTests(unittest.TestCase):
    """A sample has to be the shape and the ink of the real thing."""

    def setUp(self) -> None:
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")
        self.blocks = (PANEL / "panel-template-blocks.mixin.js").read_text(encoding="utf-8")
        self.components = (PANEL / "panel-template-components.mixin.js").read_text(encoding="utf-8")
        self.styles = (PANEL / "panel-render-ui.mixin.js").read_text(encoding="utf-8")

    def test_no_preview_is_stretched_to_fit_its_tile(self) -> None:
        # preserveAspectRatio="none" is what squashed a square block into a
        # 2.3:1 tile and stretched a wide one - the exact complaint.
        self.assertNotIn('preserveAspectRatio="none"', self.blocks)
        self.assertNotIn('preserveAspectRatio="none"', self.components)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', self.blocks)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', self.components)

    def test_tiles_are_drawn_at_the_designer_s_own_viewport(self) -> None:
        self.assertIn("_templateBlockPaletteCanvas()", self.blocks)
        self.assertIn("this._renderTemplateComponentSvg(item, canvas.width, canvas.height)", self.devices)
        self.assertNotIn("this._renderTemplateComponentSvg(item, 296, 128)", self.devices)

    def test_the_tile_is_painted_by_the_send_path_and_quantised(self) -> None:
        self.assertIn("async _templatePaletteBitmap(source)", self.devices)
        self.assertIn("this._paintTemplateOverlays(context, [overlay], width, height)", self.devices)
        self.assertIn("this._quantizeEinkPixel(", self.devices)
        # Painted at display resolution and cropped, never resampled: a
        # one-pixel halftone screen does not survive a rescale.
        self.assertIn("context.getImageData(0, 0, w, h)", self.devices)

    def test_every_tile_declares_what_to_paint(self) -> None:
        self.assertIn("data-template-palette-bitmap", self.blocks)
        self.assertIn("data-template-palette-bitmap", self.devices)
        self.assertIn("_paintTemplatePalettePreviews()", self.devices)
        self.assertIn("[data-template-palette-bitmap]>img{", self.styles)

    def test_the_bitmap_cache_is_keyed_by_viewport_and_palette(self) -> None:
        # A BWR display and a BWRY one quantise the same sample differently, and
        # so does a 296x128 panel against an 800x480 one.
        self.assertIn("`${canvas.width}x${canvas.height}:${this._displayPaletteKey()}:${raw}`", self.devices)


class MultiLineTextTests(unittest.TestCase):
    """Enter in a text element is a second line, everywhere."""

    def setUp(self) -> None:
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")
        self.styles = (PANEL / "panel-render-ui.mixin.js").read_text(encoding="utf-8")

    def test_the_content_field_accepts_a_newline(self) -> None:
        self.assertIn('<textarea rows="2" data-template-element-prop="text"', self.devices)

    def test_only_the_free_text_element_gets_it(self) -> None:
        # A button caption is one centred run and a signal label is composed
        # into "Stav  ON" before it is drawn: a newline in either is dropped
        # further down the path, so offering one would be a lie.
        self.assertIn('${item.type === "text"', self.devices)
        self.assertIn('data-template-element-multiline', self.devices)

    def test_newlines_are_normalised_once(self) -> None:
        self.assertIn("_templateTextLines(value) {", self.devices)
        self.assertIn('return String(value ?? "").replace(/\\r\\n?/g, "\\n").split("\\n");', self.devices)
        self.assertIn('{ text: this._templateTextLines(storedText).join("\\n") }', self.devices)

    def test_the_painter_draws_line_by_line(self) -> None:
        self.assertIn("const lines = this._templateTextLines(item.text);", self.devices)
        # 1.12 is the preview CSS's own line-height; anything else and the two
        # pictures stop sitting on top of each other.
        self.assertIn("const lineHeight = size * 1.12;", self.devices)
        self.assertIn("const firstY = textY - (lines.length - 1) * lineHeight / 2;", self.devices)

    def test_the_preview_keeps_the_break(self) -> None:
        import re

        rules = re.findall(r"\.template-overlay-text\{[^}]*\}", self.styles)
        self.assertTrue(rules, "the overlay text rule is gone")
        # nowrap (and plain `normal`, which collapses a newline to a space) is
        # what silently swallowed the second line in the catalog thumbnails and
        # on the editor stage.
        for rule in rules:
            with self.subTest(rule=rule[:60]):
                self.assertNotIn("white-space:nowrap", rule)
                self.assertNotIn("white-space:normal", rule)
        self.assertIn("white-space:pre-wrap", "".join(rules))
        # …and the run inside it, which carries its own white-space.
        self.assertIn(
            "line-height:1.12;text-align:var(--element-text-align);text-overflow:ellipsis;white-space:pre-wrap}",
            self.styles,
        )

    def test_the_backend_already_splits_on_newlines(self) -> None:
        source = (COMPONENT / "render.py").read_text(encoding="utf-8")
        self.assertIn('lines = str(value).split("\\n")', source)


if __name__ == "__main__":
    unittest.main()
