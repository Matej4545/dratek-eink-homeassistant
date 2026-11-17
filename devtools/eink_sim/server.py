"""Live preview: edit a screen or state file, the browser shows the new panel image.

Re-renders when the screen file (or any .py next to it), the state file, the
panel type or dither mode changes, and once a minute so clocks move. In live
mode it re-reads Home Assistant once a minute.
"""

from __future__ import annotations

import io
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import panel
from .pipeline import Frame, render_frame, resolve_screen_path
from .state import LiveSource, StateSource, load_state_file

PAGE = (Path(__file__).parent / "preview.html").read_text(encoding="utf-8")


class Preview:
    def __init__(self, screen, state: Path | None, live: bool, sdk_type: int, framed: bool,
                 options: dict | None = None) -> None:
        self.screen = resolve_screen_path(screen)
        self.options = dict(options or {})
        self.state = state.resolve() if state else None
        self.live = LiveSource() if live else None
        self.sdk_type = sdk_type
        self.dither: str | None = None
        self.framed = framed
        self.frame = Frame()
        self.version = 0
        self._key: tuple | None = None
        self._live_at = 0.0
        self._lock = threading.Lock()

    def _inputs_key(self, source: StateSource) -> tuple:
        mtimes = tuple(sorted((p.name, p.stat().st_mtime) for p in self.screen.parent.glob("*.py")))
        state_m = self.state.stat().st_mtime if self.state and self.state.exists() else 0
        minute = None if source.now else int(time.time() // 60)
        return (mtimes, state_m, self.sdk_type, self.dither, minute, self._live_at)

    def current(self) -> Frame:
        with self._lock:
            if self.live:
                if time.time() - self._live_at > 60:
                    self.live.refresh()
                    self._live_at = time.time()
                source: StateSource = self.live
            elif self.state:
                try:
                    source = load_state_file(self.state)
                except Exception as exc:  # broken YAML while typing
                    self.frame = Frame(error=f"State file error: {exc}")
                    return self.frame
            else:
                source = StateSource()
            key = self._inputs_key(source)
            if key != self._key:
                self._key = key
                now = source.now or datetime.now().replace(microsecond=0)
                self.frame = render_frame(
                    self.screen, source, self.sdk_type, now, options=self.options, framed=self.framed,
                    dither_mode=self.dither,
                )
                self.version += 1
            return self.frame


def serve(screen, state: Path | None, live: bool, sdk_type: int, port: int, framed: bool,
          options: dict | None = None) -> None:
    preview = Preview(screen, state, live, sdk_type, framed, options)
    types = [
        {"sdk_type": s.sdk_type, "label": f"{s.sdk_type} · {s.model}", "size": [s.width, s.height]}
        for s in panel.supported_types()
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # quiet
            pass

        def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/frame":
                f = preview.current()
                spec = panel.panel_spec(preview.sdk_type)
                info = {
                    "version": preview.version,
                    "screen": preview.screen.name,
                    "state": "live Home Assistant" if preview.live else (preview.state.name if preview.state else "—"),
                    "sdk_type": preview.sdk_type,
                    "model": spec.model,
                    "size": list(f.drawn.size) if f.drawn else None,
                    "dither": preview.dither or "screen default",
                    "error": f.error,
                    "warnings": f.warnings,
                    "accessed": sorted(f.accessed),
                    "render_ms": round(f.render_ms, 1),
                    "bytes": len(f.wire),
                    "digest": f.digest,
                    "types": types,
                }
                return self._send(json.dumps(info).encode(), "application/json")
            if path.startswith("/img/"):
                which = path[5:].removesuffix(".png")
                f = preview.current()
                image = {"drawn": f.drawn, "quantized": f.quantized, "panel": f.panel_image}.get(which)
                if image is None:
                    return self._send(b"", "image/png", 404)
                buf = io.BytesIO()
                image.save(buf, "PNG")
                return self._send(buf.getvalue(), "image/png")
            self._send(b"not found", "text/plain", 404)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != "/api/settings":
                return self._send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if "sdk_type" in body:
                preview.sdk_type = int(body["sdk_type"])
            if "dither" in body:
                preview.dither = body["dither"] or None
            self._send(b"{}", "application/json")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"eInk preview on http://127.0.0.1:{port}/  (screen: {screen}, Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
