"""The "Cedule" sign template: a glyph on a plate, a name beside it, one switch.

It is the first template in the catalog and the only one that needs nothing set
up, so the two things that can silently break it are pinned here: the switch has
to start *on* (a board that arrives blank until its one setting is found reads as
broken, and every other option in this panel defaults to off), and the glyph has
to be fetched even though its name is typed by the user rather than written into
a template file.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "dratek_eink" / "frontend" / "panel"
TEMPLATES = PANEL / "templates"


class SignTemplateCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sign = (TEMPLATES / "sign.js").read_text(encoding="utf-8")
        self.index = (TEMPLATES / "index.js").read_text(encoding="utf-8")

    def test_it_is_the_first_template_in_the_catalog(self) -> None:
        listing = self.index[self.index.index("export const DISPLAY_TEMPLATES = ["):]
        entries = re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*),", listing, re.M)
        self.assertEqual(entries[0], "sign", f"sign must lead the catalog, got {entries[:3]}")

    def test_it_is_imported_and_registered_once(self) -> None:
        self.assertIn('import { template as sign } from "./sign.js', self.index)
        self.assertEqual(self.index.count("\n  sign,"), 1)

    def test_it_needs_no_integration(self) -> None:
        # The whole point: a brand-new display can be sent this within a minute.
        self.assertIn("manualValues: true", self.sign)
        self.assertIn("integrations: []", self.sign)

    def test_the_catalog_number_is_not_taken(self) -> None:
        numbers = []
        for path in TEMPLATES.glob("*.js"):
            if path.name == "index.js":
                continue
            found = re.search(r'number:\s*"(\d+)"', path.read_text(encoding="utf-8"))
            if found:
                numbers.append((path.name, found.group(1)))
        taken = [name for name, number in numbers if number == "31" and name != "sign.js"]
        self.assertEqual(taken, [], f"catalog number 31 is already used by {taken}")

    def test_the_icon_switch_starts_on(self) -> None:
        # Fourth element of the option tuple. Without it the sign would arrive
        # with no picture until the user went looking for the setting.
        option = re.search(r"options:\s*\[\[(.*?)\]\]", self.sign, re.S)
        self.assertIsNotNone(option, "the sign template declares no options")
        self.assertIn("true,", option.group(1))
        self.assertIn('"icon"', option.group(1))

    def test_the_switch_drives_the_row(self) -> None:
        self.assertIn('showIcon: option("icon")', self.sign)

    def test_the_default_glyph_is_one_the_offline_harness_has(self) -> None:
        # Any MDI name works in Home Assistant, but the default must also draw in
        # the test harness, whose icon set is the curated one built from these
        # very files (tools/build-test-mdi-paths.mjs).
        default = re.search(r'icon:\s*v\(0,\s*"([a-z0-9-]+)"\)', self.sign)
        self.assertIsNotNone(default)
        paths = (ROOT / "tests" / "vendor" / "mdi" / "paths.js").read_text(encoding="utf-8")
        self.assertIn(f'"{default.group(1)}"', paths)


class SignOptionDefaultTests(unittest.TestCase):
    """A declared default has to reach both the reading and the checkbox."""

    def setUp(self) -> None:
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")

    def test_the_state_falls_back_to_the_declared_default(self) -> None:
        self.assertIn("_templateOptionDefault(template, option) {", self.devices)
        self.assertIn("if (!entity) return this._templateOptionDefault(template, option);", self.devices)
        self.assertIn("return spec?.[3] === true;", self.devices)

    def test_the_checkbox_shows_that_same_default(self) -> None:
        # Reading it straight out of _displayTemplateOptions is what made the
        # switch render unticked while the drawing behaved as if it were on.
        self.assertIn(
            "const active = stored === undefined ? this._templateOptionDefault(template, option) : !!stored;",
            self.devices,
        )

    def test_an_option_without_a_default_is_unchanged(self) -> None:
        # price:sale must keep starting off - it means "a promotion is running".
        price = (TEMPLATES / "price.js").read_text(encoding="utf-8")
        option = re.search(r'options:\s*\[\[(.*?)\]\]', price, re.S)
        self.assertIsNotNone(option)
        self.assertNotIn("true", option.group(1))


class SignBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.svg = (PANEL / "panel-template-svg.mixin.js").read_text(encoding="utf-8")

    def test_the_row_is_dispatched(self) -> None:
        self.assertIn("if (row.sign) return this._blockSign(row, box);", self.svg)
        self.assertIn("_blockSign(row, box) {", self.svg)

    def test_the_glyph_is_fetched_even_though_the_user_names_it(self) -> None:
        # Every other row names its icon in a template file, so the warm-up sees
        # it. This one does not exist until someone types it into the settings.
        self.assertIn(
            "if (row.sign?.icon && !WEATHER_ICON_TO_CONDITION.has(row.sign.icon)) names.add(row.sign.icon);",
            self.svg,
        )

    def test_the_plate_follows_the_panel_s_own_inks(self) -> None:
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        # The plate ink is its own function: _templateInk would turn a yellow
        # plate red on a three-colour panel, which is right for a thin graphic
        # detail and wrong for an area the size of half the sign.
        self.assertIn("this._signPlateInk(sign.plate)", block)
        ink = self.svg[self.svg.index("_signPlateInk(plate) {"):]
        ink = ink[: ink.index("\n  },")]
        self.assertIn("this._displaySupportsYellow?.() ? YELLOW : BLACK", ink)
        # "white" is bare paper, not a fifth pigment.
        self.assertIn('if (choice === "white" || choice === "none") return "";', ink)

    def test_the_name_takes_the_board_when_the_plate_is_off(self) -> None:
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        # Two different type sizes, not one size with a gap where the icon was.
        self.assertIn("box.h * (withIcon ? 0.42 : 0.56)", block)
        self.assertIn("textWidth = Math.max(1, w - plate);", block)


class SignTranslationTests(unittest.TestCase):
    """The panel is authored in Czech and translated at runtime."""

    def setUp(self) -> None:
        self.i18n = (PANEL / "panel-i18n.mixin.js").read_text(encoding="utf-8")

    def test_the_catalog_title_and_switch_are_translated(self) -> None:
        for czech in ("Cedule s ikonou", "Zobrazit ikonu", "Nákupní oddělení"):
            with self.subTest(czech=czech):
                self.assertIn(f'"{czech}":', self.i18n)


class SignLayoutTests(unittest.TestCase):
    """Edge to edge, wrapped by word, in whichever colour the user picked."""

    def setUp(self) -> None:
        self.svg = (PANEL / "panel-template-svg.mixin.js").read_text(encoding="utf-8")
        self.sign = (TEMPLATES / "sign.js").read_text(encoding="utf-8")

    def test_the_board_owns_the_whole_panel(self) -> None:
        # The stacked layout insets every row by ~3.5% of the panel. On a sign
        # that is a white margin around a coloured plate, which reads as a badly
        # cut sticker; pixelPerfect is the existing escape hatch for a block
        # that owns its own page.
        self.assertIn("rows[0]?.sign", self.svg)
        self.assertIn("pixelPerfect: true", self.sign)
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        # …and it bleeds like a band, so a slot layout cannot re-inset it.
        self.assertIn("const x = box.fullX === undefined ? box.x : box.fullX;", block)
        self.assertIn("const w = box.fullW === undefined ? box.w : box.fullW;", block)

    def test_there_is_no_frame(self) -> None:
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        self.assertNotIn("stroke=", block)

    def test_the_name_wraps_between_words(self) -> None:
        self.assertIn("_signTextLines(text, maxWidth, maxHeight, ceiling, bold) {", self.svg)
        wrap = self.svg[self.svg.index("_signTextLines(text, maxWidth, maxHeight, ceiling, bold) {"):]
        wrap = wrap[: wrap.index("\n  },")]
        # Split on whitespace, then fill greedily - never mid-word, which is
        # what _svgText's own ellipsis clip does.
        self.assertIn(".split(/\\s+/)", wrap)
        self.assertIn("this._svgTextWidth(candidate, size, bold) > maxWidth", wrap)
        # Shrinking is the fallback, not the first move.
        self.assertIn("size -= 1", wrap)

    def test_the_plate_colour_is_a_variable(self) -> None:
        self.assertIn('["palette", "Barva pozadí", "plate"]', self.sign)
        self.assertIn('plate: v(2, "yellow")', self.sign)

    def test_the_glyph_contrasts_with_whatever_plate_was_picked(self) -> None:
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        # White on black or red, black on yellow or on bare paper. Anything else
        # is a glyph the panel prints as a smudge.
        self.assertIn('const glyphInk = plateInk && plateInk !== YELLOW ? "#ffffff" : BLACK;', block)


class SignSettingsUiTests(unittest.TestCase):
    """Two fields and a swatch row, not a wall of entity pickers."""

    def setUp(self) -> None:
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")
        self.inspector = (PANEL / "panel-inspector.mixin.js").read_text(encoding="utf-8")
        self.sign = (TEMPLATES / "sign.js").read_text(encoding="utf-8")

    def test_the_icon_slot_offers_the_designer_s_own_gallery(self) -> None:
        # One list for both, so a sign built in the settings dialog and one built
        # by dropping an icon element in the designer can be made to match.
        self.assertIn("const TEMPLATE_ICON_CHOICES = [", self.devices)
        self.assertIn("const iconNames = TEMPLATE_ICON_CHOICES;", self.devices)
        self.assertIn("_renderTemplateIconChoices(bindingKey, current) {", self.devices)
        self.assertIn('data-template-icon-choice=', self.devices)

    def test_a_gallery_pick_is_stored_like_a_typed_one(self) -> None:
        self.assertIn("this._displayTemplateBindings[bindingKey] = `literal:${icon}`;", self.inspector)

    def test_the_colour_slot_offers_every_ink_and_nothing_else(self) -> None:
        self.assertIn("const TEMPLATE_PLATE_CHOICES = [", self.devices)
        for value in ("yellow", "red", "black", "white"):
            with self.subTest(ink=value):
                self.assertIn(f'["{value}"', self.devices)

    def test_a_template_that_binds_nothing_hides_the_entity_pickers(self) -> None:
        self.assertIn("manualOnly: true", self.sign)
        self.assertIn("const manualOnly = isIcon || isPlate || !!template?.manualOnly;", self.devices)
        self.assertIn('${manualOnly ? "" : `<ha-selector data-template-entity-picker=', self.devices)


class StaticDesignAutomationTests(unittest.TestCase):
    """A design with nothing bound must not leave the old automation running."""

    def setUp(self) -> None:
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")

    def test_sending_a_static_design_clears_the_automation(self) -> None:
        # The stale automation still holds the previous design's artwork, so the
        # next state change repaints the display with it - a sign sent over a
        # weather panel turned back into the weather panel.
        self.assertIn("if (!payload.automation) {", self.devices)
        self.assertIn(
            'await this._hass.callWS({ type: "dratek_eink/automations/delete", address: device.address });',
            self.devices,
        )


class SignPrereleaseGateTests(unittest.TestCase):
    """The sign is a shop-floor tool, so only a pre-release offers its tile."""

    def setUp(self) -> None:
        self.index = (TEMPLATES / "index.js").read_text(encoding="utf-8")

    def test_it_rides_the_same_switch_as_the_logo(self) -> None:
        self.assertIn('PRERELEASE_ONLY_TEMPLATE_IDS = new Set(["dratek_logo", "sign"])', self.index)
        catalog = self.index[self.index.index("export const DISPLAY_TEMPLATE_CATALOG"):]
        catalog = catalog[: catalog.index("export const DISPLAY_TEMPLATES_BY_ID")]
        self.assertIn("BRAND_LOGO_TEMPLATE_VISIBLE", catalog)
        self.assertIn("PRERELEASE_ONLY_TEMPLATE_IDS", catalog)

    def test_hiding_the_tile_does_not_unship_the_design(self) -> None:
        # A display already carrying the sign resolves its drawing through
        # DISPLAY_TEMPLATES / DISPLAY_TEMPLATES_BY_ID, so the gate must never
        # reach either - same rule the logo tile has, and the same disaster if
        # it is broken.
        listing = self.index[self.index.index("export const DISPLAY_TEMPLATES = ["):]
        listing = listing[: listing.index("];")]
        self.assertIn("sign,", listing)
        self.assertNotIn("PRERELEASE_ONLY_TEMPLATE_IDS", listing)
        by_id = self.index[self.index.index("export const DISPLAY_TEMPLATES_BY_ID"):]
        self.assertNotIn("PRERELEASE_ONLY_TEMPLATE_IDS", by_id)
        self.assertTrue((TEMPLATES / "sign.js").exists())


if __name__ == "__main__":
    unittest.main()
