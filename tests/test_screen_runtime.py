"""The screen runtime end to end, minus Home Assistant itself and the radio.

ScreenManager and DisplayRunner run for real on a real asyncio loop, with the
real screen_render / screen_context / bundled screens. Home Assistant's helpers
(timers, state tracking, storage, dispatcher, services) are small fakes with
the same call shapes; image_service.async_send_image is a recorder. Timers are
real but shrunk to milliseconds.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"
PACKAGE = "dratek_screen_runtime_test"
ADDRESS = "FF:FF:94:20:10:78"
TZ = timezone(timedelta(hours=1))


# ------------------------------------------------------------- HA fakes


class FakeStore:
    disk: dict[str, object] = {}

    def __init__(self, hass, version, key) -> None:
        self.key = key

    async def async_load(self):
        return FakeStore.disk.get(self.key)

    def async_delay_save(self, data_func, delay=0) -> None:
        import copy

        FakeStore.disk[self.key] = copy.deepcopy(data_func())


class State:
    def __init__(self, entity_id, state, attributes=None) -> None:
        self.entity_id, self.state = entity_id, str(state)
        self.attributes = dict(attributes or {})
        self.last_changed = datetime(2026, 11, 16, 7, 0, tzinfo=TZ)


class Hass:
    def __init__(self) -> None:
        self.data: dict = {}
        self.loop = asyncio.get_running_loop()
        self.config = types.SimpleNamespace(path=lambda *p: str(ROOT / "tests" / "_no_user_screens" / Path(*p)))
        self.states = types.SimpleNamespace(async_all=lambda: list(self._states.values()))
        self._states: dict[str, State] = {}
        self._listeners: list[tuple[set[str], object]] = []
        self.service_calls: list[tuple] = []
        self.forecasts: dict[str, list] = {}
        self.services = types.SimpleNamespace(async_call=self._call)
        self.tasks: list[asyncio.Task] = []

    async def _call(self, domain, service, data, blocking=False, return_response=False):
        self.service_calls.append((domain, service, dict(data), blocking, return_response))
        if (domain, service) == ("calendar", "get_events"):
            return {data["entity_id"]: {"events": [
                {"summary": "Zubař", "start": "2026-11-16T09:00:00+01:00", "end": "2026-11-16T10:00:00+01:00"}]}}
        return {data["entity_id"]: {"forecast": self.forecasts.get(data["entity_id"], [])}}

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_create_background_task(self, coro, name):
        task = self.loop.create_task(coro, name=name)
        self.tasks.append(task)
        return task

    def set_state(self, entity_id, state, attributes=None) -> None:
        self._states[entity_id] = State(entity_id, state, attributes)
        for entities, action in list(self._listeners):
            if entity_id in entities:
                action(types.SimpleNamespace(data={"entity_id": entity_id}))


def _async_call_later(hass, delay, action):
    handle = hass.loop.call_later(delay, action, None)
    return handle.cancel


def _track_state(hass, entity_ids, action):
    entry = (set(entity_ids), action)
    hass._listeners.append(entry)
    return lambda: hass._listeners.remove(entry)


dispatched: list = []
sent: list[dict] = []
send_behaviour = {"fail": False, "same_as_last": False}


async def async_send_image(
    hass, address, image, sdk_type, transform, orientation, *,
    digest=None, force=False, pause_automation=True, wait=True, operation="show_image",
):
    if send_behaviour["fail"]:
        raise SendFailed("display did not answer")
    sent.append({"address": address, "image": image, "sdk_type": sdk_type, "transform": transform,
                 "force": force, "pause_automation": pause_automation, "wait": wait, "operation": operation})
    return {"sent": not send_behaviour["same_as_last"], "digest": "abc"}


def _resolve_sdk_type(hass, address):
    return None


async def _async_resolve_transform(hass, address):
    return "rotate_cw"


def display_state(hass, address):
    return {"sdk_type": 46}


class SendFailed(RuntimeError):
    pass


def _module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module
    return module


_module("homeassistant")
_module("homeassistant.core", Event=object, HomeAssistant=object, callback=lambda f: f)
_module("homeassistant.helpers")
_module("homeassistant.helpers.dispatcher", async_dispatcher_send=lambda hass, signal, *a: dispatched.append(a))
_module("homeassistant.helpers.event", async_call_later=_async_call_later,
        async_track_state_change_event=_track_state)
_module("homeassistant.helpers.storage", Store=FakeStore)
_module("homeassistant.util")
sys.modules["homeassistant.util"].dt = _module(
    "homeassistant.util.dt",
    now=lambda: datetime(2026, 11, 16, 7, 30, tzinfo=TZ),
    utcnow=lambda: datetime(2026, 11, 16, 6, 30, tzinfo=timezone.utc),
    as_local=lambda d: d.astimezone(TZ),
)

package = _module(PACKAGE)
package.__path__ = [str(COMPONENT)]
_module(f"{PACKAGE}.image_service", async_send_image=async_send_image, SendFailed=SendFailed,
        _resolve_sdk_type=_resolve_sdk_type, _async_resolve_transform=_async_resolve_transform)
_module(f"{PACKAGE}.device_registry", display_state=display_state)


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load("screen_runtime")
runtime.DEBOUNCE_SECONDS = 0.02
runtime.MIN_GAP_FLOOR_SECONDS = 0
runtime.RETRY_AFTER_FAILED_SEND_SECONDS = 0.05

HOURLY = [
    {"datetime": f"2026-11-16T{8 + i:02d}:00:00+01:00", "temperature": 3 + i % 5, "precipitation_probability": 20 * (i % 4)}
    for i in range(12)
]


class ScreenRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeStore.disk.clear()
        dispatched.clear()
        sent.clear()
        send_behaviour.update(fail=False, same_as_last=False)

    def run_async(self, scenario):
        async def main():
            hass = Hass()
            hass.set_state("weather.forecast_home", "rainy", {"temperature": 4.2, "humidity": 80})
            hass.set_state("sensor.unrelated", "1")
            hass.forecasts["weather.forecast_home"] = HOURLY
            manager = runtime.ScreenManager(hass)
            await manager.async_setup()
            manager.async_start()
            try:
                outcome = await scenario(hass, manager)
                # What the entities would show, taken while the runners still exist.
                self.status = manager.status(ADDRESS)
                self.running = set(manager.runners)
                return outcome
            finally:
                manager.async_stop()
                for task in hass.tasks:
                    task.cancel()

        return asyncio.run(main())

    @staticmethod
    async def settle(seconds=0.12):
        await asyncio.sleep(seconds)

    def test_bundled_screens_load(self):
        async def scenario(hass, manager):
            return manager.screens

        screens = self.run_async(scenario)
        self.assertTrue({"mini_weather", "mini_departures", "weather", "departures", "test_pattern", "mini_sensors",
                         "door", "going_out"} <= set(screens))
        self.assertEqual([s.id for s in screens.values() if s.error], [])

    def test_choices_only_list_screens_that_fit_the_display(self):
        async def scenario(hass, manager):
            return manager.screen_choices(ADDRESS)

        choices = self.run_async(scenario)
        self.assertEqual(choices[0], "off")
        self.assertIn("mini_weather", choices)
        self.assertIn("test_pattern", choices)  # no SDK_TYPE: fits anything
        self.assertNotIn("weather", choices)  # laid out for 800x480

    def test_assigning_a_screen_renders_with_forecast_and_sends(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather")
            await self.settle()
            return manager

        manager = self.run_async(scenario)
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]["sdk_type"], sent[0]["image"].size, sent[0]["transform"]), (46, (296, 128), "rotate_cw"))
        self.assertEqual(sent[0]["operation"], "screen")
        self.assertEqual(self.status["result"], "sent")
        self.assertEqual(self.status["watched"], ["weather.forecast_home"])

    def test_forecast_is_fetched_through_the_weather_action(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather")
            await self.settle()
            return hass.service_calls

        calls = self.run_async(scenario)
        self.assertIn(("weather", "get_forecasts", {"entity_id": "weather.forecast_home", "type": "hourly"}, True, True), calls)

    def test_calendar_is_read_through_the_calendar_action(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "going_out", options={"calendar": "calendar.family"})
            await self.settle()
            return hass.service_calls

        calls = self.run_async(scenario)
        self.assertIn(("calendar", "get_events", {"entity_id": "calendar.family", "duration": {"hours": 12.0}},
                       True, True), calls)
        self.assertEqual(self.status["result"], "sent")
        self.assertIn("calendar.family", self.status["watched"])

    def test_watched_change_redraws_and_unrelated_change_does_not(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather", min_refresh_seconds=0)
            await self.settle()
            hass.set_state("sensor.unrelated", "2")
            await self.settle()
            after_unrelated = len(sent)
            hass.set_state("weather.forecast_home", "sunny", {"temperature": 9.0, "humidity": 50})
            await self.settle()
            return after_unrelated, len(sent)

        after_unrelated, after_watched = self.run_async(scenario)
        self.assertEqual(after_unrelated, 1)
        self.assertEqual(after_watched, 2)

    def test_minimum_gap_postpones_but_does_not_drop(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather", min_refresh_seconds=0)
            manager.displays[ADDRESS]["min_refresh_seconds"] = 0.3
            manager._apply(ADDRESS)
            await self.settle(0.1)
            first = len(sent)
            hass.set_state("weather.forecast_home", "sunny", {"temperature": 9.0})
            await self.settle(0.1)
            during_gap = len(sent)
            await self.settle(0.4)
            return first, during_gap, len(sent)

        first, during_gap, after_gap = self.run_async(scenario)
        self.assertEqual((first, during_gap, after_gap), (1, 1, 2))

    def test_manual_refresh_skips_the_gap_and_forces(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather")  # default 600 s gap
            await self.settle()
            await manager.async_refresh(ADDRESS, force=True)
            await self.settle()
            return sent

        calls = self.run_async(scenario)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1]["force"])

    def test_options_validated_merged_and_used(self):
        async def scenario(hass, manager):
            with self.assertRaisesRegex(ValueError, "accepts: weather"):
                await manager.async_set_screen(ADDRESS, "mini_weather", options={"nope": 1})
            hass.set_state("weather.home", "sunny", {"temperature": 20})
            await manager.async_set_screen(ADDRESS, "mini_weather", options={"weather": "weather.home"})
            await self.settle()
            return manager

        manager = self.run_async(scenario)
        self.assertEqual(self.status["watched"], ["weather.home"])
        self.assertEqual(FakeStore.disk[runtime.STORE_KEY]["displays"][ADDRESS]["options"],
                         {"mini_weather": {"weather": "weather.home"}})

    def test_unknown_and_unfitting_screens_are_refused(self):
        async def scenario(hass, manager):
            with self.assertRaisesRegex(ValueError, "Unknown screen"):
                await manager.async_set_screen(ADDRESS, "nope")
            with self.assertRaisesRegex(ValueError, "SDK type 299"):
                await manager.async_set_screen(ADDRESS, "weather")

        self.run_async(scenario)

    def test_off_stops_the_runner(self):
        async def scenario(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather", min_refresh_seconds=0)
            await self.settle()
            await manager.async_set_screen(ADDRESS, "off")
            hass.set_state("weather.forecast_home", "sunny", {"temperature": 9.0})
            await self.settle()
            return manager

        manager = self.run_async(scenario)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.running, set())
        self.assertEqual(manager.screen_choices(ADDRESS)[0], "off")

    def test_assignment_survives_a_restart(self):
        async def first(hass, manager):
            await manager.async_set_screen(ADDRESS, "mini_weather", options={"weather": "weather.forecast_home"})
            await self.settle()

        async def second(hass, manager):
            await self.settle()
            return manager

        self.run_async(first)
        sent.clear()
        manager = self.run_async(second)
        self.assertEqual(manager.displays[ADDRESS]["screen"], "mini_weather")
        self.assertIn(ADDRESS, self.running)
        # Restarted within the 600 s gap: the startup redraw is postponed to the
        # gap's end instead of repainting the display on every restart.
        self.assertEqual(sent, [])

    def test_unchanged_frame_does_not_count_as_a_write(self):
        async def scenario(hass, manager):
            send_behaviour["same_as_last"] = True
            await manager.async_set_screen(ADDRESS, "mini_weather")
            await self.settle()
            return manager

        manager = self.run_async(scenario)
        self.assertEqual(self.status["result"], "unchanged")
        self.assertNotIn("last_sent_at", manager.displays[ADDRESS])

    def test_failed_send_is_retried(self):
        async def scenario(hass, manager):
            send_behaviour["fail"] = True
            await manager.async_set_screen(ADDRESS, "mini_weather")
            await self.settle(0.05)
            failed = manager.status(ADDRESS)["result"]
            send_behaviour["fail"] = False
            await self.settle(0.15)
            return failed, manager.status(ADDRESS)["result"]

        failed, later = self.run_async(scenario)
        self.assertEqual((failed, later), ("send_failed", "sent"))

    def test_broken_screen_keeps_its_triggers(self):
        user_dir = ROOT / "tests" / "_no_user_screens" / "dratek_screens"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "flaky.py").write_text(
            "def render(ctx):\n"
            "    value = ctx.state('sensor.flaky')\n"
            "    if value is None:\n"
            "        raise RuntimeError('no data yet')\n"
            "    img, d = ctx.canvas()\n"
            "    return img\n",
            encoding="utf-8",
        )
        try:
            async def scenario(hass, manager):
                await manager.async_set_screen(ADDRESS, "flaky", min_refresh_seconds=0)
                await self.settle()
                error = manager.status(ADDRESS)["result"]
                hass.set_state("sensor.flaky", "ok")
                await self.settle()
                return error, manager.status(ADDRESS)["result"]

            self.assertEqual(self.run_async(scenario), ("error", "sent"))
        finally:
            for path in user_dir.glob("*"):
                path.unlink()
            user_dir.rmdir()
            user_dir.parent.rmdir()


class FakeSignatureTests(unittest.TestCase):
    """A fake with the wrong parameters would hide a call that fails in production."""

    @staticmethod
    def real(module, function):
        import ast

        tree = ast.parse((COMPONENT / f"{module}.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
        return [a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]

    def test_fakes_match_the_real_signatures(self):
        import inspect

        for fake, module, function in (
            (async_send_image, "image_service", "async_send_image"),
            (_resolve_sdk_type, "image_service", "_resolve_sdk_type"),
            (_async_resolve_transform, "image_service", "_async_resolve_transform"),
            (display_state, "device_registry", "display_state"),
        ):
            with self.subTest(function=function):
                self.assertEqual(list(inspect.signature(fake).parameters), self.real(module, function))


if __name__ == "__main__":
    unittest.main()
