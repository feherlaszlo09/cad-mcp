"""Switchable modules (kapcsolható modulok): which operations the MCP server shows to the model.

One server, one shared drawing, but only the tools of the enabled modules are listed, so the
model sees fewer, more relevant tools. Modules work at operation level, so the big `road` tool
can be split (road design / traffic engineering / road drainage). `alap` (2D drawing core) is
always on.

Choice at start (first that is set): the file <workdir>/.cad-mcp-modules.json saved by the
`modules` tool, the environment variable CAD_MCP_MODULES (modules and/or profiles, comma
separated, e.g. "kek" or "alap,geodezia,kozmu" or "mind"), otherwise every module."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import OPS

MODULES: dict[str, dict] = {
    "alap": {"title": "2D rajzolás (mindig be)", "tools": ["drawing", "draw", "edit", "query", "layer", "block",
                                                            "style", "layout", "view", "annotate"],
             "description": "Rajz megnyitása/mentése, rajzolás, szerkesztés, lekérdezés, rétegek, blokkok, stílusok, "
                            "layoutok, nyomtatás/kép, feliratozás és méretezés."},
    "halado": {"title": "Haladó 2D (ritkább parancsok)", "tools": [],
               "description": "Ritkább rajzoló-, szerkesztő-, feliratozó-, blokk-, réteg- és fájlműveletek: pl. "
                              "REVCLOUD, MLINE, WIPEOUT, alátétek, színátmenet, ALIGN, MATCHPROP, OVERKILL, STRETCH, "
                              "SPLINEDIT, 3D tömb, QDIM, tűréskeret, mezők, XCLIP, XREF-kezelés, rétegállapot és "
                              "-szűrő, LAYTRANS, eTransmit, PUBLISH, rendszerváltozók."},
    "3d": {"title": "3D testek", "tools": ["draw3d"],
           "description": "Doboz, henger, extrudálás, sweep, loft, valódi 3DSOLID, logikai műveletek, metszet, FLATSHOT."},
    "ut": {"title": "Útterv (KÉ-K)", "tools": ["road"],
           "description": "Nyomvonal, szelvényezés, hossz- és keresztszelvény, túlemelés, csomópont, körforgalom, "
                          "e-UT tervezési ellenőrzés, kitűzés, pályaszerkezet-méretezés."},
    "forgalomtechnika": {"title": "Forgalomtechnika", "tools": [],
                         "description": "Burkolati jelek, zebra, stopvonal, nyilak, parkolók, KRESZ-táblák, "
                                        "jelzőlámpák, jelzésterv, közbenső idők, fordulóív-vizsgálat."},
    "vizelvezetes": {"title": "Út víztelenítése", "tools": [],
                     "description": "Útárok, áteresz, árok- és csőkapacitás (Manning), lefolyó vízhozam."},
    "terep": {"title": "Terepmodell", "tools": ["terrain"],
              "description": "Geodéziai pontok importja, TIN felület, szintvonalak, terepszint."},
    "geo": {"title": "Georeferencia", "tools": ["geo"],
            "description": "EOV ↔ WGS84 (GPS) átszámítás, GIS-import, földrajzi hely, KML."},
    "geodezia": {"title": "Geodézia", "tools": ["survey"],
                 "description": "Sokszögvonal, poláris pontok, metszések, szintezés, transzformáció, DAT import, "
                                "kisajátítás, megvalósulási ellenőrzés."},
    "kozmu": {"title": "Közmű (VZ-TEL)", "tools": ["utility"],
              "description": "Csatornahálózat és hossz-szelvénye, vízhálózat-számítás, közművezetékek, "
                             "ütközésvizsgálat, közművek a keresztszelvényben."},
    "villamos": {"title": "Villamos és közvilágítás", "tools": ["electric"],
                 "description": "Közvilágítási oszlopkiosztás, fényeloszlás-fájlok (LDT, IES), megvilágításszámítás, "
                                "feszültségesés, egyvonalas jelképek és kapcsolási rajz."},
    "vasut": {"title": "Vasút (KÉ-VA alap)", "tools": ["rail"],
              "description": "Vasúti túlemelés ívenként, vágány alaprajzban, kitérő (pl. 54-190-1:9), ágyazatos "
                             "keresztszelvény."},
    "python": {"title": "Python vészkijárat", "tools": ["python"],
               "description": "Tetszőleges ezdxf Python-kód (csak CAD_MCP_ALLOW_PYTHON=1 mellett)."},
}
# operations of the road tool that belong to other modules
OP_MODULE = {("road", o): "forgalomtechnika" for o in (
    "marking", "crosswalk", "stop_line", "pavement_arrow", "hatched_area", "parking", "sign", "sign_at", "sign_types",
    "kresz_list", "kresz_sign", "kresz_sign_at", "signal_head", "signal_timing", "intergreen", "swept_path")}
OP_MODULE.update({("road", o): "vizelvezetes" for o in ("ditch", "ditch_capacity", "pipe_capacity", "culvert", "runoff")})

HALADO = {
    "drawing": ["import_resources", "etransmit", "convert_files", "wblock", "named_view", "ucs", "properties",
                "get_var", "set_var", "audit", "purge"],
    "draw": ["polyline3d", "xline", "ray", "solid", "donut", "wipeout", "image", "circle_ttr", "circle_ttt", "gradient",
             "underlay", "shape", "revcloud", "mline", "divide", "measure"],
    "edit": ["fillet_any", "offset_exact", "chamfer_angle", "chamfer_polyline", "fillet_polyline", "extend_arc_end",
             "lengthen_any", "join_same", "splinedit", "pedit_vertex", "pedit_spline", "hatchedit", "rotate3d",
             "mirror3d", "array3d", "array_block", "array_edit", "array_path", "matchprop", "overkill", "reverse",
             "align", "setbylayer", "group", "ungroup", "draworder", "stretch"],
    "query": ["extract", "similar", "groups", "massprop"],
    "layer": ["state", "filter", "translate", "merge", "check_standards"],
    "block": ["xclip", "bind_xref", "xref_manage", "edit_attdef", "sync_attributes", "import_svg", "attach_xref",
              "redefine"],
    "style": ["create_mleader_style", "create_mline_style"],
    "view": ["publish", "export_3d"],
    "annotate": ["qdim", "dim_space", "dim_break", "dim_jogged", "tolerance", "centerline", "leader_styled",
                 "mleader_align", "justify_text", "field", "dim_associate", "update_fields", "dim_ordinate",
                 "centermark", "scale_text"],
}
OP_MODULE.update({(t, o): "halado" for t, ops in HALADO.items() for o in ops})

# profiles are named after the Hungarian design licences (jogosultság) where it fits
PROFILES: dict[str, list[str]] = {
    "mind": list(MODULES),
    "kek": ["alap", "ut", "forgalomtechnika", "vizelvezetes", "terep", "geo"],
    "vztel": ["alap", "kozmu", "ut", "terep", "geo"],
    "geodeta": ["alap", "geodezia", "terep", "geo"],
    "kozvil": ["alap", "villamos", "ut", "terep", "geo"],
    "keva": ["alap", "vasut", "ut", "terep", "geo"],
    "rajz": ["alap", "halado", "3d"],
    "minimal": ["alap"],
}
PROFILE_TITLES = {"mind": "minden modul", "kek": "útügyi tervezés (KÉ-K)", "vztel": "közműtervezés (VZ-TEL)",
                  "geodeta": "geodézia, kisajátítás", "kozvil": "villamos és közvilágítás", "keva": "vasúti tervezés (KÉ-VA)", "rajz": "általános 2D/3D rajzolás minden paranccsal",
                  "minimal": "csak a 2D alap"}
ALWAYS = "alap"


def module_of(tool: str, op: str) -> str:
    if (tool, op) in OP_MODULE:
        return OP_MODULE[(tool, op)]
    for name, m in MODULES.items():
        if tool in m["tools"]:
            return name
    return ALWAYS


def ops_of(module: str) -> list[tuple[str, str]]:
    return [(t, o) for t in OPS for o in OPS[t] if module_of(t, o) == module]


def expand(names) -> set[str]:
    """Module set from module and profile names ('kek', 'alap,kozmu', 'mind'); unknown names raise ValueError."""
    if isinstance(names, str):
        names = [n for n in names.replace(";", ",").split(",")]
    out: set[str] = {ALWAYS}
    for n in names:
        n = n.strip().lower()
        if not n:
            continue
        if n in ("all", "*"):
            n = "mind"
        if n in PROFILES:
            out |= set(PROFILES[n])
        elif n in MODULES:
            out.add(n)
        else:
            raise ValueError(f"Unknown module or profile '{n}'. Modules: {list(MODULES)}; profiles: {list(PROFILES)}")
    return out


def settings_file(workdir: Path) -> Path:
    return Path(workdir) / ".cad-mcp-modules.json"


def initial(workdir: Path) -> tuple[set[str], str]:
    """Modules at start: the choice saved by the `modules` tool wins, then CAD_MCP_MODULES, then everything."""
    f = settings_file(workdir)
    if f.is_file():
        try:
            return expand(json.loads(f.read_text(encoding="utf-8")).get("modules", [])), str(f)
        except (ValueError, OSError):
            pass
    env = os.environ.get("CAD_MCP_MODULES")
    if env and env.strip():
        return expand(env), "CAD_MCP_MODULES"
    return set(MODULES), "alapértelmezés (minden modul)"


def save(workdir: Path, enabled: set[str]) -> Path:
    f = settings_file(workdir)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"modules": sorted(enabled)}, ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def op_line(tool: str, op: str) -> str:
    spec = OPS[tool][op]
    first = spec.summary.split("\n\n")[0].replace("\n", " ").strip()
    return f"- {spec.signature()}: {first}"


def tokens(module: str) -> int:
    """Rough size of the module's tool descriptions in tokens (≈ 4 characters per token)."""
    return sum(len(op_line(t, o)) for t, o in ops_of(module)) // 4
