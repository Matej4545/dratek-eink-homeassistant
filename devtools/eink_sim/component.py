"""Load the integration's own pure-Python modules without Home Assistant.

The harness deliberately uses the real ``render.pack_bwr_image`` and
``quicklz.frame_payload`` from ``custom_components/dratek_eink`` so that what it
shows is what the integration would put on the wire - not a re-implementation.
Same loading trick the repo's unit tests use (a stub package whose __path__
points at the component directory), so relative imports inside it resolve.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPONENT = REPO / "custom_components" / "dratek_eink"
PACKAGE = "dratek_sim_component"


def load(name: str) -> types.ModuleType:
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMPONENT)]
        sys.modules[PACKAGE] = package
    module_name = f"{PACKAGE}.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, COMPONENT / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load integration module {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


render = load("render")
quicklz = load("quicklz")
const = load("const")

FONT_DIR = COMPONENT / "frontend" / "fonts"
MDI_PATHS_JS = REPO / "tests" / "vendor" / "mdi" / "paths.js"
