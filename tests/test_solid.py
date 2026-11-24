import math

import ezdxf
import pytest

from tests.test_ops import ent


def _vol(cad, handles):
    return cad("query", "massprop", sel=handles)["solid"]["volume"]


def test_primitives_volumes_and_real_solids(cad):
    w = cad("draw3d", "wedge", origin=[0, 0, 0], size=[2, 3, 4], solid=True)["handles"]
    assert ent(cad, w[0]).dxftype() == "3DSOLID" and _vol(cad, w) == pytest.approx(12)
    p = cad("draw3d", "pyramid", base_center=[10, 0, 0], radius=math.sqrt(2), height=3, sides=4, rotation=45)["handles"]
    assert _vol(cad, p) == pytest.approx(4)
    f = cad("draw3d", "pyramid", base_center=[20, 0, 0], radius=math.sqrt(2), top_radius=math.sqrt(2) / 2, height=3,
            sides=4, rotation=45)["handles"]
    assert _vol(cad, f) == pytest.approx(7)
    b = cad("draw3d", "box", origin=[30, 0, 0], size=[1, 2, 3], solid=True)["handles"]
    assert ent(cad, b[0]).dxftype() == "3DSOLID" and _vol(cad, b) == pytest.approx(6)
    s = cad("draw3d", "sweep", path=[[40, 0, 0], [40, 10, 0]], profile=[[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]])["handles"]
    assert _vol(cad, s) == pytest.approx(10)
    lo = cad("draw3d", "loft", profiles=[[[50, 0, 0], [52, 0, 0], [52, 2, 0], [50, 2, 0]],
                                          [[50, 0, 4], [52, 0, 4], [52, 2, 4], [50, 2, 4]]])["handles"]
    assert _vol(cad, lo) == pytest.approx(16)
    ps = cad("draw3d", "polysolid", path=[[60, 0], [70, 0]], width=0.3, height=3)["handles"]
    assert ent(cad, ps[0]).dxftype() == "3DSOLID" and _vol(cad, ps) == pytest.approx(9)
    cad("drawing", "save", path="testek.dxf")
    doc = ezdxf.readfile(cad.tmp / "testek.dxf")
    assert len(doc.modelspace().query("3DSOLID")) == 3


def test_booleans_slice_section_flatshot(cad):
    a = cad("draw3d", "box", origin=[0, 0, 0], size=[2, 2, 2], solid=True)["handles"]
    b = cad("draw3d", "box", origin=[0.5, 0.5, -1], size=[1, 1, 4])["handles"]
    r = cad("draw3d", "boolean", kind="subtract", sel_a=a, sel_b=b)
    assert r["volume"] == pytest.approx(6) and ent(cad, r["handles"][0]).dxftype() == "3DSOLID"
    c1 = cad("draw3d", "box", origin=[10, 0, 0], size=[2, 2, 2])["handles"]
    c2 = cad("draw3d", "box", origin=[11, 0, 0], size=[2, 2, 2])["handles"]
    assert cad("draw3d", "boolean", kind="union", sel_a=c1, sel_b=c2, keep_originals=True)["volume"] == pytest.approx(12)
    assert cad("draw3d", "boolean", kind="intersect", sel_a=c1, sel_b=c2)["volume"] == pytest.approx(4)
    box = cad("draw3d", "box", origin=[20, 0, 0], size=[2, 2, 2])["handles"]
    parts = cad("draw3d", "slice", sel=box, point=[20, 0, 0.5], normal=[0, 0, 1])["parts"]
    assert sorted(round(p["volume"], 6) for p in parts) == [2, 6]
    box = cad("draw3d", "box", origin=[30, 0, 0], size=[2, 3, 4])["handles"]
    sec = cad("draw3d", "section", sel=box, point=[30, 0, 1], normal=[0, 0, 1])
    assert sec["area"] == pytest.approx(6) and sec["loops"] == 1
    tilted = cad("draw3d", "section", sel=box, point=[31, 1.5, 2], normal=[1, 0, 1])
    assert tilted["area"] == pytest.approx(math.sqrt(2) * 2 * 3, rel=1e-6)
    top = cad("draw3d", "flatshot", sel=box)
    assert top["projected_area"] == pytest.approx(6)
    front = cad("draw3d", "flatshot", sel=box, direction=[0, -1, 0], origin=[0, -20])
    assert front["projected_area"] == pytest.approx(8)


def test_presspull_conversion_export(cad):
    cad("draw", "rectangle", corner1=[0, 0], corner2=[10, 10])
    cad("draw", "circle", center=[5, 5], radius=2)
    pp = cad("draw3d", "presspull", point=[1, 1], height=3)["handles"]
    assert _vol(cad, pp) == pytest.approx((100 - math.pi * 4) * 3, rel=2e-3)
    m = cad("draw3d", "to_mesh", sel=pp)["handles"]
    assert ent(cad, m[0]).dxftype() == "MESH" and _vol(cad, m) == pytest.approx((100 - math.pi * 4) * 3, rel=2e-3)
    s = cad("draw3d", "to_solid", sel=m)["handles"]
    assert ent(cad, s[0]).dxftype() == "3DSOLID"
    e = cad("view", "export_3d", path="lemez.stl", sel=s)
    assert e["triangles"] > 50


def test_massprop_2d(cad):
    r = cad("draw", "rectangle", corner1=[0, 0], corner2=[4, 2])["handles"]
    mp = cad("query", "massprop", sel=r)["region"]
    assert mp["area"] == pytest.approx(8) and mp["centroid"] == pytest.approx([2, 1])
    assert mp["Ix_centroid"] == pytest.approx(4 * 8 / 12) and mp["Iy_centroid"] == pytest.approx(2 * 64 / 12)
    assert mp["Ixy_centroid"] == pytest.approx(0, abs=1e-9) and mp["perimeter"] == pytest.approx(12)
    hole = cad("draw", "circle", center=[2, 1], radius=0.5)["handles"]
    mp2 = cad("query", "massprop", sel=r + hole)["region"]
    assert mp2["area"] == pytest.approx(8 - math.pi * 0.25, rel=1e-4) and mp2["centroid"] == pytest.approx([2, 1], abs=1e-6)
