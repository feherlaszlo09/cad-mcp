import math
import xml.etree.ElementTree as ET

import pytest

from tests.test_ops import ent
from tests.test_road import PIS


def _al(cad):
    cad("drawing", "new", units="m")
    return cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60])


def test_superelevation_rotation(cad):
    r = _al(cad)
    c1, c2 = r["curves"]
    se = cad("road", "superelevation", name="T1", e=5.0, normal=2.5)
    assert se["curves"] == 2
    from cad_mcp.ops_road import get_alignment
    from cad_mcp.road_geom import superelevation_at

    ctx_al, data = get_alignment(type("C", (), {"doc": cad.dm().get().doc})(), "T1")
    spec = data["superelevation"]
    ke = ctx_al.curves[0].stations["KE"]
    ie = ctx_al.curves[0].stations["IE"]
    assert superelevation_at(ctx_al, spec, ke - 1) == (-2.5, -2.5)
    # curve 1 turns left -> outer side is the right lane
    assert superelevation_at(ctx_al, spec, (ke + ie) / 2) == pytest.approx((-2.5, 1.25))
    assert superelevation_at(ctx_al, spec, ie + 10) == pytest.approx((-5.0, 5.0))
    # curve 2 turns right -> left lane is outer
    ie2 = ctx_al.curves[1].stations["IE"]
    assert superelevation_at(ctx_al, spec, ie2 + 5) == pytest.approx((5.0, -5.0))
    xs = cad("road", "cross_section", name="T1", station=ie + 10, insert=[0, -300], center_elevation=101,
             terrain=[[-30, 100], [30, 100]])
    assert xs["lane_slopes_pct"] == {"left": -5.0, "right": 5.0}
    cad("road", "profile", name="T1", insert=[0, -200], terrain=[[0, 100], [1483, 105]],
        vpis=[[0, 101], [1483, 106]])
    assert cad("query", "find_text", pattern="+5.0")["count"] >= 1  # superelevation band row


def test_pavement_layers_and_formation(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="E", points=[[0, 0], [100, 0]])
    tmpl = [{"width": 3.5, "slope": -2.5}]
    base = cad("road", "cross_section", name="E", station=50, insert=[0, 0], center_elevation=101,
               template=tmpl, terrain=[[-30, 100], [30, 100]])
    pav = [{"name": "AC-11 kopóréteg", "thickness": 0.04}, {"name": "AC-22 kötőréteg", "thickness": 0.06},
           {"name": "CKt", "thickness": 0.20}]
    xs = cad("road", "cross_section", name="E", station=50, insert=[0, -20], center_elevation=101,
             template=tmpl, terrain=[[-30, 100], [30, 100]], pavement=pav)
    areas = [p["area_m2"] for p in xs["pavement"]]
    assert areas == pytest.approx([7 * 0.04, 7 * 0.06, 7 * 0.20], abs=1e-4)
    assert xs["fill_m2"] == pytest.approx(base["fill_m2"] - 7 * 0.30, abs=2e-3)


def test_ditch_in_cut(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="E", points=[[0, 0], [100, 0]])
    tmpl = [{"width": 3.5, "slope": -2.5}]
    kw = dict(name="E", station=50, insert=[0, 0], center_elevation=101, template=tmpl,
              terrain=[[-30, 102], [30, 102]], cut_slope=1.5)
    plain = cad("road", "cross_section", **kw)
    ditch = cad("road", "cross_section", **kw, ditch={"depth": 0.5, "bottom_width": 0.5, "inner_slope": 1.5})
    edge_z = 101 - 3.5 * 0.025
    expected = 3.5 + 0.5 * 1.5 + 0.5 + (102 - (edge_z - 0.5)) * 1.5
    assert ditch["daylight"]["right"][0] == pytest.approx(expected, abs=1e-3)
    assert ditch["cut_m2"] > plain["cut_m2"]


def test_sign_library(cad):
    _al(cad)
    types = cad("road", "sign_types")["types"]
    assert {"sebesseg", "stop", "elsobbsegadas", "foutvonal", "helysegnev"} <= set(types)
    for i, t in enumerate(types):
        cad("road", "sign", type=t, insert=[i * 5, -50], text="50" if t == "sebesseg" else "X")
    s = cad("road", "sign", type="sebesseg", insert=[0, 0], text="70", size=4)
    assert ent(cad, s["handle"]).get_attrib_text("TEXT") == "70"
    at = cad("road", "sign_at", name="T1", station=100, type="stop", offset=-6)
    assert ent(cad, at["handle"]).dxf.insert.isclose((100, -6, 0), abs_tol=1e-6)
    assert cad("query", "count", group_by="block")["groups"]["KRESZ_SEBESSEG"] == 2


def test_roundabout(cad):
    cad("drawing", "new", units="m")
    r = cad("road", "roundabout", center=[0, 0], outer_radius=18, ring_width=6,
            approaches=[{"angle": 0, "width": 7}, {"angle": 90, "width": 7}, {"angle": 200, "width": 8}],
            corner_radius=12, apron_width=1.5)
    assert r["inscribed_diameter"] == 36 and r["central_island_radius"] == 12
    circles = [ent(cad, h) for h in r["handles"] if ent(cad, h).dxftype() == "CIRCLE"]
    assert sorted(c.dxf.radius for c in circles) == [10.5, 12]
    edge = [ent(cad, h) for h in r["handles"] if ent(cad, h).dxf.layer == "KORFORGALOM"]
    ring_arcs = [e for e in edge if e.dxftype() == "ARC" and math.isclose(e.dxf.radius, 18)]
    corner_arcs = [e for e in edge if e.dxftype() == "ARC" and math.isclose(e.dxf.radius, 12)]
    assert len(ring_arcs) == 3 and len(corner_arcs) == 6
    # every corner arc is tangent to the ring: centre distance = R + r
    for a in corner_arcs:
        assert math.hypot(a.dxf.center.x, a.dxf.center.y) == pytest.approx(30, abs=1e-9)
    # corner arcs end exactly where ring arcs and approach edges start (closed outline)
    ends = []
    for e in edge:
        if e.dxftype() == "ARC":
            ends += [e.start_point, e.end_point]
        else:
            ends += [e.dxf.start, e.dxf.end]
    for a in corner_arcs:
        for p in (a.start_point, a.end_point):
            assert sum(1 for q in ends if p.isclose(q, abs_tol=1e-6)) == 2


def test_geo_conversion_location_kml(cad):
    cad("drawing", "new", units="m")
    origin = cad("geo", "convert", points=[[650000, 200000]])["points"][0]
    assert origin[0] == pytest.approx(19.0486, abs=2e-3) and origin[1] == pytest.approx(47.1444, abs=2e-3)
    back = cad("geo", "convert", points=[origin], from_crs="EPSG:4326", to_crs="EPSG:23700")["points"][0]
    assert back == pytest.approx([650000, 200000], abs=1e-3)
    g = cad("geo", "gps_points", points=[[47.4979, 19.0402]], labels=["Budapest"])
    x, y = g["drawing_coords"][0]
    assert 640000 < x < 660000 and 230000 < y < 245000
    cad("draw", "line", start=[650000, 240000], end=[650500, 240300], layer="TENGELY")
    loc = cad("geo", "set_location")
    assert abs(loc["meridian_convergence_deg"]) < 1 and cad("geo", "location")["has_geodata"]
    k = cad("geo", "export_kml", path="terv.kml")
    root = ET.parse(k["exported"]).getroot()
    coords = root.find(".//{http://www.opengis.net/kml/2.2}LineString/{http://www.opengis.net/kml/2.2}coordinates")
    lon, lat, _ = coords.text.split()[0].split(",")
    assert float(lon) == pytest.approx(19.0474, abs=2e-3) and float(lat) == pytest.approx(47.5039, abs=2e-3)
    cad("drawing", "save", path="geo.dxf")
    import ezdxf

    assert ezdxf.readfile(cad.tmp / "geo.dxf").modelspace().get_geodata() is not None
