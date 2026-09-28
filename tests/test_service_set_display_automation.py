"""Wiring checks for the set_display_automation Home Assistant service."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"


class SetDisplayAutomationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        cls.services = (COMPONENT / "services.yaml").read_text(encoding="utf-8")

    def test_service_is_registered(self) -> None:
        self.assertIn('"set_display_automation"', self.init)
        self.assertIn("handle_set_automation", self.init)
        self.assertIn("schema=SET_AUTOMATION_SCHEMA", self.init)

    def test_schema_accepts_expected_fields(self) -> None:
        for field in (
            'vol.Required("address")',
            'vol.Optional("enabled")',
            'vol.Optional("refresh_interval_seconds")',
            'vol.Optional("refresh_trigger_mode")',
            'vol.Optional("always_send")',
            'vol.Optional("request_refresh", default=False)',
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.init)

    def test_handler_updates_manager_settings(self) -> None:
        for call in (
            "await manager.async_set_enabled(",
            "await manager.async_set_refresh_interval(",
            "await manager.async_set_refresh_trigger_mode(",
            "await manager.async_set_always_send(",
            "await manager.async_request_refresh(",
        ):
            with self.subTest(call=call):
                self.assertIn(call, self.init)

    def test_services_yaml_documents_new_service(self) -> None:
        self.assertIn("set_display_automation:", self.services)
        for field in (
            "enabled:",
            "refresh_interval_seconds:",
            "refresh_trigger_mode:",
            "always_send:",
            "request_refresh:",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.services)


if __name__ == "__main__":
    unittest.main()
