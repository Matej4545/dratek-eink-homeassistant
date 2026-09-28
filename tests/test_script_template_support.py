"""Regression checks for Script Template UI and runtime wiring."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "dratek_eink" / "frontend" / "panel"


class ScriptTemplateSupportTests(unittest.TestCase):
    def test_panel_registers_script_mixin(self) -> None:
        source = (ROOT / "custom_components" / "dratek_eink" / "frontend" / "dratek-eink-panel.js").read_text(encoding="utf-8")
        self.assertIn('import { templateScriptMixin } from "./panel/panel-template-script.mixin.js', source)
        self.assertIn("templateScriptMixin,", source)

    def test_template_cards_offer_script_actions(self) -> None:
        source = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")
        self.assertIn('data-script-template-create', source)
        self.assertIn('data-display-template-edit-choice="script"', source)
        self.assertIn('template.template_type === "script"', source)
        self.assertIn('_renderScriptTemplateEditorDialog?.() || ""', source)

    def test_template_svg_uses_script_rows(self) -> None:
        source = (PANEL / "panel-template-svg.mixin.js").read_text(encoding="utf-8")
        self.assertIn("this._isScriptUserTemplate?.(template)", source)
        self.assertIn("this._scriptTemplateRows?.(baseTemplate, width, height)", source)

    def test_project_store_normalizes_script_templates(self) -> None:
        source = (ROOT / "custom_components" / "dratek_eink" / "project_storage.py").read_text(encoding="utf-8")
        self.assertIn('if template_type == "script":', source)
        self.assertIn('template["script_source"]', source)
        self.assertIn('template["data_sources"]', source)


if __name__ == "__main__":
    unittest.main()
