"""eInk simulator CLI - no Home Assistant, no hardware.

    python devtools/sim.py serve    devtools/screens/weather.py --state devtools/states/demo.yaml
    python devtools/sim.py render   devtools/screens/weather.py --state devtools/states/demo.yaml --sdk 299
    python devtools/sim.py simulate devtools/scenarios/weather_day.yaml
    python devtools/sim.py decode   some_design.png --sdk 299        # any PNG through the real packer
    python devtools/sim.py pull-state --entities weather.home sun.sun --forecast weather.home --out devtools/states/live.yaml
    python devtools/sim.py types                                      # list panel types
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eink_sim import panel  # noqa: E402
from eink_sim.state import LiveSource, StateSource, load_state_file, parse_dt, snapshot_to_yaml  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def _sdk(args) -> int:
    from eink_sim.pipeline import screen_sdk_type

    return args.sdk or screen_sdk_type(args.screen)


def _source(args) -> StateSource:
    if getattr(args, "live", False):
        source = LiveSource()
        source.refresh()
        return source
    return load_state_file(args.state) if args.state else StateSource()


def cmd_render(args) -> int:
    from eink_sim.pipeline import render_frame

    source = _source(args)
    now = parse_dt(args.now) if args.now else None
    sdk = _sdk(args)
    frame = render_frame(args.screen, source, sdk, now, framed=args.framed, dither_mode=args.dither)
    if not frame.ok:
        print(frame.error, file=sys.stderr)
        return 1
    out = Path(args.out or OUT / Path(args.screen).stem)
    out.mkdir(parents=True, exist_ok=True)
    frame.drawn.save(out / "drawn.png")
    frame.quantized.save(out / "quantized.png")
    frame.panel_image.save(out / "panel.png")
    (out / "payload.bin").write_bytes(frame.wire)
    spec = panel.panel_spec(sdk)
    print(f"{spec.model}: {frame.drawn.width}x{frame.drawn.height}, {frame.render_ms:.0f} ms, {len(frame.wire)} bytes, digest {frame.digest}")
    print(f"entities read: {', '.join(sorted(frame.accessed)) or 'none'}")
    for warning in frame.warnings:
        print(f"WARNING: {warning}")
    print(f"wrote {out}")
    return 0


def cmd_decode(args) -> int:
    from PIL import Image

    from eink_sim import dither

    spec = panel.panel_spec(args.sdk)
    image = Image.open(args.image).convert("RGB")
    orientation = "portrait" if image.height > image.width else "landscape"
    if image.size != spec.canvas_size(orientation):
        print(f"note: image is {image.width}x{image.height}, panel canvas is {spec.canvas_size(orientation)}")
    if args.dither != "integration":
        image = dither.quantize(image, spec.colors, args.dither)
    decoded, _payload, wire = panel.roundtrip(args.sdk, image, orientation, args.transform, args.framed)
    out = Path(args.out or OUT / (Path(args.image).stem + "_panel.png"))
    out.parent.mkdir(parents=True, exist_ok=True)
    decoded.image.save(out)
    print(f"{spec.model}: {len(wire)} bytes; wrote {out}")
    for warning in decoded.warnings:
        print(f"WARNING: {warning}")
    return 0


def cmd_simulate(args) -> int:
    from eink_sim.simulate import run

    result = run(args.scenario, args.out)
    out = Path(args.out) if args.out else OUT / Path(args.scenario).stem
    print(f"renders: {result.renders}, panel writes: {result.sends}, {result.counts()}")
    print(f"report: {out / 'index.html'}")
    return 0


def cmd_serve(args) -> int:
    from eink_sim.server import serve

    serve(Path(args.screen), Path(args.state) if args.state else None, args.live, _sdk(args), args.port, args.framed)
    return 0


def cmd_pull_state(args) -> int:
    source = LiveSource()
    source.refresh()
    Path(args.out).write_text(
        snapshot_to_yaml(source, args.entities, args.forecast or [], datetime.now()), encoding="utf-8"
    )
    print(f"wrote {args.out}")
    return 0


def cmd_types(_args) -> int:
    for spec in panel.supported_types():
        print(f"{spec.sdk_type:>5}  {spec.width}x{spec.height}  {spec.model}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, screen=True):
        if screen:
            sp.add_argument("screen")
        sp.add_argument("--state", help="YAML/JSON state fixture")
        sp.add_argument("--live", action="store_true", help="read states from HA_URL/HA_TOKEN (read-only)")
        sp.add_argument("--sdk", type=int, default=None,
                        help="panel SDK type (default: the screen's SDK_TYPE, else 46 = 296x128 BWRY)")
        sp.add_argument("--framed", action="store_true", help="wrap in the vendor QuickLZ stream too")

    sp = sub.add_parser("render"); common(sp)
    sp.add_argument("--now"); sp.add_argument("--out"); sp.add_argument("--dither")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("serve"); common(sp)
    sp.add_argument("--port", type=int, default=8950)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("simulate"); sp.add_argument("scenario"); sp.add_argument("--out")
    sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("decode"); sp.add_argument("image")
    sp.add_argument("--sdk", type=int, default=46); sp.add_argument("--transform")
    sp.add_argument("--framed", action="store_true"); sp.add_argument("--out")
    sp.add_argument("--dither", default="ordered", help="ordered | floyd | none | integration (the integration's own threshold)")
    sp.set_defaults(func=cmd_decode)

    sp = sub.add_parser("pull-state"); sp.add_argument("--entities", nargs="+", required=True)
    sp.add_argument("--forecast", nargs="*"); sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_pull_state)

    sub.add_parser("types").set_defaults(func=cmd_types)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
