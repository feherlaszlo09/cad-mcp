"""KÉ-K (közúti tervezés) completions: design parameter check against a rules table
(bundled e-UT 03.01.11 rule sets in assets/eut, or the designer's own), setting-out list (kitűzési jegyzék),
swept path analysis (fordulóív-vizsgálat), pavement markings (zebra, stop/give-way
lines, arrows, hatched areas), parking layouts, traffic signal heads, signal timing
plan (jelzésterv) and intergreen times (közbenső idő)."""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

from ezdxf.math import Vec2
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .core import CadError, Ctx, ensure_layer, handles, op, select_from, vec
from .ops_road import (
    DEFAULT_TEMPLATE,
    _m,
    _se_for,
    _seg_type,
    get_alignment,
    get_profile,
)
from .road_geom import format_station

T = "road"

# ---------------------------------------------------------------------------
# design parameter check
# ---------------------------------------------------------------------------

RULE_FIELDS = {
    "min_radius_m": "legkisebb körívsugár",
    "min_radius_without_superelevation_m": "legkisebb sugár túlemelés nélkül",
    "max_superelevation_pct": "legnagyobb túlemelés",
    "min_curve_length_m": "legrövidebb körív",
    "min_tangent_between_curves_m": "legrövidebb egyenes két ív között",
    "min_clothoid_A_ratio": "átmeneti ív: A / R legkisebb aránya (pl. 1/3)",
    "max_clothoid_A_ratio": "átmeneti ív: A / R legnagyobb aránya (pl. 1)",
    "max_grade_pct": "legnagyobb hosszesés",
    "min_grade_pct": "legkisebb hosszesés (vízelvezetés)",
    "min_crest_radius_m": "legkisebb domború lekerekítő sugár",
    "min_sag_radius_m": "legkisebb homorú lekerekítő sugár",
    "stopping_sight_distance_m": "megállási látótávolság",
    "min_clothoid_A_m": "legkisebb átmenetiív-paraméter (Pmin)",
    "clothoid_required_below_radius_m": "átmeneti ív kötelező az ennél kisebb sugarú ívek előtt és után",
    "min_deflection_deg": "legkisebb középponti szög (ennél kisebb ív nem tervezhető)",
    "small_deflection_deg": "kis középponti szög határa",
    "min_curve_length_small_deflection_m": "legrövidebb ívhossz kis középponti szögnél",
    "max_consecutive_radius_ratio": "egymást követő ívek sugarainak legnagyobb aránya",
    "max_relative_edge_grade_pct": "burkolatszél legnagyobb relatív hosszesése (túlemelés-kifuttatás)",
    "min_relative_edge_grade_pct": "burkolatszél legkisebb relatív hosszesése (túlemelés-kifuttatás)",
    "min_crest_radius_passing_m": "domború sugár az előzési látótávolsághoz (figyelmeztetés)",
    "passing_sight_distance_m": "előzési látótávolság",
}
PHYSICS_FIELDS = {
    "reaction_time_s": "reakcióidő",
    "deceleration_m_s2": "lassulás (vagy friction × 9,81)",
    "eye_height_m": "szemmagasság",
    "object_height_m": "akadály magassága",
}


@op(T, "design_rules_template")
def design_rules_template(ctx: Ctx, path: str, speeds: list | None = None):
    """Write an empty design-rules JSON (per design speed) to fill from the road design standard (e-UT); road.design_check uses it. Nothing is pre-filled on purpose."""
    speeds = speeds or [30, 40, 50, 60, 70, 80, 90, 100, 110, 130]
    data = {"source": "Töltsd ki a vonatkozó útügyi műszaki előírás (e-UT) táblázatai alapján",
            "fields": {**RULE_FIELDS, **PHYSICS_FIELDS},
            "design_speeds": {str(v): {k: None for k in RULE_FIELDS} for v in speeds},
            "physics": {k: None for k in PHYSICS_FIELDS}}
    p = ctx.resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"written": str(p), "speeds": speeds}


def _eut_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "eut"


def _rules_path(ctx: Ctx, rules_file: str) -> Path:
    """A path, or the name of a bundled rule set in assets/eut (e.g. 'eut_kulterulet')."""
    p = ctx.resolve(rules_file)
    if p.is_file():
        return p
    for cand in (_eut_dir() / rules_file, _eut_dir() / f"{rules_file}.json"):
        if cand.is_file():
            return cand
    bundled = sorted(f.stem for f in _eut_dir().glob("*.json")) if _eut_dir().is_dir() else []
    raise CadError(f"Rules file not found: {rules_file}. Bundled rule sets: {bundled}")


def _rules(ctx: Ctx, rules, rules_file, speed):
    r: dict = {}
    if rules_file:
        data = json.loads(_rules_path(ctx, rules_file).read_text(encoding="utf-8"))
        speeds = data.get("design_speeds", {})
        if str(int(speed)) not in speeds and speeds:
            raise CadError(f"Design speed {speed} is not in {rules_file}: {list(speeds)}")
        # general physics first, the per-speed table (which may also hold e.g. object_height_m) wins
        for part in (data.get("physics") or {}, speeds.get(str(int(speed))) or {}):
            r.update({k: v for k, v in part.items() if v is not None and not k.startswith("_")})
        if r and data.get("source"):
            r["_source"] = data["source"]
    r.update({k: v for k, v in (rules or {}).items() if v is not None})
    return r


@op(T, "design_rules_list")
def design_rules_list(ctx: Ctx):
    """List the bundled design rule sets (filled from the official e-UT road design standard, with page references) usable as road.design_check rules_file."""
    out = []
    for f in sorted(_eut_dir().glob("*.json")) if _eut_dir().is_dir() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"name": f.stem, "title": d.get("title"), "source": d.get("source"),
                    "design_speeds": list(d.get("design_speeds", {}))})
    return {"rule_sets": out}


def _check(results, name, ok, value, limit, where):
    results.append({"check": name, "status": "OK" if ok else "HIBA", "value": round(value, 4) if isinstance(value, float) else value,
                    "limit": limit, "where": where})


@op(T, "design_check", mutates=True)
def design_check(ctx: Ctx, name: str, design_speed: float, rules: dict | None = None, rules_file: str | None = None,
                 mark: bool = True, layer: str = "ELLENORZES", edge_offset: float | None = None):
    """Check an alignment (and its profile, superelevation) against design rules for the design speed: radii, radius without superelevation, superelevation, clothoid parameter and when a clothoid is required, central angle and curve length, consecutive radius ratio, superelevation runoff (relative edge grade, edge_offset = axis to pavement edge, default the lane width 3.5 m), tangent lengths, grades, vertical curve radii, and sight distance (stopping sight distance from the table or physics, and the crest radius it needs from eye/object heights; passing sight crest radius as a warning). Rules: rules_file = a bundled rule set filled from the official e-UT 03.01.11 standard (see road.design_rules_list: eut_kulterulet, eut_gyorsforgalmi, eut_belterulet) or your own file (road.design_rules_template), and/or rules={...}. Failures are marked in the drawing."""
    al, data = get_alignment(ctx, name)
    r = _rules(ctx, rules, rules_file, design_speed)
    if not r:
        raise CadError("No rule values: fill a rules file (road.design_rules_template) or pass rules={...}")
    v = float(design_speed) / 3.6
    res: list[dict] = []
    skipped = []
    se = (data.get("superelevation") or {}).get("curves", {})
    for i, c in enumerate(al.curves, 1):
        where = f"{i}. ív, ÍE {format_station(c.stations['IE'])}"
        if "min_radius_m" in r:
            _check(res, "körívsugár", c.radius >= r["min_radius_m"], c.radius, f">= {r['min_radius_m']}", where)
        if "min_radius_without_superelevation_m" in r and str(i) not in se:
            _check(res, "sugár túlemelés nélkül", c.radius >= r["min_radius_without_superelevation_m"], c.radius,
                   f">= {r['min_radius_without_superelevation_m']} (vagy legyen túlemelés)", where)
        if "max_superelevation_pct" in r and str(i) in se:
            e = se[str(i)]["e"]
            _check(res, "túlemelés", e <= r["max_superelevation_pct"], e, f"<= {r['max_superelevation_pct']}", where)
        if "min_curve_length_m" in r:
            _check(res, "körív hossza", c.arc_length >= r["min_curve_length_m"], c.arc_length,
                   f">= {r['min_curve_length_m']}", where)
        defl = abs(c.deflection_deg)
        if "min_deflection_deg" in r:
            _check(res, "középponti szög", defl >= r["min_deflection_deg"], defl, f">= {r['min_deflection_deg']}°", where)
        if "small_deflection_deg" in r and "min_curve_length_small_deflection_m" in r and defl < r["small_deflection_deg"]:
            total = c.stations.get("KV", c.stations["IV"]) - c.stations.get("KE", c.stations["IE"])
            _check(res, "ívhossz kis középponti szögnél", total >= r["min_curve_length_small_deflection_m"], total,
                   f">= {r['min_curve_length_small_deflection_m']} (szög < {r['small_deflection_deg']}°)", where)
        if "clothoid_required_below_radius_m" in r and c.radius < r["clothoid_required_below_radius_m"]:
            _check(res, "átmeneti ív szükséges", c.spiral_length > 0, "van" if c.spiral_length > 0 else "nincs",
                   f"R < {r['clothoid_required_below_radius_m']} esetén kötelező", where)
        if c.spiral_length > 0 and "min_clothoid_A_m" in r:
            _check(res, "átmenetiív-paraméter", c.spiral_param_A >= r["min_clothoid_A_m"], c.spiral_param_A,
                   f">= {r['min_clothoid_A_m']}", where)
        cs = se.get(str(i))
        if cs and ({"max_relative_edge_grade_pct", "min_relative_edge_grade_pct"} & set(r)):
            n = float((data.get("superelevation") or {}).get("normal", 2.5))
            L = c.spiral_length if c.spiral_length > 0 else float(cs.get("runoff") or 40.0)
            b = float(edge_offset) if edge_offset is not None else sum(
                float(sg["width"]) for k, sg in enumerate(DEFAULT_TEMPLATE) if _seg_type(sg, k) == "lane")
            rel = (n + float(cs["e"])) * b / L
            if "max_relative_edge_grade_pct" in r:
                _check(res, "burkolatszél relatív hosszesése (felső)", rel <= r["max_relative_edge_grade_pct"], rel,
                       f"<= {r['max_relative_edge_grade_pct']} (b={b} m, L={L:.1f} m)", where)
            if "min_relative_edge_grade_pct" in r:
                _check(res, "burkolatszél relatív hosszesése (alsó)", rel >= r["min_relative_edge_grade_pct"], rel,
                       f">= {r['min_relative_edge_grade_pct']} (b={b} m, L={L:.1f} m)", where)
        if c.spiral_length > 0:
            ratio = c.spiral_param_A / c.radius
            if "min_clothoid_A_ratio" in r:
                _check(res, "átmeneti ív A/R (alsó)", ratio >= r["min_clothoid_A_ratio"], ratio,
                       f">= {r['min_clothoid_A_ratio']}", where)
            if "max_clothoid_A_ratio" in r:
                _check(res, "átmeneti ív A/R (felső)", ratio <= r["max_clothoid_A_ratio"], ratio,
                       f"<= {r['max_clothoid_A_ratio']}", where)
    if "max_consecutive_radius_ratio" in r:
        for k, (a, b) in enumerate(zip(al.curves, al.curves[1:]), 1):
            q = max(a.radius, b.radius) / min(a.radius, b.radius)
            _check(res, "egymást követő ívek sugararánya", q <= r["max_consecutive_radius_ratio"], q,
                   f"<= {r['max_consecutive_radius_ratio']}", f"{k}-{k + 1}. ív, ÍE {format_station(b.stations['IE'])}")
    if "min_tangent_between_curves_m" in r:
        for a, b in zip(al.curves, al.curves[1:]):
            end_a = a.stations.get("KV", a.stations["IV"])
            start_b = b.stations.get("KE", b.stations["IE"])
            _check(res, "egyenes két ív között", start_b - end_a >= r["min_tangent_between_curves_m"],
                   start_b - end_a, f">= {r['min_tangent_between_curves_m']}",
                   f"{format_station(end_a)} - {format_station(start_b)}")
    prof, _pd = get_profile(ctx, name)
    if prof is not None:
        for (sa, _za), (sb, _zb), g in zip(prof.vpis, prof.vpis[1:], prof.grades):
            where = f"{format_station(sa)} - {format_station(sb)}"
            if "max_grade_pct" in r:
                _check(res, "hosszesés", abs(g) * 100 <= r["max_grade_pct"], abs(g) * 100, f"<= {r['max_grade_pct']}", where)
            if "min_grade_pct" in r:
                _check(res, "legkisebb hosszesés", abs(g) * 100 >= r["min_grade_pct"], abs(g) * 100,
                       f">= {r['min_grade_pct']}", where)
        for c in prof.curves:
            where = f"lekerekítés {format_station(c.station)}"
            key = "min_crest_radius_m" if c.kind == "crest" else "min_sag_radius_m"
            if key in r:
                _check(res, "domború sugár" if c.kind == "crest" else "homorú sugár", c.radius >= r[key], c.radius,
                       f">= {r[key]}", where)
            if c.kind == "crest" and "min_crest_radius_passing_m" in r:
                ok = c.radius >= r["min_crest_radius_passing_m"]
                res.append({"check": "előzési látótávolság a domború ívben", "status": "OK" if ok else "FIGYELEM",
                            "value": c.radius, "limit": f">= {r['min_crest_radius_passing_m']} (különben itt nincs előzési lehetőség)",
                            "where": where})
    else:
        skipped.append("hossz-szelvény (nincs road.profile vpis)")
    # physics: stopping sight distance and the crest radius it requires
    ssd = r.get("stopping_sight_distance_m")
    if ssd is None and {"reaction_time_s", "deceleration_m_s2"} <= set(r):
        ssd = v * r["reaction_time_s"] + v * v / (2 * r["deceleration_m_s2"])
    if ssd is not None:
        res.append({"check": "megállási látótávolság", "status": "INFO", "value": round(ssd, 2),
                    "limit": "fizikai képlet: v·t + v²/(2a)" if "stopping_sight_distance_m" not in r else "táblázat",
                    "where": f"{design_speed} km/h"})
    if "passing_sight_distance_m" in r:
        res.append({"check": "előzési látótávolság", "status": "INFO", "value": r["passing_sight_distance_m"],
                    "limit": "táblázat", "where": f"{design_speed} km/h"})
    if ssd is not None:
        if prof is not None and {"eye_height_m", "object_height_m"} <= set(r):
            h = (math.sqrt(r["eye_height_m"]) + math.sqrt(r["object_height_m"])) ** 2
            need = ssd * ssd / (2 * h)
            for c in prof.curves:
                if c.kind == "crest":
                    _check(res, "domború sugár a látótávolsághoz", c.radius >= need, c.radius,
                           f">= {need:.0f} (S²/(2(√h1+√h2)²))", f"lekerekítés {format_station(c.station)}")
    missing = [RULE_FIELDS.get(k, k) for k in RULE_FIELDS if k not in r]
    warnings = [x for x in res if x["status"] == "FIGYELEM"]
    fails = [x for x in res if x["status"] == "HIBA"]
    marked = []
    if mark and fails:
        ensure_layer(ctx.doc, layer)
        ctx.doc.layers.get(layer).color = 1
        m = _m(ctx)
        for f in fails:
            st = _station_from_where(f["where"])
            if st is None:
                continue
            x, y, _h = al.point_at(st)
            c = ctx.msp.add_circle((x * m, y * m), 8 * m, dxfattribs={"layer": layer})
            t = ctx.msp.add_text(f"{f['check']}: {f['value']} ({f['limit']})", height=2.5 * m, dxfattribs={"layer": layer})
            t.set_placement((x * m + 9 * m, y * m + 9 * m))
            marked += [c, t]
    return {"design_speed": design_speed, "rules_source": r.get("_source"), "checks": res, "failures": len(fails),
            "warnings": len(warnings), "not_checked": missing + skipped, "marked": handles(marked)}


def _station_from_where(text: str):
    import re

    m = re.search(r"(\d+)\+(\d+(?:\.\d+)?)", text)
    return int(m.group(1)) * 1000 + float(m.group(2)) if m else None


# ---------------------------------------------------------------------------
# setting-out list
# ---------------------------------------------------------------------------


def _z_at(ctx: Ctx, name: str, al, s: float, offset_right: float, template) -> float | None:
    prof, _d = get_profile(ctx, name)
    if prof is None or not (prof.vpis[0][0] <= s <= prof.vpis[-1][0]):
        return None
    se = _se_for(ctx, name, al, s, True)
    side = "right" if offset_right >= 0 else "left"
    lane = None if se is None else (se[1] if side == "right" else se[0])
    z, rest = prof.elevation(s), abs(offset_right)
    for i, seg in enumerate(template):
        w = float(seg["width"])
        slope = lane if (_seg_type(seg, i) == "lane" and lane is not None) else float(seg["slope"])
        step = min(w, rest)
        z += step * slope / 100
        rest -= step
        if rest <= 1e-9:
            break
    return z


@op(T, "setout_list", mutates=True)
def setout_list(ctx: Ctx, name: str, interval: float = 20.0, offsets: list | None = None, key_points: bool = True,
                path: str | None = None, table_at=None, template: list | None = None, decimals: int = 3,
                text_height: float = 2.0):
    """Setting-out list (kitűzési jegyzék): point number, station, offset (+ right), Y/X coordinates (drawing x/y, e.g. EOV) and design elevation (profile + cross slopes incl. superelevation) for the axis and offsets, every interval and at curve key points; CSV and/or table in the drawing."""
    al, _d = get_alignment(ctx, name)
    m = _m(ctx)
    offs = [0.0] + [float(o) for o in (offsets or []) if float(o) != 0.0]
    tmpl = template or DEFAULT_TEMPLATE
    sts = {round(s, 6): "" for s in al.stations(interval)}
    if key_points:
        for i, c in enumerate(al.curves, 1):
            for k, s in c.stations.items():
                sts[round(s, 6)] = f"{i}. ív {k.replace('IE', 'ÍE').replace('IV', 'ÍV')}"
    rows = []
    n = 1
    for s in sorted(sts):
        for o in offs:
            x, y, _h = al.point_at(s, -o)
            z = _z_at(ctx, name, al, s, o, tmpl)
            rows.append({"pont": n, "szelveny": format_station(s, 2), "eltolas": round(o, 3),
                         "Y": round(x * m, decimals), "X": round(y * m, decimals),
                         "Z": None if z is None else round(z, decimals), "megjegyzes": sts[s] if o == 0 else ""})
            n += 1
    out = {"points": len(rows), "rows": rows[:300]}
    if path:
        p = ctx.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
        p.write_text(buf.getvalue(), encoding="utf-8-sig")
        out["csv"] = str(p)
    if table_at is not None:
        from .ops_annotate import table

        hdr = ["Pont", "Szelvény", "Eltolás", "Y", "X", "Z", "Megjegyzés"]
        body = [[str(r["pont"]), r["szelveny"], f"{r['eltolas']:.2f}", f"{r['Y']:.{decimals}f}", f"{r['X']:.{decimals}f}",
                 "" if r["Z"] is None else f"{r['Z']:.{decimals}f}", r["megjegyzes"]] for r in rows]
        th = text_height * m
        t = table(ctx, insert=table_at, rows=[hdr] + body, row_height=th * 2.2, text_height=th,
                  col_widths=[th * 5, th * 9, th * 7, th * 12, th * 12, th * 8, th * 12], layer="KITUZES")
        out["table_handles"] = len(t["handles"])
    return out


# ---------------------------------------------------------------------------
# swept path analysis
# ---------------------------------------------------------------------------

# Typical vehicle dimensions (m). Check them against the design vehicle (mértékadó jármű) of the standard.
VEHICLES = {
    "szemelyauto": {"wheelbase": 2.7, "front_overhang": 0.9, "rear_overhang": 1.0, "width": 1.8},
    "kisteherauto": {"wheelbase": 3.7, "front_overhang": 1.0, "rear_overhang": 1.8, "width": 2.1},
    "tehergepkocsi": {"wheelbase": 6.0, "front_overhang": 1.4, "rear_overhang": 2.6, "width": 2.55},
    "autobusz": {"wheelbase": 6.0, "front_overhang": 2.7, "rear_overhang": 3.3, "width": 2.55},
    "nyerges": {"wheelbase": 3.8, "front_overhang": 1.4, "rear_overhang": 0.5, "width": 2.55,
                "kingpin_offset": 0.5, "trailer_wheelbase": 7.7, "trailer_front_overhang": 1.6,
                "trailer_rear_overhang": 4.2},
}


def _path_points(ctx: Ctx, path, path_handle, alignment, offset, step):
    if alignment:
        al, _d = get_alignment(ctx, alignment)
        m = _m(ctx)
        n = max(2, int(al.length / step))
        return [Vec2(al.point_at(al.start_station + al.length * i / n, offset)[:2]) * m for i in range(n + 1)]
    if path_handle:
        from . import geom

        shp = geom.to_shape(ctx.entity(path_handle))
    elif path:
        shp = LineString([tuple(vec(p).vec2) for p in path])
    else:
        raise CadError("Give path points, path_handle or alignment")
    n = max(2, int(shp.length / step))
    return [Vec2(shp.interpolate(shp.length * i / n).coords[0]) for i in range(n + 1)]


def _body(rear: Vec2, head: Vec2, back: float, front: float, half: float) -> Polygon:
    u = head
    nrm = Vec2(-u.y, u.x)
    a, b = rear - u * back, rear + u * front
    return Polygon([a + nrm * half, b + nrm * half, b - nrm * half, a - nrm * half])


@op(T, "swept_path", mutates=True)
def swept_path(ctx: Ctx, vehicle: str | dict = "tehergepkocsi", path=None, path_handle: str | None = None,
               alignment: str | None = None, offset: float = 0.0, step: float = 0.2, check=None,
               max_steering_deg: float | None = None, layer: str = "FORDULOIV", space=None):
    """Swept path (fordulóív-vizsgálat): the front axle centre drives along a path (points, a curve or an alignment with offset); the rear axle and a semi-trailer follow (tractrix). Draws the swept envelope and wheel tracks, reports the largest steering angle and where the envelope crosses the boundaries in `check` (e.g. kerb lines). vehicle = szemelyauto | kisteherauto | tehergepkocsi | autobusz | nyerges, or a dict of dimensions (wheelbase, front/rear_overhang, width; trailer: kingpin_offset, trailer_wheelbase, trailer_front/rear_overhang). Typical values: check against the standard's design vehicle."""
    veh = dict(VEHICLES[vehicle]) if isinstance(vehicle, str) else dict(vehicle)
    if isinstance(vehicle, str) and vehicle not in VEHICLES:
        raise CadError(f"vehicle: {list(VEHICLES)} or a dict")
    pts = _path_points(ctx, path, path_handle, alignment, offset, step)
    L, half = float(veh["wheelbase"]), float(veh["width"]) / 2
    a, b = float(veh["front_overhang"]), float(veh["rear_overhang"])
    d0 = (pts[1] - pts[0]).normalize()
    rear = pts[0] - d0 * L
    trailer = "trailer_wheelbase" in veh
    if trailer:
        c, L2 = float(veh["kingpin_offset"]), float(veh["trailer_wheelbase"])
        a2, b2 = float(veh["trailer_front_overhang"]), float(veh["trailer_rear_overhang"])
        t_rear = rear + d0 * c - d0 * L2
    bodies, front_outer, rear_inner, track_l, track_r = [], [], [], [], []
    max_steer = 0.0
    for i, f in enumerate(pts):
        rear = f - (f - rear).normalize() * L
        head = (f - rear).normalize()
        if i + 1 < len(pts):
            d = (pts[i + 1] - f).normalize()
            max_steer = max(max_steer, abs(math.degrees(math.atan2(head.x * d.y - head.y * d.x, head.dot(d)))))
        poly = _body(rear, head, b, L + a, half)
        nrm = Vec2(-head.y, head.x)
        track_l.append(f + nrm * half)
        track_r.append(f - nrm * half)
        front_outer.append(rear + nrm * half)
        rear_inner.append(rear - nrm * half)
        if trailer:
            k = rear + head * c
            t_rear = k - (k - t_rear).normalize() * L2
            th = (k - t_rear).normalize()
            poly = poly.union(_body(t_rear, th, b2, L2 + a2, half))
            tn = Vec2(-th.y, th.x)
            front_outer[-1] = t_rear + tn * half
            rear_inner[-1] = t_rear - tn * half
        if i % 2 == 0 or i == len(pts) - 1:
            bodies.append(poly)
    env = unary_union(bodies).buffer(0)
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    ctx.doc.layers.get(layer).color = 6
    created = []
    polys = list(env.geoms) if env.geom_type == "MultiPolygon" else [env]
    for pg in polys:
        created.append(lay.add_lwpolyline(list(pg.exterior.coords)[:-1], close=True, dxfattribs={"layer": layer}))
        for hole in pg.interiors:
            created.append(lay.add_lwpolyline(list(hole.coords)[:-1], close=True, dxfattribs={"layer": layer}))
    for tr in (track_l, track_r, front_outer, rear_inner):
        created.append(lay.add_lwpolyline([(q.x, q.y) for q in tr], dxfattribs={"layer": layer + "_KEREKNYOM"}))
    ensure_layer(ctx.doc, layer + "_KEREKNYOM")
    conflicts = []
    if check is not None:
        for e in select_from(ctx, check):
            from . import geom

            s = geom.to_shape(e)
            if s is None:
                continue
            inter = env.intersection(s)
            if not inter.is_empty:
                from shapely.geometry import Point

                coords = [c for g in getattr(inter, "geoms", [inter]) for c in getattr(g, "coords", [])]
                depth = max((env.exterior.distance(Point(c)) for c in coords), default=0.0)
                conflicts.append({"handle": e.dxf.handle, "length_inside_m": round(inter.length, 3),
                                  "max_depth_m": round(depth, 3)})
    out = {"handles": handles(created), "envelope_area_m2": round(env.area, 3),
           "max_steering_angle_deg": round(max_steer, 2), "conflicts": conflicts,
           "vehicle": veh}
    if max_steering_deg is not None:
        out["steering_ok"] = max_steer <= max_steering_deg
    return out


# ---------------------------------------------------------------------------
# pavement markings and parking
# ---------------------------------------------------------------------------


def _frame_at(ctx: Ctx, name: str, station: float):
    al, _d = get_alignment(ctx, name)
    x, y, h = al.point_at(float(station))
    m = _m(ctx)
    u = Vec2(math.cos(h), math.sin(h))
    return Vec2(x, y) * m, u, Vec2(-u.y, u.x), m


def _solid(lay, pts, layer):
    h = lay.add_hatch(color=7, dxfattribs={"layer": layer})
    h.paths.add_polyline_path([(p.x, p.y) for p in pts], is_closed=True)
    h.set_solid_fill(color=7)
    return h


@op(T, "crosswalk", mutates=True)
def crosswalk(ctx: Ctx, name: str, station: float, width: float = 4.0, from_offset: float = -3.5,
              to_offset: float = 3.5, stripe: float = 0.5, gap: float = 0.5, layer: str = "BURKOLATI_JEL", space=None):
    """Pedestrian crossing (zebra) across the road at a station: stripes parallel to the axis, crossing `width` long along the road, from_offset..to_offset across (+ left). Stripe/gap widths are parameters (check the marking standard)."""
    c, u, n, m = _frame_at(ctx, name, station)
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    created = []
    o = float(from_offset)
    while o + stripe <= float(to_offset) + 1e-9:
        p0 = c + n * (o * m) - u * (width / 2 * m)
        created.append(_solid(lay, [p0, p0 + u * (width * m), p0 + u * (width * m) + n * (stripe * m), p0 + n * (stripe * m)], layer))
        o += stripe + gap
    return {"handles": handles(created), "stripes": len(created)}


@op(T, "stop_line", mutates=True)
def stop_line(ctx: Ctx, name: str, station: float, from_offset: float, to_offset: float, kind: str = "stop",
              width: float = 0.5, dash: float = 0.5, gap: float = 0.5, layer: str = "BURKOLATI_JEL", space=None):
    """Stop line (kind=stop, solid) or give-way line (kind=give_way, dashed) across the lanes at a station between two offsets (+ left)."""
    c, u, n, m = _frame_at(ctx, name, station)
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    pieces = [(from_offset, to_offset)] if kind == "stop" else []
    if kind == "give_way":
        o = float(from_offset)
        while o < float(to_offset) - 1e-9:
            pieces.append((o, min(o + dash, to_offset)))
            o += dash + gap
    elif kind != "stop":
        raise CadError("kind: stop or give_way")
    created = []
    for o0, o1 in pieces:
        p0 = c + n * (o0 * m) - u * (width / 2 * m)
        created.append(_solid(lay, [p0, p0 + n * ((o1 - o0) * m), p0 + n * ((o1 - o0) * m) + u * (width * m), p0 + u * (width * m)], layer))
    return {"handles": handles(created)}


ARROWS = {
    "straight": [(0, 0), (0.15, 0), (0.15, 3.5), (0.45, 3.5), (0, 5.0), (-0.45, 3.5), (-0.15, 3.5), (-0.15, 0)],
    "left": [(0.15, 0), (0.15, 3.0), (-0.9, 3.0), (-0.9, 3.4), (-1.6, 2.85), (-0.9, 2.3), (-0.9, 2.7), (-0.15, 2.7), (-0.15, 0)],
    "right": [(-0.15, 0), (-0.15, 3.0), (0.9, 3.0), (0.9, 3.4), (1.6, 2.85), (0.9, 2.3), (0.9, 2.7), (0.15, 2.7), (0.15, 0)],
}


@op(T, "pavement_arrow", mutates=True)
def pavement_arrow(ctx: Ctx, name: str, station: float, offset: float, kind: str = "straight", scale: float = 1.0,
                   reverse: bool = False, layer: str = "BURKOLATI_JEL", space=None):
    """Direction arrow painted on the lane (straight, left, right, straight_left, straight_right) at a station/offset (+ left), pointing in the direction of travel (reverse=true for the opposite lane). Simplified shapes ~5 m long, scalable."""
    c, u, n, m = _frame_at(ctx, name, station)
    centre = c + n * (offset * m)  # offset + = left of the alignment direction
    d = -u if reverse else u       # arrow points along the traffic direction
    right = Vec2(d.y, -d.x)        # shape x > 0 = right of the arrow
    parts = {"straight_left": ["straight", "left"], "straight_right": ["straight", "right"]}.get(kind, [kind])
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    created = []
    for pk in parts:
        if pk not in ARROWS:
            raise CadError(f"kind: {list(ARROWS) + ['straight_left', 'straight_right']}")
        pts = [centre + d * (y * scale * m) + right * (x * scale * m) for x, y in ARROWS[pk]]
        created.append(_solid(lay, pts, layer))
    return {"handles": handles(created)}


@op(T, "hatched_area", mutates=True)
def hatched_area(ctx: Ctx, boundary=None, boundary_handle: str | None = None, spacing: float = 1.0, angle: float = 45.0,
                 stripe: float = 0.15, chevron: bool = False, layer: str = "BURKOLATI_JEL", space=None):
    """Area closed to traffic (záróvonallal határolt terület): outline plus parallel diagonal stripes (or chevrons) clipped to the area."""
    from shapely import affinity

    if boundary_handle:
        from . import geom

        shp = geom.to_shape(ctx.entity(boundary_handle))
        poly = Polygon(shp.coords)
    elif boundary:
        poly = Polygon([tuple(vec(p).vec2) for p in boundary])
    else:
        raise CadError("Give boundary points or boundary_handle")
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    created = [lay.add_lwpolyline(list(poly.exterior.coords)[:-1], close=True,
                                  dxfattribs={"layer": layer, "const_width": stripe})]
    minx, miny, maxx, maxy = poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    angles = [angle, -angle] if chevron else [angle]
    for ang in angles:
        k = -diag
        while k <= diag:
            ln = LineString([(cx - diag, cy + k), (cx + diag, cy + k)])
            ln = affinity.rotate(ln, ang, origin=(cx, cy))
            band = ln.buffer(stripe / 2, cap_style="flat").intersection(poly)
            for g in getattr(band, "geoms", [band]):
                if not g.is_empty and g.geom_type == "Polygon":
                    created.append(_solid(lay, [Vec2(q) for q in list(g.exterior.coords)[:-1]], layer))
            k += spacing
        if chevron:
            break
    return {"handles": handles(created), "stripes": len(created) - 1}


@op(T, "parking", mutates=True)
def parking(ctx: Ctx, path=None, path_handle: str | None = None, stall_width: float = 2.5, stall_length: float = 5.0,
            angle: float = 90.0, side: str = "left", count: int | None = None, numbering: bool = False,
            layer: str = "PARKOLO", space=None):
    """Parking stalls along a line (kerb or aisle edge): perpendicular (90), angled (e.g. 45, 60) or parallel (0); stall size, side, optional count and numbering. Draws the stall marking lines."""
    from . import geom

    if path_handle:
        shp = geom.to_shape(ctx.entity(path_handle))
    elif path:
        shp = LineString([tuple(vec(p).vec2) for p in path])
    else:
        raise CadError("Give path points or path_handle")
    m = _m(ctx)
    ang = math.radians(float(angle))
    along = stall_width / math.sin(ang) if angle else stall_length
    depth = stall_length * math.sin(ang) + (stall_width * math.cos(ang) if angle else 0) if angle else stall_width
    n_max = int(shp.length / (along * m))
    n = min(count, n_max) if count else n_max
    sgn = 1 if side == "left" else -1
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    created = []
    for i in range(n + 1):
        d = i * along * m
        p = Vec2(shp.interpolate(d).coords[0])
        q = Vec2(shp.interpolate(min(shp.length, d + 0.01 * m)).coords[0])
        u = (q - p).normalize() if q.distance(p) > 0 else Vec2(1, 0)
        nl = Vec2(-u.y, u.x) * sgn
        if angle:
            direction = (u * math.cos(ang) + nl * math.sin(ang)).normalize()
            created.append(lay.add_line(p, p + direction * (stall_length * m), dxfattribs={"layer": layer}))
        else:
            created.append(lay.add_line(p, p + nl * (stall_width * m), dxfattribs={"layer": layer}))
        if numbering and i < n:
            mid = Vec2(shp.interpolate(d + along * m / 2).coords[0]) + nl * (depth * m / 2)
            t = lay.add_text(str(i + 1), height=0.6 * m, dxfattribs={"layer": layer})
            from ezdxf.enums import TextEntityAlignment

            t.set_placement((mid.x, mid.y), align=TextEntityAlignment.MIDDLE_CENTER)
            created.append(t)
    if not angle and n:
        start = Vec2(shp.interpolate(0).coords[0])
        u0 = (Vec2(shp.interpolate(0.01 * m).coords[0]) - start).normalize()
        nl0 = Vec2(-u0.y, u0.x) * sgn
        end = Vec2(shp.interpolate(n * along * m).coords[0])
        created.append(lay.add_line(start + nl0 * (stall_width * m), end + nl0 * (stall_width * m), dxfattribs={"layer": layer}))
    return {"handles": handles(created), "stalls": n, "depth_m": round(depth, 3)}


# ---------------------------------------------------------------------------
# traffic signals
# ---------------------------------------------------------------------------


def _ensure_signal_block(ctx: Ctx, kind: str) -> str:
    name = f"JELZOFEJ_{kind.upper()}"
    if ctx.doc.blocks.get(name) is not None:
        return name
    lights = {"vehicle": [(1, 0, 0), (1, 0.8, 0), (0, 0.7, 0)], "pedestrian": [(1, 0, 0), (0, 0.7, 0)],
              "bicycle": [(1, 0, 0), (1, 0.8, 0), (0, 0.7, 0)], "arrow": [(1, 0, 0), (1, 0.8, 0), (0, 0.7, 0)]}.get(kind)
    if lights is None:
        raise CadError("kind: vehicle, pedestrian, bicycle, arrow")
    blk = ctx.doc.blocks.new(name, base_point=(0, 0))
    h = len(lights) * 0.4 + 0.1
    blk.add_lwpolyline([(-0.25, 0), (0.25, 0), (0.25, h), (-0.25, h)], close=True)
    for i, rgb in enumerate(lights):
        c = blk.add_circle((0, h - 0.25 - i * 0.4), 0.15)
        c.rgb = tuple(int(v * 255) for v in rgb)
    blk.add_line((0, 0), (0, -0.6))
    blk.add_attdef("CSOPORT", (0.35, h / 2), text="", dxfattribs={"height": 0.25})
    return name


@op(T, "signal_head", mutates=True)
def signal_head(ctx: Ctx, insert, group: str, kind: str = "vehicle", rotation: float = 0.0, size: float = 3.0,
                layer: str = "JELZOLAMPA", space=None):
    """Traffic signal head symbol (jelzőfej) with its signal group label: kind vehicle | pedestrian | bicycle | arrow."""
    bname = _ensure_signal_block(ctx, kind)
    ensure_layer(ctx.doc, layer)
    ref = ctx.layout(space).add_blockref(bname, vec(insert), dxfattribs={"layer": layer, "xscale": size, "yscale": size,
                                                                          "zscale": size, "rotation": float(rotation)})
    ref.add_auto_attribs({"CSOPORT": group})
    return {"handle": ref.dxf.handle}


@op(T, "intergreen", mutates=True)
def intergreen(ctx: Ctx, clearing_distance: float, entering_distance: float, clearing_speed_kmh: float,
               entering_speed_kmh: float, vehicle_length: float = 6.0, amber_time: float = 3.0):
    """Intergreen (közbenső) time between a clearing and an entering signal group: t = t_amber + (s_clear + l) / v_clear - s_enter / v_enter, rounded up to whole seconds. Distances to the conflict point in m; speeds and vehicle length per the design guideline."""
    vc, ve = clearing_speed_kmh / 3.6, entering_speed_kmh / 3.6
    t = amber_time + (clearing_distance + vehicle_length) / vc - entering_distance / ve
    return {"intergreen_s": math.ceil(max(t, 0.0) - 1e-9), "exact_s": round(t, 3)}


@op(T, "signal_timing", mutates=True)
def signal_timing(ctx: Ctx, cycle: float, groups: list, insert, intergreens: list | None = None, amber: float = 3.0,
                  red_amber: float = 1.0, scale: float = 1.0, row_height: float = 2.0, layer: str = "JELZESTERV",
                  space=None):
    """Signal timing plan (jelzésterv): bar chart over the cycle for each group [{name, green_start, green_end}] (s), with red-amber before and amber after green; checks the intergreen times given as [{from, to, required}] (from-group green end -> to-group green start)."""
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    ox, oy = vec(insert).vec2
    created = []
    W = cycle * scale

    def rect(t0, t1, row, rgb):
        y0 = oy - (row + 1) * row_height
        segs = [(t0, t1)] if t1 >= t0 else [(t0, cycle), (0, t1)]
        for a, b in segs:
            if b - a <= 0:
                continue
            h = lay.add_hatch(dxfattribs={"layer": layer})
            h.paths.add_polyline_path([(ox + a * scale, y0), (ox + b * scale, y0), (ox + b * scale, y0 + row_height * 0.7),
                                       (ox + a * scale, y0 + row_height * 0.7)], is_closed=True)
            h.set_solid_fill(color=7)
            h.rgb = rgb
            created.append(h)

    for i, g in enumerate(groups):
        gs, ge = float(g["green_start"]) % cycle, float(g["green_end"]) % cycle
        rect(ge, (ge + amber) % cycle, i, (255, 190, 0))
        rect((ge + amber) % cycle, (gs - red_amber) % cycle, i, (220, 0, 0))
        rect((gs - red_amber) % cycle, gs, i, (255, 120, 0))
        rect(gs, ge, i, (0, 170, 0))
        t = lay.add_text(str(g["name"]), height=row_height * 0.5, dxfattribs={"layer": layer})
        from ezdxf.enums import TextEntityAlignment

        t.set_placement((ox - row_height * 0.5, oy - (i + 1) * row_height + row_height * 0.35),
                        align=TextEntityAlignment.MIDDLE_RIGHT)
        created.append(t)
    n = len(groups)
    created.append(lay.add_lwpolyline([(ox, oy), (ox + W, oy), (ox + W, oy - (n + 0.3) * row_height),
                                       (ox, oy - (n + 0.3) * row_height)], close=True, dxfattribs={"layer": layer}))
    tick = 10 if cycle > 40 else 5
    s = 0
    while s <= cycle + 1e-9:
        created.append(lay.add_line((ox + s * scale, oy), (ox + s * scale, oy + row_height * 0.3), dxfattribs={"layer": layer}))
        txt = lay.add_text(f"{s:g}", height=row_height * 0.35, dxfattribs={"layer": layer})
        from ezdxf.enums import TextEntityAlignment

        txt.set_placement((ox + s * scale, oy + row_height * 0.4), align=TextEntityAlignment.BOTTOM_CENTER)
        created.append(txt)
        s += tick
    checks = []
    by_name = {str(g["name"]): g for g in groups}
    for ig in intergreens or []:
        a, b = by_name.get(str(ig["from"])), by_name.get(str(ig["to"]))
        if a is None or b is None:
            raise CadError(f"Unknown group in intergreen {ig}")
        actual = (float(b["green_start"]) - float(a["green_end"])) % cycle
        checks.append({"from": ig["from"], "to": ig["to"], "actual_s": round(actual, 2), "required_s": ig["required"],
                       "status": "OK" if actual >= float(ig["required"]) - 1e-9 else "HIBA"})
    return {"handles": handles(created), "intergreen_checks": checks,
            "failures": sum(1 for c in checks if c["status"] == "HIBA")}

