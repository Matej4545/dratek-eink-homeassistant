const SCRIPT_SOURCE_LIMIT = 64 * 1024;
const SCRIPT_OUTPUT_LIMIT = 256 * 1024;
const SCRIPT_EXECUTION_TIMEOUT_MS = 2000;
const SCRIPT_MAX_ROWS = 80;
const SCRIPT_MAX_ROW_KEYS = 80;

const SCRIPT_ALLOWED_SOURCE_TYPES = new Set([
  "entity",
  "forecast",
  "calendar",
  "transit",
  "todo_list",
  "http",
]);

function clampText(value, max = 2000) {
  return String(value ?? "").slice(0, max);
}

export const templateScriptMixin = {
  _isScriptUserTemplate(template) {
    return !!template?.user_created && String(template?.template_type || "").toLowerCase() === "script";
  },

  _scriptTemplateDefaultSource() {
    return [
      "const title = String(data.inside_temperature ?? \"21.5 °C\");",
      "const humidity = String(data.inside_humidity ?? \"45 %\");",
      "return [",
      "  { band: { label: \"SCRIPT\", value: \"CUSTOM WIDGET\" }, bleed: true, h: 0.18 },",
      "  { duo: {",
      "      left: { icon: \"thermometer\", label: \"Teplota\", value: title },",
      "      right: { icon: \"water-percent\", label: \"Vlhkost\", value: humidity }",
      "    }, h: 0.62 },",
      "  { footer: [{ label: \"Zdroj\", value: \"Script Template\" }], h: 0.12 },",
      "];",
    ].join("\n");
  },

  _scriptTemplateDefaultDataSources() {
    return [
      {
        id: "inside_temperature",
        type: "entity",
        entity_id: "sensor.living_room_temperature",
      },
      {
        id: "inside_humidity",
        type: "entity",
        entity_id: "sensor.living_room_humidity",
      },
    ];
  },

  _newScriptTemplateDraft() {
    const now = Math.floor(Date.now() / 1000);
    return {
      id: `user-template-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      title: "Script Template",
      category: "custom",
      variables: [],
      template_type: "script",
      script_source: this._scriptTemplateDefaultSource(),
      data_sources: this._scriptTemplateDefaultDataSources(),
      script_revision: 1,
      script_validation: { valid: false, error: "", updated_at: now },
      script_last_good_source: "",
      script_last_good_revision: 0,
      user_created: true,
      created_at: now,
      updated_at: now,
      editor_elements: [],
      element_adjustments: {},
    };
  },

  _normalizeScriptDataSource(source) {
    if (!source || typeof source !== "object") return null;
    const type = String(source.type || "entity").trim().toLowerCase();
    const sourceType = SCRIPT_ALLOWED_SOURCE_TYPES.has(type) ? type : "entity";
    const id = String(source.id || "").trim().slice(0, 80);
    if (!id) return null;
    return {
      id,
      type: sourceType,
      entity_id: clampText(source.entity_id, 255).trim(),
      entity_attribute: clampText(source.entity_attribute, 120).trim(),
      path: clampText(source.path, 255).trim(),
      url: clampText(source.url, 1024).trim(),
      method: String(source.method || "GET").toUpperCase() === "POST" ? "POST" : "GET",
      headers: source.headers && typeof source.headers === "object" && !Array.isArray(source.headers)
        ? Object.fromEntries(
          Object.entries(source.headers)
            .map(([key, value]) => [clampText(key, 80), clampText(value, 512)])
            .filter(([key]) => key.trim()),
        )
        : {},
      body: clampText(source.body, 4096),
      timeout_seconds: Math.max(1, Math.min(30, Number(source.timeout_seconds) || 10)),
    };
  },

  _normalizeScriptTemplateTemplate(source) {
    const template = source ? structuredClone(source) : this._newScriptTemplateDraft();
    const now = Math.floor(Date.now() / 1000);
    const id = String(template.id || `user-template-${Date.now()}`).trim();
    const revision = Math.max(1, Number(template.script_revision) || 1);
    const normalizedSources = (Array.isArray(template.data_sources) ? template.data_sources : [])
      .map((item) => this._normalizeScriptDataSource(item))
      .filter(Boolean)
      .slice(0, 24);
    return {
      ...template,
      id,
      title: clampText(template.title || "Script Template", 120),
      category: "custom",
      user_created: true,
      template_type: "script",
      variables: normalizedSources.map((item) => [item.type === "entity" ? "database-outline" : "source-branch", item.id]),
      editor_elements: [],
      element_adjustments: {},
      script_source: clampText(template.script_source, SCRIPT_SOURCE_LIMIT),
      data_sources: normalizedSources,
      script_revision: revision,
      script_validation: {
        valid: !!template?.script_validation?.valid,
        error: clampText(template?.script_validation?.error, 2000),
        updated_at: Number(template?.script_validation?.updated_at) || now,
      },
      script_last_good_source: clampText(template.script_last_good_source, SCRIPT_SOURCE_LIMIT),
      script_last_good_revision: Math.max(0, Number(template.script_last_good_revision) || 0),
      created_at: Number(template.created_at) || now,
      updated_at: Number(template.updated_at) || now,
    };
  },

  _scriptTemplateEditorDataSourcesFromText(text) {
    let parsed = [];
    if (String(text || "").trim()) parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) throw new Error("Data sources must be a JSON array.");
    return parsed.map((item) => this._normalizeScriptDataSource(item)).filter(Boolean);
  },

  _openScriptTemplateEditor(templateId = "") {
    const existing = (this._userDisplayTemplates || []).find((template) => template.id === templateId);
    const draft = this._normalizeScriptTemplateTemplate(existing || this._newScriptTemplateDraft());
    this._scriptTemplateEditorTemplateId = draft.id;
    this._scriptTemplateEditorTitle = draft.title;
    this._scriptTemplateEditorSource = draft.script_source;
    this._scriptTemplateEditorDataSources = JSON.stringify(draft.data_sources || [], null, 2);
    this._scriptTemplateEditorRevision = Number(draft.script_revision) || 1;
    this._scriptTemplateEditorValidation = structuredClone(draft.script_validation || { valid: false, error: "" });
    this._scriptTemplateEditorLastGoodSource = draft.script_last_good_source || "";
    this._scriptTemplateEditorLastGoodRevision = Number(draft.script_last_good_revision) || 0;
    this._scriptTemplateEditorOpen = true;
    this._scriptTemplateEditorResult = null;
    this._templateEditMenuId = "";
    this._render();
    this._paint();
  },

  _closeScriptTemplateEditor() {
    this._scriptTemplateEditorOpen = false;
    this._scriptTemplateEditorResult = null;
    this._render();
    this._paint();
  },

  async _validateScriptTemplateEditor() {
    try {
      const sources = this._scriptTemplateEditorDataSourcesFromText(this._scriptTemplateEditorDataSources);
      const source = clampText(this._scriptTemplateEditorSource, SCRIPT_SOURCE_LIMIT);
      const result = await this._executeScriptTemplateSandbox(source, {
        width: 296,
        height: 128,
        data: Object.fromEntries(sources.map((item) => [item.id, this._scriptTemplateSampleValue(item)])),
      });
      const rows = this._sanitizeScriptTemplateRows(result);
      this._scriptTemplateEditorValidation = {
        valid: true,
        error: "",
        updated_at: Math.floor(Date.now() / 1000),
      };
      this._scriptTemplateEditorResult = {
        ok: true,
        message: `Script is valid (${rows.length} rows).`,
      };
      this._render();
      this._paint();
      return true;
    } catch (error) {
      this._scriptTemplateEditorValidation = {
        valid: false,
        error: clampText(error?.message || error, 2000),
        updated_at: Math.floor(Date.now() / 1000),
      };
      this._scriptTemplateEditorResult = {
        ok: false,
        message: `Validation failed: ${this._scriptTemplateEditorValidation.error}`,
      };
      this._render();
      this._paint();
      return false;
    }
  },

  async _saveScriptTemplateEditor() {
    const valid = await this._validateScriptTemplateEditor();
    if (!valid) return;
    const now = Math.floor(Date.now() / 1000);
    const template = this._normalizeScriptTemplateTemplate({
      id: this._scriptTemplateEditorTemplateId,
      title: this._scriptTemplateEditorTitle || "Script Template",
      category: "custom",
      template_type: "script",
      script_source: this._scriptTemplateEditorSource,
      data_sources: this._scriptTemplateEditorDataSourcesFromText(this._scriptTemplateEditorDataSources),
      script_revision: Math.max(1, Number(this._scriptTemplateEditorRevision) + 1),
      script_validation: this._scriptTemplateEditorValidation,
      script_last_good_source: this._scriptTemplateEditorSource,
      script_last_good_revision: Math.max(1, Number(this._scriptTemplateEditorRevision) + 1),
      user_created: true,
      created_at: now,
      updated_at: now,
    });
    const saved = await this._saveUserDisplayTemplate(template);
    this._scriptTemplateRowsCache = new Map();
    this._scriptTemplateEditorTemplateId = saved.id;
    this._scriptTemplateEditorRevision = Number(saved.script_revision) || template.script_revision;
    this._scriptTemplateEditorLastGoodSource = saved.script_source || template.script_source;
    this._scriptTemplateEditorLastGoodRevision = Number(saved.script_last_good_revision) || template.script_last_good_revision;
    this._scriptTemplateEditorResult = { ok: true, message: "Script template saved." };
    this._render();
    this._paint();
  },

  _rollbackScriptTemplateEditorToLastGood() {
    if (!this._scriptTemplateEditorLastGoodSource) return;
    this._scriptTemplateEditorSource = this._scriptTemplateEditorLastGoodSource;
    this._scriptTemplateEditorRevision = Math.max(1, Number(this._scriptTemplateEditorLastGoodRevision) || 1);
    this._scriptTemplateEditorResult = { ok: true, message: "Rolled back to last valid revision." };
    this._render();
    this._paint();
  },

  _scriptTemplateSampleValue(source) {
    const type = String(source?.type || "entity");
    if (type === "forecast") return [{ condition: "sunny", temperature: 23, datetime: new Date().toISOString() }];
    if (type === "calendar") return [{ summary: "Událost", start: new Date().toISOString(), location: "Domov" }];
    if (type === "todo_list") return [{ summary: "Mléko", status: "needs_action" }];
    if (type === "transit") return { stop_name: "Hlavní nádraží", departures: [{ line: "9", destination: "Centrum", countdown: "za 4 min" }] };
    return "sample";
  },

  async _resolveScriptTemplateDataSources(template) {
    const data = {};
    for (const source of template?.data_sources || []) {
      const key = String(source?.id || "").trim();
      if (!key) continue;
      const sourceType = String(source?.type || "entity");
      if (sourceType === "entity") {
        const entityId = String(source.entity_id || "").trim();
        if (!entityId) {
          data[key] = null;
          continue;
        }
        const state = this._hass?.states?.[entityId];
        if (!state) {
          data[key] = null;
          continue;
        }
        const attribute = String(source.entity_attribute || "").trim();
        data[key] = attribute ? state.attributes?.[attribute] : state.state;
        continue;
      }
      if (sourceType === "forecast") {
        data[key] = this._templateForecast(String(source.entity_id || "").trim()) || [];
        continue;
      }
      if (sourceType === "calendar") {
        data[key] = this._templateCalendarEvents(String(source.entity_id || "").trim()) || [];
        continue;
      }
      if (sourceType === "todo_list") {
        data[key] = this._templateTodoItems(String(source.entity_id || "").trim()) || [];
        continue;
      }
      if (sourceType === "transit") {
        data[key] = this._transitPreview || null;
        continue;
      }
      if (sourceType === "http") {
        data[key] = { error: "HTTP source is disabled in this phase." };
        continue;
      }
      data[key] = null;
    }
    return data;
  },

  _scriptTemplateRowsKey(template, width, height) {
    const signature = this._hass?.states || null;
    const stamp = Number(template?.updated_at) || Number(template?.script_revision) || 0;
    return `${template?.id || "script"}:${stamp}:${width}x${height}:${signature ? "live" : "none"}`;
  },

  _scriptTemplateLoadingRows(template) {
    return [
      { band: { label: "SCRIPT", value: "LOADING" }, bleed: true, h: 0.2 },
      { text: String(template?.title || "Script Template"), size: 0.1, h: 0.32, bold: true },
      { text: "Načítám data a vyhodnocuji skript…", size: 0.07, h: 0.2 },
      { flex: true },
      { footer: [{ label: "Status", value: "pending" }], h: 0.1 },
    ];
  },

  _scriptTemplateErrorRows(template, error) {
    return [
      { band: { label: "SCRIPT", value: "ERROR", color: "red" }, bleed: true, h: 0.2 },
      { text: String(template?.title || "Script Template"), size: 0.1, h: 0.24, bold: true },
      { text: "Skript se nepodařilo vykreslit.", size: 0.08, h: 0.16 },
      { text: clampText(error || "Unknown error", 120), size: 0.06, h: 0.18 },
      { flex: true },
      { footer: [{ label: "Tip", value: "Otevřete editor a klikněte Validovat" }], h: 0.1 },
    ];
  },

  _sanitizeScriptTemplateRows(value) {
    if (!Array.isArray(value)) throw new Error("Script must return an array of row objects.");
    const rows = value
      .filter((row) => row && typeof row === "object" && !Array.isArray(row))
      .slice(0, SCRIPT_MAX_ROWS)
      .map((row) => {
        const sanitized = {};
        for (const [key, entry] of Object.entries(row).slice(0, SCRIPT_MAX_ROW_KEYS)) {
          sanitized[key] = entry;
        }
        return structuredClone(sanitized);
      });
    if (!rows.length) throw new Error("Script returned no rows.");
    const encoded = JSON.stringify(rows);
    if (encoded.length > SCRIPT_OUTPUT_LIMIT) throw new Error("Script output is too large.");
    return rows;
  },

  async _executeScriptTemplateSandbox(source, context) {
    const script = clampText(source, SCRIPT_SOURCE_LIMIT);
    if (!script.trim()) throw new Error("Script source is empty.");
    const workerBody = `
      const __global = self;
      const __postMessage = postMessage.bind(__global);
      const __Function = Function;
      const __lock = (name, value = undefined) => {
        try {
          Object.defineProperty(__global, name, {
            value,
            writable: false,
            configurable: false,
          });
        } catch (_error) {}
      };
      [
        "fetch",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "importScripts",
        "indexedDB",
        "caches",
        "BroadcastChannel",
        "Worker",
        "SharedWorker",
        "window",
        "document",
        "globalThis",
        "self",
        "Function",
        "eval",
      ].forEach((name) => __lock(name));
      try {
        if (__global?.navigator && typeof __global.navigator === "object" && "sendBeacon" in __global.navigator) {
          Object.defineProperty(__global.navigator, "sendBeacon", {
            value: undefined,
            writable: false,
            configurable: false,
          });
        }
      } catch (_error) {}
      onmessage = (event) => {
        try {
          const source = String(event.data?.source || "");
          const context = event.data?.context || {};
          const data = context?.data || {};
          const width = Number(context?.width) || 296;
          const height = Number(context?.height) || 128;
          const runner = __Function("context", "data", "width", "height", source);
          const result = runner(context, data, width, height);
          __postMessage({ ok: true, result });
        } catch (error) {
          const message = String(error?.message || error);
          const syntax = error?.name === "SyntaxError"
            ? \`Syntax error in script: \${message}\`
            : message;
          __postMessage({ ok: false, error: syntax });
        }
      };
    `;
    const blob = new Blob([workerBody], { type: "application/javascript" });
    const worker = new Worker(URL.createObjectURL(blob));
    try {
      const result = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          worker.terminate();
          reject(new Error(`Script timed out after ${SCRIPT_EXECUTION_TIMEOUT_MS}ms.`));
        }, SCRIPT_EXECUTION_TIMEOUT_MS);
        worker.onmessage = (event) => {
          clearTimeout(timeout);
          const payload = event.data || {};
          if (!payload.ok) {
            reject(new Error(payload.error || "Script execution failed."));
            return;
          }
          resolve(payload.result);
        };
        worker.onerror = (event) => {
          clearTimeout(timeout);
          reject(new Error(event?.message || "Script worker error."));
        };
        worker.postMessage({
          source: script,
          context: {
            width: Number(context?.width) || 296,
            height: Number(context?.height) || 128,
            data: context?.data || {},
            now_iso: new Date().toISOString(),
            now_unix: Math.floor(Date.now() / 1000),
          },
        });
      });
      return result;
    } finally {
      worker.terminate();
    }
  },

  _requestScriptTemplateRows(template, width, height) {
    this._scriptTemplateRowsCache ||= new Map();
    this._scriptTemplateRowsPending ||= new Set();
    const key = this._scriptTemplateRowsKey(template, width, height);
    const cached = this._scriptTemplateRowsCache.get(key);
    if (cached?.status === "ready") return cached.rows;
    if (cached?.status === "error") return this._scriptTemplateErrorRows(template, cached.error);
    if (this._scriptTemplateRowsPending.has(key)) return this._scriptTemplateLoadingRows(template);
    this._scriptTemplateRowsPending.add(key);
    this._scriptTemplateRowsCache.set(key, { status: "pending" });
    Promise.resolve()
      .then(async () => {
        const data = await this._resolveScriptTemplateDataSources(template);
        const result = await this._executeScriptTemplateSandbox(template.script_source, { width, height, data });
        const rows = this._sanitizeScriptTemplateRows(result);
        this._scriptTemplateRowsCache.set(key, { status: "ready", rows });
      })
      .catch((error) => {
        this._scriptTemplateRowsCache.set(key, { status: "error", error: clampText(error?.message || error, 2000) });
      })
      .finally(() => {
        this._scriptTemplateRowsPending.delete(key);
        this._render();
        this._paint();
      });
    return this._scriptTemplateLoadingRows(template);
  },

  _scriptTemplateRows(template, width, height) {
    try {
      return this._requestScriptTemplateRows(template, width, height);
    } catch (error) {
      return this._scriptTemplateErrorRows(template, error?.message || error);
    }
  },

  _assignedTemplatesAreValidForSend(device) {
    const cards = this._displayTemplateCards?.() || [];
    const assigned = this._assignedDisplayTemplates?.(device) || [];
    for (const templateId of assigned) {
      const template = cards.find((item) => item.id === templateId);
      if (!this._isScriptUserTemplate(template)) continue;
      if (template?.script_validation?.valid) continue;
      return false;
    }
    return true;
  },

  _renderScriptTemplateEditorDialog() {
    if (!this._scriptTemplateEditorOpen) return "";
    const valid = !!this._scriptTemplateEditorValidation?.valid;
    const result = this._scriptTemplateEditorResult;
    return `<div class="template-settings-backdrop" data-script-template-close>
      <section class="card template-settings-dialog" role="dialog" aria-modal="true" aria-label="Script Template editor" style="max-width:980px" data-script-template-dialog>
        <header>
          <span><small>Script Template</small><strong>${this._escape(this._scriptTemplateEditorTitle || "Script Template")}</strong></span>
          <button type="button" data-script-template-close title="Zavřít"><ha-icon icon="mdi:close"></ha-icon></button>
        </header>
        <div class="template-settings-dialog-content" style="display:grid;gap:14px">
          <div class="field">
            <label>Název šablony</label>
            <input type="text" data-script-template-title value="${this._escape(this._scriptTemplateEditorTitle || "")}" maxlength="120">
          </div>
          <div class="field">
            <label>Data sources (JSON pole)</label>
            <textarea rows="7" data-script-template-sources spellcheck="false">${this._escape(this._scriptTemplateEditorDataSources || "[]")}</textarea>
          </div>
          <div class="field">
            <label>Script (body) <small style="opacity:.7">Dostupné: context, data, width, height, context.now_iso, context.now_unix</small></label>
            <textarea rows="14" data-script-template-source spellcheck="false">${this._escape(this._scriptTemplateEditorSource || "")}</textarea>
          </div>
          <div class="template-guide-section" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <button type="button" class="secondary" data-script-template-validate><ha-icon icon="mdi:check-decagram-outline"></ha-icon> Validovat</button>
            <button type="button" class="secondary" data-script-template-rollback ${this._scriptTemplateEditorLastGoodSource ? "" : "disabled"}><ha-icon icon="mdi:history"></ha-icon> Obnovit poslední funkční</button>
            <button type="button" class="primary-action" data-script-template-save><ha-icon icon="mdi:content-save-check-outline"></ha-icon> Uložit</button>
            <span class="pill ${valid ? "good" : "warning"}">${valid ? "Validní" : "Nevalidní"}</span>
            <span class="pill muted">rev ${Math.max(1, Number(this._scriptTemplateEditorRevision) || 1)}</span>
          </div>
          ${result ? `<div class="template-send-result ${result.ok ? "is-success" : "is-error"}"><ha-icon icon="mdi:${result.ok ? "check-circle-outline" : "alert-circle-outline"}"></ha-icon><span>${this._escape(result.message)}</span></div>` : ""}
          ${!valid && this._scriptTemplateEditorValidation?.error ? `<div class="template-send-result is-error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${this._escape(this._scriptTemplateEditorValidation.error)}</span></div>` : ""}
        </div>
      </section>
    </div>`;
  },
};
