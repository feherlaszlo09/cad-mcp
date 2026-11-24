"""Tool `view`: render the drawing to PNG for the model to look at, and export
PNG/PDF/SVG files (to scale on a paper size)."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf import bbox, units as ezunits  # noqa: E402
from ezdxf.math import Vec3  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402
from ezdxf.addons.drawing.properties import LayoutProperties  # noqa: E402

from .core import CadError, Ctx, op, vec  # noqa: E402
from .ops_tables import PAPER  # noqa: E402

T = "view"
MAX_LABELS = 400


def _config(dark: bool) -> Configuration:
    return Configuration(background_policy=BackgroundPolicy.DEFAULT, color_policy=ColorPolicy.COLOR)


def _plot_style_fn(ctx: Ctx, plot_style):
    """Property override applying a plot style: 'monochrome', 'grayscale' or a .ctb file."""
    if not plot_style:
        return None
    if plot_style in ("monochrome", "monochrome.ctb"):
        def mono(entity, props):
            props.color = "#000000"
        return mono
    if plot_style in ("grayscale", "grayscale.ctb"):
        def gray(entity, props):
            c = props.color.lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            v = int(0.299 * r + 0.587 * g + 0.114 * b)
            v = min(v, 160) if v > 200 else v  # white/yellow would vanish on paper
            props.color = "#%02x%02x%02x" % (v, v, v)
        return gray
    from ezdxf.addons import acadctb

    path = ctx.resolve(str(plot_style))
    if not path.is_file():
        raise CadError(f"Plot style table not found: {path} (use 'monochrome', 'grayscale' or a .ctb path)")
    ctb = acadctb.load(str(path))

    def apply(entity, props):
        aci = props.pen if 1 <= props.pen <= 255 else 7
        style = ctb[aci]
        if not style.has_object_color():
            props.color = "#%02x%02x%02x" % tuple(style.color)
        lw = ctb.get_lineweight(aci)
        if lw:
            props.lineweight = lw
    return apply


def _draw(ctx: Ctx, fig, ax, space, dark, layers, plot_style=None):
    doc = ctx.doc
    layout = ctx.layout(space)
    rctx = RenderContext(doc)
    rctx.set_current_layout(layout)
    wanted = {n.lower() for n in layers} if layers else None

    def keep(e) -> bool:
        return wanted is None or e.dxf.get("layer", "0").lower() in wanted

    props = LayoutProperties.from_layout(layout)
    # ACI 7 follows the background: black lines on white paper, white on black
    props.set_colors("#000000" if dark else "#ffffff")
    fe = Frontend(rctx, MatplotlibBackend(ax, adjust_figure=False), config=_config(dark))
    fn = _plot_style_fn(ctx, plot_style)
    if fn:
        fe.push_property_override_function(fn)
    fe.draw_layout(layout, finalize=True, filter_func=keep, layout_properties=props)
    return layout


def _region(layout, region, margin=0.03):
    if region:
        (x1, y1), (x2, y2) = [tuple(vec(p).vec2) for p in region]
        lo, hi = (min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))
    else:
        ext = bbox.extents(layout, fast=True)
        if not ext.has_data:
            return None
        lo, hi = (ext.extmin.x, ext.extmin.y), (ext.extmax.x, ext.extmax.y)
    w, h = max(hi[0] - lo[0], 1e-9), max(hi[1] - lo[1], 1e-9)
    m = max(w, h) * margin
    return (lo[0] - m, lo[1] - m), (hi[0] + m, hi[1] + m)


def _labels(ax, layout, lim, dark):
    (x1, y1), (x2, y2) = lim
    n = 0
    for e in layout:
        if n >= MAX_LABELS:
            break
        ext = bbox.extents([e], fast=True)
        if not ext.has_data:
            continue
        c = ext.center
        if x1 <= c.x <= x2 and y1 <= c.y <= y2:
            ax.text(c.x, c.y, e.dxf.handle, fontsize=6, color="#ff5050" if dark else "#d00000",
                    ha="center", va="center", alpha=0.85)
            n += 1
    return n


def render_png(ctx: Ctx, space=None, region=None, width: int = 1200, height: int = 900,
               dark: bool = False, show_handles: bool = False, axes: bool = False, layers=None) -> tuple[bytes, dict]:
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0.06, 0.05, 0.92, 0.92] if axes else [0, 0, 1, 1])
    try:
        layout = _draw(ctx, fig, ax, space, dark, layers)
        lim = _region(layout, region)
        info: dict = {"space": layout.name}
        if lim is None:
            info["empty"] = True
            lim = ((0, 0), (100, 100))
        (x1, y1), (x2, y2) = lim
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(x1, x2)
        ax.set_ylim(y1, y2)
        ax.set_anchor("C")
        if axes:
            ax.set_axis_on()
            ax.xaxis.set_visible(True)
            ax.yaxis.set_visible(True)
            for sp in ax.spines.values():
                sp.set_visible(True)
            ax.grid(True, alpha=0.25, linewidth=0.5)
            ax.tick_params(labelsize=7)
        if show_handles:
            info["labels"] = _labels(ax, layout, lim, dark)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="black" if dark else "white")
        rx1, rx2 = ax.get_xlim()
        ry1, ry2 = ax.get_ylim()
        info["visible_region"] = [[round(float(rx1), 4), round(float(ry1), 4)],
                                  [round(float(rx2), 4), round(float(ry2), 4)]]
        info["pixels"] = [width, height]
        return buf.getvalue(), info
    finally:
        plt.close(fig)


@op(T, "png")
def png(ctx: Ctx, space=None, region=None, width: int = 1200, height: int = 900, dark: bool = False,
        show_handles: bool = False, axes: bool = False, layers=None):
    """Render to an image you can see. region=[[x1,y1],[x2,y2]] zooms in; show_handles labels every entity with its handle; axes shows coordinates; layers=[...] shows only those."""
    data, info = render_png(ctx, space, region, width, height, dark, show_handles, axes, layers)
    return {"_image": data, **info}


def _unit_mm(doc) -> float:
    try:
        return ezunits.conversion_factor(doc.units, ezunits.MM) if doc.units else 1.0
    except Exception:
        return 1.0


FORMATS = ("pdf", "svg", "png", "jpg", "jpeg", "tif", "tiff", "eps", "ps")


def _page(ctx: Ctx, space=None, paper: str = "A3", landscape: bool = True, scale: float | None = None,
          center=None, region=None, margins: float = 10, dark: bool = False, dpi: int = 300, layers=None,
          plot_style=None):
    """Render one sheet into a new matplotlib figure; returns (figure, info)."""
    layout = ctx.layout(space)
    is_paper = layout.name != "Model" and not str(space or "").lower().startswith("block:")
    if is_paper:
        lmin, lmax = layout.dxf.limmin, layout.dxf.limmax
        pw, ph = lmax.x - lmin.x, lmax.y - lmin.y
        if pw <= 0 or ph <= 0:
            pw, ph = layout.dxf.paper_width, layout.dxf.paper_height
            lmin = vec((0, 0))
    else:
        if paper.upper() not in PAPER:
            raise CadError(f"paper must be one of {list(PAPER)}")
        pw, ph = PAPER[paper.upper()]
        if not landscape:
            pw, ph = ph, pw
    fig = plt.figure(figsize=(pw / 25.4, ph / 25.4), dpi=dpi)
    try:
        if is_paper:
            ax = fig.add_axes([0, 0, 1, 1])
            _draw(ctx, fig, ax, space, dark, layers, plot_style)
            ax.set_xlim(lmin.x, lmin.x + pw)
            ax.set_ylim(lmin.y, lmin.y + ph)
            info = {"paper_mm": [pw, ph], "scale": "1:1 (layout)", "space": layout.name}
        else:
            m = float(margins)
            ax = fig.add_axes([m / pw, m / ph, 1 - 2 * m / pw, 1 - 2 * m / ph])
            _draw(ctx, fig, ax, space, dark, layers, plot_style)
            pr_w, pr_h = pw - 2 * m, ph - 2 * m
            if scale:
                unit_mm = _unit_mm(ctx.doc)
                vis_w = pr_w / (float(scale) * unit_mm)
                vis_h = pr_h / (float(scale) * unit_mm)
                if center is not None:
                    cx, cy = tuple(vec(center).vec2)
                else:
                    lim = _region(layout, region, 0) or ((0, 0), (vis_w, vis_h))
                    cx, cy = (lim[0][0] + lim[1][0]) / 2, (lim[0][1] + lim[1][1]) / 2
                ax.set_xlim(cx - vis_w / 2, cx + vis_w / 2)
                ax.set_ylim(cy - vis_h / 2, cy + vis_h / 2)
                info = {"paper_mm": [pw, ph], "scale": f"1:{round(1 / float(scale), 3)}", "space": layout.name}
            else:
                lim = _region(layout, region, 0.02)
                if lim:
                    (x1, y1), (x2, y2) = lim
                    ax.set_aspect("equal", adjustable="datalim")
                    ax.set_xlim(x1, x2)
                    ax.set_ylim(y1, y2)
                info = {"paper_mm": [pw, ph], "scale": "fit to paper", "space": layout.name}
        return fig, info
    except Exception:
        plt.close(fig)
        raise


@op(T, "export")
def export(ctx: Ctx, path: str, space=None, paper: str = "A3", landscape: bool = True,
           scale: float | None = None, center=None, region=None, margins: float = 10,
           dark: bool = False, dpi: int = 300, layers=None, plot_style: str | None = None):
    """Write PDF, SVG, PNG, JPG, TIFF or EPS (PLOT). Model space: fits the drawing (or region) on the paper, or uses scale = paper/real, e.g. 0.01 for 1:100, centered on center. Paper space layouts print at 1:1 on their own paper size. plot_style = 'monochrome', 'grayscale' or a .ctb file (colours and lineweights by colour)."""
    p = ctx.resolve(path)
    fmt = p.suffix.lower().lstrip(".")
    if fmt not in FORMATS:
        raise CadError(f"path must end in one of {['.' + f for f in FORMATS]}")
    fig, info = _page(ctx, space, paper, landscape, scale, center, region, margins, dark, dpi, layers, plot_style)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, format={"jpg": "jpeg", "tif": "tiff"}.get(fmt, fmt), dpi=dpi,
                    facecolor="black" if dark else "white")
    finally:
        plt.close(fig)
    return {"exported": str(p), "format": fmt, **info}


@op(T, "publish")
def publish(ctx: Ctx, path: str, sheets: list | None = None, plot_style: str | None = None, dpi: int = 200):
    """PUBLISH: multi-page PDF. sheets = list of layout names, or of dicts with view.export options ({space, paper, scale, region, center, layers, landscape}); default: every paper space layout, or the model if there is none."""
    from matplotlib.backends.backend_pdf import PdfPages

    p = ctx.resolve(path)
    if p.suffix.lower() != ".pdf":
        raise CadError("publish writes a .pdf")
    if not sheets:
        names = [n for n in ctx.doc.layout_names_in_taborder() if n != "Model"]
        sheets = names or ["model"]
    p.parent.mkdir(parents=True, exist_ok=True)
    pages = []
    with PdfPages(p) as pdf:
        for sh in sheets:
            opts = {"space": sh} if isinstance(sh, str) else dict(sh)
            opts.setdefault("plot_style", plot_style)
            opts.setdefault("dpi", dpi)
            fig, info = _page(ctx, **opts)
            try:
                pdf.savefig(fig, facecolor="white")
            finally:
                plt.close(fig)
            pages.append(info)
    return {"exported": str(p), "pages": len(pages), "sheets": pages}


def _triangles(ctx: Ctx, ents):
    from ezdxf.acis import api as acis
    from ezdxf.render import MeshBuilder

    tris = []

    def add_mesh(vertices, faces):
        for f in faces:
            f = list(f)
            for i in range(1, len(f) - 1):
                tris.append((Vec3(vertices[f[0]]), Vec3(vertices[f[i]]), Vec3(vertices[f[i + 1]])))

    for e in ents:
        t = e.dxftype()
        if t == "MESH":
            add_mesh(list(e.vertices), [list(f) for f in e.faces])
        elif t == "3DFACE":
            v = [Vec3(p) for p in e.wcs_vertices()]
            tris.append((v[0], v[1], v[2]))
            if len(v) == 4 and not v[3].isclose(v[2]):
                tris.append((v[0], v[2], v[3]))
        elif t == "POLYLINE" and e.is_poly_face_mesh:
            mb = MeshBuilder.from_polyface(e)
            add_mesh(mb.vertices, mb.faces)
        elif t in ("3DSOLID", "BODY", "REGION"):
            try:
                for body in acis.load_dxf(e):
                    for m in acis.mesh_from_body(body):
                        add_mesh(m.vertices, m.faces)
            except Exception as exc:
                raise CadError(f"Cannot read the ACIS data of {e.dxf.handle} (curved ACIS faces are not supported): {exc}") from exc
    return tris


@op(T, "export_3d")
def export_3d(ctx: Ctx, path: str, sel=None):
    """Export 3D geometry (MESH, 3DFACE, polyface, faceted 3DSOLID) to STL or OBJ (3D printing, other 3D software)."""
    from .core import select_from

    ents = select_from(ctx, sel if sel is not None else {"all": True})
    tris = _triangles(ctx, ents)
    if not tris:
        raise CadError("No 3D faces in the selection")
    p = ctx.resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fmt = p.suffix.lower()
    if fmt == ".stl":
        lines = ["solid cadmcp"]
        for a, b, c in tris:
            n = (b - a).cross(c - a)
            n = n.normalize() if n.magnitude > 0 else n
            lines += [f"facet normal {n.x:e} {n.y:e} {n.z:e}", " outer loop"] + \
                [f"  vertex {v.x:e} {v.y:e} {v.z:e}" for v in (a, b, c)] + [" endloop", "endfacet"]
        lines.append("endsolid cadmcp")
    elif fmt == ".obj":
        lines, idx = ["# CAD MCP export"], {}
        faces = []
        for tri in tris:
            ids = []
            for v in tri:
                key = (round(v.x, 9), round(v.y, 9), round(v.z, 9))
                if key not in idx:
                    idx[key] = len(idx) + 1
                    lines.append(f"v {key[0]} {key[1]} {key[2]}")
                ids.append(idx[key])
            faces.append(f"f {ids[0]} {ids[1]} {ids[2]}")
        lines += faces
    else:
        raise CadError("path must end in .stl or .obj")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"exported": str(p), "triangles": len(tris)}
