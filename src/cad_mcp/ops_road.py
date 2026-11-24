"""Tool `road`: road design (útügyi) drawings: horizontal alignment with clothoids,
stationing, edge/lane lines, road markings, curve table, longitudinal profile,
cross sections with cut/fill areas and earthwork volumes."""

from __future__ import annotations

import json
import math

from ezdxf import units as ezunits
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from .core import CadError, Ctx, ensure_layer, op, vec
from .road_geom import Alignment, GeomError, Profile, format_station

T = "road"
DICT = "CADMCP_ROAD"

# ---------------------------------------------------------------------------
# persistence: definitions live inside the drawing (XRECORD), survive save/open
# ---------------------------------------------------------------------------


def _store(ctx: Ctx, key: str, data: dict) -> None:
    d = ctx.doc.rootdict.get_required_dict(DICT)
    text = json.dumps(data, separators=(",", ":"))
    if key in d:
        d.remove(key)
    xr = d.add_xrecord(key)
    xr.reset([(1, text[i:i + 250]) for i in range(0, len(text), 250)])


def _load(ctx: Ctx, key: str) -> dict | None:
    d = ctx.doc.rootdict.get(DICT)
    if d is None or key not in d:
        return None
    return json.loads("".join(v for c, v in d[key].tags if c == 1))


def _keys(ctx: Ctx, prefix: str) -> list[str]:
    d = ctx.doc.rootdict.get(DICT)
    return [k[len(prefix):] for k in (d.keys() if d is not None else []) if k.startswith(prefix)]


def get_alignment(ctx: Ctx, name: str) -> tuple[Alignment, dict]:
    data = _load(ctx, "ALIGN_" + name)
    if data is None:
        raise CadError(f"No alignment '{name}'. Alignments: {_keys(ctx, 'ALIGN_')}")
    return Alignment.from_dict(data["geometry"]), data


def get_profile(ctx: Ctx, name: str) -> tuple[Profile, dict] | tuple[None, None]:
    data = _load(ctx, "PROFILE_" + name)
    if data is None:
        return None, None
    return Profile(data["vpis"], data["radii"]), data


def _m(ctx: Ctx) -> float:
    """Drawing units per meter (road ops work in meters)."""
    u = ctx.doc.units
    if not u:
        return 1.0
    try:
        return ezunits.conversion_factor(ezunits.M, u)
    except Exception:
        return 1.0


def _attribs(ctx: Ctx, layer: str, color=None, linetype: str | None = None) -> dict:
    ensure_layer(ctx.doc, layer)
    a = {"layer": layer}
    if color is not None:
        a["color"] = color
    if linetype:
        from .core import ensure_linetype

        ensure_linetype(ctx.doc, linetype)
        a["linetype"] = linetype
    return a


def _wrap(fn):
    try:
        return fn()
    except GeomError as exc:
        raise CadError(str(exc)) from exc


# ---------------------------------------------------------------------------
# alignment
# ---------------------------------------------------------------------------


@op(T, "alignment", mutates=True)
def alignment(ctx: Ctx, name: str, points: list, radii: list | None = None, spiral_lengths: list | None = None,
              start_station: float = 0.0, layer: str = "TENGELY", space=None):
    """Horizontal alignment (nyomvonal) from start point, intersection points (PI) and end point. radii = one circular radius per PI (0 = sharp angle), spiral_lengths = clothoid (átmeneti ív) length per PI on both sides (0 = none). Draws lines, arcs and clothoids and stores the alignment in the drawing."""
    m = _m(ctx)
    pts = [tuple(c / m for c in vec(p).vec2) for p in points]
    al = _wrap(lambda: Alignment.from_pis(pts, radii or [0] * (len(pts) - 2), spiral_lengths, start_station))
    lay = ctx.layout(space)
    at = _attribs(ctx, layer)
    hs = []
    for e in al.elements:
        x0, y0 = e.x0 * m, e.y0 * m
        if e.kind == "line":
            x1, y1, _ = e.end
            ent = lay.add_line((x0, y0), (x1 * m, y1 * m), dxfattribs=at)
        elif e.kind == "arc":
            k = e.k0
            r = abs(1 / k)
            cx, cy = e.x0 - math.sin(e.h0) / k, e.y0 + math.cos(e.h0) / k
            a0 = math.degrees(math.atan2(e.y0 - cy, e.x0 - cx))
            sweep = math.degrees(e.length / r)
            start, end = (a0, a0 + sweep) if k > 0 else (a0 - sweep, a0)
            ent = lay.add_arc((cx * m, cy * m), r * m, start, end, dxfattribs=at)
        else:
            n = max(16, int(e.length / 2))
            fit = [tuple(c * m for c in e.point(e.length * i / n)) for i in range(n + 1)]
            ent = lay.add_spline(fit, dxfattribs=at)
            ent.dxf.start_tangent = (math.cos(e.h0), math.sin(e.h0), 0)
            h1 = e.heading(e.length)
            ent.dxf.end_tangent = (math.cos(h1), math.sin(h1), 0)
        hs.append(ent.dxf.handle)
    data = {"name": name, "points": [list(p) for p in pts], "radii": radii, "spiral_lengths": spiral_lengths,
            "layer": layer, "handles": hs, "geometry": al.to_dict()}
    _store(ctx, "ALIGN_" + name, data)
    return {
        "alignment": name, "handles": hs, "start": format_station(al.start_station),
        "end": format_station(al.end_station), "length_m": round(al.length, 3),
        "elements": [{"type": e.kind, "from": format_station(e.s0), "length": round(e.length, 3),
                      **({"R": round(abs(1 / e.k0 if e.k0 else 1 / e.k1), 3)} if e.kind != "line" else {})}
                     for e in al.elements],
        "curves": [{"PI": c.index, "deflection_deg": round(c.deflection_deg, 4), "R": c.radius,
                    "L": c.spiral_length, "A": round(c.spiral_param_A, 3), "T": round(c.tangent_length, 3),
                    "arc_length": round(c.arc_length, 3),
                    **{k: format_station(v) for k, v in c.stations.items()}} for c in al.curves],
    }


@op(T, "list")
def road_list(ctx: Ctx):
    """Alignments and profiles stored in the drawing."""
    out = []
    for n in _keys(ctx, "ALIGN_"):
        al, d = get_alignment(ctx, n)
        out.append({"name": n, "from": format_station(al.start_station), "to": format_station(al.end_station),
                    "length_m": round(al.length, 3), "curves": len(al.curves),
                    "has_profile": _load(ctx, "PROFILE_" + n) is not None})
    return {"alignments": out}


@op(T, "station_point")
def station_point(ctx: Ctx, name: str, station: float, offset: float = 0.0):
    """Coordinates and direction at a station (and offset, + = left)."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    x, y, h = _wrap(lambda: al.point_at(float(station), float(offset)))
    return {"point": [round(x * m, 4), round(y * m, 4)], "bearing_deg": round(math.degrees(h) % 360, 6),
            "station": format_station(station)}


@op(T, "station_of")
def station_of(ctx: Ctx, name: str, point):
    """Station and offset (+ left / - right) of a point relative to an alignment."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    x, y = (c / m for c in vec(point).vec2)
    s, o = al.station_of(x, y)
    return {"station": round(s, 4), "station_text": format_station(s), "offset": round(o, 4)}


@op(T, "stationing", mutates=True)
def stationing(ctx: Ctx, name: str, interval: float = 100, minor_interval: float | None = 20,
               tick: float = 2.0, text_height: float = 1.5, decimals: int = 0, key_points: bool = True,
               layer: str = "SZELVENYEZES", side: str = "left", space=None):
    """Chainage marks (szelvényezés) along an alignment: labelled ticks every interval, short ticks every minor_interval, and labelled curve key points (KE, ÍE, ÍV, KV)."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    lay = ctx.layout(space)
    at = _attribs(ctx, layer)
    sgn = 1 if side == "left" else -1
    created = []

    def mark(s, length, label=None):
        x0, y0, h = al.point_at(s, -sgn * length / 2)
        x1, y1, _ = al.point_at(s, sgn * length)
        created.append(lay.add_line((x0 * m, y0 * m), (x1 * m, y1 * m), dxfattribs=at))
        if label:
            xt, yt, _ = al.point_at(s, sgn * (length + 0.5 * text_height))
            rot = math.degrees(h) + 90 * sgn
            if 90 < rot % 360 < 270:
                rot += 180
                align = "MIDDLE_RIGHT"
            else:
                align = "MIDDLE_LEFT"
            t = lay.add_text(label, height=text_height * m, rotation=rot, dxfattribs=at)
            from ezdxf.enums import TextEntityAlignment

            t.set_placement((xt * m, yt * m), align=TextEntityAlignment[align])
            created.append(t)

    majors = set(round(s, 6) for s in al.stations(interval, include_ends=False))
    for s in sorted(majors | {round(al.start_station, 6), round(al.end_station, 6)}):
        mark(s, tick, format_station(s, decimals))
    if minor_interval:
        for s in al.stations(minor_interval, include_ends=False):
            if round(s, 6) not in majors:
                mark(s, tick / 2)
    if key_points:
        for c in al.curves:
            for k, s in c.stations.items():
                mark(s, tick * 1.5, f"{k.replace('IE', 'ÍE').replace('IV', 'ÍV')} {format_station(s, 2)}")
    return {"handles": [e.dxf.handle for e in created], "marks": len(created)}


def _sample(al: Alignment, offset: float, step: float, s0=None, s1=None) -> list[tuple[float, float]]:
    a = al.start_station if s0 is None else max(al.start_station, s0)
    b = al.end_station if s1 is None else min(al.end_station, s1)
    stations = [a] + [s for s in al.stations(step, include_ends=False) if a < s < b] + [b]
    # always include element boundaries so corners and curve ends are exact
    for e in al.elements:
        if a < e.s0 < b:
            stations.append(e.s0)
    return [al.point_at(s, offset)[:2] for s in sorted(set(round(s, 9) for s in stations))]


@op(T, "offset_lines", mutates=True)
def offset_lines(ctx: Ctx, name: str, offsets: list, layer: str = "BURKOLATSZEL", step: float = 1.0,
                 from_station: float | None = None, to_station: float | None = None, color=None,
                 linetype: str | None = None, space=None):
    """Lines parallel to the alignment at given offsets (+ left, - right), e.g. pavement edges [-3.5, 3.5] or ditch lines."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    lay = ctx.layout(space)
    at = _attribs(ctx, layer, color, linetype)
    hs = []
    for off in offsets:
        pts = _sample(al, float(off), step, from_station, to_station)
        hs.append(lay.add_lwpolyline([(x * m, y * m) for x, y in pts], dxfattribs=at).dxf.handle)
    return {"handles": hs}


@op(T, "marking", mutates=True)
def marking(ctx: Ctx, name: str, offset: float = 0.0, dash: float = 3.0, gap: float = 6.0, width: float = 0.12,
            solid: bool = False, from_station: float | None = None, to_station: float | None = None,
            layer: str = "BURKOLATI_JEL", space=None):
    """Road marking (burkolati jel) along the alignment: dashed (dash/gap in m, e.g. 3/6 or 6/3) or solid line, real width in m. Drawn as filled polylines that follow curves."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    lay = ctx.layout(space)
    at = _attribs(ctx, layer)
    a = al.start_station if from_station is None else from_station
    b = al.end_station if to_station is None else to_station
    pieces = [(a, b)] if solid else []
    if not solid:
        s = a
        while s < b - 1e-9:
            pieces.append((s, min(s + dash, b)))
            s += dash + gap
    hs = []
    for s0, s1 in pieces:
        pts = _sample(al, float(offset), 0.5, s0, s1)
        e = lay.add_lwpolyline([(x * m, y * m) for x, y in pts], dxfattribs={**at, "const_width": width * m})
        hs.append(e.dxf.handle)
    return {"handles": hs, "pieces": len(hs)}


@op(T, "curve_table", mutates=True)
def curve_table(ctx: Ctx, name: str, insert, text_height: float = 2.0, layer: str = "KITUZES", space=None):
    """Curve setting-out table (kitűzési táblázat): deflection, R, clothoid L and A, tangent T, arc length and key stations for each curve."""
    from .ops_annotate import table

    al, _ = get_alignment(ctx, name)
    rows = [["Ív", "Eltérés [°]", "R [m]", "L klot. [m]", "A [m]", "T [m]", "Körív [m]", "KE", "ÍE", "ÍV", "KV"]]
    for i, c in enumerate(al.curves, 1):
        st = c.stations
        rows.append([str(i), f"{abs(c.deflection_deg):.4f}", f"{c.radius:.2f}", f"{c.spiral_length:.2f}",
                     f"{c.spiral_param_A:.2f}", f"{c.tangent_length:.3f}", f"{c.arc_length:.3f}",
                     format_station(st["KE"]) if "KE" in st else "-", format_station(st["IE"]),
                     format_station(st["IV"]), format_station(st["KV"]) if "KV" in st else "-"])
    th = text_height * _m(ctx)
    widths = [6 * th, 10 * th, 8 * th, 9 * th, 8 * th, 8 * th, 9 * th] + [10 * th] * 4
    return table(ctx, insert=insert, rows=rows, col_widths=widths, row_height=2.2 * th, text_height=th,
                 space=space, layer=layer)


# ---------------------------------------------------------------------------
# longitudinal profile (hossz-szelvény)
# ---------------------------------------------------------------------------


def _terrain_line(ctx: Ctx, al: Alignment, terrain, surface, step):
    if terrain:
        return [(float(s), float(z)) for s, z in terrain]
    if surface:
        from .ops_terrain import surface_interpolator

        f = surface_interpolator(ctx, surface)
        m = _m(ctx)
        out = []
        for s in al.stations(step):
            x, y, _ = al.point_at(s)
            z = f(x * m, y * m)
            if z is not None:
                out.append((s, z / m))
        if len(out) < 2:
            raise CadError("The alignment does not cross the terrain surface")
        return out
    return []


@op(T, "profile", mutates=True)
def profile(ctx: Ctx, name: str, insert, vpis: list | None = None, radii: list | None = None,
            terrain: list | None = None, surface: str | None = None, v_exag: float = 10.0,
            datum: float | None = None, grid_station: float = 50.0, grid_elev: float = 1.0,
            band_interval: float = 50.0, text_height: float = 2.0, terrain_step: float = 10.0, space=None):
    """Longitudinal profile (hossz-szelvény) drawing at insert: terrain line (given [[station, z],...] or sampled from a terrain surface), design grade line through vpis [[station, z],...] with vertical curve radii, grid, VPI labels, grades and a data band (station, terrain, design, difference). Horizontal 1 m = 1 drawing meter, vertical exaggerated v_exag times."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    lay = ctx.layout(space)
    ox, oy = (c / m for c in vec(insert).vec2)
    terr = _terrain_line(ctx, al, terrain, surface, terrain_step)
    prof = None
    if vpis:
        prof = _wrap(lambda: Profile(vpis, radii))
        _store(ctx, "PROFILE_" + name, {"vpis": [list(v) for v in prof.vpis], "radii": list(radii or [])})
    elif get_profile(ctx, name)[0] is not None:
        prof = get_profile(ctx, name)[0]
    zs = [z for _, z in terr] + ([z for _, z in prof.vpis] if prof else [])
    if not zs:
        raise CadError("Give terrain, surface or vpis")
    if datum is None:
        datum = math.floor(min(zs) / grid_elev) * grid_elev - grid_elev * 2
    top = math.ceil(max(zs) / grid_elev) * grid_elev + grid_elev
    s0, s1 = al.start_station, al.end_station
    X = lambda s: (ox + (s - s0)) * m  # noqa: E731
    Y = lambda z: (oy + (z - datum) * v_exag) * m  # noqa: E731
    th = text_height * m
    created = []
    a_grid = _attribs(ctx, "HOSSZ_RACS", color=8)
    a_ter = _attribs(ctx, "HOSSZ_TEREP", color=3)
    a_des = _attribs(ctx, "HOSSZ_TERV", color=1)
    a_txt = _attribs(ctx, "HOSSZ_FELIRAT", color=7)
    # grid
    s = math.ceil(s0 / grid_station) * grid_station
    while s <= s1 + 1e-9:
        created.append(lay.add_line((X(s), Y(datum)), (X(s), Y(top)), dxfattribs=a_grid))
        s += grid_station
    z = datum
    while z <= top + 1e-9:
        created.append(lay.add_line((X(s0), Y(z)), (X(s1), Y(z)), dxfattribs=a_grid))
        created.append(lay.add_text(f"{z:.2f}", height=th * 0.8, dxfattribs=a_txt).set_placement(
            (X(s0) - th, Y(z)), align=_al("MIDDLE_RIGHT")))
        z += grid_elev
    created.append(lay.add_lwpolyline([(X(s0), Y(datum)), (X(s1), Y(datum)), (X(s1), Y(top)), (X(s0), Y(top))],
                                      close=True, dxfattribs=a_grid))
    # terrain
    if len(terr) >= 2:
        created.append(lay.add_lwpolyline([(X(s), Y(z)) for s, z in terr], dxfattribs=a_ter))
    # design line with vertical curves
    result = {}
    if prof:
        pts = []
        ss = sorted(set([v[0] for v in prof.vpis] + [s for c in prof.curves for s in (c.start, c.end)] +
                        [prof.vpis[0][0] + i for i in range(int(prof.vpis[-1][0] - prof.vpis[0][0]) + 1)]))
        pts = [(X(s), Y(prof.elevation(s))) for s in ss if prof.vpis[0][0] <= s <= prof.vpis[-1][0]]
        created.append(lay.add_lwpolyline(pts, dxfattribs=a_des))
        for (sa, za), (sb, zb), g in zip(prof.vpis, prof.vpis[1:], prof.grades):
            created.append(lay.add_line((X(sa), Y(za)), (X(sb), Y(zb)), dxfattribs={**a_grid, "linetype": "DASHED"}
                                        if ctx.doc.linetypes.has_entry("DASHED") else a_grid))
            mid = (sa + sb) / 2
            ang = math.degrees(math.atan2((zb - za) * v_exag, sb - sa))
            created.append(lay.add_text(f"{g * 100:+.2f}%  L={sb - sa:.1f}", height=th, rotation=ang,
                                        dxfattribs=a_des).set_placement(
                (X(mid), Y(prof.elevation(mid)) + th), align=_al("BOTTOM_CENTER")))
        for c in prof.curves:
            label = f"{'Dombív' if c.kind == 'crest' else 'Teknőív'} R={c.radius:.0f} T={c.length / 2:.2f}"
            created.append(lay.add_line((X(c.station), Y(c.elevation)), (X(c.station), Y(top)),
                                        dxfattribs=a_des))
            created.append(lay.add_text(label, height=th, rotation=90, dxfattribs=a_des).set_placement(
                (X(c.station) - th * 0.3, Y(top) - th), align=_al("TOP_RIGHT")))
        result["curves"] = [{"station": format_station(c.station), "type": c.kind, "R": c.radius,
                             "T": round(c.length / 2, 3), "from": format_station(c.start),
                             "to": format_station(c.end)} for c in prof.curves]
        result["grades_percent"] = [round(g * 100, 3) for g in prof.grades]
    # data band
    from .road_geom import superelevation_at

    se_spec = get_alignment(ctx, name)[1].get("superelevation")
    rows = ["Szelvény", "Terepszint", "Tervezett szint", "Különbség"] + (["Keresztesés B/J %"] if se_spec else [])
    rh = th * 3
    band_top = Y(datum)
    for i in range(len(rows) + 1):
        yy = band_top - i * rh
        created.append(lay.add_line((X(s0) - th * 14, yy), (X(s1), yy), dxfattribs=a_grid))
    for i, r in enumerate(rows):
        created.append(lay.add_text(r, height=th, dxfattribs=a_txt).set_placement(
            (X(s0) - th * 13.5, band_top - (i + 0.5) * rh), align=_al("MIDDLE_LEFT")))

    def tz(s):
        if len(terr) < 2 or not (terr[0][0] <= s <= terr[-1][0]):
            return None
        for (sa, za), (sb, zb) in zip(terr, terr[1:]):
            if sa <= s <= sb:
                return za + (zb - za) * (s - sa) / (sb - sa) if sb > sa else za
        return None

    table_rows = []
    for s in al.stations(band_interval):
        t_z = tz(s)
        d_z = prof.elevation(s) if prof and prof.vpis[0][0] <= s <= prof.vpis[-1][0] else None
        vals = [format_station(s, 0 if band_interval >= 1 else 2), f"{t_z:.2f}" if t_z is not None else "",
                f"{d_z:.2f}" if d_z is not None else "",
                f"{d_z - t_z:+.2f}" if (t_z is not None and d_z is not None) else ""]
        if se_spec:
            sl, sr = superelevation_at(al, se_spec, s)
            vals.append(f"{sl:+.1f}/{sr:+.1f}")
        for i, v in enumerate(vals):
            if v:
                created.append(lay.add_text(v, height=th * 0.8, rotation=90, dxfattribs=a_txt).set_placement(
                    (X(s), band_top - (i + 0.5) * rh), align=_al("MIDDLE_CENTER")))
        table_rows.append({"station": s, "terrain": t_z, "design": d_z})
    # remember where the profile view is, so ditches etc. can be drawn into it later
    _store(ctx, "PVIEW_" + name, {"insert": [ox, oy], "datum": datum, "v_exag": v_exag, "s0": s0,
                                  "space": space})
    result.update({"handles": [e.dxf.handle for e in created if e is not None], "datum": datum,
                   "v_exag": v_exag, "band": table_rows[:200]})
    return result


def _al(name: str):
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment[name]


# ---------------------------------------------------------------------------
# superelevation (túlemelés)
# ---------------------------------------------------------------------------


def _update_alignment(ctx: Ctx, name: str, **values) -> dict:
    _al_, data = get_alignment(ctx, name)
    data.update(values)
    _store(ctx, "ALIGN_" + name, data)
    return data


@op(T, "superelevation", mutates=True)
def superelevation(ctx: Ctx, name: str, e, normal: float = 2.5, runoff: float | None = None,
                   interval: float = 20.0):
    """Superelevation (túlemelés) for the curves of an alignment: e = one-way cross slope in % for every curve, or a list per curve (0 = keep crown). The outer lane rotates about the axis linearly along the clothoids (or a runoff length, 2/3 on the tangent, when there is no clothoid). Used automatically by cross sections; returns the slope table."""
    from .road_geom import superelevation_at

    al, _d = get_alignment(ctx, name)
    es = e if isinstance(e, list) else [e] * len(al.curves)
    if len(es) != len(al.curves):
        raise CadError(f"Give one e value per curve ({len(al.curves)})")
    spec = {"normal": float(normal), "curves": {str(i): {"e": float(v), "runoff": runoff}
                                                for i, v in enumerate(es, 1) if v}}
    _update_alignment(ctx, name, superelevation=spec)
    keys = set(al.stations(interval))
    for c in al.curves:
        keys |= set(c.stations.values())
    table = []
    for s in sorted(keys):
        lft, rgt = superelevation_at(al, spec, s)
        table.append({"station": format_station(s), "left_pct": round(lft, 3), "right_pct": round(rgt, 3)})
    return {"alignment": name, "curves": len(spec["curves"]), "table": table}


# ---------------------------------------------------------------------------
# cross sections (keresztszelvény)
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE = [{"width": 3.5, "slope": -2.5, "type": "lane"}, {"width": 1.5, "slope": -4.0, "type": "shoulder"}]


def _seg_type(seg: dict, i: int) -> str:
    return seg.get("type") or ("lane" if i == 0 else "shoulder")


def _section(ctx: Ctx, al: Alignment, station: float, center_z: float, template_left, template_right,
             cut_slope: float, fill_slope: float, terrain, surface, width: float, se=None,
             pavement=None, ditch=None):
    """Compute one cross section. Offsets: right = +. Returns a dict with lines, areas and layers."""
    if terrain:
        tline = [(float(o), float(z)) for o, z in terrain]
    else:
        from .ops_terrain import surface_interpolator

        f = surface_interpolator(ctx, surface)
        m = _m(ctx)
        tline = []
        n = int(width * 2)
        for i in range(n + 1):
            o = -width + 2 * width * i / n
            x, y, _ = al.point_at(station, -o)
            z = f(x * m, y * m)
            if z is not None:
                tline.append((o, z / m))
    if len(tline) < 2:
        raise CadError(f"No terrain at station {format_station(station)}")
    tline.sort()
    terr = LineString(tline)
    thick = [float(layer["thickness"]) for layer in (pavement or [])]
    total = sum(thick)
    sides = {}
    for side, tmpl in (("right", template_right), ("left", template_left)):
        sgn = 1 if side == "right" else -1
        lane_slope = None if se is None else (se[1] if side == "right" else se[0])
        surf = [(0.0, center_z)]
        o, z = 0.0, center_z
        paved_o, paved_z = 0.0, center_z
        for i, seg in enumerate(tmpl):
            kind = _seg_type(seg, i)
            slope = lane_slope if (kind == "lane" and lane_slope is not None) else float(seg["slope"])
            o += sgn * float(seg["width"])
            z += float(seg["width"]) * slope / 100
            surf.append((o, z))
            if kind == "lane" or seg.get("paved"):
                paved_o, paved_z = o, z
        edge_o, edge_z = o, z
        tz = _z_on(tline, edge_o)
        if tz is None:
            raise CadError(f"Terrain too narrow at station {format_station(station)}: widen the section")
        in_cut = tz >= edge_z
        outer = list(surf)
        if in_cut and ditch:
            d = float(ditch.get("depth", 0.5))
            o2 = edge_o + sgn * d * float(ditch.get("inner_slope", 1.5))
            outer.append((o2, edge_z - d))
            o3 = o2 + sgn * float(ditch.get("bottom_width", 0.5))
            outer.append((o3, edge_z - d))
        so, sz = outer[-1]
        dz_per_m = 1 / cut_slope if in_cut else -1 / fill_slope
        ray = LineString([(so, sz), (so + sgn * 300, sz + 300 * dz_per_m)])
        hit = ray.intersection(terr)
        cand = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
        if not cand:
            raise CadError(f"Side slope does not reach the terrain at station {format_station(station)}")
        best = min(cand, key=lambda p: abs(p.x - so))
        outer.append((best.x, best.y))
        sides[side] = {"surface": outer, "paved_o": paved_o, "paved_z": paved_z, "cut": in_cut,
                       "lane_slope": lane_slope}
    dline = list(reversed(sides["left"]["surface"])) + sides["right"]["surface"][1:]
    # formation (földmű) line: below the paved width lowered by the pavement thickness
    if total > 0:
        lo_p, hi_p = sides["left"]["paved_o"], sides["right"]["paved_o"]
        inner_pts = [(o, z) for o, z in dline if lo_p - 1e-9 <= o <= hi_p + 1e-9]
        left_out = [(o, z) for o, z in dline if o < lo_p - 1e-9]
        right_out = [(o, z) for o, z in dline if o > hi_p + 1e-9]
        formation = left_out + [(lo_p, _z_on(dline, lo_p))] + [(o, z - total) for o, z in inner_pts] + \
            [(hi_p, _z_on(dline, hi_p))] + right_out
        layers = []
        depth = 0.0
        for spec, t in zip(pavement, thick):
            top = [(o, z - depth) for o, z in inner_pts]
            bot = [(o, z - depth - t) for o, z in inner_pts]
            poly = Polygon(top + list(reversed(bot)))
            layers.append({"name": spec.get("name", f"réteg {len(layers) + 1}"), "thickness": t,
                           "area_m2": poly.area, "outline": top + list(reversed(bot))})
            depth += t
    else:
        formation, layers = dline, []
    lo, hi = formation[0][0], formation[-1][0]
    terr_part = [(lo, _z_on(tline, lo))] + [p for p in tline if lo < p[0] < hi] + [(hi, _z_on(tline, hi))]
    faces = list(polygonize(unary_union([LineString(formation), LineString(terr_part)])))
    cut = fill = 0.0
    for f in faces:
        rp = f.representative_point()
        dz = _z_on(formation, rp.x)
        if dz is None:
            continue
        if rp.y > dz:
            cut += f.area
        else:
            fill += f.area
    return {"terrain": tline, "surface": dline, "formation": formation, "layers": layers, "cut": cut,
            "fill": fill, "se": se}


def _z_on(line, o):
    for (a, za), (b, zb) in zip(line, line[1:]):
        if min(a, b) - 1e-9 <= o <= max(a, b) + 1e-9:
            return za if abs(b - a) < 1e-12 else za + (zb - za) * (o - a) / (b - a)
    return None


def _se_for(ctx: Ctx, name: str, al: Alignment, station: float, use: bool):
    if not use:
        return None
    from .road_geom import superelevation_at

    spec = get_alignment(ctx, name)[1].get("superelevation")
    return superelevation_at(al, spec, station) if spec else None


@op(T, "cross_section", mutates=True)
def cross_section(ctx: Ctx, name: str, station: float, insert, center_elevation: float | None = None,
                  template: list | None = None, template_left: list | None = None, cut_slope: float = 1.5,
                  fill_slope: float = 1.5, terrain: list | None = None, surface: str | None = None,
                  pavement: list | None = None, ditch: dict | None = None, use_superelevation: bool = True,
                  half_width: float = 30.0, text_height: float = 0.5, scale: float = 1.0, space=None):
    """Cross section (keresztszelvény) at a station, drawn at insert. terrain [[offset, z]] (right = +) or a surface; template [{width, slope %, type: lane|shoulder, paved}] from the axis outward (default lane 3.5 m -2.5 %, shoulder 1.5 m -4 %); lane slopes follow the stored superelevation; pavement [{name, thickness m}] layers under the paved width (earthwork is then measured to the formation); ditch {depth, bottom_width, inner_slope} in cut; side slopes 1:n to daylight. Returns cut/fill and layer areas."""
    al, _ = get_alignment(ctx, name)
    if center_elevation is None:
        prof, _d = get_profile(ctx, name)
        if prof is None:
            raise CadError("Give center_elevation or create road.profile with vpis first")
        center_elevation = prof.elevation(float(station))
    tr = template or DEFAULT_TEMPLATE
    tl = template_left or tr
    if not terrain and not surface:
        raise CadError("Give terrain [[offset, z], ...] or a terrain surface name")
    sec = _section(ctx, al, float(station), float(center_elevation), tl, tr, cut_slope, fill_slope, terrain,
                   surface, half_width, _se_for(ctx, name, al, float(station), use_superelevation), pavement, ditch)
    created = _draw_section(ctx, insert, station, center_elevation, sec, text_height, scale, space)
    d = sec["surface"]
    return {"handles": created, "station": format_station(station), "center_elevation": round(center_elevation, 3),
            "cut_m2": round(sec["cut"], 3), "fill_m2": round(sec["fill"], 3),
            "lane_slopes_pct": None if sec["se"] is None else {"left": round(sec["se"][0], 3),
                                                               "right": round(sec["se"][1], 3)},
            "pavement": [{"name": la["name"], "area_m2": round(la["area_m2"], 4)} for la in sec["layers"]],
            "daylight": {"left": [round(c, 3) for c in d[0]], "right": [round(c, 3) for c in d[-1]]}}


def _draw_section(ctx, insert, station, cz, sec, th, scale, space):
    m = _m(ctx)
    lay = ctx.layout(space)
    ox, oy = (c / m for c in vec(insert).vec2)
    P = lambda o, z: ((ox + o * scale) * m, (oy + (z - cz) * scale) * m)  # noqa: E731
    a_t = _attribs(ctx, "KERESZT_TEREP", color=3)
    a_d = _attribs(ctx, "KERESZT_TERV", color=1)
    a_x = _attribs(ctx, "KERESZT_FELIRAT", color=7)
    out = [lay.add_lwpolyline([P(o, z) for o, z in sec["terrain"]], dxfattribs=a_t),
           lay.add_lwpolyline([P(o, z) for o, z in sec["surface"]], dxfattribs=a_d),
           lay.add_line(P(0, cz - 1.5), P(0, cz + 3), dxfattribs=a_x)]
    if sec["layers"]:
        a_f = _attribs(ctx, "KERESZT_FOLDMU", color=30)
        a_p = _attribs(ctx, "KERESZT_PALYASZERKEZET", color=8)
        out.append(lay.add_lwpolyline([P(o, z) for o, z in sec["formation"]], dxfattribs=a_f))
        for la in sec["layers"]:
            out.append(lay.add_lwpolyline([P(o, z) for o, z in la["outline"]], close=True, dxfattribs=a_p))
    h = th * m * scale
    texts = [(f"{format_station(station)}", 5.0), (f"Tengely: {cz:.2f}", 4.0),
             (f"Bevágás: {sec['cut']:.2f} m²   Töltés: {sec['fill']:.2f} m²", 3.0)]
    if sec["se"] is not None:
        texts.append((f"Keresztesés B: {sec['se'][0]:+.2f}%  J: {sec['se'][1]:+.2f}%", 2.0))
    for text, dy in texts:
        out.append(lay.add_text(text, height=h, dxfattribs=a_x).set_placement(
            P(0, cz + dy), align=_al("MIDDLE_CENTER")))
    for o, z in sec["surface"]:
        out.append(lay.add_text(f"{z:.2f}", height=h * 0.8, rotation=90, dxfattribs=a_d).set_placement(
            P(o, z + 0.3), align=_al("MIDDLE_LEFT")))
    if sec["layers"]:
        right = max(o for o, _ in sec["surface"])
        for i, la in enumerate(sec["layers"]):
            out.append(lay.add_text(f"{la['name']} {la['thickness'] * 100:.0f} cm", height=h * 0.7,
                                    dxfattribs=a_x).set_placement(P(right + 1, cz - 1.5 - i * 0.6),
                                                                  align=_al("MIDDLE_LEFT")))
    return [e.dxf.handle for e in out]


@op(T, "cross_sections", mutates=True)
def cross_sections(ctx: Ctx, name: str, insert, interval: float = 20.0, stations: list | None = None,
                   template: list | None = None, template_left: list | None = None, cut_slope: float = 1.5,
                   fill_slope: float = 1.5, surface: str | None = None, terrains: dict | None = None,
                   pavement: list | None = None, ditch: dict | None = None, use_superelevation: bool = True,
                   half_width: float = 30.0, columns: int = 4, spacing: list | None = None,
                   text_height: float = 0.5, space=None):
    """Series of cross sections in a grid with quantities by the average end area method: earthwork cut/fill (to the formation when pavement is given) and each pavement layer in m³. Terrain from a surface, or terrains={station: [[offset, z],...]}."""
    al, _ = get_alignment(ctx, name)
    prof, _d = get_profile(ctx, name)
    if prof is None:
        raise CadError("Create road.profile with vpis first (design elevations come from it)")
    sts = [float(s) for s in stations] if stations else [
        s for s in al.stations(interval) if prof.vpis[0][0] <= s <= prof.vpis[-1][0]]
    dx, dy = spacing or [2 * half_width + 10, 25]
    ox, oy = vec(insert).vec2
    m = _m(ctx)
    results, handles_all = [], []
    for i, s in enumerate(sts):
        terr = None
        if terrains:
            terr = terrains.get(str(s)) or terrains.get(str(int(s))) or terrains.get(s)
        sec = _section(ctx, al, s, prof.elevation(s), template_left or template or DEFAULT_TEMPLATE,
                       template or DEFAULT_TEMPLATE, cut_slope, fill_slope, terr, None if terr else surface,
                       half_width, _se_for(ctx, name, al, s, use_superelevation), pavement, ditch)
        at = (ox + (i % columns) * dx * m, oy - (i // columns) * dy * m)
        handles_all += _draw_section(ctx, at, s, prof.elevation(s), sec, text_height, 1.0, space)
        results.append({"station": s, "cut": sec["cut"], "fill": sec["fill"],
                        "layers": [la["area_m2"] for la in sec["layers"]]})
    vol_cut = vol_fill = 0.0
    vol_layers = [0.0] * len(pavement or [])
    for a, b in zip(results, results[1:]):
        d = b["station"] - a["station"]
        vol_cut += (a["cut"] + b["cut"]) / 2 * d
        vol_fill += (a["fill"] + b["fill"]) / 2 * d
        for k in range(len(vol_layers)):
            vol_layers[k] += (a["layers"][k] + b["layers"][k]) / 2 * d
    return {"handles": handles_all,
            "sections": [{"station": format_station(r["station"]), "cut_m2": round(r["cut"], 3),
                          "fill_m2": round(r["fill"], 3)} for r in results],
            "volume_cut_m3": round(vol_cut, 2), "volume_fill_m3": round(vol_fill, 2),
            "pavement_m3": {(pavement or [])[k].get("name", f"réteg {k + 1}"): round(v, 2)
                            for k, v in enumerate(vol_layers)}}
