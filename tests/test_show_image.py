"""dratek_eink.show_image: fitting/dithering, and the handler's decisions end to end.

The handler runs for real against stubbed Home Assistant modules and a fake
routed-transfer function, so these tests cover source handling, SDK type and
transform resolution, the unchanged-skip, automation pausing and failures -
everything except the radio itself.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import inspect
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path

import voluptuous as vol
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dratek_eink"
PACKAGE = "dratek_show_image_test"
ADDRESS = "FF:FF:94:20:10:78"


class HomeAssistantError(Exception):
    pass


class ServiceValidationError(HomeAssistantError):
    pass


def _install_homeassistant_stubs() -> None:
    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.exceptions": types.ModuleType("homeassistant.exceptions"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.config_validation": types.ModuleType("homeassistant.helpers.config_validation"),
    }
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.core"].ServiceCall = object
    modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    modules["homeassistant.exceptions"].ServiceValidationError = ServiceValidationError
    cv = modules["homeassistant.helpers.config_validation"]
    cv.string = vol.Coerce(str)
    cv.url = vol.Coerce(str)
    cv.entity_id = vol.Coerce(str)
    cv.boolean = vol.Coerce(bool)
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = FakeStore
    modules["homeassistant.helpers.storage"] = storage
    sys.modules.update(modules)


class FakeStore:
    """homeassistant.helpers.storage.Store with an in-memory "disk" shared by key."""

    disk: dict[str, object] = {}

    def __init__(self, hass, version, key) -> None:
        self.key = key

    async def async_load(self):
        return FakeStore.disk.get(self.key)

    def async_delay_save(self, data_func, delay=0) -> None:
        FakeStore.disk[self.key] = data_func()


def _load(name: str):
    module_name = f"{PACKAGE}.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _stub(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(f"{PACKAGE}.{name}")
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[module.__name__] = module
    return module


_install_homeassistant_stubs()
package = types.ModuleType(PACKAGE)
package.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE] = package
screen_image = _load("screen_image")
render = _load("render")


# ------------------------------------------------------------------ fakes


class FakeManager:
    def __init__(self) -> None:
        self._configs: dict[str, dict] = {}
        self.enabled_calls: list[tuple[str, bool]] = []

    @staticmethod
    def _automation_enabled(config):
        return config.get("enabled", True) is not False

    async def async_set_enabled(self, address, enabled):
        self.enabled_calls.append((address, bool(enabled)))
        if address in self._configs:
            self._configs[address]["enabled"] = bool(enabled)


class World:
    """Everything the handler touches outside itself."""

    def __init__(self) -> None:
        self.manager = FakeManager()
        self.project = {"device_drafts": {}}
        self.previews: dict[str, dict] = {}
        self.clock = 1000
        self.sent: list[dict] = []
        self.transfer_ok = True
        self.submissions: list[dict] = []
        self.gateway_route: dict | None = None  # set -> the "router" picks this gateway
        self.gateway_result: dict = {"ok": True}
        self.gateway_calls: list[dict] = []


world = World()


# The fakes carry the exact parameter lists of the functions they replace;
# FakeSignatureTests compares them with the real source.
async def async_save_display_preview(hass, address, image, orientation=None, template_ids=None):
    world.clock += 1
    world.previews[address] = {"preview_updated_at": world.clock, "size": image.size}
    return world.previews[address]


async def async_display_preview(hass, address):
    return world.previews.get(address)


async def _load_project_data(hass):
    return world.project


async def _async_submit_routed_transfer(
    hass, *, address, operation, local_runner, gateway_runner_factory, wait_for_completion, retry_budget=0
):
    world.submissions.append({"address": address, "operation": operation, "wait": wait_for_completion})
    if not wait_for_completion:
        return {"ok": True, "queued": True}
    if world.gateway_route is not None:
        return await gateway_runner_factory(world.gateway_route)(lambda _line: None)
    if not world.transfer_ok:
        return {"ok": False, "error": "display did not answer"}
    return await local_runner(lambda _line: None)


async def async_send_gateway_payload(
    hass, gateway_id, address, sdk_type, image, transform=None, orientation=None,
    software_version=None, log_callback=None, partial=None,
):
    world.gateway_calls.append(
        {"gateway_id": gateway_id, "address": address, "sdk_type": sdk_type, "size": image.size,
         "transform": transform, "orientation": orientation}
    )
    return dict(world.gateway_result)


class FakeTransfer:
    def __init__(self, log=None, hass=None) -> None:
        pass

    async def send_image(self, address, sdk_type, image, transform=None, orientation=None, software_version=None):
        world.sent.append(
            {"address": address, "sdk_type": sdk_type, "image": image, "transform": transform, "orientation": orientation}
        )


_stub("automation", get_entity_auto_update_manager=lambda _hass: world.manager)
_stub("ws_shared", _load_project_data=_load_project_data)
_stub("display_preview", async_save_display_preview=async_save_display_preview,
      async_display_preview=async_display_preview)
_stub("gateway", async_send_gateway_payload=async_send_gateway_payload)
_stub("transfer", DratekTransfer=FakeTransfer)
_stub("ws_sending", _async_submit_routed_transfer=_async_submit_routed_transfer)
image_service = _load("image_service")


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts):
        return str(self.root.joinpath(*parts))

    def is_allowed_path(self, path: str) -> bool:
        return Path(path).resolve().is_relative_to((self.root / "www").resolve())


class FakeHass:
    def __init__(self, root: Path) -> None:
        self.data: dict = {"dratek_eink.discovery_cache": {ADDRESS: {"sdk_type": 46}}}
        self.config = FakeConfig(root)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeCall:
    def __init__(self, data: dict, return_response: bool = True) -> None:
        self.data = image_service.SHOW_IMAGE_SCHEMA(data)
        self.return_response = return_response


def _png(size=(296, 128), colour=(128, 128, 128)) -> str:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, colour)
    image.paste((0, 0, 0), (10, 10, 60, 60))
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


# ------------------------------------------------------------------ tests


class PrepareImageTests(unittest.TestCase):
    def test_bwry_label_gets_four_pigments_only(self):
        source = Image.new("RGB", (296, 128), (232, 108, 6))  # orange
        image, orientation = screen_image.prepare_image(source, 46)
        self.assertEqual((orientation, image.size), ("landscape", (296, 128)))
        colours = {c for _n, c in image.getcolors(1 << 16)}
        self.assertTrue(colours <= set(screen_image.panel_palette(46)))
        self.assertEqual(len(screen_image.panel_palette(46)), 4)

    def test_tall_picture_goes_portrait(self):
        image, orientation = screen_image.prepare_image(Image.new("RGB", (100, 300), "white"), 46)
        self.assertEqual((orientation, image.size), ("portrait", (128, 296)))

    def test_fit_modes(self):
        source = Image.new("RGB", (400, 100), "black")
        contain = screen_image.fit_image(source, (296, 128), "contain")
        self.assertEqual(contain.getpixel((148, 2)), (255, 255, 255))  # letterbox margin
        cover = screen_image.fit_image(source, (296, 128), "cover")
        self.assertEqual(cover.getpixel((148, 2)), (0, 0, 0))
        self.assertEqual(screen_image.fit_image(source, (296, 128), "stretch").size, (296, 128))
        with self.assertRaisesRegex(ValueError, "panel canvas is 296x128"):
            screen_image.fit_image(source, (296, 128), "none")

    def test_transparency_is_flattened_onto_white(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(buffer, "PNG")
        self.assertEqual(screen_image.decode_image(buffer.getvalue()).getpixel((0, 0)), (255, 255, 255))

    def test_garbage_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "Not a readable image"):
            screen_image.decode_image(b"not an image")

    def test_bw_panel_has_no_red(self):
        self.assertEqual(screen_image.panel_palette(296), ((0, 0, 0), (255, 255, 255)))


class ShowImageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        global world
        world.__init__()
        FakeStore.disk.clear()
        # image_service imports Store lazily; other test modules stub this module
        # with their own (Store = object), so put ours back for every test.
        storage = types.ModuleType("homeassistant.helpers.storage")
        storage.Store = FakeStore
        sys.modules["homeassistant.helpers.storage"] = storage
        self.hass = FakeHass(ROOT / "tests")

    def run_call(self, data: dict, return_response: bool = True):
        payload = {"address": ADDRESS.lower(), **data}
        return asyncio.run(image_service.async_handle_show_image(self.hass, FakeCall(payload, return_response)))

    def test_sends_a_fitted_picture_with_the_saved_transform(self):
        world.project["device_drafts"][ADDRESS] = {"display_transform": "rotate_ccw"}
        response = self.run_call({"data": _png((592, 256))})
        self.assertTrue(response["sent"])
        sent = world.sent[-1]
        self.assertEqual((sent["sdk_type"], sent["transform"], sent["image"].size), (46, "rotate_ccw", (296, 128)))
        self.assertTrue({c for _n, c in sent["image"].getcolors(1 << 16)} <= set(screen_image.panel_palette(46)))
        self.assertEqual(world.submissions[-1]["operation"], "show_image")
        self.assertIn(ADDRESS, world.previews)

    def test_default_transform_matches_the_panel(self):
        self.run_call({"data": _png()})
        self.assertEqual(world.sent[-1]["transform"], "rotate_cw")

    def test_identical_picture_is_skipped_until_forced(self):
        self.run_call({"data": _png()})
        second = self.run_call({"data": _png()})
        self.assertEqual((second["sent"], second["reason"]), (False, "unchanged"))
        self.assertEqual(len(world.sent), 1)
        self.assertTrue(self.run_call({"data": _png(), "force": True})["sent"])
        self.assertEqual(len(world.sent), 2)

    def test_the_skip_survives_a_restart(self):
        self.run_call({"data": _png()})
        self.hass = FakeHass(ROOT / "tests")  # fresh hass.data, same "disk"
        self.assertFalse(self.run_call({"data": _png()})["sent"])

    def test_another_write_to_the_display_defeats_the_skip(self):
        self.run_call({"data": _png()})
        world.previews[ADDRESS]["preview_updated_at"] += 50  # e.g. the panel sent a design
        self.assertTrue(self.run_call({"data": _png()})["sent"])

    def test_send_text_path_forgets_the_last_picture(self):
        self.run_call({"data": _png()})
        image_service.forget_last_sent(self.hass, ADDRESS)
        self.assertTrue(self.run_call({"data": _png()})["sent"])

    def test_exactly_one_source(self):
        with self.assertRaisesRegex(ServiceValidationError, "exactly one"):
            self.run_call({})
        with self.assertRaises(vol.Invalid):
            FakeCall({"address": ADDRESS, "data": _png(), "url": "http://x/y.png"})

    def test_file_outside_allowed_dirs_is_refused(self):
        with self.assertRaisesRegex(ServiceValidationError, "allowed directory"):
            self.run_call({"image": str(ROOT / "README.md")})

    def test_allowed_file_is_read(self):
        www = ROOT / "tests" / "www"
        www.mkdir(exist_ok=True)
        target = www / "_show_image_test.png"
        try:
            target.write_bytes(base64.b64decode(_png().split(",", 1)[1]))
            self.assertTrue(self.run_call({"image": "www/_show_image_test.png"})["sent"])
        finally:
            target.unlink(missing_ok=True)
            if not any(www.iterdir()):
                www.rmdir()

    def test_wrong_size_with_fit_none_is_a_validation_error(self):
        with self.assertRaisesRegex(ServiceValidationError, "fit: contain"):
            self.run_call({"data": _png((300, 300)), "fit": "none"})

    def test_bad_base64_is_a_validation_error(self):
        with self.assertRaisesRegex(ServiceValidationError, "base64"):
            self.run_call({"data": "%%%not base64%%%"})

    def test_unknown_sdk_type_asks_for_one(self):
        self.hass.data.clear()
        with self.assertRaisesRegex(ServiceValidationError, "Pass sdk_type"):
            self.run_call({"data": _png()})
        self.assertTrue(self.run_call({"data": _png(), "sdk_type": 46})["sent"])

    def test_sdk_type_falls_back_to_the_automation_config(self):
        self.hass.data.clear()
        world.manager._configs[ADDRESS] = {"sdk_type": 46, "enabled": False}
        self.assertEqual(self.run_call({"data": _png()})["sdk_type"], 46)

    def test_running_automation_is_paused_not_deleted(self):
        world.manager._configs[ADDRESS] = {"sdk_type": 46, "enabled": True, "bindings": [1]}
        response = self.run_call({"data": _png()})
        self.assertTrue(response["automation_paused"])
        self.assertEqual(world.manager._configs[ADDRESS]["bindings"], [1])
        self.assertEqual(world.manager.enabled_calls, [(ADDRESS, False)])

    def test_failed_transfer_raises_and_resumes_the_automation(self):
        world.manager._configs[ADDRESS] = {"enabled": True}
        world.transfer_ok = False
        with self.assertRaisesRegex(HomeAssistantError, "display did not answer"):
            self.run_call({"data": _png()})
        self.assertEqual(world.manager.enabled_calls, [(ADDRESS, False), (ADDRESS, True)])
        world.transfer_ok = True
        self.assertTrue(self.run_call({"data": _png()})["sent"])  # nothing was remembered

    def test_gateway_route_carries_the_same_picture(self):
        world.gateway_route = {"id": "gw-1", "name": "Kitchen ESP32", "rssi": -60}
        world.project["device_drafts"][ADDRESS] = {"display_transform": "rotate_ccw"}
        self.assertTrue(self.run_call({"data": _png()})["sent"])
        self.assertEqual(world.sent, [])
        self.assertEqual(
            world.gateway_calls[-1],
            {"gateway_id": "gw-1", "address": ADDRESS, "sdk_type": 46, "size": (296, 128),
             "transform": "rotate_ccw", "orientation": "landscape"},
        )
        self.assertIn(ADDRESS, world.previews)
        self.assertFalse(self.run_call({"data": _png()})["sent"])  # remembered like a local send

    def test_failed_gateway_transfer_raises_and_remembers_nothing(self):
        world.gateway_route = {"id": "gw-1"}
        world.gateway_result = {"ok": False, "error": "payload_exceeds_gateway_limit"}
        with self.assertRaisesRegex(HomeAssistantError, "payload_exceeds_gateway_limit"):
            self.run_call({"data": _png()})
        self.assertNotIn(ADDRESS, world.previews)

    def test_wait_false_only_queues(self):
        response = self.run_call({"data": _png(), "wait": False})
        self.assertEqual((response["sent"], response["queued"]), (False, True))
        self.assertFalse(world.submissions[-1]["wait"])

    def test_no_response_unless_asked(self):
        self.assertIsNone(self.run_call({"data": _png()}, return_response=False))
        self.assertEqual(len(world.sent), 1)


class RegistrationTests(unittest.TestCase):
    def test_service_is_registered_and_documented(self):
        init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("SERVICE_SHOW_IMAGE", init)
        self.assertIn("supports_response=SupportsResponse.OPTIONAL", init)
        # send_text writes the panel without a preview, so it must forget (and persist that)
        self.assertIn("forget_last_sent(hass, address)", init)
        import yaml

        services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
        schema_keys = {str(key) for key in image_service.SHOW_IMAGE_SCHEMA.schema}
        self.assertEqual(set(services["show_image"]["fields"]), schema_keys)


def _real_parameters(module: str, function: str, cls: str | None = None) -> list[str]:
    tree = ast.parse((COMPONENT / f"{module}.py").read_text(encoding="utf-8"))
    scope = tree.body
    if cls:
        scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
    return [a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]


class FakeSignatureTests(unittest.TestCase):
    """A fake with the wrong parameters would hide a call that fails in production."""

    def test_fakes_match_the_real_signatures(self):
        for fake, module, function, cls in (
            (_async_submit_routed_transfer, "ws_sending", "_async_submit_routed_transfer", None),
            (async_send_gateway_payload, "gateway", "async_send_gateway_payload", None),
            (async_save_display_preview, "display_preview", "async_save_display_preview", None),
            (async_display_preview, "display_preview", "async_display_preview", None),
            (_load_project_data, "ws_shared", "_load_project_data", None),
            (FakeTransfer.send_image, "transfer", "send_image", "DratekTransfer"),
            (FakeTransfer.__init__, "transfer", "__init__", "DratekTransfer"),
        ):
            with self.subTest(function=function):
                self.assertEqual(list(inspect.signature(fake).parameters), _real_parameters(module, function, cls))


if __name__ == "__main__":
    unittest.main()
