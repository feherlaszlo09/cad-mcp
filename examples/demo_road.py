"""Demo road plan: terrain from survey points, contours, alignment with clothoids,
stationing, pavement edges, markings, curve table, long profile, cross sections.
Run: .venv/bin/python examples/demo_road.py  -> examples/road.dxf + road_*.png + road.pdf"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from cad_mcp import server  # noqa: E402
from cad_mcp.core import DocumentManager  # noqa: E402

server.dm = DocumentManager(workdir=HERE)
X = lambda tool, op, **a: server.execute(tool, op, a, None)  # noqa: E731

# synthetic survey (EOV-like local coordinates, meters)
rows = ["pont;x;y;z;kod"]
i = 0
for x in range(-100, 1501, 20):
    for y in range(-150, 451, 20):
        z = 100 + 0.01 * x + 2 * math.sin(y / 60) + 1.5 * math.cos(x / 140)
        rows.append(f"P{i};{x};{y};{z:.3f};TEREP")
        i += 1
(HERE / "road_points.csv").write_text("\n".join(rows), encoding="utf-8")

X("drawing", "new", name="Ut", units="m")
X("terrain", "import_points", path="road_points.csv", label=False)
X("terrain", "surface", name="TEREP", sel={"type": "POINT"})
X("layer", "modify", name="TEREP_TEREP", on=False)
X("terrain", "contours", name="TEREP", interval=0.5, major_every=4, text_height=2)
X("layer", "modify", name="GEODEZIA_PONTOK", on=False)
al = X("road", "alignment", name="T1", points=[[0, 0], [500, 0], [900, 300], [1400, 300]],
       radii=[400, 300], spiral_lengths=[80, 60], start_station=0)
X("road", "superelevation", name="T1", e=[5.0, 6.0], normal=2.5)
X("road", "stationing", name="T1", interval=100, minor_interval=20, tick=4, text_height=3)
X("road", "sign_at", name="T1", station=250, type="veszely", text="!", size=6, offset=-8)
X("road", "sign_at", name="T1", station=300, type="sebesseg", text="70", size=6, offset=-8)
X("road", "sign_at", name="T1", station=1200, type="elozni_tilos", text="TILOS", size=6, offset=8, facing="backward")
X("road", "offset_lines", name="T1", offsets=[-3.5, 3.5], layer="BURKOLATSZEL")
X("road", "offset_lines", name="T1", offsets=[-5.0, 5.0], layer="PADKA", color=8)
X("road", "marking", name="T1", offset=0, dash=3, gap=6, width=0.12)
X("road", "marking", name="T1", offset=-3.25, solid=True, width=0.12)
X("road", "marking", name="T1", offset=3.25, solid=True, width=0.12)
X("road", "curve_table", name="T1", insert=[0, 450], text_height=3)
pr = X("road", "profile", name="T1", insert=[0, -400], surface="TEREP",
       vpis=[[0, 101.5], [600, 108], [1100, 109.5], [al_end := float(al["length_m"]), 113]],
       radii=[10000, 8000], grid_station=100, grid_elev=1, band_interval=100, text_height=3)
PAV = [{"name": "AC-11 kopóréteg", "thickness": 0.04}, {"name": "AC-22 kötőréteg", "thickness": 0.06},
       {"name": "CKt", "thickness": 0.20}, {"name": "Homokos kavics", "thickness": 0.25}]
xs = X("road", "cross_sections", name="T1", insert=[0, -700], interval=100, surface="TEREP", columns=5,
       spacing=[80, 30], pavement=PAV, ditch={"depth": 0.6, "bottom_width": 0.5, "inner_slope": 1.5})
X("road", "cross_section", name="T1", station=500, insert=[600, -1000], surface="TEREP", pavement=PAV,
  ditch={"depth": 0.6, "bottom_width": 0.5, "inner_slope": 1.5}, text_height=0.25)
print(json.dumps({"alignment_m": al["length_m"], "curves": al["curves"], "profile_curves": pr["curves"],
                  "grades": pr["grades_percent"], "cut_m3": xs["volume_cut_m3"], "fill_m3": xs["volume_fill_m3"],
                  "pavement_m3": xs["pavement_m3"]},
                 ensure_ascii=False, indent=1))
img = X("view", "png", width=1600, height=1000, region=[[-120, -170], [1520, 470]])
(HERE / "road_plan.png").write_bytes(img["_image"])
img = X("view", "png", width=1400, height=900, region=[[380, -60], [720, 160]])
(HERE / "road_detail.png").write_bytes(img["_image"])
img = X("view", "png", width=1600, height=700, region=[[-150, -470], [1520, -170]])
(HERE / "road_profile.png").write_bytes(img["_image"])
img = X("view", "png", width=1600, height=700, region=[[-50, -800], [400, -640]])
(HERE / "road_sections.png").write_bytes(img["_image"])
img = X("view", "png", width=1400, height=700, region=[[578, -1006], [622, -990]])
(HERE / "road_section_detail.png").write_bytes(img["_image"])
X("drawing", "save", path="road.dxf")
print("saved road.dxf")
