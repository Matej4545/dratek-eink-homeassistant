"""Per display: which screen it shows. Drive it from automations with select.select_option."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .device_registry import display_device_info, display_states, display_update_signal

MANAGER_KEY = "screen_manager"  # screen_runtime.MANAGER_KEY, without importing the runtime here
SCREEN_STATUS_SIGNAL = f"{DOMAIN}_screen_status"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = hass.data.get(DOMAIN, {}).get(MANAGER_KEY)
    if manager is None:  # the screen runtime failed to start; it logged why
        return
    added: set[str] = set()

    @callback
    def _add(address: str) -> None:
        normalized = str(address or "").strip().upper()
        if normalized and normalized not in added:
            added.add(normalized)
            async_add_entities([DisplayScreenSelect(manager, normalized)])

    for address in set(display_states(hass)) | set(manager.displays):
        _add(address)
    entry.async_on_unload(async_dispatcher_connect(hass, display_update_signal(entry.entry_id), _add))


class DisplayScreenSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Obrazovka"
    _attr_icon = "mdi:monitor-dashboard"
    _attr_should_poll = False

    def __init__(self, manager: Any, address: str) -> None:
        self._manager = manager
        self.address = address
        self._attr_unique_id = f"display_{address}_screen"

    @property
    def device_info(self) -> dict[str, Any]:
        return display_device_info(self.hass, self.address)

    @property
    def options(self) -> list[str]:
        return self._manager.screen_choices(self.address)

    @property
    def current_option(self) -> str:
        return self._manager.displays.get(self.address, {}).get("screen") or "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._manager.status(self.address)

    async def async_select_option(self, option: str) -> None:
        try:
            await self._manager.async_set_screen(self.address, option)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def async_added_to_hass(self) -> None:
        @callback
        def _changed(address: str | None) -> None:
            if address is None or address == self.address:
                self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SCREEN_STATUS_SIGNAL, _changed))
