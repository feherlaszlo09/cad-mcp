"""Small NURBS toolkit in homogeneous coordinates (x·w, y·w, z·w, w).

Used to extend splines along their own curve (EXTEND) and to join lines, arcs, ellipse
arcs, polylines and splines into one spline (JOIN): Boehm knot insertion, Bezier
decomposition, degree elevation, de Casteljau subdivision (also beyond t = 1, which is the
natural continuation of the end span), and conversion of entities to rational Bezier
segments."""

from __future__ import annotations

import math

import numpy as np
from ezdxf.math import BSpline, Vec3


def hom(points, weights=None) -> np.ndarray:
    P = np.asarray([tuple(Vec3(p)) for p in points], float)
    w = np.ones(len(P)) if weights is None or len(weights) == 0 else np.asarray(weights, float)
    return np.hstack([P * w[:, None], w[:, None]])


def proj(H) -> np.ndarray:
    H = np.asarray(H, float)
    return H[..., :3] / H[..., 3:4]


def from_bspline(bs: BSpline):
    return bs.degree, [float(u) for u in bs.knots()], hom(bs.control_points, bs.weights())


def to_bspline(p: int, U, Pw) -> BSpline:
    Pw = np.asarray(Pw, float)
    w = Pw[:, 3]
    pts = [Vec3(*q) for q in proj(Pw)]
    return BSpline(pts, order=p + 1, knots=list(U), weights=None if np.allclose(w, 1.0) else list(w))


def is_clamped(p: int, U) -> bool:
    return all(u == U[0] for u in U[: p + 1]) and all(u == U[-1] for u in U[-p - 1:])


def insert_knot(p: int, U, Pw, u: float):
    """Boehm: insert knot u once (U[p] <= u < U[-p-1])."""
    U = list(U)
    Pw = np.asarray(Pw, float)
    k = max(i for i in range(len(U) - 1) if U[i] <= u < U[i + 1])
    n = len(Pw)
    Q = np.zeros((n + 1, 4))
    Q[: k - p + 1] = Pw[: k - p + 1]
    for i in range(k - p + 1, k + 1):
        a = (u - U[i]) / (U[i + p] - U[i])
        Q[i] = a * Pw[i] + (1 - a) * Pw[i - 1]
    Q[k + 1:] = Pw[k:]
    U.insert(k + 1, u)
    return U, Q


def bezier_segments(p: int, U, Pw) -> list[np.ndarray]:
    """Rational Bezier segments (homogeneous control points) of a clamped NURBS curve."""
    if not is_clamped(p, U):
        raise ValueError("only clamped (open) splines")
    U, Pw = list(U), np.asarray(Pw, float)
    for u in sorted(set(U[p + 1: len(U) - p - 1])):
        while U.count(u) < p:
            U, Pw = insert_knot(p, U, Pw, u)
    return [Pw[i * p: i * p + p + 1] for i in range((len(Pw) - 1) // p)]


def elevate(B, to: int) -> np.ndarray:
    B = np.asarray(B, float)
    while len(B) - 1 < to:
        n = len(B) - 1
        Q = np.zeros((n + 2, 4))
        Q[0], Q[-1] = B[0], B[-1]
        for i in range(1, n + 1):
            a = i / (n + 1)
            Q[i] = a * B[i - 1] + (1 - a) * B[i]
        B = Q
    return B


def casteljau(B, t: float):
    """Point at t and the control polygons of [0, t] and [t, 1]; t > 1 extends the segment."""
    pts = [np.asarray(b, float) for b in B]
    left, right = [pts[0]], [pts[-1]]
    while len(pts) > 1:
        pts = [(1 - t) * a + t * b for a, b in zip(pts, pts[1:])]
        left.append(pts[0])
        right.append(pts[-1])
    return pts[0], np.array(left), np.array(right[::-1])


def point(B, t: float) -> np.ndarray:
    return proj(casteljau(B, t)[0])


def reverse_segments(segs):
    return [np.asarray(s, float)[::-1] for s in reversed(segs)]


def from_segments(segs):
    """One clamped NURBS (degree = highest segment degree) through consecutive Bezier segments;
    knot spans follow the control polygon lengths."""
    p = max(len(s) - 1 for s in segs)
    out = []
    for s in segs:
        s = elevate(s, p)
        if out:
            s = s * (out[-1][-1][3] / s[0][3])  # same weight at the joint (a rational Bezier is scale invariant)
        out.append(s)
    Pw = [out[0][0]] + [q for s in out for q in s[1:]]
    spans = [max(float(np.sum(np.linalg.norm(np.diff(proj(s), axis=0), axis=1))), 1e-9) for s in out]
    U = [0.0] * (p + 1)
    acc = 0.0
    for L in spans[:-1]:
        acc += L
        U += [acc] * p
    U += [acc + spans[-1]] * (p + 1)
    return p, U, np.array(Pw)


def entity_segments(e) -> list[np.ndarray]:
    """Rational Bezier segments of a LINE, ARC, CIRCLE, ELLIPSE, SPLINE or LWPOLYLINE (WCS)."""
    from ezdxf.math import (
        bulge_to_arc,
        rational_bspline_from_arc,
        rational_bspline_from_ellipse,
    )

    t = e.dxftype()
    if t == "LINE":
        return [hom([e.dxf.start, e.dxf.end])]
    if t in ("ARC", "CIRCLE"):
        ocs = e.ocs()
        sa, ea = (e.dxf.start_angle, e.dxf.end_angle) if t == "ARC" else (0.0, 360.0)
        bs = rational_bspline_from_arc(center=Vec3(e.dxf.center), radius=e.dxf.radius, start_angle=sa,
                                       end_angle=ea if ea > sa else ea + 360)
        p, U, Pw = from_bspline(bs)
        segs = bezier_segments(p, U, Pw)
        if ocs.transform:
            segs = [hom([ocs.to_wcs(Vec3(*q)) for q in proj(s)], s[:, 3]) for s in segs]
        return segs
    if t == "ELLIPSE":
        bs = rational_bspline_from_ellipse(e.construction_tool())
        return bezier_segments(*from_bspline(bs))
    if t == "SPLINE":
        return bezier_segments(*from_bspline(e.construction_tool()))
    if t == "LWPOLYLINE":
        pts = list(e.get_points("xyb"))
        if e.closed:
            pts.append(pts[0])
        elev = e.dxf.get("elevation", 0.0)
        ocs = e.ocs()
        segs = []
        for (x0, y0, b), (x1, y1, _b) in zip(pts, pts[1:]):
            a, z = Vec3(x0, y0, elev), Vec3(x1, y1, elev)
            if abs(b) < 1e-12:
                local = [hom([a, z])]
            else:
                c, sa, ea, r = bulge_to_arc(a, z, b)
                sa, ea = math.degrees(sa) % 360, math.degrees(ea) % 360
                bs = rational_bspline_from_arc(center=Vec3(c.x, c.y, elev), radius=r, start_angle=sa,
                                               end_angle=ea if ea > sa else ea + 360)
                local = bezier_segments(*from_bspline(bs))
                if b < 0:  # bulge_to_arc returns the arc counter-clockwise: walk it from a to z
                    local = reverse_segments(local)
            if ocs.transform:
                local = [hom([ocs.to_wcs(Vec3(*q)) for q in proj(s)], s[:, 3]) for s in local]
            segs += local
        return segs
    raise ValueError(f"cannot convert {t} to a spline")
