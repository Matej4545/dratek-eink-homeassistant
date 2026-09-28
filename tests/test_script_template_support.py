"""Regression checks for Script Template UI and runtime wiring."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "dratek_eink" / "frontend" / "panel"
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


class ScriptTemplateSupportTests(unittest.TestCase):
    def test_script_sandbox_runs_normal_js_and_convenience_parameters(self) -> None:
        script_mixin_url = json.dumps(SCRIPT_MIXIN.as_uri())
        payload = json.dumps(
            """
              const values = [1, 2, 3];
              const doubled = values.map((value) => value * 2);
              class RowBuilder { make(message) { return { text: message }; } }
              const row = new RowBuilder().make(`T:${doubled?.[1] ?? 0}`);
              return [
                { text: `${row.text} / ${data.temp}` },
                { text: String(width + height) },
              ];
            """
        )
        node_script = f"""
          import vm from "node:vm";
          import {{ templateScriptMixin }} from {script_mixin_url};

          globalThis.Blob = class {{
            constructor(parts) {{
              this.code = parts.join("");
            }}
          }};
          globalThis.URL = {{
            createObjectURL(blob) {{
              return blob.code;
            }},
          }};
          globalThis.Worker = class {{
            constructor(code) {{
              this.onmessage = null;
              this.onerror = null;
              const worker = this;
              const scope = {{
                Object,
                String,
                Number,
                Math,
                Date,
                JSON,
                Array,
                Map,
                Set,
                RegExp,
                Error,
                SyntaxError,
                onmessage: null,
                postMessage(payload) {{
                  worker.onmessage?.({{ data: payload }});
                }},
              }};
              scope.self = scope;
              vm.runInNewContext(code, scope);
              this.scope = scope;
            }}
            postMessage(payload) {{
              this.scope.onmessage?.({{ data: payload }});
            }}
            terminate() {{}}
          }};

          const rows = await templateScriptMixin._executeScriptTemplateSandbox.call(
            {{}},
            {payload},
            {{ width: 100, height: 50, data: {{ temp: "Hello" }} }},
          );
          console.log(JSON.stringify(rows));
        """
        rows = json.loads(_run_node(node_script))
        self.assertEqual(rows[0]["text"], "T:4 / Hello")
        self.assertEqual(rows[1]["text"], "150")

    def test_script_sandbox_reports_syntax_errors_clearly(self) -> None:
        script_mixin_url = json.dumps(SCRIPT_MIXIN.as_uri())
        payload = json.dumps('return [{ text: "broken" };')
        node_script = f"""
          import vm from "node:vm";
          import {{ templateScriptMixin }} from {script_mixin_url};

          globalThis.Blob = class {{
            constructor(parts) {{
              this.code = parts.join("");
            }}
          }};
          globalThis.URL = {{
            createObjectURL(blob) {{
              return blob.code;
            }},
          }};
          globalThis.Worker = class {{
            constructor(code) {{
              this.onmessage = null;
              this.onerror = null;
              const worker = this;
              const scope = {{
                Object,
                String,
                Number,
                Math,
                Date,
                JSON,
                Array,
                Map,
                Set,
                RegExp,
                Error,
                SyntaxError,
                onmessage: null,
                postMessage(payload) {{
                  worker.onmessage?.({{ data: payload }});
                }},
              }};
              scope.self = scope;
              vm.runInNewContext(code, scope);
              this.scope = scope;
            }}
            postMessage(payload) {{
              this.scope.onmessage?.({{ data: payload }});
            }}
            terminate() {{}}
          }};

          try {{
            await templateScriptMixin._executeScriptTemplateSandbox.call(
              {{}},
              {payload},
              {{ width: 296, height: 128, data: {{}} }},
            );
            console.log("NO_ERROR");
          }} catch (error) {{
            console.log(String(error?.message || error));
          }}
        """
        message = _run_node(node_script)
        self.assertNotEqual(message, "NO_ERROR")
        self.assertIn("Syntax error in script:", message)

    def test_script_sandbox_timeout_is_relaxed(self) -> None:
        source = SCRIPT_MIXIN.read_text(encoding="utf-8")
        self.assertIn("const SCRIPT_EXECUTION_TIMEOUT_MS = 2000;", source)

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
