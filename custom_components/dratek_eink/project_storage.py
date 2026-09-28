"""Compatibility helpers for persisted display projects and custom elements."""

from __future__ import annotations

from typing import Any

SCRIPT_TEMPLATE_MAX_SOURCE = 64 * 1024
SCRIPT_TEMPLATE_MAX_SOURCES = 24
SCRIPT_TEMPLATE_MAX_TITLE = 120


def _record_list(value: Any) -> list[dict[str, Any]]:
    """Return records from both current lists and legacy numeric-key mappings."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _normalize_record_objects(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    objects = normalized.get("objects")
    if isinstance(objects, dict):
        normalized["objects"] = _record_list(objects)
    elif not isinstance(objects, list):
        normalized["objects"] = []
    else:
        normalized["objects"] = [
            item for item in objects if isinstance(item, dict)
        ]
    return normalized


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_device_drafts(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize all historical device draft layouts into an address mapping."""
    candidates: list[tuple[Any, Any]]
    if isinstance(value, list):
        candidates = [(None, item) for item in value]
    elif isinstance(value, dict):
        if "objects" in value and ("device_address" in value or "address" in value):
            candidates = [(None, value)]
        else:
            candidates = list(value.items())
    else:
        candidates = []

    drafts: dict[str, dict[str, Any]] = {}
    for stored_key, source in candidates:
        if not isinstance(source, dict):
            continue
        address = str(
            source.get("device_address")
            or source.get("address")
            or stored_key
            or ""
        ).strip().upper()
        if not address:
            continue
        draft = _normalize_record_objects(source)
        draft["device_address"] = address
        variables = draft.get("variables")
        if not isinstance(variables, dict):
            draft["variables"] = {}
        drafts[address] = draft
    return drafts


def normalize_custom_elements(value: Any) -> list[dict[str, Any]]:
    """Normalize custom elements, layers and layer objects without dropping data."""
    elements: list[dict[str, Any]] = []
    sources = (
        [value]
        if isinstance(value, dict) and ("id" in value or "element_type" in value)
        else _record_list(value)
    )
    for source in sources:
        element = dict(source)
        layers = []
        for layer_source in _record_list(element.get("layers")):
            layers.append(_normalize_record_objects(layer_source))
        if element.get("element_type") == "layered" or "layers" in element:
            element["layers"] = layers
        rules = element.get("condition_rules")
        if isinstance(rules, dict):
            element["condition_rules"] = _record_list(rules)
        elif not isinstance(rules, list):
            element["condition_rules"] = []
        else:
            element["condition_rules"] = [
                item for item in rules if isinstance(item, dict)
            ]
        elements.append(element)
    return elements


def normalize_user_templates(value: Any) -> list[dict[str, Any]]:
    """Keep valid user-created display templates in the shared library."""
    templates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in _record_list(value):
        template_id = str(source.get("id") or "").strip()
        if not template_id.startswith("user-template-") or template_id in seen:
            continue
        seen.add(template_id)
        template = dict(source)
        template["id"] = template_id
        template["title"] = str(template.get("title") or "Vlastní šablona")[:SCRIPT_TEMPLATE_MAX_TITLE]
        template["user_created"] = True
        template_type = str(template.get("template_type") or "designer").strip().lower()
        if template_type not in {"designer", "script"}:
            template_type = "designer"
        template["template_type"] = template_type
        if template_type == "script":
            script_source = str(template.get("script_source") or "")
            template["script_source"] = script_source[:SCRIPT_TEMPLATE_MAX_SOURCE]
            sources: list[dict[str, Any]] = []
            for source_item in _record_list(template.get("data_sources"))[:SCRIPT_TEMPLATE_MAX_SOURCES]:
                source_id = str(source_item.get("id") or "").strip()[:80]
                source_type = str(source_item.get("type") or "entity").strip().lower()
                if source_type not in {"entity", "forecast", "calendar", "transit", "todo_list", "http"}:
                    source_type = "entity"
                if not source_id:
                    continue
                normalized_source = {
                    "id": source_id,
                    "type": source_type,
                    "entity_id": str(source_item.get("entity_id") or "").strip()[:255],
                    "entity_attribute": str(source_item.get("entity_attribute") or "").strip()[:120],
                    "path": str(source_item.get("path") or "").strip()[:255],
                    "url": str(source_item.get("url") or "").strip()[:1024],
                    "method": (
                        "POST"
                        if str(source_item.get("method") or "GET").strip().upper() == "POST"
                        else "GET"
                    ),
                    "headers": {
                        str(key)[:80]: str(value)[:512]
                        for key, value in (source_item.get("headers") or {}).items()
                        if str(key).strip()
                    } if isinstance(source_item.get("headers"), dict) else {},
                    "body": str(source_item.get("body") or "")[:4096],
                    "timeout_seconds": max(
                        1,
                        min(30, _safe_int(source_item.get("timeout_seconds"), 10)),
                    ),
                }
                sources.append(normalized_source)
            template["data_sources"] = sources
            template["script_revision"] = max(1, _safe_int(template.get("script_revision"), 1))
            template["script_validation"] = {
                "valid": bool((template.get("script_validation") or {}).get("valid")),
                "error": str((template.get("script_validation") or {}).get("error") or "")[:2000],
                "updated_at": _safe_int((template.get("script_validation") or {}).get("updated_at"), 0),
            }
            template["script_last_good_source"] = str(template.get("script_last_good_source") or "")[
                :SCRIPT_TEMPLATE_MAX_SOURCE
            ]
            template["script_last_good_revision"] = max(
                0, _safe_int(template.get("script_last_good_revision"), 0)
            )
            template["editor_elements"] = []
            template["element_adjustments"] = {}
        else:
            template["editor_elements"] = _record_list(template.get("editor_elements"))
            template.pop("script_source", None)
            template.pop("data_sources", None)
            template.pop("script_revision", None)
            template.pop("script_validation", None)
            template.pop("script_last_good_source", None)
            template.pop("script_last_good_revision", None)
        adjustments = template.get("element_adjustments")
        template["element_adjustments"] = adjustments if isinstance(adjustments, dict) else {}
        templates.append(template)
    return templates


def normalize_project_data(value: Any) -> dict[str, Any]:
    """Return a safe, current-shaped project store from any historical payload."""
    source = dict(value) if isinstance(value, dict) else {}
    normalized = dict(source)
    normalized["projects"] = [
        _normalize_record_objects(item)
        for item in _record_list(source.get("projects"))
    ]
    normalized["device_drafts"] = normalize_device_drafts(
        source.get("device_drafts")
    )
    names = source.get("device_names")
    normalized["device_names"] = {
        str(address).strip().upper(): str(name)
        for address, name in names.items()
        if str(address).strip() and isinstance(name, (str, int, float))
    } if isinstance(names, dict) else {}
    gateway_preferences = source.get("device_gateway_preferences")
    normalized["device_gateway_preferences"] = {
        str(address).strip().upper(): str(gateway_id).strip()
        for address, gateway_id in gateway_preferences.items()
        if str(address).strip()
        and isinstance(gateway_id, (str, int, float))
        and str(gateway_id).strip()
    } if isinstance(gateway_preferences, dict) else {}
    normalized["custom_elements"] = normalize_custom_elements(
        source.get("custom_elements")
    )
    normalized["user_templates"] = normalize_user_templates(
        source.get("user_templates")
    )
    return normalized
