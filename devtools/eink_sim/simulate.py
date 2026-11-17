"""Replay a timeline of state changes and show when the display would refresh.

Runs in simulated time (a 24 h scenario takes seconds). The update policy is the
integration's own ``screen_render.UpdatePolicy`` - the object Home Assistant's
screen runtime uses:

* redraw when an entity the screen *read* last time changes (debounced),
  and every ``INTERVAL`` seconds if the screen sets one;
* never refresh the panel more often than ``min_gap`` - a change inside the gap
  is deferred, not dropped;
* skip the write when the packed bytes equal what the panel already shows.

Scenario file (YAML)::

    screen: weather            # a bundled screen id, or a path to a .py file
    state: ../states/demo.yaml
    options: {weather: weather.home}
    sdk_type: 299
    duration: 6h               # s / m / h suffix, or seconds
    debounce: 5                # seconds (default 5)
    min_gap: 120               # seconds between panel writes (default 600, as in HA)
    events:
      - at: 10m             # offset from the state file's `now`
        set: {sensor.outside_temperature: 5.1}
      - at: 1h
        set: {weather.home: {state: rainy, attributes: {temperature: 4.0}}}
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .pipeline import (Frame, changed_box, load_screen, render_frame, resolve_screen_path, screen_render,
                       screen_sdk_type)
from .state import StateSource, load_state_file


def seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text)
    if parts and re.fullmatch(r"(\s*\d+(?:\.\d+)?\s*[dhms])+\s*", text):
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return sum(float(n) * units[u] for n, u in parts)  # "1h30m", "10m3s"
    return float(text)


@dataclass
class LogEntry:
    t: float
    kind: str  # change | ignored | sent | unchanged | deferred | error
    detail: str
    frame_file: str = ""
    box: tuple[int, int, int, int] | None = None
    bytes: int = 0


@dataclass
class Result:
    log: list[LogEntry] = field(default_factory=list)
    renders: int = 0
    sends: int = 0

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for entry in self.log:
            out[entry.kind] = out.get(entry.kind, 0) + 1
        return out


def run(scenario_path: str | Path, out_dir: str | Path | None = None) -> Result:
    scenario_path = Path(scenario_path).resolve()
    base = scenario_path.parent
    cfg = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    screen_ref = str(cfg["screen"])
    screen_path = resolve_screen_path((base / screen_ref) if screen_ref.endswith(".py") else screen_ref)
    source = load_state_file(base / cfg["state"]) if cfg.get("state") else StateSource()
    sdk_type = int(cfg.get("sdk_type") or screen_sdk_type(screen_path))
    options = dict(cfg.get("options") or {})
    start: datetime = source.now or datetime.now().replace(microsecond=0)
    duration = seconds(cfg.get("duration", "6h"))
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parents[1] / "out" / scenario_path.stem
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    screen = load_screen(screen_path)
    # The integration's own policy object - the simulator only feeds it a clock.
    policy = screen_render.UpdatePolicy(
        debounce=seconds(cfg.get("debounce", 5)),
        min_gap=seconds(cfg.get("min_gap", 600)),
        interval=screen.interval,
    )
    events = sorted(((seconds(e["at"]), e.get("set") or {}) for e in cfg.get("events") or []), key=lambda e: e[0])

    result = Result()
    watched: set[str] = set()
    last_digest = ""
    last_image = None
    event_i = 0
    frame_no = 0
    policy.start(0.0)

    while True:
        candidates = [c for c in (policy.next_wakeup(), events[event_i][0] if event_i < len(events) else None)
                      if c is not None]
        if not candidates:
            break
        t = min(candidates)
        if t > duration:
            break

        while event_i < len(events) and events[event_i][0] == t:
            for entity_id, value in events[event_i][1].items():
                source.set(entity_id, value)
                if entity_id in watched:
                    result.log.append(LogEntry(t, "change", f"{entity_id} → {_short(value)}"))
                    policy.on_change(t, entity_id)
                else:
                    result.log.append(LogEntry(t, "ignored", f"{entity_id} → {_short(value)} (screen does not read it)"))
            event_i += 1

        reason = policy.reason
        decision = policy.decide(t)
        if decision == "defer":
            since = t - (policy.last_send_at or 0)
            result.log.append(LogEntry(t, "deferred", f"{policy.reason}; panel refreshed {since:.0f}s ago, "
                                                      f"waiting until +{_fmt(policy.due_at or t)}"))
            continue
        if decision != "render":
            continue
        reason = policy.reason or reason
        now = start + timedelta(seconds=t)
        source.now = now  # departures count down from the simulated clock
        frame: Frame = render_frame(screen, source, sdk_type, now, options=options)
        result.renders += 1
        if not frame.ok:
            policy.done(t, sent=False)
            result.log.append(LogEntry(t, "error", frame.error.strip().splitlines()[-1]))
            (out / f"error_{frame_no:04d}.txt").write_text(frame.error, encoding="utf-8")
            continue
        watched = frame.accessed
        if frame.digest == last_digest:
            policy.done(t, sent=False)
            result.log.append(LogEntry(t, "unchanged", f"{reason}; identical bytes, no write"))
            continue
        policy.done(t, sent=True)
        frame_no += 1
        name = f"{frame_no:04d}_{_fmt(t).replace(':', '')}.png"
        frame.panel_image.save(out / name)
        box = changed_box(last_image, frame.panel_image)
        result.log.append(LogEntry(t, "sent", reason, name, box, len(frame.wire)))
        result.sends += 1
        last_digest, last_image = frame.digest, frame.panel_image

    _write_report(out, cfg, result, start, sdk_type, screen_path, watched)
    return result


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
    return text if len(text) < 70 else text[:67] + "…"


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def _write_report(out: Path, cfg: dict, result: Result, start: datetime, sdk_type: int, screen: Path, watched: set[str]) -> None:
    rows = []
    for e in result.log:
        when = (start + timedelta(seconds=e.t)).strftime("%H:%M:%S")
        thumb = f'<a href="{e.frame_file}"><img src="{e.frame_file}" loading="lazy"></a>' if e.frame_file else ""
        box = ""
        if e.box:
            area = (e.box[2] - e.box[0]) * (e.box[3] - e.box[1])
            box = f"changed box {e.box} · {e.bytes} B"
            if e.kind == "sent" and area:
                box += f" · {area}px²"
        rows.append(
            f'<tr class="{e.kind}"><td>+{_fmt(e.t)}<br><small>{when}</small></td>'
            f"<td><b>{e.kind}</b></td><td>{html.escape(e.detail)}<br><small>{box}</small></td><td>{thumb}</td></tr>"
        )
    counts = result.counts()
    summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    page = f"""<!doctype html><meta charset="utf-8"><title>eInk simulation – {html.escape(out.name)}</title>
<style>
body{{font:14px system-ui,sans-serif;margin:24px;background:#f4f4f1;color:#222}}
table{{border-collapse:collapse;width:100%}} td{{padding:6px 10px;border-bottom:1px solid #ddd;vertical-align:top}}
img{{max-width:400px;image-rendering:pixelated;border:1px solid #999;background:#fff}}
tr.sent{{background:#fff}} tr.ignored,tr.unchanged{{color:#888}} tr.deferred{{color:#a60}} tr.error{{color:#b00}}
small{{color:#777}}
</style>
<h1>{html.escape(screen.name)} on SDK type {sdk_type}</h1>
<p>Start {start} · renders: {result.renders} · panel writes: {result.sends} · {summary}</p>
<p>Debounce {cfg.get('debounce', 5)} s · min gap {cfg.get('min_gap', 600)} s · watched entities: {html.escape(', '.join(sorted(watched)) or '—')}</p>
<table>{''.join(rows)}</table>"""
    (out / "index.html").write_text(page, encoding="utf-8")
