"""More AutoCAD commands added to the existing tools: MATCHPROP, DIVIDE, MEASURE,
OVERKILL, BOUNDARY, REVCLOUD, GROUP, DIMBASELINE/DIMCONTINUE, PEDIT, REVERSE,
FIND (replace), SCALETEXT, WBLOCK, MLINE, HELIX, CENTERMARK, ALIGN, SETBYLAYER,
LAYMRG, ATTSYNC, named VIEW/UCS, DWGPROPS."""

from __future__ import annotations

import math
import re

from ezdxf.math import Matrix44, Vec2, Vec3
from shapely.geometry import Point, Polygon
from shapely.ops import polygonize, unary_union

from . import dwg, geom
from .core import (CadError, Ctx, apply_props, finish, handles, op, pick_props, select_from,
                   vec, vecs)

# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@op("edit", "matchprop", mutates=True)
def matchprop(ctx: Ctx, source: str, sel, text_style: bool = True):
    """MATCHPROP: copy layer, color, linetype, lineweight, ltscale, transparency (and text height/style) from source to the selection."""
    src = ctx.entity(source)
    props = {}
    for k in ("layer", "linetype", "lineweight", "ltscale"):
        if src.dxf.hasattr(k):
            props[k] = src.dxf.get(k)
    if src.dxf.hasattr("true_color"):
        props["color"] = "#%02x%02x%02x" % src.rgb
    else:
        props["color"] = src.dxf.get("color", 256)
    targets = [e for e in select_from(ctx, sel) if e is not src]
    for e in targets:
        apply_props(ctx.doc, e, props)
        if src.dxf.hasattr("transparency"):
            e.dxf.transparency = src.dxf.transparency
        if text_style and src.dxftype() in ("TEXT", "MTEXT") and e.dxftype() == src.dxftype():
            e.dxf.style = src.dxf.style
            if src.dxftype() == "TEXT":
                e.dxf.height = src.dxf.height
            else:
                e.dxf.char_height = src.dxf.char_height
    return {"handles": handles(targets), "copied": sorted(props)}


def _signature(e) -> tuple | None:
    t = e.dxftype()
    r = lambda v: tuple(round(c, 6) for c in Vec3(v))  # noqa: E731
    lay = e.dxf.get("layer", "0")
    if t == "LINE":
        a, b = sorted([r(e.dxf.start), r(e.dxf.end)])
        return (t, lay, a, b)
    if t == "CIRCLE":
        return (t, lay, r(e.dxf.center), round(e.dxf.radius, 6))
    if t == "ARC":
        return (t, lay, r(e.dxf.center), round(e.dxf.radius, 6), round(e.dxf.start_angle % 360, 4),
                round(e.dxf.end_angle % 360, 4))
    if t == "POINT":
        return (t, lay, r(e.dxf.location))
    if t in ("TEXT", "MTEXT"):
        return (t, lay, r(e.dxf.insert), e.dxf.get("text", "") if t == "TEXT" else e.text)
    if t == "INSERT":
        return (t, lay, e.dxf.name, r(e.dxf.insert), round(e.dxf.rotation, 4))
    if t == "LWPOLYLINE":
        return (t, lay, e.closed, tuple(tuple(round(c, 6) for c in p) for p in e.get_points("xyb")))
    return None


@op("edit", "overkill", mutates=True)
def overkill(ctx: Ctx, sel=None, merge_collinear: bool = True, tolerance: float = 1e-6):
    """OVERKILL: delete duplicate objects and merge overlapping collinear lines on the same layer."""
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    seen: dict = {}
    deleted = []
    for e in ents:
        s = _signature(e)
        if s is None:
            continue
        if s in seen:
            e.get_layout().delete_entity(e)
            deleted.append(e)
        else:
            seen[s] = e
    merged = 0
    if merge_collinear:
        lines = [e for e in ents if e.is_alive and e.dxftype() == "LINE"]
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(lines):
                if not a.is_alive:
                    continue
                pa, pb = Vec2(a.dxf.start), Vec2(a.dxf.end)
                d = pb - pa
                if d.magnitude < tolerance:
                    continue
                u = d.normalize()
                for b in lines[i + 1:]:
                    if not b.is_alive or b.dxf.layer != a.dxf.layer:
                        continue
                    qa, qb = Vec2(b.dxf.start), Vec2(b.dxf.end)
                    off1 = abs(u.x * (qa.y - pa.y) - u.y * (qa.x - pa.x))
                    off2 = abs(u.x * (qb.y - pa.y) - u.y * (qb.x - pa.x))
                    if off1 > tolerance or off2 > tolerance:
                        continue
                    ts = sorted([0.0, d.magnitude, (qa - pa).dot(u), (qb - pa).dot(u)])
                    ta, tb = sorted([(qa - pa).dot(u), (qb - pa).dot(u)])
                    if ta > d.magnitude + tolerance or tb < -tolerance:
                        continue  # no overlap / touch
                    a.dxf.start = Vec3(pa + u * ts[0])
                    a.dxf.end = Vec3(pa + u * ts[-1])
                    b.get_layout().delete_entity(b)
                    deleted.append(b)
                    merged += 1
                    changed = True
                    break
                if changed:
                    break
    return {"deleted": len(deleted), "merged_lines": merged}


@op("edit", "reverse", mutates=True)
def reverse(ctx: Ctx, sel):
    """REVERSE: flip the direction of lines, polylines, arcs and splines."""
    out = []
    for e in select_from(ctx, sel):
        t = e.dxftype()
        if t == "LINE":
            e.dxf.start, e.dxf.end = e.dxf.end, e.dxf.start
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyb"))
            n = len(pts)
            # segment i of the reversed polyline is original segment n-2-i walked backwards;
            # for closed polylines index -1 is the closing segment
            new = [(pts[n - 1 - i][0], pts[n - 1 - i][1],
                    -pts[n - 2 - i][2] if (i < n - 1 or e.closed) else 0.0) for i in range(n)]
            e.set_points(new, format="xyb")
        elif t == "ARC":
            continue  # ARC is always counter-clockwise in DXF
        elif t == "SPLINE":
            e.reverse()
        else:
            continue
        out.append(e)
    return {"handles": handles(out)}


@op("edit", "pedit", mutates=True)
def pedit(ctx: Ctx, handle: str, close: bool | None = None, width: float | None = None,
          decurve: bool = False, from_line: bool = False):
    """PEDIT: close/open a polyline, set constant width, remove arcs (decurve); from_line=true turns a LINE or ARC into a polyline first."""
    e = ctx.entity(handle)
    if e.dxftype() in ("LINE", "ARC") and from_line:
        from .ops_edit import _segments

        segs = _segments(e)
        verts = [(s.x, s.y, b) for s, _, b in segs] + [(segs[-1][1].x, segs[-1][1].y, 0.0)]
        lay = e.get_layout()
        new = lay.add_lwpolyline(verts, format="xyb")
        for k in ("layer", "color", "linetype", "lineweight"):
            if e.dxf.hasattr(k):
                new.dxf.set(k, e.dxf.get(k))
        lay.delete_entity(e)
        e = new
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("pedit works on LWPOLYLINE (use from_line=true for a LINE/ARC)")
    if close is not None:
        e.closed = bool(close)
    if width is not None:
        e.dxf.const_width = float(width)
    if decurve:
        e.set_points([(x, y, 0.0) for x, y, _ in e.get_points("xyb")], format="xyb")
    return {"handle": e.dxf.handle, "closed": e.closed}


@op("edit", "align", mutates=True)
def align(ctx: Ctx, sel, src1, dst1, src2=None, dst2=None, scale: bool = False):
    """ALIGN: move src1 onto dst1; with a second pair also rotate (and scale if scale=true) so src2 lines up with dst2."""
    ents = select_from(ctx, sel)
    s1, d1 = vec(src1), vec(dst1)
    m = Matrix44.translate(-s1.x, -s1.y, 0)
    if src2 is not None and dst2 is not None:
        s2, d2 = vec(src2), vec(dst2)
        a_src = math.atan2(s2.y - s1.y, s2.x - s1.x)
        a_dst = math.atan2(d2.y - d1.y, d2.x - d1.x)
        m = Matrix44.chain(m, Matrix44.z_rotate(a_dst - a_src))
        if scale:
            f = d1.distance(d2) / max(s1.distance(s2), 1e-12)
            m = Matrix44.chain(m, Matrix44.scale(f))
    m = Matrix44.chain(m, Matrix44.translate(d1.x, d1.y, 0))
    for e in ents:
        e.transform(m)
    return {"handles": handles(ents)}


@op("edit", "setbylayer", mutates=True)
def setbylayer(ctx: Ctx, sel):
    """SETBYLAYER: set color, linetype and lineweight of the selection to BYLAYER."""
    ents = select_from(ctx, sel)
    for e in ents:
        apply_props(ctx.doc, e, {"color": 256, "linetype": "BYLAYER", "lineweight": -1})
    return {"handles": handles(ents)}


@op("edit", "group", mutates=True)
def group(ctx: Ctx, sel, name: str | None = None, description: str = ""):
    """GROUP: make a named group of the selection (select it later with sel={"group": name} via query.group_members)."""
    ents = select_from(ctx, sel)
    g = ctx.doc.groups.new(name=name, description=description) if name else ctx.doc.groups.new(description=description)
    g.extend(ents)
    return {"group": g.dxf.name if hasattr(g.dxf, "name") else name, "handles": handles(ents)}


@op("edit", "ungroup", mutates=True)
def ungroup(ctx: Ctx, name: str):
    """UNGROUP: dissolve a group (entities stay)."""
    if name not in ctx.doc.groups:
        raise CadError(f"No group '{name}'. Groups: {[n for n, _ in ctx.doc.groups]}")
    ctx.doc.groups.delete(name)
    return {"ungrouped": name}


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@op("query", "groups")
def groups(ctx: Ctx):
    """List named groups with their member handles."""
    return {"groups": [{"name": n, "description": g.get_description() if hasattr(g, "get_description") else "",
                        "handles": [e.dxf.handle for e in g]} for n, g in ctx.doc.groups]}


# ---------------------------------------------------------------------------
# draw
# ---------------------------------------------------------------------------


def _points_along(ctx: Ctx, handle: str, distances) -> list[tuple[Vec2, float]]:
    shape = geom.to_shape(ctx.entity(handle))
    if shape is None:
        raise CadError("Entity has no path")
    out = []
    for d in distances:
        p = shape.interpolate(d)
        q = shape.interpolate(min(shape.length, d + 1e-6))
        q0 = shape.interpolate(max(0.0, d - 1e-6))
        ang = math.degrees(math.atan2(q.y - q0.y, q.x - q0.x))
        out.append((Vec2(p.x, p.y), ang))
    return out


def _place(ctx: Ctx, lay, pts, block, align, props):
    created = []
    for p, ang in pts:
        if block:
            e = lay.add_blockref(block, (p.x, p.y), dxfattribs={"rotation": ang if align else 0})
        else:
            e = lay.add_point((p.x, p.y))
        created.append(finish(ctx.doc, e, props))
    return created


@op("draw", "divide", mutates=True)
def divide(ctx: Ctx, handle: str, segments: int, block: str | None = None, align: bool = True, **props):
    """DIVIDE: place points (or block references) dividing an entity into equal segments."""
    shape = geom.to_shape(ctx.entity(handle))
    if shape is None or segments < 2:
        raise CadError("Need a curve entity and segments >= 2")
    L = shape.length
    n = segments if shape.is_ring else segments - 1
    ds = [L * i / segments for i in range(1, n + 1)] if not shape.is_ring else [L * i / segments for i in range(segments)]
    pts = _points_along(ctx, handle, ds)
    created = _place(ctx, ctx.entity(handle).get_layout(), pts, block, align, pick_props(props))
    return {"handles": handles(created)}


@op("draw", "measure", mutates=True)
def measure(ctx: Ctx, handle: str, length: float, block: str | None = None, align: bool = True, **props):
    """MEASURE: place points (or blocks) every `length` along an entity from its start."""
    shape = geom.to_shape(ctx.entity(handle))
    if shape is None or length <= 0:
        raise CadError("Need a curve entity and a positive length")
    ds, d = [], length
    while d < shape.length - 1e-9:
        ds.append(d)
        d += length
    pts = _points_along(ctx, handle, ds)
    created = _place(ctx, ctx.entity(handle).get_layout(), pts, block, align, pick_props(props))
    return {"handles": handles(created)}


def boundary_polygon(ctx: Ctx, point, sel=None, space=None):
    ents = select_from(ctx, sel if sel is not None else {"all": True, "space": space})
    shapes = []
    for e in ents:
        if e.dxftype() in ("TEXT", "MTEXT", "DIMENSION", "HATCH", "POINT"):
            continue
        s = geom.to_shape(e)
        if s is not None:
            shapes.extend(s.geoms if s.geom_type == "MultiLineString" else [s])
    if not shapes:
        raise CadError("No linework to build a boundary from")
    noded = unary_union(shapes)
    p = Point(*vec(point).vec2)
    best = None
    for poly in polygonize(noded):
        if poly.contains(p) and (best is None or poly.area < best.area):
            best = poly
    if best is None:
        raise CadError("The point is not inside a closed area formed by the selected objects")
    # polygonize returns the face with its islands as interior rings: split into outline + islands
    outer = Polygon(best.exterior.coords)
    islands = [Polygon(r.coords) for r in best.interiors]
    return outer, islands


@op("draw", "boundary", mutates=True)
def boundary(ctx: Ctx, point, sel=None, space=None, islands: bool = True, **props):
    """BOUNDARY: closed polyline around the smallest area enclosing point, formed by existing lines/arcs/polylines (islands too)."""
    poly, holes = boundary_polygon(ctx, point, sel, space)
    lay = ctx.layout(space)
    created = [lay.add_lwpolyline(list(poly.exterior.coords)[:-1], close=True)]
    if islands:
        created += [lay.add_lwpolyline(list(h.exterior.coords)[:-1], close=True) for h in holes]
    for e in created:
        finish(ctx.doc, e, pick_props(props))
    return {"handles": handles(created), "area": round(poly.area - sum(h.area for h in holes), 6)}


@op("draw", "hatch_pick", mutates=True)
def hatch_pick(ctx: Ctx, point, pattern: str = "SOLID", scale: float = 1.0, angle: float = 0, sel=None,
               space=None, **props):
    """BHATCH with pick point: hatch the closed area around point (islands left empty)."""
    from .ops_draw import hatch

    poly, holes = boundary_polygon(ctx, point, sel, space)
    loops = [[list(c) for c in list(poly.exterior.coords)[:-1]]]
    loops += [[list(c) for c in list(h.exterior.coords)[:-1]] for h in holes]
    return hatch(ctx, boundary=loops, pattern=pattern, scale=scale, angle=angle, space=space, **props)


@op("draw", "revcloud", mutates=True)
def revcloud(ctx: Ctx, points=None, handle: str | None = None, arc_length: float = 10.0, space=None, **props):
    """REVCLOUD: revision cloud along a closed outline (points or a closed entity)."""
    if handle:
        shape = geom.to_shape(ctx.entity(handle))
    elif points:
        pts = [tuple(vec(p).vec2) for p in points]
        shape = LineStringClosed(pts)
    else:
        raise CadError("Give points or handle")
    L = shape.length
    n = max(3, int(L / arc_length))
    verts = []
    for i in range(n):
        p = shape.interpolate(L * i / n)
        verts.append((p.x, p.y))
    area = Polygon(verts).exterior.is_ccw
    bulge = -0.6 if area else 0.6  # arcs bulge outward
    e = ctx.layout(space).add_lwpolyline([(x, y, bulge) for x, y in verts], format="xyb", close=True)
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle]}


def LineStringClosed(pts):
    from shapely.geometry import LineString

    return LineString(pts + [pts[0]])


@op("draw", "mline", mutates=True)
def mline(ctx: Ctx, points, scale: float = 1.0, justification: str = "zero", closed: bool = False,
          style: str = "Standard", space=None, **props):
    """MLINE: multiline (parallel lines) through points; scale = spacing factor; justification top|zero|bottom."""
    just = {"top": 0, "zero": 1, "bottom": 2}.get(justification.lower())
    if just is None:
        raise CadError("justification must be top, zero or bottom")
    e = ctx.layout(space).add_mline(vecs(points, 2), close=closed,
                                    dxfattribs={"style_name": style, "scale_factor": float(scale),
                                                "justification": just})
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle]}


@op("draw3d", "helix", mutates=True)
def helix(ctx: Ctx, base_center, radius: float, pitch: float, turns: float, ccw: bool = True,
          space=None, **props):
    """HELIX: 3D spiral around +Z from base_center."""
    e = ctx.layout(space).add_helix(float(radius), float(pitch), float(turns), ccw=ccw)
    c = vec(base_center)
    e.transform(Matrix44.translate(c.x, c.y, c.z))
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle]}


# ---------------------------------------------------------------------------
# annotate
# ---------------------------------------------------------------------------


def _linear_parts(ctx: Ctx, handle):
    d = ctx.entity(handle)
    if d.dxftype() != "DIMENSION" or (d.dimtype & 7) not in (0, 1):
        raise CadError("Base must be a linear or aligned DIMENSION")
    return d


@op("annotate", "dim_continue", mutates=True)
def dim_continue(ctx: Ctx, base: str, points: list, text_height: float | None = None,
                 arrow_size: float | None = None):
    """DIMCONTINUE: chain of dimensions continuing from a linear dimension's second point through each new point, same dimension line."""
    from .ops_annotate import _override

    d = _linear_parts(ctx, base)
    loc = d.dxf.defpoint
    prev = d.dxf.defpoint3
    angle = d.dxf.get("angle", 0)
    lay = d.get_layout()
    created = []
    for p in points:
        nd = lay.add_linear_dim(base=loc, p1=prev, p2=vec(p), angle=angle, dimstyle=d.dxf.dimstyle,
                                override=_override(text_height, arrow_size, None, None))
        nd.render()
        nd.dimension.dxf.layer = d.dxf.layer
        created.append(nd.dimension)
        prev = vec(p)
    return {"handles": handles(created)}


@op("annotate", "dim_baseline", mutates=True)
def dim_baseline(ctx: Ctx, base: str, points: list, spacing: float, text_height: float | None = None,
                 arrow_size: float | None = None):
    """DIMBASELINE: dimensions all measured from the base dimension's first point, each dimension line `spacing` further out."""
    from .ops_annotate import _override

    d = _linear_parts(ctx, base)
    p1 = d.dxf.defpoint2
    angle = d.dxf.get("angle", 0)
    loc = Vec3(d.dxf.defpoint)
    # direction away from the measured points
    mid = (Vec3(d.dxf.defpoint2) + Vec3(d.dxf.defpoint3)) / 2
    n = Vec3(-math.sin(math.radians(angle)), math.cos(math.radians(angle)), 0)
    if (loc - mid).dot(n) < 0:
        n = -n
    lay = d.get_layout()
    created = []
    for i, p in enumerate(points, start=1):
        nd = lay.add_linear_dim(base=loc + n * spacing * i, p1=p1, p2=vec(p), angle=angle,
                                dimstyle=d.dxf.dimstyle, override=_override(text_height, arrow_size, None, None))
        nd.render()
        nd.dimension.dxf.layer = d.dxf.layer
        created.append(nd.dimension)
    return {"handles": handles(created)}


@op("annotate", "find_replace", mutates=True)
def find_replace(ctx: Ctx, find: str, replace: str, regex: bool = False, case_sensitive: bool = False,
                 space=None):
    """FIND/REPLACE in TEXT, MTEXT, block attributes and dimension text overrides."""
    flags = 0 if case_sensitive else re.I
    rx = re.compile(find if regex else re.escape(find), flags)
    changed = []
    for e in ctx.layout(space):
        t = e.dxftype()
        if t in ("TEXT",) and rx.search(e.dxf.text):
            e.dxf.text = rx.sub(replace, e.dxf.text)
            changed.append(e.dxf.handle)
        elif t == "MTEXT" and rx.search(e.text):
            e.text = rx.sub(replace, e.text)
            changed.append(e.dxf.handle)
        elif t == "DIMENSION" and rx.search(e.dxf.get("text", "")):
            e.dxf.text = rx.sub(replace, e.dxf.text)
            e.override().render()
            changed.append(e.dxf.handle)
        elif t == "INSERT":
            for a in e.attribs:
                if rx.search(a.dxf.text):
                    a.dxf.text = rx.sub(replace, a.dxf.text)
                    changed.append(a.dxf.handle)
    return {"replaced_in": len(changed), "handles": changed}


@op("annotate", "scale_text", mutates=True)
def scale_text(ctx: Ctx, sel, height: float | None = None, factor: float | None = None):
    """SCALETEXT: set text height, or multiply it by factor, keeping insertion points."""
    out = []
    for e in select_from(ctx, sel):
        key = {"TEXT": "height", "ATTRIB": "height", "MTEXT": "char_height"}.get(e.dxftype())
        if not key:
            continue
        cur = e.dxf.get(key)
        e.dxf.set(key, float(height) if height else cur * float(factor or 1))
        out.append(e)
    return {"handles": handles(out)}


@op("annotate", "centermark", mutates=True)
def centermark(ctx: Ctx, handle: str, size: float | None = None, extend: float = 2.0, layer: str | None = None):
    """CENTERMARK: center cross on a circle or arc (lines reaching `extend` beyond the radius)."""
    e = ctx.entity(handle)
    if e.dxftype() not in ("CIRCLE", "ARC"):
        raise CadError("centermark needs a CIRCLE or ARC")
    c, r = Vec3(e.dxf.center), e.dxf.radius
    half = r + extend if size is None else size / 2
    lay = e.get_layout()
    attribs = {"layer": layer or e.dxf.layer}
    if ctx.doc.linetypes.has_entry("CENTER"):
        attribs["linetype"] = "CENTER"
    else:
        from .core import ensure_linetype

        ensure_linetype(ctx.doc, "CENTER")
        attribs["linetype"] = "CENTER"
    if layer and not ctx.doc.layers.has_entry(layer):
        ctx.doc.layers.add(layer)
    l1 = lay.add_line(c - Vec3(half, 0, 0), c + Vec3(half, 0, 0), dxfattribs=attribs)
    l2 = lay.add_line(c - Vec3(0, half, 0), c + Vec3(0, half, 0), dxfattribs=attribs)
    return {"handles": handles([l1, l2])}


# ---------------------------------------------------------------------------
# layer / block
# ---------------------------------------------------------------------------


@op("layer", "merge", mutates=True)
def layer_merge(ctx: Ctx, sources: list[str], target: str):
    """LAYMRG: move everything from source layers to target and delete the sources."""
    doc = ctx.doc
    if not doc.layers.has_entry(target):
        doc.layers.add(target)
    moved = 0
    srcs = {s.lower() for s in sources}
    for lay in doc.layouts_and_blocks():
        for e in lay:
            if e.dxf.get("layer", "0").lower() in srcs:
                e.dxf.layer = target
                moved += 1
    for s in sources:
        if doc.layers.has_entry(s) and s not in ("0", "Defpoints") and s.lower() != target.lower():
            doc.layers.remove(s)
    return {"moved": moved, "target": target}


@op("block", "sync_attributes", mutates=True)
def sync_attributes(ctx: Ctx, name: str):
    """ATTSYNC: make every reference of a block carry exactly the block's attribute definitions (keeps existing values)."""
    blk = ctx.doc.blocks.get(name)
    if blk is None:
        raise CadError(f"Block '{name}' does not exist")
    defs = {a.dxf.tag: a for a in blk.attdefs()}
    n = 0
    for lay in ctx.doc.layouts_and_blocks():
        for ref in lay:
            if ref.dxftype() != "INSERT" or ref.dxf.name != name:
                continue
            values = {a.dxf.tag: a.dxf.text for a in ref.attribs}
            for a in list(ref.attribs):
                ref.delete_attrib(a.dxf.tag)
            ref.add_auto_attribs({t: values.get(t, d.dxf.text) for t, d in defs.items()})
            n += 1
    return {"block": name, "references_synced": n, "tags": list(defs)}


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------


@op("drawing", "wblock")
def wblock(ctx: Ctx, sel, path: str, base_point=(0, 0)):
    """WBLOCK: write the selection to a new .dxf/.dwg file (base_point becomes the origin)."""
    from ezdxf import xref

    ents = select_from(ctx, sel)
    new = xref.write_block(ents, origin=vec(base_point))
    p = ctx.resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".dwg":
        dwg.write_dwg(new, p)
    else:
        new.saveas(p)
    return {"written": str(p), "entities": len(new.modelspace())}


@op("drawing", "named_view", mutates=True)
def named_view(ctx: Ctx, name: str, region: list | None = None, delete: bool = False):
    """VIEW: save a named view of a model region [[x1,y1],[x2,y2]] (or delete it). Without region lists views."""
    doc = ctx.doc
    if delete:
        doc.views.remove(name)
        return {"deleted": name}
    if region is None:
        return {"views": [{"name": v.dxf.name, "center": list(v.dxf.center), "width": v.dxf.width,
                           "height": v.dxf.height} for v in doc.views]}
    (x1, y1), (x2, y2) = [tuple(vec(p).vec2) for p in region]
    if doc.views.has_entry(name):
        doc.views.remove(name)
    v = doc.views.new(name)
    v.dxf.center = ((x1 + x2) / 2, (y1 + y2) / 2)
    v.dxf.width = abs(x2 - x1)
    v.dxf.height = abs(y2 - y1)
    return {"view": name}


@op("drawing", "ucs", mutates=True)
def ucs(ctx: Ctx, name: str | None = None, origin=None, x_axis=(1, 0, 0), y_axis=(0, 1, 0)):
    """UCS: save a named user coordinate system (origin and axes); without name lists them."""
    doc = ctx.doc
    if not name:
        return {"ucs": [{"name": u.dxf.name, "origin": list(u.dxf.origin)} for u in doc.ucs]}
    if origin is None:
        raise CadError("Give origin")
    if doc.ucs.has_entry(name):
        doc.ucs.remove(name)
    u = doc.ucs.new(name)
    u.dxf.origin = vec(origin)
    u.dxf.xaxis = vec(x_axis)
    u.dxf.yaxis = vec(y_axis)
    return {"ucs": name}


@op("drawing", "properties", mutates=True)
def properties(ctx: Ctx, values: dict | None = None):
    """DWGPROPS: read or set custom drawing properties, e.g. {"Projekt": "M0 felújítás", "Tervező": "..."}."""
    cv = ctx.doc.header.custom_vars
    if values:
        for k, v in values.items():
            if cv.has_tag(k):
                cv.replace(k, str(v))
            else:
                cv.append(k, str(v))
    return {"properties": dict(cv.properties)}

