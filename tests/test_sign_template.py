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
        # Yellow where the hardware has it, black where it does not - never a red
        # plate, which would sit beside red type and compete with it.
        self.assertIn("this._displaySupportsYellow?.() ? YELLOW : BLACK", block)
        self.assertNotIn("RED", block)

    def test_the_name_takes_the_board_when_the_plate_is_off(self) -> None:
        block = self.svg[self.svg.index("_blockSign(row, box) {"):]
        block = block[: block.index("\n  },")]
        # Two different type sizes, not one size with a gap where the icon was.
        self.assertIn("inner.h * (withIcon ? 0.42 : 0.56)", block)
        self.assertIn("textWidth = Math.max(1, inner.w - plate);", block)


class SignTranslationTests(unittest.TestCase):
    """The panel is authored in Czech and translated at runtime."""

    def setUp(self) -> None:
        self.i18n = (PANEL / "panel-i18n.mixin.js").read_text(encoding="utf-8")

    def test_the_catalog_title_and_switch_are_translated(self) -> None:
        for czech in ("Cedule s ikonou", "Zobrazit ikonu", "Nákupní oddělení"):
            with self.subTest(czech=czech):
                self.assertIn(f'"{czech}":', self.i18n)


if __name__ == "__main__":
    unittest.main()
