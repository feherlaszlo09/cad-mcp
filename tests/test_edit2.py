import math

import pytest

from tests.test_ops import ent


def test_fillet_any_line_circle_and_line_arc(cad):
    ln = cad("draw", "line", start=[0, 0], end=[20, 0])["handles"][0]
    c = cad("draw", "circle", center=[10, 6], radius=5)["handles"][0]
    r = cad("edit", "fillet_any", handle1=ln, handle2=c, radius=2, pick1=[0, 0], pick2=[5, 6])
    cx, cy = r["center"]
    assert cy == pytest.approx(2) and math.hypot(cx - 10, cy - 6) == pytest.approx(7)
    assert ent(cad, ln).dxf.end.isclose((cx, 0, 0), abs_tol=1e-6)  # centre is reported rounded
    ln2 = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    arc = cad("draw", "arc", center=[20, 0], radius=10, start_angle=90, end_angle=180)["handles"][0]
    r = cad("edit", "fillet_any", handle1=ln2, handle2=arc, radius=2, pick1=[2, 0], pick2=[20, 10])
    cx, cy = r["center"]
    assert cy == pytest.approx(2) and math.hypot(cx - 20, cy) == pytest.approx(12)
    f = ent(cad, r["created"][0])
    assert f.dxf.radius == 2


def test_tangent_circles(cad):
    a = cad("draw", "line", start=[0, 0], end=[20, 0])["handles"][0]
    b = cad("draw", "line", start=[0, 0], end=[0, 20])["handles"][0]
    assert cad("draw", "circle_ttr", handle1=a, handle2=b, radius=3, pick1=[10, 0], pick2=[0, 10])["center"] == \
        pytest.approx([3, 3])
    l1 = cad("draw", "line", start=[0, 0], end=[4, 0])["handles"][0]
    l2 = cad("draw", "line", start=[4, 0], end=[0, 3])["handles"][0]
    l3 = cad("draw", "line", start=[0, 3], end=[0, 0])["handles"][0]
    t = cad("draw", "circle_ttt", handle1=l1, handle2=l2, handle3=l3)
    assert t["center"] == pytest.approx([1, 1]) and t["radius"] == pytest.approx(1)
    c2 = cad("draw", "circle_2p", p1=[0, 0], p2=[10, 0])["handles"][0]
    assert ent(cad, c2).dxf.radius == 5 and ent(cad, c2).dxf.center.isclose((5, 0, 0))


def test_offset_exact_keeps_arcs(cad):
    rect = cad("draw", "rectangle", corner1=[0, 0], corner2=[20, 10], fillet=2)["handles"][0]
    out = cad("edit", "offset_exact", handle=rect, distance=1)["created"][0]
    assert cad("query", "length", sel=[out])["total"] == pytest.approx(44 + 2 * math.pi * 3, abs=1e-6)
    assert sum(1 for *_, b in ent(cad, out).get_points("xyb") if abs(b) > 1e-9) == 4
    inn = cad("edit", "offset_exact", handle=rect, distance=1, side_point=[10, 5])["created"][0]
    assert cad("query", "length", sel=[inn])["total"] == pytest.approx(44 + 2 * math.pi * 1, abs=1e-6)
    pl = cad("draw", "polyline", points=[[0, 0], [10, 0], [10, 10]], bulges=[0, 1])["handles"][0]
    o = cad("edit", "offset_exact", handle=pl, distance=1, side_point=[5, 2])["created"][0]
    pts = list(ent(cad, o).get_points("xyb"))
    assert [p[:2] for p in pts] == [pytest.approx((0, 1)), pytest.approx((10, 1)), pytest.approx((10, 9))]
    assert pts[1][2] == pytest.approx(1)


def test_chamfers(cad):
    a = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    b = cad("draw", "line", start=[10, 0], end=[10, 10])["handles"][0]
    c = cad("edit", "chamfer_angle", handle1=a, handle2=b, distance=2, angle=45)["created"][0]
    assert ent(cad, c).dxf.start.isclose((8, 0, 0)) and ent(cad, c).dxf.end.isclose((10, 2, 0))
    sq = cad("draw", "rectangle", corner1=[0, 20], corner2=[10, 30])["handles"][0]
    cad("edit", "chamfer_polyline", handle=sq, distance1=1)
    assert len(ent(cad, sq)) == 8
    assert cad("query", "length", sel=[sq])["total"] == pytest.approx(4 * 8 + 4 * math.sqrt(2))


def test_extend_arc_end_and_lengthen(cad):
    b = math.tan(math.radians(90) / 4)
    pl = cad("draw", "polyline", points=[[0, 0], [10, 0], [20, 10]], bulges=[0, b])["handles"][0]
    bound = cad("draw", "line", start=[0, 15], end=[30, 15])["handles"][0]
    cad("edit", "extend_arc_end", handle=pl, boundary=[bound])
    pts = list(ent(cad, pl).get_points("xyb"))
    assert pts[-1][:2] == pytest.approx((10 + math.sqrt(75), 15))
    assert pts[-2][2] == pytest.approx(math.tan(math.radians(120) / 4))
    arc = cad("draw", "arc", center=[0, 0], radius=10, start_angle=0, end_angle=90)["handles"][0]
    cad("edit", "lengthen_any", handle=arc, total=10 * math.pi)
    assert ent(cad, arc).dxf.end_angle % 360 == pytest.approx(180)
    cad("edit", "lengthen_any", handle=arc, delta_angle=-45)
    assert ent(cad, arc).dxf.end_angle % 360 == pytest.approx(135)
    p2 = cad("draw", "polyline", points=[[0, 50], [10, 50], [10, 60]])["handles"][0]
    cad("edit", "lengthen_any", handle=p2, delta=5, at_start=True)
    assert list(ent(cad, p2).get_points("xy"))[0] == pytest.approx((-5, 50))
    cad("edit", "lengthen_any", handle=p2, percent=110)  # like AutoCAD: only the end segment changes
    assert cad("query", "length", sel=[p2])["total"] == pytest.approx(27.5)


def test_join_same_and_stretch(cad):
    cad("draw", "line", start=[0, 0], end=[5, 0])
    cad("draw", "line", start=[4, 0], end=[10, 0])
    j = cad("edit", "join_same", sel={"type": "LINE"})
    nl = ent(cad, j["created"][0])
    assert j["type"] == "LINE" and nl.dxf.start.isclose((0, 0, 0)) and nl.dxf.end.isclose((10, 0, 0))
    cad("draw", "arc", center=[50, 0], radius=5, start_angle=0, end_angle=180)
    cad("draw", "arc", center=[50, 0], radius=5, start_angle=180, end_angle=360)
    assert cad("edit", "join_same", sel={"type": "ARC"})["type"] == "CIRCLE"
    cad("drawing", "new", name="S")
    arc = cad("draw", "arc", center=[0, 0], radius=10, start_angle=0, end_angle=180)["handles"][0]
    cad("block", "define", name="B", entities=[{"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 0.5}}])
    ref = cad("block", "insert", name="B", insert=[10, 1])["handle"]
    cad("edit", "stretch", window=[[8, -1], [12, 2]], vector=[2, 0])
    a = ent(cad, arc)
    assert a.dxf.radius == pytest.approx((121 + 100) / 20)
    assert a.start_point.isclose((12, 0, 0), abs_tol=1e-9) and a.end_point.isclose((-10, 0, 0), abs_tol=1e-9)
    assert ent(cad, ref).dxf.insert.isclose((12, 1, 0))


def test_splinedit_pedit_hatchedit_gradient(cad):
    sp = cad("draw", "spline", fit_points=[[0, 0], [10, 5], [20, 0]])["handles"][0]
    cad("edit", "splinedit", handle=sp, action="add_fit_point", index=1, point=[5, 4])
    assert len(ent(cad, sp).fit_points) == 4
    cad("edit", "splinedit", handle=sp, action="close")
    assert ent(cad, sp).closed
    poly = cad("edit", "splinedit", handle=sp, action="to_polyline")["created"][0]
    assert ent(cad, poly).dxftype() == "LWPOLYLINE"
    pl = cad("draw", "polyline", points=[[0, 0], [10, 0], [20, 0]])["handles"][0]
    cad("edit", "pedit_vertex", handle=pl, action="move", index=1, point=[10, 5])
    cad("edit", "pedit_vertex", handle=pl, action="insert", index=0, point=[5, 2])
    cad("edit", "pedit_vertex", handle=pl, action="set", index=0, bulge=0.5, start_width=1, end_width=0)
    pts = list(ent(cad, pl).get_points("xyseb"))
    assert len(pts) == 4 and pts[1][:2] == (5, 2) and pts[0][4] == 0.5 and pts[0][2] == 1
    cad("edit", "pedit_vertex", handle=pl, action="remove", index=1)
    assert len(ent(cad, pl)) == 3
    s2 = cad("edit", "pedit_spline", handle=pl)["created"][0]
    assert ent(cad, s2).dxftype() == "SPLINE"
    h = cad("draw", "hatch", boundary=[[0, 0], [10, 0], [10, 10], [0, 10]])["handles"][0]
    cad("edit", "hatchedit", handle=h, pattern="ANSI31", scale=2, angle=45, color="red")
    assert ent(cad, h).dxf.pattern_name == "ANSI31" and ent(cad, h).dxf.color == 1
    cad("edit", "hatchedit", handle=h, gradient={"color1": "blue", "color2": "#ffffff", "name": "CYLINDER"})
    assert ent(cad, h).gradient is not None and ent(cad, h).gradient.name == "CYLINDER"
    g = cad("draw", "gradient", boundary=[[20, 0], [30, 0], [30, 10]], color1="red", color2="yellow", rotation=30)
    assert ent(cad, g["handles"][0]).gradient.rotation == pytest.approx(30)


def test_3d_transforms(cad):
    ln = cad("draw", "line", start=[0, 1, 0], end=[0, 2, 0])["handles"][0]
    cad("edit", "rotate3d", sel=[ln], axis_p1=[0, 0, 0], axis_p2=[1, 0, 0], angle=90)
    assert ent(cad, ln).dxf.start.isclose((0, 0, 1), abs_tol=1e-9)
    p = cad("draw", "point", location=[1, 2, 5])["handles"][0]
    m = cad("edit", "mirror3d", sel=[p], p1=[0, 0, 0], p2=[1, 0, 0], p3=[0, 1, 0])["handles"][0]
    assert ent(cad, m).dxf.location.isclose((1, 2, -5))
    assert len(cad("edit", "array3d", sel=[p], rows=2, cols=2, levels=2, row_spacing=1, col_spacing=1,
                   level_spacing=1)["created"]) == 7
    polar = cad("edit", "array3d", sel=[p], polar_axis=[[0, 0, 0], [0, 0, 1]], count=4)["created"]
    assert ent(cad, polar[0]).dxf.location.isclose((-2, 1, 5), abs_tol=1e-9)
