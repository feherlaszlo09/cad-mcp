"""Build the AutoCAD acceptance test pack: one drawing per topic, to open in real AutoCAD and tick
off the checklist in TESZTLISTA.md.

    python scripts/make_test_pack.py                 # -> teszt_csomag/*.dxf (+ .dwg with --dwg)
    python scripts/make_test_pack.py --out D:/teszt --dwg

--dwg also writes DWG copies with the ODA File Converter (needs it installed, and on macOS a
desktop session). Every drawing is also exported to PDF/PNG for side-by-side comparison."""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cad_mcp import server  # noqa: E402
from cad_mcp.core import DocumentManager  # noqa: E402

DAT = (
    "T_CIMREK*\r\nproba*Proba DAT*1.0*Teszt*Teszt*Teszt*Teszt*20261122*cad-mcp*1*\r\n"
    "T_PONT*\r\n1*240000.00*650000.00**0*0*\r\n2*240040.00*650000.00**0*0*\r\n3*240040.00*650050.00**0*0*\r\n"
    "4*240000.00*650050.00**0*0*\r\n5*240040.00*650100.00**0*0*\r\n6*240000.00*650100.00**0*0*\r\n"
    "T_OSSZEKOT_IV*\r\n1*240020.00*650075.00*32.0156*\r\n"
    "T_HATARVONAL*\r\n1*1*1*2*0**\r\n1*2*2*3*0**\r\n2*1*3*4*0**\r\n3*1*4*1*0**\r\n4*1*3*5*1*1*\r\n5*1*5*6*0**\r\n"
    "5*2*6*4*0**\r\n"
    "T_HATAR*\r\n1*1*1*+*\r\n1*2*2*+*\r\n1*3*3*+*\r\n2*1*2*-*\r\n2*2*4*+*\r\n2*3*5*+*\r\n"
    "T_FELULET*\r\n1*1*1*+*\r\n2*1*2*+*\r\n"
    "T_OBJ_ATTRBD*\r\n1*BD01*1*0123/4*1*1*2000*\r\n2*BD01*2*0123/5*1*1*2418*\r\n\x1a"
)


def X(tool, op, **args):
    return server.execute(tool, op, args, None)


def alap_2d():
    X("drawing", "new", units="mm")
    X("layer", "create_many", layers=[{"name": "FAL", "color": 1, "lineweight": 0.5},
                                      {"name": "NYILAS", "color": 3, "linetype": "DASHED"},
                                      {"name": "MERET", "color": 2}, {"name": "SZOVEG", "color": 7}])
    X("draw", "rectangle", corner1=[0, 0], corner2=[6000, 4000], layer="FAL")
    X("draw", "polyline", points=[[7000, 0], [9000, 0], [9000, 2000], [7000, 2000]], bulges=[0, 0.5, 0, 0], layer="FAL")
    c = X("draw", "circle", center=[3000, 2000], radius=600, layer="FAL")["handles"][0]
    X("draw", "ellipse", center=[1500, 3000], major_axis=[800, 0], ratio=0.5, layer="FAL")
    X("draw", "spline", fit_points=[[0, 5000], [2000, 6000], [4000, 5000], [6000, 6000]], layer="NYILAS")
    X("draw", "hatch", boundary=[[[200, 200], [2200, 200], [2200, 1800], [200, 1800]],
                                 [[700, 700], [1700, 700], [1700, 1300], [700, 1300]]], pattern="ANSI31", scale=20)
    X("draw", "gradient", boundary=[[4000, 200], [5800, 200], [5800, 1800], [4000, 1800]], color1="red",
      color2="yellow", rotation=30)
    X("annotate", "text", text="Árvíztűrő tükörfúrógép – ÁRVÍZTŰRŐ TÜKÖRFÚRÓGÉP", insert=[0, 7000], height=250,
      layer="SZOVEG")
    X("annotate", "mtext", text="Többsoros szöveg\nmásodik sor: ő ű Ő Ű", insert=[0, 8000], width=5000, layer="SZOVEG")
    X("annotate", "dim_linear", p1=[0, 0], p2=[6000, 0], location=[0, -800], layer="MERET")
    X("annotate", "dim_aligned", p1=[7000, 0], p2=[9000, 2000], distance=500, layer="MERET")
    X("annotate", "dim_angular", center=[0, 0], p1=[1000, 0], p2=[0, 1000], location=[700, 700], layer="MERET")
    X("annotate", "dim_radius", handle=c, layer="MERET")
    X("annotate", "dim_diameter", center=[3000, 2000], radius=600, layer="MERET")
    X("annotate", "dim_ordinate", feature=[6000, 4000], leader_end=[6500, 4800], axis="x", layer="MERET")
    big = X("draw", "arc", center=[11000, -9000], radius=12000, start_angle=75, end_angle=105, layer="FAL")["handles"][0]
    X("annotate", "dim_jogged", handle=big, center_override=[11500, 1000], angle=90, text_height=200)
    X("annotate", "leader", points=[[3000, 2000], [4500, 3500]], text="Megtört vezérvonal (MLEADER)")
    X("annotate", "table", insert=[10000, 8000], rows=[["Tétel", "Mennyiség"], ["Fal", "24 m"], ["Ajtó", "3 db"]],
      col_widths=[2500, 2000], row_height=500, text_height=200)
    X("block", "define", name="AKNA", entities=[{"tool": "draw", "operation": "circle",
                                                 "args": {"center": [0, 0], "radius": 300}}])
    X("block", "attdef", block="AKNA", tag="SZAM", insert=[400, 0], default="1", height=150)
    X("block", "insert", name="AKNA", insert=[8000, 3000], attributes={"SZAM": "A-17"})
    X("layer", "state", action="save", name="Minden látszik")
    X("layer", "modify", name="NYILAS", on=False)
    X("layer", "state", action="save", name="Nyílások nélkül", description="teszt")
    X("layer", "modify", name="NYILAS", on=True)
    X("layer", "filter", action="create", name="Falak és méretek", criteria={"name": "*A*"})
    X("layer", "filter", action="create", name="Csoport: szöveg", layers=["SZOVEG"])
    X("drawing", "named_view", name="Alaprajz", region=[[0, 0], [9000, 4000]])


def harom_d():
    X("drawing", "new", units="mm")
    a = X("draw3d", "box", origin=[0, 0, 0], size=[2000, 2000, 2000], solid=True)["handles"]
    b = X("draw3d", "cylinder", base_center=[1000, 1000, -500], radius=500, height=3000)["handles"]
    X("draw3d", "boolean", kind="subtract", sel_a=a, sel_b=b)
    X("draw3d", "wedge", origin=[3000, 0, 0], size=[2000, 1000, 1500], solid=True)
    X("draw3d", "sweep", path=[[6000, 0, 0], [6000, 3000, 1000]],
      profile=[[-200, -200], [200, -200], [200, 200], [-200, 200]])
    X("draw3d", "loft", profiles=[[[8000, 0, 0], [9000, 0, 0], [9000, 1000, 0], [8000, 1000, 0]],
                                  [[8200, 200, 1500], [8800, 200, 1500], [8800, 800, 1500], [8200, 800, 1500]]])
    box = X("draw3d", "box", origin=[0, 4000, 0], size=[1500, 1000, 800])["handles"]
    X("draw3d", "flatshot", sel=box, direction=[1, -1, 1], hidden=True, block="NEZET", origin=[0, 8000])


def layout_nyomtatas():
    alap_2d()
    X("layout", "create", name="A3 lap", paper="A3", landscape=True)
    X("layout", "page_setup", name="A3 lap", paper="A3", landscape=True, plot_style="monochrome.ctb")
    X("layout", "add_viewport", layout="A3 lap", center=[210, 148], size=[380, 250], view_center=[4500, 3500],
      scale=0.02)


def utterv():
    X("drawing", "new", units="m")
    pis = [[0, 0], [500, 0], [900, 300], [1400, 300]]
    al = X("road", "alignment", name="T1", points=pis, radii=[400, 300], spiral_lengths=[80, 60])
    X("road", "superelevation", name="T1", e=[5.0, 6.0])
    X("road", "stationing", name="T1", interval=100, minor_interval=20)
    X("road", "offset_lines", name="T1", offsets=[-3.5, 3.5], layer="BURKOLATSZEL")
    X("road", "marking", name="T1", offset=0, dash=3, gap=6, width=0.12)
    X("road", "marking", name="T1", offset=-3.25, solid=True, width=0.12)
    X("road", "marking", name="T1", offset=3.25, solid=True, width=0.12)
    X("road", "curve_table", name="T1", insert=[0, 450], text_height=3)
    L = float(al["length_m"])
    grid = [[x, y, 100 + 0.008 * x + 2 * math.sin(y / 60)] for x in range(-100, 1501, 50) for y in range(-150, 451, 50)]
    X("terrain", "surface", name="TEREP", points=grid)
    X("terrain", "contours", name="TEREP", interval=1, major_every=5, text_height=2)
    X("layer", "modify", name="TEREP_TEREP", on=False)
    X("road", "profile", name="T1", insert=[0, -400], surface="TEREP",
      vpis=[[0, 101.5], [600, 108], [1100, 109.5], [L, 113]], radii=[10000, 8000])
    pav = X("road", "pavement_design", mf_million=2.5, base="rba")["pavement"]
    X("road", "cross_sections", name="T1", insert=[0, -700], interval=200, columns=4, spacing=[80, 30],
      surface="TEREP", pavement=pav, ditch={"depth": 0.6, "bottom_width": 0.5, "inner_slope": 1.5})
    X("road", "design_check", name="T1", design_speed=70, rules_file="eut_kulterulet")
    for st, code, off in ((150, "A-001", -8), (180, "C-033-70", -8), (700, "B-001", 8), (1200, "D-001", 8)):
        X("road", "kresz_sign_at", name="T1", station=st, code=code, offset=off, size=3)
    X("road", "pavement_design", mf_million=2.5, base="rba", insert=[1500, 0])


def csomopont():
    X("drawing", "new", units="m")
    X("road", "alignment", name="FO", points=[[-100, 0], [100, 0]])
    X("road", "alignment", name="MEL", points=[[0, 0], [0, 80]])
    X("road", "intersection", main="FO", side="MEL", main_width=7, side_width=6, radius=10, extent=40)
    X("road", "crosswalk", name="FO", station=60, width=4, from_offset=-3.5, to_offset=3.5)
    X("road", "stop_line", name="FO", station=55, from_offset=-3.5, to_offset=0)
    X("road", "parking", path=[[-90, 20], [-40, 20]], angle=90)
    X("road", "signal_head", insert=[-10, -8], group="K1", kind="vehicle")
    X("road", "roundabout", center=[300, 0], outer_radius=18, ring_width=6,
      approaches=[{"angle": 0, "width": 7}, {"angle": 90, "width": 7}, {"angle": 200, "width": 8}],
      corner_radius=12, apron_width=1.5)
    X("road", "swept_path", vehicle="nyerges", path=[[-60, -2], [-10, -2]] + [
        [12 * math.sin(t), -2 + 12 - 12 * math.cos(t)] for t in [i * math.radians(2) for i in range(1, 46)]])


def kozmu():
    X("drawing", "new", units="m")
    X("utility", "sewer", name="SZ1", min_cover=1.5, min_slope_permille=5, inflows={"A1": 10, "B1": 5},
      manholes=[{"name": "A1", "point": [0, 0], "rim": 105}, {"name": "A2", "point": [50, 0], "rim": 104.6},
                {"name": "A3", "point": [90, 0], "rim": 104.0}, {"name": "B1", "point": [50, 30], "rim": 105.2}],
      pipes=[{"from": "A1", "to": "A2", "diameter": 0.3, "material": "KG-PVC"},
             {"from": "A2", "to": "A3", "diameter": 0.3, "material": "KG-PVC"},
             {"from": "B1", "to": "A2", "diameter": 0.2, "material": "KG-PVC"}])
    X("utility", "sewer_profile", name="SZ1", start="A1", insert=[0, -60], text_height=1)
    X("utility", "water_network", name="V1", sources=[{"name": "R", "point": [150, 0], "head": 145}],
      nodes=[{"name": "J1", "point": [200, 0], "elevation": 100, "demand": 5},
             {"name": "J2", "point": [300, 0], "elevation": 101, "demand": 8}],
      pipes=[{"from": "R", "to": "J1", "diameter": 0.2, "C": 110}, {"from": "J1", "to": "J2", "diameter": 0.15, "C": 110}])
    X("utility", "gas_network", name="G1", k_mm=0.01, sources=[{"name": "GS", "point": [150, 60], "pressure": 25}],
      nodes=[{"name": "GN", "point": [300, 60], "demand": 20}], pipes=[{"from": "GS", "to": "GN", "diameter": 0.05}])
    X("utility", "line", points=[[0, 20], [100, 20]], kind="gaz", size=0.11, elevations=[103.0, 103.0], material="KPE")
    X("utility", "line", points=[[0, 20.5], [100, 20.6]], kind="viz", status="tervezett", size=0.11,
      elevations=[102.5, 102.5], material="KPE")
    X("utility", "clearance_check", rules={"default": {"horizontal_m": 0.5, "vertical_m": 0.2}})


def geodezia():
    X("drawing", "new", units="m")
    (OUT / "proba_alaptérkép.dat").write_bytes(DAT.encode("cp1250"))
    X("survey", "import_dat", path="proba_alaptérkép.dat")
    X("road", "alignment", name="UT", points=[[649990, 240010], [650110, 240010]])
    X("survey", "land_take", alignment="UT", left=5, right=5, table_at=[650000, 239980], path="kisajatitas.csv")
    X("survey", "export_dat", path="export.dat", obj_fels="BD01")
    X("survey", "points", action="add", points={"A": [650000.0, 240100.0, 100.0], "R": [649950.0, 240150.0]})
    X("survey", "polar", station="A", orientation_angle=0,
      observations=[{"name": "P1", "direction": 45, "distance": 30}, {"name": "P2", "direction": 90, "distance": 40}])


def villamos():
    X("drawing", "new", units="m")
    X("road", "alignment", name="UT", points=[[0, 0], [200, 0]])
    X("road", "offset_lines", name="UT", offsets=[-3.5, 3.5])
    X("electric", "lighting_layout", name="KV", alignment="UT", spacing=30, arrangement="staggered", height=8,
      overhang=1.5, from_station=0, to_station=180)
    X("electric", "single_line", insert=[0, -60], bus_label="0,4 kV gyűjtősín",
      supply={"elements": ["transzformator", "megszakito"], "label": "20/0,4 kV"},
      feeders=[{"label": "KV1", "elements": ["megszakito"], "load": "lampa", "text": "NAYY-J 4x16"},
               {"label": "F2", "elements": ["biztosito", "fogyasztasmero"], "load": "dugalj"}])


def vasut():
    X("drawing", "new", units="m")
    X("road", "alignment", name="V", points=[[0, 0], [500, 0], [900, 300]], radii=[600], spiral_lengths=[80])
    X("rail", "track", alignment="V", from_station=0, to_station=120)
    X("rail", "turnout", start=[0, -50], direction_deg=0, hand="right", turnout="54-190-1:9")
    X("rail", "cross_section", insert=[0, -100], cant_mm=100)


def xref():
    X("drawing", "new", units="m")
    X("draw", "rectangle", corner1=[0, 0], corner2=[100, 60], layer="ALAPTERKEP")
    X("annotate", "text", text="Külső hivatkozás (XREF)", insert=[10, 30], height=4)
    X("drawing", "save", path=str(OUT / "10_xref_alap.dxf"))
    X("drawing", "new", units="m")
    X("block", "attach_xref", path=str(OUT / "10_xref_alap.dxf"), name="ALAP", relative_to=str(OUT))
    ref = X("block", "insert", name="ALAP", insert=[0, 0])["handle"]
    X("block", "xclip", handle=ref, boundary=[[0, 0], [70, 0], [70, 40], [0, 40]])


def geo():
    X("drawing", "new", units="m")
    X("geo", "gps_points", points=[[47.4979, 19.0402], [47.5316, 21.6273]], labels=["Budapest", "Debrecen"])
    X("geo", "set_location")


PACK = [("01_alap_2d", alap_2d), ("02_3d", harom_d), ("03_layout_nyomtatas", layout_nyomtatas), ("04_utterv", utterv),
        ("05_csomopont", csomopont), ("06_kozmu", kozmu), ("07_geodezia", geodezia), ("08_villamos", villamos),
        ("09_vasut", vasut), ("10_xref_fo", xref), ("11_geo", geo)]


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "teszt_csomag"))
    ap.add_argument("--dwg", action="store_true", help="also write DWG copies (ODA File Converter)")
    a = ap.parse_args()
    OUT = Path(a.out).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    server.dm = DocumentManager(workdir=OUT)
    failed = []
    for name, fn in PACK:
        try:
            fn()
            X("drawing", "save", path=str(OUT / f"{name}.dxf"))
            X("view", "export", path=str(OUT / f"{name}.png"), dpi=96)
            if a.dwg:
                X("drawing", "save", path=str(OUT / f"{name}.dwg"))
            print("ok  ", name)
        except Exception as exc:  # keep going, report at the end
            failed.append(name)
            print("HIBA", name, exc)
            traceback.print_exc()
    print(f"{len(PACK) - len(failed)}/{len(PACK)} rajz kész: {OUT}")
    return 1 if failed else 0


OUT = ROOT / "teszt_csomag"

if __name__ == "__main__":
    sys.exit(main())
