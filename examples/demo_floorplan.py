"""Demo: draws a small floor plan through the same API the MCP tools use.
Run:  .venv/bin/python examples/demo_floorplan.py   -> examples/demo.dxf, demo.png, demo.pdf"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from cad_mcp import server  # noqa: E402
from cad_mcp.core import DocumentManager  # noqa: E402

server.dm = DocumentManager(workdir=HERE)
X = server.execute

X("drawing", "new", {"name": "Demo", "units": "mm"}, None)
X("layer", "create_many", {"layers": [
    {"name": "FAL", "color": 7, "lineweight": 0.5},
    {"name": "AJTO", "color": 3},
    {"name": "MERET", "color": 4},
    {"name": "SRAFF", "color": 8},
    {"name": "BUTOR", "color": 5},
    {"name": "SZOVEG", "color": 2},
]}, None)

steps = [
    # outer wall: 8 x 6 m, 30 cm thick
    {"tool": "draw", "operation": "rectangle", "args": {"corner1": [0, 0], "corner2": [8000, 6000], "layer": "FAL"}},
    {"tool": "edit", "operation": "offset", "args": {"handle": "$0.handles[0]", "distance": 300, "side_point": [4000, 3000]}},
    # wall poche between outer and inner outline
    {"tool": "draw", "operation": "hatch", "args": {"boundary": [[[0, 0], [8000, 0], [8000, 6000], [0, 6000]], [[300, 300], [7700, 300], [7700, 5700], [300, 5700]]], "pattern": "ANSI31", "scale": 20, "layer": "SRAFF"}},
    # inner partition wall at x = 5000
    {"tool": "draw", "operation": "rectangle", "args": {"corner1": [5000, 300], "corner2": [5120, 5700], "layer": "FAL"}},
    {"tool": "draw", "operation": "hatch", "args": {"boundary": [[5000, 300], [5120, 300], [5120, 5700], [5000, 5700]], "pattern": "SOLID", "layer": "SRAFF"}},
    # door: leaf + swing arc
    {"tool": "draw", "operation": "line", "args": {"start": [5120, 2000], "end": [5920, 2000], "layer": "AJTO"}},
    {"tool": "draw", "operation": "arc", "args": {"center": [5120, 2000], "radius": 800, "start_angle": 0, "end_angle": 90, "layer": "AJTO"}},
    # table block with attribute
    {"tool": "block", "operation": "define", "args": {"name": "ASZTAL", "base_point": [0, 0], "entities": [
        {"tool": "draw", "operation": "rectangle", "args": {"corner1": [-600, -400], "corner2": [600, 400], "fillet": 60}},
        {"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 80}},
    ]}},
    {"tool": "block", "operation": "insert", "args": {"name": "ASZTAL", "insert": [2500, 3000], "layer": "BUTOR"}},
    {"tool": "block", "operation": "insert", "args": {"name": "ASZTAL", "insert": [6500, 4200], "rotation": 90, "scale": 0.7, "layer": "BUTOR"}},
    # dimensions
    {"tool": "annotate", "operation": "dim_linear", "args": {"p1": [0, 0], "p2": [8000, 0], "location": [0, -700], "text_height": 180, "arrow_size": 120, "layer": "MERET"}},
    {"tool": "annotate", "operation": "dim_linear", "args": {"p1": [8000, 0], "p2": [8000, 6000], "location": [8700, 0], "angle": 90, "text_height": 180, "arrow_size": 120, "layer": "MERET"}},
    {"tool": "annotate", "operation": "dim_linear", "args": {"p1": [300, 6000], "p2": [5000, 6000], "location": [0, 6600], "text_height": 180, "arrow_size": 120, "layer": "MERET"}},
    # room labels
    {"tool": "annotate", "operation": "text", "args": {"text": "NAPPALI", "insert": [2650, 1200], "height": 250, "align": "middle_center", "layer": "SZOVEG"}},
    {"tool": "annotate", "operation": "text", "args": {"text": "HALO", "insert": [6400, 1200], "height": 250, "align": "middle_center", "layer": "SZOVEG"}},
    {"tool": "annotate", "operation": "leader", "args": {"points": [[2500, 3000], [3400, 4300], [3900, 4300]], "text": "Asztal 1200x800", "char_height": 150, "layer": "SZOVEG"}},
]
res = json.loads(server.batch(steps))
areas = X("query", "area", {"points": [[300, 300], [5000, 300], [5000, 5700], [300, 5700]]}, None)
print("steps:", res["steps"], "living room area m2:", round(areas["area"] / 1e6, 2))
png = X("view", "png", {"width": 1400, "height": 1000}, None)
(HERE / "demo.png").write_bytes(png["_image"])
X("view", "export", {"path": "demo.pdf", "paper": "A3", "scale": 0.02}, None)
print(X("drawing", "save", {"path": "demo.dxf"}, None))
print(json.dumps(X("drawing", "info", None, None), ensure_ascii=False)[:400])
