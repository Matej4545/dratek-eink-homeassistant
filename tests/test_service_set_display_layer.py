"""Wiring checks for named display automation layers."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"


class SetDisplayLayerServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        cls.services = (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        cls.automation = (COMPONENT / "automation.py").read_text(encoding="utf-8")

    def test_layer_service_is_registered(self) -> None:
        self.assertIn('"set_display_layer"', self.init)
        self.assertIn("handle_set_display_layer", self.init)
        self.assertIn("schema=DISPLAY_LAYER_SCHEMA", self.init)

    def test_layer_schema_accepts_expected_fields(self) -> None:
        for field in (
            'vol.Required("address")',
            'vol.Required("action")',
            'vol.Required("layer")',
            'vol.Optional("request_refresh", default=False)',
            '["save_current", "activate", "delete"]',
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.init)

    def test_layer_handler_calls_manager_methods(self) -> None:
        for call in (
            "await manager.async_save_layer(",
            "await manager.async_activate_layer(",
            "await manager.async_delete_layer(",
            "await manager.async_request_refresh(",
        ):
            with self.subTest(call=call):
                self.assertIn(call, self.init)

    def test_automation_manager_persists_and_exposes_layers(self) -> None:
        for snippet in (
            '"layers": self._layers',
            "self._layers = normalized_layers",
            "async def async_save_layer(",
            "async def async_activate_layer(",
            "async def async_delete_layer(",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, self.automation)

    def test_services_yaml_documents_layer_service(self) -> None:
        self.assertIn("set_display_layer:", self.services)
        for field in ("action:", "layer:", "request_refresh:"):
            with self.subTest(field=field):
                self.assertIn(field, self.services)


if __name__ == "__main__":
    unittest.main()
