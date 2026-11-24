"""Demo: skewed T junction with corner arcs, ditch with flow arrows, culverts, signs.
Run: .venv/bin/python examples/demo_junction.py -> examples/junction.dxf + road_junction.png"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from cad_mcp import server  # noqa: E402
from cad_mcp.core import DocumentManager  # noqa: E402

server.dm = DocumentManager(workdir=HERE)
X = lambda t, o, **a: server.execute(t, o, a, None)  # noqa: E731

X("drawing", "new", units="m")
X("road", "alignment", name="FO", points=[[0, 0], [300, 0]])
X("road", "alignment", name="MEL", points=[[150, 0], [210, 90]])
X("road", "profile", name="FO", insert=[0, -150], terrain=[[0, 99.5], [300, 99.2]],
  vpis=[[0, 100], [150, 101.5], [300, 100.4]])
r = X("road", "intersection", main="FO", side="MEL", main_width=7, side_width=6, radius=[12, 9], extent=60)
for off in (-3.5, 3.5):
    X("road", "offset_lines", name="FO", offsets=[off], from_station=0, to_station=90)
    X("road", "offset_lines", name="FO", offsets=[off], from_station=210, to_station=300)
X("road", "marking", name="FO", offset=0, dash=3, gap=6)
d = X("road", "ditch", name="FO", side="right", interval=10)
c1 = X("road", "culvert", name="FO", station=0.5)
c2 = X("road", "culvert", name="FO", station=299.5)
X("road", "sign_at", name="MEL", station=12, type="stop", offset=-5, size=4)
X("road", "sign_at", name="FO", station=120, type="foutvonal", offset=-8, size=4)
q = X("road", "runoff", area_m2=150 * 12, runoff_coefficient=0.8, intensity_l_s_ha=180,
      capacity_m3_s=d["capacity_at_flattest"]["flow_m3_s"])
img = X("view", "png", width=1500, height=800, region=[[-10, -25], [310, 95]])
(HERE / "road_junction.png").write_bytes(img["_image"])
X("drawing", "save", path="junction.dxf")
print(json.dumps({"junction": r["type"], "corners": r["corners"], "ditch_low_points": d["low_points"],
                  "culverts": [c1["capacity_full"], c2["capacity_full"]], "runoff": q}, ensure_ascii=False, indent=1))
