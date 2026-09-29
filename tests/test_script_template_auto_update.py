"""Automatic updates for script templates, and keeping a chosen interval.

Two regressions live here. A display running a user script template produced
no automation at all (the capture only looked at v() variables, which a script
template does not have), so there was nowhere to switch automatic refresh on.
And a refresh interval a user had picked - 30 minutes, say - fell back to the
600 s default whenever a draft was autosaved or a design resent without one.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"
PANEL = COMPONENT / "frontend" / "panel"
SCRIPT_MIXIN = PANEL / "panel-template-script.mixin.js"


def _run_node(script: str) -> str:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("Node.js is not available")
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


WORKER_STUB = """
  globalThis.Blob = class {
    constructor(parts) { this.code = parts.join(""); }
  };
  globalThis.URL = { createObjectURL(blob) { return blob.code; } };
  globalThis.Worker = class {
    constructor(code) {
      this.onmessage = null;
      this.onerror = null;
      const worker = this;
      const scope = {
        Object, String, Number, Math, Date, JSON, Array, Map, Set, RegExp,
        Error, SyntaxError,
        onmessage: null,
        postMessage(payload) { worker.onmessage?.({ data: payload }); },
      };
      scope.self = scope;
      vm.runInNewContext(code, scope);
      this.scope = scope;
    }
    postMessage(payload) { this.scope.onmessage?.({ data: payload }); }
    terminate() {}
  };
"""


class ScriptTemplateProbeTests(unittest.TestCase):
    """The probe that turns a data source into an automation binding."""

    def _panel(self, body: str) -> str:
        return f"""
          import vm from "node:vm";
          import {{ templateScriptMixin }} from {json.dumps(SCRIPT_MIXIN.as_uri())};
          {WORKER_STUB}
          const panel = {{
            ...templateScriptMixin,
            _hass: {{ states: {{ "sensor.temperature": {{ state: "21.5", attributes: {{}} }} }} }},
            _render() {{}},
            _paint() {{}},
          }};
          const template = {{
            id: "user-template-script",
            user_created: true,
            template_type: "script",
            updated_at: 10,
            script_source: "return [{{ text: `Teplota ${{data.inside}} °C` }}];",
            data_sources: [{{ id: "inside", type: "entity", entity_id: "sensor.temperature" }}],
          }};
          {body}
        """

    def test_probe_value_replaces_only_the_probed_data_source(self) -> None:
        output = _run_node(self._panel("""
          const live = await panel._resolveScriptTemplateDataSources(template);
          panel._scriptTemplateDataOverrides = { "user-template-script:inside": "QZS0X" };
          const probed = await panel._resolveScriptTemplateDataSources(template);
          console.log(JSON.stringify({ live, probed }));
        """))
        payload = json.loads(output)
        self.assertEqual({"inside": "21.5"}, payload["live"])
        self.assertEqual({"inside": "QZS0X"}, payload["probed"])

    def test_probe_render_is_cached_separately_from_the_real_one(self) -> None:
        output = _run_node(self._panel("""
          const real = await panel._resolveScriptTemplateRows(template, 296, 128);
          panel._scriptTemplateDataOverrides = { "user-template-script:inside": "QZS0X" };
          const probed = await panel._resolveScriptTemplateRows(template, 296, 128);
          delete panel._scriptTemplateDataOverrides;
          const again = await panel._resolveScriptTemplateRows(template, 296, 128);
          console.log(JSON.stringify({
            real: real[0].text,
            probed: probed[0].text,
            again: again[0].text,
            keys: panel._scriptTemplateRowsCache.size,
          }));
        """))
        payload = json.loads(output)
        self.assertEqual("Teplota 21.5 °C", payload["real"])
        # The probe must reach the rendered run, or the capture has nothing to
        # diff against and the data source never becomes a binding.
        self.assertEqual("Teplota QZS0X °C", payload["probed"])
        self.assertEqual("Teplota 21.5 °C", payload["again"])
        self.assertEqual(2, payload["keys"])

    def test_a_list_valued_source_is_never_probed_into_a_text_binding(self) -> None:
        # An hourly forecast kept in an attribute is drawn by the script as a
        # weatherChart; binding it as text would print the raw list over
        # whichever label changed.
        output = _run_node(self._panel("""
          panel._hass.states["sensor.hourly"] = { state: "24", attributes: { forecast: [{ temperature: 14 }] } };
          template.data_sources.push({ id: "hourly", type: "entity", entity_id: "sensor.hourly", entity_attribute: "forecast" });
          const empty = { querySelector: () => null, querySelectorAll: () => [] };
          globalThis.DOMParser = class { parseFromString() { return empty; } };
          const probed = [];
          panel._warmScriptTemplateRows = async () => {};
          panel._alignTemplateTextRuns = () => [];
          panel._buildDisplayTemplateSvg = async () => {
            probed.push(Object.keys(panel._scriptTemplateDataOverrides));
            return "<svg></svg>";
          };
          await panel._scriptTemplateAutomationBindings(template, 0, { templates: [template] }, empty, 296, 128);
          console.log(JSON.stringify(probed));
        """))
        self.assertEqual([["user-template-script:inside"]], json.loads(output))


class ScriptTemplateAutomationWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = SCRIPT_MIXIN.read_text(encoding="utf-8")
        self.devices = (PANEL / "panel-devices.mixin.js").read_text(encoding="utf-8")

    def test_script_templates_produce_entity_text_bindings(self) -> None:
        self.assertIn("async _scriptTemplateAutomationBindings(", self.script)
        self.assertIn("this._templateAutomationTextBinding(", self.script)
        self.assertIn('String(source?.type || "entity") === "entity"', self.script)

    def test_binding_capture_asks_a_script_template_for_its_own_sources(self) -> None:
        self.assertIn(
            "bindings.push(...await this._scriptTemplateAutomationBindings(",
            self.devices,
        )
        # Without warming the rows first the captured document is the script's
        # "loading" placeholder rather than the design being sent.
        self.assertIn("await this._warmScriptTemplateRows?.(", self.devices)

    def test_script_rows_are_resolved_before_the_document_is_captured(self) -> None:
        capture = self.devices[self.devices.index("async _preparedTemplateEntityBindings("):]
        capture = capture[:capture.index("const currentSvg = await this._buildDisplayTemplateSvg(")]
        self.assertIn("_warmScriptTemplateRows", capture)

    def test_the_cadence_is_configurable_before_the_first_send(self) -> None:
        # A Script Template design has no automation until it is sent once, so
        # the empty state of the refresh row has to offer the interval and the
        # trigger mode itself - otherwise the first send always uses 600 s.
        empty = self.devices[self.devices.index("_renderDisplayTemplateRefreshSettings("):]
        empty = empty[:empty.index("const enabled = automation.enabled !== false;")]
        self.assertIn("this._displayRefreshIntervalSelect(address)", empty)
        self.assertIn("this._displayRefreshTriggerSelect(address)", empty)

        automations = (PANEL / "panel-automations.mixin.js").read_text(encoding="utf-8")
        # They must write into the draft, which is what _projectPayload sends
        # with the design - hence the data-device-* attributes whose handlers
        # already live in panel-inspector.mixin.js.
        self.assertIn('data-device-refresh-interval="${this._escape(address)}"', automations)
        self.assertIn('data-device-refresh-trigger-mode="${this._escape(address)}"', automations)


class RefreshIntervalPreservationTests(unittest.TestCase):
    """A chosen interval survives drafts, resends and payloads that omit it."""

    def setUp(self) -> None:
        from test_automation_bindings import automation

        self.automation = automation

    def _manager(self):
        manager = self.automation.EntityAutoUpdateManager.__new__(
            self.automation.EntityAutoUpdateManager
        )
        manager._initialized = True
        manager._configs = {}
        manager._last_refresh_at = {}
        manager._last_refresh_wall_time = {}
        manager._next_scheduled_wall_time = {}
        manager._pending_refreshes = set()
        manager._timers = {}
        manager._refresh_tasks = {}
        manager._retained_refresh_settings = {}

        async def _save():
            return None

        manager._async_save_store = _save
        manager._refresh_listener = lambda: None
        manager._sync_interval_timer = lambda _address: None
        return manager

    def test_resending_a_design_without_an_interval_keeps_the_chosen_one(self) -> None:
        address = "FF:FF:92:81:46:32"
        manager = self._manager()
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
            "refresh_interval_seconds": 1800,
            "refresh_trigger_mode": "interval_only",
        }))

        # A send clears the previous design first, then installs the new one -
        # here without saying anything about the schedule.
        asyncio.run(manager.async_set_config(address, None))
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
        }))

        self.assertEqual(
            1800, manager._configs[address]["refresh_interval_seconds"]
        )
        self.assertEqual(
            "interval_only", manager._configs[address]["refresh_trigger_mode"]
        )

    def test_an_explicit_interval_still_wins(self) -> None:
        address = "FF:FF:92:81:46:32"
        manager = self._manager()
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
            "refresh_interval_seconds": 1800,
        }))
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
            "refresh_interval_seconds": 300,
        }))

        self.assertEqual(300, manager._configs[address]["refresh_interval_seconds"])

    def test_a_brand_new_display_still_gets_the_default(self) -> None:
        address = "FF:FF:92:81:46:32"
        manager = self._manager()
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
        }))

        self.assertEqual(600, manager._configs[address]["refresh_interval_seconds"])

    def test_a_failed_upload_still_rolls_its_own_automation_back(self) -> None:
        address = "FF:FF:92:81:46:32"
        manager = self._manager()
        asyncio.run(manager.async_set_config(address, {
            "enabled": True,
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
            "refresh_interval_seconds": 1800,
        }))
        asyncio.run(manager.async_set_config(address, None))
        installed = {
            "enabled": True,
            "installation_id": "abc123",
            "bindings": [{"type": "text", "entity_id": "sensor.temperature"}],
        }
        asyncio.run(manager.async_set_config(address, installed))

        asyncio.run(manager.async_clear_config_if_matches(address, installed))

        self.assertNotIn(address, manager._configs)


class DraftSaveDoesNotResetTheScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ws_projects = (COMPONENT / "ws_projects.py").read_text(encoding="utf-8")
        self.projects = (PANEL / "panel-projects.mixin.js").read_text(encoding="utf-8")
        self.automations = (PANEL / "panel-automations.mixin.js").read_text(encoding="utf-8")

    def test_draft_save_only_pushes_a_value_the_draft_changed(self) -> None:
        self.assertIn('previous = data["device_drafts"].get(address)', self.ws_projects)
        self.assertIn(
            'if interval and interval != previous.get("refresh_interval_seconds"):',
            self.ws_projects,
        )

    def test_panel_adopts_the_live_schedule_of_the_open_display(self) -> None:
        self.assertIn("_syncRefreshSettingsFromAutomations(", self.automations)
        self.assertIn("this._syncRefreshSettingsFromAutomations();", self.automations)

    def test_a_draft_without_an_interval_falls_back_to_the_automation(self) -> None:
        self.assertIn(
            "Number(activeAutomation?.refresh_interval_seconds) || 600",
            self.projects,
        )


if __name__ == "__main__":
    unittest.main()
