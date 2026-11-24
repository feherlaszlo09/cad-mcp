"""Geometry helpers for trim/extend/offset/join, built on shapely."""

from __future__ import annotations

import math

from ezdxf import bbox
from ezdxf import path as ezpath
from ezdxf.entities import DXFGraphic
from ezdxf.math import Vec2, Vec3
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

TOL = 1e-9


def flatten_distance(e: DXFGraphic) -> float:
    ext = bbox.extents([e], fast=True)
    size = ext.size.magnitude if ext.has_data else 1.0
    return max(size * 1e-4, 1e-6)


def to_shape(e: DXFGraphic) -> BaseGeometry | None:
    """Entity as shapely line geometry (curves flattened). None if it has no path."""
    t = e.dxftype()
    if t == "INSERT":
        parts = [to_shape(v) for v in e.virtual_entities()]
        lines = []
        for p in parts:
            if p is None:
                continue
            lines.extend(p.geoms if isinstance(p, MultiLineString) else [p])
        return MultiLineString(lines) if lines else None
    if t in ("XLINE", "RAY"):
        start = Vec3(e.dxf.start)
        d = Vec3(e.dxf.unit_vector).normalize() * 1e7
        a = start - d if t == "XLINE" else start
        return LineString([(a.x, a.y), ((start + d).x, (start + d).y)])
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        return None
    pts = [(v.x, v.y) for v in p.flattening(flatten_distance(e))]
    if len(pts) < 2:
        return None
    return LineString(pts)


def intersection_points(a: BaseGeometry, b: BaseGeometry) -> list[Vec2]:
    inter = a.intersection(b)
    out: list[Vec2] = []

    def collect(g):
        if g.is_empty:
            return
        if g.geom_type == "Point":
            out.append(Vec2(g.x, g.y))
        elif g.geom_type in ("MultiPoint", "GeometryCollection", "MultiLineString"):
            for sub in g.geoms:
                collect(sub)
        elif g.geom_type == "LineString":  # overlap: use its end points
            cs = list(g.coords)
            out.append(Vec2(cs[0]))
            out.append(Vec2(cs[-1]))

    collect(inter)
    return out


def dedupe(values: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def angle_of(center: Vec2, p: Vec2) -> float:
    return math.degrees(math.atan2(p.y - center.y, p.x - center.x)) % 360


def ccw_sweep(start: float, end: float) -> float:
    s = (end - start) % 360
    return 360.0 if abs(s) < 1e-12 else s


def line_intersection(p1: Vec2, d1: Vec2, p2: Vec2, d2: Vec2) -> Vec2 | None:
    cross = d1.x * d2.y - d1.y * d2.x
    if abs(cross) < 1e-12:
        return None
    t = ((p2.x - p1.x) * d2.y - (p2.y - p1.y) * d2.x) / cross
    return p1 + d1 * t


def point_on(shape: LineString, p: Vec2) -> float:
    return shape.project(Point(p.x, p.y))
