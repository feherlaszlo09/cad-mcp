"""SVG -> AutoCAD block (filled areas as solid hatches, strokes as width polylines,
texts as TEXT) and the official KRESZ traffic sign library built on it (public-domain
SVGs from Wikimedia Commons, see assets/kresz/index.json)."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import numpy as np

from .core import CadError, Ctx, ensure_layer, op, vec

def _assets() -> Path:
    return Path(os.environ.get("CAD_MCP_KRESZ_DIR") or Path(__file__).resolve().parents[2] / "assets" / "kresz")


def _rgb(color):
    if color is None or getattr(color, "value", None) is None:
        return None
    if color.alpha == 0:
        return None
    return (color.red, color.green, color.blue)


def _sample(se, sub, unit: float) -> list[tuple[float, float]]:
    """Points of one subpath: line ends as they are, curves sampled by parameter with a count that keeps the
    chord error small relative to the drawing size `unit` (no slow arc-length maths)."""
    pts: list[tuple[float, float]] = []
    segs = sub.segments() if hasattr(sub, "segments") else se.Path(sub).segments()
    for seg in segs:
        if isinstance(seg, se.Move):
            if seg.end is not None:
                pts.append((float(seg.end.x), float(seg.end.y)))
        elif isinstance(seg, (se.Line, se.Close)):
            if seg.end is not None:
                pts.append((float(seg.end.x), float(seg.end.y)))
        else:
            ctrl = [q for q in (getattr(seg, "start", None), getattr(seg, "control", None),
                                getattr(seg, "control1", None), getattr(seg, "control2", None),
                                getattr(seg, "end", None)) if q is not None]
            hull = sum(math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(ctrl, ctrl[1:]))
            if isinstance(seg, se.Arc):
                hull = max(hull, abs(float(seg.sweep)) * max(float(seg.rx), float(seg.ry)))
            n = int(min(256, max(6, hull / (0.004 * unit) + 4)))
            for q in seg.npoint(np.linspace(0, 1, n + 1)[1:]):
                pts.append((float(q[0]), float(q[1])))
    return [q for q in pts if not (math.isnan(q[0]) or math.isnan(q[1]))]


def _area2(loop) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1]))


def _winding(px: float, py: float, loop) -> int:
    """Winding number of a closed loop around the point (ray casting with signed crossings)."""
    w = 0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        if y0 <= py < y1 or y1 <= py < y0:
            xc = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
            if xc > px:
                w += 1 if y1 > y0 else -1
    return w


def _fill_region(loops, rule: str):
    """Filled area of an SVG path's subpaths as shapely polygons (exteriors with holes), exactly by the fill rule:
    the subpaths are noded into faces and a face is filled when its winding number is odd (evenodd) or non-zero."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    rings = [loop for loop in loops if len(loop) >= 3]
    if not rings:
        return []
    lines = unary_union([LineString(list(r) + [r[0]]) for r in rings])
    keep = []
    for face in polygonize(lines):
        if face.area <= 0:
            continue
        q = face.representative_point()
        w = sum(_winding(q.x, q.y, r) for r in rings)
        if (w % 2 == 1) if rule == "evenodd" else (w != 0):
            keep.append(face)
    if not keep:
        return []
    region = unary_union(keep)
    geoms = [g for g in getattr(region, "geoms", [region]) if g.geom_type == "Polygon" and g.area > 0]
    return [piece for g in geoms for piece in _split_holes(g)]


def _split_holes(poly):
    """Holes whose bounding boxes overlap confuse bounding-box island detection (e.g. the ezdxf preview): cut such
    polygons into hole-free pieces with a vertical line through every hole."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import split

    holes = list(poly.interiors)
    if len(holes) < 2:
        return [poly]
    boxes = [h.bounds for h in holes]
    overlap = any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                  for i, a in enumerate(boxes) for b in boxes[i + 1:])
    if not overlap:
        return [poly]
    x0, y0, x1, y1 = poly.bounds
    cuts = []
    for h in holes:
        from shapely.geometry import Polygon

        x = Polygon(h).representative_point().x
        cuts.append(LineString([(x, y0 - 1), (x, y1 + 1)]))
    parts = split(poly, MultiLineString(cuts))
    return [g for g in parts.geoms if g.geom_type == "Polygon" and g.area > 0]


def _parse(path: Path):
    """Return a list of drawing items in SVG coordinates (y down)."""
    import svgelements as se

    svg = se.SVG.parse(str(path), reify=True)
    vb = getattr(svg, "viewbox", None)
    w = float(getattr(vb, "width", 0) or svg.width or 100)
    h = float(getattr(vb, "height", 0) or svg.height or 100)
    unit = math.hypot(w, h) or 100.0
    items = []
    for el in svg.elements():
        if isinstance(el, se.Text):
            if el.text and _rgb(el.fill):
                fs = float(el.font_size or 12)
                anchor = {"middle": "MIDDLE_CENTER", "end": "BOTTOM_RIGHT"}.get(getattr(el, "anchor", None), "BOTTOM_LEFT")
                items.append(("text", (float(el.x), float(el.y)), el.text, fs, _rgb(el.fill), anchor))
            continue
        if not isinstance(el, se.Shape):
            continue
        if el.values.get("visibility") == "hidden" or el.values.get("display") == "none":
            continue
        try:
            p = se.Path(el)
        except Exception:
            continue
        loops = []
        for sub in p.as_subpaths():
            loop = _sample(se, sub, unit)
            if len(loop) >= 2:
                loops.append(loop)
        if not loops:
            continue
        fill = _rgb(el.fill)
        areas = [loop for loop in loops if len(loop) >= 3 and abs(_area2(loop)) > 1e-12]
        if fill is not None and areas and float(el.values.get("fill-opacity", 1) or 1) > 0:
            rule = (el.values.get("fill-rule") or "nonzero").strip().lower()
            items.append(("fill", areas, fill, rule))  # lines have the SVG default fill but no area
        stroke = _rgb(el.stroke)
        sw = float(getattr(el, "stroke_width", 0) or 0)
        if stroke is not None and sw > 0:
            items.append(("stroke", loops, stroke, sw))
    if not items:
        raise CadError(f"Nothing drawable in {path.name}")
    return items


def svg_to_block(ctx: Ctx, path: Path, name: str, height: float = 1.0, post: float = 0.0, replace: bool = False) -> str:
    doc = ctx.doc
    if doc.blocks.get(name) is not None:
        if not replace:
            return name
        doc.blocks.delete_block(name, safe=False)
    items = _parse(path)
    xs = [x for it in items if it[0] != "text" for loop in it[1] for x, _ in loop]
    ys = [y for it in items if it[0] != "text" for loop in it[1] for _, y in loop]
    if not xs:
        raise CadError("SVG has no shapes")
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = height / max(maxy - miny, 1e-12)
    cx = (minx + maxx) / 2

    def tr(x, y):  # SVG y down -> drawing y up; sign face bottom-centre at (0, post)
        return ((x - cx) * s, (maxy - y) * s + post)

    blk = doc.blocks.new(name, base_point=(0, 0))
    if post > 0:
        blk.add_line((0, 0), (0, post))
    for it in items:
        if it[0] == "fill":
            for poly in _fill_region(it[1], it[3]):
                h = blk.add_hatch()
                h.dxf.hatch_style = 0
                ext = [tr(x, y) for x, y in poly.exterior.coords[:-1]]
                if _area2(ext) < 0:
                    ext.reverse()
                h.paths.add_polyline_path(ext, is_closed=True, flags=1)  # outer boundary counter-clockwise
                for hole in poly.interiors:
                    hp = [tr(x, y) for x, y in hole.coords[:-1]]
                    if _area2(hp) > 0:
                        hp.reverse()
                    h.paths.add_polyline_path(hp, is_closed=True, flags=0)  # holes clockwise
                h.set_solid_fill(style=0)  # normal style: holes stay open (set_solid_fill defaults to 1)
                h.rgb = it[2]
        elif it[0] == "stroke":
            for loop in it[1]:
                closed = len(loop) > 2 and math.dist(loop[0], loop[-1]) < 1e-6 * max(maxx - minx, 1)
                pl = blk.add_lwpolyline([tr(x, y) for x, y in (loop[:-1] if closed else loop)], close=closed,
                                        dxfattribs={"const_width": it[3] * s})
                pl.rgb = it[2]
        else:
            from ezdxf.enums import TextEntityAlignment

            _k, (x, y), text, fs, rgb, anchor = it
            t = blk.add_text(text, height=fs * s * 0.72)
            t.rgb = rgb
            t.set_placement(tr(x, y), align=TextEntityAlignment[anchor])
    return name


@op("block", "import_svg", mutates=True)
def import_svg(ctx: Ctx, path: str, name: str | None = None, height: float = 1.0, post: float = 0.0,
               replace: bool = False, insert=None, rotation: float = 0.0, space=None):
    """Turn an SVG drawing (logo, symbol, sign) into a block: filled areas become solid hatches in their colours, strokes become width polylines, texts become TEXT. height = block height; post > 0 adds a post line with the drawing above it. Optionally inserts it."""
    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    bname = name or re.sub(r"[^A-Za-z0-9_\-]", "_", p.stem).upper()
    svg_to_block(ctx, p, bname, float(height), float(post), replace)
    out = {"block": bname, "entities": len(ctx.doc.blocks.get(bname))}
    if insert is not None:
        ref = ctx.layout(space).add_blockref(bname, vec(insert), dxfattribs={"rotation": float(rotation)})
        out["handle"] = ref.dxf.handle
    return out


def _index() -> list[dict]:
    f = _assets() / "index.json"
    if not f.is_file():
        raise CadError(f"KRESZ sign library not found in {_assets()} (run scripts/fetch_kresz_signs.py)")
    return json.loads(f.read_text(encoding="utf-8"))


def _find(code: str) -> dict:
    idx = _index()
    key = code.strip().lower().replace(" ", "_")
    for d in idx:
        if d["code"].lower() == key or d["file"].lower() == key or d["file"].lower() == key + ".svg":
            return d
    cands = [d for d in idx if key in d["code"].lower()]
    if len(cands) == 1:
        return cands[0]
    raise CadError(f"No sign '{code}'. Search with road.kresz_list; e.g. {[d['code'] for d in (cands or idx)[:10]]}")


@op("road", "kresz_list")
def kresz_list(ctx: Ctx, search: str | None = None, limit: int = 100):
    """Official KRESZ sign library (public-domain SVGs from Wikimedia Commons): list or search codes and descriptions (e.g. 'sebesség', 'stop', 'C-031', 'parkoló')."""
    idx = _index()
    if search:
        rx = re.compile(re.escape(search), re.I)
        idx = [d for d in idx if rx.search(d["code"]) or rx.search(d.get("description", "")) or rx.search(d.get("name", ""))]
    return {"count": len(idx), "signs": [{"code": d["code"], "description": d.get("description", "")[:120]}
                                         for d in idx[:limit]]}


@op("road", "kresz_sign", mutates=True)
def kresz_sign(ctx: Ctx, code: str, insert, size: float = 3.0, rotation: float = 0.0, post: bool = True,
               layer: str = "KRESZ_TABLA", space=None):
    """Place an official KRESZ sign image (from the library, see road.kresz_list) as a block: size = sign face height in drawing units; post adds a short post with the base point at its foot."""
    d = _find(code)
    bname = "KRESZ_" + re.sub(r"[^A-Za-z0-9_\-]", "_", d["code"]).upper()
    svg_to_block(ctx, _assets() / d["file"], bname, 1.0, 0.6 if post else 0.0)
    ensure_layer(ctx.doc, layer)
    ref = ctx.layout(space).add_blockref(bname, vec(insert), dxfattribs={
        "layer": layer, "xscale": size, "yscale": size, "zscale": size, "rotation": float(rotation)})
    return {"handle": ref.dxf.handle, "block": bname, "sign": d["code"], "source": d.get("source")}


@op("road", "kresz_sign_at", mutates=True)
def kresz_sign_at(ctx: Ctx, name: str, station: float, code: str, offset: float = -6.0, size: float = 3.0,
                  facing: str = "forward", layer: str = "KRESZ_TABLA", space=None):
    """Place an official KRESZ sign at a station/offset of an alignment, facing traffic going forward (or backward)."""
    from .ops_road import _m, get_alignment

    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    x, y, h = al.point_at(float(station), float(offset))
    rot = math.degrees(h) - 90 if facing == "forward" else math.degrees(h) + 90
    return kresz_sign(ctx, code=code, insert=(x * m, y * m), size=size, rotation=rot, layer=layer, space=space)
