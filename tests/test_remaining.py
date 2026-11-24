"""DAT export, gas and district heating networks, electrical / street lighting and railway basics:
checked against round trips, hand calculations and closed-form solutions."""
import math

import ezdxf
import numpy as np
import pytest

from cad_mcp.ops_utility import swamee_jain, water_props
from tests.test_survey_utility import DAT

G_ANG = [i * 5 for i in range(19)]


def _areas(cad, layer="DAT_FOLDRESZLET"):
    doc = cad.dm().get().doc
    return sorted(round(cad("query", "area", sel=[p.dxf.handle])["total_area"], 2)
                  for p in doc.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'))


def test_dat_export_round_trip(cad):
    cad("drawing", "new", units="m")
    (cad.tmp / "be.dat").write_bytes(DAT.encode("cp1250"))
    cad("survey", "import_dat", path="be.dat")
    before = _areas(cad)
    e = cad("survey", "export_dat", path="ki.dat", obj_fels="BD01")
    assert e["parcels"] == 2 and e["boundary_lines"] == 7 and e["arcs"] == 1  # the shared boundary is written once
    raw = (cad.tmp / "ki.dat").read_bytes()
    assert raw.endswith(b"\x1a") and b"\r\nT_HATAR*\r\n" in raw and raw.startswith(b"T_CIMREK*\r\n")
    cad("drawing", "new", units="m")
    r = cad("survey", "import_dat", path="ki.dat")
    assert r["parcels"] == 2 and _areas(cad) == before
    texts = {t.dxf.text for t in cad.dm().get().doc.modelspace().query("TEXT")}
    assert {"0123/4", "0123/5"} <= texts
    # drawn parcels: an enclave becomes a hole, an arc over 180° is split, helyrajzi szám from hrsz={}
    cad("drawing", "new", units="m")
    outer = cad("draw", "polyline", points=[[650000, 240000], [650100, 240000], [650100, 240100], [650000, 240100]],
                closed=True)["handles"][0]
    hole = cad("draw", "polyline", points=[[650040, 240040], [650060, 240040], [650060, 240060], [650040, 240060]],
               closed=True)["handles"][0]
    circ = cad("draw", "polyline", points=[[650200, 240050], [650220, 240050]], bulges=[1.5, 0.4], closed=True)["handles"][0]
    circ_area = cad("query", "area", sel=[circ])["total_area"]
    e2 = cad("survey", "export_dat", path="ki2.dat", sel=[outer, hole, circ], hrsz={outer: "100", circ: "101"})
    assert e2["parcels"] == 2 and e2["boundaries"] == 3 and e2["arcs"] == 3
    text = (cad.tmp / "ki2.dat").read_bytes().decode("cp1250")
    assert "1*BD01" not in text and "*100***9600*" in text  # parcel 100 without the 20x20 enclave
    cad("drawing", "new", units="m")
    cad("survey", "import_dat", path="ki2.dat")
    assert _areas(cad) == [pytest.approx(circ_area, abs=0.02), 400.0, 10000.0]


def test_gas_networks(cad):
    cad("drawing", "new", units="m")
    low = cad("utility", "gas_network", name="G1", pressure_level="low", k_mm=0.01,
              sources=[{"name": "S", "point": [0, 0], "pressure": 25}],
              nodes=[{"name": "N", "point": [200, 0], "demand": 20}], pipes=[{"from": "S", "to": "N", "diameter": 0.05}])
    p_abs, T = 101325 + 2500, 283.15
    rho = 0.73 * p_abs / 101325 * 273.15 / T
    v = 20 / 3600 * (101325 / p_abs) * (T / 273.15) / (math.pi * 0.05 ** 2 / 4)
    f = float(swamee_jain(np.array([v * 0.05 * rho / 1.1e-5]), np.array([0.01e-3 / 0.05]))[0])
    assert low["nodes"][0]["pressure_mbar"] == pytest.approx(25 - f * 200 / 0.05 * rho * v * v / 2 / 100, abs=1e-3)
    med = cad("utility", "gas_network", name="G2", pressure_level="medium", k_mm=0.01, min_pressure=2.95,
              sources=[{"name": "S", "point": [0, 0], "pressure": 3}],
              nodes=[{"name": "N", "point": [2000, 0], "demand": 500}], pipes=[{"from": "S", "to": "N", "diameter": 0.1}])
    Qn = 500 / 3600
    f = float(swamee_jain(np.array([4 * 0.73 * Qn / (math.pi * 0.1 * 1.1e-5)]), np.array([0.01e-3 / 0.1]))[0])
    K = 16 * 0.73 * 101325 * 283.15 / (math.pi ** 2 * 273.15) * f * 2000 / 0.1 ** 5
    p2 = math.sqrt((3e5 + 101325) ** 2 - K * Qn ** 2)
    assert med["nodes"][0]["pressure_bar"] == pytest.approx((p2 - 101325) / 1e5, abs=1e-4) and med["failures"] == ["N"]
    loop = cad("utility", "gas_network", name="G3", pressure_level="low", k_mm=0.01,
               sources=[{"name": "S", "point": [0, 0], "pressure": 25, "elevation": 100}],
               nodes=[{"name": "A", "point": [100, 0], "demand": 10, "elevation": 100},
                      {"name": "B", "point": [100, 100], "demand": 8, "elevation": 130},
                      {"name": "C", "point": [0, 100], "demand": 6, "elevation": 100}],
               pipes=[{"from": "S", "to": "A", "diameter": 0.063}, {"from": "A", "to": "B", "diameter": 0.04},
                      {"from": "B", "to": "C", "diameter": 0.04}, {"from": "C", "to": "S", "diameter": 0.063}])
    p = {n["node"]: n["pressure_mbar"] for n in loop["nodes"]}
    assert loop["continuity_error_m3_h"] < 1e-6 and p["B"] > p["A"]  # natural gas is lighter than air
    with pytest.raises(Exception, match="k_mm"):
        cad("utility", "gas_network", name="G4", sources=[{"name": "S", "point": [0, 0], "pressure": 25}],
            nodes=[{"name": "N", "point": [1, 0], "demand": 1}], pipes=[{"from": "S", "to": "N", "diameter": 0.05}])


def test_heat_network(cad):
    cad("drawing", "new", units="m")
    h = cad("utility", "heat_network", name="H1", plant={"name": "K", "point": [0, 0]}, supply_temp_c=90,
            return_temp_c=60, k_mm=0.05, consumer_dp_kpa=50, max_velocity=0.82,
            consumers=[{"name": "F1", "point": [100, 0], "load_kw": 300}, {"name": "F2", "point": [100, 80], "load_kw": 200}],
            pipes=[{"from": "K", "to": "F1", "diameter": 0.08}, {"from": "F1", "to": "F2", "diameter": 0.05}])
    rho, mu = water_props(75)
    assert rho == pytest.approx(974.8, abs=0.3)

    def dp(load, D, L):
        Q = load / (4.19 * 30) / rho
        v = Q / (math.pi * D ** 2 / 4)
        f = float(swamee_jain(np.array([v * D * rho / mu]), np.array([0.05e-3 / D]))[0])
        return f * L / D * rho * v * v / 2

    need = 2 * (dp(500, 0.08, 100) + dp(200, 0.05, 80)) + 50000
    assert h["plant_differential_kpa"] == pytest.approx(need / 1000, abs=1e-3)
    assert h["total_flow_m3_h"] == pytest.approx(500 / (4.19 * 30) / rho * 3600, abs=1e-3)
    assert h["failures"] == ["F1-F2"]  # 0.831 m/s > 0.82


def _ldt(values, isym=1, mc=36, dc=10):
    head = ["Test", "1", str(isym), str(mc), str(dc), "19", "5", "R1", "Proba lampa", "L1", "proba.ldt", "2026", "500",
            "200", "100", "400", "150", "0", "0", "0", "0", "100", "100", "1", "0", "1", "1", "LED", "10000", "3000K", "80",
            "80"] + ["0.5"] * 10 + [str(i * dc) for i in range(mc)] + [str(x) for x in G_ANG]
    return "\r\n".join(head + [f"{v:.4f}" for v in values]) + "\r\n"


def test_street_lighting(cad):
    cad("drawing", "new", units="m")
    cos_tab = [300 * math.cos(math.radians(g)) for g in G_ANG]
    (cad.tmp / "l.ldt").write_text(_ldt(cos_tab), encoding="latin-1")
    ies = ["IESNA:LM-63-2002", "[LUMINAIRE] Proba IES", "TILT=NONE", "1 10000 1 19 1 1 2 0.5 0.2 0.1", "1 1 80",
           " ".join(str(x) for x in G_ANG), "0", " ".join(f"{3000 * math.cos(math.radians(x)):.4f}" for x in G_ANG)]
    (cad.tmp / "l.ies").write_text("\n".join(ies) + "\n")
    ph = cad("electric", "photometry", path="l.ldt")
    assert ph["flux_lm"] == 10000 and ph["max_cd"] == pytest.approx(3000) and ph["efficacy_lm_w"] == 125
    cad("road", "alignment", name="UT", points=[[0, 0], [200, 0]])
    lay = cad("electric", "lighting_layout", name="KV", alignment="UT", spacing=30, arrangement="right", offset=1.0,
              road_half_width=3.5, height=8, overhang=1.5, from_station=0, to_station=90)
    assert lay["count"] == 4 and lay["poles"][1]["x"] == pytest.approx(30) and lay["cable_length_m"]["R"] == pytest.approx(90)
    r = cad("electric", "illuminance", layout="KV", luminaire="l.ldt", maintenance_factor=0.8,
            requirements={"Eav_min": 10, "U0_min": 0.4})
    # closed form for I = I0·cos γ: E = I0·h²/r⁴ from each luminaire (at y = -3.0)
    xs, ys = np.arange(0.5, 30, 1.0), np.arange(-3.0, 3.5, 1.0)
    E = sum(3000 * 64 / (((xs[None, :] - lx) ** 2 + (ys[:, None] + 3.0) ** 2 + 64) ** 2) for lx in (0, 30, 60, 90))
    assert r["Eav_lx"] == pytest.approx(0.8 * E.mean(), rel=2e-3) and r["Emin_lx"] == pytest.approx(0.8 * E.min(), rel=2e-3)
    assert [c["ok"] for c in r["checks"]] == [True, False] and r["handles"]
    assert cad("electric", "illuminance", layout="KV", luminaire="l.ies", maintenance_factor=0.8)["Eav_lx"] == r["Eav_lx"]
    # light only towards C0..C180 (the road side, C90): behind the poles it is dark
    half = []
    for c in range(36):
        half += [300.0 if c * 10 <= 180 else 0.0] * 19
    (cad.tmp / "h.ldt").write_text(_ldt(half, isym=0), encoding="latin-1")
    road = cad("electric", "illuminance", layout="KV", luminaire="h.ldt", maintenance_factor=1, left=3.5, right=3.5)
    behind = cad("electric", "illuminance", layout="KV", luminaire="h.ldt", maintenance_factor=1, left=-6, right=10)
    assert road["Eav_lx"] > 5 * behind["Eav_lx"]
    vd = cad("electric", "voltage_drop", layout="KV", side="R", lamp_power_w=80, cross_section_mm2=10, feeder_length=20,
             limit_pct=0.1)
    i_tot = 4 * 80 / 230
    first = 2 * i_tot * 20 * 0.017241 / 10
    assert vd["nodes"][0]["du_v"] == pytest.approx(first, abs=1e-3) and not vd["check"]["ok"]
    three = cad("electric", "voltage_drop", cross_section_mm2=16, material="Al", phases=3, voltage=400, cos_phi=0.9,
                x_ohm_per_km=0.08, conductor_temp_c=70,
                nodes=[{"name": "A", "length": 100, "load_a": 20}, {"name": "B", "length": 50, "load_a": 10}])
    r_al = 0.028264 * (1 + 0.00403 * 50) / 16
    du = math.sqrt(3) * (30 * 100 + 10 * 50) * (r_al * 0.9 + 0.08e-3 * math.sqrt(1 - 0.81))
    assert three["nodes"][-1]["du_v"] == pytest.approx(du, abs=1e-3)
    sl = cad("electric", "single_line", insert=[0, -50], bus_label="0,4 kV",
             supply={"elements": ["transzformator", "megszakito"], "label": "20/0,4 kV"},
             feeders=[{"label": "KV1", "elements": ["megszakito"], "load": "lampa", "text": "NAYY-J 4x16"},
                      {"label": "F2", "elements": ["biztosito", "fogyasztasmero"], "load": "dugalj"}])
    assert sl["feeders"] == 2 and len(sl["handles"]) > 10
    for k in ("kapcsolo", "motor", "generator", "foldeles", "elosztoszekreny", "tulfeszultseg_vedo", "kabelvegelzaro",
              "aramvalto"):
        cad("electric", "symbol", kind=k, insert=[0, 100], label=k)
    cad("drawing", "save", path="vill.dxf")
    assert not ezdxf.readfile(cad.tmp / "vill.dxf").audit().has_errors


def test_railway(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="V", points=[[0, 0], [500, 0], [900, 300]], radii=[600], spiral_lengths=[80])
    c = cad("rail", "cant", alignment="V", v_max=120, v_min=60, design_speed=100, max_cant_mm=150, max_deficiency_mm=100,
            max_excess_mm=110, ramp_ratio=400)["curves"][0]
    assert c["equilibrium_cant_vmax_mm"] == pytest.approx(1500 * (120 / 3.6) ** 2 / (9.81 * 600), abs=0.05)
    assert c["cant_mm"] == 150 and c["deficiency_mm"] == pytest.approx(133.2, abs=0.05) and "hiány" in c["status"]
    assert c["min_ramp_length_m"] == 60 and c["excess_mm"] == pytest.approx(150 - 70.8, abs=0.05)
    tr = cad("rail", "track", alignment="V", from_station=0, to_station=50)
    assert tr["sleepers"] == 83 and tr["rail_offset_m"] == pytest.approx((1435 + 72) / 2000)
    t = cad("rail", "turnout", start=[0, -50], direction_deg=0, hand="right", turnout="54-190-1:9")
    alpha = math.atan(1 / 9)
    T = 190 * math.tan(alpha / 2)
    assert t["rail_system"] == 54 and t["tangent_T"] == pytest.approx(T, abs=1e-4)
    end = t["points"]["end_diverging"]
    assert end == [pytest.approx(T + 2 * T * math.cos(alpha), abs=1e-3), pytest.approx(-50 - 2 * T * math.sin(alpha), abs=1e-3)]
    lt = cad("rail", "turnout", start=[0, 0], direction_deg=90, hand="left", radius=300, ratio=11, a=20, b=25)
    assert lt["points"]["end_diverging"][0] < 0 and lt["note"] is None
    with pytest.raises(Exception, match="tangent length"):
        cad("rail", "turnout", start=[0, 0], direction_deg=0, radius=300, ratio=11, a=5, b=25)
    xs = cad("rail", "cross_section", insert=[0, -100], cant_mm=100)
    assert xs["cant_rotation_deg"] == pytest.approx(math.degrees(math.atan2(0.1, 1.507)), abs=1e-4)
