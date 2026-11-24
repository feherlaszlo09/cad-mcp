import math

import pytest

from tests.test_ops import ent


def _arcs(cad, handles):
    return [ent(cad, h) for h in handles if ent(cad, h).dxftype() == "ARC"]


def test_t_intersection_exact(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="FO", points=[[0, 0], [200, 0]])
    cad("road", "alignment", name="MEL", points=[[100, 0], [100, 80]])
    r = cad("road", "intersection", main="FO", side="MEL", main_width=7, side_width=6, radius=10, extent=40)
    assert r["type"] == "T" and len(r["corners"]) == 2
    centres = sorted((round(a.dxf.center.x, 6), round(a.dxf.center.y, 6)) for a in _arcs(cad, r["handles"]))
    assert centres == [(87, 13.5), (113, 13.5)]
    for a in _arcs(cad, r["handles"]):
        ends = sorted([(round(a.start_point.x, 6), round(a.start_point.y, 6)), (round(a.end_point.x, 6), round(a.end_point.y, 6))])
        assert ends in ([(87, 3.5), (97, 13.5)], [(103, 13.5), (113, 3.5)])
    edges = [ent(cad, h) for h in r["handles"] if ent(cad, h).dxftype() == "LWPOLYLINE"]
    left = sorted([sorted(p[0] for p in e.get_points("xy")) for e in edges
                   if all(abs(p[1] - 3.5) < 1e-9 for p in e.get_points("xy"))])
    assert [(round(x[0], 6), round(x[-1], 6)) for x in left] == [(60, 87), (113, 140)]
    right = [e for e in edges if all(abs(p[1] + 3.5) < 1e-9 for p in e.get_points("xy"))]
    assert len(right) == 1  # the far side of the main road stays continuous
    side_edges = [e for e in edges if all(abs(p[0] - 97) < 1e-9 or abs(p[0] - 103) < 1e-9 for p in e.get_points("xy"))]
    assert len(side_edges) == 2 and all(min(p[1] for p in e.get_points("xy")) == pytest.approx(13.5) for e in side_edges)


def test_x_intersection_radii_order_and_skew(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="FO", points=[[0, 0], [200, 0]])
    cad("road", "alignment", name="KERESZT", points=[[100, -80], [100, 80]])
    r = cad("road", "intersection", main="FO", side="KERESZT", main_width=7, side_width=6, radius=[10, 12, 8, 15])
    assert r["type"] == "X"
    got = {(round(a.dxf.center.x, 6), round(a.dxf.center.y, 6)): a.dxf.radius for a in _arcs(cad, r["handles"])}
    assert got == {(113, 13.5): 10, (100 - 3 - 12, 3.5 + 12): 12, (100 - 3 - 8, -3.5 - 8): 8, (113 + 5, -18.5): 15}
    # skewed crossing at 60 degrees: every corner arc is tangent to both edges
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="FO", points=[[0, 0], [200, 0]])
    d = (math.cos(math.radians(60)), math.sin(math.radians(60)))
    cad("road", "alignment", name="FERDE", points=[[100 - 80 * d[0], -80 * d[1]], [100 + 80 * d[0], 80 * d[1]]])
    r = cad("road", "intersection", main="FO", side="FERDE", main_width=7, side_width=6, radius=9)
    for a in _arcs(cad, r["handles"]):
        c = a.dxf.center
        dist_main = abs(abs(c.y) - 3.5)
        # distance to the nearer edge of the skewed road
        perp = abs((c.x - 100) * d[1] - c.y * d[0])
        assert dist_main == pytest.approx(9, abs=2e-3) and abs(perp - 3) == pytest.approx(9, abs=2e-3)


def test_ditch_levels_grades_low_points(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="U", points=[[0, 0], [300, 0]])
    cad("road", "profile", name="U", insert=[0, -100], terrain=[[0, 99], [300, 99]],
        vpis=[[0, 100], [150, 103], [300, 100]])
    r = cad("road", "ditch", name="U", side="right", depth=0.6, bottom_width=0.5, inner_slope=1.5, interval=25)
    edge_drop = 3.5 * 0.025 + 1.5 * 0.04
    assert r["bottom"][0]["z"] == pytest.approx(100 - edge_drop - 0.6, abs=1e-3)
    assert [p["station"] for p in r["high_points"]] == ["0+150.00"]
    assert [p["station"] for p in r["low_points"]] == ["0+000.00", "0+300.00"]
    assert r["too_flat"] == [] and r["grades_pct"]["min_abs"] == pytest.approx(2.0, abs=1e-6)
    b, y, mm = 0.5, 0.6, 1.5
    area = b * y + y * y * mm
    rh = area / (b + 2 * y * math.sqrt(1 + mm * mm))
    q = (1 / 0.03) * area * rh ** (2 / 3) * math.sqrt(0.02)
    assert r["capacity_at_flattest"]["flow_m3_s"] == pytest.approx(q, abs=1e-3)
    bottom = ent(cad, r["handles"][1])
    assert bottom.get_points("xy")[0][1] == pytest.approx(-(5.0 + 0.6 * 1.5 + 0.25))  # right side: y < 0
    assert cad("query", "count", group_by="layer")["groups"]["HOSSZ_ARKOK"] == 1
    flat = cad("road", "ditch", name="U", side="left", min_grade=2.5, interval=50)
    assert len(flat["too_flat"]) == 6


def test_culvert_and_capacities(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="U", points=[[0, 0], [300, 0]])
    cad("road", "profile", name="U", insert=[0, -100], terrain=[[0, 99], [300, 99]],
        vpis=[[0, 100], [150, 103], [300, 100]])
    c = cad("road", "culvert", name="U", station=150, diameter=0.6, length=20, invert_left=99.5, invert_right=99.2)
    assert c["slope_pct"] == pytest.approx(1.5) and c["flows_to"] == "jobb"
    a, rh = math.pi * 0.36 / 4, 0.15
    q = (1 / 0.013) * a * rh ** (2 / 3) * math.sqrt(0.015)
    assert c["capacity_full"]["flow_m3_s"] == pytest.approx(q, abs=1e-4)
    auto = cad("road", "culvert", name="U", station=150)
    assert auto["invert_left"] == pytest.approx(auto["invert_right"]) and auto["length_m"] > 14
    assert cad("road", "pipe_capacity", diameter=0.6, slope_pct=1.5)["flow_m3_s"] == pytest.approx(q, abs=1e-4)
    d = cad("road", "ditch_capacity", bottom_width=0.5, depth=0.6, slope_pct=2)
    assert d["flow_m3_s"] > 0.5


def test_runoff_rational_method(cad):
    r = cad("road", "runoff", area_m2=300 * 7, runoff_coefficient=0.9, intensity_l_s_ha=180, capacity_m3_s=1.111)
    assert r["flow_l_s"] == pytest.approx(0.9 * 180 * 0.21, abs=0.01)
    assert r["ok"] and r["utilisation_pct"] == pytest.approx(0.9 * 180 * 0.21 / 1000 / 1.111 * 100, abs=0.1)
