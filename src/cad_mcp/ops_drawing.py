"""Tool `drawing`: open, create, save, switch, undo/redo, header variables."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import bbox, recover

from . import dwg
from .core import CadError, Ctx, _clean, op, parse_units, units_name

T = "drawing"


@op(T, "new")
def new(ctx: Ctx, name: str = "Drawing", units: str = "mm", version: str = "R2018"):
    """Create a new empty drawing (standard linetypes, text and dimension styles loaded) and make it current."""
    doc = ctx.dm.new_doc(units=units, version=version)
    st = ctx.dm.add(doc, name)
    return {"drawing": st.name, "units": units, "version": doc.dxfversion}


@op(T, "open")
def open_(ctx: Ctx, path: str, name: str | None = None, recover_errors: bool = True):
    """Open a .dxf or .dwg file (DWG needs ODA File Converter). Relative paths are inside the work folder."""
    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    ext = p.suffix.lower()
    messages: list[str] = []
    if ext == ".dwg":
        doc = dwg.read_dwg(p)
    elif ext == ".dxf":
        try:
            doc = ezdxf.readfile(p)
        except ezdxf.DXFStructureError:
            if not recover_errors:
                raise
            doc, auditor = recover.readfile(p)
            messages = [str(e.message) for e in auditor.errors][:20]
    else:
        raise CadError("Only .dxf and .dwg files can be opened")
    st = ctx.dm.add(doc, name or p.stem, path=p)
    res = {"drawing": st.name, "path": str(p), **_info(st)}
    if messages:
        res["recovered_errors"] = messages
    return res


@op(T, "save")
def save(ctx: Ctx, path: str | None = None, dwg_version: str = "R2018", dxf_version: str | None = None):
    """Save the drawing. Extension decides the format (.dxf or .dwg). Without path saves to the file it came from."""
    st = ctx.state
    if path:
        p = ctx.resolve(path)
    elif st.path:
        p = st.path
    else:
        p = ctx.resolve(f"{st.name}.dxf")
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower()
    if ext == ".dwg":
        dwg.write_dwg(st.doc, p, dwg_version)
    elif ext == ".dxf":
        if dxf_version and dxf_version != st.doc.dxfversion:
            _save_version(st.doc, p, dxf_version)
        else:
            st.doc.saveas(p)
    else:
        raise CadError("Path must end with .dxf or .dwg")
    st.path = p
    st.dirty = False
    return {"saved": str(p), "format": ext[1:]}


def _save_version(doc, p: Path, version: str):
    import io

    stream = io.StringIO()
    doc.write(stream)
    copy = ezdxf.read(io.StringIO(stream.getvalue()))
    copy.dxfversion = version
    copy.saveas(p)


def _info(st) -> dict:
    doc = st.doc
    msp = doc.modelspace()
    counts: dict[str, int] = {}
    for e in msp:
        counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1
    ext = bbox.extents(msp, fast=True)
    return {
        "version": doc.dxfversion,
        "units": units_name(doc.units),
        "entities": sum(counts.values()),
        "by_type": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "layers": len(doc.layers),
        "blocks": len([b for b in doc.blocks if not b.name.startswith("*")]),
        "layouts": [n for n in doc.layout_names() if n != "Model"],
        "extents": [_clean(ext.extmin), _clean(ext.extmax)] if ext.has_data else None,
        "current_layer": doc.header.get("$CLAYER", "0"),
        "unsaved_changes": st.dirty,
        "undo_steps": len(st.undo),
    }


@op(T, "info")
def info(ctx: Ctx):
    """Summary of the current drawing: units, extents, entity counts, layers, blocks, layouts."""
    st = ctx.state
    return {"drawing": st.name, "path": str(st.path) if st.path else None, **_info(st)}


@op(T, "list")
def list_(ctx: Ctx):
    """List open drawings and which one is current."""
    return {
        "current": ctx.dm.current,
        "open": [
            {"name": s.name, "path": str(s.path) if s.path else None, "unsaved_changes": s.dirty}
            for s in ctx.dm.docs.values()
        ],
        "workdir": str(ctx.dm.workdir),
    }


@op(T, "switch")
def switch(ctx: Ctx, name: str):
    """Make another open drawing current."""
    ctx.dm.get(name)
    ctx.dm.current = name
    return {"current": name}


@op(T, "close")
def close(ctx: Ctx, name: str | None = None, discard_changes: bool = False):
    """Close a drawing (current by default). Refuses if unsaved unless discard_changes=true."""
    st = ctx.dm.get(name or ctx.drawing)
    if st.dirty and not discard_changes:
        raise CadError(f"'{st.name}' has unsaved changes: save it or pass discard_changes=true")
    del ctx.dm.docs[st.name]
    if ctx.dm.current == st.name:
        ctx.dm.current = next(iter(ctx.dm.docs), None)
    return {"closed": st.name, "current": ctx.dm.current}


@op(T, "undo")
def undo(ctx: Ctx, steps: int = 1):
    """Undo the last change(s). Handles stay valid."""
    st = ctx.state
    done = 0
    for _ in range(max(1, steps)):
        if not st.undo:
            break
        st.redo.append(st.snapshot())
        st.restore(st.undo.pop())
        done += 1
    st.dirty = True
    return {"undone": done, "undo_left": len(st.undo), "redo_available": len(st.redo)}


@op(T, "redo")
def redo(ctx: Ctx, steps: int = 1):
    """Redo changes undone with undo."""
    st = ctx.state
    done = 0
    for _ in range(max(1, steps)):
        if not st.redo:
            break
        st.undo.append(st.snapshot())
        st.restore(st.redo.pop())
        done += 1
    st.dirty = True
    return {"redone": done, "redo_left": len(st.redo)}


@op(T, "get_var")
def get_var(ctx: Ctx, names: list[str] | None = None):
    """Read header (system) variables like $LTSCALE, $DIMSCALE, $INSUNITS. Without names lists all."""
    hdr = ctx.doc.header
    if not names:
        return {k: _clean(hdr.get(k)) for k in sorted(hdr.varnames())}
    out = {}
    for n in names:
        key = n if n.startswith("$") else "$" + n.upper()
        out[key] = _clean(hdr.get(key)) if key in hdr else None
    return out


@op(T, "set_var", mutates=True)
def set_var(ctx: Ctx, values: dict):
    """Set header variables, e.g. {"$LTSCALE": 10, "$DIMSCALE": 50, "$CLAYER": "WALL"}."""
    hdr = ctx.doc.header
    done = {}
    for n, v in values.items():
        key = n if n.startswith("$") else "$" + n.upper()
        try:
            hdr[key] = tuple(v) if isinstance(v, list) else v
        except Exception as exc:
            raise CadError(f"Cannot set {key}: {exc}") from exc
        done[key] = v
    return {"set": done}


@op(T, "set_units", mutates=True)
def set_units(ctx: Ctx, units: str):
    """Set drawing units (mm, cm, m, in, ft, unitless). Does not scale geometry."""
    ctx.doc.units = parse_units(units)
    ctx.doc.header["$MEASUREMENT"] = 0 if units in ("in", "inch", "ft", "feet") else 1
    return {"units": units_name(ctx.doc.units)}


@op(T, "audit", mutates=True)
def audit(ctx: Ctx):
    """Check and repair the drawing database (like AutoCAD AUDIT)."""
    auditor = ctx.doc.audit()
    return {
        "errors": [str(e.message) for e in auditor.errors][:50],
        "fixes": [str(f.message) for f in auditor.fixes][:50],
    }


@op(T, "purge", mutates=True)
def purge(ctx: Ctx):
    """Remove unused block definitions and empty layers that nothing references (like PURGE)."""
    doc = ctx.doc
    used_blocks: set[str] = set()
    used_layers: set[str] = {"0", "Defpoints", doc.header.get("$CLAYER", "0")}
    for layout in doc.layouts_and_blocks():
        for e in layout:
            used_layers.add(e.dxf.get("layer", "0"))
            if e.dxftype() == "INSERT":
                used_blocks.add(e.dxf.name)
            if e.dxftype() == "DIMENSION" and e.dxf.hasattr("geometry"):
                used_blocks.add(e.dxf.geometry)
    removed_blocks = []
    changed = True
    while changed:  # nested blocks: repeat until stable
        changed = False
        for blk in list(doc.blocks):
            n = blk.name
            if n.startswith("*") or n in used_blocks or blk.block_record.is_any_layout:
                continue
            doc.blocks.delete_block(n, safe=False)
            removed_blocks.append(n)
            changed = True
        if changed:
            used_blocks = {
                e.dxf.name for lay in doc.layouts_and_blocks() for e in lay if e.dxftype() == "INSERT"
            }
    removed_layers = []
    for name in [layer.dxf.name for layer in doc.layers]:
        if name not in used_layers:
            doc.layers.remove(name)  # destroys the entity: keep only the name
            removed_layers.append(name)
    return {"removed_blocks": removed_blocks, "removed_layers": removed_layers}


@op(T, "import", mutates=True)
def import_(ctx: Ctx, path: str, include_paperspace: bool = False):
    """Merge the model space of another .dxf/.dwg file into this drawing (layers, blocks and styles come along)."""
    from ezdxf import xref

    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    src = dwg.read_dwg(p) if p.suffix.lower() == ".dwg" else ezdxf.readfile(p)
    before = len(ctx.msp)
    xref.load_modelspace(src, ctx.doc)
    if include_paperspace:
        for layout in src.layouts:
            if layout.name != "Model":
                xref.load_paperspace(layout, ctx.doc)
    return {"imported_entities": len(ctx.msp) - before}
