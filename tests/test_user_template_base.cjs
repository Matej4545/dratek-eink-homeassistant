const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const panel = path.join(__dirname, '../custom_components/dratek_eink/frontend/panel');
function method(file, name) {
  const source = fs.readFileSync(path.join(panel, file), 'utf8');
  const start = source.indexOf(`  ${name}(`);
  assert.ok(start >= 0);
  const end = source.indexOf('\n  },', start);
  return Function(`return ({${source.slice(start, end + 4)}})` )()[name];
}
const base = method('panel-template-svg.mixin.js', '_templateBaseDefinition');
const rows = method('panel-template-svg.mixin.js', '_templateSvgRows');
const trusted = method('panel-devices.mixin.js', '_hasTrustedUserTemplatePreview');
const save = method('panel-devices.mixin.js', '_storeCurrentUserDisplayTemplate');
const elements = [{type: 'image', src: 'data:image/png;base64,shop', x: 5}, {type: 'text', text: 'Nakupni oddeleni'}];
const user = {id: 'user-1', title: 'Vlastni sablona', user_created: true, base_template_id: '', editor_elements: elements};
const ctx = {
  _selectedDisplayTemplateId: user.id, _userDisplayTemplates: [user],
  _templateEditorElements: structuredClone(elements),
  _displayTemplateCards() { return [...this._userDisplayTemplates, {id:'shopping', title:'Shopping'}].map(t => ({...t})); },
  _templateBaseDefinition: base,
  _rememberActiveTemplateEditorState() {},
  _templateSvgSpecs() { return {shopping: () => [{text: 'real content'}]}; },
  _fourColorTemplateRows(r) { return r; },
};
for (const baseId of ['', 'user-1', 'missing', 'blank']) {
  const template = {...user, base_template_id: baseId};
  assert.deepEqual(rows.call(ctx, template, 296, 128), []);
  if (baseId) assert.equal(trusted.call(ctx, {...template, preview_image:'data:image/png;base64,old', preview_template_id:template.id}), false);
}
// Repeated saves preserve a deliberately empty base and the authored artwork.
for (let i=0; i<3; i++) {
  const saved = save.call(ctx, {});
  assert.equal(saved.base_template_id, '');
  assert.deepEqual(saved.editor_elements, elements);
}
ctx._userDisplayTemplates[0].base_template_id = user.id;
assert.equal(save.call(ctx, {}).base_template_id, '');
ctx._userDisplayTemplates[0].base_template_id = 'shopping';
assert.equal(save.call(ctx, {}).base_template_id, 'shopping');
assert.equal(rows.call(ctx, ctx._userDisplayTemplates[0], 296, 128)[0].text, 'real content');
ctx._userDisplayTemplates = [{...user, base_template_id:'user-2'}, {...user, id:'user-2', base_template_id:'user-1'}];
assert.deepEqual(rows.call(ctx, ctx._userDisplayTemplates[0], 296, 128), []);
ctx._userDisplayTemplates[1].base_template_id = 'shopping';
assert.equal(rows.call(ctx, ctx._userDisplayTemplates[0], 296, 128)[0].text, 'real content');
console.log('User template save, legacy cycles, stale previews and derived bases: OK');
