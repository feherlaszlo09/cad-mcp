"""Tool `survey` (geodézia): named survey points, bearing/distance (2nd basic task), polar
detail points with orientation (poláris pontszámítás, tájékozás), traverses (sokszögvonal) with
angular and linear misclosure distribution, intersections (előmetszés, ívmetszés,
hátrametszés by least squares), levelling lines (szintezési vonal), Helmert/affine
transformation with residuals, import of the Hungarian DAT land registry exchange format
(DAT-M1 G Függelék: T_PONT, T_HATARVONAL, T_HATAR, T_FELULET, T_OBJ_ATTRxx), land take per
parcel (kisajátítás) and as-built versus design comparison (megvalósulási ellenőrzés).

Coordinates are EOV-style [Y, X(, H)] in metres = drawing [x, y(, z)]; bearings (irányszög)
are clockwise from north (+X); angles in decimal degrees or 'DDD-MM-SS' strings."""

from __future__ import annotations

import csv
import io
import math
import re

import numpy as np

from .core import CadError, Ctx, ensure_layer, handles, op, select_from

T = "survey"
LAYER_PTS = "GEODEZIA_SZAMITOTT"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def parse_angle(v, unit: str = "deg") -> float:
    """Degrees from a number (decimal degrees, or gon with unit='gon') or a DMS string like '123-45-12.5', '123 45 12.5' or 123°45'12.5"."""
    if isinstance(v, (int, float)):
        return float(v) * (0.9 if unit == "gon" else 1.0)
    s = str(v).strip().replace(",", ".")
    if not s:
        raise CadError("Empty angle")
    low = s.lower()
    if unit == "gon" or low.endswith("gon") or low.endswith("g"):
        return float(re.sub(r"[^0-9.+-]", "", s)) * 0.9
    sign = -1.0 if s.startswith("-") else 1.0
    parts = [p for p in re.split(r"[^0-9.]+", s) if p]
    if not parts:
        raise CadError(f"Bad angle {v!r}")
    nums = [float(p) for p in parts]
    return sign * (nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0))


def fmt_dms(deg: float, decimals: int = 1, signed: bool = False) -> str:
    sign = "-" if signed and deg < 0 else ""
    a = abs(deg) if signed else deg % 360
    total = round(a * 3600, decimals)
    d = int(total // 3600)
    m = int((total - d * 3600) // 60)
    sec = total - d * 3600 - m * 60
    return f"{sign}{d}-{m:02d}-{sec:0{3 + decimals if decimals else 2}.{decimals}f}"


def wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def bearing(a, b) -> float:
    """Irányszög a -> b in degrees (clockwise from north), points as (Y, X)."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0


def _m(ctx: Ctx) -> float:
    from .ops_road import _m as road_m

    return road_m(ctx)


def _registry(ctx: Ctx) -> dict:
    from .ops_road import _load

    return _load(ctx, "SURVEY_POINTS") or {}


def _save_registry(ctx: Ctx, reg: dict) -> None:
    from .ops_road import _store

    _store(ctx, "SURVEY_POINTS", reg)


def _pt(ctx: Ctx, p, reg: dict | None = None) -> tuple[float, float, float | None, str | None]:
    """(Y, X, H, name) of a point name from the registry or [Y, X(, H)]."""
    if isinstance(p, str):
        reg = reg if reg is not None else _registry(ctx)
        if p not in reg:
            raise CadError(f"Unknown point '{p}'. Known: {sorted(reg)[:30]} (survey.points action=add)")
        y, x, h = reg[p][:3]
        return float(y), float(x), (None if h is None else float(h)), p
    if isinstance(p, dict):
        name = p.get("name")
        return float(p["y"]), float(p["x"]), (None if p.get("h") is None else float(p["h"])), name
    c = list(p)
    if len(c) < 2:
        raise CadError(f"Point needs [Y, X] or a name, got {p!r}")
    return float(c[0]), float(c[1]), (float(c[2]) if len(c) > 2 and c[2] is not None else None), None


def _draw_points(ctx: Ctx, pts: list[dict], layer: str, text_height: float, color: int | None = None) -> list[str]:
    m = _m(ctx)
    ensure_layer(ctx.doc, layer)
    if color is not None:
        ctx.doc.layers.get(layer).color = color
    msp = ctx.msp
    out = []
    th = text_height * m
    for p in pts:
        z = (p.get("h") or 0.0) * m
        out.append(msp.add_point((p["y"] * m, p["x"] * m, z), dxfattribs={"layer": layer}))
        label = str(p.get("name") or "")
        if p.get("h") is not None:
            label = f"{label}  {p['h']:.3f}" if label else f"{p['h']:.3f}"
        if label:
            t = msp.add_text(label, height=th, dxfattribs={"layer": layer})
            t.set_placement((p["y"] * m + th * 0.4, p["x"] * m + th * 0.2))
            out.append(t)
    return handles(out)


def _store_points(ctx: Ctx, pts: list[dict], code: str) -> None:
    reg = _registry(ctx)
    for p in pts:
        if p.get("name"):
            reg[str(p["name"])] = [p["y"], p["x"], p.get("h"), code]
    _save_registry(ctx, reg)


def _r(v, n=4):
    return None if v is None else round(float(v), n)


# ---------------------------------------------------------------------------
# point registry, inverse task
# ---------------------------------------------------------------------------


@op(T, "points", mutates=True)
def points(ctx: Ctx, action: str = "list", points: list | dict | None = None, path: str | None = None,
           text: str | None = None, order: str = "name,y,x,h", delimiter: str | None = None, names: list | None = None,
           code: str = "adott", draw: bool = True, layer: str = "GEODEZIA_ADOTT", text_height: float = 0.5):
    """Named survey points kept in the drawing (alappontok, számított pontok): action list | add | delete | import. add: points=[{"name":"1001","y":650000.12,"x":240000.34,"h":120.5}, ...] or {"1001":[Y,X,H], ...}; import: CSV/TXT path or text with order like "name,y,x,h" (EOV: Y east, X north). Other survey ops can refer to these points by name."""
    reg = _registry(ctx)
    if action == "list":
        sel = {k: v for k, v in reg.items() if not names or k in names}
        return {"count": len(sel), "points": [{"name": k, "y": v[0], "x": v[1], "h": v[2], "code": v[3] if len(v) > 3 else None}
                                              for k, v in sorted(sel.items())]}
    if action == "delete":
        gone = [n for n in (names or []) if reg.pop(n, None) is not None]
        _save_registry(ctx, reg)
        return {"deleted": gone}
    new: list[dict] = []
    if action == "add":
        if isinstance(points, dict):
            items = [{"name": k, "y": v[0], "x": v[1], "h": v[2] if len(v) > 2 else None} for k, v in points.items()]
        else:
            items = [p if isinstance(p, dict) else {"name": p[0], "y": p[1], "x": p[2], "h": p[3] if len(p) > 3 else None}
                     for p in (points or [])]
        for p in items:
            new.append({"name": str(p["name"]), "y": float(p["y"]), "x": float(p["x"]),
                        "h": None if p.get("h") is None else float(p["h"])})
    elif action == "import":
        raw = ctx.resolve(path).read_text(encoding="utf-8-sig", errors="replace") if path else text
        if not raw:
            raise CadError("Give path or text")
        cols = [c.strip().lower() for c in order.split(",")]
        if delimiter is None:
            sample = raw[:2000]
            delimiter = ";" if sample.count(";") > sample.count(",") else ("," if "," in sample else None)
        rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter)) if delimiter else [ln.split() for ln in raw.splitlines()]
        for r in rows:
            rec = dict(zip(cols, [c.strip() for c in r]))
            try:
                new.append({"name": rec.get("name") or rec.get("id"), "y": float(rec["y"].replace(",", ".")),
                            "x": float(rec["x"].replace(",", ".")),
                            "h": float(rec["h"].replace(",", ".")) if rec.get("h") not in (None, "") else None})
            except (KeyError, ValueError, AttributeError):
                continue
        if not new:
            raise CadError("No point rows recognised; check order and delimiter")
    else:
        raise CadError("action: list, add, delete, import")
    _store_points(ctx, new, code)
    out = {"added": len(new), "total": len(_registry(ctx))}
    if draw:
        out["handles"] = _draw_points(ctx, new, layer, text_height)[:100]
    return out


@op(T, "inverse")
def inverse(ctx: Ctx, a, b):
    """Second basic task (második alapfeladat): bearing (irányszög, from north clockwise) and distance from a to b, plus the height difference when both have heights."""
    A, B = _pt(ctx, a), _pt(ctx, b)
    dy, dx = B[0] - A[0], B[1] - A[1]
    d = math.hypot(dy, dx)
    out = {"bearing_deg": round(bearing(A, B), 8), "bearing_dms": fmt_dms(bearing(A, B)), "distance": round(d, 4),
           "dY": round(dy, 4), "dX": round(dx, 4)}
    if A[2] is not None and B[2] is not None:
        out["dH"] = round(B[2] - A[2], 4)
        if d > 0:
            out["grade_pct"] = round((B[2] - A[2]) / d * 100, 4)
    return out


# ---------------------------------------------------------------------------
# polar detail points with orientation
# ---------------------------------------------------------------------------


def _orientation(S, refs: list[tuple[tuple, float]]):
    """Mean orientation angle z (tájékozási szög) and residuals from (known point, observed direction)."""
    zs, dists = [], []
    for P, ldir in refs:
        zs.append((bearing(S, P) - ldir) % 360.0)
        dists.append(math.hypot(P[0] - S[0], P[1] - S[1]))
    z0 = zs[0]
    z = (z0 + sum(wrap180(zi - z0) for zi in zs) / len(zs)) % 360.0
    res = []
    for zi, d in zip(zs, dists):
        v = wrap180(z - zi)
        res.append({"residual_sec": round(v * 3600, 1), "linear_mm": round(math.radians(v) * d * 1000, 1),
                    "distance": round(d, 3)})
    return z, res


@op(T, "polar", mutates=True)
def polar(ctx: Ctx, station, observations: list, orientation: list | None = None, orientation_angle=None,
          station_height: float | None = None, instrument_height: float = 0.0, distance_type: str = "horizontal",
          scale_factor: float = 1.0, angle_unit: str = "deg", add: bool = True, draw: bool = True,
          layer: str = LAYER_PTS, text_height: float = 0.5):
    """Polar detail points (poláris részletpont-számítás): station (name or [Y,X,H]); orientation = [{"point": known name or [Y,X], "direction": observed direction}, ...] gives the mean orientation angle with residuals (tájékozás), or give orientation_angle (z) directly. observations = [{"name","direction","distance", optional "zenith", "target_height"}]; distance_type 'horizontal' or 'slope' (needs zenith). Heights by trigonometric heighting when the station height and zenith angles are known. scale_factor reduces distances (e.g. EOV scale). New points go into the point list and the drawing."""
    S = _pt(ctx, station)
    hs = station_height if station_height is not None else S[2]
    res_or = []
    if orientation:
        refs = [(_pt(ctx, o["point"]), parse_angle(o["direction"], angle_unit)) for o in orientation]
        z, res_or = _orientation(S, refs)
    elif orientation_angle is not None:
        z = parse_angle(orientation_angle, angle_unit)
    else:
        z = 0.0  # directions are bearings
    out_pts = []
    for i, ob in enumerate(observations):
        ldir = parse_angle(ob["direction"], angle_unit)
        dist = float(ob["distance"])
        zen = parse_angle(ob["zenith"], angle_unit) if ob.get("zenith") is not None else None
        if distance_type == "slope":
            if zen is None:
                raise CadError(f"Observation {i}: slope distance needs a zenith angle")
            dh_geom = dist * math.cos(math.radians(zen))
            d_h = dist * math.sin(math.radians(zen))
        else:
            d_h = dist
            dh_geom = dist / math.tan(math.radians(zen)) if zen not in (None, 0.0) else None
        d_h *= float(scale_factor)
        brg = (z + ldir) % 360.0
        y = S[0] + d_h * math.sin(math.radians(brg))
        x = S[1] + d_h * math.cos(math.radians(brg))
        h = None
        if hs is not None and dh_geom is not None:
            h = hs + float(instrument_height) + dh_geom - float(ob.get("target_height", 0.0))
        out_pts.append({"name": str(ob.get("name", f"P{i + 1}")), "y": y, "x": x, "h": h,
                        "bearing_dms": fmt_dms(brg), "horizontal_distance": d_h})
    if add:
        _store_points(ctx, out_pts, "poláris")
    result = {"orientation_angle_deg": round(z, 8), "orientation_angle_dms": fmt_dms(z), "orientation_residuals": res_or,
              "points": [{"name": p["name"], "y": _r(p["y"]), "x": _r(p["x"]), "h": _r(p["h"]),
                          "bearing_dms": p["bearing_dms"], "horizontal_distance": _r(p["horizontal_distance"])} for p in out_pts]}
    if draw:
        result["handles"] = _draw_points(ctx, out_pts, layer, text_height)
    return result


# ---------------------------------------------------------------------------
# traverse
# ---------------------------------------------------------------------------


@op(T, "traverse", mutates=True)
def traverse(ctx: Ctx, start, angles: list, distances: list, names: list | None = None, start_ref=None,
             start_bearing=None, end=None, end_ref=None, end_bearing=None, angle_side: str = "left",
             angle_unit: str = "deg", max_angle_misclosure_sec: float | None = None,
             max_linear_misclosure: float | None = None, add: bool = True, draw: bool = True,
             layer: str = "GEODEZIA_SOKSZOGVONAL", text_height: float = 0.5):
    """Traverse (sokszögvonal) from start to end: angles = traverse angles (törésszögek) at the start, every new point and (for end orientation) the end, measured clockwise from the back sight to the fore sight (angle_side 'left' = bal oldali törésszög; 'right' angles are converted); distances = horizontal leg lengths; names = new point names. Start orientation from start_ref (known back-sight point) or start_bearing; end = known end point (closed loop: end = start, end_ref = start_ref); end orientation from end_ref or end_bearing. Distributes the angular misclosure equally and the coordinate misclosure in proportion to the leg lengths (Bowditch); reports f_β, f_Y, f_X, f_l, 1:N and checks the given limits. Without end it is an open (unchecked) traverse."""
    A = _pt(ctx, start)
    if start_bearing is not None:
        d0 = parse_angle(start_bearing, angle_unit)
    elif start_ref is not None:
        d0 = bearing(A, _pt(ctx, start_ref))
    else:
        raise CadError("Give start_ref (known back-sight point) or start_bearing")
    legs = len(distances)
    if legs < 1:
        raise CadError("Give at least one distance")
    B = _pt(ctx, end) if end is not None else None
    if end_bearing is not None:
        d_end = parse_angle(end_bearing, angle_unit)
    elif end_ref is not None:
        if B is None:
            raise CadError("end_ref needs end")
        d_end = bearing(B, _pt(ctx, end_ref))
    else:
        d_end = None
    need = legs + (1 if d_end is not None else 0)
    if len(angles) != need:
        raise CadError(f"Need {need} angles ({legs} legs{' + closing angle at the end' if d_end is not None else ''}), got {len(angles)}")
    beta = [parse_angle(a, angle_unit) for a in angles]
    if angle_side == "right":
        beta = [360.0 - b for b in beta]
    n_new = legs - 1 if B is not None else legs
    names = [str(n) for n in (names or [f"S{i + 1}" for i in range(n_new)])]
    if len(names) != n_new:
        raise CadError(f"Give {n_new} names for the new points")
    # angular closure
    f_beta = None
    corr = 0.0
    if d_end is not None:
        # computed end bearing: at the start back bearing + angle, then (previous bearing + 180°) + angle
        d = d0
        for k, b in enumerate(beta):
            d = (d + b) % 360.0 if k == 0 else (d + 180.0 + b) % 360.0
        f_beta = wrap180(d - d_end)
        corr = -f_beta / len(beta)
    brgs = []
    d = d0
    for k in range(legs):
        b = beta[k] + corr
        d = (d + b) % 360.0 if k == 0 else (d + 180.0 + b) % 360.0
        brgs.append(d)
    dists = [float(x) for x in distances]
    dY = [s * math.sin(math.radians(b)) for s, b in zip(dists, brgs)]
    dX = [s * math.cos(math.radians(b)) for s, b in zip(dists, brgs)]
    total = sum(dists)
    fY = fX = None
    if B is not None:
        fY = A[0] + sum(dY) - B[0]
        fX = A[1] + sum(dX) - B[1]
        dY = [v - fY * s / total for v, s in zip(dY, dists)]
        dX = [v - fX * s / total for v, s in zip(dX, dists)]
    pts, y, x = [], A[0], A[1]
    for k in range(n_new):
        y += dY[k]
        x += dX[k]
        pts.append({"name": names[k], "y": y, "x": x, "h": None})
    out = {"legs": legs, "total_length": round(total, 3),
           "bearings": [fmt_dms(b) for b in brgs],
           "points": [{"name": p["name"], "y": _r(p["y"]), "x": _r(p["x"])} for p in pts]}
    checks = []
    if f_beta is not None:
        out.update({"angular_misclosure_sec": round(f_beta * 3600, 1), "angle_correction_sec": round(corr * 3600, 2)})
        if max_angle_misclosure_sec is not None:
            checks.append({"check": "szögzáróhiba", "value_sec": round(abs(f_beta) * 3600, 1),
                           "limit_sec": max_angle_misclosure_sec, "ok": abs(f_beta) * 3600 <= max_angle_misclosure_sec})
    if fY is not None:
        fl = math.hypot(fY, fX)
        out.update({"fY": round(fY, 4), "fX": round(fX, 4), "linear_misclosure": round(fl, 4),
                    "relative": f"1:{int(total / fl)}" if fl > 1e-9 else "1:∞"})
        if max_linear_misclosure is not None:
            checks.append({"check": "vonalas záróhiba", "value": round(fl, 4), "limit": max_linear_misclosure,
                           "ok": fl <= max_linear_misclosure})
    else:
        out["warning"] = "Szabad (ellenőrzés nélküli) sokszögvonal: nincs záróhiba."
    if checks:
        out["checks"] = checks
    if add:
        _store_points(ctx, pts, "sokszögpont")
    if draw:
        m = _m(ctx)
        ensure_layer(ctx.doc, layer)
        chain = [(A[0], A[1])] + [(p["y"], p["x"]) for p in pts] + ([(B[0], B[1])] if B is not None else [])
        pl = ctx.msp.add_lwpolyline([(yy * m, xx * m) for yy, xx in chain], dxfattribs={"layer": layer})
        out["handles"] = [pl.dxf.handle] + _draw_points(ctx, pts, layer, text_height)
    return out


# ---------------------------------------------------------------------------
# intersections
# ---------------------------------------------------------------------------


def _ray_cross(A, da, B, db):
    ua = (math.sin(math.radians(da)), math.cos(math.radians(da)))
    ub = (math.sin(math.radians(db)), math.cos(math.radians(db)))
    det = ua[0] * (-ub[1]) - ua[1] * (-ub[0])
    if abs(det) < 1e-12:
        raise CadError("The two directions are parallel")
    rx, ry = B[0] - A[0], B[1] - A[1]
    t = (rx * (-ub[1]) - ry * (-ub[0])) / det
    return A[0] + t * ua[0], A[1] + t * ua[1]


def _resection(known: list[tuple], dirs: list[float]):
    """Least-squares resection: returns (Y, X, z, residuals_sec, rms_sec)."""
    P = np.array([[k[0], k[1]] for k in known])
    L = np.radians(np.array(dirs))
    spread = float(np.max(np.linalg.norm(P - P.mean(axis=0), axis=1))) or 1.0
    starts = [P.mean(axis=0)] + [P.mean(axis=0) + spread * f * np.array([math.sin(a), math.cos(a)])
                                  for f in (0.5, 2.0) for a in np.radians(np.arange(0, 360, 45))]
    best = None
    for s0 in starts:
        y, x = float(s0[0]), float(s0[1])
        ok = False
        for _ in range(60):
            dy, dx = P[:, 0] - y, P[:, 1] - x
            r2 = dy ** 2 + dx ** 2
            if np.any(r2 < 1e-12):
                break
            brg = np.arctan2(dy, dx)
            z = math.atan2(np.mean(np.sin(brg - L)), np.mean(np.cos(brg - L)))
            v = np.angle(np.exp(1j * (brg - z - L)))  # computed - observed
            J = np.column_stack([-dx / r2, dy / r2, -np.ones(len(P))])  # d(brg)/dY, d(brg)/dX, d/dz
            step, *_ = np.linalg.lstsq(J, -v, rcond=None)
            y += step[0]
            x += step[1]
            if abs(step[0]) + abs(step[1]) < 1e-9:
                ok = True
                break
        if not ok:
            continue
        dy, dx = P[:, 0] - y, P[:, 1] - x
        brg = np.arctan2(dy, dx)
        z = math.atan2(np.mean(np.sin(brg - L)), np.mean(np.cos(brg - L)))
        v = np.degrees(np.angle(np.exp(1j * (z + L - brg)))) * 3600
        rss = float(np.sum(v ** 2))
        if best is None or rss < best[4] - 1e-9:
            best = (y, x, math.degrees(z) % 360.0, v, rss)
    if best is None:
        raise CadError("Resection did not converge (check the directions and point order)")
    y, x, z, v, rss = best
    dof = len(known) - 3
    rms = math.sqrt(rss / dof) if dof > 0 else 0.0
    return y, x, z, [round(float(t), 1) for t in v], rms


@op(T, "intersection", mutates=True)
def intersection(ctx: Ctx, kind: str, a=None, b=None, name: str = "P", bearing_a=None, bearing_b=None,
                 angle_a=None, angle_b=None, distance_a: float | None = None, distance_b: float | None = None,
                 side: str = "left", known: list | None = None, directions: list | None = None,
                 angle_unit: str = "deg", add: bool = True, draw: bool = True, layer: str = LAYER_PTS,
                 text_height: float = 0.5):
    """Intersections: kind='forward' (előmetszés) from known a and b with bearings bearing_a/bearing_b to the new point, or with the triangle angles angle_a/angle_b and side ('left'/'right' of a→b); kind='arc' (ívmetszés) with distances distance_a/distance_b and side; kind='resection' (hátrametszés) with known=[3+ known points] and directions=[observed directions] at the new station, solved by least squares with residuals (and a danger-circle warning)."""
    out: dict = {"kind": kind}
    if kind == "forward":
        A, B = _pt(ctx, a), _pt(ctx, b)
        if bearing_a is not None and bearing_b is not None:
            da, db = parse_angle(bearing_a, angle_unit), parse_angle(bearing_b, angle_unit)
        elif angle_a is not None and angle_b is not None:
            dab, dba = bearing(A, B), bearing(B, A)
            al, be = parse_angle(angle_a, angle_unit), parse_angle(angle_b, angle_unit)
            da, db = ((dab - al, dba + be) if side == "left" else (dab + al, dba - be))
        else:
            raise CadError("Give bearing_a and bearing_b, or angle_a, angle_b and side")
        y, x = _ray_cross(A, da, B, db)
        cut = abs(wrap180(da - db))
        out["intersection_angle_deg"] = round(min(cut, 180 - cut), 4)
        if out["intersection_angle_deg"] < 30:
            out["warning"] = "Kis metszési szög (< 30°): a pont meghatározása gyenge."
    elif kind == "arc":
        A, B = _pt(ctx, a), _pt(ctx, b)
        c = math.hypot(B[0] - A[0], B[1] - A[1])
        ra, rb = float(distance_a), float(distance_b)
        if c > ra + rb or c < abs(ra - rb):
            raise CadError("The two arcs do not intersect")
        along = (ra ** 2 - rb ** 2 + c ** 2) / (2 * c)
        h = math.sqrt(max(ra ** 2 - along ** 2, 0.0))
        uy, ux = (B[0] - A[0]) / c, (B[1] - A[1]) / c
        # left of a→b in a north-clockwise system: rotate the direction by -90°
        ny, nx = (-ux, uy) if side == "left" else (ux, -uy)
        y, x = A[0] + along * uy + h * ny, A[1] + along * ux + h * nx
    elif kind == "resection":
        if not known or not directions or len(known) != len(directions) or len(known) < 3:
            raise CadError("Give known=[3+ points] and the same number of directions")
        K = [_pt(ctx, k) for k in known]
        y, x, z, v, rms = _resection(K, [parse_angle(d, angle_unit) for d in directions])
        out.update({"orientation_angle_dms": fmt_dms(z), "residuals_sec": v, "rms_sec": round(rms, 2)})
        (y1, x1), (y2, x2), (y3, x3) = [(k[0], k[1]) for k in K[:3]]
        dd = 2 * (y1 * (x2 - x3) + y2 * (x3 - x1) + y3 * (x1 - x2))
        if abs(dd) > 1e-9:
            uy_ = ((y1 ** 2 + x1 ** 2) * (x2 - x3) + (y2 ** 2 + x2 ** 2) * (x3 - x1) + (y3 ** 2 + x3 ** 2) * (x1 - x2)) / dd
            ux_ = ((y1 ** 2 + x1 ** 2) * (y3 - y2) + (y2 ** 2 + x2 ** 2) * (y1 - y3) + (y3 ** 2 + x3 ** 2) * (y2 - y1)) / dd
            rad = math.hypot(y1 - uy_, x1 - ux_)
            if abs(math.hypot(y - uy_, x - ux_) - rad) < 0.05 * rad:
                out["warning"] = "Az álláspont közel van a veszélyes körhöz (az első három pont körülírt köre): a megoldás bizonytalan."
    else:
        raise CadError("kind: forward, arc, resection")
    y, x = float(y), float(x)
    p = {"name": name, "y": y, "x": x, "h": None}
    out["point"] = {"name": name, "y": round(y, 4), "x": round(x, 4)}
    if add:
        _store_points(ctx, [p], kind)
    if draw:
        out["handles"] = _draw_points(ctx, [p], layer, text_height)
    return out


# ---------------------------------------------------------------------------
# levelling
# ---------------------------------------------------------------------------


@op(T, "levelling", mutates=True)
def levelling(ctx: Ctx, start_height: float, setups: list, end_height: float | None = None,
              max_misclosure_mm: float | None = None, add: bool = False, draw: bool = False,
              layer: str = LAYER_PTS):
    """Levelling line (szintezési vonal): setups = [{"back": hátra leolvasás, "fore": előre leolvasás, "point": name of the fore point, optional "distance" (m, for weighting), optional "side": [{"point": name, "reading": r}] intermediate points (oldalpontok)}], readings in metres. With end_height the misclosure is distributed in proportion to distance (or equally per setup) and checked against max_misclosure_mm. Heights of turning and intermediate points are returned (and optionally given to points already in the point list)."""
    if not setups:
        raise CadError("Give setups")
    use_dist = all(s.get("distance") is not None for s in setups)
    w = [float(s["distance"]) if use_dist else 1.0 for s in setups]
    total_w = sum(w)
    raw = float(start_height)
    for s in setups:
        raw += float(s["back"]) - float(s["fore"])
    f = (raw - float(end_height)) if end_height is not None else None
    h = float(start_height)
    acc = 0.0
    rows, side_rows = [], []
    for i, s in enumerate(setups):
        corr_before = -f * acc / total_w if f is not None else 0.0
        hi = h + float(s["back"])  # instrument horizon (műszerhorizont)
        acc += w[i]
        corr_after = -f * acc / total_w if f is not None else 0.0
        for sp in s.get("side") or []:
            hp = hi - float(sp["reading"]) + (corr_before + corr_after) / 2
            side_rows.append({"point": sp["point"], "h": round(hp, 4)})
        h = h + float(s["back"]) - float(s["fore"])
        rows.append({"point": s.get("point", f"F{i + 1}"), "h": round(h + corr_after, 4),
                     "correction_mm": round(corr_after * 1000, 2)})
    out = {"setups": len(setups), "points": rows, "side_points": side_rows,
           "sum_back_minus_fore": round(raw - float(start_height), 4)}
    if f is not None:
        out["misclosure_mm"] = round(f * 1000, 2)
        if max_misclosure_mm is not None:
            out["check"] = {"limit_mm": max_misclosure_mm, "ok": abs(f * 1000) <= max_misclosure_mm}
    if add:
        reg = _registry(ctx)
        for r in rows + side_rows:
            if r["point"] in reg:
                reg[r["point"]][2] = r["h"]
        _save_registry(ctx, reg)
    if draw:
        reg = _registry(ctx)
        pts = [{"name": r["point"], "y": reg[r["point"]][0], "x": reg[r["point"]][1], "h": r["h"]}
               for r in rows + side_rows if r["point"] in reg]
        out["handles"] = _draw_points(ctx, pts, layer, 0.5)
    return out


# ---------------------------------------------------------------------------
# coordinate transformation
# ---------------------------------------------------------------------------


@op(T, "transform", mutates=True)
def transform(ctx: Ctx, common: list, kind: str = "helmert", points: list | None = None, sel=None):
    """Plane coordinate transformation from common points (közös pontok): common = [{"source": [x, y], "target": [Y, X], optional "name"}]; kind 'helmert' (4 parameters: shift, rotation, scale; 2+ points) or 'affine' (6 parameters; 3+ points), least squares with residuals per point and the mean error. points = [[x, y], ...] to transform; sel = drawing entities to transform in place (drawing units)."""
    if kind not in ("helmert", "affine"):
        raise CadError("kind: helmert or affine")
    src = np.array([[float(c["source"][0]), float(c["source"][1])] for c in common])
    dst = np.array([[float(c["target"][0]), float(c["target"][1])] for c in common])
    n = len(src)
    need = 2 if kind == "helmert" else 3
    if n < need:
        raise CadError(f"{kind} needs at least {need} common points")
    if kind == "helmert":
        A = np.zeros((2 * n, 4))
        A[0::2] = np.column_stack([np.ones(n), np.zeros(n), src[:, 0], -src[:, 1]])
        A[1::2] = np.column_stack([np.zeros(n), np.ones(n), src[:, 1], src[:, 0]])
        sol, *_ = np.linalg.lstsq(A, dst.reshape(-1), rcond=None)
        a, b, c, d = sol
        M = np.array([[c, -d], [d, c]])
        t = np.array([a, b])
        params = {"shift_Y": round(float(a), 4), "shift_X": round(float(b), 4), "scale": round(float(math.hypot(c, d)), 9),
                  "rotation_deg": round(math.degrees(math.atan2(d, c)), 8)}
        u = 4
    else:
        A = np.column_stack([np.ones(n), src[:, 0], src[:, 1]])
        sy, *_ = np.linalg.lstsq(A, dst[:, 0], rcond=None)
        sx, *_ = np.linalg.lstsq(A, dst[:, 1], rcond=None)
        M = np.array([[sy[1], sy[2]], [sx[1], sx[2]]])
        t = np.array([sy[0], sx[0]])
        params = {"a": [round(float(v), 9) for v in sy], "b": [round(float(v), 9) for v in sx]}
        u = 6
    fit = src @ M.T + t
    resid = dst - fit
    dof = 2 * n - u
    m0 = math.sqrt(float(np.sum(resid ** 2)) / dof) if dof > 0 else 0.0
    out = {"kind": kind, "parameters": params, "mean_error": round(m0, 4),
           "residuals": [{"name": c.get("name", str(i + 1)), "vY": round(float(r[0]), 4), "vX": round(float(r[1]), 4),
                          "v": round(float(math.hypot(*r)), 4)} for i, (c, r) in enumerate(zip(common, resid))]}
    if points:
        P = np.array([[float(p[0]), float(p[1])] for p in points])
        out["points"] = [[round(float(q[0]), 4), round(float(q[1]), 4)] for q in P @ M.T + t]
    if sel is not None:
        from ezdxf.math import Matrix44

        mat = Matrix44([M[0, 0], M[1, 0], 0, 0, M[0, 1], M[1, 1], 0, 0, 0, 0, 1, 0, t[0], t[1], 0, 1])
        done, failed = 0, []
        for e in select_from(ctx, sel):
            try:
                e.transform(mat)
                done += 1
            except Exception as exc:  # non-uniform scaling of circles etc.
                failed.append(f"{e.dxf.handle} {e.dxftype()}: {type(exc).__name__}")
        out["transformed"] = done
        if failed:
            out["not_transformed"] = failed
    return out


# ---------------------------------------------------------------------------
# DAT import (DAT-M1, G Függelék)
# ---------------------------------------------------------------------------

DAT_FIELDS = {
    "T_PONT": ["pont_id", "pont_x", "pont_y", "pont_H", "kozephiba_oszt_V", "kozephiba_oszt_M"],
    "T_OSSZEKOT_IV": ["osszekot_id", "center_x", "center_y", "sugar"],
    "T_VONAL": ["vonal_id", "vsub_id", "pont_id_1", "pont_id_2", "osszekot_mod", "osszekot_id"],
    "T_HATARVONAL": ["hatarvonal_id", "hvsub_id", "pont_id_1", "pont_id_2", "osszekot_mod", "osszekot_id"],
    "T_HATAR": ["hatar_id", "hsub_id", "hatarvonal_id", "irany_valt"],
    "T_FELULET": ["felulet_id", "subfel_id", "hatar_id", "hatar_valt"],
    "T_FELIRAT": ["felirat_id", "felirat_text", "pont_id_text", "irany_text", "font_id", "megsz_datum", "tabla_nev",
                  "sor_id", "jelleg_kod"],
    "T_OBJ_ATTRAA": ["alappont_id", "obj_fels", "pont_szam", "pont_id"],
    "T_OBJ_ATTRAB": ["malapp_id", "obj_fels", "mpont_szam", "pont_id"],
    "T_OBJ_ATTRAC": ["rpont_id", "obj_fels", "pont_szam", "pont_id"],
    "T_OBJ_ATTRBA": ["kozig_idba", "obj_fels", "felulet_id"],
    "T_OBJ_ATTRBB": ["kozigal_id", "obj_fels", "felulet_id", "kozigal_nev"],
    "T_OBJ_ATTRBC": ["parcel_id", "obj_fels", "felulet_id", "helyr_szam", "cim_id", "fekves", "kozter_jell", "terulet",
                     "foldert", "forg_ertek", "val_nem", "szerv_tip", "jogi_jelleg", "jogallas", "ceg_id", "elhat_jell",
                     "elhat_mod", "elozo_parcel_id", "l_datum", "hatarozat", "valt_jell", "tar_hely", "blokk_id",
                     "megsz_datum", "jelkulcs", "munkater_id", "pont_id"],
    "T_OBJ_ATTRBD": ["parcel_id", "obj_fels", "felulet_id", "helyr_szam", "cim_id", "fekves", "terulet", "foldert",
                     "forg_ertek", "val_nem", "szerv_tip", "jogi_jelleg", "jogallas", "szemely_id", "ceg_id",
                     "elhat_jell", "elhat_mod", "elozo_parcel_id", "l_datum", "hatarozat", "valt_jell", "tar_hely",
                     "blokk_id", "megsz_datum", "jelkulcs", "munkater_id", "pont_id"],
    "T_OBJ_ATTRBE": ["alreszlet_id", "obj_fels", "felulet_id", "alator", "helyr_szam", "terulet", "foldert", "muvel_ag",
                     "elhat_jell", "elhat_mod", "elozo_alreszlet_id", "l_datum", "hatarozat", "valt_jell", "tar_cim",
                     "megsz_datum", "jelkulcs", "munkater_id", "pont_id"],
    "T_OBJ_ATTRBG": ["eoi_id", "obj_fels", "felulet_id", "alator_eoi", "helyr_szam"],
    "T_OBJ_ATTRCA": ["ep_id", "obj_fels", "felulet_id", "cim_id", "parcel_id1", "parcel_id2", "ep_sorsz", "szintek",
                     "fugg_kiter", "anyag", "epulet_tip", "epulet_alt", "szemely_id", "ceg_id", "elozo_ep_id", "blokk_id",
                     "megsz_datum"],
    "T_OBJ_ATTREA": ["tavvez_id", "obj_fels", "vonal_id"],
}
# tables whose geometry is given by obj_kiterj (1 point, 2 line, 3 surface) + geo_ae_id
for _t in ("BH", "BI", "CB", "CC", "CD", "CE", "DD", "DF", "DG", "EB", "FB", "FC", "GA", "GB"):
    DAT_FIELDS.setdefault(f"T_OBJ_ATTR{_t}", ["obj_id", "obj_fels", "obj_kiterj", "geo_ae_id"])
DAT_FIELDS["T_OBJ_ATTRBH"] = ["obj_fels", "obj_kiterj", "geo_ae_id"]
# felulet_id at position 2 for the other surface tables
for _t in ("DB", "DC", "DE", "FA", "HA", "HB", "HC"):
    DAT_FIELDS.setdefault(f"T_OBJ_ATTR{_t}", ["obj_id", "obj_fels", "felulet_id"])
DAT_LAYERS = {"BA": "DAT_KOZIGAZGATAS", "BB": "DAT_KOZIG_ALEGYSEG", "BC": "DAT_FOLDRESZLET_KOZTER",
              "BD": "DAT_FOLDRESZLET", "BE": "DAT_ALRESZLET", "BF": "DAT_MINOSEGI_OSZTALY", "BG": "DAT_EOI",
              "BH": "DAT_SZOLGALMI", "CA": "DAT_EPULET", "CB": "DAT_EPULET_TARTOZEK", "CC": "DAT_KERITES",
              "CD": "DAT_TEREPTARGY", "CE": "DAT_SZOBOR", "DB": "DAT_KOZLEKEDES_BEL", "DC": "DAT_KOZLEKEDES_KUL",
              "DD": "DAT_VASUT", "DE": "DAT_REPTER", "DF": "DAT_MUTARGY", "DG": "DAT_MUTARGY_EGYEB",
              "EA": "DAT_TAVVEZETEK", "EB": "DAT_VEZETEK_MUTARGY", "FA": "DAT_VIZ", "FB": "DAT_VIZ_KOZMU",
              "FC": "DAT_VIZ_MUTARGY", "GA": "DAT_SZINTVONAL", "GB": "DAT_DOMBORZAT", "HA": "DAT_MUNKATERULET",
              "HB": "DAT_NYILVANTARTASI", "HC": "DAT_TERSEG", "AA": "DAT_ALAPPONT", "AB": "DAT_MAGASSAGI_ALAPPONT",
              "AC": "DAT_RESZLETPONT"}
DAT_COLORS = {"BD": 7, "BC": 7, "BE": 3, "CA": 1, "BA": 6, "BB": 6, "CC": 8, "DB": 8, "DC": 8, "FA": 5}


def parse_dat(raw: str) -> dict[str, list[list[str]]]:
    tables: dict[str, list[list[str]]] = {}
    cur = None
    for line in raw.replace("\x1a", "").splitlines():
        line = line.strip("\r\n")
        if not line.strip():
            continue
        fields = line.split("*")
        if fields and fields[-1] == "":
            fields = fields[:-1]
        if len(fields) == 1 and re.fullmatch(r"T_[A-Z0-9_ ]+", fields[0].strip()):
            cur = fields[0].strip().replace(" ", "")
            tables.setdefault(cur, [])
            continue
        if cur is None:
            cur = "T_CIMREK"
            tables.setdefault(cur, [])
        tables[cur].append([f.strip() for f in fields])
    return tables


def _rec(table: str, row: list[str]) -> dict:
    return dict(zip(DAT_FIELDS.get(table, []), row))


def _valid(rec: dict) -> bool:
    md = (rec.get("megsz_datum") or "").strip()
    return md in ("", "0", "00000000")


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


@op(T, "import_dat", mutates=True)
def import_dat(ctx: Ctx, path: str, encoding: str | None = None, tables: list | None = None, labels: bool = True,
               text_height: float = 1.5, points: bool = False):
    """Import a Hungarian DAT land registry map (adatcsere .dat, DAT-M1 G Függelék): parcels (földrészletek, T_OBJ_ATTRBC/BD) as closed polylines with helyrajzi szám labels, sub-parcels, buildings, administrative units, roads, waters, fences and other objects on DAT_* layers, survey control points and texts (T_FELIRAT). Arcs (T_OSSZEKOT_IV) become polyline arcs; records with an end-of-validity date are skipped. EOV: drawing x = Y (east), y = X (north). Parcels are remembered for survey.land_take. tables = e.g. ['BD','BC','CA'] to limit; points=True also draws every T_PONT."""
    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    data = p.read_bytes()
    text = None
    for enc in ([encoding] if encoding else ["utf-8", "cp1250", "cp852", "iso8859_2"]):
        try:
            text = data.decode(enc)
            used = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise CadError("Cannot decode the file; give encoding (e.g. cp1250 or cp852)")
    T_ = parse_dat(text)
    m = _m(ctx)
    pts = {}
    for row in T_.get("T_PONT", []):
        r = _rec("T_PONT", row)
        x, y = _num(r.get("pont_x")), _num(r.get("pont_y"))
        if x is not None and y is not None:
            pts[r["pont_id"]] = (y, x, _num(r.get("pont_H")))  # (Y east, X north, H)
    arcs = {}
    for row in T_.get("T_OSSZEKOT_IV", []):
        r = _rec("T_OSSZEKOT_IV", row)
        arcs[r["osszekot_id"]] = (_num(r["center_y"]), _num(r["center_x"]), _num(r["sugar"]))

    def chains(table: str, id_key: str, sub_key: str) -> dict:
        out: dict = {}
        for row in T_.get(table, []):
            r = _rec(table, row)
            out.setdefault(r[id_key], []).append(r)
        for k in out:
            out[k].sort(key=lambda r: int(_num(r[sub_key]) or 0))
        return out

    hvonal = chains("T_HATARVONAL", "hatarvonal_id", "hvsub_id")
    vonal = chains("T_VONAL", "vonal_id", "vsub_id")
    hatar = chains("T_HATAR", "hatar_id", "hsub_id")
    felulet = chains("T_FELULET", "felulet_id", "subfel_id")

    def seg_bulge(a, b, r) -> float:
        if str(r.get("osszekot_mod", "0")).strip() not in ("1",) or r.get("osszekot_id") not in arcs:
            return 0.0
        cy, cx, rad = arcs[r["osszekot_id"]]
        a1 = math.atan2(a[1] - cx, a[0] - cy)
        a2 = math.atan2(b[1] - cx, b[0] - cy)
        sweep = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi  # the shorter arc (drawing: x=Y, y=X, CCW +)
        return math.tan(sweep / 4)

    def line_vertices(recs: list[dict]) -> list[tuple]:
        """[(Y, X, bulge)] of a chain of point pairs."""
        verts = []
        for i, r in enumerate(recs):
            a, b = pts.get(r["pont_id_1"]), pts.get(r["pont_id_2"])
            if a is None or b is None:
                return []
            if i == 0:
                verts.append([a[0], a[1], 0.0])
            verts[-1][2] = seg_bulge(a, b, r)
            verts.append([b[0], b[1], 0.0])
        return verts

    def reverse(v):
        n = len(v)
        return [[v[n - 1 - i][0], v[n - 1 - i][1], -v[n - 2 - i][2] if i < n - 1 else 0.0] for i in range(n)]

    def ring(hatar_id: str) -> list:
        out: list = []
        for r in hatar.get(hatar_id, []):
            v = line_vertices(hvonal.get(r["hatarvonal_id"], []))
            if not v:
                return []
            if r.get("irany_valt", "+").strip() == "-":
                v = reverse(v)
            # the chain's end vertex (bulge 0) is the next line's first vertex, which carries its first bulge
            out = out[:-1] + v if out and math.dist(out[-1][:2], v[0][:2]) < 1e-6 else out + v
        if len(out) > 1 and math.dist(out[0][:2], out[-1][:2]) < 1e-6:
            out = out[:-1]
        return out

    def surface_rings(fid: str) -> list[tuple[list, bool]]:
        return [(ring(r["hatar_id"]), r.get("hatar_valt", "+").strip() != "-") for r in felulet.get(fid, [])]

    msp = ctx.msp
    th = text_height * m
    stats: dict = {}
    parcels = {}
    created = 0

    def add_poly(verts, layer, closed=True):
        nonlocal created
        pl = msp.add_lwpolyline([(v[0] * m, v[1] * m, v[2]) for v in verts], format="xyb", close=closed,
                                dxfattribs={"layer": layer})
        created += 1
        return pl

    def label(txt, at, layer):
        nonlocal created
        if txt:
            t = msp.add_text(str(txt), height=th, dxfattribs={"layer": layer})
            t.set_placement((at[0] * m, at[1] * m), align=_mid())
            created += 1

    want = {t.upper() for t in tables} if tables else None
    for tname, rows in T_.items():
        if not tname.startswith("T_OBJ_ATTR"):
            continue
        code = tname[-2:]
        if want and code not in want:
            continue
        fields = DAT_FIELDS.get(tname)
        if not fields:
            stats.setdefault("ismeretlen_tabla", []).append(tname)
            continue
        layer = DAT_LAYERS.get(code, f"DAT_{code}")
        ensure_layer(ctx.doc, layer)
        if code in DAT_COLORS:
            ctx.doc.layers.get(layer).color = DAT_COLORS[code]
        n = 0
        for row in rows:
            r = _rec(tname, row)
            if not _valid(r):
                continue
            geo_kind, gid = None, None
            if "felulet_id" in r:
                geo_kind, gid = 3, r["felulet_id"]
            elif "obj_kiterj" in r:
                geo_kind, gid = int(_num(r.get("obj_kiterj")) or 0), r.get("geo_ae_id")
            elif "vonal_id" in r:
                geo_kind, gid = 2, r["vonal_id"]
            elif "pont_id" in r:
                geo_kind, gid = 1, r["pont_id"]
            txt = r.get("helyr_szam") or r.get("pont_szam") or r.get("mpont_szam") or r.get("kozigal_nev")
            if code == "BE" and r.get("alator"):
                txt = r["alator"]
            if geo_kind == 3:
                rings = surface_rings(gid)
                outer = [v for v, is_outer in rings if is_outer and len(v) >= 3]
                if not outer:
                    continue
                main = add_poly(outer[0], layer)
                holes = []
                for v, is_outer in rings[1:] if len(rings) > 1 else []:
                    if len(v) >= 3:
                        holes.append(add_poly(v, layer).dxf.handle)
                n += 1
                if code in ("BC", "BD", "BG"):
                    parcels[main.dxf.handle] = {"hrsz": r.get("helyr_szam"), "table": code, "obj_fels": r.get("obj_fels"),
                                                "registered_area_m2": _num(r.get("terulet")), "holes": holes}
                if labels and txt:
                    gp = pts.get(r.get("pont_id"))
                    if gp is None:
                        from shapely.geometry import Polygon

                        rp = Polygon([(v[0], v[1]) for v in outer[0]]).representative_point()
                        gp = (rp.x, rp.y)
                    label(txt, gp, layer + "_FELIRAT")
            elif geo_kind == 2:
                v = line_vertices(vonal.get(gid, []))
                if len(v) >= 2:
                    add_poly(v, layer, closed=False)
                    n += 1
            elif geo_kind == 1:
                pp = pts.get(gid)
                if pp is None:
                    continue
                msp.add_point((pp[0] * m, pp[1] * m, (pp[2] or 0.0) * m), dxfattribs={"layer": layer})
                created += 1
                n += 1
                if labels and txt:
                    label(txt, (pp[0] + text_height, pp[1] + text_height), layer + "_FELIRAT")
        stats[code] = n
    # texts
    if labels and (not want or "FELIRAT" in want):
        ensure_layer(ctx.doc, "DAT_FELIRAT")
        k = 0
        for row in T_.get("T_FELIRAT", []):
            r = _rec("T_FELIRAT", row)
            if not _valid(r) or r.get("pont_id_text") not in pts:
                continue
            pp = pts[r["pont_id_text"]]
            ang = 90.0 - (_num(r.get("irany_text")) or 90.0)  # DAT: direction from north
            t = msp.add_text(r.get("felirat_text", ""), height=th, rotation=ang, dxfattribs={"layer": "DAT_FELIRAT"})
            t.set_placement((pp[0] * m, pp[1] * m))
            k += 1
        stats["FELIRAT"] = k
        created += k
    if points:
        ensure_layer(ctx.doc, "DAT_PONT")
        for pp in pts.values():
            msp.add_point((pp[0] * m, pp[1] * m, (pp[2] or 0.0) * m), dxfattribs={"layer": "DAT_PONT"})
        created += len(pts)
    if parcels:
        from .ops_road import _load, _store

        reg = _load(ctx, "DAT_PARCELS") or {}
        reg.update(parcels)
        _store(ctx, "DAT_PARCELS", reg)
    return {"encoding": used, "tables": {k: len(v) for k, v in T_.items()}, "drawn_by_object_table": stats,
            "points": len(pts), "parcels": len(parcels), "entities": created}


def _mid():
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment.MIDDLE_CENTER


# ---------------------------------------------------------------------------
# land take (kisajátítás)
# ---------------------------------------------------------------------------


def _poly_of(e, m: float):
    """Shapely polygon (metres) of a closed LWPOLYLINE/POLYLINE/CIRCLE (arcs flattened finely)."""
    from ezdxf import path as ezpath
    from shapely.geometry import Polygon

    p = ezpath.make_path(e)
    v = [(q.x / m, q.y / m) for q in p.flattening(0.005 * m)]
    if len(v) < 3:
        return None
    poly = Polygon(v)
    return poly if poly.is_valid else poly.buffer(0)


@op(T, "land_take", mutates=True)
def land_take(ctx: Ctx, boundary=None, alignment: str | None = None, left: float | None = None,
              right: float | None = None, widths: list | None = None, from_station: float | None = None,
              to_station: float | None = None, parcels=None, labels=None, path: str | None = None,
              table_at=None, layer: str = "KISAJATITAS", text_height: float = 1.5, min_area_m2: float = 0.5):
    """Land take per parcel (kisajátítási terület): the area to acquire = a closed boundary polyline (boundary = selection), or the strip along an alignment between from/to stations with left/right widths (or widths=[[station, left, right], ...] interpolated). Parcels = DAT parcels from survey.import_dat (default) or a selection of closed polylines, with helyrajzi szám from DAT or from the texts (labels selection) inside each parcel. Returns per parcel the original, taken and remaining area (m², rounded like the land registry), the share, and the new boundary points where the land-take line crosses the parcel boundary; hatches and labels the taken parts, optional CSV (path) and table in the drawing (table_at)."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    m = _m(ctx)
    if boundary is not None:
        polys = [q for q in (_poly_of(e, m) for e in select_from(ctx, boundary)) if q is not None]
        if not polys:
            raise CadError("boundary: give closed polylines")
        take = unary_union(polys)
    elif alignment:
        from .ops_road import get_alignment

        al, _ = get_alignment(ctx, alignment)
        s0 = al.start_station if from_station is None else float(from_station)
        s1 = al.end_station if to_station is None else float(to_station)
        if widths:
            W = sorted([float(w[0]), float(w[1]), float(w[2])] for w in widths)

            def wl(s):
                return float(np.interp(s, [w[0] for w in W], [w[1] for w in W])), float(np.interp(s, [w[0] for w in W], [w[2] for w in W]))
        elif left is not None and right is not None:
            def wl(s):
                return float(left), float(right)
        else:
            raise CadError("Give left and right widths (or widths=[[station, left, right], ...])")
        ss = list(np.arange(s0, s1, 1.0)) + [s1]
        lpts = [al.point_at(s, wl(s)[0])[:2] for s in ss]
        rpts = [al.point_at(s, -wl(s)[1])[:2] for s in ss]
        take = Polygon(lpts + rpts[::-1]).buffer(0)
    else:
        raise CadError("Give boundary (closed polyline selection) or alignment with widths")
    from .ops_road import _load

    reg = _load(ctx, "DAT_PARCELS") or {}
    items = []
    if parcels is not None:
        ents = select_from(ctx, parcels)
        texts = select_from(ctx, labels) if labels is not None else []
        for e in ents:
            poly = _poly_of(e, m)
            if poly is None:
                continue
            hrsz = None
            meta = reg.get(e.dxf.handle)
            if meta:
                hrsz = meta.get("hrsz")
            for t in texts:
                if t.dxftype() in ("TEXT", "MTEXT"):
                    ins = t.dxf.insert
                    if poly.contains(Point(ins.x / m, ins.y / m)):
                        hrsz = t.plain_text() if t.dxftype() == "MTEXT" else t.dxf.text
                        break
            items.append((e.dxf.handle, hrsz, poly, meta))
    else:
        if not reg:
            raise CadError("No parcels: import a DAT file (survey.import_dat) or give parcels (closed polylines) and labels")
        for h, meta in reg.items():
            e = ctx.doc.entitydb.get(h)
            if e is None or not e.is_alive:
                continue
            poly = _poly_of(e, m)
            for hh in meta.get("holes", []):
                he = ctx.doc.entitydb.get(hh)
                if he is not None and he.is_alive:
                    hp = _poly_of(he, m)
                    if hp is not None:
                        poly = poly.difference(hp)
            items.append((h, meta.get("hrsz"), poly, meta))
    ensure_layer(ctx.doc, layer)
    ctx.doc.layers.get(layer).color = 1
    msp = ctx.msp
    th = text_height * m
    rows, created = [], []
    take_edge = take.boundary
    for h, hrsz, poly, meta in items:
        if poly is None or not poly.intersects(take):
            continue
        part = poly.intersection(take)
        if part.area < min_area_m2:
            continue
        rest = poly.difference(take)
        new_pts = []
        for g in getattr(take_edge.intersection(poly.boundary), "geoms", [take_edge.intersection(poly.boundary)]):
            if g.geom_type == "Point":
                new_pts.append([round(g.x, 3), round(g.y, 3)])
        row = {"hrsz": hrsz or f"?({h})", "parcel_area_m2": round(poly.area),
               "registered_area_m2": (meta or {}).get("registered_area_m2"),
               "taken_m2": round(part.area), "remaining_m2": round(rest.area),
               "share_pct": round(part.area / poly.area * 100, 2) if poly.area else None,
               "remaining_pieces": len(getattr(rest, "geoms", [rest])) if not rest.is_empty else 0,
               "new_boundary_points": new_pts}
        rows.append(row)
        for g in getattr(part, "geoms", [part]):
            if g.geom_type != "Polygon":
                continue
            ha = msp.add_hatch(color=1, dxfattribs={"layer": layer})
            ha.paths.add_polyline_path([(x * m, y * m) for x, y in g.exterior.coords[:-1]], is_closed=True, flags=1)
            for hole in g.interiors:
                ha.paths.add_polyline_path([(x * m, y * m) for x, y in hole.coords[:-1]], is_closed=True)
            ha.set_pattern_fill("ANSI31", scale=0.5 * m)
            created.append(ha)
            ol = msp.add_lwpolyline([(x * m, y * m) for x, y in g.exterior.coords[:-1]], close=True,
                                    dxfattribs={"layer": layer})
            created.append(ol)
        rp = part.representative_point()
        t = msp.add_text(f"{row['hrsz']}: {row['taken_m2']} m²", height=th, dxfattribs={"layer": layer})
        t.set_placement((rp.x * m, rp.y * m), align=_mid())
        created.append(t)
    rows.sort(key=lambda r: str(r["hrsz"]))
    out = {"parcels_affected": len(rows), "total_taken_m2": sum(r["taken_m2"] for r in rows),
           "land_take_area_m2": round(take.area), "rows": rows, "handles": handles(created)}
    if path:
        fp = ctx.resolve(path)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["hrsz", "foldreszlet_terulet_m2", "nyilvantartott_m2", "kisajatitando_m2", "maradek_m2", "arany_%",
                    "uj_hatarpontok_YX"])
        for r in rows:
            w.writerow([r["hrsz"], r["parcel_area_m2"], r["registered_area_m2"] or "", r["taken_m2"], r["remaining_m2"],
                        str(r["share_pct"]).replace(".", ","), " ".join(f"{p[0]:.3f},{p[1]:.3f}" for p in r["new_boundary_points"])])
        fp.write_text(buf.getvalue(), encoding="utf-8-sig")
        out["written"] = str(fp)
    if table_at is not None and rows:
        from .ops_annotate import table as draw_table

        data = [["Hrsz", "Földrészlet m²", "Kisajátítandó m²", "Maradék m²", "Arány %"]] + [
            [str(r["hrsz"]), str(r["parcel_area_m2"]), str(r["taken_m2"]), str(r["remaining_m2"]),
             f"{r['share_pct']:.2f}".replace(".", ",")] for r in rows]
        data.append(["Összesen", "", str(out["total_taken_m2"]), "", ""])
        widths = [12 * th, 12 * th, 14 * th, 11 * th, 9 * th]
        tb = draw_table(ctx, insert=table_at, rows=data, col_widths=widths, row_height=2.2 * th, text_height=th,
                        layer=layer)
        out["table_handles"] = tb.get("handles", [])[:5]
    return out


# ---------------------------------------------------------------------------
# as-built versus design
# ---------------------------------------------------------------------------


@op(T, "asbuilt_check", mutates=True)
def asbuilt_check(ctx: Ctx, mode: str, points=None, path: str | None = None, text: str | None = None,
                  order: str = "name,y,x,h", surface: str | None = None, alignment: str | None = None,
                  template: list | None = None, lines=None, tolerance_z: float | None = None,
                  tolerance_xy: float | None = None, label: bool = True, report: str | None = None,
                  layer: str = "MEGVALOSULAS", text_height: float = 0.3):
    """As-built check (megvalósulási ellenőrzés, ME-KÉ / MV-KÉ): measured points (points = selection of POINTs or [[Y,X,H],...], or a CSV path/text with order) against the design. mode 'surface': ΔZ to a terrain/design surface (terrain.surface name); mode 'road': station, offset and ΔZ to the road design (alignment + road.profile + template, superelevation included); mode 'line': horizontal deviation from design lines (lines = selection). Points outside tolerance_z / tolerance_xy are flagged red; labels in the drawing and a CSV report (report=path)."""
    from shapely.geometry import Point

    m = _m(ctx)
    meas = []
    if points is not None and isinstance(points, dict):
        for e in select_from(ctx, points):
            if e.dxftype() == "POINT":
                loc = e.dxf.location
                meas.append({"name": e.dxf.handle, "y": loc.x / m, "x": loc.y / m, "h": loc.z / m})
    elif points is not None:
        for i, p in enumerate(points):
            q = _pt(ctx, p)
            meas.append({"name": q[3] or f"M{i + 1}", "y": q[0], "x": q[1], "h": q[2]})
    elif path or text:
        raw = ctx.resolve(path).read_text(encoding="utf-8-sig", errors="replace") if path else text
        cols = [c.strip().lower() for c in order.split(",")]
        delim = ";" if raw.count(";") > raw.count(",") else ("," if "," in raw else None)
        rows = list(csv.reader(io.StringIO(raw), delimiter=delim)) if delim else [ln.split() for ln in raw.splitlines()]
        for r in rows:
            rec = dict(zip(cols, [c.strip() for c in r]))
            try:
                meas.append({"name": rec.get("name") or rec.get("id"), "y": float(rec["y"].replace(",", ".")),
                             "x": float(rec["x"].replace(",", ".")),
                             "h": float(rec["h"].replace(",", ".")) if rec.get("h") else None})
            except (KeyError, ValueError):
                continue
    if not meas:
        raise CadError("No measured points (points, path or text)")
    res = []
    if mode == "surface":
        from .ops_terrain import surface_interpolator

        if not surface:
            raise CadError("mode surface needs surface=name")
        f = surface_interpolator(ctx, surface)
        for p in meas:
            zd = f(p["y"] * m, p["x"] * m)
            zd = None if zd is None else zd / m
            res.append({**p, "design_h": zd, "dZ": None if zd is None or p["h"] is None else p["h"] - zd})
    elif mode == "road":
        from .ops_road import DEFAULT_TEMPLATE, get_alignment
        from .ops_road_kek import _z_at

        al, _ = get_alignment(ctx, alignment)
        tpl = template or DEFAULT_TEMPLATE
        for p in meas:
            s, o = al.station_of(p["y"], p["x"])
            zd = _z_at(ctx, alignment, al, s, -o, tpl)
            res.append({**p, "station": s, "offset": o, "design_h": zd,
                        "dZ": None if zd is None or p["h"] is None else p["h"] - zd})
    elif mode == "line":
        from . import geom

        shapes = [g for g in (geom.to_shape(e) for e in select_from(ctx, lines)) if g is not None]
        if not shapes:
            raise CadError("mode line needs lines=selection of design lines")
        for p in meas:
            q = Point(p["y"] * m, p["x"] * m)
            d = min(sh.distance(q) for sh in shapes) / m
            res.append({**p, "dXY": d})
    else:
        raise CadError("mode: surface, road or line")
    bad = 0
    ensure_layer(ctx.doc, layer)
    created = []
    for r in res:
        flag = False
        if tolerance_z is not None and r.get("dZ") is not None and abs(r["dZ"]) > tolerance_z:
            flag = True
        if tolerance_xy is not None and r.get("dXY") is not None and r["dXY"] > tolerance_xy:
            flag = True
        r["ok"] = not flag
        bad += flag
        if label:
            val = r.get("dZ") if mode != "line" else r.get("dXY")
            txt = f"{r['name']}: {'Δ' if mode != 'line' else 'e'}={val * 1000:+.0f} mm" if val is not None else f"{r['name']}: -"
            t = ctx.msp.add_text(txt, height=text_height * m, dxfattribs={"layer": layer, "color": 1 if flag else 3})
            t.set_placement((r["y"] * m + text_height * m * 0.4, r["x"] * m - text_height * m * 1.2))
            created.append(t)
    vals = [abs(r["dZ"]) for r in res if r.get("dZ") is not None] or [r["dXY"] for r in res if r.get("dXY") is not None]
    out = {"mode": mode, "points": len(res), "outside_tolerance": bad,
           "max_abs_deviation": round(max(vals), 4) if vals else None,
           "mean_deviation": round(float(np.mean([r.get("dZ", r.get("dXY")) for r in res
                                                   if r.get("dZ", r.get("dXY")) is not None])), 4) if vals else None,
           "rows": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in res][:500],
           "handles": handles(created)}
    if report:
        fp = ctx.resolve(report)
        keys = [k for k in ("name", "y", "x", "h", "station", "offset", "design_h", "dZ", "dXY", "ok") if k in res[0]]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(keys)
        for r in res:
            w.writerow([("" if r.get(k) is None else (f"{r[k]:.4f}".replace(".", ",") if isinstance(r[k], float) else r[k]))
                        for k in keys])
        fp.write_text(buf.getvalue(), encoding="utf-8-sig")
        out["written"] = str(fp)
    return out


# ---------------------------------------------------------------------------
# DAT export (DAT-M1, G Függelék)
# ---------------------------------------------------------------------------


def _ring_xyb(e, m: float) -> list[list[float]]:
    """[[Y, X, bulge], ...] of a closed polyline in metres, arcs over 180° split in two."""
    if e.dxftype() == "LWPOLYLINE":
        pts = [[x / m, y / m, b] for x, y, b in e.get_points("xyb")]
    elif e.dxftype() == "POLYLINE":
        pts = [[v.dxf.location.x / m, v.dxf.location.y / m, v.dxf.get("bulge", 0.0)] for v in e.vertices]
    else:
        raise CadError(f"{e.dxf.handle}: export needs closed polylines, not {e.dxftype()}")
    if len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-6:
        pts = pts[:-1]
    out = []
    for i, (y, x, b) in enumerate(pts):
        ny, nx = pts[(i + 1) % len(pts)][:2]
        if abs(b) >= 1.0 - 1e-9:  # sweep >= 180°: insert the arc midpoint (DAT arcs are the shorter ones)
            th = 4 * math.atan(b)
            ch = math.hypot(ny - y, nx - x)
            r = ch / (2 * math.sin(abs(th) / 2))
            mid_y, mid_x = (y + ny) / 2, (x + nx) / 2
            ux, uy = (ny - y) / ch, (nx - x) / ch  # chord direction in (Y, X)
            sag = r * (1 - math.cos(th / 2)) * (1 if th > 0 else -1)
            # the arc bulges to the right of a→b for a positive (counter-clockwise) bulge
            py, px = mid_y + uy * sag, mid_x - ux * sag
            hb = math.tan(th / 8)
            out += [[y, x, hb], [py, px, hb]]
        else:
            out.append([y, x, b])
    return out


def _signed_area(ring) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2


def _reverse_ring(ring):
    n = len(ring)
    return [[ring[(-i) % n][0], ring[(-i) % n][1], -ring[(-i - 1) % n][2]] for i in range(n)]


@op(T, "export_dat")
def export_dat(ctx: Ctx, path: str, sel=None, hrsz: dict | None = None, labels=None, table: str = "BD",
               obj_fels: str | None = None, encoding: str = "cp1250", title: str = "cad-mcp DAT export",
               sender: str = "", receiver: str = ""):
    """Write parcels as a DAT exchange file (DAT-M1 G Függelék): T_CIMREK, T_PONT, T_OSSZEKOT_IV, T_HATARVONAL, T_HATAR, T_FELULET and T_OBJ_ATTRBD (table='BC' for public land) with the helyrajzi szám, area and geometry (shared boundaries written once, outer boundaries clockwise, holes, exact arcs). sel = closed polylines (default: the parcels imported by survey.import_dat); helyrajzi szám from the import, from hrsz={handle: "0123/4"} or from texts (labels selection) inside. The geometry is complete; attributes that come from land registry code tables (fekvés, elhatárolás, jelkulcs, munkaterület …) are left empty for the surveyor to fill before submitting to the land office."""
    from shapely.geometry import Point, Polygon

    from .ops_road import _load

    if table not in ("BD", "BC"):
        raise CadError("table: BD (földrészlet) or BC (közterületi földrészlet)")
    m = _m(ctx)
    reg = _load(ctx, "DAT_PARCELS") or {}
    if sel is None:
        ents = [ctx.doc.entitydb[h] for h in reg if h in ctx.doc.entitydb and ctx.doc.entitydb[h].is_alive]
    else:
        ents = select_from(ctx, sel)
    if not ents:
        raise CadError("No parcels to export (import a DAT file or give sel)")
    texts = select_from(ctx, labels) if labels is not None else []
    parcels = []
    for e in ents:
        meta = reg.get(e.dxf.handle, {})
        outer = _ring_xyb(e, m)
        if len(outer) < 3:
            continue
        holes = [_ring_xyb(ctx.doc.entitydb[h], m) for h in meta.get("holes", []) if h in ctx.doc.entitydb]
        name = (hrsz or {}).get(e.dxf.handle) or meta.get("hrsz")
        if not name and texts:
            poly = Polygon([(p[0], p[1]) for p in outer])
            for t in texts:
                if t.dxftype() in ("TEXT", "MTEXT") and poly.contains(Point(t.dxf.insert.x / m, t.dxf.insert.y / m)):
                    name = t.plain_text() if t.dxftype() == "MTEXT" else t.dxf.text
                    break
        area = abs(_poly_of(e, m).area) if _poly_of(e, m) is not None else abs(_signed_area(outer))
        for h in holes:
            area -= abs(_signed_area(h))
        parcels.append({"handle": e.dxf.handle, "hrsz": name or "", "outer": outer, "holes": holes, "area": area,
                        "obj_fels": obj_fels or meta.get("obj_fels") or "",
                        "poly": Polygon([(q[0], q[1]) for q in outer]).buffer(0)})
    # a selected polygon inside another one is a hole (enclave) of the smallest one containing it; it stays a parcel
    # of its own only when it has a helyrajzi szám
    if sel is not None:
        for p in sorted(parcels, key=lambda q: q["poly"].area):
            hosts = [q for q in parcels if q is not p and q["poly"].area > p["poly"].area
                     and q["poly"].buffer(1e-6).contains(p["poly"])]
            if hosts:
                host = min(hosts, key=lambda q: q["poly"].area)
                if not any(math.isclose(abs(_signed_area(h)), abs(_signed_area(p["outer"])), rel_tol=1e-9) for h in host["holes"]):
                    host["holes"].append(p["outer"])
                    host["area"] -= p["poly"].area
                p["enclave"] = True
        parcels = [p for p in parcels if not p.get("enclave") or p["hrsz"]]
    # points
    pid: dict = {}
    pts: list = []

    def point_id(y, x):
        key = (round(y, 3), round(x, 3))
        if key not in pid:
            pts.append(key)
            pid[key] = len(pts)
        return pid[key]

    arcs: list = []
    edges: dict = {}  # canonical key -> hatarvonal id
    edge_rows: list = []
    rings: dict = {}  # canonical ring key -> hatar id
    hatar_rows: list = []

    def edge(a, b, bulge, ya, xa, yb, xb):
        """hatarvonal id and whether the ring runs along its stored direction."""
        if a == b:
            return None
        fwd = a < b
        lo, hi = (a, b) if fwd else (b, a)
        key = (lo, hi, round(bulge if fwd else -bulge, 9))
        if key not in edges:
            arc_id = ""
            if abs(bulge) > 1e-12:
                th = 4 * math.atan(bulge)
                sgn = 1.0 if th > 0 else -1.0
                ch = math.hypot(yb - ya, xb - xa)
                r = ch / (2 * math.sin(abs(th) / 2))
                d = r * math.cos(th / 2)  # centre distance from the chord midpoint
                dY, dX = (yb - ya) / ch, (xb - xa) / ch
                # counter-clockwise (positive) bulge: the centre lies to the left of a→b
                cy = (ya + yb) / 2 - sgn * dX * d
                cx = (xa + xb) / 2 + sgn * dY * d
                arcs.append((cy, cx, r))
                arc_id = str(len(arcs))
            edges[key] = len(edges) + 1
            edge_rows.append([edges[key], 1, lo, hi, 1 if arc_id else 0, arc_id])
        return edges[key], fwd

    def ring_id(ring) -> int:
        if _signed_area(ring) > 0:  # base orientation: clockwise (DAT-M1 T_HATAR rule 2)
            ring = _reverse_ring(ring)
        ids = [point_id(p[0], p[1]) for p in ring]
        segs = []
        for i in range(len(ring)):
            j = (i + 1) % len(ring)
            r = edge(ids[i], ids[j], ring[i][2], ring[i][0], ring[i][1], ring[j][0], ring[j][1])
            if r:
                segs.append(r)
        key = tuple(sorted(s[0] for s in segs))
        if key not in rings:
            rings[key] = len(rings) + 1
            for k, (hv, fwd) in enumerate(segs, 1):
                hatar_rows.append([rings[key], k, hv, "+" if fwd else "-"])
        return rings[key]

    fel_rows, obj_rows = [], []
    for k, p in enumerate(parcels, 1):
        fel_rows.append([k, 1, ring_id(p["outer"]), "+"])
        for h in p["holes"]:
            fel_rows.append([k, 1, ring_id(h), "-"])
        row = [k, p["obj_fels"], k, p["hrsz"], "", "", ""] if table == "BC" else [k, p["obj_fels"], k, p["hrsz"], "", ""]
        row.append(str(int(round(p["area"]))))
        nfields = len(DAT_FIELDS["T_OBJ_ATTR" + table])
        row += [""] * (nfields - len(row))
        fields = DAT_FIELDS["T_OBJ_ATTR" + table]
        row[fields.index("elozo_parcel_id")] = k
        obj_rows.append(row)
    import datetime

    def line(vals) -> str:
        return "".join(f"{'' if v is None else v}*" for v in vals) + "\r\n"

    fp = ctx.resolve(path)
    stem = re.sub(r"[^A-Za-z0-9]", "", fp.stem)[:8] or "export"
    out = [line(["T_CIMREK"]),
           line([stem, title[:22], "DAT1", sender[:25], "", receiver[:25], "", datetime.date.today().strftime("%Y%m%d"),
                 "cad-mcp", "1"]),
           line(["T_PONT"])]
    out += [line([i, f"{x:.2f}", f"{y:.2f}", "", "", ""]) for i, (y, x) in enumerate(pts, 1)]
    if arcs:
        out.append(line(["T_OSSZEKOT_IV"]))
        out += [line([i, f"{cx:.2f}", f"{cy:.2f}", f"{r:.2f}"]) for i, (cy, cx, r) in enumerate(arcs, 1)]
    out.append(line(["T_HATARVONAL"]))
    out += [line(r) for r in edge_rows]
    out.append(line(["T_HATAR"]))
    out += [line(r) for r in hatar_rows]
    out.append(line(["T_FELULET"]))
    out += [line(r) for r in fel_rows]
    out.append(line(["T_OBJ_ATTR" + table]))
    out += [line(r) for r in obj_rows]
    fp.write_bytes(("".join(out)).encode(encoding, errors="replace") + b"\x1a")
    missing = [] if all(p["hrsz"] for p in parcels) else [p["handle"] for p in parcels if not p["hrsz"]]
    res = {"written": str(fp), "parcels": len(parcels), "points": len(pts), "boundary_lines": len(edge_rows),
           "boundaries": len(rings), "arcs": len(arcs), "encoding": encoding,
           "note": "Geometria és helyrajzi szám kész; a kódtáblázatos kötelező attribútumokat (obj_fels, fekvés, "
                   "elhatárolás, jelkulcs, munkaterület) a földhivatali beadás előtt ki kell tölteni."}
    if missing:
        res["warning"] = f"Helyrajzi szám nélküli földrészletek: {missing}"
    return res
