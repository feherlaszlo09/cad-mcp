"""Tests for the operations not exercised elsewhere, so every MCP operation is proven to run."""

import math

import ezdxf
import pytest

from cad_mcp.core import CadError
from tests.test_ops import ent


def test_remaining_draw_ops(cad, tmp_path):
    assert len(cad("draw", "lines", segments=[[[0, 0], [1, 0]], [[0, 1], [1, 1]]])["handles"]) == 2
    p3 = cad("draw", "polyline3d", points=[[0, 0, 0], [1, 0, 2], [1, 1, 3]])["handles"][0]
    assert ent(cad, p3).dxftype() == "POLYLINE" and ent(cad, p3).is_3d_polyline
    r = cad("draw", "ray", start=[0, 0], direction=[1, 1])["handles"][0]
    assert ent(cad, r).dxftype() == "RAY"
    w = cad("draw", "wipeout", points=[[0, 0], [5, 0], [5, 5]])["handles"][0]
    assert ent(cad, w).dxftype() == "WIPEOUT"
    from matplotlib import pyplot as plt

    img = tmp_path / "kep.png"
    plt.imsave(img, [[0, 1], [1, 0]])
    im = cad("draw", "image", path=str(img), insert=[10, 10], width=20)["handles"][0]
    assert ent(cad, im).dxftype() == "IMAGE"
    assert ent(cad, cad("draw3d", "face", points=[[0, 0, 0], [1, 0, 0], [1, 1, 1]])["handles"][0]).dxftype() == "3DFACE"
    assert ent(cad, cad("draw3d", "cone", base_center=[0, 0, 0], radius=2, height=5)["handles"][0]).dxftype() == "MESH"
    assert ent(cad, cad("draw3d", "torus", center=[0, 0, 0], major_radius=5, minor_radius=1)["handles"][0]).dxftype() == "MESH"
    m = cad("draw3d", "mesh", vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])["handles"][0]
    assert len(ent(cad, m).faces) == 1


def test_remaining_annotate_ops(cad):
    d = cad("annotate", "dim_arc_length", center=[0, 0], p1=[10, 0], p2=[0, 10], location=[12, 12])["handles"][0]
    assert ent(cad, d).dxftype() == "ARC_DIMENSION"
    t = cad("annotate", "text", text="régi", insert=[0, 0])["handles"][0]
    cad("annotate", "set_text", handle=t, text="új")
    assert ent(cad, t).dxf.text == "új"
    mt = cad("annotate", "mtext", text="a", insert=[0, 0])["handles"][0]
    cad("annotate", "set_text", handle=mt, text="sor1\nsor2")
    assert ent(cad, mt).plain_text() == "sor1\nsor2"


def test_remaining_drawing_ops(cad, tmp_path):
    cad("drawing", "new", name="A")
    cad("drawing", "new", name="B")
    assert {d["name"] for d in cad("drawing", "list")["open"]} == {"A", "B"}
    cad("drawing", "switch", name="A")
    assert cad("drawing", "list")["current"] == "A"
    cad("drawing", "set_var", values={"LTSCALE": 50})
    assert cad("drawing", "get_var", names=["LTSCALE"])["$LTSCALE"] == 50
    cad("drawing", "set_units", units="m")
    assert cad("drawing", "info")["units"] == "m"
    cad("block", "define", name="NEMKELL", entities=[{"tool": "draw", "operation": "point", "args": {"location": [0, 0]}}])
    cad("layer", "create", name="URES")
    pg = cad("drawing", "purge")
    assert "NEMKELL" in pg["removed_blocks"] and "URES" in pg["removed_layers"]
    assert "errors" in cad("drawing", "audit")
    src = ezdxf.new()
    src.modelspace().add_circle((0, 0), 1)
    src.saveas(tmp_path / "masik.dxf")
    assert cad("drawing", "import", path="masik.dxf")["imported_entities"] == 1
    cad("draw", "line", start=[0, 0], end=[1, 1])
    with pytest.raises(CadError, match="unsaved"):
        cad("drawing", "close")
    cad("drawing", "close", discard_changes=True)
    assert cad("drawing", "list")["current"] == "B"


def test_remaining_edit_ops(cad):
    ln = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    cad("edit", "lengthen", handle=ln, total=25)
    assert math.isclose(ent(cad, ln).dxf.end.x, 25)
    cad("edit", "lengthen", handle=ln, delta=-5)
    assert math.isclose(ent(cad, ln).dxf.end.x, 20)
    c = cad("draw", "circle", center=[0, 0], radius=1)["handles"][0]
    path = cad("draw", "arc", center=[0, 0], radius=50, start_angle=0, end_angle=180)["handles"][0]
    cp = cad("edit", "array_path", sel=[c], path_handle=path, count=5)["created"]
    assert len(cp) == 5 and ent(cad, cp[-1]).dxf.center.isclose((-50, 0, 0), abs_tol=1e-6)
    cad("edit", "set_geometry", handle=c, values={"radius": 7})
    assert ent(cad, c).dxf.radius == 7
    cad("edit", "draworder", sel=[c], mode="back")
    order = [h for h, _ in sorted(cad.dm().get().doc.modelspace().get_redraw_order(), key=lambda x: int(x[1], 16))]
    assert order[0] == c
    rect = cad("draw", "rectangle", corner1=[0, 0], corner2=[4, 2])["handles"][0]
    ex = cad("edit", "explode", sel=[rect])["created"]
    assert len(ex) == 4


def test_remaining_layer_ops(cad):
    cad("layer", "create_many", layers=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    cad("layer", "set_current", name="B")
    assert cad("layer", "list")["current"] == "B"
    cad("layer", "isolate", names=["A"])
    lst = {x["name"]: x for x in cad("layer", "list")["layers"]}
    assert lst["A"]["on"] and not lst["C"]["on"]
    cad("layer", "all_on")
    assert all(x["on"] for x in cad("layer", "list")["layers"])
    cad("draw", "line", start=[0, 0], end=[1, 0], layer="C")
    with pytest.raises(CadError, match="entities"):
        cad("layer", "delete", name="C")
    cad("layer", "delete", name="C", move_entities_to="A")
    assert "C" not in {x["name"] for x in cad("layer", "list")["layers"]}
    chk = cad("layer", "check_standards", rules={"allowed_layers": ["A"], "no_entities_on": ["A"]})
    assert chk["violations"] >= 2


def test_remaining_block_ops(cad, tmp_path):
    cad("block", "define", name="KUT", entities=[{"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 1}}])
    assert cad("block", "contents", name="KUT")["entities"][0]["type"] == "CIRCLE"
    cad("block", "redefine", name="KUT", entities=[{"tool": "draw", "operation": "rectangle", "args": {"corner1": [-1, -1], "corner2": [1, 1]}}])
    assert cad("block", "contents", name="KUT")["entities"][0]["type"] == "LWPOLYLINE"
    ref = cad("block", "insert", name="KUT", insert=[5, 5])["handle"]
    cad("block", "rename", name="KUT", new_name="AKNA")
    assert ent(cad, ref).dxf.name == "AKNA"
    with pytest.raises(CadError, match="references"):
        cad("block", "delete", name="AKNA")
    cad("block", "delete", name="AKNA", delete_references=True)
    assert all(b["name"] != "AKNA" for b in cad("block", "list")["blocks"])
    lib = ezdxf.new()
    blk = lib.blocks.new("TABLA_KRESZ")
    blk.add_circle((0, 0), 0.3)
    lib.saveas(tmp_path / "konyvtar.dxf")
    assert cad("block", "import", path="konyvtar.dxf", names=["TABLA_KRESZ"])["imported"] == ["TABLA_KRESZ"]
    x = cad("block", "attach_xref", path=str(tmp_path / "konyvtar.dxf"), insert=[0, 0], name="ALAP")
    assert x["xref"] == "ALAP" and any(b["name"] == "ALAP" and b["xref"] for b in cad("block", "list")["blocks"])


def test_remaining_layout_style_ops(cad):
    cad("layout", "create", name="Lap1", paper="A4", landscape=False)
    vp = cad("layout", "add_viewport", layout="Lap1", center=[105, 148], size=[180, 250], view_center=[0, 0], scale=0.01)
    cad("layout", "zoom_viewport", handle=vp["handle"], view_center=[100, 100], scale=0.002)
    v = ent(cad, vp["handle"])
    assert math.isclose(v.dxf.view_height, 250 / 0.002) and v.dxf.view_center_point.isclose((100, 100, 0))
    cad("layout", "rename", name="Lap1", new_name="Helyszinrajz")
    assert any(x["name"] == "Helyszinrajz" for x in cad("layout", "list")["layouts"])
    cad("layout", "delete", name="Helyszinrajz")
    assert all(x["name"] != "Helyszinrajz" for x in cad("layout", "list")["layouts"])
    assert any(s["name"] == "Standard" for s in cad("style", "list_text_styles")["styles"])
    u = cad("style", "units", units="m", linear_format=2, decimals=3)
    assert u["units"] == "m" and u["$LUPREC"] == 3
