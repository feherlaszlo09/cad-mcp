import json

import pytest

from tests.test_ops import ent

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200" width="100" height="200">
  <rect x="0" y="0" width="100" height="200" fill="#0054a6"/>
  <g transform="translate(50,100)">
    <path d="M -30,0 A 30,30 0 1,0 30,0 A 30,30 0 1,0 -30,0 Z M -10,0 A 10,10 0 1,0 10,0 A 10,10 0 1,0 -10,0 Z"
          fill="#cc0000" fill-rule="evenodd"/>
  </g>
  <line x1="10" y1="190" x2="90" y2="190" stroke="#ffffff" stroke-width="4"/>
  <text x="50" y="40" font-size="20" fill="#ffffff" text-anchor="middle">P</text>
</svg>"""


def _write(tmp, name="proba.svg", text=SVG):
    p = tmp / name
    p.write_text(text, encoding="utf-8")
    return p


def test_import_svg_geometry_colours(cad):
    _write(cad.tmp)
    r = cad("block", "import_svg", path="proba.svg", name="PROBA", height=2.0, insert=[10, 10])
    blk = cad.dm().get().doc.blocks.get("PROBA")
    kinds = [e.dxftype() for e in blk]
    assert kinds.count("HATCH") == 2 and "LWPOLYLINE" in kinds and "TEXT" in kinds
    bg, ring = [e for e in blk if e.dxftype() == "HATCH"]
    assert bg.rgb == (0, 84, 166) and ring.rgb == (204, 0, 0)
    # 100 x 200 SVG scaled to height 2 -> scale 0.01; ring radii 0.3 and 0.1 -> area pi*(0.09-0.01)
    from ezdxf import path as ezpath
    from shapely.geometry import Polygon

    loops = [Polygon([(v.x, v.y) for v in p.flattening(0.0005)]) for p in ezpath.from_hatch(ring)]
    big, small = sorted(loops, key=lambda q: -q.area)
    assert big.area - small.area == pytest.approx(3.14159265 * (0.09 - 0.01), rel=5e-3)
    assert big.centroid.x == pytest.approx(0, abs=1e-6) and big.centroid.y == pytest.approx(1.0, abs=1e-3)
    line = next(e for e in blk if e.dxftype() == "LWPOLYLINE")
    assert line.dxf.const_width == pytest.approx(0.04) and line.rgb == (255, 255, 255)
    txt = next(e for e in blk if e.dxftype() == "TEXT")
    assert txt.dxf.text == "P" and txt.rgb == (255, 255, 255)
    assert ent(cad, r["handle"]).dxf.name == "PROBA"


def test_kresz_library_with_index(cad, monkeypatch):
    lib = cad.tmp / "kresz"
    lib.mkdir()
    _write(lib, "Hungary_road_sign_C-031.svg")
    (lib / "index.json").write_text(json.dumps([{"code": "C-031", "file": "Hungary_road_sign_C-031.svg",
                                                  "description": "Sebességkorlátozás", "license": "Public domain",
                                                  "source": "https://commons.wikimedia.org/wiki/File:x"}]), encoding="utf-8")
    monkeypatch.setenv("CAD_MCP_KRESZ_DIR", str(lib))
    cad("drawing", "new", units="m")
    assert cad("road", "kresz_list", search="sebesség")["signs"][0]["code"] == "C-031"
    s = cad("road", "kresz_sign", code="C-031", insert=[5, 5], size=2)
    blk = cad.dm().get().doc.blocks.get(s["block"])
    assert s["block"] == "KRESZ_C-031" and any(e.dxftype() == "LINE" for e in blk)  # post
    cad("road", "alignment", name="U", points=[[0, 0], [100, 0]])
    a = cad("road", "kresz_sign_at", name="U", station=30, code="c-031", offset=-5)
    assert ent(cad, a["handle"]).dxf.insert.isclose((30, -5, 0))
    with pytest.raises(Exception, match="No sign"):
        cad("road", "kresz_sign", code="X-999", insert=[0, 0])


def test_svg_fill_rules_and_holes(cad):
    """Rings (evenodd), nonzero holes and holes whose bounding boxes overlap (a prohibition sign: ring + bar)."""
    import math

    import pytest

    ring = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<rect width="100" height="100" fill="#ffffff"/>'
            '<path fill="#ff0000" fill-rule="evenodd" d="M50,5 A45,45 0 1 1 49.99,5 Z M50,15 A35,35 0 1 0 50.01,15 Z"/>'
            '<path fill="#ff0000" d="M10,10 H90 V90 H10 Z M30,30 V70 H70 V30 Z" transform="translate(200,0)"/>'
            '</svg>')
    (cad.tmp / "gyuru.svg").write_text(ring, encoding="utf-8")
    cad("drawing", "new", units="m")
    r = cad("block", "import_svg", path="gyuru.svg", name="GYURU", height=100)
    blk = cad.dm().get().doc.blocks.get("GYURU")
    reds = [e for e in blk if e.dxftype() == "HATCH" and e.rgb == (255, 0, 0)]
    from ezdxf.math import area as poly_area

    def hatch_area(h):
        ext = [p for p in h.paths if p.path_type_flags & 1]
        holes = [p for p in h.paths if not p.path_type_flags & 1]
        return sum(poly_area([v[:2] for v in p.vertices]) for p in ext) - sum(poly_area([v[:2] for v in p.vertices]) for p in holes)

    areas = sorted(hatch_area(h) for h in reds)
    assert r["entities"] >= 3
    # evenodd ring: π(45² − 35²) (sampled arcs), nonzero square frame: 80² − 40² (inner square wound the other way)
    assert areas[0] == pytest.approx(math.pi * (45 ** 2 - 35 ** 2), rel=2e-3)
    assert areas[1] == pytest.approx(80 ** 2 - 40 ** 2, rel=1e-6)
    # ring + diagonal bar: two holes with overlapping bounding boxes are cut into hole-free pieces
    from shapely.geometry import Point, box

    from cad_mcp.ops_svg import _fill_region

    outer = list(Point(0, 0).buffer(45, 256).exterior.coords)[:-1]
    inner = Point(0, 0).buffer(35, 256)
    from shapely.affinity import rotate

    bar = rotate(box(-60, -5, 60, 5), 45, origin=(0, 0))  # diagonal: the two half-disc holes' boxes overlap
    halves = [g for g in inner.difference(bar).geoms]
    loops = [outer] + [list(h.exterior.coords)[:-1] for h in halves]
    pieces = _fill_region(loops, "evenodd")
    assert all(len(p.interiors) == 0 for p in pieces)
    assert sum(p.area for p in pieces) == pytest.approx(Point(0, 0).buffer(45, 256).area - sum(h.area for h in halves), rel=1e-6)
