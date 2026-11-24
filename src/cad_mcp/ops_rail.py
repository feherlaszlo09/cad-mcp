"""Tool `rail` (vasút, KÉ-VA basics): track alignments reuse the road alignment (clothoids,
stationing, long section). This adds cant (túlemelés, mm) per curve with equilibrium cant,
cant deficiency/excess and ramp length, the track in plan (rails and sleepers), turnouts
(kitérő) from radius and crossing ratio (e.g. '54-190-1:9'), and the ballasted track cross
section. Limits (maximum cant, deficiency, excess, ramp gradient) and the track dimensions of
the applicable MÁV regulation are given by the designer; the defaults of the drawing
dimensions are only examples."""

from __future__ import annotations

import math
import re

from .core import CadError, Ctx, ensure_layer, handles, op

T = "rail"
G = 9.81


def _m(ctx: Ctx) -> float:
    from .ops_road import _m as road_m

    return road_m(ctx)


def _al(name: str):
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment[name]


def equilibrium_cant_mm(v_kmh: float, radius: float, rail_distance_mm: float = 1500.0) -> float:
    """c = s·v²/(g·R): the cant at which the resultant is perpendicular to the track."""
    return rail_distance_mm * (v_kmh / 3.6) ** 2 / (G * radius)


@op(T, "cant")
def cant(ctx: Ctx, alignment: str | None = None, radii: list | None = None, v_max: float | None = None,
         v_min: float | None = None, cant_mm: list | None = None, design_speed: float | None = None,
         max_cant_mm: float | None = None, max_deficiency_mm: float | None = None,
         max_excess_mm: float | None = None, ramp_ratio: float | None = None, rail_distance_mm: float = 1500.0,
         round_to_mm: float = 5.0):
    """Cant (vasúti túlemelés) per curve of an alignment (or radii=[...]): equilibrium cant c₀ = s·v²/(g·R) for v_max (and v_min), applied cant (cant_mm per curve, or proposed from design_speed rounded up to round_to_mm and capped at max_cant_mm), cant deficiency I = c₀(v_max) − c, excess E = c − c₀(v_min), uncompensated lateral acceleration a = g·I/s, and the minimum cant ramp length c·ramp_ratio/1000 (ramp 1:ramp_ratio). Checks against the limits given by the designer. s = distance of the rail head centres (1500 mm for standard gauge)."""
    if alignment:
        from .ops_road import get_alignment

        al, _ = get_alignment(ctx, alignment)
        rs = [c.radius for c in al.curves]
        spirals = [c.spiral_length for c in al.curves]
    elif radii:
        rs = [float(r) for r in radii]
        spirals = [None] * len(rs)
    else:
        raise CadError("Give alignment or radii")
    if v_max is None:
        raise CadError("Give v_max (km/h)")
    rows, fails = [], []
    for i, R in enumerate(rs):
        c_max = equilibrium_cant_mm(float(v_max), R, rail_distance_mm)
        c_min = equilibrium_cant_mm(float(v_min), R, rail_distance_mm) if v_min is not None else None
        if cant_mm is not None:
            c = float(cant_mm[i])
        elif design_speed is not None:
            c = math.ceil(equilibrium_cant_mm(float(design_speed), R, rail_distance_mm) / round_to_mm) * round_to_mm
            if max_cant_mm is not None:
                c = min(c, float(max_cant_mm))
        else:
            c = 0.0
        I = c_max - c
        row = {"curve": i + 1, "R": R, "equilibrium_cant_vmax_mm": round(c_max, 1), "cant_mm": c,
               "deficiency_mm": round(I, 1), "lateral_acc_m_s2": round(G * I / rail_distance_mm, 3)}
        if c_min is not None:
            row.update({"equilibrium_cant_vmin_mm": round(c_min, 1), "excess_mm": round(c - c_min, 1)})
        if ramp_ratio is not None:
            row["min_ramp_length_m"] = round(c * float(ramp_ratio) / 1000, 2)
            if spirals[i]:
                row["transition_length_m"] = round(spirals[i], 2)
        checks = []
        if max_cant_mm is not None and c > float(max_cant_mm):
            checks.append(f"túlemelés > {max_cant_mm} mm")
        if max_deficiency_mm is not None and I > float(max_deficiency_mm):
            checks.append(f"hiány > {max_deficiency_mm} mm")
        if max_excess_mm is not None and c_min is not None and c - c_min > float(max_excess_mm):
            checks.append(f"többlet > {max_excess_mm} mm")
        if ramp_ratio is not None and spirals[i] and spirals[i] < row["min_ramp_length_m"] - 1e-9:
            checks.append("átmeneti ív rövidebb a kifuttatáshoz szükségesnél")
        row["status"] = "OK" if not checks else "HIBA: " + ", ".join(checks)
        if checks:
            fails.append(i + 1)
        rows.append(row)
    return {"v_max": v_max, "v_min": v_min, "curves": rows, "failures": fails}


@op(T, "track", mutates=True)
def track(ctx: Ctx, alignment: str, gauge_mm: float = 1435.0, rail_head_mm: float = 72.0,
          sleeper_spacing: float | None = 0.6, sleeper_length: float = 2.6, sleeper_width: float = 0.3,
          from_station: float | None = None, to_station: float | None = None, layer: str = "VASUT_SIN"):
    """Track in plan along an alignment: the two rails at ± (gauge + head width)/2 from the axis and the sleepers (talpfa / alj) every sleeper_spacing (None: no sleepers). Dimensions are example defaults; use the values of the actual superstructure."""
    from .ops_road import get_alignment

    al, _ = get_alignment(ctx, alignment)
    m = _m(ctx)
    s0 = al.start_station if from_station is None else float(from_station)
    s1 = al.end_station if to_station is None else float(to_station)
    half = (float(gauge_mm) + float(rail_head_mm)) / 2000
    ensure_layer(ctx.doc, layer)
    ensure_layer(ctx.doc, "VASUT_ALJ")
    n = max(2, int((s1 - s0) / 0.5) + 1)
    ss = [s0 + (s1 - s0) * k / (n - 1) for k in range(n)]
    out = []
    for o in (half, -half):
        out.append(ctx.msp.add_lwpolyline([(x * m, y * m) for x, y, _h in (al.point_at(s, o) for s in ss)],
                                          dxfattribs={"layer": layer}))
    count = 0
    if sleeper_spacing:
        s = s0 + float(sleeper_spacing) / 2
        while s < s1:
            x, y, h = al.point_at(s, 0.0)
            ux, uy = math.cos(h), math.sin(h)
            nx, ny = -uy, ux
            a, b = float(sleeper_width) / 2, float(sleeper_length) / 2
            pts = [(x - ux * a - nx * b, y - uy * a - ny * b), (x + ux * a - nx * b, y + uy * a - ny * b),
                   (x + ux * a + nx * b, y + uy * a + ny * b), (x - ux * a + nx * b, y - uy * a + ny * b)]
            out.append(ctx.msp.add_lwpolyline([(px * m, py * m) for px, py in pts], close=True,
                                              dxfattribs={"layer": "VASUT_ALJ", "color": 8}))
            count += 1
            s += float(sleeper_spacing)
    return {"rails": 2, "sleepers": count, "rail_offset_m": round(half, 4), "handles": handles(out)[:50]}


def _parse_turnout(spec: str) -> tuple[float | None, float, float]:
    m = re.fullmatch(r"\s*(?:(\d+)\s*[-–]\s*)?(\d+(?:[.,]\d+)?)\s*[-–]\s*1\s*:\s*(\d+(?:[.,]\d+)?)\s*", spec)
    if not m:
        raise CadError("turnout like '54-190-1:9' (rail system - radius - crossing ratio)")
    return (int(m.group(1)) if m.group(1) else None, float(m.group(2).replace(",", ".")),
            float(m.group(3).replace(",", ".")))


@op(T, "turnout", mutates=True)
def turnout(ctx: Ctx, start, direction_deg: float, hand: str = "right", turnout: str | None = None,
            radius: float | None = None, ratio: float | None = None, a: float | None = None, b: float | None = None,
            gauge_mm: float = 1435.0, rails: bool = True, label: bool = True, text_height: float = 0.5,
            layer: str = "VASUT_KITERO"):
    """Turnout (kitérő) in plan from the switch start point (váltókezdet), direction of the straight track (degrees, counter-clockwise from +X) and hand ('left'/'right'): diverging curve of radius R tangent to the straight track up to the crossing angle α = atan(1:n), then straight. turnout = '54-190-1:9' or radius + ratio. The theoretical centre (elméleti középpont) lies at T = R·tan(α/2); a (switch start → centre) and b (centre → turnout end) come from the turnout table of the type, otherwise the drawing uses a = T, b = 2·T. Draws both track axes (and rails), marks the switch start, centre and ends."""
    sys_ = None
    if turnout:
        sys_, radius, ratio = _parse_turnout(turnout)
    if radius is None or ratio is None:
        raise CadError("Give turnout='54-190-1:9' or radius and ratio")
    R, n = float(radius), float(ratio)
    alpha = math.atan(1.0 / n)
    Tn = R * math.tan(alpha / 2)
    aa = float(a) if a is not None else Tn
    bb = float(b) if b is not None else 2 * Tn
    if aa < Tn - 1e-9 or bb < Tn - 1e-9:
        raise CadError(f"a and b must be at least the tangent length T = {Tn:.3f} m")
    th = math.radians(float(direction_deg))
    sgn = -1.0 if hand == "right" else 1.0
    x0, y0 = float(start[0]), float(start[1])
    ux, uy = math.cos(th), math.sin(th)
    nx, ny = -uy * sgn, ux * sgn  # towards the diverging side
    # straight track: from the start to the centre plus b
    S = (x0, y0)
    M = (x0 + ux * aa, y0 + uy * aa)
    E1 = (M[0] + ux * bb, M[1] + uy * bb)
    # diverging axis: arc (centre of curvature on the diverging side) up to alpha, then straight
    cxy = (x0 + (aa - Tn) * ux + nx * R, y0 + (aa - Tn) * uy + ny * R)
    arc_start = (x0 + (aa - Tn) * ux, y0 + (aa - Tn) * uy)
    pts_div = [S, arc_start] if aa - Tn > 1e-9 else [S]
    k = 24
    for i in range(1, k + 1):
        phi = alpha * i / k
        # point on the circle, measured from the tangent point
        px = arc_start[0] + ux * R * math.sin(phi) + nx * R * (1 - math.cos(phi))
        py = arc_start[1] + uy * R * math.sin(phi) + ny * R * (1 - math.cos(phi))
        pts_div.append((px, py))
    dx, dy = ux * math.cos(alpha) + nx * math.sin(alpha), uy * math.cos(alpha) + ny * math.sin(alpha)
    # straight diverging leg up to b from the theoretical centre
    E2 = (M[0] + dx * bb, M[1] + dy * bb)
    pts_div.append(E2)
    m = _m(ctx)
    ensure_layer(ctx.doc, layer)
    out = [ctx.msp.add_lwpolyline([(S[0] * m, S[1] * m), (E1[0] * m, E1[1] * m)], dxfattribs={"layer": layer}),
           ctx.msp.add_lwpolyline([(p[0] * m, p[1] * m) for p in pts_div], dxfattribs={"layer": layer})]
    if rails:
        from shapely.geometry import LineString

        half = float(gauge_mm) / 2000
        for line in (LineString([S, E1]), LineString(pts_div)):
            for side in ("left", "right"):
                off = line.offset_curve(half if side == "left" else -half)
                out.append(ctx.msp.add_lwpolyline([(x * m, y * m) for x, y in off.coords],
                                                  dxfattribs={"layer": layer + "_SIN", "color": 8}))
    if label:
        for name, p in (("VK", S), ("M", M), ("VV1", E1), ("VV2", E2)):
            out.append(ctx.msp.add_circle((p[0] * m, p[1] * m), 0.3 * m, dxfattribs={"layer": layer}))
            t = ctx.msp.add_text(name, height=text_height * m, dxfattribs={"layer": layer})
            t.set_placement((p[0] * m + 0.4 * m, p[1] * m + 0.4 * m))
            out.append(t)
    return {"rail_system": sys_, "radius": R, "ratio": f"1:{n:g}", "crossing_angle_deg": round(math.degrees(alpha), 6),
            "tangent_T": round(Tn, 4), "a": round(aa, 4), "b": round(bb, 4),
            "points": {"switch_start": [round(c, 4) for c in S], "centre": [round(c, 4) for c in M],
                       "end_straight": [round(c, 4) for c in E1], "end_diverging": [round(c, 4) for c in E2]},
            "circle_centre": [round(c, 4) for c in cxy], "handles": handles(out),
            "note": None if a is not None and b is not None else "a és b a kitérő típustáblázatából adandó meg; a rajz a = T, b = 2T értékkel készült."}


@op(T, "cross_section", mutates=True)
def rail_cross_section(ctx: Ctx, insert, top_of_rail: float = 0.0, cant_mm: float = 0.0, gauge_mm: float = 1435.0,
                       rail_height: float = 0.172, sleeper_length: float = 2.6, sleeper_height: float = 0.22,
                       ballast_depth: float = 0.30, ballast_shoulder: float = 0.40, ballast_slope: float = 1.5,
                       formation_width: float | None = None, formation_slope_pct: float = 5.0,
                       scale: float = 1.0, text_height: float = 0.1, layer: str = "VASUT_KERESZT"):
    """Ballasted track cross section (vasúti keresztszelvény) at insert (track axis, top of rail level): rails, sleeper, ballast bed with shoulder and slope, formation (alépítmény korona) with crossfall, and cant (cant_mm raises the outer rail, the superstructure rotates about the inner rail). All dimensions are example defaults – give the values of the actual superstructure and regulation."""
    m = _m(ctx)
    ox, oy = float(insert[0]) / m, float(insert[1]) / m
    s = (float(gauge_mm) + 72) / 2000  # rail centre offset
    rot = math.atan2(float(cant_mm) / 1000, 2 * s)
    pivot = (-s, 0.0)

    def P(x, z):
        # rotate about the inner (left) rail for cant, then place
        dx, dz = x - pivot[0], z - pivot[1]
        xr = pivot[0] + dx * math.cos(rot) - dz * math.sin(rot)
        zr = pivot[1] + dx * math.sin(rot) + dz * math.cos(rot)
        return ((ox + xr * scale) * m, (oy + zr * scale) * m)

    def Pf(x, z):  # formation: no cant
        return ((ox + x * scale) * m, (oy + z * scale) * m)

    ensure_layer(ctx.doc, layer)
    out = []
    rh = float(rail_height)
    for xc in (-s, s):
        out.append(ctx.msp.add_lwpolyline([P(xc - 0.075, -rh), P(xc + 0.075, -rh), P(xc + 0.036, -rh + 0.03),
                                           P(xc + 0.008, -rh + 0.03), P(xc + 0.008, -0.04), P(xc + 0.036, -0.04),
                                           P(xc + 0.036, 0), P(xc - 0.036, 0), P(xc - 0.036, -0.04), P(xc - 0.008, -0.04),
                                           P(xc - 0.008, -rh + 0.03), P(xc - 0.036, -rh + 0.03)], close=True,
                                          dxfattribs={"layer": layer, "color": 1}))
    sl, shh = float(sleeper_length) / 2, float(sleeper_height)
    z_top_sl = -rh
    out.append(ctx.msp.add_lwpolyline([P(-sl, z_top_sl), P(sl, z_top_sl), P(sl, z_top_sl - shh), P(-sl, z_top_sl - shh)],
                                      close=True, dxfattribs={"layer": layer, "color": 8}))
    z_bal = z_top_sl - shh - float(ballast_depth)  # bottom of ballast under the sleeper
    sh = sl + float(ballast_shoulder)
    bottom_half = sh + (z_top_sl - z_bal) * float(ballast_slope)
    bal = [P(-sh, z_top_sl), P(sh, z_top_sl), P(bottom_half, z_bal), P(-bottom_half, z_bal)]
    out.append(ctx.msp.add_lwpolyline(bal, close=True, dxfattribs={"layer": layer, "color": 33}))
    fw = float(formation_width) / 2 if formation_width else bottom_half + 0.5
    zb = z_bal - 0.0
    fs = float(formation_slope_pct) / 100
    out.append(ctx.msp.add_lwpolyline([Pf(-fw, zb - fw * fs), Pf(0, zb), Pf(fw, zb - fw * fs)],
                                      dxfattribs={"layer": layer, "color": 30}))
    out.append(ctx.msp.add_line(Pf(0, zb - 0.5), Pf(0, 0.5), dxfattribs={"layer": layer, "linetype": "CENTER"}
                                if ctx.doc.linetypes.has_entry("CENTER") else {"layer": layer}))
    t = ctx.msp.add_text(f"SK {float(top_of_rail):.3f}" + (f"  túlemelés {cant_mm:g} mm" if cant_mm else ""),
                         height=text_height * m * scale, dxfattribs={"layer": layer})
    t.set_placement(Pf(0, 0.6), align=_al("BOTTOM_CENTER"))
    out.append(t)
    ballast_area = (2 * sh + 2 * bottom_half) / 2 * (z_top_sl - z_bal)  # trapezoid incl. the sleeper
    return {"ballast_area_m2": round(ballast_area, 4), "ballast_bottom_width": round(2 * bottom_half, 3),
            "cant_rotation_deg": round(math.degrees(rot), 4), "handles": handles(out),
            "note": "A méretek példaértékek; a felépítmény és a MÁV-utasítás szerinti értékekkel add meg."}
