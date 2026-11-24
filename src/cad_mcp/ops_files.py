"""References and files: PDF/DWF/DGN underlays, XCLIP, XBIND, xref management,
resources from other drawings (DesignCenter), page setup, eTransmit packages, batch
DWG/DXF conversion, layer states and LAYTRANS, attribute definitions (BATTMAN),
editable rectangular arrays (MINSERT), data extraction and select similar."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from pathlib import Path

import ezdxf

from . import dwg
from .core import (
    CadError,
    Ctx,
    describe,
    ensure_layer,
    finish,
    handles,
    op,
    parse_color,
    parse_lineweight,
    pick_props,
    select_from,
    vec,
)

# ---------------------------------------------------------------------------
# underlays and clipping
# ---------------------------------------------------------------------------


@op("draw", "underlay", mutates=True)
def underlay(ctx: Ctx, path: str, insert=(0, 0), scale: float = 1.0, rotation: float = 0.0, page: str = "1",
             clip: list | None = None, space=None, **props):
    """PDFATTACH / DWFATTACH / DGNATTACH: attach a PDF (page), DWF/DWFx or DGN file as an underlay; clip = boundary [[x,y],...] in underlay units."""
    p = ctx.resolve(path)
    ext = p.suffix.lower().lstrip(".")
    fmt = {"pdf": "pdf", "dwf": "dwf", "dwfx": "dwf", "dgn": "dgn"}.get(ext)
    if fmt is None:
        raise CadError("Underlay must be .pdf, .dwf, .dwfx or .dgn")
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    udef = ctx.doc.add_underlay_def(filename=str(p), fmt=fmt, name=str(page) if fmt == "pdf" else "default")
    u = ctx.layout(space).add_underlay(udef, insert=vec(insert), scale=(scale, scale, scale), rotation=float(rotation))
    if clip:
        u.boundary_path = [tuple(vec(q).vec2) for q in clip]
        u.clipping = True
    return {"handles": [finish(ctx.doc, u, pick_props(props)).dxf.handle], "format": fmt}


@op("block", "xclip", mutates=True)
def xclip(ctx: Ctx, handle: str, boundary: list | None = None, corner1=None, corner2=None, remove: bool = False):
    """XCLIP: clip a block reference / xref to a polygon (boundary in drawing coordinates) or rectangle (corner1, corner2); remove deletes the clipping. (Inverted clips are not offered: AutoCAD cannot open inverted clips written by ezdxf.)"""
    from ezdxf.xclip import XClip

    ref = ctx.entity(handle)
    if ref.dxftype() != "INSERT":
        raise CadError("xclip needs a block reference (INSERT)")
    xc = XClip(ref)
    if remove:
        xc.discard_clipping_path()
        return {"handle": handle, "clipped": False}
    if boundary:
        pts = [tuple(vec(q).vec2) for q in boundary]
    elif corner1 is not None and corner2 is not None:
        (x1, y1), (x2, y2) = tuple(vec(corner1).vec2), tuple(vec(corner2).vec2)
        pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    else:
        raise CadError("Give boundary points or corner1/corner2")
    xc.set_wcs_clipping_path(pts)
    return {"handle": handle, "clipped": True}


@op("block", "bind_xref", mutates=True)
def bind_xref(ctx: Ctx, name: str):
    """XBIND / Bind: turn an attached external reference into a normal block containing the referenced drawing."""
    from ezdxf import xref

    blk = ctx.doc.blocks.get(name)
    if blk is None or not blk.block.is_xref:
        raise CadError(f"'{name}' is not an attached xref")
    path = Path(blk.block.dxf.xref_path)
    if not path.is_absolute():
        path = ctx.resolve(str(path))
    load = (lambda fn: dwg.read_dwg(Path(fn))) if path.suffix.lower() == ".dwg" else None
    xref.embed(blk, load_fn=load, search_paths=[path.parent])
    return {"bound": name, "entities": len(blk)}


@op("block", "xref_manage", mutates=True)
def xref_manage(ctx: Ctx, action: str = "list", name: str | None = None, new_path: str | None = None):
    """XREF manager: action list | path (repath to new_path) | detach (remove the xref and its references)."""
    doc = ctx.doc
    if action == "list":
        out = []
        for b in doc.blocks:
            if b.block.is_xref:
                p = Path(b.block.dxf.xref_path)
                out.append({"name": b.name, "path": str(p), "found": (p if p.is_absolute() else ctx.resolve(str(p))).is_file(),
                            "overlay": bool(b.block.is_xref_overlay),
                            "references": sum(1 for lay in doc.layouts_and_blocks() for e in lay
                                              if e.dxftype() == "INSERT" and e.dxf.name == b.name)})
        return {"xrefs": out}
    blk = doc.blocks.get(name or "")
    if blk is None or not blk.block.is_xref:
        raise CadError(f"'{name}' is not an attached xref")
    if action == "path":
        if not new_path:
            raise CadError("Give new_path")
        blk.block.dxf.xref_path = str(ctx.resolve(new_path))
        return {"xref": name, "path": blk.block.dxf.xref_path}
    if action == "detach":
        refs = [e for lay in doc.layouts_and_blocks() for e in lay if e.dxftype() == "INSERT" and e.dxf.name == name]
        for e in refs:
            e.get_layout().delete_entity(e)
        doc.blocks.delete_block(name, safe=False)
        return {"detached": name, "references_removed": len(refs)}
    raise CadError("action: list, path, detach (reload/unload are AutoCAD session states)")


@op("drawing", "import_resources", mutates=True)
def import_resources(ctx: Ctx, path: str, layers: list | None = None, linetypes: list | None = None,
                     text_styles: list | None = None, dim_styles: list | None = None, mline_styles: list | None = None,
                     mleader_styles: list | None = None, blocks: list | None = None, everything: bool = False):
    """DesignCenter: copy layers, linetypes, text/dimension/multiline/multileader styles and blocks from another .dxf/.dwg (by name, or everything=true)."""
    from ezdxf import xref

    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    src = dwg.read_dwg(p) if p.suffix.lower() == ".dwg" else ezdxf.readfile(p)

    def names(table, wanted):
        if everything:
            return [e.dxf.name for e in table]
        return list(wanted or [])

    loader = xref.Loader(src, ctx.doc)
    got = {
        "layers": names(src.layers, layers), "linetypes": names(src.linetypes, linetypes),
        "text_styles": names(src.styles, text_styles), "dim_styles": names(src.dimstyles, dim_styles),
        "mline_styles": [n for n, _ in src.mline_styles] if everything else list(mline_styles or []),
        "mleader_styles": [n for n, _ in src.mleader_styles] if everything else list(mleader_styles or []),
    }
    loader.load_layers(got["layers"])
    loader.load_linetypes(got["linetypes"])
    loader.load_text_styles(got["text_styles"])
    loader.load_dim_styles(got["dim_styles"])
    loader.load_mline_styles(got["mline_styles"])
    loader.load_mleader_styles(got["mleader_styles"])
    bl = [b.name for b in src.blocks if not b.name.startswith("*") and not b.block_record.is_any_layout] \
        if everything else list(blocks or [])
    for n in bl:
        if src.blocks.get(n) is None:
            raise CadError(f"Block '{n}' not in {p.name}")
        loader.load_block_layout(src.blocks.get(n))
    loader.execute()
    got["blocks"] = bl
    return {"imported": {k: v for k, v in got.items() if v}}


# ---------------------------------------------------------------------------
# page setup, eTransmit, batch conversion
# ---------------------------------------------------------------------------


@op("layout", "page_setup", mutates=True)
def page_setup(ctx: Ctx, name: str, paper: str = "A3", landscape: bool = True, width: float | None = None,
               height: float | None = None, margins: float = 10, scale: float = 1.0, plot_style: str | None = None,
               device: str = "DWG To PDF.pc3"):
    """PAGESETUP for a paper space layout: paper size (A0-A4, LETTER, TABLOID or width/height mm), orientation, margins, plot scale (paper:drawing, e.g. 1 for layouts), plot style table (e.g. monochrome.ctb), plotter."""
    from .ops_tables import PAPER

    lay = ctx.layout(name)
    if lay.name == "Model":
        raise CadError("page_setup applies to paper space layouts (create one with layout.create)")
    if width and height:
        w, h = float(width), float(height)
    else:
        if paper.upper() not in PAPER:
            raise CadError(f"paper must be one of {list(PAPER)}")
        w, h = PAPER[paper.upper()]
        if not landscape:
            w, h = h, w
    lay.page_setup(size=(w, h), margins=(margins,) * 4, units="mm", scale=(1, 1 / float(scale)) if scale != 1 else 1,
                   name=f"{paper} {'fekvő' if landscape else 'álló'}", device=device)
    if plot_style:
        lay.dxf_layout.dxf.current_style_sheet = plot_style
    return {"layout": lay.name, "paper_mm": [w, h], "plot_style": plot_style, "device": device}


@op("drawing", "etransmit")
def etransmit(ctx: Ctx, path: str, as_dwg: bool = False):
    """ETRANSMIT: zip package with the drawing, attached xrefs, images and underlays, plus a transmittal report."""
    st = ctx.state
    doc = st.doc
    files: dict[str, Path] = {}
    missing = []

    def want(p: str):
        q = Path(p)
        q = q if q.is_absolute() else ctx.resolve(p)
        if q.is_file():
            files.setdefault(q.name, q)
        else:
            missing.append(p)

    for b in doc.blocks:
        if b.block.is_xref:
            want(b.block.dxf.xref_path)
    for obj in doc.objects:
        t = obj.dxftype()
        if t == "IMAGEDEF" or t.endswith("DEFINITION") and obj.dxf.hasattr("filename"):
            want(obj.dxf.filename)
    zp = ctx.resolve(path)
    zp.parent.mkdir(parents=True, exist_ok=True)
    name = (st.path.stem if st.path else st.name) + (".dwg" if as_dwg else ".dxf")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dp = Path(tmp) / name
        if as_dwg:
            dwg.write_dwg(doc, dp)
        else:
            doc.saveas(dp)
        report = [f"eTransmit csomag – {datetime.now().isoformat(timespec='seconds')}", f"Rajz: {name}", "Mellékletek:"]
        report += [f"  {n}" for n in files] or ["  (nincs)"]
        if missing:
            report += ["Nem található hivatkozott fájlok:"] + [f"  {m}" for m in missing]
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dp, name)
            for n, f in files.items():
                z.write(f, n)
            z.writestr("Atadasi_jegyzek.txt", "\n".join(report))
    return {"exported": str(zp), "files": [name] + list(files), "missing": missing}


@op("drawing", "convert_files")
def convert_files(ctx: Ctx, files: list | None = None, folder: str | None = None, to: str = "dwg",
                  version: str = "R2018", out_folder: str | None = None):
    """DWGCONVERT / batch: convert many .dxf/.dwg files to DWG or DXF of a given version (R12 … R2018)."""
    srcs = [ctx.resolve(f) for f in (files or [])]
    if folder:
        d = ctx.resolve(folder)
        srcs += sorted(list(d.glob("*.dxf")) + list(d.glob("*.dwg")))
    if not srcs:
        raise CadError("Give files or a folder")
    out_dir = ctx.resolve(out_folder) if out_folder else None
    done, failed = [], []
    for s in srcs:
        try:
            doc = dwg.read_dwg(s) if s.suffix.lower() == ".dwg" else ezdxf.readfile(s)
            target = (out_dir or s.parent) / (s.stem + "." + to.lower())
            target.parent.mkdir(parents=True, exist_ok=True)
            if to.lower() == "dwg":
                dwg.write_dwg(doc, target, version)
            else:
                rel = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021",
                       "R2010": "AC1024", "R2013": "AC1027", "R2018": "AC1032"}
                if version not in rel:
                    raise CadError(f"version must be one of {list(rel)}")
                doc.dxfversion = rel[version]
                doc.saveas(target)
            done.append(str(target))
        except Exception as exc:  # keep going with the other files
            failed.append({"file": str(s), "error": str(exc)[:300]})
    return {"converted": done, "failed": failed}


# ---------------------------------------------------------------------------
# layers: states and translation
# ---------------------------------------------------------------------------


# Layer states as AutoCAD keeps them: LAYER table extension dictionary -> ACAD_LAYERSTATES ->
# one XRECORD per state (layout measured in AutoCAD 2024): 91 mask, 301 description, 290 0,
# 302 current layer, then per layer 330 LAYER handle, 90 flags (1 off, 2 frozen, 4 locked,
# 8 plotted, 16 frozen in new viewports), 62 colour, 370 lineweight, 331 LTYPE handle,
# 1 'Color_N' (colour-dependent plot styles) or 390 plot style placeholder, 440 transparency,
# 92 true colour (0xC2RRGGBB).
LS_BITS = {"on": 1, "frozen": 2, "locked": 4, "plot": 8, "new_vp_frozen": 16, "color": 32, "linetype": 64,
           "lineweight": 128, "plotstyle": 256, "current_vp": 512, "transparency": 1024}


def _xdict_dict(ctx: Ctx, key: str, create: bool):
    head = ctx.doc.layers.head
    if not head.has_extension_dict:
        if not create:
            return None
        head.new_extension_dict()
    xd = head.get_extension_dict()
    d = xd.get(key)
    if d is None and create:
        d = xd.add_dictionary(key, hard_owned=True)
    return d


def _find_key(d, name: str):
    if d is None:
        return None
    for k in d.keys():
        if k.lower() == name.lower():
            return k
    return None


def _i32(v: int) -> int:
    return v - (1 << 32) if v >= (1 << 31) else v


def _state_tags(ctx: Ctx, mask: int, description: str) -> list:
    from ezdxf.colors import float2transparency

    doc = ctx.doc
    tags = [(91, mask), (301, description or ""), (290, 0), (302, doc.header.get("$CLAYER", "0"))]
    colour_dep = doc.header.get("$PSTYLEMODE", 1) == 1
    ps_dict = doc.rootdict.get("ACAD_PLOTSTYLENAME")
    for la in doc.layers:
        flags = ((0 if la.is_on() else 1) | (2 if la.is_frozen() else 0) | (4 if la.is_locked() else 0)
                 | (8 if la.dxf.get("plot", 1) else 0) | (16 if la.dxf.get("flags", 0) & 2 else 0))
        aci = abs(la.dxf.get("color", 7)) or 7
        tags += [(330, la.dxf.handle), (90, flags), (62, aci), (370, la.dxf.get("lineweight", -3))]
        lt = doc.linetypes.get(la.dxf.get("linetype", "Continuous")) or doc.linetypes.get("Continuous")
        if lt is not None:
            tags.append((331, lt.dxf.handle))
        if colour_dep:
            tags.append((1, f"Color_{aci}"))
        elif ps_dict is not None:
            h = la.dxf.get("plotstyle_handle") or (ps_dict.get("Normal").dxf.handle if ps_dict.get("Normal") else None)
            if h:
                tags.append((390, h))
        t = la.transparency
        tags.append((440, 0 if not t else float2transparency(t)))
        if la.rgb:
            r, g, b = la.rgb
            tags.append((92, _i32(0xC2000000 | (r << 16) | (g << 8) | b)))
    return tags


def _parse_state(xr) -> dict:
    tags = [(t.code, t.value) for t in xr.tags]
    head, layers, cur = {}, [], None
    for code, val in tags:
        if code == 330:
            cur = {"handle": val}
            layers.append(cur)
        elif cur is None:
            head[code] = val
        else:
            cur[code] = val
    return {"mask": int(head.get(91, 2047)), "description": head.get(301, ""), "current": head.get(302, "0"),
            "layers": layers}


@op("layer", "state", mutates=True)
def layer_state(ctx: Ctx, action: str, name: str | None = None, description: str = "", properties: list | None = None):
    """LAYERSTATE (Layer States Manager): action save | restore | delete | list. Stored natively in the drawing (ACAD_LAYERSTATES), so AutoCAD's Layer States Manager sees and restores them, and states saved in AutoCAD can be listed/restored here. properties = which settings to save/restore (on, frozen, locked, plot, new_vp_frozen, color, linetype, lineweight, plotstyle, transparency; default all)."""
    from ezdxf.colors import transparency2float

    doc = ctx.doc
    d = _xdict_dict(ctx, "ACAD_LAYERSTATES", create=action == "save")
    if action == "list":
        out = []
        for k in (d.keys() if d is not None else []):
            st = _parse_state(d[k])
            out.append({"name": k, "description": st["description"], "layers": len(st["layers"])})
        return {"states": sorted(x["name"] for x in out), "details": sorted(out, key=lambda x: x["name"])}
    if not name:
        raise CadError("Give a state name")
    key = _find_key(d, name)
    if action == "save":
        bad = [p for p in (properties or []) if p not in LS_BITS]
        if bad:
            raise CadError(f"Unknown properties {bad}; use {list(LS_BITS)}")
        mask = sum(LS_BITS[p] for p in properties) if properties else 2047
        if key is not None:
            d.remove(key)
        xr = d.add_xrecord(name)
        xr.reset(_state_tags(ctx, mask, description))
        return {"action": "save", "state": name, "layers": len(doc.layers), "mask": mask}
    if key is None:
        raise CadError(f"No layer state '{name}'. States: {sorted(d.keys()) if d is not None else []}")
    if action == "delete":
        d.remove(key)
        return {"action": "delete", "state": key}
    if action != "restore":
        raise CadError("action: save, restore, delete, list")
    st = _parse_state(d[key])
    m = st["mask"]
    restored = 0
    for ent in st["layers"]:
        la = doc.entitydb.get(str(ent["handle"]))
        if la is None or la.dxftype() != "LAYER":
            continue
        f = int(ent.get(90, 8))
        if m & 1:
            la.off() if f & 1 else la.on()
        if m & 2:
            la.freeze() if f & 2 else la.thaw()
        if m & 4:
            la.lock() if f & 4 else la.unlock()
        if m & 8:
            la.dxf.plot = 1 if f & 8 else 0
        if m & 16:
            la.dxf.flags = (la.dxf.get("flags", 0) | 2) if f & 16 else (la.dxf.get("flags", 0) & ~2)
        if m & 32 and 62 in ent:
            on = la.is_on()
            la.color = abs(int(ent[62]))
            la.on() if on else la.off()
            if 92 in ent:
                v = int(ent[92]) & 0xFFFFFFFF
                la.rgb = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
            elif la.dxf.hasattr("true_color"):
                la.dxf.discard("true_color")
        if m & 64 and 331 in ent:
            lt = doc.entitydb.get(str(ent[331]))
            if lt is not None:
                la.dxf.linetype = lt.dxf.name
        if m & 128 and 370 in ent:
            la.dxf.lineweight = int(ent[370])
        if m & 1024 and 440 in ent:
            v = int(ent[440])
            la.transparency = transparency2float(v) if v else 0.0
        restored += 1
    if st["current"] and doc.layers.has_entry(st["current"]):
        doc.header["$CLAYER"] = st["current"]
    return {"action": "restore", "state": key, "layers": restored}


# Layer filters as the Layer Properties Manager keeps them: LAYER table extension dictionary ->
# ACLYDICTIONARY -> anonymous *A<n> XRECORDs: property filter (1 AcLyLayerFilter, 90 1, 300 name,
# 301 expression such as NAME=="UT*" AND ON=="True"), group filter (1 AcLyLayerGroup, 90 1,
# 300 name, 330 layer handles).
_FILTER_PROPS = {"name": "NAME", "on": "ON", "frozen": "FROZEN", "locked": "LOCKED", "plot": "PLOTTABLE",
                 "color": "COLOR", "linetype": "LINETYPE", "description": "DESCRIPTION"}


def _filter_expr(criteria: dict) -> str:
    parts = []
    for k, v in criteria.items():
        if k not in _FILTER_PROPS:
            raise CadError(f"Unknown filter property {k}; use {list(_FILTER_PROPS)}")
        if isinstance(v, bool):
            v = "True" if v else "False"
        parts.append(f'{_FILTER_PROPS[k]}=="{v}"')
    return " AND ".join(parts)


def _expr_match(expr: str, layer) -> bool:
    import fnmatch
    import re

    vals = {"NAME": layer.dxf.name, "ON": str(layer.is_on()), "FROZEN": str(layer.is_frozen()),
            "LOCKED": str(layer.is_locked()), "PLOTTABLE": str(bool(layer.dxf.get("plot", 1))),
            "COLOR": str(abs(layer.dxf.get("color", 7))), "LINETYPE": layer.dxf.get("linetype", "Continuous"),
            "DESCRIPTION": layer.description or ""}
    clean = expr.replace("(", " ").replace(")", " ")
    for alt in re.split(r"\s+OR\s+", clean.strip(), flags=re.IGNORECASE):
        ok = True
        for cond in re.split(r"\s+AND\s+", alt.strip(), flags=re.IGNORECASE):
            m = re.match(r'\s*(NOT\s+)?(\w+)\s*(==|!=)\s*"([^"]*)"\s*$', cond, flags=re.IGNORECASE)
            if not m:
                raise CadError(f"Cannot read filter condition: {cond!r}")
            neg, prop, opr, val = m.groups()
            hit = fnmatch.fnmatch(vals.get(prop.upper(), "").lower(), val.lower())
            if opr == "!=":
                hit = not hit
            if neg:
                hit = not hit
            ok = ok and hit
        if ok:
            return True
    return False


@op("layer", "filter", mutates=True)
def layer_filter(ctx: Ctx, action: str = "list", name: str | None = None, criteria: dict | None = None,
                 expression: str | None = None, layers: list | None = None):
    """Named layer filters as in AutoCAD's Layer Properties Manager (stored natively in ACLYDICTIONARY). action create | list | delete | apply. Property filter: criteria={"name": "UT*", "on": true, "color": 1, ...} (name/linetype/description take * and ?) or a raw expression like NAME=="UT*" AND FROZEN=="False". Group filter: layers=[...]. apply returns the layers the filter selects."""
    doc = ctx.doc
    d = _xdict_dict(ctx, "ACLYDICTIONARY", create=action == "create")
    recs = []
    for k in (d.keys() if d is not None else []):
        tags = {t.code: t.value for t in d[k].tags if t.code in (1, 300, 301)}
        hs = [t.value for t in d[k].tags if t.code == 330]
        recs.append({"key": k, "kind": tags.get(1), "name": tags.get(300), "expression": tags.get(301), "handles": hs})
    if action == "list":
        return {"filters": [{"name": r["name"], "type": "csoport" if r["kind"] == "AcLyLayerGroup" else "tulajdonság",
                             "expression": r["expression"], "layers": len(r["handles"]) or None} for r in recs]}
    if not name:
        raise CadError("Give a filter name")
    rec = next((r for r in recs if (r["name"] or "").lower() == name.lower()), None)
    if action == "create":
        if rec is not None:
            d.remove(rec["key"])
        n = 1
        while f"*A{n}" in d:
            n += 1
        xr = d.add_xrecord(f"*A{n}")
        if layers:
            hs = []
            for ln in layers:
                if not doc.layers.has_entry(ln):
                    raise CadError(f"No layer {ln}")
                hs.append(doc.layers.get(ln).dxf.handle)
            xr.reset([(1, "AcLyLayerGroup"), (90, 1), (300, name)] + [(330, h) for h in hs])
            return {"action": "create", "filter": name, "type": "csoport", "layers": len(hs)}
        expr = expression or _filter_expr(criteria or {})
        if not expr:
            raise CadError("Give criteria, expression or layers")
        for la in doc.layers:  # validates the expression
            _expr_match(expr, la)
        xr.reset([(1, "AcLyLayerFilter"), (90, 1), (300, name), (301, expr)])
        return {"action": "create", "filter": name, "type": "tulajdonság", "expression": expr}
    if rec is None:
        raise CadError(f"No layer filter '{name}'. Filters: {[r['name'] for r in recs]}")
    if action == "delete":
        d.remove(rec["key"])
        return {"action": "delete", "filter": rec["name"]}
    if action == "apply":
        if rec["kind"] == "AcLyLayerGroup":
            names = [doc.entitydb[h].dxf.name for h in rec["handles"] if h in doc.entitydb]
        else:
            names = [la.dxf.name for la in doc.layers if _expr_match(rec["expression"] or "", la)]
        return {"filter": rec["name"], "layers": names}
    raise CadError("action: create, list, delete, apply")


@op("layer", "translate", mutates=True)
def layer_translate(ctx: Ctx, mapping: dict):
    """LAYTRANS: map layers to a standard: {"old": "NEW"} or {"old": {"name": "NEW", "color": 1, "linetype": "DASHED", "lineweight": 0.35}}. Entities move to the new layers, old layers are removed."""
    doc = ctx.doc
    moved = 0
    for old, target in mapping.items():
        spec = {"name": target} if isinstance(target, str) else dict(target)
        new = spec["name"]
        ensure_layer(doc, new)
        la = doc.layers.get(new)
        if "color" in spec:
            aci, rgb = parse_color(spec["color"])
            if rgb:
                la.rgb = rgb
            else:
                la.color = aci
        if "linetype" in spec:
            from .core import ensure_linetype

            ensure_linetype(doc, spec["linetype"])
            la.dxf.linetype = spec["linetype"]
        if "lineweight" in spec:
            la.dxf.lineweight = parse_lineweight(spec["lineweight"])
        if old.lower() == new.lower():
            continue
        for lay in doc.layouts_and_blocks():
            for e in lay:
                if e.dxf.get("layer", "0").lower() == old.lower():
                    e.dxf.layer = new
                    moved += 1
        if doc.layers.has_entry(old) and old not in ("0", "Defpoints"):
            doc.layers.remove(old)
    return {"entities_moved": moved, "layers": list(mapping)}


# ---------------------------------------------------------------------------
# blocks: attribute definitions, editable arrays
# ---------------------------------------------------------------------------


@op("block", "edit_attdef", mutates=True)
def edit_attdef(ctx: Ctx, block: str, tag: str, new_tag: str | None = None, prompt: str | None = None,
                default: str | None = None, height: float | None = None, invisible: bool | None = None,
                constant: bool | None = None, order: list | None = None, sync: bool = True):
    """BATTMAN: edit an attribute definition (tag, prompt, default, height, invisible, constant) and/or set the order of all tags (order=[...]); sync updates existing references."""
    blk = ctx.doc.blocks.get(block)
    if blk is None:
        raise CadError(f"Block '{block}' does not exist")
    defs = {a.dxf.tag.upper(): a for a in blk.attdefs()}
    a = defs.get(tag.upper())
    if a is None:
        raise CadError(f"No attribute '{tag}' in {block}: {list(defs)}")
    if new_tag:
        a.dxf.tag = new_tag.upper()
    if prompt is not None:
        a.dxf.prompt = prompt
    if default is not None:
        a.dxf.text = default
    if height is not None:
        a.dxf.height = float(height)
    if invisible is not None:
        a.is_invisible = bool(invisible)
    if constant is not None:
        a.is_const = bool(constant)
    if order:
        current = {d.dxf.tag.upper(): d for d in blk.attdefs()}
        for t in [o.upper() for o in order]:
            if t not in current:
                raise CadError(f"Unknown tag in order: {t}")
            d = current[t]
            copy = d.copy()
            blk.delete_entity(d)
            blk.add_entity(copy)
    if sync:
        from .ops_more import sync_attributes

        sync_attributes(ctx, block)
    return {"block": block, "tags": [d.dxf.tag for d in blk.attdefs()]}


@op("edit", "array_block", mutates=True)
def array_block(ctx: Ctx, sel, rows: int, cols: int, row_spacing: float, col_spacing: float, base_point=None,
                name: str | None = None, delete_originals: bool = True):
    """Editable rectangular array (associative-style): the selection becomes a block shown as a MINSERT grid; change it later with edit.array_edit."""
    from ezdxf import bbox

    ents = select_from(ctx, sel)
    bp = vec(base_point) if base_point is not None else bbox.extents(ents).extmin
    i = 1
    bname = name or "ARRAY_1"
    while ctx.doc.blocks.get(bname) is not None and not name:
        i += 1
        bname = f"ARRAY_{i}"
    blk = ctx.doc.blocks.new(bname, base_point=bp)
    lay = ents[0].get_layout()
    for e in ents:
        blk.add_entity(e.copy())
        if delete_originals:
            e.get_layout().delete_entity(e)
    ref = lay.add_blockref(bname, bp)
    ref.dxf.row_count, ref.dxf.column_count = int(rows), int(cols)
    ref.dxf.row_spacing, ref.dxf.column_spacing = float(row_spacing), float(col_spacing)
    return {"handle": ref.dxf.handle, "block": bname, "items": int(rows) * int(cols)}


@op("edit", "array_edit", mutates=True)
def array_edit(ctx: Ctx, handle: str, rows: int | None = None, cols: int | None = None,
               row_spacing: float | None = None, col_spacing: float | None = None):
    """ARRAYEDIT for arrays made by edit.array_block: change row/column count and spacing."""
    ref = ctx.entity(handle)
    if ref.dxftype() != "INSERT":
        raise CadError("handle must be an array made by edit.array_block")
    if rows is not None:
        ref.dxf.row_count = int(rows)
    if cols is not None:
        ref.dxf.column_count = int(cols)
    if row_spacing is not None:
        ref.dxf.row_spacing = float(row_spacing)
    if col_spacing is not None:
        ref.dxf.column_spacing = float(col_spacing)
    return {"handle": handle, "items": ref.dxf.row_count * ref.dxf.column_count}


# ---------------------------------------------------------------------------
# query: extraction and select similar
# ---------------------------------------------------------------------------


@op("query", "extract", mutates=True)
def extract(ctx: Ctx, sel=None, fields: list | None = None, path: str | None = None, table_at=None,
            text_height: float = 2.5):
    """DATAEXTRACTION: one row per entity with fields (handle, type, layer, color, block, attributes, length, area, x, y, text) -> returned, written to CSV (path) and/or placed as a table (table_at)."""
    from .ops_query import _area, _length

    ents = select_from(ctx, sel if sel is not None else {"all": True})
    fields = fields or ["handle", "type", "layer", "block", "attributes"]
    rows = []
    for e in ents:
        d = describe(e)
        r = {}
        for f in fields:
            if f == "attributes":
                r[f] = "; ".join(f"{k}={v}" for k, v in (d.get("attributes") or {}).items())
            elif f == "block":
                r[f] = d.get("block", "")
            elif f == "length":
                try:
                    r[f] = round(_length(e), 4)
                except CadError:
                    r[f] = ""
            elif f == "area":
                try:
                    r[f] = round(_area(e)[0], 4)
                except CadError:
                    r[f] = ""
            elif f in ("x", "y"):
                p = d.get("insert") or d.get("center") or d.get("location") or d.get("start") or [None, None]
                r[f] = p[0] if f == "x" else p[1]
            else:
                r[f] = d.get(f, "")
        rows.append(r)
    out = {"rows": rows[:500], "count": len(rows)}
    if path:
        p = ctx.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)
        p.write_text(buf.getvalue(), encoding="utf-8-sig")
        out["csv"] = str(p)
    if table_at is not None:
        from .ops_annotate import table

        t = table(ctx, insert=table_at, rows=[fields] + [[str(r[f]) for f in fields] for r in rows],
                  text_height=text_height, row_height=text_height * 2.4,
                  col_widths=[max(8, max(len(str(r[f])) for r in rows + [{f: f}]) * text_height * 0.9) for f in fields])
        out["table_handles"] = len(t["handles"])
    return out


@op("query", "similar")
def similar(ctx: Ctx, handle: str, match: list | None = None, space=None):
    """SELECTSIMILAR: entities like the given one (same type plus layer, colour, block name, text style … as listed in match)."""
    ref = ctx.entity(handle)
    match = match or ["type", "layer", "block"]
    out = []
    for e in ctx.layout(space):
        ok = True
        for m in match:
            if m == "type":
                ok &= e.dxftype() == ref.dxftype()
            elif m == "block":
                ok &= e.dxftype() != "INSERT" or e.dxf.name == ref.dxf.get("name")
            elif m == "style":
                ok &= e.dxf.get("style") == ref.dxf.get("style")
            else:
                ok &= e.dxf.get(m) == ref.dxf.get(m)
        if ok:
            out.append(e)
    return {"handles": handles(out), "count": len(out)}



@op("draw", "shape", mutates=True)
def shape(ctx: Ctx, name: str, insert, size: float = 1.0, shx_file: str = "ltypeshp.shx", rotation: float = 0.0,
          space=None, **props):
    """SHAPE: insert a shape from an SHX shape file (e.g. ltypeshp.shx); AutoCAD needs the .shx on its support path."""
    if ctx.doc.styles.find_shx(shx_file) is None:  # unnamed shape-file entry in the STYLE table
        ctx.doc.styles.add_shx(shx_file)
    e = ctx.layout(space).add_shape(name, vec(insert), float(size), dxfattribs={"rotation": float(rotation)})
    return {"handles": [finish(ctx.doc, e, pick_props(props)).dxf.handle]}
