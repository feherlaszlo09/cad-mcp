import math

import ezdxf

import pytest
from ezdxf import bbox

from tests.test_ops import ent


def _meas(cad, hs):
    return [round(ent(cad, h).get_measurement(), 6) for h in hs]


def test_qdim_and_dimspace(cad):
    for x in (0, 10, 25):
        cad("draw", "line", start=[x, 0], end=[x, 8])
    cont = cad("annotate", "qdim", sel={"type": "LINE"}, location=[0, -5])["handles"]
    assert _meas(cad, cont) == [10, 15]
    base = cad("annotate", "qdim", sel={"type": "LINE"}, location=[0, -20], mode="baseline", spacing=4)["handles"]
    assert _meas(cad, base) == [10, 25]
    d0 = cad("annotate", "dim_linear", p1=[0, 0], p2=[10, 0], location=[0, -40])["handles"][0]
    d1 = cad("annotate", "dim_linear", p1=[0, 0], p2=[20, 0], location=[0, -41])["handles"][0]
    d2 = cad("annotate", "dim_linear", p1=[0, 0], p2=[30, 0], location=[0, -50])["handles"][0]
    cad("annotate", "dim_space", base=d0, sel=[d1, d2], spacing=4)
    assert ent(cad, d1).dxf.defpoint.y == pytest.approx(-44) and ent(cad, d2).dxf.defpoint.y == pytest.approx(-48)


def test_dim_text_break_jogged(cad):
    d = cad("annotate", "dim_linear", p1=[0, 0], p2=[20, 0], location=[0, -5])["handles"][0]
    cad("annotate", "dim_text", handle=d, location=[30, -5], rotation=15, text="<> mm", oblique=60)
    dim = ent(cad, d)
    assert dim.dxf.text_midpoint.isclose((30, -5, 0)) and dim.dxf.text_rotation == 15 and dim.dxf.oblique_angle == 60
    cad("annotate", "dim_text", handle=d, home=True)
    # back in the middle of the dimension line, which the 60° oblique extension lines shift by 5/tan(60°)
    assert ent(cad, d).dxf.text_midpoint.x == pytest.approx(10 - 5 / math.tan(math.radians(60)))
    cad("draw", "line", start=[10, -10], end=[10, 5])
    parts = cad("annotate", "dim_break", handle=d, gap=1)["handles"]
    assert len([h for h in parts if ent(cad, h).dxftype() == "LINE"]) >= 4
    c = cad("draw", "circle", center=[0, 0], radius=100)["handles"][0]
    j = cad("annotate", "dim_jogged", handle=c, center_override=[20, 20])
    jd = ent(cad, j["handles"][0])
    assert j["native"] and jd.dxftype() == "LARGE_RADIAL_DIMENSION" and jd.dxf.dimtype & 15 == 9
    assert jd.dxf.chord_point.isclose((100 / math.sqrt(2), 100 / math.sqrt(2), 0)) and jd.dxf.override_center.isclose((20, 20, 0))
    blk = cad.dm().get().doc.blocks.get(jd.dxf.geometry)
    assert any(x.dxftype() == "TEXT" and x.dxf.text == "R100.00" for x in blk)
    cad("drawing", "save", path="jogged.dxf")
    back = ezdxf.readfile(cad.tmp / "jogged.dxf")
    assert len(back.modelspace().query("LARGE_RADIAL_DIMENSION")) == 1 and back.audit().has_errors is False


def test_tolerance_centerline_leaders(cad):
    t = cad("annotate", "tolerance", symbol="position", value="0.05", insert=[0, 0], datums=["A", "B"],
            diameter=True, material="M", height=3.5)
    tol = ent(cad, t["handles"][0])
    assert tol.dxftype() == "TOLERANCE" and tol.dxf.content == "{\\Fgdt;j}%%v{\\Fgdt;n}0.05{\\Fgdt;m}%%vA%%vB"
    assert cad.dm().get().doc.dimstyles.get(tol.dxf.dimstyle).dxf.dimtxt == 3.5
    a = cad("draw", "line", start=[0, 0], end=[20, 0])["handles"][0]
    b = cad("draw", "line", start=[20, 10], end=[0, 10])["handles"][0]
    cl = ent(cad, cad("annotate", "centerline", handle1=a, handle2=b)["handles"][0])
    assert cl.dxf.start.isclose((-2, 5, 0)) and cl.dxf.end.isclose((22, 5, 0)) and cl.dxf.linetype == "CENTER"
    ld = cad("annotate", "leader_classic", points=[[0, 0], [5, 5], [10, 5]], text="Áteresz D60")
    leader, mt = (ent(cad, h) for h in ld["handles"])
    assert leader.dxftype() == "LEADER" and leader.dxf.annotation_handle == mt.dxf.handle
    cad("style", "create_mleader_style", name="UT", char_height=3.5, arrow_size=3, has_frame=True)
    m1 = cad("annotate", "leader_styled", points=[[0, 0], [10, 10]], text="A", style="UT")["handles"][0]
    m2 = cad("annotate", "leader", points=[[0, -20], [8, -15]], text="B")["handles"][0]
    st = cad.dm().get().doc.mleader_styles.get("UT")
    assert ent(cad, m1).dxf.style_handle == st.dxf.handle and st.dxf.char_height == 3.5
    cad("annotate", "mleader_align", sel=[m1, m2], x=50)
    assert [round(ent(cad, h).context.mtext.insert.x, 6) for h in (m1, m2)] == [50, 50]


def test_justify_text_keeps_position(cad):
    t = cad("annotate", "text", text="Szelvény 0+100", insert=[10, 10], height=2.5)["handles"][0]
    before = bbox.extents([ent(cad, t)])
    cad("annotate", "justify_text", sel=[t], align="middle_center")
    after = bbox.extents([ent(cad, t)])
    assert ent(cad, t).dxf.halign == 1 and before.extmin.isclose(after.extmin, abs_tol=0.05)


def test_mline_style_fields_associative_dims(cad):
    cad("style", "create_mline_style", name="UT2", elements=[{"offset": 3.5, "color": "white"},
                                                             {"offset": 0, "color": "yellow", "linetype": "DASHED"},
                                                             {"offset": -3.5, "color": "white"}])
    ml = ent(cad, cad("draw", "mline", points=[[0, 0], [50, 0]], style="UT2")["handles"][0])
    assert ml.dxf.style_name == "UT2" and len(cad.dm().get().doc.mline_styles.get("UT2").elements) == 3
    rect = cad("draw", "rectangle", corner1=[0, 0], corner2=[10, 10])["handles"][0]
    f = cad("annotate", "field", insert=[0, -5], expression="area", handle=rect, suffix=" m²", decimals=1)
    assert f["text"] == "100.0 m²"
    cad("edit", "scale", sel=[rect], base=[0, 0], factor=2)
    ln = cad("draw", "line", start=[0, 30], end=[10, 30])["handles"][0]
    d = cad("annotate", "dim_linear", p1=[0, 30], p2=[10, 30], location=[0, 25])["handles"][0]
    cad("annotate", "dim_associate", dimension=d, p1_handle=ln, p1_point="start", p2_handle=ln, p2_point="end")
    cad("edit", "lengthen", handle=ln, total=17)
    u = cad("annotate", "update_fields")
    assert u == {"fields_updated": 1, "dimensions_updated": 1}
    assert ent(cad, f["handles"][0]).text == "400.0 m²" and ent(cad, d).get_measurement() == pytest.approx(17)
    assert math.isclose(ent(cad, d).dxf.defpoint.y, 25)
