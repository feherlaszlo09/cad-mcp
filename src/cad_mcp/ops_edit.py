"""Tool `edit`: transform, copy, delete, explode, offset, trim, extend, fillet,
chamfer, break, join, stretch, properties, draw order."""

from __future__ import annotations

import math

from ezdxf import bbox
from ezdxf.entities import DXFGraphic
from ezdxf.math import Matrix44, Vec2, Vec3
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring

from . import geom
from .core import (CadError, Ctx, apply_props, handles, op, pick_props, select_from,
                   vec)

T = "edit"


def _layout_of(e: DXFGraphic):
    lay = e.get_layout()
    if lay is None:
        raise CadError(f"Entity {e.dxf.handle} is not in a layout")
    return lay


def _copy(e: DXFGraphic) -> DXFGraphic:
    try:
        new = e.copy()
    except Exception as exc:
        raise CadError(f"{e.dxftype()} {e.dxf.handle} cannot be copied: {exc}") from exc
    _layout_of(e).add_entity(new)
    return new


def _transform(ents, m: Matrix44) -> list[str]:
    failed = []
    for e in ents:
        try:
            e.transform(m)
        except Exception as exc:  # NonUniformScalingError, NotImplementedError ...
            failed.append(f"{e.dxf.handle} ({e.dxftype()}): {exc}")
    return failed


def _vector(vector, from_point, to_point) -> Vec3:
    if vector is not None:
        return vec(vector)
    if from_point is not None and to_point is not None:
        return vec(to_point) - vec(from_point)
    raise CadError("Give vector=[dx,dy] or from_point and to_point")


def _rot(base: Vec3, angle: float) -> Matrix44:
    return Matrix44.chain(Matrix44.translate(-base.x, -base.y, -base.z),
                          Matrix44.z_rotate(math.radians(angle)),
                          Matrix44.translate(base.x, base.y, base.z))


def _result(ents=None, created=None, failed=None, **extra):
    r = {}
    if ents is not None:
        r["handles"] = handles(ents)
    if created is not None:
        r["created"] = handles(created)
    if failed:
        r["failed"] = failed
    r.update(extra)
    return r


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------


@op(T, "move", mutates=True)
def move(ctx: Ctx, sel, vector=None, from_point=None, to_point=None):
    """Move selected entities by vector or from_point->to_point."""
    ents = select_from(ctx, sel)
    v = _vector(vector, from_point, to_point)
    return _result(ents, failed=_transform(ents, Matrix44.translate(v.x, v.y, v.z)))


@op(T, "copy", mutates=True)
def copy(ctx: Ctx, sel, vector=None, from_point=None, to_point=None, count: int = 1):
    """Copy selection by vector (count>1 makes several copies at multiples of vector). Returns new handles."""
    ents = select_from(ctx, sel)
    v = _vector(vector, from_point, to_point)
    created, failed = [], []
    for i in range(1, max(1, count) + 1):
        for e in ents:
            new = _copy(e)
            failed += _transform([new], Matrix44.translate(v.x * i, v.y * i, v.z * i))
            created.append(new)
    return _result(created=created, failed=failed)


@op(T, "rotate", mutates=True)
def rotate(ctx: Ctx, sel, base, angle: float, copy: bool = False):
    """Rotate selection around base point by angle (deg, counter-clockwise). copy=true keeps originals."""
    ents = select_from(ctx, sel)
    if copy:
        ents = [_copy(e) for e in ents]
    return _result(ents, failed=_transform(ents, _rot(vec(base), angle)))


@op(T, "scale", mutates=True)
def scale(ctx: Ctx, sel, base, factor: float, copy: bool = False):
    """Scale selection uniformly about base point."""
    ents = select_from(ctx, sel)
    if copy:
        ents = [_copy(e) for e in ents]
    b = vec(base)
    m = Matrix44.chain(Matrix44.translate(-b.x, -b.y, -b.z), Matrix44.scale(factor),
                       Matrix44.translate(b.x, b.y, b.z))
    return _result(ents, failed=_transform(ents, m))


@op(T, "mirror", mutates=True)
def mirror(ctx: Ctx, sel, p1, p2, keep_original: bool = True, mirror_text: bool = False):
    """Mirror selection across the line p1-p2. Text stays readable unless mirror_text=true (MIRRTEXT)."""
    ents = select_from(ctx, sel)
    a, b = vec(p1), vec(p2)
    ang = math.atan2(b.y - a.y, b.x - a.x)
    m = Matrix44.chain(Matrix44.translate(-a.x, -a.y, 0), Matrix44.z_rotate(-ang),
                       Matrix44.scale(1, -1, 1), Matrix44.z_rotate(ang), Matrix44.translate(a.x, a.y, 0))
    targets = [_copy(e) for e in ents] if keep_original else ents
    failed = []
    for e in targets:
        if not mirror_text and e.dxftype() in ("TEXT", "MTEXT"):
            ins = Vec3(e.dxf.insert)
            failed += _transform([e], Matrix44.translate(*(m.transform(ins) - ins).xyz))
        else:
            failed += _transform([e], m)
    return _result(targets, failed=failed)


@op(T, "array_rect", mutates=True)
def array_rect(ctx: Ctx, sel, rows: int, cols: int, row_spacing: float, col_spacing: float):
    """Rectangular array: rows x cols copies (the original is cell 0,0)."""
    ents = select_from(ctx, sel)
    created, failed = [], []
    for r in range(rows):
        for c in range(cols):
            if r == 0 and c == 0:
                continue
            for e in ents:
                new = _copy(e)
                failed += _transform([new], Matrix44.translate(c * col_spacing, r * row_spacing, 0))
                created.append(new)
    return _result(created=created, failed=failed)


@op(T, "array_polar", mutates=True)
def array_polar(ctx: Ctx, sel, center, count: int, total_angle: float = 360, rotate_items: bool = True):
    """Polar array of count items (including original) around center over total_angle."""
    ents = select_from(ctx, sel)
    c = vec(center)
    step = total_angle / count if abs(total_angle) >= 360 else total_angle / max(1, count - 1)
    created, failed = [], []
    ref = bbox.extents(ents).center
    for i in range(1, count):
        a = step * i
        for e in ents:
            new = _copy(e)
            if rotate_items:
                failed += _transform([new], _rot(c, a))
            else:
                moved = _rot(c, a).transform(ref)
                failed += _transform([new], Matrix44.translate(*(moved - ref).xyz))
            created.append(new)
    return _result(created=created, failed=failed)


@op(T, "array_path", mutates=True)
def array_path(ctx: Ctx, sel, path_handle: str, count: int, align: bool = True):
    """Copies spaced evenly along a path entity (line, polyline, arc, spline); the selection's center goes on the path."""
    ents = select_from(ctx, sel)
    shape = geom.to_shape(ctx.entity(path_handle))
    if shape is None or shape.geom_type != "LineString":
        raise CadError("path_handle must be a line, polyline, arc, circle or spline")
    ref = bbox.extents(ents).center
    created, failed = [], []
    n = max(2, count)
    for i in range(n):
        d = shape.length * i / (n - 1 if not shape.is_ring else n)
        p = shape.interpolate(d)
        q = shape.interpolate(min(shape.length, d + shape.length * 1e-3))
        q0 = shape.interpolate(max(0.0, d - shape.length * 1e-3))
        ang = math.degrees(math.atan2(q.y - q0.y, q.x - q0.x)) if align else 0
        for e in ents:
            new = _copy(e)
            m = Matrix44.chain(Matrix44.translate(-ref.x, -ref.y, 0),
                               Matrix44.z_rotate(math.radians(ang)),
                               Matrix44.translate(p.x, p.y, 0))
            failed += _transform([new], m)
            created.append(new)
    return _result(created=created, failed=failed)


@op(T, "delete", mutates=True)
def delete(ctx: Ctx, sel):
    """Delete selected entities."""
    ents = select_from(ctx, sel)
    hs = handles(ents)
    for e in ents:
        _layout_of(e).delete_entity(e)
    return {"deleted": hs}


@op(T, "explode", mutates=True)
def explode(ctx: Ctx, sel):
    """Explode blocks, polylines, dimensions, multileaders, hatches into simple entities."""
    ents = select_from(ctx, sel)
    created, failed = [], []
    for e in ents:
        try:
            created += list(e.explode())
        except Exception as exc:
            failed.append(f"{e.dxf.handle} ({e.dxftype()}): {exc}")
    return _result(created=created, failed=failed)


@op(T, "set_props", mutates=True)
def set_props(ctx: Ctx, sel, layer=None, color=None, linetype=None, lineweight=None,
              ltscale=None, transparency=None, thickness=None):
    """Change layer, color, linetype, lineweight, ltscale, transparency (0..1), thickness of a selection."""
    ents = select_from(ctx, sel)
    props = pick_props(dict(layer=layer, color=color, linetype=linetype, lineweight=lineweight,
                            ltscale=ltscale, transparency=transparency, thickness=thickness))
    for e in ents:
        apply_props(ctx.doc, e, props)
    return _result(ents, changed=list(props))


@op(T, "set_geometry", mutates=True)
def set_geometry(ctx: Ctx, handle: str, values: dict):
    """Set raw DXF attributes of one entity, e.g. {"start":[0,0], "end":[5,5]} for a LINE, {"radius":12} for a CIRCLE, {"points":[[..]..], "closed":true} for LWPOLYLINE."""
    e = ctx.entity(handle)
    for k, v in values.items():
        if e.dxftype() == "LWPOLYLINE" and k == "points":
            e.set_points([tuple(p) for p in v], format="xyb" if any(len(p) == 3 for p in v) else "xy")
            continue
        if e.dxftype() == "LWPOLYLINE" and k == "closed":
            e.closed = bool(v)
            continue
        try:
            if isinstance(v, list) and len(v) in (2, 3) and all(isinstance(c, (int, float)) for c in v):
                v = vec(v)
            e.dxf.set(k, v)
        except Exception as exc:
            raise CadError(f"Cannot set {k} on {e.dxftype()}: {exc}") from exc
    return {"handle": e.dxf.handle, "set": list(values)}


@op(T, "draworder", mutates=True)
def draworder(ctx: Ctx, sel, mode: str = "front"):
    """Bring selection to front or send to back (front|back) in its layout."""
    ents = select_from(ctx, sel)
    if not ents:
        return {"handles": []}
    lay = _layout_of(ents[0])
    current = {h: s for h, s in lay.get_redraw_order()}
    order = sorted((e for e in lay), key=lambda e: int(current.get(e.dxf.handle, e.dxf.handle), 16))
    chosen = {e.dxf.handle for e in ents}
    rest = [e for e in order if e.dxf.handle not in chosen]
    picked = [e for e in order if e.dxf.handle in chosen]
    new_order = rest + picked if mode == "front" else picked + rest
    keys = sorted((e.dxf.handle for e in order), key=lambda h: int(h, 16))
    lay.set_redraw_order({e.dxf.handle: k for e, k in zip(new_order, keys)})
    return {"handles": handles(picked), "mode": mode}


# ---------------------------------------------------------------------------
# Offset
# ---------------------------------------------------------------------------


def _copy_attribs(src: DXFGraphic) -> dict:
    keys = ("layer", "color", "linetype", "lineweight", "ltscale", "true_color", "transparency")
    return {k: src.dxf.get(k) for k in keys if src.dxf.hasattr(k)}


def _side_sign_line(a: Vec2, b: Vec2, p: Vec2) -> float:
    return 1.0 if (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) > 0 else -1.0


@op(T, "offset", mutates=True)
def offset(ctx: Ctx, handle: str, distance: float, side_point=None):
    """Parallel copy at distance (like OFFSET). side_point picks the side; otherwise positive = left of a line/open polyline, outward for circles, arcs and closed shapes."""
    e = ctx.entity(handle)
    t = e.dxftype()
    lay = _layout_of(e)
    d = float(distance)
    attribs = _copy_attribs(e)
    sp = Vec2(vec(side_point)) if side_point is not None else None
    if t == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        sign = _side_sign_line(a, b, sp) if sp else (1.0 if d >= 0 else -1.0)
        n = (b - a).normalize().orthogonal() * abs(d) * sign
        new = lay.add_line(a + n, b + n, dxfattribs=attribs)
        return _result(created=[new])
    if t in ("CIRCLE", "ARC"):
        c, r = Vec2(e.dxf.center), e.dxf.radius
        outward = (sp.distance(c) > r) if sp else d >= 0
        nr = r + abs(d) if outward else r - abs(d)
        if nr <= 0:
            raise CadError("Offset distance larger than radius")
        new = e.copy()
        new.dxf.radius = nr
        lay.add_entity(new)
        return _result(created=[new])
    shape = geom.to_shape(e)
    if shape is None:
        raise CadError(f"Cannot offset {t}")
    note = None
    closed = shape.is_ring or (t == "LWPOLYLINE" and e.closed)
    has_bulge = t == "LWPOLYLINE" and any(b for *_, b in e.get_points("xyb"))
    join = "round" if (has_bulge or t not in ("LWPOLYLINE", "POLYLINE")) else "mitre"
    if closed:
        poly = Polygon(shape.coords)
        outward = (not poly.contains(Point(sp.x, sp.y))) if sp else d >= 0
        res = poly.buffer(abs(d) if outward else -abs(d), join_style=join, mitre_limit=10)
        if res.is_empty:
            raise CadError("Offset collapses the shape")
        polys = list(res.geoms) if res.geom_type == "MultiPolygon" else [res]
        created = [lay.add_lwpolyline(list(p.exterior.coords)[:-1], close=True, dxfattribs=attribs)
                   for p in polys]
    else:
        if sp:
            nearest = shape.interpolate(shape.project(Point(sp.x, sp.y)))
            ahead = shape.interpolate(min(shape.length, shape.project(nearest) + 1e-6))
            behind = shape.interpolate(max(0, shape.project(nearest) - 1e-6))
            sign = _side_sign_line(Vec2(behind.x, behind.y), Vec2(ahead.x, ahead.y), sp)
        else:
            sign = 1.0 if d >= 0 else -1.0
        res = shape.offset_curve(abs(d) * sign, join_style=join, mitre_limit=10)
        lines = list(res.geoms) if res.geom_type == "MultiLineString" else [res]
        created = [lay.add_lwpolyline(list(ls.coords), dxfattribs=attribs) for ls in lines if not ls.is_empty]
    if has_bulge or t not in ("LWPOLYLINE", "POLYLINE"):
        note = "Curved parts are approximated by short straight segments."
    return _result(created=created, note=note) if note else _result(created=created)


# ---------------------------------------------------------------------------
# Trim / extend / break
# ---------------------------------------------------------------------------


def _cutters(ctx: Ctx, target: DXFGraphic, cutting) -> list:
    if cutting is None:
        ents = [e for e in _layout_of(target) if e is not target]
    else:
        ents = [e for e in select_from(ctx, cutting) if e is not target]
    shapes = []
    for e in ents:
        s = geom.to_shape(e)
        if s is not None:
            shapes.append(s)
    return shapes


def _cut_params(shape: LineString, cutters) -> list[float]:
    ds = []
    for c in cutters:
        for p in geom.intersection_points(shape, c):
            ds.append(geom.point_on(shape, p))
    return geom.dedupe(ds, shape.length * 1e-7 + 1e-9)


@op(T, "trim", mutates=True)
def trim(ctx: Ctx, handle: str, pick, cutting=None):
    """Cut away the part of an entity (line, arc, circle, polyline, spline, ellipse) that contains the pick point, between the nearest cutting edges. cutting = selection of edges (default: every other entity in the layout)."""
    e = ctx.entity(handle)
    t = e.dxftype()
    cutters = _cutters(ctx, e, cutting)
    pk = Vec2(vec(pick))
    lay = _layout_of(e)
    attribs = _copy_attribs(e)
    if t == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        shape = LineString([a, b])
        L = shape.length
        cuts = [d for d in _cut_params(shape, cutters) if 1e-9 < d < L - 1e-9]
        if not cuts:
            raise CadError("No cutting edge crosses this line")
        dp = geom.point_on(shape, pk)
        bounds = [0.0] + cuts + [L]
        i = max(j for j in range(len(bounds) - 1) if bounds[j] <= dp)
        lo, hi = bounds[i], bounds[i + 1]
        pt = lambda d: a + (b - a) * (d / L)  # noqa: E731
        created = []
        if lo == 0 and hi == L:
            raise CadError("Nothing to trim")
        if lo == 0:
            e.dxf.start = Vec3(pt(hi))
        elif hi == L:
            e.dxf.end = Vec3(pt(lo))
        else:
            created.append(lay.add_line(pt(hi), b, dxfattribs=attribs))
            e.dxf.end = Vec3(pt(lo))
        return _result([e], created=created)
    if t in ("ARC", "CIRCLE"):
        c, r = Vec2(e.dxf.center), e.dxf.radius
        start = 0.0 if t == "CIRCLE" else e.dxf.start_angle
        sweep = 360.0 if t == "CIRCLE" else geom.ccw_sweep(e.dxf.start_angle, e.dxf.end_angle)
        shape = geom.to_shape(e)
        angs = []
        for cu in cutters:
            for p in geom.intersection_points(shape, cu):
                rel = (geom.angle_of(c, p) - start) % 360
                if 1e-7 < rel < sweep - 1e-7 or (t == "CIRCLE"):
                    angs.append(rel)
        angs = geom.dedupe(angs, 1e-6)
        relp = (geom.angle_of(c, pk) - start) % 360
        if t == "CIRCLE":
            if len(angs) < 2:
                raise CadError("A circle needs at least two cutting points")
            ring = angs + [angs[0] + 360]
            for j in range(len(angs)):
                lo, hi = ring[j], ring[j + 1]
                if lo <= relp < hi or lo <= relp + 360 < hi:
                    break
            new = lay.add_arc(c, r, (hi + start) % 360, (lo + start) % 360, dxfattribs=attribs)
            lay.delete_entity(e)
            return _result(created=[new], deleted=[handle])
        if not angs:
            raise CadError("No cutting edge crosses this arc")
        bounds = [0.0] + angs + [sweep]
        relp = min(relp, sweep)
        i = max(j for j in range(len(bounds) - 1) if bounds[j] <= relp)
        lo, hi = bounds[i], bounds[i + 1]
        created = []
        if lo == 0 and hi == sweep:
            raise CadError("Nothing to trim")
        if lo == 0:
            e.dxf.start_angle = (start + hi) % 360
        elif hi == sweep:
            e.dxf.end_angle = (start + lo) % 360
        else:
            created.append(lay.add_arc(c, r, (start + hi) % 360, (start + sweep) % 360, dxfattribs=attribs))
            e.dxf.end_angle = (start + lo) % 360
        return _result([e], created=created)
    # generic: polylines, splines, ellipses -> rebuilt as LWPOLYLINE pieces
    shape = geom.to_shape(e)
    if shape is None:
        raise CadError(f"Cannot trim {t}")
    L = shape.length
    closed = shape.is_ring
    cuts = [d for d in _cut_params(shape, cutters) if 1e-9 < d < L - 1e-9]
    if not cuts or (closed and len(cuts) < 2):
        raise CadError("Not enough cutting points on this entity")
    dp = geom.point_on(shape, pk)
    keep = []
    if closed:
        ring = cuts + [cuts[0] + L]
        for j in range(len(cuts)):
            lo, hi = ring[j], ring[j + 1]
            if lo <= dp < hi or lo <= dp + L < hi:
                break
        a = substring(shape, hi % L if hi > L else hi, L)
        b = substring(shape, 0, lo % L if lo > L else lo)
        coords = list(a.coords) + list(b.coords)[1:] if hi <= L else list(substring(shape, hi - L, lo).coords)
        keep.append(coords)
    else:
        bounds = [0.0] + cuts + [L]
        i = max(j for j in range(len(bounds) - 1) if bounds[j] <= dp)
        if i > 0:
            keep.append(list(substring(shape, 0, bounds[i]).coords))
        if i + 1 < len(bounds) - 1:
            keep.append(list(substring(shape, bounds[i + 1], L).coords))
    curved = t != "LWPOLYLINE" or any(b for *_, b in e.get_points("xyb"))
    created = [lay.add_lwpolyline(cs, dxfattribs=attribs) for cs in keep if len(cs) >= 2]
    lay.delete_entity(e)
    note = "Rebuilt as polyline; curves approximated by short segments." if curved else None
    out = _result(created=created, deleted=[handle])
    if note:
        out["note"] = note
    return out


def _ray_hits(origin: Vec2, direction: Vec2, cutters, max_len: float) -> float | None:
    ray = LineString([origin, origin + direction.normalize() * max_len])
    best = None
    for c in cutters:
        for p in geom.intersection_points(ray, c):
            d = origin.distance(p)
            if d > 1e-9 and (best is None or d < best):
                best = d
    return best


@op(T, "extend", mutates=True)
def extend(ctx: Ctx, handle: str, pick=None, boundary=None):
    """EXTEND a line, arc, open polyline (straight or arc end), spline (natural continuation of its end span) or ellipse arc: the end nearest pick (default the end point) goes to the nearest boundary edge (default: all other entities)."""
    e = ctx.entity(handle)
    t = e.dxftype()
    cutters = _cutters(ctx, e, boundary)
    ext = bbox.extents(_layout_of(e), fast=True)
    max_len = (ext.size.magnitude if ext.has_data else 1e6) * 10 + 1
    pk = Vec2(vec(pick)) if pick is not None else None
    if t == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        at_start = pk is not None and pk.distance(a) < pk.distance(b)
        origin, direction = (a, a - b) if at_start else (b, b - a)
        d = _ray_hits(origin, direction, cutters, max_len)
        if d is None:
            raise CadError("No boundary in the extension direction")
        newp = origin + direction.normalize() * d
        if at_start:
            e.dxf.start = Vec3(newp)
        else:
            e.dxf.end = Vec3(newp)
        return _result([e], extended_by=round(d, 6))
    if t == "ARC":
        c, r = Vec2(e.dxf.center), e.dxf.radius
        sa, ea = e.dxf.start_angle, e.dxf.end_angle
        p_s = c + Vec2.from_deg_angle(sa) * r
        p_e = c + Vec2.from_deg_angle(ea) * r
        at_start = pk is not None and pk.distance(p_s) < pk.distance(p_e)
        full = LineString([c + Vec2.from_deg_angle(a) * r for a in [i * 0.5 for i in range(721)]])
        best = None
        for cu in cutters:
            for p in geom.intersection_points(full, cu):
                a = geom.angle_of(c, p)
                delta = (sa - a) % 360 if at_start else (a - ea) % 360
                if delta > 1e-7 and (best is None or delta < best[0]):
                    best = (delta, a)
        if best is None:
            raise CadError("No boundary reached by extending this arc")
        if at_start:
            e.dxf.start_angle = best[1]
        else:
            e.dxf.end_angle = best[1]
        return _result([e], extended_degrees=round(best[0], 6))
    if t == "LWPOLYLINE" and not e.closed:
        pts = list(e.get_points("xyb"))
        if len(pts) < 2:
            raise CadError("Polyline too short")
        a0, a1 = Vec2(pts[0][:2]), Vec2(pts[1][:2])
        b0, b1 = Vec2(pts[-1][:2]), Vec2(pts[-2][:2])
        at_start = pk is not None and pk.distance(a0) < pk.distance(b0)
        if (at_start and pts[0][2]) or (not at_start and pts[-2][2]):
            from .ops_edit2 import extend_arc_end

            return extend_arc_end(ctx, handle, pick=pick, boundary=boundary)
        origin, direction = (a0, a0 - a1) if at_start else (b0, b0 - b1)
        d = _ray_hits(origin, direction, cutters, max_len)
        if d is None:
            raise CadError("No boundary in the extension direction")
        newp = origin + direction.normalize() * d
        if at_start:
            pts[0] = (newp.x, newp.y, pts[0][2])
        else:
            pts[-1] = (newp.x, newp.y, pts[-1][2])
        e.set_points(pts, format="xyb")
        return _result([e], extended_by=round(d, 6))
    if t in ("SPLINE", "ELLIPSE"):
        from .ops_edit2 import extend_curve

        return extend_curve(ctx, e, pick=pick, boundary=boundary)
    raise CadError(f"Cannot extend {t}: use a LINE, ARC, open LWPOLYLINE, SPLINE or ELLIPSE arc")


@op(T, "lengthen", mutates=True)
def lengthen(ctx: Ctx, handle: str, delta: float | None = None, total: float | None = None,
             at_start: bool = False):
    """Change a line's length by delta, or set its total length; moves the end point (or start with at_start)."""
    e = ctx.entity(handle)
    if e.dxftype() != "LINE":
        raise CadError("lengthen works on LINE entities")
    a, b = Vec3(e.dxf.start), Vec3(e.dxf.end)
    L = a.distance(b)
    new_len = total if total is not None else L + float(delta or 0)
    if new_len <= 0:
        raise CadError("Resulting length must be positive")
    if at_start:
        e.dxf.start = b + (a - b).normalize() * new_len
    else:
        e.dxf.end = a + (b - a).normalize() * new_len
    return _result([e], length=round(new_len, 6))


@op(T, "break_at", mutates=True)
def break_at(ctx: Ctx, handle: str, point, point2=None):
    """Split a line, arc or polyline at point (BREAK AT POINT); with point2 also removes the part between the two points."""
    e = ctx.entity(handle)
    t = e.dxftype()
    lay = _layout_of(e)
    attribs = _copy_attribs(e)
    p1 = Vec2(vec(point))
    p2 = Vec2(vec(point2)) if point2 is not None else None
    if t == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        s = LineString([a, b])
        d1 = geom.point_on(s, p1)
        d2 = geom.point_on(s, p2) if p2 else d1
        lo, hi = sorted((d1, d2))
        L = s.length
        pt = lambda d: a + (b - a) * (d / L)  # noqa: E731
        new = lay.add_line(pt(hi), b, dxfattribs=attribs)
        e.dxf.end = Vec3(pt(lo))
        return _result([e], created=[new])
    if t == "ARC":
        c = Vec2(e.dxf.center)
        a1 = geom.angle_of(c, p1)
        a2 = geom.angle_of(c, p2) if p2 else a1
        sa = e.dxf.start_angle
        r1, r2 = sorted(((a1 - sa) % 360, (a2 - sa) % 360))
        new = lay.add_arc(c, e.dxf.radius, (sa + r2) % 360, e.dxf.end_angle, dxfattribs=attribs)
        e.dxf.end_angle = (sa + r1) % 360
        return _result([e], created=[new])
    shape = geom.to_shape(e)
    if shape is None:
        raise CadError(f"Cannot break {t}")
    d1 = geom.point_on(shape, p1)
    d2 = geom.point_on(shape, p2) if p2 else d1
    lo, hi = sorted((d1, d2))
    parts = [list(substring(shape, 0, lo).coords), list(substring(shape, hi, shape.length).coords)]
    created = [lay.add_lwpolyline(cs, dxfattribs=attribs) for cs in parts if len(cs) >= 2]
    lay.delete_entity(e)
    return _result(created=created, deleted=[handle])


# ---------------------------------------------------------------------------
# Fillet / chamfer / join / stretch
# ---------------------------------------------------------------------------


def _corner(ctx: Ctx, h1: str, h2: str, pick1, pick2):
    e1, e2 = ctx.entity(h1), ctx.entity(h2)
    if e1.dxftype() != "LINE" or e2.dxftype() != "LINE":
        raise CadError("fillet/chamfer between two entities needs two LINEs (use fillet_polyline for polylines)")
    a1, b1 = Vec2(e1.dxf.start), Vec2(e1.dxf.end)
    a2, b2 = Vec2(e2.dxf.start), Vec2(e2.dxf.end)
    P = geom.line_intersection(a1, b1 - a1, a2, b2 - a2)
    if P is None:
        raise CadError("Lines are parallel")

    def keep(a, b, pick):
        if pick is not None:
            pk = Vec2(vec(pick))
            da, db = (a - P).dot(pk - P), (b - P).dot(pk - P)
            return ("start", a) if da > db else ("end", b)
        return ("start", a) if a.distance(P) > b.distance(P) else ("end", b)

    k1, K1 = keep(a1, b1, pick1)
    k2, K2 = keep(a2, b2, pick2)
    if K1.isclose(P) or K2.isclose(P):
        raise CadError("A line ends exactly at the corner on the kept side")
    return e1, e2, P, k1, K1, k2, K2


def _set_near_end(e, kept_end: str, p: Vec2):
    if kept_end == "start":
        e.dxf.end = Vec3(p)
    else:
        e.dxf.start = Vec3(p)


@op(T, "fillet", mutates=True)
def fillet(ctx: Ctx, handle1: str, handle2: str, radius: float = 0, pick1=None, pick2=None):
    """Round the corner between two lines with an arc of radius (0 = sharp corner, like FILLET R=0). pick1/pick2 choose which side of each line is kept."""
    e1, e2, P, k1, K1, k2, K2 = _corner(ctx, handle1, handle2, pick1, pick2)
    if radius <= 0:
        _set_near_end(e1, k1, P)
        _set_near_end(e2, k2, P)
        return _result([e1, e2], corner=[P.x, P.y])
    u1, u2 = (K1 - P).normalize(), (K2 - P).normalize()
    theta = math.acos(max(-1.0, min(1.0, u1.dot(u2))))
    if theta < 1e-9 or abs(theta - math.pi) < 1e-9:
        raise CadError("Lines are collinear")
    t = radius / math.tan(theta / 2)
    if t > K1.distance(P) + 1e-9 or t > K2.distance(P) + 1e-9:
        raise CadError("Radius too large for these lines")
    T1, T2 = P + u1 * t, P + u2 * t
    C = P + (u1 + u2).normalize() * (radius / math.sin(theta / 2))
    a1, a2 = geom.angle_of(C, T1), geom.angle_of(C, T2)
    cross = (T1 - C).x * (T2 - C).y - (T1 - C).y * (T2 - C).x
    start, end = (a1, a2) if cross > 0 else (a2, a1)
    arc = _layout_of(e1).add_arc(C, radius, start, end, dxfattribs=_copy_attribs(e1))
    _set_near_end(e1, k1, T1)
    _set_near_end(e2, k2, T2)
    return _result([e1, e2], created=[arc])


@op(T, "chamfer", mutates=True)
def chamfer(ctx: Ctx, handle1: str, handle2: str, distance1: float, distance2: float | None = None,
            pick1=None, pick2=None):
    """Bevel the corner between two lines: cut distance1 along line 1 and distance2 (default same) along line 2."""
    e1, e2, P, k1, K1, k2, K2 = _corner(ctx, handle1, handle2, pick1, pick2)
    d2 = distance1 if distance2 is None else distance2
    T1 = P + (K1 - P).normalize() * distance1
    T2 = P + (K2 - P).normalize() * d2
    line = _layout_of(e1).add_line(T1, T2, dxfattribs=_copy_attribs(e1))
    _set_near_end(e1, k1, T1)
    _set_near_end(e2, k2, T2)
    return _result([e1, e2], created=[line])


@op(T, "fillet_polyline", mutates=True)
def fillet_polyline(ctx: Ctx, handle: str, radius: float):
    """Round every straight corner of a 2D polyline with radius (like FILLET Polyline)."""
    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("fillet_polyline needs an LWPOLYLINE")
    pts = [(Vec2(x, y), b) for x, y, b in e.get_points("xyb")]
    n = len(pts)
    closed = e.closed
    out = []
    for i in range(n):
        p, b = pts[i]
        if not closed and (i == 0 or i == n - 1):
            out.append((p.x, p.y, b))
            continue
        prev_p, prev_b = pts[i - 1]
        nxt = pts[(i + 1) % n][0]
        if prev_b or b:
            out.append((p.x, p.y, b))
            continue
        u1, u2 = (prev_p - p).normalize(), (nxt - p).normalize()
        theta = math.acos(max(-1.0, min(1.0, u1.dot(u2))))
        if theta < 1e-9 or abs(theta - math.pi) < 1e-6:
            out.append((p.x, p.y, b))
            continue
        t = radius / math.tan(theta / 2)
        if t > prev_p.distance(p) / 2 + 1e-9 or t > nxt.distance(p) / 2 + 1e-9:
            raise CadError(f"Radius too large at vertex {i}")
        T1, T2 = p + u1 * t, p + u2 * t
        din, dout = (p - prev_p).normalize(), (nxt - p).normalize()
        turn = din.x * dout.y - din.y * dout.x
        deflection = math.pi - theta
        bulge = math.tan(deflection / 4) * (1 if turn > 0 else -1)
        out.append((T1.x, T1.y, bulge))
        out.append((T2.x, T2.y, 0.0))
    e.set_points(out, format="xyb")
    return _result([e], vertices=len(out))


def _segments(e):
    """Entity -> list of (start, end, bulge)."""
    t = e.dxftype()
    if t == "LINE":
        return [(Vec2(e.dxf.start), Vec2(e.dxf.end), 0.0)]
    if t == "ARC":
        c, r = Vec2(e.dxf.center), e.dxf.radius
        sa, ea = e.dxf.start_angle, e.dxf.end_angle
        sweep = geom.ccw_sweep(sa, ea)
        return [(c + Vec2.from_deg_angle(sa) * r, c + Vec2.from_deg_angle(ea) * r,
                 math.tan(math.radians(sweep) / 4))]
    if t == "LWPOLYLINE" and not e.closed:
        pts = list(e.get_points("xyb"))
        return [(Vec2(pts[i][:2]), Vec2(pts[i + 1][:2]), pts[i][2]) for i in range(len(pts) - 1)]
    raise CadError(f"join supports LINE, ARC and open LWPOLYLINE, not {t}")


def _rev(segs):
    return [(b, a, -bu) for a, b, bu in reversed(segs)]


@op(T, "join", mutates=True)
def join(ctx: Ctx, sel, tolerance: float = 1e-6):
    """JOIN touching objects: lines, arcs and open polylines become a polyline (PEDIT Join); when a spline or ellipse arc is among them the result is one SPLINE (arcs and ellipses exactly, as rational spans)."""
    ents = select_from(ctx, sel)
    if any(e.dxftype() in ("SPLINE", "ELLIPSE") for e in ents):
        from .ops_edit2 import join_to_spline

        return join_to_spline(ctx, ents, tolerance)
    pieces = [(e, _segments(e)) for e in ents]
    if not pieces:
        raise CadError("Nothing selected")
    lay = _layout_of(ents[0])
    attribs = _copy_attribs(ents[0])
    chains = []
    remaining = pieces[:]
    while remaining:
        _, chain = remaining.pop(0)
        grown = True
        while grown:
            grown = False
            for idx, (_, segs) in enumerate(remaining):
                if segs[0][0].distance(chain[-1][1]) <= tolerance:
                    chain = chain + segs
                elif segs[-1][1].distance(chain[-1][1]) <= tolerance:
                    chain = chain + _rev(segs)
                elif segs[-1][1].distance(chain[0][0]) <= tolerance:
                    chain = segs + chain
                elif segs[0][0].distance(chain[0][0]) <= tolerance:
                    chain = _rev(segs) + chain
                else:
                    continue
                remaining.pop(idx)
                grown = True
                break
        chains.append(chain)
    created = []
    for chain in chains:
        closed = chain[0][0].distance(chain[-1][1]) <= tolerance
        verts = [(s.x, s.y, b) for s, _, b in chain]
        if not closed:
            verts.append((chain[-1][1].x, chain[-1][1].y, 0.0))
        created.append(lay.add_lwpolyline(verts, format="xyb", close=closed, dxfattribs=attribs))
    joined = handles(ents)
    for e in ents:
        lay.delete_entity(e)
    return _result(created=created, deleted=joined)
