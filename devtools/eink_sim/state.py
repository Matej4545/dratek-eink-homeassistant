"""Where entity states come from: a YAML/JSON fixture, or a live (read-only) HA.

State file format (YAML or JSON)::

    now: "2026-11-16T07:30:00"          # optional; the render clock
    states:
      sensor.outside_temperature: 4.2    # shorthand: just the state
      weather.home:
        state: cloudy
        attributes: {temperature: 4.2, humidity: 81}
    forecasts:                           # what weather.get_forecasts would return
      weather.home:
        daily:  [{datetime: "2026-11-17T00:00:00", condition: rainy, temperature: 7, templow: 2}]
        hourly: [...]
    history:                             # numeric history for charts
      sensor.outside_temperature: [["2026-11-16T06:00:00", 3.1], ...]

Live mode reads ``HA_URL`` and ``HA_TOKEN`` (a long-lived access token) from the
environment or ``devtools/.env``. It only issues GET requests plus the
``weather.get_forecasts`` service call, which changes nothing.
"""

from __future__ import annotations

import copy
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def _normalise_entity(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and "state" in value:
        entity = dict(value)
        entity["state"] = str(entity["state"])
        entity.setdefault("attributes", {})
        return entity
    return {"state": str(value), "attributes": {}}


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class StateSource:
    """In-memory snapshot. Also the base the simulator mutates."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.now: datetime | None = parse_dt(data["now"]) if data.get("now") else None
        self.states: dict[str, dict[str, Any]] = {
            k: _normalise_entity(v) for k, v in (data.get("states") or {}).items()
        }
        self.forecasts: dict[str, dict[str, list]] = data.get("forecasts") or {}
        self.history_data: dict[str, list] = data.get("history") or {}

    def refresh(self) -> None:
        """Re-fetch (live sources). No-op for fixtures."""

    def get(self, entity_id: str) -> dict[str, Any] | None:
        return self.states.get(entity_id)

    def forecast(self, entity_id: str, kind: str) -> list[dict[str, Any]]:
        return list((self.forecasts.get(entity_id) or {}).get(kind) or [])

    def history(self, entity_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        points = []
        for stamp, value in self.history_data.get(entity_id) or []:
            when = parse_dt(stamp)
            if start <= when <= end:
                try:
                    points.append((when, float(value)))
                except (TypeError, ValueError):
                    pass
        return points

    def set(self, entity_id: str, value: Any) -> None:
        """Apply a change. A dict merges attributes; a scalar replaces the state."""
        current = self.states.get(entity_id) or {"state": "unknown", "attributes": {}}
        if isinstance(value, dict):
            merged = copy.deepcopy(current)
            if "state" in value:
                merged["state"] = str(value["state"])
            merged["attributes"] = {**merged.get("attributes", {}), **(value.get("attributes") or {})}
            self.states[entity_id] = merged
        else:
            self.states[entity_id] = {**current, "state": str(value)}

    def copy(self) -> "StateSource":
        return copy.deepcopy(self)


def load_state_file(path: str | Path) -> StateSource:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
    return StateSource(data or {})


def _load_env_file() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


class LiveSource(StateSource):
    """Pulls real states from your Home Assistant over its REST API (read-only)."""

    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        super().__init__()
        _load_env_file()
        self.url = (url or os.environ.get("HA_URL") or "").rstrip("/")
        self._token = token or os.environ.get("HA_TOKEN") or ""
        if not self.url or not self._token:
            raise SystemExit("Live mode needs HA_URL and HA_TOKEN (environment or devtools/.env).")
        self._forecast_cache: dict[tuple[str, str], list] = {}
        self._history_cache: dict[tuple[str, int], list] = {}

    def _request(self, path: str, body: dict | None = None) -> Any:
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method="POST" if body is not None else "GET",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - user-configured URL
            return json.loads(resp.read().decode())

    def refresh(self) -> None:
        self.states = {
            item["entity_id"]: {
                "state": item["state"],
                "attributes": item.get("attributes", {}),
                "last_changed": item.get("last_changed"),
            }
            for item in self._request("/api/states")
        }
        self._forecast_cache.clear()
        self._history_cache.clear()

    def forecast(self, entity_id: str, kind: str) -> list[dict[str, Any]]:
        key = (entity_id, kind)
        if key not in self._forecast_cache:
            data = self._request(
                "/api/services/weather/get_forecasts?return_response",
                {"entity_id": entity_id, "type": kind},
            )
            response = data.get("service_response", data)
            self._forecast_cache[key] = (response.get(entity_id) or {}).get("forecast") or []
        return list(self._forecast_cache[key])

    def history(self, entity_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        key = (entity_id, int(start.timestamp()) // 300)
        if key not in self._history_cache:
            stamp = start.astimezone().isoformat()
            rows = self._request(
                f"/api/history/period/{urllib.parse.quote(stamp)}"
                f"?filter_entity_id={entity_id}&minimal_response&no_attributes"
            )
            points = []
            for row in rows[0] if rows else []:
                try:
                    points.append((parse_dt(row["last_changed"]).astimezone().replace(tzinfo=None), float(row["state"])))
                except (KeyError, TypeError, ValueError):
                    pass
            self._history_cache[key] = points
        return [p for p in self._history_cache[key] if start <= p[0] <= end]


def snapshot_to_yaml(source: StateSource, entity_ids: list[str], forecast_ids: list[str], now: datetime) -> str:
    """Freeze part of a (live) source into a fixture file."""
    data: dict[str, Any] = {"now": now.replace(microsecond=0).isoformat(), "states": {}, "forecasts": {}}
    for entity_id in entity_ids:
        entity = source.get(entity_id)
        if entity:
            data["states"][entity_id] = {"state": entity["state"], "attributes": entity.get("attributes", {})}
    for entity_id in forecast_ids:
        data["forecasts"][entity_id] = {k: source.forecast(entity_id, k) for k in ("daily", "hourly")}
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
