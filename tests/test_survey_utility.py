"""Geodesy (survey) and utilities (utility): every result is checked against geometry built from
known 'true' coordinates or against hand calculations."""
import math

import pytest

from cad_mcp.ops_survey import bearing, fmt_dms, parse_angle
from tests.test_ops import ent

A, R, P1, P2, B, E = (650000.0, 240000.0), (649500.0, 240800.0), (650300.0, 240100.0), (650650.0, 239950.0), \
    (651000.0, 240200.0), (651400.0, 240900.0)

DAT = (
    "T_CIMREK*\r\nproba*Proba DAT*1.0*Teszt*Teszt*Teszt*Teszt*20261122*cad-mcp*1*\r\n"
    "T_PONT*\r\n1*240000.00*650000.00**0*0*\r\n2*240040.00*650000.00**0*0*\r\n3*240040.00*650050.00**0*0*\r\n"
    "4*240000.00*650050.00**0*0*\r\n5*240040.00*650100.00**0*0*\r\n6*240000.00*650100.00**0*0*\r\n"
    "7*240020.00*650020.00**0*0*\r\n8*240021.00*650072.00**0*0*\r\n"
    "T_OSSZEKOT_IV*\r\n1*240020.00*650075.00*32.0156*\r\n"
    "T_HATARVONAL*\r\n1*1*1*2*0**\r\n1*2*2*3*0**\r\n2*1*3*4*0**\r\n3*1*4*1*0**\r\n4*1*3*5*1*1*\r\n5*1*5*6*0**\r\n"
    "5*2*6*4*0**\r\n"
    "T_HATAR*\r\n1*1*1*+*\r\n1*2*2*+*\r\n1*3*3*+*\r\n2*1*2*-*\r\n2*2*4*+*\r\n2*3*5*+*\r\n"
    "T_FELULET*\r\n1*1*1*+*\r\n2*1*2*+*\r\n"
    "T_OBJ_ATTRBD*\r\n1*BD01*1*0123/4*1*1*2000*\r\n2*BD01*2*0123/5*1*1*2418*\r\n"
    "9*BD01*1*0123/9*1*1*2000*****************20200101*\r\n"
    "T_FELIRAT*\r\n1*Kert utca*8*90.0*1**T_OBJ_ATTRBD*1**\r\n\x1a"
)


def test_angles_and_inverse(cad):
    assert parse_angle("123-45-36") == pytest.approx(123.76)
    assert parse_angle("123°45'36\"") == pytest.approx(123.76) and parse_angle("100g") == pytest.approx(90)
    assert fmt_dms(123.76) == "123-45-36.0"
    cad("drawing", "new", units="m")
    cad("survey", "points", action="add", points={"A": [*A, 100.0], "R": [*R, 101.0]})
    inv = cad("survey", "inverse", a="A", b="R")
    assert inv["distance"] == pytest.approx(math.dist(A, R), abs=1e-4) and inv["dH"] == pytest.approx(1.0)
    assert inv["bearing_deg"] == pytest.approx(bearing(A, R)) and 270 < inv["bearing_deg"] < 360
    lst = cad("survey", "points", action="import", text="K1;650010,5;240020,25;99,1\nK2;650011;240021;99,2",
              order="name,y,x,h")
    assert lst["added"] == 2 and cad("survey", "points", names=["K1"])["points"][0]["y"] == 650010.5


def test_traverse_polar_intersections(cad):
    cad("drawing", "new", units="m")
    cad("survey", "points", action="add", points={"A": [*A, 100.0], "R": [*R], "B": [*B], "E": [*E]})
    chain = [R, A, P1, P2, B, E]
    angs = [(bearing(chain[i], chain[i + 1]) - bearing(chain[i], chain[i - 1])) % 360 for i in range(1, 5)]
    dists = [math.dist(chain[i], chain[i + 1]) for i in range(1, 4)]
    exact = cad("survey", "traverse", start="A", start_ref="R", angles=[fmt_dms(a, 3) for a in angs], distances=dists,
                names=["P1", "P2"], end="B", end_ref="E")
    assert abs(exact["angular_misclosure_sec"]) < 0.01 and abs(exact["linear_misclosure"]) < 1e-4
    assert exact["points"][1] == {"name": "P2", "y": pytest.approx(P2[0], abs=1e-3), "x": pytest.approx(P2[1], abs=1e-3)}
    noisy = cad("survey", "traverse", start="A", start_ref="R", angles=[angs[0] + 5 / 3600, angs[1] - 3 / 3600,
                                                                           angs[2] + 4 / 3600, angs[3] + 2 / 3600],
                distances=[d + 0.01 for d in dists], names=["Q1", "Q2"], end="B", end_ref="E",
                max_angle_misclosure_sec=5, max_linear_misclosure=0.05)
    assert noisy["angular_misclosure_sec"] == pytest.approx(8.0, abs=0.05)
    assert [c["ok"] for c in noisy["checks"]] == [False, True]
    assert math.dist((noisy["points"][0]["y"], noisy["points"][0]["x"]), P1) < 0.01
    # right-hand angles give the same result
    right = cad("survey", "traverse", start="A", start_ref="R", angles=[360 - a for a in angs], distances=dists,
                names=["W1", "W2"], end="B", end_ref="E", angle_side="right", add=False, draw=False)
    assert right["points"][0]["y"] == pytest.approx(P1[0], abs=1e-3)
    opn = cad("survey", "traverse", start="A", start_ref="R", angles=angs[:2], distances=dists[:2], names=["O1", "O2"],
              draw=False)
    assert "warning" in opn
    # polar with orientation on two known points, trigonometric height
    S, z, T1 = (650200.0, 240300.0), 37.123, (650260.0, 240350.0)
    pol = cad("survey", "polar", station=[*S, 101.0], instrument_height=1.5,
              orientation=[{"point": "A", "direction": (bearing(S, A) - z) % 360},
                           {"point": "B", "direction": (bearing(S, B) - z) % 360}],
              observations=[{"name": "T1", "direction": (bearing(S, T1) - z) % 360, "distance": math.dist(S, T1),
                             "zenith": 88.0, "target_height": 1.3}])
    assert pol["orientation_angle_deg"] == pytest.approx(z) and all(abs(r["residual_sec"]) < 0.05 for r in pol["orientation_residuals"])
    p = pol["points"][0]
    assert (p["y"], p["x"]) == (pytest.approx(T1[0], abs=1e-4), pytest.approx(T1[1], abs=1e-4))
    assert p["h"] == pytest.approx(101 + 1.5 + math.dist(S, T1) / math.tan(math.radians(88)) - 1.3, abs=1e-4)
    slope = cad("survey", "polar", station=[*S, 101.0], orientation_angle=z, distance_type="slope",
                observations=[{"name": "T2", "direction": (bearing(S, T1) - z) % 360,
                               "distance": math.dist(S, T1) / math.sin(math.radians(88)), "zenith": 88.0}], draw=False)
    assert slope["points"][0]["y"] == pytest.approx(T1[0], abs=1e-4)
    P = (650500.0, 240600.0)
    f1 = cad("survey", "intersection", kind="forward", a="A", b="B", bearing_a=bearing(A, P), bearing_b=bearing(B, P), name="F1")
    f2 = cad("survey", "intersection", kind="forward", a="A", b="B", side="left", name="F2",
             angle_a=(bearing(A, B) - bearing(A, P)) % 360, angle_b=(bearing(B, P) - bearing(B, A)) % 360)
    f3 = cad("survey", "intersection", kind="arc", a="A", b="B", distance_a=math.dist(A, P), distance_b=math.dist(B, P),
             side="left", name="F3")
    h1 = cad("survey", "intersection", kind="resection", known=["A", "B", "R", "E"], name="H1",
             directions=[(bearing(P, q) - 12.5 + (0.5 / 3600 if i == 1 else 0)) % 360 for i, q in enumerate((A, B, R, E))])
    for r in (f1, f2, f3, h1):
        assert (r["point"]["y"], r["point"]["x"]) == (pytest.approx(P[0], abs=2e-3), pytest.approx(P[1], abs=2e-3))
    assert h1["rms_sec"] > 0 and len(h1["residuals_sec"]) == 4
    assert "H1" in [x["name"] for x in cad("survey", "points")["points"]]


def test_levelling_and_transform(cad):
    lev = cad("survey", "levelling", start_height=100.0, end_height=100.5,
              setups=[{"back": 1.5, "fore": 1.2, "point": "F1", "distance": 40},
                      {"back": 1.4, "fore": 1.198, "point": "F2", "distance": 60, "side": [{"point": "O1", "reading": 0.9}]}],
              max_misclosure_mm=1)
    assert lev["misclosure_mm"] == pytest.approx(2.0) and not lev["check"]["ok"]
    assert [p["h"] for p in lev["points"]] == [pytest.approx(100.2992), pytest.approx(100.5)]
    assert lev["side_points"][0]["h"] == pytest.approx(101.7 - 0.9 - 0.0014)
    src = [[0, 0], [100, 0], [100, 100], [0, 100]]
    ang, sc, t = math.radians(10), 1.0002, (650000, 240000)
    tgt = [[t[0] + sc * (math.cos(ang) * x - math.sin(ang) * y), t[1] + sc * (math.sin(ang) * x + math.cos(ang) * y)]
           for x, y in src]
    h = cad("survey", "transform", common=[{"source": s, "target": g} for s, g in zip(src, tgt)], points=[[50, 50]])
    assert h["parameters"]["scale"] == pytest.approx(1.0002) and h["parameters"]["rotation_deg"] == pytest.approx(10)
    assert h["mean_error"] < 1e-6 and h["points"][0] == [pytest.approx(tgt[0][0] + (tgt[2][0] - tgt[0][0]) / 2, abs=1e-4),
                                                         pytest.approx(tgt[0][1] + (tgt[2][1] - tgt[0][1]) / 2, abs=1e-4)]
    ln = cad("draw", "line", start=[0, 0], end=[100, 0])["handles"][0]
    af = cad("survey", "transform", kind="affine", common=[{"source": s, "target": g} for s, g in zip(src, tgt)], sel=[ln])
    assert af["transformed"] == 1 and ent(cad, ln).dxf.end.isclose((tgt[1][0], tgt[1][1], 0), abs_tol=1e-4)


def test_dat_import_and_land_take(cad):
    cad("drawing", "new", units="m")
    (cad.tmp / "proba.dat").write_bytes(DAT.encode("cp1250"))
    r = cad("survey", "import_dat", path="proba.dat")
    assert r["parcels"] == 2 and r["drawn_by_object_table"] == {"BD": 2, "FELIRAT": 1}  # the expired record is skipped
    doc = cad.dm().get().doc
    polys = doc.modelspace().query('LWPOLYLINE[layer=="DAT_FOLDRESZLET"]')
    areas = sorted(round(cad("query", "area", sel=[p.dxf.handle])["total_area"], 1) for p in polys)
    seg = 0.5 * 32.0156 ** 2 * (2 * math.atan(25 / 20) - math.sin(2 * math.atan(25 / 20)))
    assert areas == [2000.0, pytest.approx(2000 + seg, abs=0.2)]  # the arc boundary (T_OSSZEKOT_IV) is exact
    texts = {t.dxf.text for t in doc.modelspace().query("TEXT")}
    assert {"0123/4", "0123/5", "Kert utca"} <= texts
    cad("road", "alignment", name="UT", points=[[649990, 240010], [650110, 240010]])
    lt = cad("survey", "land_take", alignment="UT", left=5, right=5, path="kisajatitas.csv", table_at=[650000, 239980])
    rows = {x["hrsz"]: x for x in lt["rows"]}
    assert rows["0123/4"]["taken_m2"] == 500 and rows["0123/4"]["remaining_m2"] == 1500
    assert rows["0123/5"]["taken_m2"] == 500 and rows["0123/5"]["share_pct"] == pytest.approx(500 / (2000 + seg) * 100, abs=0.01)
    assert len(rows["0123/4"]["new_boundary_points"]) == 4 and lt["total_taken_m2"] == 1000
    assert (cad.tmp / "kisajatitas.csv").read_text(encoding="utf-8-sig").startswith("hrsz;")
    box = cad("draw", "polyline", points=[[650040, 240030], [650060, 240030], [650060, 240050], [650040, 240050]],
              closed=True)["handles"][0]
    lt2 = cad("survey", "land_take", boundary=[box])
    r2 = 32.0156 ** 2
    F = lambda y: y / 2 * math.sqrt(r2 - y * y) + r2 / 2 * math.asin(y / math.sqrt(r2))  # noqa: E731
    cap = F(-15) - F(-25) - 20 * 10  # the part of the box above X 240040 under the arc
    assert {x["hrsz"]: x["taken_m2"] for x in lt2["rows"]} == {"0123/4": 100, "0123/5": round(100 + cap)}


def test_asbuilt_check(cad):
    cad("drawing", "new", units="m")
    cad("terrain", "surface", name="TERV", points=[[0, 0, 100], [50, 0, 100.5], [50, 50, 101], [0, 50, 100.5]])
    s = cad("survey", "asbuilt_check", mode="surface", surface="TERV", tolerance_z=0.02,
            points=[[25, 10, 100.36], [10, 40, 100.6]], report="megval.csv")
    dz = [r["dZ"] for r in s["rows"]]
    assert dz[0] == pytest.approx(0.01, abs=1e-6) and dz[1] == pytest.approx(0.1, abs=1e-6)
    assert s["outside_tolerance"] == 1 and (cad.tmp / "megval.csv").is_file()
    cad("road", "alignment", name="E", points=[[0, 100], [100, 100]])
    cad("road", "profile", name="E", insert=[0, -50], terrain=[[0, 99], [100, 99]], vpis=[[0, 100], [100, 101]])
    r = cad("survey", "asbuilt_check", mode="road", alignment="E", template=[{"width": 3.5, "slope": -2.5}],
            points=[[50, 98.5, 100.5 - 1.5 * 0.025 + 0.004]], tolerance_z=0.01)
    row = r["rows"][0]
    assert row["station"] == pytest.approx(50) and row["offset"] == pytest.approx(-1.5) and row["dZ"] == pytest.approx(0.004)
    ln = cad("draw", "line", start=[0, 0], end=[100, 0])["handles"][0]
    li = cad("survey", "asbuilt_check", mode="line", lines=[ln], points=[[30, 0.03, 0], [60, -0.01, 0]], tolerance_xy=0.02)
    assert [row["ok"] for row in li["rows"]] == [False, True]


def test_sewer_network_and_profile(cad):
    cad("drawing", "new", units="m")
    r = cad("utility", "sewer", name="SZ1", min_cover=1.5, min_slope_permille=5, inflows={"A1": 10, "B1": 5},
            min_velocity=0.6,
            manholes=[{"name": "A1", "point": [0, 0], "rim": 105}, {"name": "A2", "point": [50, 0], "rim": 104.6},
                      {"name": "A3", "point": [90, 0], "rim": 104.0}, {"name": "B1", "point": [50, 30], "rim": 105.2}],
            pipes=[{"from": "A1", "to": "A2", "diameter": 0.3, "material": "KG-PVC"},
                   {"from": "A2", "to": "A3", "diameter": 0.3, "material": "KG-PVC"},
                   {"from": "B1", "to": "A2", "diameter": 0.2, "material": "KG-PVC"}])
    p = {x["pipe"]: x for x in r["pipes"]}
    # inverts follow the terrain with 1.5 m cover: 105-1.5-0.3 = 103.2 -> 104.6-1.8 = 102.8 (8 ‰ > 5 ‰)
    assert (p["A1-A2"]["invert_from"], p["A1-A2"]["invert_to"], p["A1-A2"]["slope_permille"]) == (103.2, 102.8, 8.0)
    full = 1 / 0.013 * 0.075 ** (2 / 3) * math.sqrt(0.008) * math.pi * 0.3 ** 2 / 4
    assert p["A1-A2"]["Q_full_l_s"] == pytest.approx(full * 1000, abs=0.01)
    assert p["A2-A3"]["Q_l_s"] == 15.0 and 0 < p["A2-A3"]["h_D"] < 0.5 and r["outfalls"] == ["A3"] and not r["failures"]
    cb = cad("utility", "sewer", name="SZ2", method="colebrook", k_mm=1.5, draw=False,
             manholes=[{"name": "X", "point": [0, 0], "rim": 100, "invert": 98}, {"name": "Y", "point": [100, 0], "rim": 99.5}],
             pipes=[{"from": "X", "to": "Y", "diameter": 0.4, "slope_permille": 3}], inflows={"X": 200}, max_fill_ratio=0.7)
    assert cb["pipes"][0]["invert_to"] == pytest.approx(97.7) and "HIBA" in cb["pipes"][0]["status"]
    with pytest.raises(Exception, match="min_cover"):
        cad("utility", "sewer", name="Z", manholes=[{"name": "a", "point": [0, 0], "rim": 1}, {"name": "b", "point": [5, 0], "rim": 1}],
            pipes=[{"from": "a", "to": "b", "diameter": 0.3}])
    pr = cad("utility", "sewer_profile", name="SZ1", start="A1", insert=[0, -60], text_height=1)
    assert pr["path"] == ["A1", "A2", "A3"] and pr["length"] == 90 and pr["band"][1]["inverts"] == [102.8, 102.8]


def test_water_network(cad):
    cad("drawing", "new", units="m")
    one = cad("utility", "water_network", name="V1", sources=[{"name": "R", "point": [0, 100], "head": 150}],
              nodes=[{"name": "N1", "point": [1000, 100], "elevation": 100, "demand": 10}],
              pipes=[{"from": "R", "to": "N1", "diameter": 0.15, "length": 1000, "C": 120}])
    hw = 10.67 * 1000 * 0.01 ** 1.852 / (120 ** 1.852 * 0.15 ** 4.87)
    assert one["nodes"][0]["head"] == pytest.approx(150 - hw, abs=1e-3)
    nodes = [{"name": "J1", "point": [0, 0], "elevation": 100, "demand": 5},
             {"name": "J2", "point": [200, 0], "elevation": 101, "demand": 8},
             {"name": "J3", "point": [200, 200], "elevation": 102, "demand": 6},
             {"name": "J4", "point": [0, 200], "elevation": 100, "demand": 4}]
    pipes = [{"from": "R", "to": "J1", "diameter": 0.2, "C": 110}, {"from": "J1", "to": "J2", "diameter": 0.15, "C": 110},
             {"from": "J2", "to": "J3", "diameter": 0.1, "C": 110}, {"from": "J3", "to": "J4", "diameter": 0.1, "C": 110},
             {"from": "J4", "to": "J1", "diameter": 0.15, "C": 110}]
    loop = cad("utility", "water_network", name="V2", sources=[{"name": "R", "point": [-300, 0], "head": 145}],
               nodes=nodes, pipes=pipes, min_pressure=42)
    q = {x["pipe"]: x["Q_l_s"] for x in loop["pipes"]}
    assert q["R-J1"] == pytest.approx(23) and loop["continuity_error_l_s"] < 1e-6
    # loop energy balance: the head losses around J1-J2-J3-J4 sum to zero
    hl = {x["pipe"]: math.copysign(x["headloss_m"], x["Q_l_s"]) for x in loop["pipes"]}
    assert hl["J1-J2"] + hl["J2-J3"] + hl["J3-J4"] + hl["J4-J1"] == pytest.approx(0, abs=1e-6)
    assert set(loop["failures"]) == {"J2", "J3"}
    dw = cad("utility", "water_network", name="V3", method="darcy", sources=[{"name": "R", "point": [-300, 0], "head": 145}],
             nodes=nodes, pipes=[{**p, "k_mm": 0.1} for p in pipes], draw=False)
    assert dw["continuity_error_l_s"] < 1e-6 and all(30 < n["pressure_m"] < 46 for n in dw["nodes"])


def test_utility_lines_clearance_cross_section(cad):
    cad("drawing", "new", units="m")
    g = cad("utility", "line", points=[[0, 20], [100, 20]], kind="gaz", size=0.11, elevations=[103.0, 103.0], material="KPE")
    v = cad("utility", "line", points=[[0, 20.5], [100, 20.6]], kind="viz", status="tervezett", size=0.11,
            elevations=[102.5, 102.5], material="KPE")
    cad("utility", "line", points=[[40, 0], [40, 40]], kind="tavkozles", size=0.1, elevations=[102.9, 102.9])
    cad("utility", "line", points=[[0, 60], [100, 60]], kind="villany", status="megszuntetendo", size=0.05)
    assert ent(cad, g["handle"]).dxf.layer == "KOZMU_GAZ_MEGLEVO" and ent(cad, v["handle"]).dxf.layer == "KOZMU_VIZ_TERVEZETT"
    assert cad("utility", "clearance_rules_template", path="kozmu.json")["pairs"] == 36
    c = cad("utility", "clearance_check", rules={"default": {"horizontal_m": 0.5, "vertical_m": 0.2},
                                                 "pairs": {"gaz|viz": {"horizontal_m": 1.0, "vertical_m": 0.3}}})
    kinds = sorted((x["type"], tuple(sorted(x["kinds"]))) for x in c["conflicts"] if x["status"] == "HIBA")
    assert kinds == [("keresztezés", ("gaz", "tavkozles")), ("párhuzamos", ("gaz", "viz"))]
    par = next(x for x in c["conflicts"] if x["type"] == "párhuzamos")
    assert par["min_clear_m"] == pytest.approx(0.5 - 0.11, abs=1e-3)
    cad("road", "alignment", name="UT", points=[[-10, 10], [110, 10]])
    cs = cad("utility", "cross_section", alignment="UT", station=30, insert=[0, -200], center_elevation=104,
             half_width=60)
    found = {u["kind"]: u for u in cs["utilities"]}
    assert found["gaz"]["offset_right"] == pytest.approx(-10) and found["gaz"]["axis_elevation"] == 103.0
    assert set(found) == {"gaz", "viz", "villany"} and found["villany"]["axis_elevation"] is None
