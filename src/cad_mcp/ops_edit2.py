"""Completes 2D editing: exact OFFSET of polylines with arcs, FILLET/CHAMFER for
lines, arcs and circles, EXTEND/LENGTHEN for arcs and polyline arc ends, AutoCAD-style
JOIN, STRETCH for arcs/blocks/text, circles tangent to entities (TTR, TTT),
SPLINEDIT, PEDIT vertex editing, HATCHEDIT, gradients, 3D rotate/mirror/array."""

from __future__ import annotations

import math

import numpy as np
from ezdxf.math import Matrix44, Vec2, Vec3

from .core import CadError, Ctx, finish, handles, op, pick_props, select_from, vec
from .ops_edit import _copy, _copy_attribs, _layout_of, _transform

T = "edit"
EPS = 1e-9

# ---------------------------------------------------------------------------
# primitives: lines and circles (for offsets, fillets, tangents)
# ---------------------------------------------------------------------------


def _bulge_arc(p0: Vec2, p1: Vec2, b: float):
    """Centre, radius and signed sweep of a polyline arc segment."""
    theta = 4 * math.atan(b)
    v = p1 - p0
    c = v.magnitude
    r = c / (2 * abs(math.sin(theta / 2)))
    n = Vec2(-v.y, v.x).normalize()
    centre = (p0 + p1) / 2 + n * (r * math.cos(theta / 2) * (1 if theta > 0 else -1))
    return centre, r, theta


def _ang(c: Vec2, p: Vec2) -> float:
    return math.atan2(p.y - c.y, p.x - c.x)


def _line_line(p1: Vec2, d1: Vec2, p2: Vec2, d2: Vec2):
    cross = d1.x * d2.y - d1.y * d2.x
    if abs(cross) < 1e-12:
        return []
    t = ((p2.x - p1.x) * d2.y - (p2.y - p1.y) * d2.x) / cross
    return [p1 + d1 * t]


def _line_circle(p: Vec2, d: Vec2, c: Vec2, r: float):
    d = d.normalize()
    f = p - c
    b = f.dot(d)
    disc = b * b - (f.dot(f) - r * r)
    if disc < -1e-12:
        return []
    disc = math.sqrt(max(disc, 0.0))
    return [p + d * (-b - disc), p + d * (-b + disc)]


def _circle_circle(c1: Vec2, r1: float, c2: Vec2, r2: float):
    d = c1.distance(c2)
    if d < 1e-12 or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    m = c1 + (c2 - c1) * (a / d)
    n = Vec2(-(c2.y - c1.y), c2.x - c1.x) / d
    return [m + n * h, m - n * h]


def _intersect(a, b):
    if a[0] == "line" and b[0] == "line":
        return _line_line(a[1], a[2], b[1], b[2])
    if a[0] == "line":
        return _line_circle(a[1], a[2], b[1], b[2])
    if b[0] == "line":
        return _line_circle(b[1], b[2], a[1], a[2])
    return _circle_circle(a[1], a[2], b[1], b[2])


def _prim(e):
    t = e.dxftype()
    if t == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        return ("line", a, (b - a).normalize())
    if t in ("ARC", "CIRCLE"):
        return ("circle", Vec2(e.dxf.center), e.dxf.radius)
    raise CadError(f"{t} is not supported here (use LINE, ARC or CIRCLE)")


def _offset_prims(p, d: float):
    if p[0] == "line":
        n = Vec2(-p[2].y, p[2].x)
        return [("line", p[1] + n * d, p[2]), ("line", p[1] - n * d, p[2])]
    out = [("circle", p[1], p[2] + d)]
    if p[2] - d > EPS:
        out.append(("circle", p[1], p[2] - d))
    return out


def _foot(p, q: Vec2) -> Vec2:
    if p[0] == "line":
        return p[1] + p[2] * (q - p[1]).dot(p[2])
    v = q - p[1]
    return p[1] + v.normalize() * p[2] if v.magnitude > EPS else p[1] + Vec2(p[2], 0)


def _default_pick(e) -> Vec2:
    t = e.dxftype()
    if t == "LINE":
        return (Vec2(e.dxf.start) + Vec2(e.dxf.end)) / 2
    if t == "ARC":
        s, en = e.dxf.start_angle, e.dxf.end_angle
        mid = math.radians(s + ((en - s) % 360) / 2)
        return Vec2(e.dxf.center) + Vec2(math.cos(mid), math.sin(mid)) * e.dxf.radius
    return Vec2(e.dxf.center) + Vec2(e.dxf.radius, 0)


def _tangent_centres(e1, e2, R, pick1, pick2):
    p1, p2 = _prim(e1), _prim(e2)
    k1 = Vec2(vec(pick1).vec2) if pick1 is not None else _default_pick(e1)
    k2 = Vec2(vec(pick2).vec2) if pick2 is not None else _default_pick(e2)
    best = None
    for o1 in _offset_prims(p1, R):
        for o2 in _offset_prims(p2, R):
            for c in _intersect(o1, o2):
                t1, t2 = _foot(p1, c), _foot(p2, c)
                score = t1.distance(k1) + t2.distance(k2)
                if best is None or score < best[0]:
                    best = (score, c, t1, t2)
    if best is None:
        raise CadError("No tangent circle of that radius exists between these objects")
    return best[1], best[2], best[3], k1, k2


def _trim_to(e, t: Vec2, keep: Vec2):
    """Shorten/extend LINE or ARC so it ends at t, keeping the part that contains `keep`."""
    kind = e.dxftype()
    if kind == "LINE":
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        d = b - a
        L2 = d.dot(d)
        tt, tk = (t - a).dot(d) / L2, (keep - a).dot(d) / L2
        if tk < tt:
            e.dxf.end = Vec3(t)
        else:
            e.dxf.start = Vec3(t)
    elif kind == "ARC":
        c = Vec2(e.dxf.center)
        s, en = e.dxf.start_angle % 360, e.dxf.end_angle % 360
        at = math.degrees(_ang(c, t)) % 360
        ak = math.degrees(_ang(c, keep)) % 360
        sweep = (en - s) % 360 or 360
        rt, rk = (at - s) % 360, (ak - s) % 360
        if rt <= sweep + 1e-9:  # tangent point on the arc: split there
            if rk < rt:
                e.dxf.end_angle = at
            else:
                e.dxf.start_angle = at
        else:  # outside: extend the nearer end
            if (s - at) % 360 < (at - en) % 360:
                e.dxf.start_angle = at
            else:
                e.dxf.end_angle = at


def _short_arc(lay, c: Vec2, r: float, t1: Vec2, t2: Vec2, attribs):
    a1, a2 = math.degrees(_ang(c, t1)), math.degrees(_ang(c, t2))
    if (a2 - a1) % 360 > 180:
        a1, a2 = a2, a1
    return lay.add_arc(c, r, a1, a2, dxfattribs=attribs)


@op(T, "fillet_any", mutates=True)
def fillet_any(ctx: Ctx, handle1: str, handle2: str, radius: float, pick1=None, pick2=None, trim: bool = True):
    """FILLET between any two of LINE, ARC, CIRCLE with a radius: tangent arc; lines and arcs are trimmed/extended to the tangent points (circles stay whole). pick1/pick2 = points on the parts to keep (choose the solution)."""
    e1, e2 = ctx.entity(handle1), ctx.entity(handle2)
    if radius <= 0:
        raise CadError("radius must be > 0 (use edit.fillet for a sharp corner between lines)")
    c, t1, t2, k1, k2 = _tangent_centres(e1, e2, float(radius), pick1, pick2)
    if trim:
        for e, t, k in ((e1, t1, k1), (e2, t2, k2)):
            if e.dxftype() != "CIRCLE":
                _trim_to(e, t, k)
    arc = _short_arc(_layout_of(e1), c, float(radius), t1, t2, _copy_attribs(e1))
    return {"handles": handles([e1, e2]), "created": [arc.dxf.handle], "center": [round(c.x, 6), round(c.y, 6)]}


@op("draw", "circle_ttr", mutates=True)
def circle_ttr(ctx: Ctx, handle1: str, handle2: str, radius: float, pick1=None, pick2=None, space=None, **props):
    """CIRCLE Tan-Tan-Radius: circle of radius tangent to two lines/arcs/circles; pick points choose which of the solutions."""
    e1, e2 = ctx.entity(handle1), ctx.entity(handle2)
    c, _t1, _t2, _k1, _k2 = _tangent_centres(e1, e2, float(radius), pick1, pick2)
    e = ctx.layout(space).add_circle(c, float(radius))
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle], "center": [round(c.x, 6), round(c.y, 6)]}


@op("draw", "circle_ttt", mutates=True)
def circle_ttt(ctx: Ctx, handle1: str, handle2: str, handle3: str, inside_point=None, space=None, **props):
    """CIRCLE Tan-Tan-Tan for three lines: the inscribed circle (or the excircle on the side of inside_point)."""
    ls = [ctx.entity(h) for h in (handle1, handle2, handle3)]
    if any(e.dxftype() != "LINE" for e in ls):
        raise CadError("circle_ttt works with three LINEs")
    prims = [_prim(e) for e in ls]
    verts = []
    for i in range(3):
        pts = _line_line(prims[i][1], prims[i][2], prims[(i + 1) % 3][1], prims[(i + 1) % 3][2])
        if not pts:
            raise CadError("Two of the lines are parallel")
        verts.append(pts[0])
    A, B, C = verts[2], verts[0], verts[1]  # A opposite line 1 ...
    a, b, cc = B.distance(C), C.distance(A), A.distance(B)
    cands = []
    for sa, sb, sc in ((1, 1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, -1)):
        w = sa * a + sb * b + sc * cc
        if abs(w) < 1e-12:
            continue
        centre = (A * (sa * a) + B * (sb * b) + C * (sc * cc)) / w
        r = abs((B - A).x * (centre - A).y - (B - A).y * (centre - A).x) / (B - A).magnitude
        cands.append((centre, r))
    target = Vec2(vec(inside_point).vec2) if inside_point is not None else (A + B + C) / 3
    centre, r = min(cands, key=lambda cr: cr[0].distance(target))
    e = ctx.layout(space).add_circle(centre, r)
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle], "center": [round(centre.x, 6), round(centre.y, 6)],
            "radius": round(r, 6)}


@op("draw", "circle_2p", mutates=True)
def circle_2p(ctx: Ctx, p1, p2, space=None, **props):
    """CIRCLE 2P: circle with p1-p2 as diameter."""
    a, b = vec(p1), vec(p2)
    e = ctx.layout(space).add_circle((a + b) / 2, a.distance(b) / 2)
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle]}


# ---------------------------------------------------------------------------
# exact polyline offset (arcs stay arcs)
# ---------------------------------------------------------------------------


def offset_polyline(pts, closed: bool, d: float):
    """pts = [(x, y, bulge)]; d > 0 = left of travel. Returns new [(x, y, bulge)] or raises."""
    n = len(pts)
    nseg = n if closed else n - 1
    segs = []
    for i in range(nseg):
        p0, p1 = Vec2(pts[i][:2]), Vec2(pts[(i + 1) % n][:2])
        b = pts[i][2]
        if p0.distance(p1) < EPS:
            continue
        if abs(b) < 1e-12:
            u = (p1 - p0).normalize()
            nl = Vec2(-u.y, u.x)
            segs.append({"k": "line", "s": p0 + nl * d, "e": p1 + nl * d, "u": u})
        else:
            c, r, th = _bulge_arc(p0, p1, b)
            r2 = r - d if th > 0 else r + d
            if r2 <= EPS:
                raise CadError("Offset larger than an arc radius of the polyline")
            segs.append({"k": "arc", "c": c, "r": r2, "ccw": th > 0, "th": th,
                         "s": c + (p0 - c).normalize() * r2, "e": c + (p1 - c).normalize() * r2})

    def prim(sg):
        return ("line", sg["s"], sg["u"]) if sg["k"] == "line" else ("circle", sg["c"], sg["r"])

    m = len(segs)
    joints = []
    for i in range(m if closed else m - 1):
        a, b = segs[i], segs[(i + 1) % m]
        if a["e"].distance(b["s"]) < 1e-7:
            joints.append(a["e"])
            continue
        cands = _intersect(prim(a), prim(b))
        guess = (a["e"] + b["s"]) / 2
        joints.append(min(cands, key=lambda q: q.distance(guess)) if cands else None)
    out = []
    for i, sg in enumerate(segs):
        start = joints[i - 1] if (closed or i > 0) else sg["s"]
        end = joints[i] if (closed or i < m - 1) else sg["e"]
        if start is None:
            start = sg["s"]
        if end is None:
            end = sg["e"]
        if sg["k"] == "line":
            if (end - start).dot(sg["u"]) <= EPS:
                raise CadError("Offset removes a straight segment (distance too large)")
            out.append((start.x, start.y, 0.0))
        else:
            a0, a1 = _ang(sg["c"], start), _ang(sg["c"], end)
            sweep = (a1 - a0) % (2 * math.pi) if sg["ccw"] else -((a0 - a1) % (2 * math.pi))
            if abs(sweep) < 1e-9 or abs(sweep) > abs(sg["th"]) + math.pi:
                raise CadError("Offset removes an arc segment (distance too large)")
            out.append((start.x, start.y, math.tan(sweep / 4)))
        if joints and ((i < len(joints) and joints[i] is None) and (closed or i < m - 1)):
            out.append((sg["e"].x, sg["e"].y, 0.0))  # gap: connect with a straight segment
    if not closed:
        last = segs[-1]["e"]
        out.append((last.x, last.y, 0.0))
    return out


def _signed_area(pts) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


@op(T, "offset_exact", mutates=True)
def offset_exact(ctx: Ctx, handle: str, distance: float, side_point=None):
    """OFFSET for 2D polylines with arc segments, keeping arcs as arcs (corners are extended/trimmed like AutoCAD). side_point picks the side; otherwise + = left / outward for closed polylines."""
    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("offset_exact works on LWPOLYLINE (use edit.offset for other objects)")
    pts = [tuple(p) for p in e.get_points("xyb")]
    d = abs(float(distance))
    cands = []
    for sgn in (1, -1):
        try:
            cands.append((sgn, offset_polyline(pts, e.closed, sgn * d)))
        except CadError:
            continue
    if not cands:
        raise CadError("Offset not possible at this distance")
    if side_point is not None:
        sp = Vec2(vec(side_point).vec2)
        from shapely.geometry import LineString, Point

        def dist(c):
            return LineString([(x, y) for x, y, _ in c[1]] + ([c[1][0][:2]] if e.closed else [])).distance(Point(sp.x, sp.y))

        sgn, res = min(cands, key=dist)
    else:
        want = 1 if float(distance) >= 0 else -1
        if e.closed:
            ccw = _signed_area([p[:2] for p in pts]) > 0
            want = -want if ccw else want  # outward is right of travel for counter-clockwise outlines
        sgn, res = next((c for c in cands if c[0] == want), cands[0])
    new = _layout_of(e).add_lwpolyline(res, format="xyb", close=e.closed, dxfattribs=_copy_attribs(e))
    return {"created": [new.dxf.handle], "side": "left" if sgn > 0 else "right"}


# ---------------------------------------------------------------------------
# chamfer variants
# ---------------------------------------------------------------------------


@op(T, "chamfer_angle", mutates=True)
def chamfer_angle(ctx: Ctx, handle1: str, handle2: str, distance: float, angle: float, pick1=None, pick2=None):
    """CHAMFER by distance on the first line and angle (deg) from it."""
    from .ops_edit import _corner, _set_near_end

    e1, e2, P, k1, K1, k2, K2 = _corner(ctx, handle1, handle2, pick1, pick2)
    u1 = (K1 - P).normalize()
    T1 = P + u1 * distance
    u2 = (K2 - P).normalize()
    phi = math.atan2(u1.x * u2.y - u1.y * u2.x, u1.dot(u2))
    ray = (-u1).rotate(-math.copysign(math.radians(angle), phi))  # turn towards the second line
    hit = _line_line(T1, ray, P, u2)
    if not hit:
        raise CadError("Chamfer line does not reach the second line")
    T2 = hit[0]
    line = _layout_of(e1).add_line(T1, T2, dxfattribs=_copy_attribs(e1))
    _set_near_end(e1, k1, T1)
    _set_near_end(e2, k2, T2)
    return {"handles": handles([e1, e2]), "created": [line.dxf.handle]}


@op(T, "chamfer_polyline", mutates=True)
def chamfer_polyline(ctx: Ctx, handle: str, distance1: float, distance2: float | None = None):
    """CHAMFER Polyline: bevel every straight corner of a 2D polyline."""
    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("chamfer_polyline needs an LWPOLYLINE")
    d2 = distance1 if distance2 is None else distance2
    pts = [(Vec2(x, y), b) for x, y, b in e.get_points("xyb")]
    n = len(pts)
    out = []
    for i in range(n):
        p, b = pts[i]
        if not e.closed and i in (0, n - 1) or pts[i - 1][1] or b:
            out.append((p.x, p.y, b))
            continue
        prev, nxt = pts[i - 1][0], pts[(i + 1) % n][0]
        if distance1 > prev.distance(p) or d2 > nxt.distance(p):
            raise CadError(f"Chamfer too large at vertex {i}")
        t1 = p + (prev - p).normalize() * distance1
        t2 = p + (nxt - p).normalize() * d2
        out += [(t1.x, t1.y, 0.0), (t2.x, t2.y, 0.0)]
    e.set_points(out, format="xyb")
    return {"handles": [e.dxf.handle], "vertices": len(out)}


# ---------------------------------------------------------------------------
# extend / lengthen for arcs and polyline arc ends
# ---------------------------------------------------------------------------


@op(T, "extend_arc_end", mutates=True)
def extend_arc_end(ctx: Ctx, handle: str, pick=None, boundary=None):
    """EXTEND an open polyline whose end segment is an arc: the arc continues on its circle to the nearest boundary."""
    from . import geom
    from .ops_edit import _cutters

    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE" or e.closed:
        raise CadError("extend_arc_end needs an open LWPOLYLINE")
    pts = list(e.get_points("xyb"))
    pk = Vec2(vec(pick).vec2) if pick is not None else None
    at_start = pk is not None and pk.distance(Vec2(pts[0][:2])) < pk.distance(Vec2(pts[-1][:2]))
    if at_start:
        p0, p1, b = Vec2(pts[1][:2]), Vec2(pts[0][:2]), -pts[0][2]
    else:
        p0, p1, b = Vec2(pts[-2][:2]), Vec2(pts[-1][:2]), pts[-2][2]
    if abs(b) < 1e-12:
        raise CadError("End segment is straight: use edit.extend")
    c, r, th = _bulge_arc(p0, p1, b)
    from shapely.geometry import LineString

    circle = LineString([(c.x + r * math.cos(t), c.y + r * math.sin(t)) for t in
                         [2 * math.pi * k / 1440 for k in range(1441)]])
    a_end = _ang(c, p1)
    best = None
    for cu in _cutters(ctx, e, boundary):
        for q in geom.intersection_points(circle, cu):
            a = _ang(c, Vec2(q.x, q.y))
            delta = (a - a_end) % (2 * math.pi) if th > 0 else (a_end - a) % (2 * math.pi)
            if delta > 1e-7 and (best is None or delta < best[0]):
                best = (delta, a)
    if best is None:
        raise CadError("No boundary reached by continuing the arc")
    new_end = c + Vec2(math.cos(best[1]), math.sin(best[1])) * r
    new_sweep = th + math.copysign(best[0], th)
    nb = math.tan(new_sweep / 4)
    if at_start:
        pts[0] = (new_end.x, new_end.y, -nb)
    else:
        pts[-2] = (pts[-2][0], pts[-2][1], nb)
        pts[-1] = (new_end.x, new_end.y, 0.0)
    e.set_points(pts, format="xyb")
    return {"handles": [e.dxf.handle], "extended_deg": round(math.degrees(best[0]), 6)}


@op(T, "lengthen_any", mutates=True)
def lengthen_any(ctx: Ctx, handle: str, delta: float | None = None, total: float | None = None,
                 percent: float | None = None, delta_angle: float | None = None, at_start: bool = False):
    """LENGTHEN for lines, arcs and open polylines: by delta length, to a total length, by percent, or (arcs) by delta_angle in degrees. Changes the end (or the start with at_start)."""
    from .ops_query import _length

    e = ctx.entity(handle)
    t = e.dxftype()
    L = _length(e)
    if percent is not None:
        target = L * float(percent) / 100
    elif total is not None:
        target = float(total)
    elif delta is not None:
        target = L + float(delta)
    elif delta_angle is None:
        raise CadError("Give delta, total, percent or delta_angle")
    else:
        target = None
    if t == "LINE":
        from .ops_edit import lengthen

        return lengthen(ctx, handle, total=target, at_start=at_start)
    if t == "ARC":
        r = e.dxf.radius
        add = math.radians(delta_angle) if target is None else (target - L) / r
        if at_start:
            e.dxf.start_angle = e.dxf.start_angle - math.degrees(add)
        else:
            e.dxf.end_angle = e.dxf.end_angle + math.degrees(add)
        return {"handles": [e.dxf.handle], "length": round(_length(e), 6)}
    if t == "LWPOLYLINE" and not e.closed:
        pts = list(e.get_points("xyb"))
        if target is None:
            raise CadError("delta_angle works on arcs only")
        add = target - L
        if at_start:
            pts = _reverse_xyb(pts)
        p0, p1, b = Vec2(pts[-2][:2]), Vec2(pts[-1][:2]), pts[-2][2]
        if abs(b) < 1e-12:
            u = (p1 - p0).normalize()
            if add < -p0.distance(p1):
                raise CadError("Cannot shorten past the last vertex")
            q = p1 + u * add
            pts[-1] = (q.x, q.y, 0.0)
        else:
            c, r, th = _bulge_arc(p0, p1, b)
            nth = th + math.copysign(add / r, th)
            a0 = _ang(c, p0)
            q = c + Vec2(math.cos(a0 + nth), math.sin(a0 + nth)) * r
            pts[-2] = (pts[-2][0], pts[-2][1], math.tan(nth / 4))
            pts[-1] = (q.x, q.y, 0.0)
        if at_start:
            pts = _reverse_xyb(pts)
        e.set_points(pts, format="xyb")
        return {"handles": [e.dxf.handle], "length": round(_length(e), 6)}
    raise CadError(f"Cannot lengthen {t}")


def _reverse_xyb(pts):
    """Reverse an open polyline [(x, y, bulge)]: segment i of the result is original segment n-2-i walked backwards."""
    n = len(pts)
    return [(pts[n - 1 - i][0], pts[n - 1 - i][1], -pts[n - 2 - i][2] if i < n - 1 else 0.0) for i in range(n)]


# ---------------------------------------------------------------------------
# AutoCAD-style JOIN
# ---------------------------------------------------------------------------


@op(T, "join_same", mutates=True)
def join_same(ctx: Ctx, sel, tolerance: float = 1e-6):
    """JOIN like AutoCAD for same-type objects: collinear touching/overlapping LINEs become one LINE; ARCs on the same circle become one ARC (or a CIRCLE when closed). Mixed objects: use edit.join (polyline)."""
    ents = select_from(ctx, sel)
    kinds = {e.dxftype() for e in ents}
    lay = _layout_of(ents[0])
    if kinds == {"LINE"}:
        a0, b0 = Vec2(ents[0].dxf.start), Vec2(ents[0].dxf.end)
        u = (b0 - a0).normalize()
        ts = []
        for e in ents:
            for p in (Vec2(e.dxf.start), Vec2(e.dxf.end)):
                off = abs(u.x * (p.y - a0.y) - u.y * (p.x - a0.x))
                if off > tolerance:
                    raise CadError("Lines are not collinear")
                ts.append((p - a0).dot(u))
        new = lay.add_line(a0 + u * min(ts), a0 + u * max(ts), dxfattribs=_copy_attribs(ents[0]))
    elif kinds <= {"ARC"}:
        c, r = Vec2(ents[0].dxf.center), ents[0].dxf.radius
        spans = []
        for e in ents:
            if Vec2(e.dxf.center).distance(c) > tolerance or abs(e.dxf.radius - r) > tolerance:
                raise CadError("Arcs are not on the same circle")
            spans.append((e.dxf.start_angle % 360, (e.dxf.end_angle - e.dxf.start_angle) % 360))
        spans.sort()
        start, length = spans[0]
        changed = True
        while changed:
            changed = False
            for s, ln in spans:
                if (s - start) % 360 <= length + 1e-6 and (s - start) % 360 + ln > length:
                    length = (s - start) % 360 + ln
                    changed = True
        if length >= 360 - 1e-6:
            new = lay.add_circle(c, r, dxfattribs=_copy_attribs(ents[0]))
        else:
            new = lay.add_arc(c, r, start, start + length, dxfattribs=_copy_attribs(ents[0]))
    else:
        raise CadError("join_same needs only LINEs or only ARCs; use edit.join for mixed objects")
    for e in ents:
        lay.delete_entity(e)
    return {"created": [new.dxf.handle], "type": new.dxftype()}


# ---------------------------------------------------------------------------
# STRETCH for arcs, blocks, text, splines
# ---------------------------------------------------------------------------


@op(T, "stretch", mutates=True)
def stretch(ctx: Ctx, window, vector=None, from_point=None, to_point=None, space=None):
    """STRETCH: objects entirely inside the window move; line and polyline vertices inside move; arcs with an end inside are re-shaped keeping their height; blocks, texts, points and circles move when their insertion point/centre is inside; spline control and fit points inside move."""
    from ezdxf import bbox

    from .ops_edit import _vector

    v = _vector(vector, from_point, to_point)
    (x1, y1), (x2, y2) = [tuple(vec(p).vec2) for p in window]
    lo, hi = Vec2(min(x1, x2), min(y1, y2)), Vec2(max(x1, x2), max(y1, y2))

    def inside(p) -> bool:
        return lo.x <= p.x <= hi.x and lo.y <= p.y <= hi.y

    move = Matrix44.translate(v.x, v.y, v.z)
    plan = []  # decide everything first, then change (so nothing moves twice)
    for e in ctx.select(crossing=window, space=space):
        ext = bbox.extents([e], fast=True)
        plan.append((e, inside(ext.extmin) and inside(ext.extmax)))
    done = []
    for e, whole in plan:
        t = e.dxftype()
        if whole:
            e.transform(move)
        elif t == "LINE":
            if inside(e.dxf.start):
                e.dxf.start = Vec3(e.dxf.start) + v
            if inside(e.dxf.end):
                e.dxf.end = Vec3(e.dxf.end) + v
        elif t == "LWPOLYLINE":
            e.set_points([((x + v.x, y + v.y, b) if inside(Vec2(x, y)) else (x, y, b))
                          for x, y, b in e.get_points("xyb")], format="xyb")
        elif t == "ARC":
            c, r = Vec2(e.dxf.center), e.dxf.radius
            s0, s1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
            ps = c + Vec2(math.cos(s0), math.sin(s0)) * r
            pe = c + Vec2(math.cos(s1), math.sin(s1)) * r
            sweep = (s1 - s0) % (2 * math.pi)
            h = r * (1 - math.cos(sweep / 2))  # sagitta stays the same
            if inside(ps):
                ps = ps + Vec2(v.x, v.y)
            if inside(pe):
                pe = pe + Vec2(v.x, v.y)
            chord = ps.distance(pe)
            if chord < EPS or h < EPS:
                continue
            r2 = (chord * chord / 4 + h * h) / (2 * h)
            nrm = Vec2(-(pe - ps).y, (pe - ps).x).normalize()
            c2 = (ps + pe) / 2 + nrm * (r2 - h)
            e.dxf.center = Vec3(c2)
            e.dxf.radius = r2
            e.dxf.start_angle = math.degrees(_ang(c2, ps))
            e.dxf.end_angle = math.degrees(_ang(c2, pe))
        elif t in ("INSERT", "TEXT", "MTEXT", "POINT", "CIRCLE"):
            key = {"POINT": "location", "CIRCLE": "center"}.get(t, "insert")
            if not inside(Vec2(e.dxf.get(key))):
                continue
            e.transform(move)
        elif t == "SPLINE":
            e.control_points = [Vec3(p) + v if inside(Vec2(p)) else Vec3(p) for p in e.control_points]
            if e.fit_points:
                e.fit_points = [Vec3(p) + v if inside(Vec2(p)) else Vec3(p) for p in e.fit_points]
        else:
            continue
        done.append(e)
    return {"handles": handles(done)}


# ---------------------------------------------------------------------------
# SPLINEDIT, PEDIT vertices, HATCHEDIT, gradient
# ---------------------------------------------------------------------------


@op(T, "splinedit", mutates=True)
def splinedit(ctx: Ctx, handle: str, action: str, points: list | None = None, index: int | None = None,
              point=None, precision: float = 0.01):
    """SPLINEDIT: action close | open | set_fit_points (points) | move_control_point (index, point) | add_fit_point (index, point) | to_polyline (precision) | reverse."""
    e = ctx.entity(handle)
    if e.dxftype() != "SPLINE":
        raise CadError("splinedit needs a SPLINE")
    lay = _layout_of(e)
    if action == "close":
        e.closed = True
    elif action == "open":
        e.closed = False
    elif action == "set_fit_points":
        e.fit_points = [vec(p) for p in points or []]
        e.control_points = []
        e.knots = []
    elif action == "add_fit_point":
        fps = list(e.fit_points)
        if not fps:
            raise CadError("This spline has no fit points; use move_control_point")
        fps.insert(int(index if index is not None else len(fps)), vec(point))
        e.fit_points = fps
        e.control_points = []
        e.knots = []
    elif action == "move_control_point":
        cps = list(e.control_points)
        cps[int(index)] = vec(point)
        e.control_points = cps
    elif action == "to_polyline":
        from ezdxf import path as ezpath

        pts = [(p.x, p.y) for p in ezpath.make_path(e).flattening(precision)]
        new = lay.add_lwpolyline(pts, close=e.closed, dxfattribs=_copy_attribs(e))
        lay.delete_entity(e)
        return {"created": [new.dxf.handle]}
    elif action == "reverse":
        e.reverse()
    else:
        raise CadError("action: close, open, set_fit_points, add_fit_point, move_control_point, to_polyline, reverse")
    return {"handles": [e.dxf.handle]}


@op(T, "pedit_vertex", mutates=True)
def pedit_vertex(ctx: Ctx, handle: str, action: str, index: int, point=None, bulge: float | None = None,
                 start_width: float | None = None, end_width: float | None = None):
    """PEDIT Edit vertex: action move | insert (after index) | remove | set (bulge / segment widths of the segment starting at index)."""
    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("pedit_vertex needs an LWPOLYLINE")
    pts = [list(p) for p in e.get_points("xyseb")]
    i = int(index)
    if action == "move":
        x, y = vec(point).vec2
        pts[i][0], pts[i][1] = x, y
    elif action == "insert":
        x, y = vec(point).vec2
        pts.insert(i + 1, [x, y, 0, 0, 0])
    elif action == "remove":
        if len(pts) <= 2:
            raise CadError("A polyline needs at least 2 vertices")
        pts.pop(i)
    elif action == "set":
        if bulge is not None:
            pts[i][4] = float(bulge)
        if start_width is not None:
            pts[i][2] = float(start_width)
        if end_width is not None:
            pts[i][3] = float(end_width)
    else:
        raise CadError("action: move, insert, remove, set")
    e.set_points([tuple(p) for p in pts], format="xyseb")
    return {"handles": [e.dxf.handle], "vertices": len(pts)}


@op(T, "pedit_spline", mutates=True)
def pedit_spline(ctx: Ctx, handle: str, keep_polyline: bool = False):
    """PEDIT Spline/Fit: turn a polyline into a smooth SPLINE through its vertices."""
    e = ctx.entity(handle)
    if e.dxftype() != "LWPOLYLINE":
        raise CadError("pedit_spline needs an LWPOLYLINE")
    pts = [Vec3(x, y, 0) for x, y in e.get_points("xy")]
    lay = _layout_of(e)
    if e.closed:
        pts.append(pts[0])
    sp = lay.add_spline(pts, dxfattribs=_copy_attribs(e))
    if not keep_polyline:
        lay.delete_entity(e)
    return {"created": [sp.dxf.handle]}


@op(T, "hatchedit", mutates=True)
def hatchedit(ctx: Ctx, handle: str, pattern: str | None = None, scale: float | None = None,
              angle: float | None = None, color=None, gradient: dict | None = None):
    """HATCHEDIT: change pattern, scale, angle, colour of an existing hatch (boundary kept), or make it a gradient {color1, color2, rotation, name}."""
    h = ctx.entity(handle)
    if h.dxftype() != "HATCH":
        raise CadError("hatchedit needs a HATCH")
    if gradient:
        _apply_gradient(h, gradient)
    elif pattern or scale or angle is not None:
        name = (pattern or h.dxf.pattern_name).upper()
        if name == "SOLID":
            h.set_solid_fill()
        else:
            h.set_pattern_fill(name, scale=float(scale or h.dxf.get("pattern_scale", 1.0)),
                               angle=float(angle if angle is not None else h.dxf.get("pattern_angle", 0.0)), style=0)
    if color is not None:
        from .core import apply_props

        apply_props(ctx.doc, h, {"color": color})
    return {"handle": handle, "pattern": h.dxf.pattern_name}


def _rgb(c):
    from .core import parse_color

    aci, rgb = parse_color(c)
    if rgb:
        return rgb
    from ezdxf.colors import aci2rgb

    return tuple(aci2rgb(aci or 7))


def _apply_gradient(h, g: dict):
    from ezdxf.colors import RGB

    names = ("LINEAR", "CYLINDER", "INVCYLINDER", "SPHERICAL", "INVSPHERICAL", "HEMISPHERICAL",
             "INVHEMISPHERICAL", "CURVED", "INVCURVED")
    name = str(g.get("name", "LINEAR")).upper()
    if name not in names:
        raise CadError(f"gradient name must be one of {names}")
    h.set_gradient(RGB(*_rgb(g.get("color1", "blue"))), RGB(*_rgb(g.get("color2", "white"))),
                   rotation=float(g.get("rotation", 0)), centered=float(g.get("centered", 0)), name=name)


@op("draw", "gradient", mutates=True)
def gradient(ctx: Ctx, boundary=None, boundary_handles=None, color1="blue", color2="white", rotation: float = 0,
             name: str = "LINEAR", centered: float = 0, space=None, **props):
    """GRADIENT fill: like draw.hatch but with a two-colour gradient (LINEAR, CYLINDER, SPHERICAL, CURVED ... and INV* variants)."""
    from .ops_draw import hatch

    res = hatch(ctx, boundary=boundary, boundary_handles=boundary_handles, pattern="SOLID", space=space, **props)
    for h in res["handles"]:
        _apply_gradient(ctx.entity(h), {"color1": color1, "color2": color2, "rotation": rotation, "name": name,
                                        "centered": centered})
    return res


# ---------------------------------------------------------------------------
# 3D transformations
# ---------------------------------------------------------------------------


@op(T, "rotate3d", mutates=True)
def rotate3d(ctx: Ctx, sel, axis_p1, axis_p2, angle: float, copy: bool = False):
    """3DROTATE / ROTATE3D: rotate around any axis through axis_p1 -> axis_p2 (right-hand rule, degrees)."""
    ents = select_from(ctx, sel)
    if copy:
        ents = [_copy(e) for e in ents]
    a, b = vec(axis_p1), vec(axis_p2)
    m = Matrix44.chain(Matrix44.translate(-a.x, -a.y, -a.z), Matrix44.axis_rotate(b - a, math.radians(angle)),
                       Matrix44.translate(a.x, a.y, a.z))
    return {"handles": handles(ents), "failed": _transform(ents, m)}


@op(T, "mirror3d", mutates=True)
def mirror3d(ctx: Ctx, sel, p1, p2, p3, keep_original: bool = True):
    """3DMIRROR / MIRROR3D: mirror across the plane through three points."""
    ents = select_from(ctx, sel)
    a, b, c = vec(p1), vec(p2), vec(p3)
    n = (b - a).cross(c - a).normalize()
    if n.magnitude < 0.5:
        raise CadError("The three points are collinear")
    # Householder reflection about the plane: x' = x - 2 ((x - a)·n) n
    r = [[(1 if i == j else 0) - 2 * n[i] * n[j] for j in range(3)] for i in range(3)]
    m = Matrix44([r[0][0], r[1][0], r[2][0], 0, r[0][1], r[1][1], r[2][1], 0, r[0][2], r[1][2], r[2][2], 0, 0, 0, 0, 1])
    m = Matrix44.chain(Matrix44.translate(-a.x, -a.y, -a.z), m, Matrix44.translate(a.x, a.y, a.z))
    targets = [_copy(e) for e in ents] if keep_original else ents
    return {"handles": handles(targets), "failed": _transform(targets, m)}


@op(T, "array3d", mutates=True)
def array3d(ctx: Ctx, sel, rows: int = 1, cols: int = 1, levels: int = 1, row_spacing: float = 0,
            col_spacing: float = 0, level_spacing: float = 0, polar_axis: list | None = None, count: int = 0,
            total_angle: float = 360):
    """3DARRAY: rectangular (rows x cols x levels with spacings in Y, X, Z) or polar around an axis polar_axis=[p1, p2] with count items over total_angle."""
    ents = select_from(ctx, sel)
    created, failed = [], []
    if polar_axis:
        a, b = vec(polar_axis[0]), vec(polar_axis[1])
        step = total_angle / count if abs(total_angle) >= 360 else total_angle / max(1, count - 1)
        for i in range(1, count):
            m = Matrix44.chain(Matrix44.translate(-a.x, -a.y, -a.z),
                               Matrix44.axis_rotate(b - a, math.radians(step * i)), Matrix44.translate(a.x, a.y, a.z))
            for e in ents:
                new = _copy(e)
                failed += _transform([new], m)
                created.append(new)
    else:
        for lv in range(levels):
            for r in range(rows):
                for c in range(cols):
                    if lv == r == c == 0:
                        continue
                    for e in ents:
                        new = _copy(e)
                        failed += _transform([new], Matrix44.translate(c * col_spacing, r * row_spacing,
                                                                       lv * level_spacing))
                        created.append(new)
    return {"created": handles(created), "failed": failed}


# ---------------------------------------------------------------------------
# EXTEND for splines and ellipse arcs, JOIN into a spline
# ---------------------------------------------------------------------------


def _first_hit(f, t0: float, t1: float, cutters, steps: int = 400):
    """Smallest t in (t0, t1] where the path f(t) (2D points) crosses a cutter; chord search plus bisection."""
    from shapely.geometry import LineString, Point

    ts = [t0 + (t1 - t0) * k / steps for k in range(steps + 1)]
    pts = [tuple(f(t)) for t in ts]

    def crosses(a, b):
        """The chord a-b meets a cutter somewhere other than at a (the current end itself may touch one)."""
        if math.dist(a, b) < 1e-12:
            return False
        seg, pa = LineString([a, b]), Point(a)
        return any(seg.intersects(c) and seg.intersection(c).hausdorff_distance(pa) > 1e-9 for c in cutters)

    for k in range(steps):
        if crosses(pts[k], pts[k + 1]):
            lo, hi = ts[k], ts[k + 1]
            for _ in range(60):  # the chord shrinks onto the curve, so the hit converges to the exact crossing
                mid = (lo + hi) / 2
                if crosses(tuple(f(lo)), tuple(f(mid))):
                    hi = mid
                else:
                    lo = mid
            return hi
    return None


def extend_curve(ctx: Ctx, e, pick=None, boundary=None):
    """EXTEND a SPLINE (along the natural continuation of its end span) or an ELLIPSE arc (along the ellipse)."""
    from ezdxf import bbox

    from . import nurbs
    from .ops_edit import _cutters

    cutters = _cutters(ctx, e, boundary)
    if not cutters:
        raise CadError("No boundary edges")
    pk = Vec2(vec(pick).vec2) if pick is not None else None
    if e.dxftype() == "ELLIPSE":
        el = e.construction_tool()
        sp, ep = e.dxf.start_param, e.dxf.end_param
        if abs((ep - sp) % math.tau) < 1e-9:
            raise CadError("A full ellipse has no end to extend")
        p_s, p_e = Vec2(el.start_point), Vec2(el.end_point)
        at_start = pk is not None and pk.distance(p_s) < pk.distance(p_e)
        c, maj, mnr = Vec3(el.center), Vec3(el.major_axis), Vec3(el.minor_axis)
        span = (ep - sp) % math.tau

        def f(d):  # d = parameter distance beyond the end (or before the start)
            t = sp - d if at_start else ep + d
            q = c + maj * math.cos(t) + mnr * math.sin(t)
            return (q.x, q.y)

        d = _first_hit(f, 0.0, math.tau - span, cutters, steps=720)
        if d is None:
            raise CadError("No boundary reached by continuing the ellipse")
        if at_start:
            e.dxf.start_param = (sp - d) % math.tau
        else:
            e.dxf.end_param = (ep + d) % math.tau
        return {"handles": [e.dxf.handle], "extended_param_deg": round(math.degrees(d), 6)}
    # SPLINE
    bs = e.construction_tool()
    p, U, Pw = nurbs.from_bspline(bs)
    if not nurbs.is_clamped(p, U) or e.closed:
        raise CadError("Only open (clamped) splines can be extended")
    p_s, p_e = Vec2(nurbs.proj(Pw[0])[:2]), Vec2(nurbs.proj(Pw[-1])[:2])
    at_start = pk is not None and pk.distance(p_s) < pk.distance(p_e)
    if at_start:
        U = [U[0] + U[-1] - u for u in reversed(U)]
        Pw = Pw[::-1].copy()
    a = max(u for u in U if u < U[-1])
    while U.count(a) < p:
        U, Pw = nurbs.insert_knot(p, U, Pw, a)
    B = Pw[-(p + 1):]
    ext = bbox.extents(e.get_layout(), fast=True)
    reach = (ext.size.magnitude if ext.has_data else 1e4) * 4 + 1
    seg_len = max(float(np.linalg.norm(np.diff(nurbs.proj(B), axis=0), axis=1).sum()), 1e-9)
    t_max = 1.0
    while t_max < 64 and seg_len * (t_max - 1) < reach:
        t_max *= 2
    t = _first_hit(lambda s: nurbs.point(B, s)[:2], 1.0, t_max, cutters, steps=800)
    if t is None:
        raise CadError("No boundary reached by continuing the spline")
    _pt, left, _right = nurbs.casteljau(B, t)
    if np.any(left[:, 3] <= 0):
        raise CadError("The rational spline cannot be continued that far")
    Pw = Pw.copy()
    Pw[-(p + 1):] = left
    if at_start:
        U = [U[0] + U[-1] - u for u in reversed(U)]
        Pw = Pw[::-1]
    old = Vec3(p_s.x, p_s.y, 0) if at_start else Vec3(p_e.x, p_e.y, 0)
    e.apply_construction_tool(nurbs.to_bspline(p, U, Pw))
    e.fit_points = []
    end = nurbs.proj(Pw[0] if at_start else Pw[-1])
    return {"handles": [e.dxf.handle], "new_end": [round(float(v), 6) for v in end],
            "extended_by": round(Vec2(old).distance(Vec2(float(end[0]), float(end[1]))), 6)}


def join_to_spline(ctx: Ctx, ents, tolerance: float = 1e-6):
    """JOIN with splines/ellipse arcs: touching lines, arcs, polylines, ellipse arcs and splines become one SPLINE (exact: arcs and ellipses as rational spans)."""
    from . import nurbs

    pieces = []
    for e in ents:
        try:
            segs = nurbs.entity_segments(e)
        except ValueError as ex:
            raise CadError(str(ex)) from ex
        pieces.append(segs)
    lay = _layout_of(ents[0])
    attribs = _copy_attribs(ents[0])

    def ends(segs):
        return nurbs.proj(segs[0][0]), nurbs.proj(segs[-1][-1])

    def close(a, b):
        return float(np.linalg.norm(a - b)) <= tolerance

    remaining = pieces[:]
    chains = []
    while remaining:
        chain = remaining.pop(0)
        grown = True
        while grown:
            grown = False
            for idx, segs in enumerate(remaining):
                cs, ce = ends(chain)
                s, t = ends(segs)
                if close(s, ce):
                    chain = chain + segs
                elif close(t, ce):
                    chain = chain + nurbs.reverse_segments(segs)
                elif close(t, cs):
                    chain = segs + chain
                elif close(s, cs):
                    chain = nurbs.reverse_segments(segs) + chain
                else:
                    continue
                remaining.pop(idx)
                grown = True
                break
        chains.append(chain)
    created = []
    for chain in chains:
        p, U, Pw = nurbs.from_segments(chain)
        sp = lay.add_spline(dxfattribs=attribs)
        sp.apply_construction_tool(nurbs.to_bspline(p, U, Pw))
        created.append(sp)
    joined = handles(ents)
    for e in ents:
        lay.delete_entity(e)
    return {"created": handles(created), "deleted": joined, "type": "SPLINE", "pieces": len(chains)}
