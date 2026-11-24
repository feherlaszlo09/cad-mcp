import math

import ezdxf

from tests.test_ops import ent


def test_matchprop_setbylayer_align(cad):
    src = cad("draw", "line", start=[0, 0], end=[1, 0], layer="A", color="red", lineweight=0.5)["handles"][0]
    t = cad("draw", "circle", center=[5, 5], radius=1)["handles"][0]
    cad("edit", "matchprop", source=src, sel=[t])
    assert ent(cad, t).dxf.layer == "A" and ent(cad, t).dxf.color == 1
    cad("edit", "setbylayer", sel=[t])
    assert ent(cad, t).dxf.color == 256
    ln = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    cad("edit", "align", sel=[ln], src1=[0, 0], dst1=[5, 5], src2=[10, 0], dst2=[5, 25], scale=True)
    assert ent(cad, ln).dxf.end.isclose((5, 25, 0))


def test_divide_measure(cad):
    ln = cad("draw", "line", start=[0, 0], end=[100, 0])["handles"][0]
    pts = cad("draw", "divide", handle=ln, segments=4)["handles"]
    assert [round(ent(cad, h).dxf.location.x) for h in pts] == [25, 50, 75]
    pts = cad("draw", "measure", handle=ln, length=30)["handles"]
    assert [round(ent(cad, h).dxf.location.x) for h in pts] == [30, 60, 90]
    cad("block", "define", name="TICK", entities=[{"tool": "draw", "operation": "line", "args": {"start": [0, -1], "end": [0, 1]}}])
    ins = cad("draw", "measure", handle=ln, length=50, block="TICK")["handles"]
    assert ent(cad, ins[0]).dxftype() == "INSERT"


def test_overkill_reverse_pedit(cad):
    cad("draw", "line", start=[0, 0], end=[10, 0])
    cad("draw", "line", start=[10, 0], end=[0, 0])  # duplicate, reversed
    cad("draw", "line", start=[5, 0], end=[20, 0])  # overlapping collinear
    cad("draw", "circle", center=[0, 0], radius=3)
    cad("draw", "circle", center=[0, 0], radius=3)
    r = cad("edit", "overkill")
    assert r["deleted"] == 3
    lines = cad("query", "list", sel={"type": "LINE"})["entities"]
    assert len(lines) == 1 and sorted([lines[0]["start"][0], lines[0]["end"][0]]) == [0, 20]
    pl = cad("draw", "polyline", points=[[0, 0], [10, 0], [10, 10]], bulges=[0, 0.5])["handles"][0]
    cad("edit", "reverse", sel=[pl])
    pts = list(ent(cad, pl).get_points("xyb"))
    assert pts[0][:2] == (10, 10) and math.isclose(pts[0][2], -0.5)
    cad("edit", "pedit", handle=pl, close=True, width=0.5, decurve=True)
    assert ent(cad, pl).closed and all(b == 0 for *_, b in ent(cad, pl).get_points("xyb"))
    ln = cad("draw", "line", start=[0, 50], end=[5, 50])["handles"][0]
    r = cad("edit", "pedit", handle=ln, from_line=True, width=1)
    assert ent(cad, r["handle"]).dxftype() == "LWPOLYLINE"


def test_boundary_and_hatch_pick(cad):
    cad("draw", "rectangle", corner1=[0, 0], corner2=[100, 50])
    cad("draw", "line", start=[60, 0], end=[60, 50])
    cad("draw", "circle", center=[30, 25], radius=5)
    b = cad("draw", "boundary", point=[10, 10])
    assert math.isclose(b["area"], 60 * 50 - math.pi * 25, rel_tol=1e-3)
    assert len(b["handles"]) == 2  # outline + the island around the circle
    h = cad("draw", "hatch_pick", point=[80, 25], pattern="ANSI31")
    assert math.isclose(cad("query", "area", sel=h["handles"])["total_area"], 40 * 50, rel_tol=1e-6)


def test_revcloud_mline_helix_groups(cad):
    r = cad("draw", "revcloud", points=[[0, 0], [40, 0], [40, 20], [0, 20]], arc_length=5)
    assert ent(cad, r["handles"][0]).closed
    m = cad("draw", "mline", points=[[0, 0], [50, 0], [50, 30]], scale=2)
    assert ent(cad, m["handles"][0]).dxftype() == "MLINE"
    hx = cad("draw3d", "helix", base_center=[0, 0, 0], radius=5, pitch=2, turns=3)
    assert ent(cad, hx["handles"][0]).dxftype() == "HELIX"
    a = cad("draw", "line", start=[0, 0], end=[1, 1])["handles"][0]
    g = cad("edit", "group", sel=[a, r["handles"][0]], name="FELHO")
    assert cad("query", "groups")["groups"][0]["name"] == "FELHO"
    cad("edit", "ungroup", name="FELHO")
    assert cad("query", "groups")["groups"] == []
    assert g["handles"]


def test_dim_chains_text_tools(cad):
    d = cad("annotate", "dim_linear", p1=[0, 0], p2=[10, 0], location=[0, -5])["handles"][0]
    cont = cad("annotate", "dim_continue", base=d, points=[[25, 0], [40, 0]])["handles"]
    assert [round(ent(cad, h).get_measurement()) for h in cont] == [15, 15]
    base = cad("annotate", "dim_baseline", base=d, points=[[25, 0], [40, 0]], spacing=4)["handles"]
    assert [round(ent(cad, h).get_measurement()) for h in base] == [25, 40]
    assert ent(cad, base[1]).dxf.defpoint.y < ent(cad, base[0]).dxf.defpoint.y < -5
    t = cad("annotate", "text", text="M0 körgyűrű", insert=[0, 20])["handles"][0]
    cad("annotate", "find_replace", find="M0", replace="M1")
    assert ent(cad, t).dxf.text == "M1 körgyűrű"
    cad("annotate", "scale_text", sel=[t], factor=2)
    assert ent(cad, t).dxf.height == 5
    c = cad("draw", "circle", center=[0, 0], radius=10)["handles"][0]
    assert len(cad("annotate", "centermark", handle=c)["handles"]) == 2


def test_layer_merge_attsync_wblock_views_props(cad):
    cad("draw", "line", start=[0, 0], end=[1, 0], layer="RÉGI1")
    cad("draw", "line", start=[0, 1], end=[1, 1], layer="RÉGI2")
    cad("layer", "merge", sources=["RÉGI1", "RÉGI2"], target="ÚJ")
    assert cad("query", "count", group_by="layer")["groups"] == {"ÚJ": 2}
    cad("block", "define", name="B", entities=[{"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 1}}])
    ref = cad("block", "insert", name="B", insert=[0, 0])["handle"]
    cad("block", "attdef", block="B", tag="SZAM", insert=[0, 0], default="1")
    cad("block", "sync_attributes", name="B")
    assert {a.dxf.tag for a in ent(cad, ref).attribs} == {"SZAM"}
    w = cad("drawing", "wblock", sel={"layer": "ÚJ"}, path="kivag.dxf")
    assert ezdxf.readfile(w["written"]).modelspace().query("LINE").__len__() == 2
    cad("drawing", "named_view", name="Csomopont", region=[[0, 0], [10, 10]])
    assert cad("drawing", "named_view", name="x")["views"][0]["name"] == "Csomopont"
    cad("drawing", "ucs", name="Tengely", origin=[100, 100])
    assert cad("drawing", "ucs")["ucs"][0]["name"] == "Tengely"
    cad("drawing", "properties", values={"Projekt": "Teszt út"})
    assert cad("drawing", "properties")["properties"]["Projekt"] == "Teszt út"
