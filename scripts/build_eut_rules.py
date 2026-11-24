"""Build the bundled road design rule sets (assets/eut/*.json) for road.design_check.

Every number below was read from the official, currently valid
  e-UT 03.01.11:2008 (ÚT 2-1.201) Közutak tervezése (KTSZ)
published by Magyar Közút Nonprofit Zrt. at https://ume.kozut.hu/dokumentum/1490
(state of the online copy: published 2024. június). Page numbers are the printed
page numbers of the standard. Only numeric limit values are reproduced here; the
standard itself remains the authority (copyright: Magyar Közút Nonprofit Zrt.).
Fields the standard does not give as a number are left null on purpose.

Run:  python3 scripts/build_eut_rules.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "eut"
SOURCE = "e-UT 03.01.11:2008 (ÚT 2-1.201) Közutak tervezése (KTSZ), https://ume.kozut.hu/dokumentum/1490"

# 1.2. táblázat – Tervezési elemek szélső értékei a tervezési sebesség függvényében (10. o.)
SPEEDS = [30, 40, 50, 60, 70, 80, 90, 100, 110, 130]
T12 = {
    "min_radius_m": [25, 45, 80, 120, 180, 250, 340, 450, 600, 900],
    "min_clothoid_A_m": [21, 32, 48, 64, 85, 130, 165, 180, 220, 300],
    "max_grade_kulterulet": [11, 10, 9, 8, 7, 6, 6, 5.5, 5, 4],
    "max_grade_belterulet": [15, 14, 12, 10, 8, 7, 6, 5.5, 5, None],
    "min_crest_radius_m": [160, 350, 700, 1200, 2100, 3500, 5500, 8500, 9200, 15500],
    "min_crest_radius_passing_m": [11000, 13500, 16500, 20000, 25000, 30000, 40000, 50000, 65000, None],
    "min_sag_radius_m": [250, 500, 800, 1100, 1600, 2300, 3000, 3900, 5000, 8000],
    "max_relative_edge_grade_pct": [2.0, 2.0, 1.5, 1.5, 1.0, 0.5, 0.5, 0.5, 0.5, 0.3],  # = 1.4. táblázat (23. o.)
    "stopping_sight_distance_m": [25, 35, 50, 65, 85, 110, 140, 170, 210, 300],
    "passing_sight_distance_m": [300, 330, 360, 400, 440, 500, 560, 640, 700, None],
}
MAX_SUPERELEVATION = 7.0          # 1.2. táblázat qmax (10. o.); 3.7.2.3 (87. o.)
MIN_RELATIVE_EDGE_GRADE = 0.3     # 1.2. táblázat Δer,min; 1.4. táblázat (23. o.)
EYE_HEIGHT = 1.00                 # 1.6.2.1 (15. o.)
OBJECT_HEIGHT = {110: 0.30, 130: 0.50}  # 1.6.2.1 (15. o.), otherwise 0.10 m

# 3.3. táblázat – Túlemelés nélkül alkalmazható helyszínrajzi ívek legkisebb sugarai, külterület (87. o.)
NO_SE_KULTERULET = {90: 2500, 80: 2000, 70: 1500, 60: 1000, 50: 800, 40: 500, 30: 200}
# 2.2. táblázat – ugyanez gyorsforgalmi utakon (61. o.)
NO_SE_GYORS = {130: 5500, 120: 4100, 110: 3500, 100: 3000, 90: 2500, 80: 2000}
# 3.6.1.1 – klotoid átmeneti ív kell minden ív előtt és után, melynek sugara kisebb (81. o.)
CLOTHOID_KULTERULET = {90: 3000, 80: 2000, 70: 1500, 60: 1000, 50: 500}
# 2.6.1.1 – ugyanez gyorsforgalmi utak folyópályáján (58. o.)
CLOTHOID_GYORS = {130: 8000, 120: 6000, 110: 5000, 100: 4000, 90: 3500, 80: 3000}

REFS_COMMON = {
    "min_radius_m": "1.2. táblázat (10. o.)",
    "min_clothoid_A_m": "1.2. táblázat, Pmin (10. o.)",
    "max_grade_pct": "1.2. táblázat, emax (10. o.)",
    "min_crest_radius_m": "1.2. táblázat, Rd,min megállási látótávolság alapján (10. o.)",
    "min_crest_radius_passing_m": "1.2. táblázat, Rd,min előzési látótávolság alapján (10. o.)",
    "min_sag_radius_m": "1.2. táblázat, Rh,min (10. o.)",
    "max_superelevation_pct": "1.2. táblázat, qmax (10. o.)",
    "max_relative_edge_grade_pct": "1.2. táblázat, Δer,max és 1.4. táblázat (10., 23. o.)",
    "min_relative_edge_grade_pct": "1.2. táblázat, Δer,min és 1.4. táblázat (10., 23. o.)",
    "stopping_sight_distance_m": "1.2. táblázat, Lm,min (e = 0%) (10. o.); lejtőben 1.1. ábra (15. o.)",
    "passing_sight_distance_m": "1.2. táblázat, Le,min (10. o.)",
    "eye_height_m": "1.6.2.1 (15. o.)",
    "object_height_m": "1.6.2.1 (15. o.)",
}
NOTES_COMMON = [
    "A túlemelés értékét az 1.5. ábra (24. o.) alapján kell felvenni, fél százalékra felfelé kerekítve; a design_check csak a qmax = 7% felső határt ellenőrzi.",
    "Δer,min: 0,1% ha a burkolat-oldalesés iránya nem változik; 0,5% ha az úttengely hosszesése < 0,5% (1.4. táblázat megjegyzései, 23. o.). A fájl az alapértéket (0,3%) tartalmazza.",
    "A túlemelés-átmenet nulla százalékos keresztesésű pontjánál a hosszesés legalább 0,5% legyen (23. o.); általános legkisebb hosszesést az előírás nem ad, ezért min_grade_pct üres.",
    "Reakcióidőt és lassulást az előírás nem ad meg: a megállási látótávolság a táblázatból jön (stopping_sight_distance_m).",
    "Legrövidebb körív, legrövidebb egyenes két ív között és az A/R arány az előírásban nincs számszerűen megadva (a 10. tervezési útmutatóra hivatkozik), ezért üresek.",
]


def _col(speed: int):
    return SPEEDS.index(speed) if speed in SPEEDS else None


def _common(speed: int, grade_row: str) -> dict:
    i = _col(speed)
    get = (lambda k: T12[k][i]) if i is not None else (lambda k: None)
    return {
        "min_radius_m": get("min_radius_m"),
        "min_clothoid_A_m": get("min_clothoid_A_m"),
        "max_grade_pct": get(grade_row),
        "min_crest_radius_m": get("min_crest_radius_m"),
        "min_crest_radius_passing_m": get("min_crest_radius_passing_m"),
        "min_sag_radius_m": get("min_sag_radius_m"),
        "max_superelevation_pct": MAX_SUPERELEVATION if i is not None else None,
        "max_relative_edge_grade_pct": get("max_relative_edge_grade_pct"),
        "min_relative_edge_grade_pct": MIN_RELATIVE_EDGE_GRADE if i is not None else None,
        "stopping_sight_distance_m": get("stopping_sight_distance_m"),
        "passing_sight_distance_m": get("passing_sight_distance_m"),
        "object_height_m": OBJECT_HEIGHT.get(speed, 0.10) if i is not None else None,
        # not given numerically by the standard
        "min_curve_length_m": None,
        "min_tangent_between_curves_m": None,
        "min_clothoid_A_ratio": None,
        "max_clothoid_A_ratio": None,
        "min_grade_pct": None,
    }


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    sets = {}

    # --- külterületi közutak (3. fejezet: K.III–K.VI) ---
    ds = {}
    for v in [30, 40, 50, 60, 70, 80, 90]:
        d = _common(v, "max_grade_kulterulet")
        d.update({
            "min_radius_without_superelevation_m": NO_SE_KULTERULET.get(v),
            "clothoid_required_below_radius_m": CLOTHOID_KULTERULET.get(v),
            "small_deflection_deg": 3.0,
            "min_curve_length_small_deflection_m": 300.0,
            "max_consecutive_radius_ratio": 3.0,
            "min_deflection_deg": None,
        })
        ds[str(v)] = d
    sets["eut_kulterulet"] = {
        "title": "Külterületi közutak (K.III–K.VI) – e-UT 03.01.11 3. fejezet",
        "design_speeds": ds,
        "references": {**REFS_COMMON,
                       "max_grade_pct": "1.2. táblázat, emax külterület (10. o.)",
                       "min_radius_without_superelevation_m": "3.3. táblázat (87. o.)",
                       "clothoid_required_below_radius_m": "3.6.1.1 (81. o.)",
                       "small_deflection_deg": "3.6.1 (80. o.): α < 3° ívek kerülendők",
                       "min_curve_length_small_deflection_m": "3.6.1 (80. o.): legalább 300 m ívhossz",
                       "max_consecutive_radius_ratio": "3.6.1 (80. o.): arányuk az 1:2, 1:3 értéket ne haladja meg"},
        "notes": NOTES_COMMON + [
            "Egymást követő ívek sugararánya: a szöveg '1:2, 1:3' értéket ad; a fájl a megengedőbb 1:3-at tartalmazza, 1:2 a kívánatos.",
            "Hegyvidéki hajtűkanyarban a tervezési sebesség feléhez tartozó legkisebb sugár is alkalmazható, sebességkorlátozással (80. o.).",
            "Hegyvidéki utakon 100 m-es és kisebb sugarú ívekben a megengedett legnagyobb emelkedőt 30%-kal csökkenteni kell; csomópontokban 25%-kal, és 4%-nál nagyobb emelkedőbe nem kerülhetnek (81. o.).",
            "Síkvidéki főutak felüljáróinál az emelkedő legfeljebb 3% (81. o.).",
        ],
    }

    # --- gyorsforgalmi utak (2. fejezet: K.I, K.II, B.I, B.II) ---
    ds = {}
    for v in [80, 90, 100, 110, 120, 130]:
        d = _common(v, "max_grade_kulterulet")
        d.update({
            "min_radius_without_superelevation_m": NO_SE_GYORS.get(v),
            "clothoid_required_below_radius_m": CLOTHOID_GYORS.get(v),
            "min_deflection_deg": 3.0,
            "small_deflection_deg": None,
            "min_curve_length_small_deflection_m": None,
            "max_consecutive_radius_ratio": None,
        })
        ds[str(v)] = d
    sets["eut_gyorsforgalmi"] = {
        "title": "Gyorsforgalmi utak (autópálya, autóút) – e-UT 03.01.11 2. fejezet",
        "design_speeds": ds,
        "references": {**REFS_COMMON,
                       "max_grade_pct": "1.2. táblázat, emax külterület (10. o.)",
                       "min_radius_without_superelevation_m": "2.2. táblázat (61. o.)",
                       "clothoid_required_below_radius_m": "2.6.1.1 (58. o.)",
                       "min_deflection_deg": "2.6.1.1 (58. o.): 3 foknál kisebb középponti szögű ív nem tervezhető"},
        "notes": NOTES_COMMON + [
            "120 km/h: az 1.2. táblázatnak nincs 120-as oszlopa, ezért ott csak a 2.2. táblázat és a 2.6.1.1 értékei szerepelnek.",
            "Belterületi gyorsforgalmi úton (B.I, B.II) 80 km/h-nál az emax belterületi értéke 7% (a fájl a külterületi 6%-ot tartalmazza).",
            "Átmeneti ív választásánál A ≈ 0,55·R és 0,65·R közötti arány célszerű (58. o.) – ajánlás, nem határérték.",
            "Kapaszkodósáv kell, ha az emelkedés legalább 500 m hosszon eléri vagy meghaladja a 3%-ot (59. o.).",
        ],
    }

    # --- belterületi közutak (4. fejezet: B.III–B.VI) ---
    ds = {}
    for v in [30, 40, 50, 60, 70, 80]:
        d = _common(v, "max_grade_belterulet")
        d.update({
            "min_radius_without_superelevation_m": 0 if v < 40 else None,
            "clothoid_required_below_radius_m": None,
            "min_deflection_deg": None,
            "small_deflection_deg": None,
            "min_curve_length_small_deflection_m": None,
            "max_consecutive_radius_ratio": None,
        })
        ds[str(v)] = d
    sets["eut_belterulet"] = {
        "title": "Belterületi közutak (B.III–B.VI) – e-UT 03.01.11 4. fejezet",
        "design_speeds": ds,
        "references": {**REFS_COMMON,
                       "max_grade_pct": "1.2. táblázat, emax belterület (10. o.)",
                       "min_radius_without_superelevation_m": "4.7.2.3 (106. o.): vt < 40 km/h esetén nem kell túlemelés"},
        "notes": NOTES_COMMON + [
            "Új út, I. és II. rendű főút, 'a', 'b', 'c' funkció: ívekben az 1.5. ábra szerinti túlemelés kell; vt = 50 km/h-nál 2%-kal csökkenthető; vt = 40 km/h-nál az egyenesben alkalmazott oldalesés az ív közepe felé lejtve is jó (106. o.).",
            "Mellékutakon ('c', 'd', vt ≤ 50) átmeneti ív csak ott kell, ahol a körív-eltolás Δr > 0,2 m és a sáv ≤ 3,0 m; vt ≤ 40 km/h-nál átmeneti ív nélkül is tervezhető (98. o.).",
            "Mellékutakon 12%-nál nagyobb emelkedő kerülendő; 50 m-nél kisebb sugarú ívben a megengedett emelkedő 3 százalékponttal csökkentendő; csomópont 4%-nál nagyobb emelkedőbe ne kerüljön (98. o.).",
            "0,3%-nál kisebb hosszesésnél kiemelt szegély mentén a burkolatszél hossz-szelvényét 'hullámoztatni' kell (98. o.).",
        ],
    }

    for name, body in sets.items():
        data = {"source": SOURCE, **body,
                "physics": {"eye_height_m": EYE_HEIGHT, "object_height_m": None,
                            "reaction_time_s": None, "deceleration_m_s2": None}}
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("written", OUT / f"{name}.json", len(body["design_speeds"]), "speeds")


if __name__ == "__main__":
    build()
