"""Asphalt pavement design (útpályaszerkezet-méretezés) by the currently valid
  e-UT 06.03.14:2026 Aszfaltburkolatú útpályaszerkezetek méretezése és megerősítése
(Magyar Közút Nonprofit Zrt., https://ume.kozut.hu/dokumentum/2024, in force from 2026-04-15;
it replaces e-UT 06.03.13:2005, 06.03.12:2009 and 06.03.11:2010).

Implemented: design traffic MF (4.1-4.4 formulas, 4.1 design life), traffic load class
(4.1. táblázat), minimum subgrade design modulus (5.1. táblázat), type pavements with total
asphalt thickness (6.1-6.3. táblázat, interpolation rules of 6.2.1/6.2.2), cycle paths and
footways (6.4. táblázat), and for strengthening the representative and the allowed deflection
(7.5-7.8 formulas). Only numeric table values are reproduced, with page references; the
standard itself remains the authority (copyright: Magyar Közút Nonprofit Zrt.)."""

from __future__ import annotations

import math

from .core import CadError, Ctx, ensure_layer, handles, op, vec

T = "road"
SOURCE = "e-UT 06.03.14:2026 Aszfaltburkolatú útpályaszerkezetek méretezése és megerősítése, https://ume.kozut.hu/dokumentum/2024"

# 4.1. táblázat (17. o.): traffic load classes by MF (million unit axle passes)
CLASSES = [("A1", 0.0, 0.01), ("A2", 0.01, 0.03), ("A", 0.03, 0.1), ("B", 0.1, 0.3), ("C", 0.3, 1.0),
           ("D", 1.0, 3.0), ("E", 3.0, 10.0), ("K", 10.0, 30.0), ("R", 30.0, 100.0), ("R+", 100.0, math.inf)]
# 5.1. táblázat (18. o.): classes in which a subgrade design modulus E2m may be chosen
E2M_CLASSES = {40: {"A1", "A2", "A", "B", "C", "D"}, 60: {"C", "D", "E", "K", "R", "R+"},
               80: {"D", "E", "K", "R", "R+"}}
# 4.1 (13. o.): full design life, years
DESIGN_LIFE = {"gyorsforgalmi": 30, "fout": 20, "egyeb": 15}
# 4.2.2 (15. o.): heavy traffic factor n
N_FACTOR = {"gyorsforgalmi": 1.5, "fout": 1.2, "egyeb": 1.0}
# M1.1. táblázat (41. o.): vehicle conversion factors e_i; M1.2. táblázat: model categories
E_FACTORS = {"B": 1.3, "C1n+C2": 0.6, "D": 1.6, "E+F": 1.7, "busz": 1.3, "D3": 0.8, "D4": 1.7}

# Type pavement tables: thickness of all asphalt layers (mm) at the boundary MF values.
# Keys: "<0.01" (A1), boundary values 0.01 ... 100, ">100" (R+).
# (base, base thickness cm, E2m MPa, asphalt mix code of the lowest asphalt layer, values, page)
_RBA = "rugalmas burkolatalap (RBA)"
_SZ = "kötőanyag nélküli szemcsés alap (FZKA vagy M)"
_HK = "hidraulikus kötőanyagú stabilizáció"
TYPE_ROWS = [
    # 6.1. táblázat (20. o.) – RBA; not selectable in K, R, R+
    (_RBA, "15", 40, "N", {"<0.01": 40, 0.01: 50, 0.03: 80, 0.1: 100, 0.3: 110}, "6.1. táblázat (20. o.)"),
    (_RBA, "20", 40, "F", {0.3: 110, 1: 160, 3: 200}, "6.1. táblázat (20. o.)"),
    (_RBA, "20", 60, "F", {0.3: 100, 1: 150, 3: 190}, "6.1. táblázat (20. o.)"),
    (_RBA, "20", 60, "mF", {0.3: 90, 1: 130, 3: 160, 10: 210}, "6.1. táblázat (20. o.)"),
    (_RBA, "20", 80, "mF", {0.3: 90, 1: 120, 3: 150, 10: 200}, "6.1. táblázat (20. o.)"),
    (_RBA, "25", 60, "mF", {0.3: 80, 1: 110, 3: 140, 10: 190}, "6.1. táblázat (20. o.)"),
    # 6.2. táblázat (21. o.) – unbound granular base: FZKA thickness, or mechanical stabilisation (M)
    (_SZ, "15 FZKA vagy 20 M", 40, "N", {"<0.01": 60, 0.01: 80, 0.03: 110, 0.1: 130}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA vagy 25 M", 40, "N", {0.03: 100, 0.1: 120, 0.3: 140}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA vagy 25 M", 40, "F", {0.3: 140, 1: 180, 3: 210}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA vagy 25 M", 60, "F", {0.3: 130, 1: 170, 3: 200}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA vagy 25 M", 60, "mF", {0.3: 120, 1: 160, 3: 190, 10: 230}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA (M nem tervezhető)", 80, "mF", {3: 180, 10: 220}, "6.2. táblázat (21. o.), * megjegyzés"),
    (_SZ, "20 FZKA", 60, "mI", {10: 230, 30: 260, 100: 310, ">100": 320}, "6.2. táblázat (21. o.)"),
    (_SZ, "20 FZKA", 80, "mI", {10: 220, 30: 250, 100: 290, ">100": 300}, "6.2. táblázat (21. o.)"),
    # 6.3. táblázat (22. o.) – hydraulically bound base
    (_HK, "15", 40, "N", {"<0.01": 60, 0.01: 60, 0.03: 60, 0.1: 100, 0.3: 140}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 40, "F", {0.3: 140, 1: 190, 3: 230}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 60, "F", {0.3: 130, 1: 170, 3: 210}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 60, "mF", {0.3: 100, 1: 140, 3: 180, 10: 230}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 80, "mF", {1: 130, 3: 170, 10: 220}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 60, "mI", {10: 220, 30: 260, 100: 300, ">100": 310}, "6.3. táblázat (22. o.)"),
    (_HK, "15", 80, "mI", {10: 210, 30: 250, 100: 290, ">100": 300}, "6.3. táblázat (22. o.)"),
    (_HK, "20", 40, "F", {0.3: 120, 1: 170, 3: 210}, "6.3. táblázat (22. o.)"),
    (_HK, "20", 60, "F", {0.3: 110, 1: 150, 3: 190}, "6.3. táblázat (22. o.)"),
    (_HK, "20", 60, "mF", {0.3: 90, 1: 120, 3: 160, 10: 210}, "6.3. táblázat (22. o.)"),
    (_HK, "20", 80, "mF", {1: 110, 3: 150, 10: 200}, "6.3. táblázat (22. o.)"),
    (_HK, "20", 60, "mI", {10: 190, 30: 240, 100: 290, ">100": 300}, "6.3. táblázat (22. o.), * a 15 cm-es változat javasolt R, R+ osztályban"),
    (_HK, "20", 80, "mI", {10: 180, 30: 230, 100: 280, ">100": 290}, "6.3. táblázat (22. o.), * a 15 cm-es változat javasolt R, R+ osztályban"),
]
# 6.4. táblázat (23. o.) – cycle paths, footways
CYCLE_TABLE = [
    {"halozati_szerep": "kiemelt jelentőségű főhálózati elem", "burkolatalap": "RBA vagy M vagy FZKA",
     "E2m_min_MPa": 40, "aszfalt": "kétrétegű"},
    {"halozati_szerep": "főhálózati elem", "burkolatalap": "RBA vagy M vagy FZKA", "E2m_min_MPa": 30,
     "aszfalt": "az A1 forgalmi terhelési osztálynak megfelelő"},
    {"halozati_szerep": "nem főhálózati elem vagy járda", "burkolatalap": "15 cm RBA", "E2m_min_MPa": 30,
     "aszfalt": "legalább 40 mm egyrétegű"},
    {"halozati_szerep": "nem főhálózati elem vagy járda", "burkolatalap": "15 cm M vagy FZKA", "E2m_min_MPa": 30,
     "aszfalt": "legalább 50 mm, egy- vagy kétrétegű"},
    {"halozati_szerep": "nem főhálózati elem vagy járda", "burkolatalap": "15 cm hidraulikus kötőanyagú",
     "E2m_min_MPa": 30, "aszfalt": "legalább 60 mm, egy- vagy kétrétegű"},
]
NOTES = [
    "Az aszfalt-összvastagságot az e-UT 06.03.21 szerint kell rétegekre bontani (kopó-, kötő-, alapréteg).",
    "Az aszfaltkeverék-jelzet ((N), (F), (mF), (mI)) a legalsó aszfaltrétegre vonatkozik, átlagos igénybevételnél (6.2.2, 20. o.).",
    "Interpoláció a táblázat két határértéke között, lineárisan az MF-ben (a módját az előírás nem részletezi), 5 mm-re felfelé kerekítve; csak ha az MF az osztály alsó határát 10%-nál jobban meghaladja (6.2.1, 19. o.).",
    "Interpoláció nélkül az osztály felső határához tartozó vastagság kell; ha az MF az alsó határt legfeljebb 10%-kal haladja meg, az alsó határhoz tartozó is elég (6.2.2, 20. o.).",
    "Rugalmas burkolatalap (RBA) K, R, R+ osztályban nem választható (6.3, 20. o.); mechanikai stabilizáció (M) csak A1–E osztályban, E-ben 80 MPa-nál nem (6.4.1, 21. o.); C1,5/2 hidraulikus keverék legfeljebb D osztályig (6.5, 22. o.).",
    "Teljes aszfalt típus-pályaszerkezet új építésnél nem választható (6.1, 19. o.).",
]


def traffic_class(mf_million: float) -> tuple[str, float, float]:
    for name, lo, hi in CLASSES:
        if name == "R" and lo <= mf_million <= hi:
            return name, lo, hi
        if lo <= mf_million < hi and name != "R+":
            return name, lo, hi
    return "R+", 100.0, math.inf


def _round_up_5(x: float) -> int:
    return int(math.ceil(x / 5.0 - 1e-9) * 5)


def thickness(values: dict, cls: str, lo: float, hi: float, mf: float, interpolate: bool):
    """Asphalt thickness of one type-pavement row for MF (million) in class cls, or None if the row does not cover it."""
    if cls == "A1":
        return (values["<0.01"], "A1 osztály egyetlen értéke") if "<0.01" in values else None
    if cls == "R+":
        return (values[">100"], "R+ osztály egyetlen értéke") if ">100" in values else None
    if lo not in values or hi not in values:
        return None
    v_lo, v_hi = values[lo], values[hi]
    if mf <= 1.1 * lo:
        return v_lo, "az MF az alsó határt legfeljebb 10%-kal haladja meg: alsó határhoz tartozó érték"
    if not interpolate:
        return v_hi, "interpoláció nélkül: felső határhoz tartozó érték"
    v = v_lo + (v_hi - v_lo) * (mf - lo) / (hi - lo)
    return _round_up_5(v), f"interpoláció {v_lo}–{v_hi} mm között, 5 mm-re felfelé kerekítve"


def design_traffic(anet=None, anf: dict | None = None, road: str = "egyeb", years: float | None = None,
                   n: float | None = None, r: float = 0.5, s: float = 1.0, w: float = 0.9, m: float = 1.0,
                   count_accuracy_pct: float | None = None, growth_factor: float | None = None) -> dict:
    if growth_factor is None:
        raise CadError("Give growth_factor (f_N, forgalomfejlődési szorzó of all heavy vehicles at year t/2, "
                       "rounded up, by e-UT 02.01.31)")
    if road not in DESIGN_LIFE:
        raise CadError(f"road must be one of {list(DESIGN_LIFE)}")
    t = float(years) if years is not None else DESIGN_LIFE[road]
    if years is not None and years < DESIGN_LIFE[road] / 2:
        raise CadError(f"Partial design life must be at least half of the full life ({DESIGN_LIFE[road] / 2} years, 4.1)")
    nn = float(n) if n is not None else N_FACTOR[road]
    mm = 1.0 + float(count_accuracy_pct) / 200.0 if count_accuracy_pct is not None else float(m)
    if anet is not None:
        anet_v = float(anet)
        formula = "4.2: MF = 1,25·365·n·t·f_N·ÁNET"
        detail = None
    elif anf:
        bad = [k for k in anf if k not in E_FACTORS]
        if bad:
            raise CadError(f"Unknown vehicle classes {bad}; use {list(E_FACTORS)} (M1.1/M1.2 táblázat)")
        weighted = sum(float(v) * E_FACTORS[k] for k, v in anf.items())
        anet_v = float(r) * float(s) * float(w) * mm * weighted
        formula = "4.1/4.3: MF = 1,25·365·n·t·r·s·w·m·f_N·Σ(ÁNF_i·e_i)"
        detail = {k: {"ANF": float(v), "e_i": E_FACTORS[k], "Et_per_day": round(float(v) * E_FACTORS[k], 3)}
                  for k, v in anf.items()}
    else:
        raise CadError("Give anet (ÁNET, unit axles/day in the design lane, one direction) or anf={class: vehicles/day}")
    mf = 1.25 * 365.0 * nn * t * float(growth_factor) * anet_v
    cls, lo, hi = traffic_class(mf / 1e6)
    out = {"MF_Et": round(mf), "MF_million": round(mf / 1e6, 4), "traffic_class": cls,
           "class_range_million": [lo, None if math.isinf(hi) else hi], "formula": formula,
           "factors": {"t_years": t, "n": nn, "f_N": float(growth_factor), "ANET": round(anet_v, 3)}}
    if anet is None:
        out["factors"].update({"r": float(r), "s": float(s), "w": float(w), "m": round(mm, 4)})
        out["vehicles"] = detail
    if cls in ("E", "K", "R", "R+"):
        out["note"] = ("E vagy nagyobb osztálynál a számított MF-et össze kell vetni a tényleges forgalomfejlődéssel "
                       "(utolsó 5 év adatai); 50%-nál nagyobb eltérésnél egyedi forgalmi vizsgálat kell (4.2.1, 14. o.).")
    return out


@op(T, "pavement_design", mutates=True)
def pavement_design(ctx: Ctx, growth_factor: float | None = None, anet: float | None = None, anf: dict | None = None,
                    road: str = "egyeb", years: float | None = None, n: float | None = None, r: float = 0.5,
                    s: float = 1.0, w: float = 0.9, m: float = 1.0, count_accuracy_pct: float | None = None,
                    mf_million: float | None = None, e2m: float | None = None, base: str | None = None,
                    interpolate: bool = True, kind: str = "ut", insert=None, layer: str = "PALYASZERKEZET",
                    text_height: float = 0.05):
    """Asphalt pavement design by the valid e-UT 06.03.14:2026: design traffic MF from ÁNET (anet) or vehicle classes (anf={"B": buses/day, "C1n+C2": heavy lorries, "D": lorries with trailer, "E+F": articulated/special; or model "busz","D3","D4"}) with design life by road ('gyorsforgalmi' 30, 'fout' 20, 'egyeb' 15 years), heavy-traffic factor n, direction r, lane s, wheel-wander w, count accuracy m (or count_accuracy_pct p), growth factor f_N (e-UT 02.01.31, required); or give mf_million directly. Returns the traffic load class (A1…R+), the minimum subgrade modulus E2m allowed (5.1), and every type pavement (RBA, unbound granular FZKA/M, hydraulically bound base) with its total asphalt thickness for the class (interpolated by the standard's rules), optionally filtered by e2m and base ('rba', 'szemcses', 'hidraulikus'). The first variant also comes as `pavement` layers usable by road.cross_sections; insert=[x, y] draws the layer column. kind='kerekpar' lists the cycle path / footway table (6.4)."""
    if kind == "kerekpar":
        return {"source": SOURCE, "table": "6.4. táblázat (23. o.)", "variants": CYCLE_TABLE,
                "note": "Ha 3,5 t-nál nehezebb jármű is használja vagy keresztezi, a méretezési forgalomnak (legalább A1) megfelelő pályaszerkezet kell (23. o.)."}
    if mf_million is not None:
        mf = float(mf_million)
        cls, lo, hi = traffic_class(mf)
        res = {"MF_Et": round(mf * 1e6), "MF_million": mf, "traffic_class": cls,
               "class_range_million": [lo, None if math.isinf(hi) else hi]}
    else:
        res = design_traffic(anet, anf, road, years, n, r, s, w, m, count_accuracy_pct, growth_factor)
        mf = res["MF_million"]
        cls, lo, hi = traffic_class(mf)
    want_base = {"rba": _RBA, "szemcses": _SZ, "hidraulikus": _HK}.get((base or "").lower()) if base else None
    if base and want_base is None:
        raise CadError("base must be rba, szemcses or hidraulikus")
    variants = []
    for b, bt, mod, mix, vals, ref in TYPE_ROWS:
        if want_base and b != want_base:
            continue
        if e2m is not None and mod != float(e2m):
            continue
        got = thickness(vals, cls, lo, hi, mf, interpolate)
        if got is None:
            continue
        mm_, how = got
        variants.append({"burkolatalap": b, "burkolatalap_vastagsag_cm": bt, "E2m_MPa": mod, "aszfaltkeverek": f"({mix})",
                         "aszfalt_osszvastagsag_mm": mm_, "E2m_valaszthato_5_1": cls in E2M_CLASSES[mod],
                         "meghatarozas": how, "forras": ref})
    variants.sort(key=lambda v: (not v["E2m_valaszthato_5_1"], v["aszfalt_osszvastagsag_mm"]))
    res.update({"source": SOURCE, "min_E2m_MPa": min(k for k, v in E2M_CLASSES.items() if cls in v),
                "E2m_choices_MPa": sorted(k for k, v in E2M_CLASSES.items() if cls in v),
                "variants": variants, "notes": NOTES})
    if not variants:
        res["warning"] = "Nincs a feltételeknek megfelelő típus-pályaszerkezet (más alapréteg vagy E2m kell)."
        return res
    best = variants[0]
    base_cm = float(str(best["burkolatalap_vastagsag_cm"]).split()[0])
    res["pavement"] = [
        {"name": f"Aszfaltrétegek {best['aszfaltkeverek']} (bontás: e-UT 06.03.21)", "thickness": best["aszfalt_osszvastagsag_mm"] / 1000},
        {"name": f"{best['burkolatalap']} {best['burkolatalap_vastagsag_cm']} cm", "thickness": base_cm / 100},
    ]
    if insert is not None:
        res["handles"] = _draw_column(ctx, vec(insert), res, best, layer, float(text_height))
    return res


def _draw_column(ctx: Ctx, at, res, best, layer: str, th: float):
    """Layer column of the chosen pavement (1 m wide, true scale in metres), with labels."""
    ensure_layer(ctx.doc, layer)
    msp = ctx.msp
    x0, y = at.x, at.y
    out = []
    fills = [("ANSI31", 0.02), ("GRAVEL", 0.05)]
    for (lay, (pat, scale)) in zip(res["pavement"], fills):
        h = float(lay["thickness"])
        pts = [(x0, y), (x0 + 1, y), (x0 + 1, y - h), (x0, y - h)]
        out.append(msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer}))
        ha = msp.add_hatch(dxfattribs={"layer": layer})
        ha.paths.add_polyline_path(pts, is_closed=True)
        ha.set_pattern_fill(pat, scale=scale)
        out.append(ha)
        t = msp.add_text(f"{lay['name']}: {lay['thickness'] * 100:g} cm", height=th, dxfattribs={"layer": layer})
        t.set_placement((x0 + 1.1, y - h / 2 - th / 2))
        out.append(t)
        y -= h
    t = msp.add_text(f"Földmű E2m >= {best['E2m_MPa']} MPa", height=th, dxfattribs={"layer": layer})
    t.set_placement((x0 + 1.1, y - 1.5 * th))
    out.append(t)
    t = msp.add_text(f"{res['traffic_class']} forgalmi terhelési osztály, MF = {res['MF_million']} millió Et",
                     height=th, dxfattribs={"layer": layer})
    t.set_placement((x0, at.y + th))
    out.append(t)
    return handles(out)


# 7.2.1.4–7.2.1.5 (34–35. o.): strengthening of existing pavements by deflection measurements
SENG_CONST = {"kulonosen_hajlekony": (25.0, 4.00), "hajlekony": (14.5, 4.55), "felig_merev": (9.0, 5.00)}


@op(T, "pavement_strengthening")
def pavement_strengthening(ctx: Ctx, deflections: list, pavement_type: str, mf_million: float | None = None,
                           base: str = "szemcses", growth_factor: float | None = None, anet: float | None = None,
                           anf: dict | None = None, road: str = "egyeb", years: float | None = None):
    """Strengthening check of an existing asphalt pavement by e-UT 06.03.14:2026 7.2: deflections = corrected static deflections (mm) of one homogeneous section; representative deflection s_m = mean + u·std (u by class and number of points, 7.5–7.7), allowed deflection s_eng = a·N^(-1/b) (7.8; pavement_type kulonosen_hajlekony / hajlekony / felig_merev, minimum 0,30 mm hydraulic or 0,35 mm granular base). MF from mf_million or the same traffic inputs as road.pavement_design. The overlay thickness Δh itself is read from figure 7.2 of the standard."""
    d = [float(x) for x in deflections]
    if len(d) < 10:
        raise CadError("At least 10 measured deflections are needed (7.2.1.4)")
    if pavement_type not in SENG_CONST:
        raise CadError(f"pavement_type must be one of {list(SENG_CONST)}")
    if mf_million is None:
        tr = design_traffic(anet, anf, road, years, None, 0.5, 1.0, 0.9, 1.0, None, growth_factor)
        mf_million = tr["MF_million"]
    cls, _lo, _hi = traffic_class(float(mf_million))
    n = len(d)
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    high = cls in ("D", "E", "K", "R", "R+")
    if n >= 30:
        u = 1.64 if high else 1.28
    else:
        u = 1.8 if high else 1.4
    sm = mean + u * sd
    N = float(mf_million) * 1e6
    used_type = pavement_type
    if pavement_type == "kulonosen_hajlekony" and N > 400_000:
        used_type = "hajlekony"  # 34. o.: above 400 thousand Et the flexible (middle) curve applies
    a, b = SENG_CONST[used_type]
    seng_formula = a * N ** (-1.0 / b)
    floor = 0.30 if base == "hidraulikus" else 0.35
    seng = max(seng_formula, floor)
    cv = sd / mean if mean else 0.0
    out = {"source": SOURCE, "traffic_class": cls, "MF_million": float(mf_million), "points": n,
           "mean_mm": round(mean, 4), "std_mm": round(sd, 4), "u": u, "s_m_mm": round(sm, 4),
           "s_eng_formula_mm": round(seng_formula, 4), "s_eng_mm": round(seng, 4),
           "strengthening_needed": sm > seng,
           "note": "Az erősítőréteg Δh vastagságát a 7.2. ábra görbéiből kell leolvasni (s_m és s_eng alapján), 5 mm-re felfelé kerekítve; 5 mm alatt fenntartási beavatkozás (e-UT 08.02.12 / 06.03.63) tervezhető (35. o.)."}
    if cv >= 0.5:
        out["warning"] = f"A behajlások variációs tényezője {cv:.2f} >= 0,50: a homogén szakaszt tovább kell bontani (7.2.1.3, 33. o.)."
    if seng_formula < floor:
        out["s_eng_note"] = f"A 7.8 szerinti érték kisebb a {floor} mm-es alsó korlátnál, ezért {floor} mm (35. o.)."
    if used_type != pavement_type:
        out["s_eng_curve"] = "hajlekony (400 ezer Et felett a különösen hajlékony pályán is ez a görbe érvényes, 34. o.)"
    return out
