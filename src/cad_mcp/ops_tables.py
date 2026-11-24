"""Tools `layer`, `block`, `style` and `layout`."""

from __future__ import annotations

from ezdxf import bbox
from ezdxf.math import Vec3

from .core import (CadError, Ctx, _clean, call_op, describe, ensure_linetype, handles, op,
                   parse_color, parse_lineweight, parse_units, select_from, units_name, vec)

# ---------------------------------------------------------------------------
# layer
# ---------------------------------------------------------------------------
L = "layer"


def _layer_dict(layer) -> dict:
    d = {
        "name": layer.dxf.name,
        "color": layer.color,
        "linetype": layer.dxf.get("linetype", "Continuous"),
        "lineweight": layer.dxf.get("lineweight", -3),
        "on": layer.is_on(),
        "frozen": layer.is_frozen(),
        "locked": layer.is_locked(),
        "plot": bool(layer.dxf.get("plot", 1)),
    }
    if layer.rgb:
        d["true_color"] = "#%02x%02x%02x" % layer.rgb
    if layer.description:
        d["description"] = layer.description
    return d


@op(L, "list")
def layer_list(ctx: Ctx, with_counts: bool = True, name: str | None = None, on: bool | None = None,
               frozen: bool | None = None, locked: bool | None = None, color=None):
    """All layers with color, linetype, lineweight, on/frozen/locked/plot and entity counts. Filters (layer filter): name pattern with * and ?, on, frozen, locked, color."""
    import fnmatch

    counts: dict[str, int] = {}
    if with_counts:
        for e in ctx.msp:
            n = e.dxf.get("layer", "0")
            counts[n] = counts.get(n, 0) + 1
    want_color = parse_color(color)[0] if color is not None else None
    out = []
    for layer in ctx.doc.layers:
        d = _layer_dict(layer)
        if name and not fnmatch.fnmatch(d["name"].lower(), name.lower()):
            continue
        if on is not None and d["on"] != on:
            continue
        if frozen is not None and d["frozen"] != frozen:
            continue
        if locked is not None and d["locked"] != locked:
            continue
        if want_color is not None and d["color"] != want_color:
            continue
        if with_counts:
            d["entities"] = counts.get(layer.dxf.name, 0)
        out.append(d)
    return {"current": ctx.doc.header.get("$CLAYER", "0"), "layers": out}


def _apply_layer(ctx: Ctx, layer, color=None, linetype=None, lineweight=None, on=None, frozen=None,
                 locked=None, plot=None, description=None, transparency=None):
    if color is not None:
        aci, rgb = parse_color(color)
        if rgb:
            layer.rgb = rgb
        else:
            layer.color = aci
    if linetype is not None:
        ensure_linetype(ctx.doc, linetype)
        layer.dxf.linetype = linetype
    if lineweight is not None:
        layer.dxf.lineweight = parse_lineweight(lineweight)
    if on is not None:
        layer.on() if on else layer.off()
    if frozen is not None:
        layer.freeze() if frozen else layer.thaw()
    if locked is not None:
        layer.lock() if locked else layer.unlock()
    if plot is not None:
        layer.dxf.plot = 1 if plot else 0
    if description is not None:
        layer.description = description
    if transparency is not None:
        layer.transparency = float(transparency)


@op(L, "create", mutates=True)
def layer_create(ctx: Ctx, name: str, color=7, linetype: str = "Continuous", lineweight=None,
                 plot: bool = True, description: str | None = None, make_current: bool = False):
    """Create a layer (or update it if it exists)."""
    doc = ctx.doc
    layer = doc.layers.get(name) if doc.layers.has_entry(name) else doc.layers.add(name)
    _apply_layer(ctx, layer, color=color, linetype=linetype, lineweight=lineweight, plot=plot,
                 description=description)
    if make_current:
        doc.header["$CLAYER"] = name
    return _layer_dict(layer)


@op(L, "create_many", mutates=True)
def layer_create_many(ctx: Ctx, layers: list):
    """Create several layers: layers=[{name, color, linetype, lineweight, ...}, ...]."""
    return {"layers": [layer_create(ctx, **spec) for spec in layers]}


@op(L, "modify", mutates=True)
def layer_modify(ctx: Ctx, name: str, color=None, linetype=None, lineweight=None, on=None, frozen=None,
                 locked=None, plot=None, description=None, transparency=None):
    """Change layer properties: color, linetype, lineweight, on, frozen, locked, plot, description, transparency."""
    if not ctx.doc.layers.has_entry(name):
        raise CadError(f"Layer '{name}' does not exist")
    layer = ctx.doc.layers.get(name)
    _apply_layer(ctx, layer, color, linetype, lineweight, on, frozen, locked, plot, description,
                 transparency)
    return _layer_dict(layer)


@op(L, "rename", mutates=True)
def layer_rename(ctx: Ctx, name: str, new_name: str):
    """Rename a layer; entities follow."""
    layer = ctx.doc.layers.get(name)
    if layer is None:
        raise CadError(f"Layer '{name}' does not exist")
    layer.rename(new_name)
    return {"renamed": name, "to": new_name}


@op(L, "delete", mutates=True)
def layer_delete(ctx: Ctx, name: str, move_entities_to: str | None = None, delete_entities: bool = False):
    """Delete a layer. Its entities must be moved (move_entities_to) or deleted (delete_entities=true) first, else refused."""
    doc = ctx.doc
    if name in ("0", "Defpoints"):
        raise CadError("Layers 0 and Defpoints cannot be deleted")
    if not doc.layers.has_entry(name):
        raise CadError(f"Layer '{name}' does not exist")
    users = [e for lay in doc.layouts_and_blocks() for e in lay if e.dxf.get("layer") == name]
    if users and not (move_entities_to or delete_entities):
        raise CadError(f"Layer '{name}' has {len(users)} entities; pass move_entities_to or delete_entities=true")
    for e in users:
        if move_entities_to:
            if not doc.layers.has_entry(move_entities_to):
                doc.layers.add(move_entities_to)
            e.dxf.layer = move_entities_to
        else:
            e.get_layout().delete_entity(e)
    if doc.header.get("$CLAYER") == name:
        doc.header["$CLAYER"] = "0"
    doc.layers.remove(name)
    return {"deleted": name, "entities_moved" if move_entities_to else "entities_deleted": len(users)}


@op(L, "set_current", mutates=True)
def layer_set_current(ctx: Ctx, name: str):
    """Make a layer current ($CLAYER)."""
    if not ctx.doc.layers.has_entry(name):
        ctx.doc.layers.add(name)
    ctx.doc.header["$CLAYER"] = name
    return {"current": name}


@op(L, "isolate", mutates=True)
def layer_isolate(ctx: Ctx, names: list[str]):
    """Turn off every layer except the given ones (like LAYISO)."""
    keep = {n.lower() for n in names}
    off = []
    for layer in ctx.doc.layers:
        if layer.dxf.name.lower() in keep:
            layer.on()
        else:
            layer.off()
            off.append(layer.dxf.name)
    return {"visible": names, "turned_off": off}


@op(L, "all_on", mutates=True)
def layer_all_on(ctx: Ctx):
    """Turn on and thaw all layers."""
    for layer in ctx.doc.layers:
        layer.on()
        layer.thaw()
    return {"layers": len(ctx.doc.layers)}


@op(L, "check_standards")
def layer_check(ctx: Ctx, rules: dict):
    """Check layers/entities against rules: {"allowed_layers": [...], "layer_colors": {"WALL": 1}, "no_entities_on": ["0"], "require_bylayer_color": true}. Returns violations with handles."""
    doc = ctx.doc
    v = []
    allowed = {n.lower() for n in rules.get("allowed_layers", [])}
    if allowed:
        for layer in doc.layers:
            if layer.dxf.name.lower() not in allowed | {"0", "defpoints"}:
                v.append({"rule": "allowed_layers", "layer": layer.dxf.name})
    for name, color in (rules.get("layer_colors") or {}).items():
        if doc.layers.has_entry(name):
            aci, rgb = parse_color(color)
            lay = doc.layers.get(name)
            if (aci is not None and lay.color != aci) or (rgb and lay.rgb != rgb):
                v.append({"rule": "layer_colors", "layer": name, "expected": color, "actual": lay.color})
    forbidden = {n.lower() for n in rules.get("no_entities_on", [])}
    bylayer = rules.get("require_bylayer_color", False)
    for e in ctx.msp:
        if e.dxf.get("layer", "0").lower() in forbidden:
            v.append({"rule": "no_entities_on", "handle": e.dxf.handle, "layer": e.dxf.layer})
        if bylayer and (e.dxf.get("color", 256) != 256 or e.dxf.hasattr("true_color")):
            v.append({"rule": "require_bylayer_color", "handle": e.dxf.handle, "color": e.dxf.get("color")})
    return {"violations": len(v), "details": v[:500]}


# ---------------------------------------------------------------------------
# block
# ---------------------------------------------------------------------------
B = "block"


@op(B, "list")
def block_list(ctx: Ctx, include_anonymous: bool = False):
    """Block definitions with entity counts, attribute tags and number of references."""
    refs: dict[str, int] = {}
    for lay in ctx.doc.layouts_and_blocks():
        for e in lay:
            if e.dxftype() == "INSERT":
                refs[e.dxf.name] = refs.get(e.dxf.name, 0) + 1
    out = []
    for blk in ctx.doc.blocks:
        if blk.block_record.is_any_layout or (blk.name.startswith("*") and not include_anonymous):
            continue
        out.append({
            "name": blk.name,
            "entities": len(blk),
            "base_point": _clean(blk.block.dxf.base_point),
            "attributes": [a.dxf.tag for a in blk.attdefs()],
            "references": refs.get(blk.name, 0),
            "xref": bool(blk.block.is_xref),
        })
    return {"blocks": out}


@op(B, "contents")
def block_contents(ctx: Ctx, name: str):
    """Entities inside a block definition."""
    blk = ctx.doc.blocks.get(name)
    if blk is None:
        raise CadError(f"Block '{name}' does not exist")
    return {"name": name, "entities": [describe(e) for e in blk]}


@op(B, "define", mutates=True)
def block_define(ctx: Ctx, name: str, base_point=(0, 0), entities: list | None = None,
                 from_selection=None, replace_with_insert: bool = False, delete_originals: bool = False):
    """Create a block. entities = list of draw steps like {"tool":"draw","operation":"circle","args":{...}} (also annotate/attdef), or from_selection = selection to copy in (coordinates relative to base_point). replace_with_insert swaps the originals for one block reference."""
    doc = ctx.doc
    if doc.blocks.get(name) is not None:
        raise CadError(f"Block '{name}' already exists")
    bp = vec(base_point)
    blk = doc.blocks.new(name, base_point=bp)
    created = []
    for step in entities or []:
        args = dict(step.get("args", {}))
        args["space"] = f"block:{name}"
        res = call_op(ctx, step.get("tool", "draw"), step["operation"], args)
        created += res.get("handles", [])
    moved = []
    if from_selection is not None:
        src = select_from(ctx, from_selection)
        for e in src:
            blk.add_entity(e.copy())
        moved = handles(src)
        if replace_with_insert or delete_originals:
            lay = src[0].get_layout() if src else ctx.msp
            for e in src:
                e.get_layout().delete_entity(e)
            if replace_with_insert:
                ref = lay.add_blockref(name, bp)
                return {"block": name, "entities": len(blk), "insert_handle": ref.dxf.handle}
    return {"block": name, "entities": len(blk), "from_selection": moved or None}


@op(B, "attdef", mutates=True)
def block_attdef(ctx: Ctx, block: str, tag: str, insert, height: float = 2.5, prompt: str = "",
                 default: str = "", invisible: bool = False, align: str = "left"):
    """Add an attribute definition (ATTDEF) to a block definition."""
    from .ops_annotate import TEXT_ALIGN

    blk = ctx.doc.blocks.get(block)
    if blk is None:
        raise CadError(f"Block '{block}' does not exist")
    a = blk.add_attdef(tag.upper(), vec(insert), text=default,
                       dxfattribs={"height": float(height), "prompt": prompt})
    a.set_placement(vec(insert), align=TEXT_ALIGN.get(align.lower(), TEXT_ALIGN["left"]))
    if invisible:
        a.is_invisible = True
    return {"block": block, "tag": tag.upper(), "handle": a.dxf.handle}


@op(B, "insert", mutates=True)
def block_insert(ctx: Ctx, name: str, insert, scale=1.0, rotation: float = 0,
                 attributes: dict | None = None, space=None, layer: str | None = None):
    """Insert a block reference. scale = number or [sx,sy,sz]; attributes = {TAG: value} filled from ATTDEFs."""
    if ctx.doc.blocks.get(name) is None:
        raise CadError(f"Block '{name}' does not exist (block.list)")
    sx, sy, sz = (scale, scale, scale) if isinstance(scale, (int, float)) else (list(scale) + [1, 1])[:3]
    attribs = {"xscale": sx, "yscale": sy, "zscale": sz, "rotation": float(rotation)}
    if layer:
        if not ctx.doc.layers.has_entry(layer):
            ctx.doc.layers.add(layer)
        attribs["layer"] = layer
    ref = ctx.layout(space).add_blockref(name, vec(insert), dxfattribs=attribs)
    if ctx.doc.blocks.get(name).attdefs():
        ref.add_auto_attribs({k.upper(): str(v) for k, v in (attributes or {}).items()})
    return {"handle": ref.dxf.handle, "attributes": {a.dxf.tag: a.dxf.text for a in ref.attribs}}


@op(B, "set_attributes", mutates=True)
def block_set_attributes(ctx: Ctx, handle: str, values: dict):
    """Change attribute values of a block reference: values={TAG: text}."""
    ref = ctx.entity(handle)
    if ref.dxftype() != "INSERT":
        raise CadError("handle must be a block reference (INSERT)")
    found = {}
    for a in ref.attribs:
        if a.dxf.tag.upper() in {k.upper() for k in values}:
            new = next(v for k, v in values.items() if k.upper() == a.dxf.tag.upper())
            a.dxf.text = str(new)
            found[a.dxf.tag] = str(new)
    missing = [k for k in values if k.upper() not in {t.upper() for t in found}]
    for tag in missing:
        a = ref.add_attrib(tag.upper(), str(values[tag]), insert=ref.dxf.insert)
        found[tag.upper()] = str(values[tag])
    return {"handle": handle, "set": found, "added_new": missing or None}


@op(B, "rename", mutates=True)
def block_rename(ctx: Ctx, name: str, new_name: str):
    """Rename a block definition; references follow."""
    if ctx.doc.blocks.get(name) is None:
        raise CadError(f"Block '{name}' does not exist")
    ctx.doc.blocks.rename_block(name, new_name)
    for lay in ctx.doc.layouts_and_blocks():
        for e in lay:
            if e.dxftype() == "INSERT" and e.dxf.name == name:
                e.dxf.name = new_name
    return {"renamed": name, "to": new_name}


@op(B, "delete", mutates=True)
def block_delete(ctx: Ctx, name: str, delete_references: bool = False):
    """Delete a block definition. Refused while referenced unless delete_references=true."""
    doc = ctx.doc
    if doc.blocks.get(name) is None:
        raise CadError(f"Block '{name}' does not exist")
    refs = [e for lay in doc.layouts_and_blocks() for e in lay
            if e.dxftype() == "INSERT" and e.dxf.name == name]
    if refs and not delete_references:
        raise CadError(f"Block '{name}' has {len(refs)} references; pass delete_references=true")
    for e in refs:
        e.get_layout().delete_entity(e)
    doc.blocks.delete_block(name, safe=False)
    return {"deleted": name, "references_deleted": len(refs)}


@op(B, "redefine", mutates=True)
def block_redefine(ctx: Ctx, name: str, entities: list):
    """Replace the content of a block definition with new draw steps (all references update)."""
    blk = ctx.doc.blocks.get(name)
    if blk is None:
        raise CadError(f"Block '{name}' does not exist")
    for e in list(blk):
        blk.delete_entity(e)
    for step in entities:
        args = dict(step.get("args", {}))
        args["space"] = f"block:{name}"
        call_op(ctx, step.get("tool", "draw"), step["operation"], args)
    return {"block": name, "entities": len(blk)}


@op(B, "import", mutates=True)
def block_import(ctx: Ctx, path: str, names: list[str] | None = None):
    """Copy block definitions from another .dxf/.dwg file (all, or only names)."""
    import ezdxf
    from ezdxf import xref

    from . import dwg

    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    src = dwg.read_dwg(p) if p.suffix.lower() == ".dwg" else ezdxf.readfile(p)
    available = [b.name for b in src.blocks if not b.name.startswith("*") and not b.block_record.is_any_layout]
    wanted = names or available
    unknown = [n for n in wanted if n not in available]
    if unknown:
        raise CadError(f"Not in source file: {unknown}. Available: {available[:100]}")
    loader = xref.Loader(src, ctx.doc)
    for n in wanted:
        loader.load_block_layout(src.blocks.get(n))
    loader.execute()
    return {"imported": wanted}


@op(B, "attach_xref", mutates=True)
def block_attach_xref(ctx: Ctx, path: str, insert=(0, 0), name: str | None = None, overlay: bool = False,
                      relative: bool = False, relative_to: str | None = None):
    """Attach an external reference (XREF) to a DXF file. relative=True stores the path relative to relative_to
    (the folder the host drawing will be saved in; default: the work folder), so the drawing pair can be moved
    to another computer; AutoCAD finds such xrefs next to the host drawing."""
    import os

    from ezdxf import xref

    p = ctx.resolve(path)
    bname = name or p.stem
    stored = str(p)
    if relative or relative_to:
        stored = os.path.relpath(p, ctx.resolve(relative_to) if relative_to else ctx.dm.workdir)
    xref.attach(ctx.doc, block_name=bname, filename=stored, insert=vec(insert), overlay=overlay)
    return {"xref": bname, "file": stored}


# ---------------------------------------------------------------------------
# style
# ---------------------------------------------------------------------------
S = "style"


@op(S, "list_linetypes")
def list_linetypes(ctx: Ctx, include_standard: bool = True):
    """Loaded linetypes, and standard ones that can be loaded on first use."""
    from ezdxf.tools.standards import linetypes

    loaded = [lt.dxf.name for lt in ctx.doc.linetypes]
    out = {"loaded": loaded}
    if include_standard:
        out["standard"] = [n for n, _, _ in linetypes() if n not in loaded]
    return out


@op(S, "load_linetype", mutates=True)
def load_linetype(ctx: Ctx, name: str, pattern: list | None = None, description: str = ""):
    """Load a standard linetype, or define a custom one: pattern=[total_length, dash, -gap, dot(0), ...]."""
    if pattern:
        ctx.doc.linetypes.add(name, pattern=[float(x) for x in pattern], description=description)
    else:
        ensure_linetype(ctx.doc, name)
    return {"linetype": name}


@op(S, "list_text_styles")
def list_text_styles(ctx: Ctx):
    """Text styles with font and fixed height."""
    return {"styles": [{"name": s.dxf.name, "font": s.dxf.get("font", ""),
                        "height": s.dxf.get("height", 0), "width": s.dxf.get("width", 1)}
                       for s in ctx.doc.styles]}


@op(S, "create_text_style", mutates=True)
def create_text_style(ctx: Ctx, name: str, font: str = "arial.ttf", height: float = 0,
                      width: float = 1.0, oblique: float = 0):
    """Create/update a text style: font file name (arial.ttf, isocpeur.ttf, txt.shx ...), fixed height (0 = variable)."""
    st = ctx.doc.styles.get(name) if ctx.doc.styles.has_entry(name) else ctx.doc.styles.add(name, font=font)
    st.dxf.font = font
    st.dxf.height = float(height)
    st.dxf.width = float(width)
    st.dxf.oblique = float(oblique)
    return {"style": name, "font": font}


DIMVAR_HELP = ("dimtxt=text height, dimasz=arrow size, dimexe=ext beyond dim line, dimexo=ext offset, "
               "dimgap=text gap, dimdec=decimals, dimscale=overall scale, dimlfac=measure factor, "
               "dimblk=arrow block (e.g. 'ARCHTICK', 'OPEN', '' for closed filled), dimtad=1 text above, "
               "dimclrd/dimclre/dimclrt=colors, dimtxsty=text style, dimpost='<> mm'")


@op(S, "list_dimstyles")
def list_dimstyles(ctx: Ctx):
    """Dimension styles with main variables."""
    keys = ["dimtxt", "dimasz", "dimexe", "dimexo", "dimgap", "dimdec", "dimscale", "dimblk", "dimtad",
            "dimlfac", "dimtxsty", "dimpost"]
    return {"dimstyles": [{"name": d.dxf.name, **{k: d.dxf.get(k) for k in keys if d.dxf.hasattr(k)}}
                          for d in ctx.doc.dimstyles]}


def _create_dimstyle(ctx: Ctx, name: str, values: dict | None = None, based_on: str = "EZDXF"):
    doc = ctx.doc
    if doc.dimstyles.has_entry(name):
        ds = doc.dimstyles.get(name)
    else:
        base = based_on if doc.dimstyles.has_entry(based_on) else "Standard"
        ds = doc.dimstyles.duplicate_entry(base, name)
    for k, v in (values or {}).items():
        try:
            ds.dxf.set(k.lower(), v)
        except Exception as exc:
            raise CadError(f"Bad dimension variable {k}: {exc}. Known: {DIMVAR_HELP}") from exc
    return {"dimstyle": name, "set": values or {}}


_create_dimstyle.__doc__ = "Create/update a dimension style from based_on with values like " + DIMVAR_HELP
op(S, "create_dimstyle", mutates=True)(_create_dimstyle)


@op(S, "units", mutates=True)
def style_units(ctx: Ctx, units: str | None = None, linear_format: int | None = None,
                decimals: int | None = None, angle_format: int | None = None):
    """Drawing units and display: units (mm, cm, m, in, ft), linear_format ($LUNITS 1 sci,2 decimal,3 eng,4 arch), decimals ($LUPREC), angle_format ($AUNITS 0 deg)."""
    doc = ctx.doc
    if units:
        doc.units = parse_units(units)
    if linear_format is not None:
        doc.header["$LUNITS"] = int(linear_format)
    if decimals is not None:
        doc.header["$LUPREC"] = int(decimals)
    if angle_format is not None:
        doc.header["$AUNITS"] = int(angle_format)
    return {"units": units_name(doc.units), "$LUNITS": doc.header.get("$LUNITS"),
            "$LUPREC": doc.header.get("$LUPREC")}


# ---------------------------------------------------------------------------
# layout (paper space)
# ---------------------------------------------------------------------------
P = "layout"

PAPER = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841),
         "LETTER": (279.4, 215.9), "TABLOID": (431.8, 279.4)}


@op(P, "list")
def layout_list(ctx: Ctx):
    """Paper space layouts with paper size and viewports."""
    out = []
    for name in ctx.doc.layout_names_in_taborder():
        if name == "Model":
            continue
        lay = ctx.doc.layouts.get(name)
        vps = [{"handle": v.dxf.handle, "center": _clean(v.dxf.center), "size": [_clean(v.dxf.width), _clean(v.dxf.height)],
                "view_center": _clean(v.dxf.view_center_point), "view_height": _clean(v.dxf.view_height)}
               for v in lay.viewports() if v.dxf.id != 1]
        out.append({"name": name, "paper": [_clean(lay.dxf.paper_width), _clean(lay.dxf.paper_height)],
                    "entities": len(lay), "viewports": vps})
    return {"layouts": out}


@op(P, "create", mutates=True)
def layout_create(ctx: Ctx, name: str, paper: str = "A3", landscape: bool = True,
                  width: float | None = None, height: float | None = None, margins: float = 10):
    """New paper space layout, paper A0-A4, LETTER, TABLOID, or width/height in mm."""
    doc = ctx.doc
    if name in doc.layout_names():
        raise CadError(f"Layout '{name}' already exists")
    if width and height:
        w, h = float(width), float(height)
    else:
        if paper.upper() not in PAPER:
            raise CadError(f"paper must be one of {list(PAPER)} or give width/height")
        w, h = PAPER[paper.upper()]
        if not landscape:
            w, h = h, w
    lay = doc.layouts.new(name)
    lay.page_setup(size=(w, h), margins=(margins, margins, margins, margins), units="mm")
    return {"layout": name, "paper": [w, h]}


@op(P, "add_viewport", mutates=True)
def layout_add_viewport(ctx: Ctx, layout: str, center, size, view_center, scale: float | None = None,
                        view_height: float | None = None, layer: str | None = None):
    """Viewport on a layout: center/size on paper (mm); view_center = model point in the middle; scale = paper/model, e.g. 0.02 for 1:50 (or view_height in model units)."""
    lay = ctx.layout(layout)
    w, h = tuple(vec(size).vec2)
    if view_height is None:
        if not scale:
            raise CadError("Give scale (e.g. 0.02 for 1:50) or view_height")
        view_height = h / float(scale)
    vp = lay.add_viewport(center=vec(center), size=(w, h), view_center_point=vec(view_center),
                          view_height=float(view_height), dxfattribs={"layer": layer} if layer else None)
    return {"handle": vp.dxf.handle, "scale": round(h / view_height, 9)}


@op(P, "zoom_viewport", mutates=True)
def layout_zoom_viewport(ctx: Ctx, handle: str, view_center=None, scale: float | None = None):
    """Pan/zoom an existing viewport: new view_center and/or scale (paper/model)."""
    vp = ctx.entity(handle)
    if vp.dxftype() != "VIEWPORT":
        raise CadError("handle must be a VIEWPORT")
    if view_center is not None:
        vp.dxf.view_center_point = vec(view_center)
    if scale:
        vp.dxf.view_height = vp.dxf.height / float(scale)
    return {"handle": handle}


@op(P, "fit_viewport", mutates=True)
def layout_fit_viewport(ctx: Ctx, handle: str, margin: float = 0.05):
    """Zoom a viewport to model-space extents (like ZOOM EXTENTS inside the viewport)."""
    vp = ctx.entity(handle)
    ext = bbox.extents(ctx.msp)
    if not ext.has_data:
        raise CadError("Model space is empty")
    c = ext.center
    vp.dxf.view_center_point = Vec3(c.x, c.y, 0)
    ratio = vp.dxf.width / vp.dxf.height
    vh = max(ext.size.y, ext.size.x / ratio) * (1 + margin)
    vp.dxf.view_height = vh
    return {"handle": handle, "scale": round(vp.dxf.height / vh, 9)}


@op(P, "delete", mutates=True)
def layout_delete(ctx: Ctx, name: str):
    """Delete a paper space layout."""
    ctx.doc.layouts.delete(name)
    return {"deleted": name}


@op(P, "rename", mutates=True)
def layout_rename(ctx: Ctx, name: str, new_name: str):
    """Rename a layout."""
    ctx.doc.layouts.rename(name, new_name)
    return {"renamed": name, "to": new_name}
