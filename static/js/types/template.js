/**
 * Template 类型定义
 *
 * @typedef {Object} TemplatePrototype
 * @property {string} prototype_id
 * @property {string} [source_name]
 * @property {'button'|'indicator'|'io_field'|'text'|'unknown'} item_kind
 * @property {string} [behavior]
 * @property {string} [indicator_mode]
 * @property {string[]} [replaceable_tags]
 * @property {Object[]} [tag_references]
 * @property {Object[]} [event_patterns]
 * @property {Object[]} [binding_patterns]
 *
 * @typedef {Object} TemplateProfile
 * @property {string} [screen_name]
 * @property {TemplatePrototype[]} [buttons]
 * @property {TemplatePrototype[]} [indicators]
 * @property {TemplatePrototype[]} [others]
 * @property {Object[]} [all_tag_references]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 */
