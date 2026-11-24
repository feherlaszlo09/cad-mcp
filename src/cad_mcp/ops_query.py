"""Tool `query`: list, inspect, count, measure, find text, intersections."""

from __future__ import annotations

import math
import re

from ezdxf import bbox
from ezdxf import path as ezpath
from shapely.geometry import Polygon

from . import geom
from .core import CadError, Ctx, _clean, describe, op, select_from, vec

T = "query"


@op(T, "list")
def list_(ctx: Ctx, sel=None, limit: int = 200, offset: int = 0, detail: bool = False):
    """List entities with key geometry. sel defaults to all of model space."""
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    page = ents[offset: offset + limit]
    return {
        "total": len(ents),
        "returned": len(page),
        "entities": [describe(e, detail=detail) for e in page],
        **({"next_offset": offset + limit} if offset + limit < len(ents) else {}),
    }


@op(T, "get")
def get(ctx: Ctx, handles: list[str] | str):
    """Full details (all DXF attributes, bbox, vertices) of entities by handle."""
    hs = [handles] if isinstance(handles, str) else handles
    return {"entities": [describe(ctx.entity(h), detail=True) for h in hs]}


@op(T, "count")
def count(ctx: Ctx, sel=None, group_by: str = "type"):
    """Count entities grouped by type, layer, color or block (block = INSERT counts per block name)."""
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    out: dict[str, int] = {}
    for e in ents:
        if group_by == "type":
            k = e.dxftype()
        elif group_by == "layer":
            k = e.dxf.get("layer", "0")
        elif group_by == "color":
            k = str(e.dxf.get("color", 256))
        elif group_by == "block":
            if e.dxftype() != "INSERT":
                continue
            k = e.dxf.name
        else:
            raise CadError("group_by must be type, layer, color or block")
        out[k] = out.get(k, 0) + 1
    return {"total": sum(out.values()), "groups": dict(sorted(out.items(), key=lambda kv: -kv[1]))}


@op(T, "extents")
def extents(ctx: Ctx, sel=None):
    """Bounding box [min, max], size and center of a selection (default: whole model space)."""
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    ext = bbox.extents(ents)
    if not ext.has_data:
        return {"extents": None}
    return {"min": _clean(ext.extmin), "max": _clean(ext.extmax), "size": _clean(ext.size),
            "center": _clean(ext.center)}


@op(T, "distance")
def distance(ctx: Ctx, p1, p2):
    """Distance, dx, dy and angle (deg) between two points (like DIST)."""
    a, b = vec(p1), vec(p2)
    d = b - a
    return {"distance": round(a.distance(b), 6), "dx": round(d.x, 6), "dy": round(d.y, 6),
            "dz": round(d.z, 6), "angle": round(math.degrees(math.atan2(d.y, d.x)) % 360, 6)}


def _length(e) -> float:
    t = e.dxftype()
    if t == "LINE":
        return e.dxf.start.distance(e.dxf.end)
    if t == "CIRCLE":
        return 2 * math.pi * e.dxf.radius
    if t == "ARC":
        return math.radians(geom.ccw_sweep(e.dxf.start_angle, e.dxf.end_angle)) * e.dxf.radius
    if t == "LWPOLYLINE":  # exact: chords for straight segments, r * angle for arcs
        pts = list(e.get_points("xyb"))
        n = len(pts)
        total = 0.0
        for i in range(n if e.closed else n - 1):
            (x0, y0, b), (x1, y1, _b) = pts[i], pts[(i + 1) % n]
            c = math.hypot(x1 - x0, y1 - y0)
            if abs(b) < 1e-12 or c == 0:
                total += c
            else:
                th = 4 * math.atan(abs(b))
                total += th * c / (2 * math.sin(th / 2))
        return total
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        raise CadError(f"{t} {e.dxf.handle} has no length") from None
    pts = list(p.flattening(geom.flatten_distance(e) * 0.1))
    return sum(a.distance(b) for a, b in zip(pts, pts[1:]))


@op(T, "length")
def length(ctx: Ctx, sel):
    """Total length of lines, arcs, circles, polylines, splines, ellipses (each and summed)."""
    ents = select_from(ctx, sel)
    each = {e.dxf.handle: round(_length(e), 6) for e in ents}
    return {"total": round(sum(each.values()), 6), "each": each}


def _area(e) -> tuple[float, float]:
    t = e.dxftype()
    if t == "CIRCLE":
        r = e.dxf.radius
        return math.pi * r * r, 2 * math.pi * r
    if t == "HATCH":
        # even-odd: islands inside the outer loop are holes
        shape = None
        for p in ezpath.from_hatch(e):
            pts = [(v.x, v.y) for v in p.flattening(geom.flatten_distance(e) * 0.1)]
            if len(pts) >= 3:
                poly = Polygon(pts).buffer(0)
                shape = poly if shape is None else shape.symmetric_difference(poly)
        if shape is None:
            return 0.0, 0.0
        return shape.area, shape.boundary.length
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        raise CadError(f"{t} {e.dxf.handle} has no area") from None
    pts = [(v.x, v.y) for v in p.flattening(geom.flatten_distance(e) * 0.1)]
    if len(pts) < 3:
        raise CadError(f"{t} {e.dxf.handle} is not a closed shape")
    poly = Polygon(pts)
    return abs(poly.area), poly.exterior.length


@op(T, "area")
def area(ctx: Ctx, sel=None, points=None):
    """Area and perimeter of closed entities (polyline, circle, ellipse, spline, hatch) or of a point list (like AREA)."""
    if points:
        poly = Polygon([tuple(vec(p).vec2) for p in points])
        return {"area": round(poly.area, 6), "perimeter": round(poly.exterior.length, 6)}
    ents = select_from(ctx, sel)
    each = {}
    for e in ents:
        a, per = _area(e)
        each[e.dxf.handle] = {"area": round(a, 6), "perimeter": round(per, 6)}
    return {"total_area": round(sum(v["area"] for v in each.values()), 6), "each": each}


@op(T, "find_text")
def find_text(ctx: Ctx, pattern: str, regex: bool = False, space=None, include_blocks: bool = True):
    """Find TEXT, MTEXT, attributes and dimension overrides whose content matches pattern (case-insensitive substring or regex)."""
    rx = re.compile(pattern if regex else re.escape(pattern), re.I)
    hits = []
    for e in ctx.layout(space):
        t = e.dxftype()
        content = None
        if t in ("TEXT", "ATTRIB"):
            content = e.dxf.text
        elif t == "MTEXT":
            content = e.plain_text()
        elif t == "DIMENSION":
            content = e.dxf.get("text", "")
        elif t == "MULTILEADER" and e.context.mtext:
            content = e.context.mtext.default_content
        if content and rx.search(content):
            hits.append({"handle": e.dxf.handle, "type": t, "text": content, "layer": e.dxf.layer})
        if include_blocks and t == "INSERT":
            for a in e.attribs:
                if rx.search(a.dxf.text):
                    hits.append({"handle": a.dxf.handle, "type": "ATTRIB", "tag": a.dxf.tag,
                                 "text": a.dxf.text, "block_ref": e.dxf.handle})
    return {"count": len(hits), "matches": hits[:500]}


@op(T, "intersections")
def intersections(ctx: Ctx, handle1: str, handle2: str):
    """Intersection points of two entities."""
    a = geom.to_shape(ctx.entity(handle1))
    b = geom.to_shape(ctx.entity(handle2))
    if a is None or b is None:
        raise CadError("Both entities need a geometric path")
    pts = geom.intersection_points(a, b)
    return {"points": [[round(p.x, 6), round(p.y, 6)] for p in pts]}


@op(T, "nearest")
def nearest(ctx: Ctx, point, sel=None, limit: int = 5):
    """Entities closest to a point (useful to find what is at a location)."""
    from shapely.geometry import Point

    p = vec(point)
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    scored = []
    for e in ents:
        s = geom.to_shape(e)
        if s is None:
            ext = bbox.extents([e], fast=True)
            if not ext.has_data:
                continue
            d = ext.center.distance(p)
        else:
            d = s.distance(Point(p.x, p.y))
        scored.append((d, e))
    scored.sort(key=lambda x: x[0])
    return {"nearest": [{"distance": round(d, 6), **describe(e)} for d, e in scored[:limit]]}
