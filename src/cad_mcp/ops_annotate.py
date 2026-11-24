"""Tool `annotate`: text, multiline text, dimensions, leaders, tables."""

from __future__ import annotations

from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.math import Vec2

from .core import CadError, Ctx, finish, op, pick_props, vec, vecs

T = "annotate"

TEXT_ALIGN = {a.name.lower(): a for a in TextEntityAlignment}
MTEXT_ATTACH = {a.name.lower(): a for a in MTextEntityAlignment}


def _done(*ents):
    return {"handles": [e.dxf.handle for e in ents if e is not None]}


@op(T, "text", mutates=True)
def text(ctx: Ctx, text: str, insert, height: float = 2.5, rotation: float = 0,
         align: str = "left", style: str = "Standard", width_factor: float = 1.0,
         space=None, **props):
    """Single-line TEXT. align: left, center, right, middle, top_left, top_center, top_right, middle_left, middle_center, middle_right, bottom_left, bottom_center, bottom_right, aligned, fit."""
    a = TEXT_ALIGN.get(align.lower())
    if a is None:
        raise CadError(f"Bad align '{align}'. Use {sorted(TEXT_ALIGN)}")
    if not ctx.doc.styles.has_entry(style):
        raise CadError(f"Text style '{style}' does not exist (style.list_text_styles)")
    e = ctx.layout(space).add_text(text, height=float(height), rotation=float(rotation),
                                   dxfattribs={"style": style, "width": float(width_factor)})
    e.set_placement(vec(insert), align=a)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "mtext", mutates=True)
def mtext(ctx: Ctx, text: str, insert, char_height: float = 2.5, width: float | None = None,
          attachment: str = "top_left", rotation: float = 0, style: str = "Standard",
          line_spacing: float = 1.0, space=None, **props):
    """Multiline text (MTEXT). Use \\n for new lines; inline codes like \\P, {\\b1;bold} work. attachment: top_left ... bottom_right."""
    a = MTEXT_ATTACH.get(attachment.lower())
    if a is None:
        raise CadError(f"Bad attachment '{attachment}'. Use {sorted(MTEXT_ATTACH)}")
    attribs = {"char_height": float(char_height), "rotation": float(rotation), "style": style,
               "line_spacing_factor": float(line_spacing)}
    if width:
        attribs["width"] = float(width)
    e = ctx.layout(space).add_mtext(text.replace("\n", "\\P"), dxfattribs=attribs)
    e.set_location(vec(insert), attachment_point=a)
    return _done(finish(ctx.doc, e, pick_props(props)))


def _ds(ctx: Ctx, name: str | None) -> str:
    """Explicit style, else the drawing's current dimension style ($DIMSTYLE), else Standard."""
    doc = ctx.doc
    if name:
        if not doc.dimstyles.has_entry(name):
            raise CadError(f"Dimension style '{name}' does not exist (style.list_dimstyles)")
        return name
    current = doc.header.get("$DIMSTYLE", "Standard")
    if doc.dimstyles.has_entry(current):
        return current
    return "Standard"


def _dim(ctx: Ctx, dimobj, props):
    dimobj.render()
    return _done(finish(ctx.doc, dimobj.dimension, pick_props(props)))


def _override(text_height=None, arrow_size=None, decimals=None, override=None):
    o = dict(override or {})
    if text_height:
        o["dimtxt"] = float(text_height)
    if arrow_size:
        o["dimasz"] = float(arrow_size)
    if decimals is not None:
        o["dimdec"] = int(decimals)
    return o


@op(T, "dim_linear", mutates=True)
def dim_linear(ctx: Ctx, p1, p2, location, angle: float = 0, text: str = "<>",
               dimstyle: str | None = None, text_height: float | None = None,
               arrow_size: float | None = None, decimals: int | None = None,
               override: dict | None = None, space=None, **props):
    """Linear dimension between p1 and p2; location = a point the dimension line passes through. angle 0 horizontal, 90 vertical. text '<>' = measured value, e.g. '<> mm'. override = raw DIMVARS like {dimtxt:3.5, dimexe:1}."""
    d = ctx.layout(space).add_linear_dim(
        base=vec(location), p1=vec(p1), p2=vec(p2), angle=float(angle), text=text,
        dimstyle=_ds(ctx, dimstyle), override=_override(text_height, arrow_size, decimals, override),
    )
    return _dim(ctx, d, props)


@op(T, "dim_aligned", mutates=True)
def dim_aligned(ctx: Ctx, p1, p2, distance: float, text: str = "<>", dimstyle: str | None = None,
                text_height: float | None = None, arrow_size: float | None = None,
                decimals: int | None = None, override: dict | None = None, space=None, **props):
    """Dimension parallel to p1-p2, offset by distance (positive = left side looking from p1 to p2)."""
    d = ctx.layout(space).add_aligned_dim(
        p1=vec(p1), p2=vec(p2), distance=float(distance), text=text, dimstyle=_ds(ctx, dimstyle),
        override=_override(text_height, arrow_size, decimals, override),
    )
    return _dim(ctx, d, props)


@op(T, "dim_angular", mutates=True)
def dim_angular(ctx: Ctx, center, p1, p2, location, text: str = "<>", dimstyle: str | None = None,
                text_height: float | None = None, decimals: int | None = None,
                override: dict | None = None, space=None, **props):
    """Angle from p1 to p2 (counter-clockwise) around center; location = point on the dimension arc."""
    d = ctx.layout(space).add_angular_dim_3p(
        base=vec(location), center=vec(center), p1=vec(p1), p2=vec(p2), text=text,
        dimstyle=_ds(ctx, dimstyle), override=_override(text_height, None, decimals, override),
    )
    return _dim(ctx, d, props)


@op(T, "dim_arc_length", mutates=True)
def dim_arc_length(ctx: Ctx, center, p1, p2, location, text: str = "<>",
                   dimstyle: str | None = None, override: dict | None = None, space=None, **props):
    """Arc length dimension of the arc from p1 to p2 around center."""
    d = ctx.layout(space).add_arc_dim_3p(
        base=vec(location), center=vec(center), p1=vec(p1), p2=vec(p2), text=text,
        dimstyle=_ds(ctx, dimstyle), override=override or {},
    )
    return _dim(ctx, d, props)


def _circle_of(ctx: Ctx, handle, center, radius):
    if handle:
        e = ctx.entity(handle)
        if e.dxftype() not in ("CIRCLE", "ARC"):
            raise CadError("handle must be a CIRCLE or ARC")
        return e.dxf.center, e.dxf.radius
    if center is None or radius is None:
        raise CadError("Give handle of a circle/arc, or center and radius")
    return vec(center), float(radius)


@op(T, "dim_radius", mutates=True)
def dim_radius(ctx: Ctx, handle: str | None = None, center=None, radius: float | None = None,
               angle: float = 45, text: str = "<>", dimstyle: str | None = None,
               text_height: float | None = None, override: dict | None = None, space=None, **props):
    """Radius dimension of a circle/arc (handle) or of center+radius, measured at angle (deg)."""
    c, r = _circle_of(ctx, handle, center, radius)
    d = ctx.layout(space).add_radius_dim(
        center=c, radius=r, angle=float(angle), text=text, dimstyle=_ds(ctx, dimstyle),
        override=_override(text_height, None, None, override),
    )
    return _dim(ctx, d, props)


@op(T, "dim_diameter", mutates=True)
def dim_diameter(ctx: Ctx, handle: str | None = None, center=None, radius: float | None = None,
                 angle: float = 45, text: str = "<>", dimstyle: str | None = None,
                 text_height: float | None = None, override: dict | None = None, space=None, **props):
    """Diameter dimension of a circle/arc (handle) or of center+radius."""
    c, r = _circle_of(ctx, handle, center, radius)
    d = ctx.layout(space).add_diameter_dim(
        center=c, radius=r, angle=float(angle), text=text, dimstyle=_ds(ctx, dimstyle),
        override=_override(text_height, None, None, override),
    )
    return _dim(ctx, d, props)


@op(T, "dim_ordinate", mutates=True)
def dim_ordinate(ctx: Ctx, feature, leader_end, axis: str = "x", origin=(0, 0), text: str = "<>",
                 dimstyle: str | None = None, override: dict | None = None, space=None, **props):
    """Ordinate dimension: X or Y coordinate of feature relative to origin; leader_end is where the text goes."""
    lay = ctx.layout(space)
    f, o = vec(feature), vec(origin)
    offset = vec(leader_end) - f
    fn = lay.add_ordinate_x_dim if axis.lower() == "x" else lay.add_ordinate_y_dim
    d = fn(feature_location=f, offset=offset, origin=o, text=text, dimstyle=_ds(ctx, dimstyle),
           override=override or {})
    return _dim(ctx, d, props)


@op(T, "leader", mutates=True)
def leader(ctx: Ctx, points, text: str, char_height: float = 2.5, space=None, **props):
    """Multileader with text: points=[arrow_tip, ..., landing]; text placed at the last point."""
    from ezdxf.render import mleader as ml

    pts = vecs(points, 2)
    builder = ctx.layout(space).add_multileader_mtext("Standard")
    builder.set_content(text, char_height=float(char_height))
    tip, land = pts[0], pts[-1]
    side = ml.ConnectionSide.right if tip.x > land.x else ml.ConnectionSide.left
    builder.add_leader_line(side, [Vec2(p) for p in pts[:-1]] or [Vec2(tip)])
    builder.build(insert=Vec2(land))
    return _done(finish(ctx.doc, builder.multileader, pick_props(props)))


@op(T, "table", mutates=True)
def table(ctx: Ctx, insert, rows: list, col_widths: list | None = None, row_height: float = 8.0,
          text_height: float = 2.5, header: bool = True, space=None, **props):
    """Table drawn as lines + text from a 2D list of strings; insert = top-left corner. First row bold-ish (bigger) if header."""
    from ezdxf.addons import TablePainter

    if not rows or not isinstance(rows[0], list):
        raise CadError("rows must be a list of lists, e.g. [['Room','Area'],['Kitchen','12.5']]")
    nrows, ncols = len(rows), max(len(r) for r in rows)
    widths = col_widths or [30.0] * ncols
    tp = TablePainter(insert=vec(insert), nrows=nrows, ncols=ncols, cell_width=widths[0],
                      cell_height=float(row_height))
    for i, w in enumerate(widths[:ncols]):
        tp.set_col_width(i, float(w))
    tp.new_cell_style("cell", char_height=float(text_height), align=MTextEntityAlignment.MIDDLE_CENTER)
    tp.new_cell_style("head", char_height=float(text_height) * 1.2,
                      align=MTextEntityAlignment.MIDDLE_CENTER)
    layer = props.get("layer")
    if layer:
        tp.bg_layer_name = tp.fg_layer_name = tp.grid_layer_name = layer
        if not ctx.doc.layers.has_entry(layer):
            ctx.doc.layers.add(layer)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            tp.text_cell(r, c, str(val), style="head" if header and r == 0 else "cell")
    lay = ctx.layout(space)
    before = {e.dxf.handle for e in lay}
    tp.render(lay)
    new = [e for e in lay if e.dxf.handle not in before]
    return {"handles": [e.dxf.handle for e in new], "size": [sum(widths[:ncols]), nrows * row_height]}


@op(T, "set_text", mutates=True)
def set_text(ctx: Ctx, handle: str, text: str):
    """Change the content of a TEXT, MTEXT, ATTRIB or DIMENSION (dimension: '<>' = measured)."""
    e = ctx.entity(handle)
    t = e.dxftype()
    if t in ("TEXT", "ATTRIB", "ATTDEF"):
        e.dxf.text = text
    elif t == "MTEXT":
        e.text = text.replace("\n", "\\P")
    elif t == "DIMENSION":
        e.dxf.text = text
        e.override().render()
    elif t == "MULTILEADER":
        e.context.mtext.default_content = text.replace("\n", "\\P")  # type: ignore[union-attr]
    else:
        raise CadError(f"{t} has no editable text")
    return {"handle": e.dxf.handle, "text": text}

