"""Screens rendered by Home Assistant itself, redrawn when their data changes.

Each display can be assigned one screen (a Python file, see screen_render.py)
plus per-display options. A DisplayRunner per assigned display:

1. renders the screen in the executor from a snapshot of HA's states, plus the
   forecasts / history / departures the screen asked for (fetched on the event
   loop, cached, last good value kept when a fetch fails);
2. watches exactly the entities the screen read, and redraws on their change,
   on the screen's INTERVAL, and on request - paced by screen_render.UpdatePolicy
   (debounce, minimum gap between panel writes, persisted across restarts);
3. sends through image_service.async_send_image, which skips identical frames.

Screens come from the integration's bundled_screens/ folder and from
/config/dratek_screens/ (same id = yours wins). Fonts and icons for your own
screens go in /config/dratek_screens/fonts and /config/dratek_screens/icons.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import image_service
from .const import DOMAIN
from .device_registry import display_state
from .screen_render import (
    OFF,
    ScreenInfo,
    UpdatePolicy,
    check_options,
    is_compatible,
    render_screen,
    resolve_options,
    scan_screens,
)

_LOGGER = logging.getLogger(__name__)

STORE_KEY = "dratek_eink.screens"
SCREEN_STATUS_SIGNAL = f"{DOMAIN}_screen_status"
MANAGER_KEY = "screen_manager"
BUNDLED_DIR = Path(__file__).resolve().parent / "bundled_screens"
USER_DIR_NAME = "dratek_screens"
DEBOUNCE_SECONDS = 5.0
# The 2.9" labels run on a CR2450 coin cell: every panel write costs battery.
DEFAULT_MIN_GAP_SECONDS = 600
MIN_GAP_FLOOR_SECONDS = 30
RETRY_AFTER_FAILED_SEND_SECONDS = 300
DATA_TTL_SECONDS = {"forecast": 15 * 60, "transit": 60, "history": 5 * 60, "calendar": 10 * 60}
EMPTY_DATA = {"forecast": [], "history": [], "calendar": [], "transit": {"stop_name": "", "departures": []}}


def get_screen_manager(hass: HomeAssistant) -> "ScreenManager | None":
    return hass.data.get(DOMAIN, {}).get(MANAGER_KEY)


class _HaSource:
    """screen_context.Source over a state snapshot and pre-fetched data."""

    def __init__(self, states: dict[str, Any], data: dict[tuple, Any]) -> None:
        self._states = states
        self._data = data

    def get(self, entity_id: str) -> dict[str, Any] | None:
        state = self._states.get(entity_id)
        if state is None:
            return None
        return {
            "state": state.state,
            "attributes": dict(state.attributes),
            "last_changed": state.last_changed.isoformat(),
        }

    def forecast(self, entity_id: str, kind: str):
        return self._data.get(("forecast", entity_id, kind))

    def history(self, entity_id: str, hours: float, now):
        return self._data.get(("history", entity_id, float(hours)))

    def transit(self, stop_id: str, limit: int):
        return self._data.get(("transit", stop_id, int(limit)))

    def calendar(self, entity_id: str, hours: float):
        return self._data.get(("calendar", entity_id, float(hours)))


class ScreenManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store = Store(hass, 1, STORE_KEY)
        self.displays: dict[str, dict[str, Any]] = {}
        self.screens: dict[str, ScreenInfo] = {}
        self.runners: dict[str, DisplayRunner] = {}
        self.user_dir = Path(hass.config.path(USER_DIR_NAME))
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._started = False

    # ----------------------------------------------------------- lifecycle
    @property
    def font_dirs(self) -> tuple[Path, ...]:
        return (self.user_dir / "fonts",)

    @property
    def icon_dirs(self) -> tuple[Path, ...]:
        return (self.user_dir / "icons",)

    async def async_setup(self) -> None:
        stored = await self.store.async_load() or {}
        self.displays = {
            str(address).upper(): dict(cfg)
            for address, cfg in (stored.get("displays") or {}).items()
            if isinstance(cfg, dict)
        }
        await self.async_reload_screens(restart=False)

    @callback
    def async_start(self, _hass: Any = None) -> None:
        """Start the runners - once Home Assistant has started and states exist."""
        self._started = True
        for address, cfg in self.displays.items():
            if cfg.get("screen"):
                self._apply(address)

    @callback
    def async_stop(self) -> None:
        self._started = False
        for runner in self.runners.values():
            runner.stop()
        self.runners.clear()

    def _save(self) -> None:
        self.store.async_delay_save(lambda: {"displays": self.displays}, 1)

    async def async_reload_screens(self, restart: bool = True) -> dict[str, ScreenInfo]:
        folders = [(BUNDLED_DIR, True), (self.user_dir, False)]
        self.screens = await self.hass.async_add_executor_job(scan_screens, folders)
        for info in self.screens.values():
            if info.error:
                _LOGGER.error("Screen %s could not be loaded:\n%s", info.path, info.error)
        if restart and self._started:
            for address in list(self.runners):
                self._apply(address)
        async_dispatcher_send(self.hass, SCREEN_STATUS_SIGNAL, None)
        return self.screens

    # -------------------------------------------------------------- queries
    def sdk_type_for(self, address: str) -> int | None:
        address = address.upper()
        for candidate in (
            display_state(self.hass, address).get("sdk_type"),
            image_service._resolve_sdk_type(self.hass, address),
            self.displays.get(address, {}).get("sdk_type"),
        ):
            try:
                if candidate and int(candidate):
                    return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def screen_choices(self, address: str) -> list[str]:
        sdk_type = self.sdk_type_for(address)
        ids = sorted(i for i, info in self.screens.items() if not info.error and is_compatible(info, sdk_type))
        current = self.displays.get(address.upper(), {}).get("screen")
        if current and current not in ids:
            ids.append(current)  # keep showing what is assigned, even if it vanished
        return [OFF, *ids]

    def status(self, address: str) -> dict[str, Any]:
        address = address.upper()
        cfg = self.displays.get(address, {})
        screen_id = cfg.get("screen")
        info = self.screens.get(screen_id) if screen_id else None
        runner = self.runners.get(address)
        status: dict[str, Any] = {
            "screen_title": info.title if info else None,
            "options": resolve_options(info, cfg.get("options", {}).get(screen_id)) if info else {},
            "min_refresh_seconds": int(cfg.get("min_refresh_seconds", DEFAULT_MIN_GAP_SECONDS)),
            "available_screens": {
                i: s.title for i, s in self.screens.items() if not s.error and is_compatible(s, self.sdk_type_for(address))
            },
        }
        if runner:
            status.update(runner.status)
        return status

    # ------------------------------------------------------------- commands
    async def async_set_screen(
        self,
        address: str,
        screen_id: str | None,
        *,
        options: dict[str, Any] | None = None,
        reset_options: bool = False,
        min_refresh_seconds: int | None = None,
    ) -> None:
        """Assign a screen (or "off"). Raises ValueError with a user-facing message."""
        address = address.strip().upper()
        cfg = self.displays.setdefault(address, {"screen": None, "options": {}})
        cfg.setdefault("options", {})
        if not screen_id or screen_id == OFF:
            if options:
                raise ValueError("Options need a screen.")
            cfg["screen"] = None
        else:
            info = self.screens.get(screen_id)
            if info is None:
                raise ValueError(f"Unknown screen {screen_id!r}. Available: {', '.join(sorted(self.screens)) or 'none'}.")
            if info.error:
                raise ValueError(f"Screen {screen_id!r} failed to load: {info.error.strip().splitlines()[-1]}")
            sdk_type = self.sdk_type_for(address)
            if not is_compatible(info, sdk_type):
                raise ValueError(f"Screen {screen_id!r} is laid out for SDK type {info.sdk_type}, not {sdk_type}.")
            if options is not None:
                check_options(info, options)
            stored = {} if reset_options else dict(cfg["options"].get(screen_id) or {})
            stored.update(options or {})
            if stored:
                cfg["options"][screen_id] = stored
            else:
                cfg["options"].pop(screen_id, None)
            cfg["screen"] = screen_id
            if sdk_type:
                cfg["sdk_type"] = sdk_type
        if min_refresh_seconds is not None:
            cfg["min_refresh_seconds"] = max(MIN_GAP_FLOOR_SECONDS, int(min_refresh_seconds))
        self._save()
        self._apply(address)

    async def async_refresh(self, address: str, *, force: bool = True) -> None:
        runner = self.runners.get(address.strip().upper())
        if runner is None:
            raise ValueError(f"No screen is assigned to {address}.")
        runner.request(force=force)

    @callback
    def _apply(self, address: str) -> None:
        runner = self.runners.pop(address, None)
        if runner:
            runner.stop()
        if self._started and self.displays.get(address, {}).get("screen"):
            runner = DisplayRunner(self, address)
            self.runners[address] = runner
            runner.start()
        async_dispatcher_send(self.hass, SCREEN_STATUS_SIGNAL, address)

    @callback
    def _record_send(self, address: str) -> None:
        self.displays.setdefault(address, {})["last_sent_at"] = time.time()
        self._save()

    # ----------------------------------------------------------------- data
    async def async_fetch(self, keys: set[tuple], refetch_entities: set[str]) -> dict[tuple, Any]:
        """Answer forecast / history / departure requests, using the cache when fresh."""
        now = self.hass.loop.time()
        data: dict[tuple, Any] = {}
        for key in keys:
            kind = key[0]
            cached = self._cache.get(key)
            stale = cached is None or now - cached[0] > DATA_TTL_SECONDS.get(kind, 300)
            if kind in ("forecast", "calendar") and key[1] in refetch_entities:
                stale = True  # the weather / calendar entity changed: its data probably did too
            if stale:
                try:
                    value = await self._async_fetch_one(key)
                    self._cache[key] = (now, value)
                    cached = self._cache[key]
                except Exception as exc:  # keep the last good value; never fail a render on this
                    _LOGGER.warning("Fetching %s for a screen failed: %s", key, exc)
            data[key] = cached[1] if cached else EMPTY_DATA.get(kind)
        return data

    async def _async_fetch_one(self, key: tuple) -> Any:
        kind = key[0]
        if kind == "forecast":
            _, entity_id, forecast_type = key
            response = await self.hass.services.async_call(
                "weather", "get_forecasts", {"entity_id": entity_id, "type": forecast_type},
                blocking=True, return_response=True,
            )
            return list(((response or {}).get(entity_id) or {}).get("forecast") or [])
        if kind == "calendar":
            _, entity_id, hours = key
            response = await self.hass.services.async_call(
                "calendar", "get_events", {"entity_id": entity_id, "duration": {"hours": hours}},
                blocking=True, return_response=True,
            )
            return list(((response or {}).get(entity_id) or {}).get("events") or [])
        if kind == "transit":
            from .transit import async_get_departures

            return await async_get_departures(self.hass, key[1], key[2])
        if kind == "history":
            _, entity_id, hours = key
            from homeassistant.components.recorder import get_instance, history

            end = dt_util.utcnow()
            start = end - timedelta(hours=hours)
            changes = await get_instance(self.hass).async_add_executor_job(
                partial(history.state_changes_during_period, self.hass, start, end, entity_id, no_attributes=True)
            )
            points = []
            for state in changes.get(entity_id, []):
                try:
                    points.append((dt_util.as_local(state.last_changed).replace(tzinfo=None), float(state.state)))
                except (TypeError, ValueError):
                    continue
            return points
        raise ValueError(f"Unknown data request {key!r}")


class DisplayRunner:
    """Keeps one display's screen current."""

    def __init__(self, manager: ScreenManager, address: str) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.address = address
        cfg = manager.displays[address]
        self.screen_id: str = cfg["screen"]
        info = manager.screens.get(self.screen_id)
        self.policy = UpdatePolicy(
            debounce=DEBOUNCE_SECONDS,
            min_gap=float(cfg.get("min_refresh_seconds", DEFAULT_MIN_GAP_SECONDS)),
            interval=info.interval if info else None,
        )
        self.status: dict[str, Any] = {"result": "starting", "error": ""}
        self._lock = asyncio.Lock()
        self._timer = None
        self._unsub_state = None
        self._watched: frozenset[str] = frozenset()
        self._needs: set[tuple] = set()
        self._changed: set[str] = set()
        self._stopped = False

    def _now(self) -> float:
        return self.hass.loop.time()

    @callback
    def start(self) -> None:
        last_sent_at = self.manager.displays[self.address].get("last_sent_at")
        if last_sent_at:  # the minimum gap survives a restart
            self.policy.last_send_at = self._now() - max(0.0, time.time() - float(last_sent_at))
        self.policy.start(self._now())
        self._arm()

    @callback
    def stop(self) -> None:
        self._stopped = True
        if self._timer:
            self._timer()
            self._timer = None
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def request(self, *, force: bool = False) -> None:
        self.policy.request(self._now(), "manual refresh", immediate=True, force=force)
        self._arm()

    @callback
    def _arm(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        wake = self.policy.next_wakeup()
        if wake is None or self._stopped:
            return
        self._timer = async_call_later(self.hass, max(0.0, wake - self._now()), self._on_timer)

    @callback
    def _on_timer(self, _now: Any) -> None:
        self._timer = None
        self.hass.async_create_background_task(self._async_process(), f"dratek_eink screen {self.address}")

    @callback
    def _on_state(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        self._changed.add(entity_id)
        self.policy.on_change(self._now(), entity_id)
        if not self._lock.locked():
            self._arm()  # otherwise _async_process re-arms when it finishes

    @callback
    def _watch(self, entities: set[str]) -> None:
        wanted = frozenset(entities)
        if wanted == self._watched:
            return
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._watched = wanted
        if wanted:
            self._unsub_state = async_track_state_change_event(self.hass, sorted(wanted), self._on_state)

    async def _async_process(self) -> None:
        async with self._lock:
            if self._stopped:
                return
            decision = self.policy.decide(self._now())
            if decision == "defer":
                self.status["next_write_in_s"] = round((self.policy.due_at or self._now()) - self._now())
            elif decision == "render":
                reason, force = self.policy.reason, self.policy.forced
                outcome = await self._async_render_and_send(reason, force)
                self.policy.done(self._now(), sent=outcome == "sent")
                if outcome == "send_failed":
                    self.policy.due_at = self._now() + RETRY_AFTER_FAILED_SEND_SECONDS
                    self.policy.reason = "retry after a failed send"
            if not self._stopped:
                self._arm()

    def _finish(self, **status: Any) -> None:
        self.status.update(status)
        self.status["last_render"] = dt_util.now().isoformat(timespec="seconds")
        async_dispatcher_send(self.hass, SCREEN_STATUS_SIGNAL, self.address)

    async def _async_render_and_send(self, reason: str, force: bool) -> str:
        manager, hass = self.manager, self.hass
        self.status["reason"] = reason
        info = manager.screens.get(self.screen_id)
        if info is None or info.error or info.module is None:
            self._finish(result="error", error=f"Screen {self.screen_id!r} is not available.")
            return "error"
        sdk_type = manager.sdk_type_for(self.address)
        if not sdk_type:
            self._finish(result="error", error="SDK type unknown: the display has not been seen since HA started.")
            return "error"
        if not is_compatible(info, sdk_type):
            self._finish(result="error", error=f"{self.screen_id} is laid out for SDK {info.sdk_type}, display is {sdk_type}.")
            return "error"

        transform = await image_service._async_resolve_transform(hass, self.address)
        options = resolve_options(info, manager.displays[self.address].get("options", {}).get(self.screen_id))
        changed, self._changed = self._changed, set()
        data = await manager.async_fetch(self._needs, changed)
        tz = dt_util.now().tzinfo
        now_local = dt_util.now().replace(tzinfo=None, microsecond=0)

        result = None
        for _attempt in range(3):  # data the screen asked for that we did not have yet
            states = {state.entity_id: state for state in hass.states.async_all()}
            result = await hass.async_add_executor_job(
                partial(
                    render_screen, info.module, _HaSource(states, data), sdk_type, now_local,
                    options=options, tz=tz, font_dirs=manager.font_dirs, icon_dirs=manager.icon_dirs,
                )
            )
            new = result.missing - data.keys()
            if not new:
                break
            data.update(await manager.async_fetch(new, set()))
        assert result is not None
        self._needs = set(result.requested)

        if not result.ok:
            # Keep every trigger we know of: a screen that fails on missing data
            # must still redraw once that data arrives.
            self._watch(set(self._watched) | result.accessed)
            _LOGGER.error("[%s] screen %s failed:\n%s", self.address, self.screen_id, result.error)
            self._finish(result="error", error=result.error.strip().splitlines()[-1], watched=sorted(self._watched))
            return "error"

        self._watch(result.accessed)
        try:
            response = await image_service.async_send_image(
                hass, self.address, result.image, sdk_type, transform, result.orientation,
                force=force, pause_automation=True, wait=True, operation="screen",
            )
        except image_service.SendFailed as exc:
            self._finish(result="send_failed", error=str(exc), watched=sorted(self._watched))
            return "send_failed"
        except Exception as exc:  # never let one display's failure kill its runner
            _LOGGER.exception("[%s] sending screen %s failed", self.address, self.screen_id)
            self._finish(result="send_failed", error=str(exc), watched=sorted(self._watched))
            return "send_failed"

        if sdk_type != manager.displays[self.address].get("sdk_type"):
            manager.displays[self.address]["sdk_type"] = sdk_type
        if response.get("sent"):
            manager._record_send(self.address)
            self.status["last_sent"] = dt_util.now().isoformat(timespec="seconds")
        self.status.pop("next_write_in_s", None)
        self._finish(
            result="sent" if response.get("sent") else "unchanged",
            error="",
            render_ms=round(result.render_ms),
            watched=sorted(result.accessed),
            digest=response.get("digest"),
        )
        return "sent" if response.get("sent") else "unchanged"
