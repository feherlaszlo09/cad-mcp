import math

import ezdxf
import pytest

from cad_mcp.core import CadError


def ent(cad, h):
    return cad.dm().get().doc.entitydb[h]


def test_new_info_save_open_roundtrip(cad):
    cad("drawing", "new", name="Plan", units="mm")
    cad("layer", "create", name="WALL", color="red", lineweight=0.5)
    h = cad("draw", "line", start=[0, 0], end=[100, 0], layer="WALL")["handles"][0]
    info = cad("drawing", "info")
    assert info["entities"] == 1 and info["units"] == "mm"
    saved = cad("drawing", "save", path="plan.dxf")
    assert (cad.tmp / "plan.dxf").is_file()
    opened = cad("drawing", "open", path=saved["saved"], name="again")
    assert opened["entities"] == 1
    assert cad("query", "get", handles=h)["entities"][0]["layer"] == "WALL"


def test_draw_everything_and_render(cad):
    cad("draw", "polyline", points=[[0, 0], [50, 0], [50, 30]], bulges=[0, 0.5], closed=False)
    cad("draw", "rectangle", corner1=[0, 0], corner2=[40, 20], fillet=3)
    cad("draw", "polygon", center=[80, 80], radius=10, sides=6)
    cad("draw", "circle", center=[0, 0], radius=5, color="#ff8800")
    cad("draw", "circle_3p", p1=[10, 0], p2=[0, 10], p3=[-10, 0])
    cad("draw", "arc", center=[0, 0], radius=8, start_angle=0, end_angle=90)
    cad("draw", "arc_3p", start=[10, 0], through=[0, 10], end=[-10, 0])
    cad("draw", "ellipse", center=[0, 0], major_axis=[20, 0], ratio=0.5)
    cad("draw", "spline", fit_points=[[0, 0], [10, 10], [20, 0], [30, 10]])
    cad("draw", "point", location=[1, 1])
    cad("draw", "xline", point=[0, 0], direction=[1, 1])
    cad("draw", "solid", points=[[0, 0], [10, 0], [10, 10], [0, 10]])
    cad("draw", "donut", center=[50, 50], inner_diameter=5, outer_diameter=10)
    r = cad("draw", "hatch", boundary=[[[0, 0], [30, 0], [30, 30], [0, 30]], [[10, 10], [20, 10], [20, 20], [10, 20]]],
            pattern="ANSI31", scale=0.5)
    assert r["handles"]
    c = cad("draw", "circle", center=[100, 100], radius=10)["handles"][0]
    cad("draw", "hatch", boundary_handles=[c], pattern="SOLID", color="blue")
    cad("draw3d", "box", origin=[0, 0, 0], size=[10, 20, 30])
    cad("draw3d", "cylinder", base_center=[50, 0, 0], radius=5, height=20)
    cad("draw3d", "sphere", center=[0, 50, 0], radius=5)
    cad("draw3d", "extrude", profile=[[0, 0], [10, 0], [10, 10]], height=5)
    cad("draw3d", "revolve", profile=[[0, 0, 0], [5, 0, 0], [5, 10, 0]], axis=[0, 1, 0])
    cad("annotate", "text", text="Hello", insert=[0, -10], height=3, align="middle_center")
    cad("annotate", "mtext", text="Line 1\nLine 2", insert=[0, -20], width=40)
    d = cad("annotate", "dim_linear", p1=[0, 0], p2=[50, 0], location=[0, -15])["handles"][0]
    assert abs(ent(cad, d).get_measurement() - 50) < 1e-9
    cad("annotate", "dim_aligned", p1=[0, 0], p2=[30, 40], distance=5)
    cad("annotate", "dim_angular", center=[0, 0], p1=[10, 0], p2=[0, 10], location=[7, 7])
    cad("annotate", "dim_radius", handle=c)
    cad("annotate", "dim_diameter", center=[0, 0], radius=5)
    cad("annotate", "dim_ordinate", feature=[10, 5], leader_end=[15, 20], axis="x")
    cad("annotate", "leader", points=[[0, 0], [10, 10], [20, 10]], text="Note")
    t = cad("annotate", "table", insert=[200, 100], rows=[["Room", "Area"], ["Kitchen", "12.5"]],
            col_widths=[40, 20])
    assert t["handles"]
    out = cad("view", "png", show_handles=True, axes=True)
    assert out["_image"][:8] == b"\x89PNG\r\n\x1a\n"
    pdf = cad("view", "export", path="out.pdf", paper="A3")
    assert (cad.tmp / "out.pdf").stat().st_size > 1000
    cad("view", "export", path="out.svg", scale=0.01)
    assert pdf["format"] == "pdf"


def test_transforms_and_arrays(cad):
    h = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    cad("edit", "move", sel=[h], vector=[5, 5])
    e = ent(cad, h)
    assert e.dxf.start.isclose((5, 5, 0))
    cad("edit", "rotate", sel=h, base=[5, 5], angle=90)
    assert ent(cad, h).dxf.end.isclose((5, 15, 0))
    cp = cad("edit", "copy", sel=[h], vector=[10, 0], count=3)["created"]
    assert len(cp) == 3
    m = cad("edit", "mirror", sel=[h], p1=[0, 0], p2=[0, 1])["handles"][0]
    assert ent(cad, m).dxf.start.isclose((-5, 5, 0))
    assert len(cad("edit", "array_rect", sel=[h], rows=2, cols=3, row_spacing=10, col_spacing=10)["created"]) == 5
    assert len(cad("edit", "array_polar", sel=[h], center=[0, 0], count=6)["created"]) == 5
    cad("edit", "scale", sel=[h], base=[5, 5], factor=2)
    assert math.isclose(ent(cad, h).dxf.start.distance(ent(cad, h).dxf.end), 20)
    cad("edit", "set_props", sel={"type": "LINE"}, color="green", layer="NEW")
    assert ent(cad, h).dxf.layer == "NEW"
    assert cad("query", "count", group_by="layer")["groups"]["NEW"] >= 10
    cad("edit", "delete", sel={"layer": "NEW"})
    assert cad("drawing", "info")["entities"] == 0


def test_offset_trim_extend(cad):
    ln = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    off = cad("edit", "offset", handle=ln, distance=2, side_point=[5, -1])["created"][0]
    assert ent(cad, off).dxf.start.isclose((0, -2, 0))
    c = cad("draw", "circle", center=[0, 0], radius=5)["handles"][0]
    big = cad("edit", "offset", handle=c, distance=1)["created"][0]
    assert ent(cad, big).dxf.radius == 6
    rect = cad("draw", "rectangle", corner1=[0, 0], corner2=[10, 10])["handles"][0]
    inner = cad("edit", "offset", handle=rect, distance=1, side_point=[5, 5])["created"][0]
    a = cad("query", "area", sel=[inner])["total_area"]
    assert math.isclose(a, 64, rel_tol=1e-6)

    cad("drawing", "new", name="T")
    h = cad("draw", "line", start=[0, 0], end=[20, 0])["handles"][0]
    v = cad("draw", "line", start=[10, -5], end=[10, 5])["handles"][0]
    cad("edit", "trim", handle=h, pick=[15, 0], cutting=[v])
    assert ent(cad, h).dxf.end.isclose((10, 0, 0))
    short = cad("draw", "line", start=[0, 3], end=[5, 3])["handles"][0]
    cad("edit", "extend", handle=short, pick=[5, 3], boundary=[v])
    assert ent(cad, short).dxf.end.isclose((10, 3, 0))
    # trim the middle of a line between two edges -> split
    h2 = cad("draw", "line", start=[0, 10], end=[30, 10])["handles"][0]
    v1 = cad("draw", "line", start=[10, 0], end=[10, 20])["handles"][0]
    v2 = cad("draw", "line", start=[20, 0], end=[20, 20])["handles"][0]
    res = cad("edit", "trim", handle=h2, pick=[15, 10], cutting=[v1, v2])
    assert ent(cad, h2).dxf.end.isclose((10, 10, 0))
    assert ent(cad, res["created"][0]).dxf.start.isclose((20, 10, 0))
    # circle trimmed by a line -> arc
    cad("drawing", "new", name="C")
    c = cad("draw", "circle", center=[0, 0], radius=10)["handles"][0]
    cut = cad("draw", "line", start=[0, -20], end=[0, 20])["handles"][0]
    r = cad("edit", "trim", handle=c, pick=[10, 0], cutting=[cut])
    arc = ent(cad, r["created"][0])
    assert arc.dxftype() == "ARC" and math.isclose(arc.dxf.start_angle, 90) and math.isclose(arc.dxf.end_angle, 270)


def test_fillet_chamfer_join_break_stretch(cad):
    a = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    b = cad("draw", "line", start=[12, 2], end=[12, 10])["handles"][0]
    r = cad("edit", "fillet", handle1=a, handle2=b, radius=2)
    arc = ent(cad, r["created"][0])
    assert math.isclose(arc.dxf.radius, 2) and arc.dxf.center.isclose((10, 2, 0))
    assert ent(cad, a).dxf.end.isclose((10, 0, 0)) and ent(cad, b).dxf.start.isclose((12, 2, 0))
    j = cad("edit", "join", sel=[a, arc.dxf.handle, b])
    pl = ent(cad, j["created"][0])
    assert pl.dxftype() == "LWPOLYLINE" and len(pl) == 4
    c1 = cad("draw", "line", start=[0, 20], end=[10, 20])["handles"][0]
    c2 = cad("draw", "line", start=[10, 20], end=[10, 30])["handles"][0]
    cad("edit", "chamfer", handle1=c1, handle2=c2, distance1=2)
    assert ent(cad, c1).dxf.end.isclose((8, 20, 0))
    rect = cad("draw", "rectangle", corner1=[0, 50], corner2=[20, 60])["handles"][0]
    cad("edit", "fillet_polyline", handle=rect, radius=2)
    assert len(ent(cad, rect)) == 8
    ln = cad("draw", "line", start=[0, 100], end=[10, 100])["handles"][0]
    br = cad("edit", "break_at", handle=ln, point=[4, 100], point2=[6, 100])
    assert ent(cad, ln).dxf.end.isclose((4, 100, 0)) and ent(cad, br["created"][0]).dxf.start.isclose((6, 100, 0))
    cad("edit", "stretch", window=[[9, 99], [11, 101]], vector=[5, 0])
    assert ent(cad, br["created"][0]).dxf.end.isclose((15, 100, 0))


def test_query_ops(cad):
    cad("draw", "rectangle", corner1=[0, 0], corner2=[10, 5], layer="A")
    c = cad("draw", "circle", center=[20, 0], radius=1, layer="B")["handles"][0]
    ln = cad("draw", "line", start=[0, 0], end=[30, 0])["handles"][0]
    cad("annotate", "text", text="Room 101", insert=[0, 10])
    assert cad("query", "count")["total"] == 4
    assert math.isclose(cad("query", "area", sel={"layer": "A"})["total_area"], 50)
    assert math.isclose(cad("query", "length", sel=[c])["total"], 2 * math.pi, rel_tol=1e-4)
    assert cad("query", "find_text", pattern="room")["count"] == 1
    pts = cad("query", "intersections", handle1=c, handle2=ln)["points"]
    assert len(pts) == 2
    assert cad("query", "list", sel={"window": [[-1, -1], [11, 6]]})["total"] == 1
    assert cad("query", "nearest", point=[20, 1.5])["nearest"][0]["handle"] == c
    assert cad("query", "distance", p1=[0, 0], p2=[3, 4])["distance"] == 5
    assert cad("query", "extents")["max"][0] == 30


def test_layers_blocks_layouts_styles(cad):
    cad("layer", "create_many", layers=[{"name": "WALL", "color": 1}, {"name": "DOOR", "color": 3, "linetype": "DASHED"}])
    cad("layer", "modify", name="DOOR", frozen=True, locked=True)
    lst = {item["name"]: item for item in cad("layer", "list")["layers"]}
    assert lst["DOOR"]["frozen"] and lst["DOOR"]["linetype"] == "DASHED"
    cad("layer", "rename", name="WALL", new_name="FAL")
    cad("block", "define", name="DESK", base_point=[0, 0], entities=[
        {"tool": "draw", "operation": "rectangle", "args": {"corner1": [0, 0], "corner2": [120, 60]}},
    ])
    cad("block", "attdef", block="DESK", tag="ID", insert=[60, 30], default="?")
    ins = cad("block", "insert", name="DESK", insert=[100, 100], rotation=90, attributes={"ID": "D-1"})
    assert ins["attributes"] == {"ID": "D-1"}
    cad("block", "set_attributes", handle=ins["handle"], values={"ID": "D-2"})
    assert cad("query", "find_text", pattern="D-2")["count"] == 1
    desk = next(b for b in cad("block", "list")["blocks"] if b["name"] == "DESK")
    assert desk["references"] == 1 and desk["attributes"] == ["ID"]
    cad("draw", "circle", center=[0, 0], radius=5)
    cad("layout", "create", name="Sheet1", paper="A3")
    vp = cad("layout", "add_viewport", layout="Sheet1", center=[200, 140], size=[380, 260],
             view_center=[0, 0], scale=0.5)
    cad("layout", "fit_viewport", handle=vp["handle"])
    sheet = next(x for x in cad("layout", "list")["layouts"] if x["name"] == "Sheet1")
    assert sheet["viewports"][0]["handle"] == vp["handle"]
    cad("view", "export", path="sheet.pdf", space="Sheet1")
    cad("style", "create_text_style", name="ISO", font="isocpeur.ttf")
    cad("style", "create_dimstyle", name="ARCH", values={"dimtxt": 3.5, "dimasz": 2.5})
    assert any(d["name"] == "ARCH" for d in cad("style", "list_dimstyles")["dimstyles"])
    cad("style", "load_linetype", name="CENTER")
    assert "CENTER" in cad("style", "list_linetypes")["loaded"]


def test_undo_redo_and_rollback(cad):
    h = cad("draw", "line", start=[0, 0], end=[1, 0])["handles"][0]
    cad("edit", "move", sel=[h], vector=[10, 0])
    cad("drawing", "undo")
    assert ent(cad, h).dxf.start.isclose((0, 0, 0))
    cad("drawing", "redo")
    assert ent(cad, h).dxf.start.isclose((10, 0, 0))
    with pytest.raises(CadError):
        cad("edit", "trim", handle=h, pick=[10, 0])  # nothing to trim against
    assert ent(cad, h).dxf.start.isclose((10, 0, 0))


def test_batch_with_references_and_atomic_rollback(cad):
    res = cad.batch([
        {"tool": "draw", "operation": "line", "args": {"start": [0, 0], "end": [10, 0]}},
        {"tool": "draw", "operation": "line", "args": {"start": [12, 2], "end": [12, 10]}},
        {"tool": "edit", "operation": "fillet", "args": {"handle1": "$0.handles[0]", "handle2": "$1.handles[0]", "radius": 2}},
    ])
    assert res["steps"] == 3
    before = cad("drawing", "info")["entities"]
    with pytest.raises(CadError):
        cad.batch([
            {"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 1}},
            {"tool": "draw", "operation": "circle", "args": {"center": [0, 0]}},
        ])
    assert cad("drawing", "info")["entities"] == before


def test_errors_are_helpful(cad):
    with pytest.raises(CadError, match="Signature"):
        cad("draw", "circle", center=[0, 0])
    with pytest.raises(CadError, match="Operations"):
        cad("draw", "nope")
    with pytest.raises(CadError, match="unknown argument"):
        cad("draw", "line", start=[0, 0], end=[1, 1], colour="red")


def test_python_tool_gate(cad, monkeypatch):
    monkeypatch.delenv("CAD_MCP_ALLOW_PYTHON", raising=False)
    with pytest.raises(CadError, match="disabled"):
        cad("python", "run", code="result = 1")
    monkeypatch.setenv("CAD_MCP_ALLOW_PYTHON", "1")
    out = cad("python", "run", code="msp.add_line((0,0),(1,1)); print('hi'); result = len(msp)")
    assert out["result"] == 1 and "hi" in out["stdout"]


def test_open_file_written_by_ezdxf_with_r12(cad):
    doc = ezdxf.new("R2000")
    doc.modelspace().add_circle((0, 0), 3)
    p = cad.tmp / "old.dxf"
    doc.saveas(p)
    cad("drawing", "open", path=str(p))
    assert cad("query", "count")["groups"] == {"CIRCLE": 1}


def test_hatch_islands_dimstyle_and_pdf_scale(cad):
    r = cad("draw", "hatch", boundary=[[[0, 0], [100, 0], [100, 100], [0, 100]],
                                       [[20, 20], [80, 20], [80, 80], [20, 80]]], pattern="ANSI31")
    h = ent(cad, r["handles"][0])
    assert h.dxf.hatch_style == 0 and len(h.paths) == 2
    assert math.isclose(cad("query", "area", sel=r["handles"])["total_area"], 100 * 100 - 60 * 60, rel_tol=1e-6)
    d = cad("annotate", "dim_linear", p1=[0, 0], p2=[8000, 0], location=[0, -500])["handles"][0]
    dim = ent(cad, d)
    assert dim.dxf.dimstyle == "Standard" and math.isclose(dim.get_measurement(), 8000)
    cad("view", "export", path="scale.pdf", paper="A3", scale=0.02)
    data = (cad.tmp / "scale.pdf").read_bytes()
    assert b"MediaBox [ 0 0 1190.55" in data  # A3 landscape in points


def test_dwg_roundtrip(cad):
    from cad_mcp import dwg

    if not dwg.oda_path():
        pytest.skip("ODA File Converter not installed")
    cad("draw", "circle", center=[0, 0], radius=5, layer="KOR")
    cad("annotate", "text", text="DWG próba", insert=[0, 10])
    try:
        cad("drawing", "save", path="kor.dwg")
    except CadError as exc:
        if "desktop session" in str(exc):
            pytest.skip("ODA needs a desktop session (sandboxed run)")
        raise
    assert (cad.tmp / "kor.dwg").read_bytes()[:6] == b"AC1032"
    cad("drawing", "open", path="kor.dwg", name="vissza")
    assert cad("query", "count")["groups"] == {"CIRCLE": 1, "TEXT": 1}
    assert cad("query", "find_text", pattern="próba")["count"] == 1
