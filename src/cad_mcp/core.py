"""Core building blocks: operation registry, open drawings, argument parsing,
selection and entity description. Every tool module builds on this file."""

from __future__ import annotations

import inspect
import io
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import ezdxf
from ezdxf import bbox, units as ezunits
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic
from ezdxf.layouts import BaseLayout
from ezdxf.math import Vec3
from mcp.server.mcpserver.exceptions import ToolError


class CadError(ToolError):
    """An error whose message is shown to the model as-is (MCP ToolError)."""


# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------


@dataclass
class OpSpec:
    tool: str
    name: str
    fn: Callable[..., Any]
    mutates: bool
    summary: str

    def signature(self) -> str:
        params = []
        for p in list(inspect.signature(self.fn).parameters.values())[1:]:
            if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
                continue
            if p.default is inspect.Parameter.empty:
                params.append(p.name)
            else:
                params.append(f"{p.name}={p.default!r}")
        return f"{self.name}({', '.join(params)})"


OPS: dict[str, dict[str, OpSpec]] = {}


def op(tool: str, name: str, *, mutates: bool = False):
    """Register ``fn(ctx, **args)`` as operation ``name`` of tool ``tool``."""

    def deco(fn):
        doc = inspect.getdoc(fn) or ""
        OPS.setdefault(tool, {})[name] = OpSpec(tool, name, fn, mutates, doc)
        return fn

    return deco


def call_op(ctx: "Ctx", tool: str, operation: str, args: dict | None) -> Any:
    ops = OPS.get(tool)
    if ops is None:
        raise CadError(f"Unknown tool '{tool}'. Tools: {', '.join(sorted(OPS))}")
    spec = ops.get(operation)
    if spec is None:
        raise CadError(
            f"Unknown operation '{operation}' for tool '{tool}'. "
            f"Operations: {', '.join(sorted(ops))}"
        )
    args = dict(args or {})
    params = inspect.signature(spec.fn).parameters
    accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())
    if not accepts_kwargs:
        unknown = [k for k in args if k not in params or k == "ctx"]
        if unknown:
            raise CadError(
                f"{tool}.{operation}: unknown argument(s) {unknown}. "
                f"Signature: {spec.signature()}"
            )
    missing = [
        n
        for n, p in list(params.items())[1:]
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
        and n not in args
    ]
    if missing:
        raise CadError(
            f"{tool}.{operation}: missing argument(s) {missing}. "
            f"Signature: {spec.signature()}"
        )
    return spec.fn(ctx, **args)


def describe_tool(tool: str, header: str) -> str:
    lines = [header.strip(), "", "Operations:"]
    for spec in OPS[tool].values():
        first = spec.summary.split("\n\n")[0].replace("\n", " ").strip()
        lines.append(f"- {spec.signature()}: {first}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Open drawings
# ---------------------------------------------------------------------------

UNDO_LEVELS = int(os.environ.get("CAD_MCP_UNDO_LEVELS", "30"))


def default_workdir() -> Path:
    env = os.environ.get("CAD_MCP_WORKDIR")
    path = Path(env).expanduser() if env else Path.home() / "Documents" / "CAD-MCP"
    return path


@dataclass
class DocState:
    name: str
    doc: Drawing
    path: Path | None = None
    dirty: bool = False
    undo: list[str] = field(default_factory=list)
    redo: list[str] = field(default_factory=list)

    def snapshot(self) -> str:
        stream = io.StringIO()
        self.doc.write(stream)
        return stream.getvalue()

    def push_undo(self) -> None:
        if UNDO_LEVELS <= 0:
            return
        self.undo.append(self.snapshot())
        if len(self.undo) > UNDO_LEVELS:
            self.undo.pop(0)
        self.redo.clear()

    def restore(self, text: str) -> None:
        self.doc = ezdxf.read(io.StringIO(text))


class DocumentManager:
    def __init__(self, workdir: Path | None = None):
        self.workdir = workdir or default_workdir()
        self.docs: dict[str, DocState] = {}
        self.current: str | None = None

    def resolve_path(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.workdir / p
        return p

    def unique_name(self, base: str) -> str:
        name, i = base, 1
        while name in self.docs:
            i += 1
            name = f"{base}-{i}"
        return name

    def add(self, doc: Drawing, name: str, path: Path | None = None) -> DocState:
        name = self.unique_name(name)
        state = DocState(name=name, doc=doc, path=path)
        self.docs[name] = state
        self.current = name
        return state

    def new_doc(self, units: str = "mm", version: str = "R2018") -> Drawing:
        doc = ezdxf.new(version, setup=True, units=parse_units(units))
        doc.header["$MEASUREMENT"] = 0 if units in ("in", "inch", "ft", "feet") else 1
        # ezdxf's own EZDXF styles measure in meters x100; AutoCAD's Standard measures 1:1
        doc.header["$DIMSTYLE"] = "Standard"
        return doc

    def get(self, name: str | None = None) -> DocState:
        if name:
            if name not in self.docs:
                raise CadError(
                    f"No open drawing named '{name}'. Open: {list(self.docs) or 'none'}"
                )
            return self.docs[name]
        if self.current is None:
            self.add(self.new_doc(), "Drawing1")
        return self.docs[self.current]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Context passed to operations
# ---------------------------------------------------------------------------


class Ctx:
    def __init__(self, dm: DocumentManager, drawing: str | None = None):
        self.dm = dm
        self.drawing = drawing

    @property
    def state(self) -> DocState:
        return self.dm.get(self.drawing)

    @property
    def doc(self) -> Drawing:
        return self.state.doc

    @property
    def msp(self):
        return self.doc.modelspace()

    def layout(self, space: str | None = None) -> BaseLayout:
        """Resolve ``space``: None/'model', a paper-space layout name, or 'block:NAME'."""
        doc = self.doc
        if space is None or space.lower() in ("model", "modelspace", "msp"):
            return doc.modelspace()
        if space.lower().startswith("block:"):
            name = space[6:]
            blk = doc.blocks.get(name)
            if blk is None:
                raise CadError(f"Block '{name}' does not exist")
            return blk
        if space.lower() in ("paper", "paperspace"):
            return doc.paperspace()
        try:
            return doc.paperspace(space)
        except (KeyError, ezdxf.DXFValueError):
            raise CadError(
                f"Unknown space '{space}'. Use 'model', a layout name "
                f"{doc.layout_names()} or 'block:NAME'"
            ) from None

    def entity(self, handle: str) -> DXFGraphic:
        e = self.doc.entitydb.get(str(handle).upper())
        if e is None or not e.is_alive:
            raise CadError(f"No entity with handle '{handle}'")
        if not isinstance(e, DXFGraphic):
            raise CadError(f"Handle '{handle}' is a {e.dxftype()}, not a drawing entity")
        return e

    def resolve(self, path: str) -> Path:
        return self.dm.resolve_path(path)

    # -- selection -------------------------------------------------------
    def select(
        self,
        handles: Iterable[str] | str | None = None,
        query: str | None = None,
        layer: str | None = None,
        type: str | None = None,
        window: list | None = None,
        crossing: list | None = None,
        space: str | None = None,
        all: bool = False,
    ) -> list[DXFGraphic]:
        if isinstance(handles, str):
            handles = [handles]
        if handles:
            ents = [self.entity(h) for h in handles]
        else:
            if not (query or layer or type or window or crossing or all):
                raise CadError(
                    "Nothing selected. Pass handles, query, layer, type, window, "
                    "crossing or all=true"
                )
            lay = self.layout(space)
            ents = list(lay.query(query) if query else lay)
        if layer:
            pat = _glob(layer)
            ents = [e for e in ents if pat.fullmatch(e.dxf.get("layer", "0"))]
        if type:
            types = {t.strip().upper() for t in type.replace(",", " ").split()}
            ents = [e for e in ents if e.dxftype() in types]
        if window or crossing:
            (x1, y1), (x2, y2) = [tuple(vec(p).vec2) for p in (window or crossing)]
            lo = (min(x1, x2), min(y1, y2))
            hi = (max(x1, x2), max(y1, y2))
            out = []
            for e in ents:
                ext = bbox.extents([e], fast=True)
                if not ext.has_data:
                    continue
                if window:
                    ok = (
                        ext.extmin.x >= lo[0] and ext.extmin.y >= lo[1]
                        and ext.extmax.x <= hi[0] and ext.extmax.y <= hi[1]
                    )
                else:
                    ok = not (
                        ext.extmax.x < lo[0] or ext.extmin.x > hi[0]
                        or ext.extmax.y < lo[1] or ext.extmin.y > hi[1]
                    )
                if ok:
                    out.append(e)
            ents = out
        return ents


def _glob(pattern: str) -> re.Pattern:
    return re.compile(re.escape(pattern).replace(r"\*", ".*").replace(r"\?", "."), re.I)


SELECTION_HELP = (
    "Selection arguments (any edit/query op that takes `sel`): "
    "{handles:[...]} or {query:'LINE CIRCLE[layer==\"WALL\"]'} (ezdxf query syntax), "
    "{layer:'WALL*'}, {type:'LINE,ARC'}, {window:[[x1,y1],[x2,y2]]} (fully inside), "
    "{crossing:[[x1,y1],[x2,y2]]} (touching), {all:true}; combine freely; add space:'Layout1' or 'block:NAME'."
)


def select_from(ctx: Ctx, sel: Any) -> list[DXFGraphic]:
    """Accept a handle, a list of handles, or a selection dict."""
    if sel is None:
        raise CadError("Missing selection 'sel'. " + SELECTION_HELP)
    if isinstance(sel, (str, list, tuple)):
        return ctx.select(handles=list(sel) if not isinstance(sel, str) else [sel])
    if isinstance(sel, dict):
        allowed = {"handles", "query", "layer", "type", "window", "crossing", "space", "all"}
        bad = set(sel) - allowed
        if bad:
            raise CadError(f"Unknown selection keys {sorted(bad)}. " + SELECTION_HELP)
        return ctx.select(**sel)
    raise CadError("Bad selection. " + SELECTION_HELP)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def vec(p: Any) -> Vec3:
    if isinstance(p, Vec3):
        return p
    if isinstance(p, dict):
        return Vec3(float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0)))
    if isinstance(p, (list, tuple)) and 2 <= len(p) <= 3:
        return Vec3(*[float(c) for c in p])
    if isinstance(p, str):
        parts = [s for s in re.split(r"[,\s]+", p.strip()) if s]
        if 2 <= len(parts) <= 3:
            return Vec3(*[float(c) for c in parts])
    raise CadError(f"Bad point {p!r}: use [x, y] or [x, y, z]")


def vecs(points: Any, min_count: int = 1) -> list[Vec3]:
    if not isinstance(points, (list, tuple)):
        raise CadError("Points must be a list like [[0,0],[10,0],...]")
    out = [vec(p) for p in points]
    if len(out) < min_count:
        raise CadError(f"Need at least {min_count} points, got {len(out)}")
    return out


UNIT_NAMES = {
    "unitless": 0, "none": 0, "in": 1, "inch": 1, "inches": 1, "ft": 2, "feet": 2,
    "mi": 3, "mm": 4, "millimeter": 4, "millimeters": 4, "cm": 5, "centimeter": 5,
    "m": 6, "meter": 6, "meters": 6, "km": 7, "um": 13, "dm": 14,
}


def parse_units(units: Any) -> int:
    if isinstance(units, int):
        return units
    key = str(units).lower().strip()
    if key not in UNIT_NAMES:
        raise CadError(f"Unknown units '{units}'. Use one of {sorted(set(UNIT_NAMES))}")
    return UNIT_NAMES[key]


def units_name(code: int) -> str:
    try:
        return ezunits.decode(code) or "unitless"
    except Exception:
        return str(code)


COLOR_NAMES = {
    "byblock": 0, "red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5,
    "magenta": 6, "white": 7, "black": 7, "gray": 8, "grey": 8, "lightgray": 9,
    "lightgrey": 9, "bylayer": 256,
}


def parse_color(c: Any) -> tuple[int | None, tuple[int, int, int] | None]:
    """Return (aci, rgb). One of them is None."""
    if c is None:
        return None, None
    if isinstance(c, bool):
        raise CadError(f"Bad color {c!r}")
    if isinstance(c, int):
        if not 0 <= c <= 256:
            raise CadError("ACI color must be 0..256")
        return c, None
    if isinstance(c, (list, tuple)) and len(c) == 3:
        return None, tuple(int(v) for v in c)  # type: ignore[return-value]
    if isinstance(c, str):
        s = c.strip().lower()
        if s in COLOR_NAMES:
            return COLOR_NAMES[s], None
        if re.fullmatch(r"#?[0-9a-f]{6}", s):
            s = s.lstrip("#")
            return None, (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        if s.isdigit():
            return parse_color(int(s))
    raise CadError(
        f"Bad color {c!r}: use ACI 0-256, a name (red, yellow, green, cyan, blue, "
        "magenta, white, gray, bylayer, byblock), '#RRGGBB' or [r,g,b]"
    )


VALID_LW = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]


def parse_lineweight(lw: Any) -> int:
    if isinstance(lw, str):
        s = lw.strip().lower()
        if s == "bylayer":
            return -1
        if s == "byblock":
            return -2
        if s == "default":
            return -3
        s = s.replace("mm", "")
        lw = float(s)
    if isinstance(lw, (int, float)):
        if lw < 0:
            return int(lw)
        # values below 3 are taken as millimeters (0.25 -> 25)
        val = lw * 100 if lw < 3 else lw
        return min(VALID_LW, key=lambda v: abs(v - val))
    raise CadError(f"Bad lineweight {lw!r}: use mm like 0.35, or 'bylayer'")


def ensure_layer(doc: Drawing, name: str) -> None:
    if name and not doc.layers.has_entry(name):
        doc.layers.add(name)


# acad.lin linetypes missing from ezdxf's standard set ([total length, dash, gap, ...])
EXTRA_LINETYPES = [
    ("HIDDEN", "Hidden __ __ __ __ __ __ __ __ __ __ __ __ __ __", [0.375, 0.25, -0.125]),
    ("HIDDEN2", "Hidden (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _", [0.1875, 0.125, -0.0625]),
    ("HIDDENX2", "Hidden (2x) ____ ____ ____ ____ ____ ____ ____", [0.75, 0.5, -0.25]),
]


def ensure_linetype(doc: Drawing, name: str) -> None:
    if not name or name.lower() in ("bylayer", "byblock", "continuous"):
        return
    if doc.linetypes.has_entry(name):
        return
    from ezdxf.tools.standards import linetypes

    for lt_name, desc, pattern in list(linetypes()) + EXTRA_LINETYPES:
        if lt_name.lower() == name.lower():
            doc.linetypes.add(lt_name, pattern=pattern, description=desc)
            return
    raise CadError(
        f"Linetype '{name}' is not loaded and not a standard linetype. "
        "Use style.list_linetypes to see options."
    )


PROP_KEYS = {"layer", "color", "linetype", "lineweight", "ltscale", "transparency", "thickness"}


def apply_props(doc: Drawing, e: DXFGraphic, props: dict) -> None:
    for key, val in props.items():
        if val is None:
            continue
        if key == "layer":
            ensure_layer(doc, val)
            e.dxf.layer = val
        elif key == "color":
            aci, rgb = parse_color(val)
            if rgb is not None:
                e.rgb = rgb
            else:
                if e.dxf.hasattr("true_color"):
                    e.dxf.discard("true_color")
                e.dxf.color = aci
        elif key == "linetype":
            ensure_linetype(doc, val)
            e.dxf.linetype = val
        elif key == "lineweight":
            e.dxf.lineweight = parse_lineweight(val)
        elif key == "ltscale":
            e.dxf.ltscale = float(val)
        elif key == "transparency":
            e.transparency = float(val)
        elif key == "thickness":
            e.dxf.thickness = float(val)
        else:
            raise CadError(f"Unknown property '{key}'. Use {sorted(PROP_KEYS)}")


def pick_props(kwargs: dict) -> dict:
    unknown = sorted(set(kwargs) - PROP_KEYS)
    if unknown:
        raise CadError(f"unknown argument(s) {unknown}. Entity properties are {sorted(PROP_KEYS)}")
    return {k: kwargs[k] for k in PROP_KEYS if k in kwargs and kwargs[k] is not None}


def finish(doc: Drawing, e: DXFGraphic, props: dict) -> DXFGraphic:
    apply_props(doc, e, props)
    return e


# ---------------------------------------------------------------------------
# Describing entities
# ---------------------------------------------------------------------------

_SKIP_ATTRIBS = {"handle", "owner", "extrusion"}


def _clean(v: Any, nd: int = 6) -> Any:
    if isinstance(v, Vec3) or (hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z")):
        return [round(v.x, nd), round(v.y, nd), round(v.z, nd)]
    if isinstance(v, float):
        return round(v, nd)
    if isinstance(v, (list, tuple)):
        return [_clean(x, nd) for x in v]
    return v


def describe(e: DXFGraphic, detail: bool = False) -> dict:
    t = e.dxftype()
    d: dict[str, Any] = {"handle": e.dxf.handle, "type": t, "layer": e.dxf.get("layer", "0")}
    color = e.dxf.get("color", 256)
    if e.dxf.hasattr("true_color"):
        d["color"] = "#%02x%02x%02x" % e.rgb  # type: ignore[str-format]
    elif color != 256:
        d["color"] = color
    if t == "LINE":
        d.update(start=_clean(e.dxf.start), end=_clean(e.dxf.end),
                 length=round(e.dxf.start.distance(e.dxf.end), 6))
    elif t == "CIRCLE":
        d.update(center=_clean(e.dxf.center), radius=_clean(e.dxf.radius))
    elif t == "ARC":
        d.update(center=_clean(e.dxf.center), radius=_clean(e.dxf.radius),
                 start_angle=_clean(e.dxf.start_angle), end_angle=_clean(e.dxf.end_angle))
    elif t == "LWPOLYLINE":
        pts = [[round(x, 6), round(y, 6)] + ([round(b, 6)] if b else [])
               for x, y, b in e.get_points("xyb")]
        d.update(closed=e.closed, points=pts if detail or len(pts) <= 50 else pts[:50],
                 count=len(pts))
    elif t in ("TEXT", "ATTRIB", "ATTDEF"):
        d.update(text=e.dxf.text, insert=_clean(e.dxf.insert), height=_clean(e.dxf.height))
        if t != "TEXT":
            d["tag"] = e.dxf.tag
    elif t == "MTEXT":
        d.update(text=e.plain_text(), insert=_clean(e.dxf.insert),
                 char_height=_clean(e.dxf.char_height))
    elif t == "INSERT":
        d.update(block=e.dxf.name, insert=_clean(e.dxf.insert),
                 scale=_clean([e.dxf.xscale, e.dxf.yscale, e.dxf.zscale]),
                 rotation=_clean(e.dxf.rotation))
        if e.attribs:
            d["attributes"] = {a.dxf.tag: a.dxf.text for a in e.attribs}
    elif t == "DIMENSION":
        try:
            d["measurement"] = _clean(e.get_measurement())
        except Exception:
            pass
        d["text"] = e.dxf.get("text", "<>")
        d["dimstyle"] = e.dxf.get("dimstyle", "")
    elif t == "HATCH":
        d.update(pattern=e.dxf.pattern_name, solid=bool(e.dxf.solid_fill),
                 paths=len(e.paths))
    elif t == "POINT":
        d.update(location=_clean(e.dxf.location))
    elif t == "ELLIPSE":
        d.update(center=_clean(e.dxf.center), major_axis=_clean(e.dxf.major_axis),
                 ratio=_clean(e.dxf.ratio))
    elif t == "SPLINE":
        d.update(degree=e.dxf.degree, control_points=len(e.control_points),
                 fit_points=len(e.fit_points), closed=e.closed)
    if detail:
        attribs = {k: _clean(v) for k, v in e.dxf.all_existing_dxf_attribs().items()
                   if k not in _SKIP_ATTRIBS}
        d["dxf"] = attribs
        ext = bbox.extents([e], fast=False)
        if ext.has_data:
            d["bbox"] = [_clean(ext.extmin), _clean(ext.extmax)]
        if t == "POLYLINE":
            d["vertices"] = [_clean(v) for v in e.points()]
        if t == "SPLINE":
            d["control_points"] = [_clean(v) for v in e.control_points]
            d["fit_points"] = [_clean(v) for v in e.fit_points]
        if t == "MTEXT":
            d["raw_text"] = e.text
    return d


def handles(ents: Iterable[DXFGraphic]) -> list[str]:
    return [e.dxf.handle for e in ents]


def deg(a: Any) -> float:
    return float(a)


def rad(a: Any) -> float:
    return math.radians(float(a))
