"""``dratek_eink.show_image``: put any picture on a display.

The picture can come from a file under an allowed directory, a URL, a camera
entity or base64 data - so it can be drawn by anything: a screen renderer, a
pyscript, an external service, a camera snapshot. This module only adapts it
to the panel (screen_image.prepare_image) and hands it to the same routed
transfer path the panel's own sends use, so ESP32 gateways work unchanged.

Behaviour worth knowing:

* SDK type and transform resolve the way the panel resolves them (advertised
  type incl. the name override; the per-display transform saved by the panel).
* A send is skipped when the packed bytes equal this service's last send to the
  display *and* nothing else has written the display since (its stored preview
  is still the one this service saved). ``force: true`` always sends.
* A display's existing automatic refresh is paused (not deleted), otherwise its
  next tick would paint over the picture. Resume it in the panel or with
  ``dratek_eink.set_display_automation``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DEVICE_SIZES, DISCOVERY_CACHE_KEY, DOMAIN
from .screen_image import DITHER_MODES, FIT_MODES, ORIENTATIONS, decode_image, prepare_image

_LOGGER = logging.getLogger(__name__)

SERVICE_SHOW_IMAGE = "show_image"
LAST_SENT_KEY = "show_image_last_sent"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 20
DEFAULT_TRANSFORM = "rotate_cw"  # the panel's default for every display
TRANSFORMS = (
    "rotate_cw", "rotate_ccw", "rotate_cw_flip_lr", "rotate_cw_flip_tb", "rotate_ccw_flip_lr",
    "rotate_ccw_flip_tb", "none", "rotate_180", "flip_lr", "flip_tb",
)
SOURCES = ("image", "url", "camera_entity", "data")

SHOW_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("address"): cv.string,
        vol.Exclusive("image", "source"): cv.string,
        vol.Exclusive("url", "source"): cv.url,
        vol.Exclusive("camera_entity", "source"): cv.entity_id,
        vol.Exclusive("data", "source"): cv.string,
        vol.Optional("sdk_type"): vol.Coerce(int),
        vol.Optional("fit", default="contain"): vol.In(FIT_MODES),
        vol.Optional("orientation", default="auto"): vol.In(ORIENTATIONS),
        vol.Optional("dither", default="ordered"): vol.In(DITHER_MODES),
        vol.Optional("transform"): vol.In(TRANSFORMS),
        vol.Optional("force", default=False): cv.boolean,
        vol.Optional("pause_automation", default=True): cv.boolean,
        vol.Optional("wait", default=True): cv.boolean,
    }
)


def forget_last_sent(hass: HomeAssistant, address: str) -> None:
    """Call from any other path that writes a display without saving a preview."""
    hass.data.get(DOMAIN, {}).get(LAST_SENT_KEY, {}).pop(str(address).strip().upper(), None)


# ---------------------------------------------------------------- sources


async def _async_read_source(hass: HomeAssistant, kind: str, value: str) -> bytes:
    if kind == "image":
        path = Path(value)
        if not path.is_absolute():
            path = Path(hass.config.path(value))
        if not hass.config.is_allowed_path(str(path)):
            raise ServiceValidationError(
                f"{path} is not in an allowed directory. Put it under /config/www or /media "
                "(allowed by default), or add its folder to homeassistant: allowlist_external_dirs."
            )

        def read() -> bytes:
            if not path.is_file():
                raise ServiceValidationError(f"{path} does not exist.")
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise ServiceValidationError(f"{path} is larger than {MAX_SOURCE_BYTES // 1048576} MB.")
            return path.read_bytes()

        return await hass.async_add_executor_job(read)

    if kind == "url":
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        chunks: list[bytes] = []
        total = 0
        try:
            async with session.get(value, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS)) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ServiceValidationError(f"{value} is larger than {MAX_SOURCE_BYTES // 1048576} MB.")
                    chunks.append(chunk)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HomeAssistantError(f"Could not fetch {value}: {exc}") from exc
        return b"".join(chunks)

    if kind == "camera_entity":
        from homeassistant.components.camera import async_get_image

        try:
            return (await async_get_image(hass, value, timeout=FETCH_TIMEOUT_SECONDS)).content
        except HomeAssistantError as exc:
            raise HomeAssistantError(f"Could not get an image from {value}: {exc}") from exc

    text = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ServiceValidationError("data is not valid base64.") from exc


# ------------------------------------------------------------ resolution


def _automation_config(hass: HomeAssistant, address: str) -> dict[str, Any]:
    from .automation import get_entity_auto_update_manager

    return dict(get_entity_auto_update_manager(hass)._configs.get(address) or {})


def _resolve_sdk_type(hass: HomeAssistant, address: str) -> int | None:
    # 1. What the panel's scans saw, locally or through a gateway.
    for key, device in (hass.data.get(DISCOVERY_CACHE_KEY) or {}).items():
        if str(key).upper() == address and isinstance(device, dict) and device.get("sdk_type"):
            return int(device["sdk_type"])
    # 2. Home Assistant's own Bluetooth cache, parsed exactly like a scan
    #    (including the PE29R name override in parse_dratek_manufacturer_data).
    try:
        from homeassistant.components import bluetooth

        from .discovery import parse_dratek_advertisement

        for info in bluetooth.async_discovered_service_info(hass, connectable=False):
            if str(getattr(info, "address", "")).upper() == address:
                parsed = parse_dratek_advertisement(info)
                if parsed is not None:
                    return int(parsed.sdk_type)
    except Exception:  # Bluetooth integration absent or incompatible core
        pass
    # 3. The type recorded with the display's automatic refresh.
    sdk_type = _automation_config(hass, address).get("sdk_type")
    return int(sdk_type) if sdk_type else None


async def _async_resolve_transform(hass: HomeAssistant, address: str) -> str:
    from .ws_shared import _load_project_data

    try:
        draft = (await _load_project_data(hass)).get("device_drafts", {}).get(address) or {}
    except Exception:
        draft = {}
    for candidate in (draft.get("display_transform"), _automation_config(hass, address).get("transform")):
        if candidate in TRANSFORMS:
            return str(candidate)
    return DEFAULT_TRANSFORM


# ---------------------------------------------------------------- service


async def async_handle_show_image(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any] | None:
    data = call.data
    address = str(data["address"]).strip().upper()
    given = [kind for kind in SOURCES if data.get(kind)]
    if len(given) != 1:
        raise ServiceValidationError("Give exactly one of: image, url, camera_entity, data.")

    sdk_type = int(data.get("sdk_type") or _resolve_sdk_type(hass, address) or 0)
    if not sdk_type:
        raise ServiceValidationError(
            f"The SDK type of {address} is unknown: it has not been seen advertising since Home "
            "Assistant started. Pass sdk_type (46 is the 2.9\" BWRY label)."
        )
    if sdk_type not in DEVICE_SIZES:
        raise ServiceValidationError(f"Unsupported SDK type {sdk_type}.")
    transform = data.get("transform") or await _async_resolve_transform(hass, address)

    raw = await _async_read_source(hass, given[0], data[given[0]])

    from .render import pack_bwr_image, packing_description

    def prepare() -> tuple[Any, str, str]:
        image, orientation = prepare_image(
            decode_image(raw), sdk_type,
            fit=data.get("fit", "contain"),
            orientation=data.get("orientation", "auto"),
            dither=data.get("dither", "ordered"),
        )
        digest = hashlib.sha1(pack_bwr_image(sdk_type, image, transform, orientation)).hexdigest()
        return image, orientation, digest

    try:
        image, orientation, digest = await hass.async_add_executor_job(prepare)
    except ValueError as exc:
        raise ServiceValidationError(str(exc)) from exc

    response: dict[str, Any] = {
        "address": address, "sdk_type": sdk_type, "transform": transform, "orientation": orientation,
        "width": image.width, "height": image.height, "digest": digest[:12],
    }
    last_sent = hass.data.setdefault(DOMAIN, {}).setdefault(LAST_SENT_KEY, {})

    if not data.get("force") and await _async_already_showing(hass, address, digest, last_sent):
        _LOGGER.debug("[%s] show_image skipped: the display already shows this picture", address)
        return {**response, "sent": False, "reason": "unchanged"} if call.return_response else None

    response["automation_paused"] = False
    if data.get("pause_automation", True):
        response["automation_paused"] = await _async_pause_automation(hass, address)

    from .display_preview import async_save_display_preview
    from .gateway import async_send_gateway_payload
    from .transfer import DratekTransfer
    from .ws_sending import _async_submit_routed_transfer

    async def on_success(add_log) -> None:
        try:
            preview = await async_save_display_preview(hass, address, image, orientation, template_ids=[])
            last_sent[address] = {"digest": digest, "preview_updated_at": preview.get("preview_updated_at")}
        except Exception as exc:  # the pixels are on the display either way
            forget_last_sent(hass, address)
            add_log(f"Display updated, but its preview could not be saved: {exc}")

    async def run_local(add_log) -> dict[str, Any]:
        add_log(f"show_image: {image.width}x{image.height}, {packing_description(sdk_type)}, transform {transform}.")
        await DratekTransfer(log=add_log, hass=hass).send_image(address, sdk_type, image, transform, orientation)
        await on_success(add_log)
        return {"ok": True, "address": address, "log": []}

    def gateway_runner_factory(route: dict[str, Any]):
        async def run_gateway(add_log) -> dict[str, Any]:
            add_log(f"show_image: {image.width}x{image.height} via gateway {route.get('name') or route.get('id')}.")
            result = await async_send_gateway_payload(
                hass, str(route.get("id") or ""), address, sdk_type, image, transform, orientation,
                None, log_callback=add_log,
            )
            if result and result.get("ok") is not False:
                await on_success(add_log)
                return result
            return result or {"ok": False, "error": "Gateway transfer failed."}

        return run_gateway

    forget_last_sent(hass, address)  # until this send is confirmed, assume nothing
    result = await _async_submit_routed_transfer(
        hass,
        address=address,
        operation="show_image",
        local_runner=run_local,
        gateway_runner_factory=gateway_runner_factory,
        wait_for_completion=bool(data.get("wait", True)),
    )
    if result and result.get("ok") is False:
        if response["automation_paused"]:
            # The old picture is still on the panel; let its refresh carry on.
            from .automation import get_entity_auto_update_manager

            await get_entity_auto_update_manager(hass).async_set_enabled(address, True)
        raise HomeAssistantError(f"Sending to {address} failed: {result.get('error') or 'unknown error'}")
    if data.get("wait", True):
        response.update({"sent": True, "queued": False})
    else:
        # Only queued: the outcome (and resuming a paused automation on failure)
        # is not known here. The queue panel and the preview camera show it.
        response.update({"sent": False, "queued": True})
    return response if call.return_response else None


async def _async_already_showing(hass: HomeAssistant, address: str, digest: str, last_sent: dict) -> bool:
    record = last_sent.get(address)
    if not record or record.get("digest") != digest:
        return False
    from .display_preview import async_display_preview

    preview = await async_display_preview(hass, address) or {}
    # Any other write that saves a preview (panel send, automatic refresh) moves this stamp.
    return preview.get("preview_updated_at") == record.get("preview_updated_at")


async def _async_pause_automation(hass: HomeAssistant, address: str) -> bool:
    from .automation import get_entity_auto_update_manager

    manager = get_entity_auto_update_manager(hass)
    config = manager._configs.get(address)
    if not config or not manager._automation_enabled(config):
        return False
    await manager.async_set_enabled(address, False)
    _LOGGER.info("[%s] show_image paused the display's automatic refresh", address)
    return True
