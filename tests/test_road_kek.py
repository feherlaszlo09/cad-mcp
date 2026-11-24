import json
import math

import pytest

from tests.test_ops import ent
from tests.test_road import PIS


def _area(cad, h):
    return cad("query", "area", sel=[h])["total_area"]


def test_design_rules_template_and_check(cad):
    cad("drawing", "new", units="m")
    t = cad("road", "design_rules_template", path="szabaly.json", speeds=[60, 90])
    data = json.loads((cad.tmp / "szabaly.json").read_text(encoding="utf-8"))
    assert set(data["design_speeds"]) == {"60", "90"} and all(v is None for v in data["design_speeds"]["90"].values())
    assert t["written"].endswith("szabaly.json")
    cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60])
    cad("road", "superelevation", name="T1", e=[5, 7])
    cad("road", "profile", name="T1", insert=[0, -200], terrain=[[0, 100], [1483, 105]],
        vpis=[[0, 101.5], [600, 108], [1100, 109.5], [1483, 113]], radii=[10000, 8000])
    data["design_speeds"]["90"].update({"min_radius_m": 350, "min_clothoid_A_ratio": 1 / 3, "max_clothoid_A_ratio": 1,
                                        "min_tangent_between_curves_m": 200, "max_grade_pct": 1.0,
                                        "max_superelevation_pct": 6, "min_crest_radius_m": 9000})
    data["physics"].update({"reaction_time_s": 2.0, "deceleration_m_s2": 4.0, "eye_height_m": 1.0, "object_height_m": 0.2})
    (cad.tmp / "szabaly.json").write_text(json.dumps(data), encoding="utf-8")
    r = cad("road", "design_check", name="T1", design_speed=90, rules_file="szabaly.json")
    fails = {(c["check"], c["where"].split(",")[0]) for c in r["checks"] if c["status"] == "HIBA"}
    assert ("körívsugár", "2. ív") in fails and ("túlemelés", "2. ív") in fails
    assert any(c[0] == "egyenes két ív között" for c in fails) and any(c[0] == "hosszesés" for c in fails)
    assert r["failures"] == 4 and len(r["marked"]) == 8
    ssd = next(c for c in r["checks"] if c["check"] == "megállási látótávolság")
    assert ssd["value"] == pytest.approx(25 * 2 + 25 * 25 / 8, abs=0.01)
    crest = next(c for c in r["checks"] if c["check"] == "domború sugár a látótávolsághoz")
    assert crest["status"] == "OK"
    with pytest.raises(Exception, match="No rule values"):
        cad("road", "design_check", name="T1", design_speed=50)


def test_setout_list(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="E", points=[[1000, 2000], [1100, 2000]])
    cad("road", "profile", name="E", insert=[0, -50], terrain=[[0, 99], [100, 99]], vpis=[[0, 100], [100, 101]])
    r = cad("road", "setout_list", name="E", interval=50, offsets=[3.5, -3.5], path="kituzes.csv", table_at=[0, -100])
    row = next(x for x in r["rows"] if x["szelveny"] == "0+050.00" and x["eltolas"] == 3.5)
    assert row["Y"] == pytest.approx(1050) and row["X"] == pytest.approx(1996.5)
    assert row["Z"] == pytest.approx(100.5 - 3.5 * 0.025, abs=1e-3)  # list is rounded to 3 decimals
    assert r["points"] == 9 and (cad.tmp / "kituzes.csv").read_text(encoding="utf-8-sig").startswith("pont;szelveny")


def test_swept_path(cad):
    cad("drawing", "new", units="m")
    s = cad("road", "swept_path", vehicle="tehergepkocsi", path=[[0, 0], [20, 0]], step=0.1)
    assert s["envelope_area_m2"] == pytest.approx(30 * 2.55, rel=1e-3) and s["max_steering_angle_deg"] == pytest.approx(0, abs=1e-6)
    R = 12.0
    arc = [[R * math.sin(t), R - R * math.cos(t)] for t in [i * math.radians(0.25) for i in range(1081)]]
    turn = cad("road", "swept_path", vehicle="tehergepkocsi", path=[[-30, 0], [0, 0]] + arc[1:], step=0.1,
               max_steering_deg=40)
    assert turn["max_steering_angle_deg"] == pytest.approx(math.degrees(math.asin(6 / R)), abs=1.0)
    assert turn["steering_ok"]
    kerb = cad("draw", "line", start=[5, 3], end=[5, 30])["handles"][0]
    c = cad("road", "swept_path", vehicle="nyerges", path=[[-40, 0], [0, 0]] + arc[1:], check=[kerb])
    assert c["conflicts"] and c["conflicts"][0]["handle"] == kerb and c["conflicts"][0]["max_depth_m"] > 0
    custom = cad("road", "swept_path", vehicle={"wheelbase": 3, "front_overhang": 1, "rear_overhang": 1, "width": 2},
                 path=[[0, 0], [10, 0]])
    assert custom["envelope_area_m2"] == pytest.approx((10 + 5) * 2, rel=2e-2)


def test_markings_and_parking(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="U", points=[[0, 0], [100, 0]])
    z = cad("road", "crosswalk", name="U", station=50, width=4, from_offset=-3.5, to_offset=3.5, stripe=0.5, gap=0.5)
    assert z["stripes"] == 7 and all(_area(cad, h) == pytest.approx(2.0) for h in z["handles"])
    st = cad("road", "stop_line", name="U", station=40, from_offset=0, to_offset=3.5)
    assert _area(cad, st["handles"][0]) == pytest.approx(3.5 * 0.5)
    gw = cad("road", "stop_line", name="U", station=60, from_offset=-3.5, to_offset=0, kind="give_way")
    assert len(gw["handles"]) == 4
    a = cad("road", "pavement_arrow", name="U", station=20, offset=-1.75)["handles"][0]
    ext = cad("query", "extents", sel=[a])
    assert ext["max"][0] == pytest.approx(25) and ext["center"][1] == pytest.approx(-1.75)
    b = cad("road", "pavement_arrow", name="U", station=20, offset=1.75, reverse=True, kind="straight_left")["handles"]
    assert len(b) == 2 and cad("query", "extents", sel=b)["min"][0] == pytest.approx(15)
    h = cad("road", "hatched_area", boundary=[[0, 10], [10, 10], [10, 20], [0, 20]], spacing=1)
    assert h["stripes"] >= 10
    p90 = cad("road", "parking", path=[[0, 50], [50, 50]], angle=90)
    assert p90["stalls"] == 20 and len(p90["handles"]) == 21
    p45 = cad("road", "parking", path=[[0, 70], [50, 70]], angle=45)
    assert p45["stalls"] == int(50 / (2.5 / math.sin(math.radians(45))))
    p0 = cad("road", "parking", path=[[0, 90], [50, 90]], angle=0, side="right", numbering=True)
    assert p0["stalls"] == 10


def test_signals(cad):
    cad("drawing", "new", units="m")
    h = cad("road", "signal_head", insert=[0, 0], group="K1", kind="vehicle")
    assert ent(cad, h["handle"]).get_attrib_text("CSOPORT") == "K1"
    cad("road", "signal_head", insert=[5, 0], group="Gy1", kind="pedestrian")
    ig = cad("road", "intergreen", clearing_distance=20, entering_distance=10, clearing_speed_kmh=50,
             entering_speed_kmh=40, vehicle_length=6, amber_time=3)
    assert ig["exact_s"] == pytest.approx(3 + 26 / (50 / 3.6) - 10 / (40 / 3.6), abs=1e-3) and ig["intergreen_s"] == 4
    t = cad("road", "signal_timing", cycle=60, insert=[0, -20],
            groups=[{"name": "K1", "green_start": 0, "green_end": 25}, {"name": "K2", "green_start": 30, "green_end": 55}],
            intergreens=[{"from": "K1", "to": "K2", "required": 4}, {"from": "K2", "to": "K1", "required": 6}])
    assert [c["status"] for c in t["intergreen_checks"]] == ["OK", "HIBA"] and t["failures"] == 1


def test_design_check_with_official_eut_rules(cad):
    """Bundled rule set filled from e-UT 03.01.11 (KTSZ): 90 km/h külterületi út."""
    cad("drawing", "new", units="m")
    names = {x["name"] for x in cad("road", "design_rules_list")["rule_sets"]}
    assert {"eut_kulterulet", "eut_gyorsforgalmi", "eut_belterulet"} <= names
    pts = [[0, 0], [1000, 0], [2000, 600], [3000, 600], [4000, 610]]
    cad("road", "alignment", name="K", points=pts, radii=[300, 1200, 5000], spiral_lengths=[60, 0, 0])
    cad("road", "superelevation", name="K", e=[7, 0, 0])
    cad("road", "profile", name="K", insert=[0, -300], terrain=[[0, 100], [3990, 160]],
        vpis=[[0, 100], [1200, 160], [2500, 150], [3990, 165]], radii=[6000, 2000])
    r = cad("road", "design_check", name="K", design_speed=90, rules_file="eut_kulterulet")
    assert "e-UT 03.01.11" in r["rules_source"]
    fails = sorted((c["check"], c["where"].split(",")[0]) for c in r["checks"] if c["status"] == "HIBA")
    assert fails == sorted([
        ("körívsugár", "1. ív"),                                    # 300 < Rmin 340
        ("átmenetiív-paraméter", "1. ív"),                          # A = √(300·60) ≈ 134 < Pmin 165
        ("burkolatszél relatív hosszesése (felső)", "1. ív"),       # (2,5+7)·3,5/60 ≈ 0,55 > 0,5
        ("átmeneti ív szükséges", "2. ív"),                         # R 1200 < 3000, no clothoid
        ("sugár túlemelés nélkül", "2. ív"),                        # R 1200 < 2500 without superelevation
        ("ívhossz kis középponti szögnél", "3. ív"),                # 0,57° < 3°, ~50 m < 300 m
        ("egymást követő ívek sugararánya", "1-2. ív"),             # 1200/300 = 4 > 3
        ("egymást követő ívek sugararánya", "2-3. ív"),             # 5000/1200 > 3
        ("homorú sugár", "lekerekítés 2+500.00"),                   # 2000 < Rh,min 3000
    ])
    edge = next(c for c in r["checks"] if c["check"] == "burkolatszél relatív hosszesése (felső)")
    assert edge["value"] == pytest.approx(9.5 * 3.5 / 60, abs=1e-3)
    assert r["warnings"] == 1  # crest 6000 < 40000: no passing sight there
    ssd = next(c for c in r["checks"] if c["check"] == "megállási látótávolság")
    assert ssd["value"] == 140
    crest = next(c for c in r["checks"] if c["check"] == "domború sugár a látótávolsághoz")
    assert crest["status"] == "OK" and "5657" in crest["limit"]  # 140²/(2(√1+√0,1)²)
    with pytest.raises(Exception, match="not in"):
        cad("road", "design_check", name="K", design_speed=130, rules_file="eut_kulterulet")
    g = cad("road", "design_check", name="K", design_speed=130, rules_file="eut_gyorsforgalmi", mark=False)
    assert any(c["check"] == "középponti szög" and c["status"] == "HIBA" for c in g["checks"])
