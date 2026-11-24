import json
import zipfile

import ezdxf
import pytest
from PIL import Image

from tests.test_ops import ent


def _ext_drawing(path, layer="SRC_L"):
    d = ezdxf.new("R2018", setup=True)
    d.layers.add(layer, color=3, linetype="DASHDOT")
    d.styles.add("ROADTXT", font="arial.ttf")
    d.dimstyles.duplicate_entry("Standard", "ROADDIM")
    b = d.blocks.new("TABLA")
    b.add_circle((0, 0), 1)
    d.modelspace().add_circle((5, 5), 2, dxfattribs={"layer": layer})
    d.saveas(path)


def test_underlay_xclip_bind_xref_manage(cad):
    from matplotlib import pyplot as plt
    from ezdxf.xclip import XClip

    fig = plt.figure(figsize=(2, 2))
    fig.savefig(cad.tmp / "alap.pdf")
    plt.close(fig)
    u = cad("draw", "underlay", path="alap.pdf", insert=[0, 0], scale=10, clip=[[0, 0], [1, 0], [1, 1]])
    und = ent(cad, u["handles"][0])
    assert und.dxftype() == "PDFUNDERLAY" and und.clipping and len(und.boundary_path) == 3
    _ext_drawing(cad.tmp / "kulso.dxf")
    cad("block", "attach_xref", path=str(cad.tmp / "kulso.dxf"), name="ALAPTERKEP")
    ref = cad("block", "insert", name="ALAPTERKEP", insert=[0, 0])["handle"]
    cad("block", "xclip", handle=ref, boundary=[[0, 0], [6, 0], [6, 6]])
    xc = XClip(ent(cad, ref))
    assert xc.has_clipping_path and len(xc.get_wcs_clipping_path().vertices) == 3
    cad("block", "xclip", handle=ref, remove=True)
    assert not XClip(ent(cad, ref)).has_clipping_path
    lst = cad("block", "xref_manage")["xrefs"]
    assert lst[0]["name"] == "ALAPTERKEP" and lst[0]["found"] and lst[0]["references"] == 2  # attach inserts one too
    cad("block", "xref_manage", action="path", name="ALAPTERKEP", new_path=str(cad.tmp / "kulso.dxf"))
    b = cad("block", "bind_xref", name="ALAPTERKEP")
    blk = cad.dm().get().doc.blocks.get("ALAPTERKEP")
    assert not blk.block.is_xref and any(e.dxftype() == "CIRCLE" for e in blk) and b["entities"] >= 1
    cad("block", "attach_xref", path=str(cad.tmp / "kulso.dxf"), name="MASIK")
    cad("block", "insert", name="MASIK", insert=[0, 0])
    assert cad("block", "xref_manage", action="detach", name="MASIK")["references_removed"] == 2


def test_import_resources_page_setup_etransmit_convert(cad):
    _ext_drawing(cad.tmp / "sablon.dxf")
    r = cad("drawing", "import_resources", path="sablon.dxf", layers=["SRC_L"], text_styles=["ROADTXT"],
            dim_styles=["ROADDIM"], blocks=["TABLA"])
    doc = cad.dm().get().doc
    assert doc.layers.get("SRC_L").color == 3 and doc.styles.has_entry("ROADTXT") and doc.dimstyles.has_entry("ROADDIM")
    assert doc.blocks.get("TABLA") is not None and r["imported"]["blocks"] == ["TABLA"]
    cad("layout", "create", name="Lap")
    ps = cad("layout", "page_setup", name="Lap", paper="A1", landscape=True, plot_style="monochrome.ctb")
    lay = doc.paperspace("Lap")
    assert ps["paper_mm"] == [841, 594] and lay.dxf_layout.dxf.current_style_sheet == "monochrome.ctb"
    from matplotlib import pyplot as plt

    plt.imsave(cad.tmp / "foto.png", [[0, 1], [1, 0]])
    cad("draw", "image", path="foto.png", insert=[0, 0], width=10)
    cad("block", "attach_xref", path=str(cad.tmp / "sablon.dxf"), name="SABLON")
    z = cad("drawing", "etransmit", path="csomag.zip")
    names = zipfile.ZipFile(z["exported"]).namelist()
    assert {"foto.png", "sablon.dxf", "Atadasi_jegyzek.txt"} <= set(names) and any(n.endswith(".dxf") and n != "sablon.dxf" for n in names)
    _ext_drawing(cad.tmp / "a.dxf")
    _ext_drawing(cad.tmp / "b.dxf")
    c = cad("drawing", "convert_files", files=["a.dxf", "b.dxf"], to="dxf", version="R2000", out_folder="regi")
    assert len(c["converted"]) == 2 and ezdxf.readfile(c["converted"][0]).dxfversion == "AC1015"


def test_layer_states_translate_battman_array(cad):
    cad("layer", "create_many", layers=[{"name": "FAL", "color": 1}, {"name": "AJTO", "color": 3}])
    cad("layer", "state", action="save", name="Alap")
    cad("layer", "modify", name="FAL", on=False, color=5)
    cad("layer", "state", action="restore", name="Alap")
    la = {x["name"]: x for x in cad("layer", "list")["layers"]}
    assert la["FAL"]["on"] and la["FAL"]["color"] == 1
    assert cad("layer", "state", action="list")["states"] == ["Alap"]
    cad("draw", "line", start=[0, 0], end=[1, 0], layer="FAL")
    cad("layer", "translate", mapping={"FAL": {"name": "A-WALL", "color": 7, "lineweight": 0.5}, "AJTO": "A-DOOR"})
    la = {x["name"]: x for x in cad("layer", "list")["layers"]}
    assert "FAL" not in la and la["A-WALL"]["entities"] == 1 and la["A-WALL"]["lineweight"] == 50
    cad("block", "define", name="AKNA", entities=[{"tool": "draw", "operation": "circle", "args": {"center": [0, 0], "radius": 1}}])
    cad("block", "attdef", block="AKNA", tag="SZAM", insert=[0, 0], default="1")
    cad("block", "attdef", block="AKNA", tag="TIPUS", insert=[0, -2], default="D40")
    ref = cad("block", "insert", name="AKNA", insert=[0, 0], attributes={"SZAM": "7"})["handle"]
    cad("block", "edit_attdef", block="AKNA", tag="TIPUS", new_tag="ATMERO", prompt="Átmérő", order=["ATMERO", "SZAM"])
    blk = cad.dm().get().doc.blocks.get("AKNA")
    assert [a.dxf.tag for a in blk.attdefs()] == ["ATMERO", "SZAM"]
    assert {a.dxf.tag: a.dxf.text for a in ent(cad, ref).attribs} == {"ATMERO": "D40", "SZAM": "7"}
    c = cad("draw", "circle", center=[0, 50], radius=0.5)["handles"][0]
    arr = cad("edit", "array_block", sel=[c], rows=3, cols=4, row_spacing=2, col_spacing=3)
    m = ent(cad, arr["handle"])
    assert m.dxftype() == "INSERT" and m.mcount == 12
    cad("edit", "array_edit", handle=arr["handle"], rows=5, col_spacing=4)
    assert ent(cad, arr["handle"]).mcount == 20 and ent(cad, arr["handle"]).dxf.column_spacing == 4


def test_extract_and_similar(cad):
    for i in range(3):
        cad("block", "define", name=f"T{i}", entities=[{"tool": "draw", "operation": "point", "args": {"location": [0, 0]}}]) \
            if i == 0 else None
    for x in (0, 10, 20):
        cad("block", "insert", name="T0", insert=[x, 0], layer="TABLAK")
    cad("draw", "line", start=[0, 0], end=[3, 4], layer="TABLAK")
    r = cad("query", "extract", sel={"layer": "TABLAK"}, fields=["type", "block", "x", "length"], path="kivonat.csv",
            table_at=[0, -20])
    assert r["count"] == 4 and (cad.tmp / "kivonat.csv").read_text(encoding="utf-8-sig").startswith("type;block;x;length")
    assert any(row["length"] == 5 for row in r["rows"])
    first = r["rows"][0]
    s = cad("query", "similar", handle=cad("query", "list", sel={"type": "INSERT"})["entities"][0]["handle"])
    assert s["count"] == 3 and first["type"] in ("INSERT", "LINE")


def _write_ctb_like_autocad(ctb, path):
    """AutoCAD's CTB layout (4-byte header fields); ezdxf's own writer uses native 8-byte longs on 64-bit macOS."""
    import io
    import struct
    import zlib

    mem = io.StringIO()
    ctb.write_content(mem)
    body = (mem.getvalue() + chr(0)).encode()
    comp = zlib.compress(body)
    path.write_bytes(b"PIAFILEVERSION_2.0,CTBVER1,compress\r\npmzlibcodec" +
                     struct.pack("<LLL", zlib.adler32(comp), len(body), len(comp)) + comp)


def test_export_formats_plot_styles_publish_3d(cad):
    cad("draw", "line", start=[0, 0], end=[100, 0], color="red", lineweight=0.7)
    cad("draw", "circle", center=[50, 20], radius=10, color="yellow")
    for ext in ("jpg", "tiff", "eps"):
        assert (cad.tmp / f"x.{ext}").exists() is False
        cad("view", "export", path=f"x.{ext}", dpi=50)
        assert (cad.tmp / f"x.{ext}").stat().st_size > 500
    cad("view", "export", path="mono.png", plot_style="monochrome", dpi=60)
    img = Image.open(cad.tmp / "mono.png").convert("RGB")
    assert not any(r > 150 and g < 80 and b < 80 for r, g, b in img.get_flattened_data())  # no red left
    cad("view", "export", path="szin.png", dpi=60)
    img = Image.open(cad.tmp / "szin.png").convert("RGB")
    assert any(r > 150 and g < 80 and b < 80 for r, g, b in img.get_flattened_data())
    from ezdxf.addons import acadctb

    ctb = acadctb.new_ctb()
    ctb[1].color = (0, 0, 255)
    _write_ctb_like_autocad(ctb, cad.tmp / "kek.ctb")
    cad("view", "export", path="ctb.png", plot_style="kek.ctb", dpi=60)
    img = Image.open(cad.tmp / "ctb.png").convert("RGB")
    assert any(b > 150 and r < 80 and g < 80 for r, g, b in img.get_flattened_data())  # red is plotted blue
    cad("layout", "create", name="L1")
    cad("layout", "create", name="L2")
    pub = cad("view", "publish", path="terv.pdf")
    data = (cad.tmp / "terv.pdf").read_bytes()
    assert pub["pages"] >= 2 and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 2
    cad("draw3d", "box", origin=[0, 0, 0], size=[1, 2, 3])
    s = cad("view", "export_3d", path="test.stl", sel={"type": "MESH"})
    assert s["triangles"] == 12 and (cad.tmp / "test.stl").read_text().startswith("solid")
    o = cad("view", "export_3d", path="test.obj", sel={"type": "MESH"})
    txt = (cad.tmp / "test.obj").read_text()
    assert o["triangles"] == 12 and txt.count("\nv ") == 8 and txt.count("\nf ") == 12


def test_gis_import_geojson_shp_kml_gpx(cad):
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"nev": "Pont", "tipus": "A"}, "geometry": {"type": "Point", "coordinates": [19.04, 47.50]}},
        {"type": "Feature", "properties": {"nev": "Út", "tipus": "B"}, "geometry": {"type": "LineString", "coordinates": [[19.04, 47.50], [19.05, 47.51]]}},
        {"type": "Feature", "properties": {"nev": "Telek", "tipus": "B"}, "geometry": {"type": "Polygon", "coordinates": [[[19.04, 47.50], [19.041, 47.50], [19.041, 47.501], [19.04, 47.50]]]}},
    ]}
    (cad.tmp / "adat.geojson").write_text(json.dumps(gj), encoding="utf-8")
    r = cad("geo", "import_vector", path="adat.geojson", layer_field="tipus", label_field="nev")
    assert r["imported"] == {"point": 1, "line": 1, "polygon": 1}
    pt = cad("query", "list", sel={"type": "POINT"})["entities"][0]["location"]
    assert 640000 < pt[0] < 660000 and 235000 < pt[1] < 245000
    assert {"GIS_A", "GIS_B"} <= {x["name"] for x in cad("layer", "list")["layers"]}
    import shapefile

    with shapefile.Writer(str(cad.tmp / "utak")) as w:
        w.field("SZAM", "C")
        w.line([[[650000, 240000], [650100, 240050]]])
        w.record("4")
    (cad.tmp / "utak.prj").write_text(
        'PROJCS["HD72_EOV",GEOGCS["HD72",DATUM["Hungarian_Datum_1972",SPHEROID["GRS 1967",6378160,298.247167427]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Hotine_Oblique_Mercator_Azimuth_Center"],'
        'PARAMETER["latitude_of_center",47.1443937222222],PARAMETER["longitude_of_center",19.0485717777778],'
        'PARAMETER["azimuth",90],PARAMETER["rectified_grid_angle",90],PARAMETER["scale_factor",0.99993],'
        'PARAMETER["false_easting",650000],PARAMETER["false_northing",200000],UNIT["metre",1]]')
    r = cad("geo", "import_vector", path="utak.shp", layer="UTAK", label_field="SZAM")
    assert r["imported"]["line"] == 1
    line = [e for e in cad("query", "list", sel={"layer": "UTAK", "type": "LWPOLYLINE"})["entities"]][0]
    assert line["points"][0] == pytest.approx([650000, 240000], abs=0.5)  # EOV .prj -> EOV drawing
    kml = ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Híd</name>'
           '<Point><coordinates>19.05,47.5,0</coordinates></Point></Placemark></Document></kml>')
    (cad.tmp / "p.kml").write_text(kml, encoding="utf-8")
    assert cad("geo", "import_vector", path="p.kml", layer="KML", label_field="name")["imported"]["point"] == 1
    gpx = ('<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="47.5" lon="19.04"><ele>110</ele>'
           '<name>WP1</name></wpt><trk><trkseg><trkpt lat="47.5" lon="19.04"/><trkpt lat="47.501" lon="19.041"/></trkseg></trk></gpx>')
    (cad.tmp / "t.gpx").write_text(gpx, encoding="utf-8")
    g = cad("geo", "import_vector", path="t.gpx", layer="GPS")
    assert g["imported"] == {"point": 1, "line": 1, "polygon": 0}


def test_shape_and_layer_filter(cad):
    s = cad("draw", "shape", name="TRACK1", insert=[0, 0], size=2)
    e = ent(cad, s["handles"][0])
    assert e.dxftype() == "SHAPE" and e.dxf.name == "TRACK1"
    assert cad.dm().get().doc.styles.find_shx("ltypeshp.shx") is not None
    cad("layer", "create_many", layers=[{"name": "UT_TENGELY", "color": 1}, {"name": "UT_SZEL", "color": 3},
                                        {"name": "EPULET", "color": 1}])
    cad("layer", "modify", name="UT_SZEL", on=False)
    assert [x["name"] for x in cad("layer", "list", name="ut_*")["layers"]] == ["UT_TENGELY", "UT_SZEL"]
    assert [x["name"] for x in cad("layer", "list", name="UT*", on=True)["layers"]] == ["UT_TENGELY"]
    assert {x["name"] for x in cad("layer", "list", color="red")["layers"]} == {"UT_TENGELY", "EPULET"}


def test_attach_xref_relative_path_is_portable(cad):
    _ext_drawing(cad.tmp / "kulso.dxf")
    r = cad("block", "attach_xref", path=str(cad.tmp / "kulso.dxf"), name="REL", relative=True)
    assert r["file"] == "kulso.dxf"
    assert cad.dm().get().doc.blocks.get("REL").block.dxf.xref_path == "kulso.dxf"
    (cad.tmp / "sub").mkdir()
    r2 = cad("block", "attach_xref", path="kulso.dxf", name="REL2", relative_to="sub")
    assert r2["file"] == "../kulso.dxf"
    lst = {x["name"]: x for x in cad("block", "xref_manage")["xrefs"]}
    assert lst["REL"]["found"]
    assert cad("block", "bind_xref", name="REL")["entities"] >= 1
