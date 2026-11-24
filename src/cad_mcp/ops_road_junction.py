"""Tool `road` (continued): at-grade intersections (szintbeni csomópont) and
longitudinal drainage (hosszirányú vízelvezetés): ditch bottom design along the
road, flow directions, low points, culverts (átereszek) and Manning capacity."""

from __future__ import annotations

import math

from ezdxf.math import Vec2
from shapely.geometry import LineString, Point

from .core import CadError, Ctx, ensure_layer, ensure_linetype, op
from .ops_road import (DEFAULT_TEMPLATE, _load, _m, _se_for, _seg_type, get_alignment, get_profile)
from .road_geom import Alignment, format_station

T = "road"

# ---------------------------------------------------------------------------
# intersection
# ---------------------------------------------------------------------------


def _curve(al: Alignment, offset: float, s0: float, s1: float, step: float = 0.25) -> LineString:
    s0, s1 = max(al.start_station, min(s0, s1)), min(al.end_station, max(s0, s1))
    n = max(2, int((s1 - s0) / step) + 1)
    return LineString([al.point_at(s0 + (s1 - s0) * i / (n - 1), offset)[:2] for i in range(n)])


def _junction_point(main: Alignment, side: Alignment, main_width: float):
    a, b = main.dense(0.25), side.dense(0.25)
    hit = a.intersection(b)
    if not hit.is_empty:
        pts = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
        if pts:
            p = pts[0]
            return Vec2(p.x, p.y)
    # T junction drawn up to (near) the main road: use the side road end nearest to the main axis
    ends = [Vec2(side.point_at(side.start_station)[:2]), Vec2(side.point_at(side.end_station)[:2])]
    best = min(ends, key=lambda e: a.distance(Point(e.x, e.y)))
    if a.distance(Point(best.x, best.y)) > main_width:
        raise CadError("The two alignments neither cross nor meet: move the side road end onto the main road")
    q = a.interpolate(a.project(Point(best.x, best.y)))
    return Vec2(q.x, q.y)


@op(T, "intersection", mutates=True)
def intersection(ctx: Ctx, main: str, side: str, main_width: float = 7.0, side_width: float = 6.0,
                 radius=10.0, extent: float = 40.0, layer: str = "BURKOLATSZEL", space=None):
    """At-grade intersection (szintbeni csomópont, T or X) of two alignments: pavement edges of both roads (total widths main_width / side_width, symmetric about each axis) around the junction, trimmed, with tangent corner arcs (radius = number, or a list per corner counter-clockwise from the main road's forward arm). extent = how far the edges are drawn along each arm from the junction; draw the rest with road.offset_lines."""
    am, _ = get_alignment(ctx, main)
    asd, _ = get_alignment(ctx, side)
    m = _m(ctx)
    P = _junction_point(am, asd, main_width)
    sm, _o = am.station_of(P.x, P.y)
    ss, _o2 = asd.station_of(P.x, P.y)
    roads = {"main": (am, sm, main_width / 2), "side": (asd, ss, side_width / 2)}
    arms = []  # (road key, direction sign, angle)
    for key, (al, s, _w) in roads.items():
        h = al.point_at(s)[2]
        if al.end_station - s > 1.0:
            arms.append((key, 1, math.degrees(h) % 360))
        if s - al.start_station > 1.0:
            arms.append((key, -1, (math.degrees(h) + 180) % 360))
    if len({k for k, _, _ in arms}) < 2:
        raise CadError("Could not find arms of both roads at the junction")
    # start the corner numbering at the main road's forward arm
    ref = next((x[2] for x in arms if x[0] == "main" and x[1] == 1), arms[0][2])  # (list is empty during sort)
    arms.sort(key=lambda a: (a[2] - ref) % 360)
    corners = [(arms[i], arms[(i + 1) % len(arms)]) for i in range(len(arms))
               if arms[i][0] != arms[(i + 1) % len(arms)][0]]
    radii = radius if isinstance(radius, list) else [radius] * len(corners)
    if len(radii) != len(corners):
        raise CadError(f"This junction has {len(corners)} corners: give that many radii")
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    at = {"layer": layer}
    removed: dict[tuple[str, int], list[tuple[float, float]]] = {}
    created, info = [], []
    for (A, B), R in zip(corners, radii):
        R = float(R)
        ka, sa, _ = A
        kb, sb, _ = B
        al_a, s_a, w_a = roads[ka]
        al_b, s_b, w_b = roads[kb]
        off_a = sa * w_a          # edge of A facing B (B is counter-clockwise from A: left of A's arm)
        off_b = -sb * w_b         # edge of B facing A
        reach = extent + R * 3
        ca = _curve(al_a, sa * (w_a + R), s_a, s_a + sa * reach)
        cb = _curve(al_b, -sb * (w_b + R), s_b, s_b + sb * reach)
        hit = ca.intersection(cb)
        pts = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
        if not pts:
            raise CadError(f"Corner radius {R} does not fit between the {ka} and {kb} arms; reduce it or increase extent")
        c = min(pts, key=lambda p: Point(P.x, P.y).distance(p))
        C = Vec2(c.x, c.y)
        st_a, _ = al_a.station_of(C.x, C.y)
        st_b, _ = al_b.station_of(C.x, C.y)
        ta = Vec2(al_a.point_at(st_a, off_a)[:2])
        tb = Vec2(al_b.point_at(st_b, off_b)[:2])
        a1 = math.degrees(math.atan2(ta.y - C.y, ta.x - C.x))
        a2 = math.degrees(math.atan2(tb.y - C.y, tb.x - C.x))
        if (a2 - a1) % 360 > 180:
            a1, a2 = a2, a1
        created.append(lay.add_arc((C.x * m, C.y * m), R * m, a1, a2, dxfattribs=at))
        removed.setdefault((ka, 1 if off_a > 0 else -1), []).append(tuple(sorted((s_a, st_a))))
        removed.setdefault((kb, 1 if off_b > 0 else -1), []).append(tuple(sorted((s_b, st_b))))
        info.append({"between": [f"{ka}{'+' if sa > 0 else '-'}", f"{kb}{'+' if sb > 0 else '-'}"], "R": R,
                     "tangent_stations": {ka: round(st_a, 3), kb: round(st_b, 3)},
                     "center": [round(C.x * m, 4), round(C.y * m, 4)]})
    # pavement edges, minus the parts inside the junction
    for key, (al, s, w) in roads.items():
        key_arms = [d for k, d, _ in arms if k == key]
        lo = s - extent if -1 in key_arms else s
        hi = s + extent if 1 in key_arms else s
        lo, hi = max(lo, al.start_station), min(hi, al.end_station)
        for side_sign in (1, -1):
            cuts = sorted(removed.get((key, side_sign), []))
            keep, cur = [], lo
            for a, b in cuts:
                if a > cur:
                    keep.append((cur, a))
                cur = max(cur, b)
            if cur < hi:
                keep.append((cur, hi))
            for a, b in keep:
                if b - a < 1e-6:
                    continue
                line = _curve(al, side_sign * w, a, b, step=0.5)
                created.append(lay.add_lwpolyline([(x * m, y * m) for x, y in line.coords], dxfattribs=at))
    return {"handles": [e.dxf.handle for e in created], "type": "X" if len(corners) == 4 else "T",
            "junction_point": [round(P.x * m, 4), round(P.y * m, 4)],
            "stations": {"main": format_station(sm), "side": format_station(ss)}, "corners": info}


# ---------------------------------------------------------------------------
# drainage
# ---------------------------------------------------------------------------


def manning_trapezoid(b: float, y: float, m1: float, m2: float, slope: float, n: float) -> dict:
    area = b * y + 0.5 * y * y * (m1 + m2)
    wet = b + y * (math.sqrt(1 + m1 * m1) + math.sqrt(1 + m2 * m2))
    r = area / wet
    v = (1 / n) * r ** (2 / 3) * math.sqrt(max(slope, 0.0))
    return {"area_m2": area, "hydraulic_radius_m": r, "velocity_m_s": v, "flow_m3_s": v * area}


def manning_pipe_full(d: float, slope: float, n: float) -> dict:
    area = math.pi * d * d / 4
    r = d / 4
    v = (1 / n) * r ** (2 / 3) * math.sqrt(max(slope, 0.0))
    return {"area_m2": area, "hydraulic_radius_m": r, "velocity_m_s": v, "flow_m3_s": v * area}


@op(T, "ditch_capacity")
def ditch_capacity(ctx: Ctx, bottom_width: float, depth: float, slope_pct: float, inner_slope: float = 1.5,
                   outer_slope: float = 1.5, n: float = 0.03, water_depth: float | None = None):
    """Manning capacity of a trapezoidal ditch (árok): Q = 1/n · A · R^(2/3) · S^(1/2). water_depth defaults to the full depth; n e.g. 0.03 grassed, 0.015 concrete."""
    y = float(water_depth if water_depth is not None else depth)
    r = manning_trapezoid(float(bottom_width), y, float(inner_slope), float(outer_slope), float(slope_pct) / 100,
                          float(n))
    return {k: round(v, 4) for k, v in r.items()}


@op(T, "pipe_capacity")
def pipe_capacity(ctx: Ctx, diameter: float, slope_pct: float, n: float = 0.013):
    """Full-flow Manning capacity of a circular pipe / culvert (cső, áteresz)."""
    r = manning_pipe_full(float(diameter), float(slope_pct) / 100, float(n))
    return {k: round(v, 4) for k, v in r.items()}


def _edge(ctx: Ctx, name: str, al: Alignment, s: float, template, side: str, use_se: bool):
    """(offset, elevation) of the template edge on one side at station s (offset right = +)."""
    prof, _d = get_profile(ctx, name)
    if prof is None:
        raise CadError("Create road.profile with vpis first (ditches follow the design levels)")
    se = _se_for(ctx, name, al, s, use_se)
    sgn = 1 if side == "right" else -1
    lane = None if se is None else (se[1] if side == "right" else se[0])
    z = prof.elevation(s)
    o = 0.0
    for i, seg in enumerate(template):
        slope = lane if (_seg_type(seg, i) == "lane" and lane is not None) else float(seg["slope"])
        o += float(seg["width"])
        z += float(seg["width"]) * slope / 100
    return sgn * o, z


def _ditch_bottom(ctx, name, al, s, template, side, depth, inner_slope, bottom_width, use_se):
    o_edge, z_edge = _edge(ctx, name, al, s, template, side, use_se)
    sgn = 1 if o_edge >= 0 else -1
    o_bot = o_edge + sgn * (depth * inner_slope + bottom_width / 2)
    return o_edge, o_bot, z_edge - depth


@op(T, "ditch", mutates=True)
def ditch(ctx: Ctx, name: str, side: str = "right", depth: float = 0.6, bottom_width: float = 0.5,
          inner_slope: float = 1.5, outer_slope: float = 1.5, template: list | None = None,
          min_grade: float = 0.5, interval: float = 10.0, from_station: float | None = None,
          to_station: float | None = None, n: float = 0.03, arrows_every: float = 50.0,
          use_superelevation: bool = True, in_profile: bool = True, layer: str = "ARKOK", space=None):
    """Longitudinal roadside ditch (hosszirányú árok) on one side: bottom follows the road edge level minus depth (same template as the cross sections, incl. superelevation). Draws the ditch edges and bottom in plan with flow arrows, the bottom line in the long profile, and reports bottom levels, grades, segments flatter than min_grade (%), low points (outlets: culvert candidates), high points and Manning capacity."""
    al, _ = get_alignment(ctx, name)
    prof, _d = get_profile(ctx, name)
    if prof is None:
        raise CadError("Create road.profile with vpis first")
    tmpl = template or DEFAULT_TEMPLATE
    a = max(al.start_station, prof.vpis[0][0], from_station if from_station is not None else -1e18)
    b = min(al.end_station, prof.vpis[-1][0], to_station if to_station is not None else 1e18)
    sts = [a] + [s for s in al.stations(interval, include_ends=False) if a < s < b] + [b]
    rows = []
    for s in sts:
        o_edge, o_bot, z = _ditch_bottom(ctx, name, al, s, tmpl, side, depth, inner_slope, bottom_width,
                                         use_superelevation)
        rows.append({"station": s, "offset": o_bot, "edge_offset": o_edge, "z": z})
    grades = [(r2["z"] - r1["z"]) / (r2["station"] - r1["station"]) * 100 for r1, r2 in zip(rows, rows[1:])]
    flat = [{"from": format_station(r1["station"]), "to": format_station(r2["station"]), "grade_pct": round(g, 3)}
            for r1, r2, g in zip(rows, rows[1:], grades) if abs(g) < min_grade]
    lows, highs = [], []
    for i, r in enumerate(rows):
        g_in = grades[i - 1] if i > 0 else None
        g_out = grades[i] if i < len(grades) else None
        # water collects where the bottom falls towards a point from both sides (ends count too)
        if (g_in is None or g_in < 0) and (g_out is None or g_out > 0):
            lows.append(r)
        if (g_in is None or g_in > 0) and (g_out is None or g_out < 0):
            highs.append(r)
    # plan drawing
    m = _m(ctx)
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    at = {"layer": layer}
    sgn = 1 if side == "right" else -1
    created = []

    def line(key_off):
        pts = [al.point_at(r["station"], -key_off(r))[:2] for r in rows]
        return lay.add_lwpolyline([(x * m, y * m) for x, y in pts], dxfattribs=at)

    created.append(line(lambda r: r["edge_offset"]))  # inner top edge (= template edge)
    created.append(line(lambda r: r["offset"]))  # bottom centre line
    outer = depth * outer_slope + bottom_width / 2
    created.append(line(lambda r: r["offset"] + sgn * outer))  # outer top edge
    ensure_linetype(ctx.doc, "DASHED")
    created[1].dxf.linetype = "DASHED"
    if arrows_every:
        s = a + arrows_every / 2
        while s < b:
            j = max(0, min(len(grades) - 1, next((k for k, r in enumerate(rows) if r["station"] > s), len(rows) - 1) - 1))
            down = 1 if grades[j] < 0 else -1  # flow towards increasing station if the bottom falls
            off = rows[j]["offset"]
            p0 = Vec2(al.point_at(s, -off)[:2])
            p1 = Vec2(al.point_at(min(b, max(a, s + down * 3.0)), -off)[:2])
            created.append(lay.add_lwpolyline([(p0.x * m, p0.y * m), (p1.x * m, p1.y * m)],
                                              dxfattribs={**at, "const_width": 0}))
            head = lay.add_lwpolyline([(p1.x * m, p1.y * m, 0.6 * m, 0.0, 0.0),
                                       ((p1 + (p1 - p0).normalize() * 1.2).x * m,
                                        (p1 + (p1 - p0).normalize() * 1.2).y * m, 0, 0, 0)],
                                      format="xyseb", dxfattribs=at)
            created.append(head)
            s += arrows_every
    # long profile overlay
    view = _load(ctx, "PVIEW_" + name)
    if in_profile and view:
        ox, oy = view["insert"]
        X = lambda st: (ox + (st - view["s0"])) * m  # noqa: E731
        Y = lambda z: (oy + (z - view["datum"]) * view["v_exag"]) * m  # noqa: E731
        ensure_layer(ctx.doc, "HOSSZ_ARKOK")
        pl = ctx.layout(view.get("space")).add_lwpolyline([(X(r["station"]), Y(r["z"])) for r in rows],
                                                          dxfattribs={"layer": "HOSSZ_ARKOK", "color": 5,
                                                                      "linetype": "DASHED"})
        created.append(pl)
    worst = min((abs(g) for g in grades), default=0.0)
    cap = manning_trapezoid(bottom_width, depth, inner_slope, outer_slope, worst / 100, n)
    step = max(1, len(rows) // 60)
    return {
        "handles": [e.dxf.handle for e in created], "side": side,
        "bottom": [{"station": format_station(r["station"]), "z": round(r["z"], 3)} for r in rows[::step]],
        "grades_pct": {"min_abs": round(worst, 3), "max_abs": round(max((abs(g) for g in grades), default=0), 3)},
        "too_flat": flat[:50],
        "low_points": [{"station": format_station(r["station"]), "z": round(r["z"], 3)} for r in lows],
        "high_points": [{"station": format_station(r["station"]), "z": round(r["z"], 3)} for r in highs],
        "capacity_at_flattest": {k: round(v, 4) for k, v in cap.items()},
        "hint": "Low points need an outlet: place a culvert there (road.culvert) or a recipient.",
    }


@op(T, "culvert", mutates=True)
def culvert(ctx: Ctx, name: str, station: float, diameter: float = 0.6, length: float | None = None,
            skew: float = 0.0, invert_left: float | None = None, invert_right: float | None = None,
            depth: float = 0.6, bottom_width: float = 0.5, inner_slope: float = 1.5, template: list | None = None,
            n: float = 0.013, headwall: float = 0.4, layer: str = "ATERESZ", space=None):
    """Culvert (áteresz) across the road at a station: plan symbol (pipe walls, headwalls, label), invert levels (default: the ditch bottoms on both sides), slope and full-flow capacity. skew = angle from perpendicular in degrees."""
    al, _ = get_alignment(ctx, name)
    tmpl = template or DEFAULT_TEMPLATE
    st = float(station)
    if invert_left is None or invert_right is None:
        _oe, o_l, z_l = _ditch_bottom(ctx, name, al, st, tmpl, "left", depth, inner_slope, bottom_width, True)
        _oe, o_r, z_r = _ditch_bottom(ctx, name, al, st, tmpl, "right", depth, inner_slope, bottom_width, True)
        invert_left = z_l if invert_left is None else invert_left
        invert_right = z_r if invert_right is None else invert_right
        half = max(abs(o_l), abs(o_r)) + 1.0
    else:
        half = sum(float(s["width"]) for s in tmpl) + 3.0
    L = float(length) if length else 2 * half / math.cos(math.radians(skew))
    x, y, h = al.point_at(st)
    c = Vec2(x, y)
    d = Vec2(-math.sin(h), math.cos(h)).rotate_deg(-skew)  # axis direction (towards the left side)
    nrm = Vec2(-d.y, d.x)
    m = _m(ctx)
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    at = {"layer": layer}
    created = []
    for sgn in (1, -1):
        p0 = c - d * (L / 2) + nrm * (sgn * diameter / 2)
        p1 = c + d * (L / 2) + nrm * (sgn * diameter / 2)
        created.append(lay.add_line((p0.x * m, p0.y * m), (p1.x * m, p1.y * m), dxfattribs=at))
    for end in (-1, 1):
        e = c + d * (end * L / 2)
        a = e + nrm * (diameter / 2 + headwall)
        b = e - nrm * (diameter / 2 + headwall)
        created.append(lay.add_line((a.x * m, a.y * m), (b.x * m, b.y * m), dxfattribs={**at, "lineweight": 50}))
    slope = (invert_left - invert_right) / L
    cap = manning_pipe_full(diameter, abs(slope), n)
    flow_to = "jobb" if slope > 0 else "bal"
    label = (f"Áteresz D{diameter * 100:.0f} L={L:.1f} m  fenék B {invert_left:.2f} / J {invert_right:.2f}  "
             f"esés {abs(slope) * 100:.2f}% → {flow_to}")
    from ezdxf.enums import TextEntityAlignment

    tp = c + nrm * (diameter / 2 + 1.0)
    ang = math.degrees(math.atan2(d.y, d.x))
    if 90 < ang % 360 < 270:
        ang += 180
    created.append(lay.add_text(label, height=0.8 * m, rotation=ang, dxfattribs=at).set_placement(
        (tp.x * m, tp.y * m), align=TextEntityAlignment.BOTTOM_CENTER))
    return {"handles": [e.dxf.handle for e in created], "station": format_station(st), "length_m": round(L, 3),
            "invert_left": round(invert_left, 3), "invert_right": round(invert_right, 3),
            "slope_pct": round(abs(slope) * 100, 3), "flows_to": flow_to,
            "capacity_full": {k: round(v, 4) for k, v in cap.items()}}


@op(T, "runoff")
def runoff(ctx: Ctx, area_m2: float, runoff_coefficient: float, intensity_l_s_ha: float,
           capacity_m3_s: float | None = None):
    """Design runoff by the rational method (racionális módszer): Q = C · i · A. area in m², C e.g. 0.9 asphalt / 0.3 grass, rain intensity i in l/(s·ha) for the chosen return period and duration. With capacity_m3_s (from road.ditch or road.culvert) also reports the utilisation."""
    q = float(runoff_coefficient) * float(intensity_l_s_ha) * float(area_m2) / 10000 / 1000
    out = {"flow_m3_s": round(q, 5), "flow_l_s": round(q * 1000, 2)}
    if capacity_m3_s:
        out["utilisation_pct"] = round(q / float(capacity_m3_s) * 100, 1)
        out["ok"] = q <= float(capacity_m3_s)
    return out
