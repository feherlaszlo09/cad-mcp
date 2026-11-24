"""The former partial items: EXTEND/JOIN for splines and ellipse arcs, FLATSHOT with hidden lines,
native layer states and layer filters, pavement design by e-UT 06.03.14:2026."""
import math

import ezdxf
import pytest

from tests.test_ops import ent


def test_extend_spline_both_ends_and_ellipse(cad):
    h = cad("draw", "spline", fit_points=[[0, 0], [10, 5], [20, 0], [30, 5]])["handles"][0]
    wall = cad("draw", "line", start=[45, -50], end=[45, 50])["handles"][0]
    before = ent(cad, h).construction_tool()
    mid = before.point(before.max_t * 0.5)
    r = cad("edit", "extend", handle=h, boundary=[wall])
    assert r["new_end"][0] == pytest.approx(45, abs=1e-6)
    after = ent(cad, h).construction_tool()
    assert after.control_points[-1][0] == pytest.approx(45, abs=1e-6)
    # the original part of the curve is unchanged (the end span was only continued)
    import numpy as np
    pts = np.array([tuple(p) for p in after.approximate(400)])
    assert np.min(np.linalg.norm(pts[:, :2] - [mid[0], mid[1]], axis=1)) < 1e-3
    wall2 = cad("draw", "line", start=[-20, -50], end=[-20, 50])["handles"][0]
    cad("edit", "extend", handle=h, pick=[0, 0], boundary=[wall2])
    assert ent(cad, h).construction_tool().control_points[0][0] == pytest.approx(-20, abs=1e-6)
    el = cad("draw", "ellipse", center=[100, 0], major_axis=[20, 0], ratio=0.5, start_angle=0, end_angle=90)["handles"][0]
    w3 = cad("draw", "line", start=[80, -50], end=[80, 50])["handles"][0]
    r = cad("edit", "extend", handle=el, boundary=[w3])
    assert r["extended_param_deg"] == pytest.approx(90, abs=1e-4)
    assert ent(cad, el).construction_tool().end_point.isclose((80, 0, 0), abs_tol=1e-5)


def test_join_with_spline_is_exact(cad):
    ln = cad("draw", "line", start=[0, 0], end=[10, 0])["handles"][0]
    arc = cad("draw", "arc", center=[10, 5], radius=5, start_angle=270, end_angle=360)["handles"][0]
    sp = cad("draw", "spline", fit_points=[[15, 5], [20, 12], [30, 10]])["handles"][0]
    j = cad("edit", "join", sel=[sp, ln, arc])
    assert j["type"] == "SPLINE" and len(j["created"]) == 1 and len(j["deleted"]) == 3
    bs = ent(cad, j["created"][0]).construction_tool()
    ends = {tuple(round(c, 6) for c in bs.point(0)), tuple(round(c, 6) for c in bs.point(bs.max_t))}
    assert ends == {(0, 0, 0), (30, 10, 0)}
    on_arc = [p for p in bs.approximate(600) if 10.01 < p.x < 14.99 and p.y < 4.99]
    assert on_arc and all(abs(math.hypot(p.x - 10, p.y - 5) - 5) < 1e-6 for p in on_arc)
    on_line = [p for p in bs.approximate(600) if p.x < 9.99]
    assert all(abs(p.y) < 1e-9 for p in on_line)


def test_flatshot_hidden_lines(cad):
    b = cad("draw3d", "box", origin=[0, 0, 0], size=[2, 3, 4])["handles"]
    top = cad("draw3d", "flatshot", sel=b, hidden=True)
    assert top["visible_edges"] == 4 and top["hidden_edges"] == 0
    iso = cad("draw3d", "flatshot", sel=b, direction=[1, 1, 1], hidden=True, origin=[50, 0])
    assert iso["visible_edges"] == 9 and iso["hidden_edges"] == 3  # the back corner's three edges
    layers = {ent(cad, h).dxf.layer for h in iso["handles"]}
    assert "FLATSHOT_TAKART" in layers
    assert cad.dm().get().doc.layers.get("FLATSHOT_TAKART").dxf.linetype == "HIDDEN"
    blk = cad("draw3d", "flatshot", sel=b, direction=[1, -1, 1], block="NEZET", origin=[100, 0])
    assert ent(cad, blk["handles"][0]).dxftype() == "INSERT" and blk["block"] == "NEZET"
    outline = cad("draw3d", "flatshot", sel=b, direction=[0, -1, 0], outline_only=True)
    assert outline["projected_area"] == pytest.approx(8)


def test_native_layer_states_and_filters(cad):
    cad("layer", "create_many", layers=[{"name": "UT_TENGELY", "color": 1}, {"name": "UT_SZEL", "color": "#ff8000"},
                                        {"name": "KOZMU", "color": 3, "linetype": "DASHED"}])
    cad("layer", "state", action="save", name="Alap", description="minden látszik")
    cad("layer", "state", action="save", name="Csak szín", properties=["color"])
    cad("layer", "modify", name="UT_TENGELY", on=False, color=5)
    cad("layer", "modify", name="KOZMU", frozen=True, linetype="CENTER")
    cad("layer", "modify", name="UT_SZEL", color=2)
    cad("drawing", "save", path="allapot.dxf")
    # what AutoCAD's Layer States Manager reads: LAYER table xdict -> ACAD_LAYERSTATES -> XRECORD per state
    doc = ezdxf.readfile(cad.tmp / "allapot.dxf")
    states = doc.layers.head.get_extension_dict()["ACAD_LAYERSTATES"]
    assert set(states.keys()) == {"Alap", "Csak szín"}
    tags = [(t.code, t.value) for t in states["Alap"].tags]
    assert (91, 2047) in tags and (301, "minden látszik") in tags and (302, "0") in tags
    assert any(c == 92 and (v & 0xFFFFFF) == 0xFF8000 for c, v in tags)
    cad("drawing", "open", path="allapot.dxf")
    cad("layer", "state", action="restore", name="csak szín")  # only colours
    la = {x["name"]: x for x in cad("layer", "list")["layers"]}
    assert la["UT_TENGELY"]["color"] == 1 and not la["UT_TENGELY"]["on"] and la["KOZMU"]["frozen"]
    assert la["UT_SZEL"].get("true_color") == "#ff8000"
    cad("layer", "state", action="restore", name="Alap")
    la = {x["name"]: x for x in cad("layer", "list")["layers"]}
    assert la["UT_TENGELY"]["on"] and not la["KOZMU"]["frozen"] and la["KOZMU"]["linetype"] == "DASHED"
    cad("layer", "state", action="delete", name="Csak szín")
    assert cad("layer", "state", action="list")["states"] == ["Alap"]
    f = cad("layer", "filter", action="create", name="Útrétegek", criteria={"name": "UT_*", "on": True})
    assert f["expression"] == 'NAME=="UT_*" AND ON=="True"'
    cad("layer", "filter", action="create", name="Közmű", layers=["KOZMU"])
    assert cad("layer", "filter", action="apply", name="útrétegek")["layers"] == ["UT_TENGELY", "UT_SZEL"]
    assert cad("layer", "filter", action="apply", name="Közmű")["layers"] == ["KOZMU"]
    cad("layer", "filter", action="create", name="Nem 0", expression='NOT NAME=="0" AND FROZEN=="False"')
    assert "0" not in cad("layer", "filter", action="apply", name="Nem 0")["layers"]
    cad("drawing", "save", path="szuro.dxf")
    lyd = ezdxf.readfile(cad.tmp / "szuro.dxf").layers.head.get_extension_dict()["ACLYDICTIONARY"]
    recs = [{t.code: t.value for t in lyd[k].tags} for k in lyd.keys()]
    assert {r[1] for r in recs} == {"AcLyLayerFilter", "AcLyLayerGroup"} and all(k.startswith("*A") for k in lyd.keys())
    cad("layer", "filter", action="delete", name="Közmű")
    assert [x["name"] for x in cad("layer", "filter")["filters"]] == ["Útrétegek", "Nem 0"]
    with pytest.raises(Exception, match="Unknown filter property"):
        cad("layer", "filter", action="create", name="x", criteria={"weight": 1})


def test_pavement_design_eut_06_03_14(cad):
    cad("drawing", "new", units="m")
    # ÁNET = r·s·w·m·Σ ÁNF·e = 0,5·1·0,9·1·(40·1,3 + 300·0,6 + 80·1,6 + 400·1,7) = 468 Et/nap
    r = cad("road", "pavement_design", anf={"B": 40, "C1n+C2": 300, "D": 80, "E+F": 400}, road="fout",
            growth_factor=1.3, insert=[0, 0])
    assert r["factors"]["ANET"] == pytest.approx(468) and r["factors"]["t_years"] == 20 and r["factors"]["n"] == 1.2
    assert r["MF_Et"] == round(1.25 * 365 * 1.2 * 20 * 1.3 * 468) and r["traffic_class"] == "E"
    assert r["min_E2m_MPa"] == 60 and r["E2m_choices_MPa"] == [60, 80]
    first = r["variants"][0]  # thinnest: 25 cm RBA on 60 MPa, 140 <> 190 interpolated, rounded up to 5 mm
    assert (first["burkolatalap_vastagsag_cm"], first["E2m_MPa"], first["aszfalt_osszvastagsag_mm"]) == ("25", 60, 170)
    assert r["pavement"][0]["thickness"] == pytest.approx(0.17) and r["pavement"][1]["thickness"] == pytest.approx(0.25)
    assert len(r["handles"]) >= 6
    # within 10% above the lower class bound the lower-bound value applies
    lo = cad("road", "pavement_design", mf_million=0.32, base="rba", e2m=40)
    assert [v["aszfalt_osszvastagsag_mm"] for v in lo["variants"]] == [110]
    # without interpolation: the class upper-bound value
    up = cad("road", "pavement_design", mf_million=0.5, base="rba", e2m=60, interpolate=False)
    assert sorted(v["aszfalt_osszvastagsag_mm"] for v in up["variants"]) == [110, 130, 150]
    a1 = cad("road", "pavement_design", mf_million=0.005, base="hidraulikus")
    assert a1["traffic_class"] == "A1" and [v["aszfalt_osszvastagsag_mm"] for v in a1["variants"]] == [60]
    rp = cad("road", "pavement_design", mf_million=150)
    assert rp["traffic_class"] == "R+" and not any("RBA" in v["burkolatalap"] for v in rp["variants"])
    assert cad("road", "pavement_design", kind="kerekpar")["variants"][2]["aszfalt"] == "legalább 40 mm egyrétegű"
    with pytest.raises(Exception, match="growth_factor"):
        cad("road", "pavement_design", anet=100)
    s = cad("road", "pavement_strengthening", deflections=[0.4, 0.45, 0.5, 0.42, 0.48, 0.39, 0.52, 0.47, 0.44, 0.46],
            pavement_type="hajlekony", mf_million=2)
    d = [0.4, 0.45, 0.5, 0.42, 0.48, 0.39, 0.52, 0.47, 0.44, 0.46]
    mean = sum(d) / 10
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / 9)
    assert s["u"] == 1.8 and s["s_m_mm"] == pytest.approx(mean + 1.8 * sd, abs=1e-4)
    assert s["s_eng_mm"] == pytest.approx(14.5 * 2e6 ** (-1 / 4.55), abs=1e-4) and not s["strengthening_needed"]
    hk = cad("road", "pavement_strengthening", deflections=[0.3] * 30, pavement_type="felig_merev", mf_million=50,
             base="hidraulikus")
    assert hk["s_eng_mm"] == 0.30 and hk["u"] == 1.64
