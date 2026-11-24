"""MCP server: exposes every registered operation as grouped tools."""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Literal

from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.types import ToolAnnotations

from . import (  # noqa: F401
    __version__,
    ops_annot2,
    ops_annotate,
    ops_draw,
    ops_drawing,
    ops_edit,
    ops_edit2,
    ops_electric,
    ops_files,
    ops_geo,
    ops_more,
    ops_query,
    ops_rail,
    ops_road,
    ops_road_extra,
    ops_road_junction,
    ops_road_kek,
    ops_road_pavement,
    ops_solid,
    ops_survey,
    ops_svg,
    ops_tables,
    ops_terrain,
    ops_utility,
    render,
    script,
)
from . import modules as mods
from .core import OPS, SELECTION_HELP, CadError, Ctx, DocumentManager, call_op

INSTRUCTIONS = """\
CAD MCP: create, edit, inspect and export AutoCAD drawings (DXF/DWG) without AutoCAD running.
The result opens in AutoCAD for Mac like any drawing.

Conventions
- Points are [x, y] or [x, y, z] in drawing units (default mm). Angles are degrees, counter-clockwise from +X.
- Every tool takes `operation` plus `args` (an object). Unknown/missing args return the exact signature.
- Create ops return entity `handles`; use them for edit/query. `view.png` with show_handles=true shows them.
- Colors: ACI 1-255, names (red, yellow, green, cyan, blue, magenta, white, gray, bylayer) or '#RRGGBB'.
  Lineweight in mm (0.25, 0.5). Layers are created automatically when first used.
- Each change can be undone with drawing.undo. Use `batch` to run many steps in one call (atomic).
- Look at your work: call view.png after drawing; zoom with region=[[x1,y1],[x2,y2]].
- Save with drawing.save path='name.dxf' (or .dwg when the ODA File Converter is installed).
  Relative paths go to the work folder (drawing.list shows it).
- Only the tools of the enabled modules are listed. `modules` (operation list) shows every module (road design,
  traffic engineering, drainage, terrain, geodesy, utilities, 3D ...); enable one, or describe it and call its
  operations with modules.run without enabling it.
"""

HEADERS = {
    "drawing": "Manage drawings: new, open (.dxf/.dwg), save, info, switch, close, undo/redo, header variables, audit, purge, import.",
    "draw": "Create 2D geometry: lines, polylines, rectangles, polygons, circles, arcs, ellipses, splines, points, hatches, solids, images. Every op accepts space ('model', a layout name or 'block:NAME') and props layer, color, linetype, lineweight, ltscale, transparency.",
    "draw3d": "3D: box, wedge, cylinder, cone, pyramid, sphere, torus, helix, extrude, revolve, sweep, loft, polysolid, presspull, free mesh; solid=true makes real 3DSOLIDs (faceted ACIS) instead of meshes; boolean union/subtract/intersect, slice, section, flatshot, mesh<->solid conversion.",
    "annotate": "Text, multiline text, dimensions (linear, aligned, angular, arc length, radius, diameter, ordinate), leaders, tables, edit text. Ops also accept space and props layer, color, linetype, lineweight. For dimensions pick text_height/arrow_size to suit the drawing size (e.g. 1/40 of the overall dimension) or set $DIMSCALE.",
    "edit": "Modify entities: move, copy, rotate, scale, mirror, arrays, delete, explode, properties, offset, trim, extend, lengthen, break, fillet, chamfer, join, stretch, draw order. " + SELECTION_HELP,
    "query": "Read the drawing: list/get entities, count, extents, distance, length, area, find text, intersections, nearest entities. " + SELECTION_HELP,
    "layer": "Layers: list, create, modify (color, linetype, lineweight, on/off, freeze, lock, plot), rename, delete, set current, isolate, standards check.",
    "block": "Blocks: list, contents, define (from draw steps or a selection), attribute definitions, insert with attributes, edit attributes, rename, delete, redefine, import from file, attach xref.",
    "style": "Linetypes, text styles, dimension styles and units.",
    "layout": "Paper space layouts and viewports (scale 0.02 = 1:50).",
    "view": "See the drawing as an image (png) and export PDF/SVG/PNG files, optionally to scale on a paper size.",
    "road": "Road design (útügyi tervezés), drawing units in meters recommended. Alignments (tengely) are stored by name and reused by profile, cross sections, setting out and the other operations below.",
    "geo": "Georeference (default EOV, EPSG:23700; drawing x = EOV Y east, y = EOV X north): convert coordinates EOV/WGS84 (GPS)/any EPSG, put GPS points into the drawing, write AutoCAD geographic location, export KML for Google Earth.",
    "terrain": "Terrain (terepmodell): import survey points (CSV/TXT, e.g. EOV), triangulated surface (TIN), contour lines (szintvonal), spot elevations, terrain along an alignment.",
    "survey": "Surveying (geodézia), EOV [Y, X, H] in metres = drawing [x, y, z]; bearings clockwise from north, angles in degrees or 'DDD-MM-SS': named point list, bearing/distance, polar detail points with orientation (tájékozás), traverse (sokszögvonal) with misclosures, forward/arc intersection and resection (előmetszés, ívmetszés, hátrametszés), levelling line (szintezés), Helmert/affine transformation, DAT land registry import (földhivatali .dat), land take per parcel (kisajátítás), as-built vs design check.",
    "utility": "Utilities (közmű), metres, EOV drawing x = Y east, y = X north: gravity sewer network (csatornahálózat) with automatic inverts from minimum cover and slope, partial-flow hydraulics (Manning / Prandtl-Colebrook) and the sewer long section; pressurised water network hydraulics (vízhálózat, Hazen-Williams / Darcy-Weisbach, loops allowed); utility lines with kind/status/size/depth; clearance check between utilities (közműegyeztetés) against designer-given rules; utilities in road cross sections.",
    "electric": "Electrical and street lighting (villamos, közvilágítás), metres: lighting poles along an alignment (one side, opposite, staggered), photometric files (EULUMDAT .ldt, IES .ies), point-by-point illuminance on the road (Eav, Emin, U0, isolux), voltage drop on radial cables (Cu/Al, 1 or 3 phase), IEC-style single-line symbols and single-line diagrams.",
    "rail": "Railway (vasút, KÉ-VA) on top of road alignments (metres): cant per curve (equilibrium cant, deficiency, excess, ramp length), track in plan with rails and sleepers, turnouts from radius and crossing ratio ('54-190-1:9'), ballasted track cross section with cant.",
    "python": "Escape hatch: run ezdxf Python code on the open drawing for anything other tools do not cover.",
}

READ_ONLY = {"query"}

dm = DocumentManager()


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


def execute(tool: str, operation: str, args: dict | None, drawing: str | None) -> Any:
    """Run one operation with undo snapshot and rollback on error."""
    ctx = Ctx(dm, drawing)
    spec = OPS.get(tool, {}).get(operation)
    state = ctx.state if spec and spec.mutates else None
    if state is not None:
        state.push_undo()
    try:
        result = call_op(ctx, tool, operation, args)
    except Exception as exc:
        if state is not None and state.undo:
            state.restore(state.undo.pop())
        if isinstance(exc, CadError):
            raise
        raise CadError(f"{tool}.{operation} failed: {type(exc).__name__}: {exc}") from exc
    if state is not None:
        state.dirty = True
    return result


def to_content(result: Any):
    if isinstance(result, dict) and "_image" in result:
        data = result.pop("_image")
        return [Image(data=data, format="png"), _dump(result)]
    return _dump(result)


def _make_tool(tool: str, names: tuple[str, ...]):

    def fn(operation: str, args: dict | None = None, drawing: str | None = None):
        return to_content(execute(tool, operation, args, drawing))

    fn.__name__ = tool
    fn.__signature__ = inspect.Signature([
        inspect.Parameter("operation", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          annotation=Literal[names]),  # type: ignore[valid-type]
        inspect.Parameter("args", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None,
                          annotation=dict[str, Any] | None),
        inspect.Parameter("drawing", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None,
                          annotation=str | None),
    ])
    fn.__annotations__ = {"operation": Literal[names], "args": dict[str, Any] | None,  # type: ignore[valid-type]
                          "drawing": str | None}
    return fn


_REF = re.compile(r"^\$(prev|\d+)((?:\.[A-Za-z_]\w*|\[\d+\])*)$")


def _resolve_refs(value: Any, results: list[Any]) -> Any:
    """Replace strings like "$0.handles[0]" or "$prev.handles" with earlier step results."""
    if isinstance(value, str):
        m = _REF.match(value)
        if not m:
            return value
        idx = len(results) - 1 if m.group(1) == "prev" else int(m.group(1))
        if not 0 <= idx < len(results):
            raise CadError(f"Reference {value}: no step {idx} yet")
        cur = results[idx]
        for part in re.findall(r"\.([A-Za-z_]\w*)|\[(\d+)\]", m.group(2)):
            key, num = part
            try:
                cur = cur[key] if key else cur[int(num)]
            except (KeyError, IndexError, TypeError):
                raise CadError(f"Reference {value} does not resolve") from None
        return cur
    if isinstance(value, list):
        return [_resolve_refs(v, results) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_refs(v, results) for k, v in value.items()}
    return value


def batch(steps: list[dict[str, Any]], drawing: str | None = None, atomic: bool = True) -> str:
    """Run many operations in one call: steps=[{"tool":"draw","operation":"line","args":{...}}, ...].
    Later steps can use earlier results with strings like "$0.handles[0]" or "$prev.handles".
    atomic=true (default) rolls everything back if one step fails; the whole batch is one undo step."""
    ctx = Ctx(dm, drawing)
    state = ctx.state
    state.push_undo()
    results: list[Any] = []
    for i, step in enumerate(steps):
        try:
            tool, operation = step["tool"], step["operation"]
            if tool == "view":
                raise CadError("Call view.png outside batch to see images")
            args = _resolve_refs(step.get("args") or {}, results)
            results.append(call_op(Ctx(dm, step.get("drawing", drawing)), tool, operation, args))
        except Exception as exc:
            msg = str(exc) if isinstance(exc, CadError) else f"{type(exc).__name__}: {exc}"
            if atomic:
                if state.undo:
                    state.restore(state.undo.pop())
                raise CadError(f"Step {i} ({step.get('tool')}.{step.get('operation')}) failed: {msg}. "
                               "All steps were rolled back.") from exc
            results.append({"error": msg})
    state.dirty = True
    return _dump({"steps": len(steps), "results": results})


# ---------------------------------------------------------------------------
# switchable modules
# ---------------------------------------------------------------------------

ENABLED: set[str] = set()
ENABLED_SOURCE = ""
_REGISTERED: set[str] = set()
MODULE_OPS = ("list", "enable", "disable", "set", "describe", "run")


def _describe(tool: str, names: tuple[str, ...]) -> str:
    lines = [HEADERS.get(tool, tool).strip(), "", "Operations:"] + [mods.op_line(tool, o) for o in names]
    hidden = sorted({mods.module_of(tool, o) for o in OPS[tool]} - ENABLED)
    if hidden:
        lines.append(f"(More operations in the disabled module(s) {', '.join(hidden)}: see the modules tool.)")
    return "\n".join(lines)


def _visible_ops() -> dict[str, tuple[str, ...]]:
    out = {}
    for tool in OPS:
        if tool == "python" and not script.enabled():
            continue
        names = tuple(o for o in OPS[tool] if mods.module_of(tool, o) in ENABLED)
        if names:
            out[tool] = names
    return out


def register_tools(server: MCPServer) -> list[str]:
    """(Re)register the CAD tools for the enabled modules; returns the tool names."""
    for name in list(_REGISTERED):
        server.remove_tool(name)
        _REGISTERED.discard(name)
    for tool, names in _visible_ops().items():
        server.add_tool(
            _make_tool(tool, names),
            name=tool,
            description=_describe(tool, names),
            annotations=ToolAnnotations(readOnlyHint=tool in READ_ONLY, destructiveHint=tool == "edit"),
            structured_output=False,
        )
        _REGISTERED.add(tool)
    return sorted(_REGISTERED)


def _module_table() -> list[dict]:
    rows = []
    for name, m in mods.MODULES.items():
        ops = mods.ops_of(name)
        if name == "python" and not script.enabled():
            continue
        rows.append({"module": name, "title": m["title"], "enabled": name in ENABLED, "operations": len(ops),
                     "tokens": mods.tokens(name), "description": m["description"]})
    return rows


def modules_op(server: MCPServer | None, operation: str, args: dict | None) -> tuple[dict | Any, bool]:
    """The modules tool without the MCP plumbing: returns (result, tools_changed)."""
    global ENABLED
    args = dict(args or {})
    if operation == "list":
        return {"enabled": sorted(ENABLED), "set_by": ENABLED_SOURCE, "modules": _module_table(),
                "profiles": {k: {"title": mods.PROFILE_TITLES.get(k, k), "modules": v} for k, v in mods.PROFILES.items()},
                "listed_tokens": sum(r["tokens"] for r in _module_table() if r["enabled"])}, False
    if operation == "describe":
        name = args.get("module")
        if name not in mods.MODULES:
            raise CadError(f"module must be one of {list(mods.MODULES)}")
        return {"module": name, "enabled": name in ENABLED, "operations": [
            {"tool": t, "operation": o, "line": mods.op_line(t, o)} for t, o in mods.ops_of(name)]}, False
    if operation == "run":
        tool, op = args.get("tool"), args.get("operation")
        if tool not in OPS or op not in OPS.get(tool, {}):
            raise CadError("run needs tool and operation of a registered operation (see modules.describe)")
        if tool == "python" and not script.enabled():
            raise CadError("The python escape hatch is disabled (CAD_MCP_ALLOW_PYTHON)")
        return execute(tool, op, args.get("args"), args.get("drawing")), False
    if operation in ("enable", "disable", "set"):
        names = args.get("modules") or args.get("profile") or []
        try:
            chosen = mods.expand(names)
        except ValueError as exc:
            raise CadError(str(exc)) from None
        if operation == "enable":
            new = ENABLED | chosen
        elif operation == "disable":
            requested = mods.expand(names) - {mods.ALWAYS} if names else set()
            new = (ENABLED - requested) | {mods.ALWAYS}
        else:
            new = chosen
        changed = new != ENABLED
        ENABLED = new
        tools = register_tools(server) if server is not None and changed else sorted(_REGISTERED)
        saved = None
        if args.get("persist", True):
            saved = str(mods.save(dm.workdir, ENABLED))
        out = {"enabled": sorted(ENABLED), "tools": tools,
               "listed_tokens": sum(r["tokens"] for r in _module_table() if r["enabled"]), "saved": saved}
        if not saved:
            out["note"] = "Not saved: at the next start the saved choice or CAD_MCP_MODULES applies."
        if changed:
            out["client_note"] = ("Tool list changed. If the new tools are not visible yet, call them through "
                                  "modules.run or restart the MCP connection.")
        return out, changed
    raise CadError(f"operation must be one of {list(MODULE_OPS)}")


def _make_modules_tool(server: MCPServer):
    async def modules(operation: Literal[MODULE_OPS], args: dict[str, Any] | None = None,  # type: ignore[valid-type]
                      ctx: Context | None = None) -> Any:
        result, changed = modules_op(server, operation, args)
        if changed and ctx is not None:
            for notify in (lambda: ctx.session.send_tool_list_changed(), ctx.notify_tools_changed):
                try:
                    await notify()
                except Exception:  # noqa: BLE001 - the client may not support it; the change still applies
                    pass
        return to_content(result) if not isinstance(result, str) else result

    modules.__doc__ = (
        "Switchable modules (kapcsolható modulok): which CAD tools are listed. operation: list (modules, profiles, "
        "token cost, what is on) | enable / disable / set with args {modules: [...]} or {profile: 'kek' (road, KÉ-K)|"
        "'vztel' (utilities)|'geodeta' (survey)|'rajz'|'minimal'|'mind'} (saved for the next start; persist=false to skip) | describe {module} "
        "(operation signatures of a module, enabled or not) | run {tool, operation, args} (run any operation, also "
        "of a disabled module). Modules: " + ", ".join(f"{k} ({v['title']})" for k, v in mods.MODULES.items()) + ".")
    return modules


def build_server(enabled: set[str] | None = None) -> MCPServer:
    global ENABLED, ENABLED_SOURCE
    if enabled is not None:
        ENABLED, ENABLED_SOURCE = mods.expand(sorted(enabled)), "build_server"
    else:
        try:
            ENABLED, ENABLED_SOURCE = mods.initial(dm.workdir)
        except ValueError as exc:
            raise SystemExit(f"CAD_MCP_MODULES: {exc}") from None
    _REGISTERED.clear()
    server = MCPServer(name="cad-mcp", title="CAD MCP (AutoCAD DXF/DWG)", version=__version__,
                       instructions=INSTRUCTIONS)
    register_tools(server)
    server.add_tool(batch, name="batch", structured_output=False,
                    annotations=ToolAnnotations(readOnlyHint=False))
    server.add_tool(_make_modules_tool(server), name="modules", structured_output=False,
                    annotations=ToolAnnotations(readOnlyHint=False))
    return server


def main() -> None:
    server = build_server()
    low = getattr(server, "_lowlevel_server", None)
    if low is None:  # other SDK layout: no list_changed capability, the modules tool still works
        server.run("stdio")
        return
    import anyio
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.stdio import stdio_server

    async def run() -> None:
        async with stdio_server() as (read, write):
            await low.run(read, write, low.create_initialization_options(NotificationOptions(tools_changed=True)))

    anyio.run(run)
