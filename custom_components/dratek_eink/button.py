"""Per display: redraw its screen now (ignores the minimum refresh gap)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .device_registry import display_device_info, display_states, display_update_signal

MANAGER_KEY = "screen_manager"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = hass.data.get(DOMAIN, {}).get(MANAGER_KEY)
    if manager is None:
        return
    added: set[str] = set()

    @callback
    def _add(address: str) -> None:
        normalized = str(address or "").strip().upper()
        if normalized and normalized not in added:
            added.add(normalized)
            async_add_entities([DisplayRedrawButton(manager, normalized)])

    for address in set(display_states(hass)) | set(manager.displays):
        _add(address)
    entry.async_on_unload(async_dispatcher_connect(hass, display_update_signal(entry.entry_id), _add))


class DisplayRedrawButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Překreslit obrazovku"
    _attr_icon = "mdi:refresh"

    def __init__(self, manager: Any, address: str) -> None:
        self._manager = manager
        self.address = address
        self._attr_unique_id = f"display_{address}_redraw"

    @property
    def device_info(self) -> dict[str, Any]:
        return display_device_info(self.hass, self.address)

    async def async_press(self) -> None:
        try:
            await self._manager.async_refresh(self.address, force=True)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
