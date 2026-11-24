import math

import pytest

from cad_mcp.core import CadError
from tests.test_ops import ent

PIS = [[0, 0], [500, 0], [900, 300], [1400, 300]]


def _terrain_csv(path, step=20):
    lines = ["pont;x;y;z;kod"]
    i = 0
    for x in range(-100, 1501, step):
        for y in range(-150, 451, step):
            z = 100 + 0.01 * x + 2 * math.sin(y / 60)
            lines.append(f"P{i};{x};{y};{z:.3f};TEREP")
            i += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return i


def test_alignment_geometry_and_queries(cad):
    cad("drawing", "new", units="m")
    r = cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60],
            start_station=1000)
    assert [e["type"] for e in r["elements"]] == ["line", "spiral", "arc", "spiral", "line", "spiral", "arc",
                                                   "spiral", "line"]
    assert r["curves"][0]["A"] == pytest.approx(math.sqrt(400 * 80), abs=1e-3)
    # drawn end of the last element is the alignment end point
    last = ent(cad, r["handles"][-1])
    assert last.dxf.end.isclose((1400, 300, 0), abs_tol=1e-6)
    p = cad("road", "station_point", name="T1", station=1100, offset=3.5)
    assert p["point"] == pytest.approx([100, 3.5])
    q = cad("road", "station_of", name="T1", point=[1200, 296])
    assert q["offset"] == pytest.approx(-4, abs=1e-4)
    assert cad("road", "list")["alignments"][0]["name"] == "T1"
    with pytest.raises(CadError, match="overlap"):
        cad("road", "alignment", name="BAD", points=[[0, 0], [100, 0], [200, 100], [300, 100]],
            radii=[2000, 2000])


def test_alignment_survives_save_and_open(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60])
    cad("drawing", "save", path="ut.dxf")
    cad("drawing", "open", path="ut.dxf", name="ujra")
    assert cad("road", "station_point", name="T1", station=0)["point"] == pytest.approx([0, 0])


def test_stationing_lines_markings_table(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60])
    st = cad("road", "stationing", name="T1", interval=100, minor_interval=20)
    assert st["marks"] > 50
    assert cad("query", "find_text", pattern="0+100")["count"] >= 1
    assert cad("query", "find_text", pattern="KE ")["count"] == 2
    edges = cad("road", "offset_lines", name="T1", offsets=[-3.5, 3.5])["handles"]
    # the right edge is exactly 3.5 m from the axis everywhere
    pl = ent(cad, edges[0])
    for x, y in list(pl.get_points("xy"))[::40]:
        assert abs(cad("road", "station_of", name="T1", point=[x, y])["offset"] + 3.5) < 1e-3
    mk = cad("road", "marking", name="T1", offset=0, dash=3, gap=6, width=0.12)
    assert mk["pieces"] == math.ceil(1000 / 9) or mk["pieces"] > 100
    cad("road", "marking", name="T1", offset=3.25, solid=True)
    tb = cad("road", "curve_table", name="T1", insert=[0, -50])
    assert tb["handles"]


def test_terrain_import_surface_contours(cad):
    cad("drawing", "new", units="m")
    n = _terrain_csv(cad.tmp / "pontok.csv")
    r = cad("terrain", "import_points", path="pontok.csv", order="id,x,y,z,code")
    assert r["points"] == n and r["skipped_lines"] == 1
    s = cad("terrain", "surface", name="TEREP", sel={"layer": "GEODEZIA_PONTOK", "type": "POINT"})
    assert s["triangles"] > 2000
    z = cad("terrain", "elevation", name="TEREP", points=[[700, 90]])["elevations"][0]["z"]
    assert z == pytest.approx(100 + 7 + 2 * math.sin(90 / 60), abs=0.05)
    c = cad("terrain", "contours", name="TEREP", interval=1, major_every=5)
    assert c["contours"] > 10
    assert cad("terrain", "list")["surfaces"][0]["name"] == "TEREP"


def test_profile_and_cross_sections_from_surface(cad):
    cad("drawing", "new", units="m")
    _terrain_csv(cad.tmp / "pontok.csv")
    cad("terrain", "import_points", path="pontok.csv", label=False)
    cad("terrain", "surface", name="TEREP", sel={"type": "POINT"})
    cad("road", "alignment", name="T1", points=PIS, radii=[400, 300], spiral_lengths=[80, 60])
    along = cad("terrain", "along_alignment", name="TEREP", alignment="T1", step=50)["terrain"]
    assert along[0][0] == 0 and len(along) > 20
    pr = cad("road", "profile", name="T1", insert=[0, -200], surface="TEREP",
             vpis=[[0, 101], [600, 106], [1200, 110], [1458.1, 112]], radii=[8000, 6000])
    assert pr["curves"][0]["type"] in ("crest", "sag") and len(pr["grades_percent"]) == 3
    xs = cad("road", "cross_section", name="T1", station=300, insert=[0, -400], surface="TEREP")
    assert xs["cut_m2"] >= 0 and xs["fill_m2"] >= 0 and xs["cut_m2"] + xs["fill_m2"] > 0
    many = cad("road", "cross_sections", name="T1", insert=[0, -500], interval=100, surface="TEREP")
    assert len(many["sections"]) >= 10 and many["volume_cut_m3"] + many["volume_fill_m3"] > 0


def test_cross_section_area_exact(cad):
    cad("drawing", "new", units="m")
    cad("road", "alignment", name="E", points=[[0, 0], [100, 0]])
    xs = cad("road", "cross_section", name="E", station=50, insert=[0, 0], center_elevation=101,
             template=[{"width": 3.5, "slope": -2.5}], terrain=[[-30, 100], [30, 100]], fill_slope=1.5)
    edge = 1 - 3.5 * 0.025
    expected = 2 * ((1 + edge) / 2 * 3.5 + 0.5 * edge * 1.5 * edge)
    assert xs["fill_m2"] == pytest.approx(expected, abs=1e-3)  # output rounded to 3 decimals
    assert xs["cut_m2"] == pytest.approx(0, abs=1e-9)
    assert xs["daylight"]["right"][0] == pytest.approx(3.5 + 1.5 * edge, abs=1e-3)
