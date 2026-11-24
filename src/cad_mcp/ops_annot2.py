"""Completes annotation: QDIM, DIMSPACE, DIMTEDIT, DIMEDIT, DIMBREAK, jogged radius,
TOLERANCE (GD&T), CENTERLINE, classic LEADER, MLEADERSTYLE, MLEADERALIGN,
JUSTIFYTEXT, MLINESTYLE, fields and dimension associativity (MCP-maintained)."""

from __future__ import annotations

import datetime as _dt
import math

from ezdxf import bbox
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.math import Vec2, Vec3

from .core import (
    CadError,
    Ctx,
    ensure_layer,
    ensure_linetype,
    finish,
    handles,
    op,
    parse_color,
    pick_props,
    select_from,
    vec,
)

T = "annotate"
APP = "CADMCP"


def _dimstyle(ctx: Ctx, name):
    from .ops_annotate import _ds

    return _ds(ctx, name)


def _rerender(dim) -> None:
    dim.override().render()


def _key_points(e) -> list[Vec2]:
    t = e.dxftype()
    if t == "LINE":
        return [Vec2(e.dxf.start), Vec2(e.dxf.end)]
    if t in ("CIRCLE", "ARC"):
        pts = [Vec2(e.dxf.center)]
        if t == "ARC":
            pts += [Vec2(e.start_point), Vec2(e.end_point)]
        return pts
    if t == "LWPOLYLINE":
        return [Vec2(x, y) for x, y in e.get_points("xy")]
    if t in ("INSERT", "TEXT", "MTEXT"):
        return [Vec2(e.dxf.insert)]
    if t == "POINT":
        return [Vec2(e.dxf.location)]
    return []


@op(T, "qdim", mutates=True)
def qdim(ctx: Ctx, sel, location, direction: str = "horizontal", mode: str = "continuous", spacing: float = 5.0,
         text_height: float | None = None, arrow_size: float | None = None, dimstyle: str | None = None,
         space=None, **props):
    """QDIM: dimension all characteristic points (line ends, centres, vertices, insertion points) of a selection in one go: direction horizontal|vertical, mode continuous|baseline; location = point the (first) dimension line passes through."""
    from .ops_annotate import _override

    ents = select_from(ctx, sel)
    ang = 0.0 if direction == "horizontal" else 90.0
    axis = 0 if direction == "horizontal" else 1
    pts = {}
    for e in ents:
        for p in _key_points(e):
            pts.setdefault(round(p[axis], 6), p)
    keys = sorted(pts)
    if len(keys) < 2:
        raise CadError("Need at least two distinct points along that direction")
    loc = vec(location)
    lay = ctx.layout(space)
    created = []
    far = 1 if (loc[1 - axis] >= max(p[1 - axis] for p in pts.values())) else -1
    for i in range(1, len(keys)):
        p1 = pts[keys[0]] if mode == "baseline" else pts[keys[i - 1]]
        p2 = pts[keys[i]]
        base = loc if mode != "baseline" else loc + (Vec3(0, far * spacing * (i - 1), 0) if axis == 0
                                                      else Vec3(far * spacing * (i - 1), 0, 0))
        d = lay.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, dimstyle=_dimstyle(ctx, dimstyle),
                               override=_override(text_height, arrow_size, None, None))
        d.render()
        created.append(finish(ctx.doc, d.dimension, pick_props(props)))
    return {"handles": handles(created), "points": len(keys)}


@op(T, "dim_space", mutates=True)
def dim_space(ctx: Ctx, base: str, sel, spacing: float):
    """DIMSPACE: re-space parallel linear dimensions so their dimension lines are `spacing` apart, starting from the base dimension (order by distance)."""
    b = ctx.entity(base)
    ang = math.radians(b.dxf.get("angle", 0))
    n = Vec3(-math.sin(ang), math.cos(ang), 0)
    ref = Vec3(b.dxf.defpoint)
    others = [d for d in select_from(ctx, sel) if d is not b and d.dxftype() == "DIMENSION"]
    side = 1
    if others:
        avg = sum((Vec3(d.dxf.defpoint) - ref).dot(n) for d in others) / len(others)
        side = 1 if avg >= 0 else -1
    others.sort(key=lambda d: abs((Vec3(d.dxf.defpoint) - ref).dot(n)))
    for i, d in enumerate(others, start=1):
        cur = Vec3(d.dxf.defpoint)
        shift = (ref - cur).dot(n) + side * spacing * i
        d.dxf.defpoint = cur + n * shift
        if d.dxf.hasattr("text_midpoint"):
            d.dxf.text_midpoint = Vec3(d.dxf.text_midpoint) + n * shift
        _rerender(d)
    return {"handles": handles(others)}


@op(T, "dim_text", mutates=True)
def dim_text(ctx: Ctx, handle: str, location=None, home: bool = False, rotation: float | None = None,
             text: str | None = None, oblique: float | None = None):
    """DIMTEDIT / DIMEDIT: move the dimension text to location (or home=true back to default), rotate it (deg), override the text ('<>' = measured), or set oblique extension lines (deg)."""
    d = ctx.entity(handle)
    if d.dxftype() != "DIMENSION":
        raise CadError("handle must be a DIMENSION")
    if text is not None:
        d.dxf.text = text
    if rotation is not None:
        d.dxf.text_rotation = float(rotation)
    if oblique is not None:
        d.dxf.oblique_angle = float(oblique)
    ov = d.override()
    if home:
        if d.dxf.hasattr("text_midpoint"):
            d.dxf.discard("text_midpoint")
        d.set_flag_state(d.USER_LOCATION_OVERRIDE, False, name="dimtype")
    elif location is not None:
        ov.set_location(vec(location), leader=False, relative=False)
    ov.render()
    return {"handle": handle}


@op(T, "dim_break", mutates=True)
def dim_break(ctx: Ctx, handle: str, cutting=None, gap: float = 1.0):
    """DIMBREAK: break the dimension's extension and dimension lines where other objects cross them (the dimension is exploded into lines, arrows and text to do so)."""
    from shapely.geometry import LineString, Point

    from . import geom

    d = ctx.entity(handle)
    if d.dxftype() != "DIMENSION":
        raise CadError("handle must be a DIMENSION")
    lay = d.get_layout()
    cutters = [geom.to_shape(e) for e in (select_from(ctx, cutting) if cutting is not None else lay)
               if e is not d and e.dxftype() not in ("DIMENSION", "TEXT", "MTEXT") and geom.to_shape(e) is not None]
    parts = list(d.explode())
    out = []
    for e in parts:
        if e.dxftype() != "LINE":
            out.append(e)
            continue
        a, b = Vec2(e.dxf.start), Vec2(e.dxf.end)
        L = a.distance(b)
        ls = LineString([a, b])
        cuts = sorted({ls.project(Point(p.x, p.y)) for c in cutters for p in geom.intersection_points(ls, c)})
        if not cuts:
            out.append(e)
            continue
        keep, cur = [], 0.0
        for t in cuts:
            if t - gap / 2 > cur:
                keep.append((cur, t - gap / 2))
            cur = t + gap / 2
        if cur < L:
            keep.append((cur, L))
        u = (b - a) / L
        for s0, s1 in keep:
            out.append(lay.add_line(a + u * s0, a + u * s1, dxfattribs={"layer": e.dxf.layer, "color": e.dxf.color}))
        lay.delete_entity(e)
    return {"handles": handles([e for e in out if e.is_alive]), "breaks": True}


@op(T, "dim_jogged", mutates=True)
def dim_jogged(ctx: Ctx, handle: str, center_override, angle: float = 45, jog_angle: float = 45,
               text_height: float = 2.5, decimals: int = 2, layer: str | None = None, dimstyle: str | None = None):
    """DIMJOGGED: jogged radius dimension for large arcs/circles whose centre is far away: from center_override a line with a zig-zag jog to the arc at angle, arrow at the arc and 'R…' text. Written as a native AutoCAD jogged radius dimension (LARGE_RADIAL_DIMENSION) with its picture block, so AutoCAD edits it like one made with DIMJOGGED."""
    e = ctx.entity(handle)
    if e.dxftype() not in ("ARC", "CIRCLE"):
        raise CadError("handle must be an ARC or CIRCLE")
    c, r = Vec2(e.dxf.center), e.dxf.radius
    u = Vec2(math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    tip = c + u * r
    co = Vec2(vec(center_override).vec2)
    lay = e.get_layout()
    lyr = layer or e.dxf.layer
    mid = co + (tip - co) * 0.5
    jog = (tip - co).normalize().rotate_deg(jog_angle) * (text_height * 1.2)
    pts = [co, mid, mid + jog, tip]
    native = ctx.doc.dxfversion >= "AC1018"
    target = ctx.doc.blocks.new_anonymous_block(type_char="D") if native else lay
    at = {"layer": "0"} if native else {"layer": lyr}
    created = [target.add_lwpolyline([(p.x, p.y) for p in pts], dxfattribs=at)]
    ah = text_height
    back = (pts[-2] - tip).normalize()
    left, right = tip + back * ah + back.orthogonal() * ah / 3, tip + back * ah - back.orthogonal() * ah / 3
    created.append(target.add_solid([tip, left, right], dxfattribs=at))
    label = f"R{r:.{decimals}f}"
    t = target.add_text(label, height=text_height, rotation=math.degrees(math.atan2(u.y, u.x)), dxfattribs=at)
    text_at = mid + jog + Vec2(0, text_height * 0.4)
    t.set_placement(text_at, align=TextEntityAlignment.BOTTOM_LEFT)
    created.append(t)
    if not native:
        g = ctx.doc.groups.new(description="DIMJOGGED")
        g.extend(created)
        return {"handles": handles(created), "radius": r, "native": False}
    dim = lay.new_entity("LARGE_RADIAL_DIMENSION", dxfattribs={
        "layer": lyr, "dimstyle": _dimstyle(ctx, dimstyle), "geometry": target.name,
        "defpoint": Vec3(c.x, c.y, 0), "text_midpoint": Vec3(text_at.x, text_at.y, 0),
        "dimtype": 9 | 32 | 128, "actual_measurement": r,
        "chord_point": Vec3(tip.x, tip.y, 0), "override_center": Vec3(co.x, co.y, 0),
        "jog_point": Vec3(mid.x, mid.y, 0), "unknown2": math.radians(jog_angle)})
    return {"handles": [dim.dxf.handle], "radius": r, "native": True, "block": target.name}


GDT = {"position": "j", "flatness": "c", "straightness": "u", "circularity": "e", "cylindricity": "g",
       "profile_line": "k", "profile_surface": "d", "angularity": "a", "perpendicularity": "n",
       "parallelism": "f", "concentricity": "r", "symmetry": "i", "runout": "h", "total_runout": "t"}


@op(T, "tolerance", mutates=True)
def tolerance(ctx: Ctx, symbol: str, value: str, insert, datums: list | None = None, diameter: bool = False,
              material: str | None = None, second: dict | None = None, height: float | None = None,
              dimstyle: str | None = None, space=None, **props):
    """TOLERANCE (geometric tolerance frame, GD&T): symbol = position, flatness, straightness, circularity, cylindricity, profile_line, profile_surface, angularity, perpendicularity, parallelism, concentricity, symmetry, runout, total_runout; value like '0.05'; datums ['A','B']; diameter adds Ø; material M/L/S modifier; second = optional second row {symbol, value, datums}. AutoCAD draws the frame."""
    def row(sym, val, dts, dia, mat):
        if sym not in GDT:
            raise CadError(f"symbol must be one of {sorted(GDT)}")
        mm = {"M": "{\\Fgdt;m}", "L": "{\\Fgdt;l}", "S": "{\\Fgdt;s}"}.get((mat or "").upper(), "")
        tol = ("{\\Fgdt;n}" if dia else "") + str(val) + mm
        cells = [f"{{\\Fgdt;{GDT[sym]}}}", tol] + [str(x) for x in (dts or [])]
        return "%%v".join(cells)

    content = row(symbol, value, datums, diameter, material)
    if second:
        content += "^J" + row(second["symbol"], second["value"], second.get("datums"), second.get("diameter"),
                              second.get("material"))
    ds = _dimstyle(ctx, dimstyle)
    if height:  # own dimension style per frame text height, so the base style stays untouched
        name = f"{ds}_TOL_{float(height):g}"
        if not ctx.doc.dimstyles.has_entry(name):
            ctx.doc.dimstyles.duplicate_entry(ds, name).dxf.dimtxt = float(height)
        ds = name
    t = ctx.layout(space).new_entity("TOLERANCE", dxfattribs={"content": content, "insert": vec(insert),
                                                               "dimstyle": ds})
    return {"handles": [finish(ctx.doc, t, pick_props(props)).dxf.handle], "content": content}


@op(T, "centerline", mutates=True)
def centerline(ctx: Ctx, handle1: str, handle2: str, extend: float = 2.0, layer: str | None = None):
    """CENTERLINE: centre line between two lines (CENTER linetype), extended `extend` beyond both ends."""
    a, b = ctx.entity(handle1), ctx.entity(handle2)
    if a.dxftype() != "LINE" or b.dxftype() != "LINE":
        raise CadError("centerline needs two LINEs")
    a0, a1, b0, b1 = (Vec2(a.dxf.start), Vec2(a.dxf.end), Vec2(b.dxf.start), Vec2(b.dxf.end))
    if (a1 - a0).dot(b1 - b0) < 0:
        b0, b1 = b1, b0
    s, e = (a0 + b0) / 2, (a1 + b1) / 2
    u = (e - s).normalize()
    ensure_linetype(ctx.doc, "CENTER")
    attribs = {"layer": layer or a.dxf.layer, "linetype": "CENTER"}
    if layer:
        ensure_layer(ctx.doc, layer)
    ln = a.get_layout().add_line(s - u * extend, e + u * extend, dxfattribs=attribs)
    return {"handles": [ln.dxf.handle]}


@op(T, "leader_classic", mutates=True)
def leader_classic(ctx: Ctx, points, text: str, char_height: float = 2.5, dimstyle: str | None = None,
                   space=None, **props):
    """LEADER (classic LEADER entity + MTEXT annotation) for drawings standardised on old-style leaders."""
    pts = [vec(p) for p in points]
    lay = ctx.layout(space)
    ld = lay.add_leader(pts, dimstyle=_dimstyle(ctx, dimstyle))
    last, prev = pts[-1], pts[-2]
    right = last.x >= prev.x
    mt = lay.add_mtext(text.replace("\n", "\\P"), dxfattribs={"char_height": float(char_height)})
    mt.set_location(last + Vec3(char_height * 0.5 * (1 if right else -1), 0, 0),
                    attachment_point=MTextEntityAlignment.MIDDLE_LEFT if right else MTextEntityAlignment.MIDDLE_RIGHT)
    ld.dxf.annotation_handle = mt.dxf.handle
    ld.dxf.annotation_type = 0
    for e in (ld, mt):
        finish(ctx.doc, e, pick_props(props))
    return {"handles": [ld.dxf.handle, mt.dxf.handle]}


@op("style", "create_mleader_style", mutates=True)
def create_mleader_style(ctx: Ctx, name: str, char_height: float = 2.5, arrow_size: float = 2.5,
                         landing_gap: float = 1.0, dogleg_length: float = 4.0, text_style: str = "Standard",
                         has_frame: bool = False):
    """MLEADERSTYLE: create/update a multileader style (text height, arrow size, landing gap, dogleg, text style, frame). Use it with annotate.leader style=..."""
    doc = ctx.doc
    st = doc.mleader_styles.get(name)
    if st is None:
        st = doc.mleader_styles.duplicate_entry("Standard", name)
    st.dxf.char_height = float(char_height)
    st.dxf.arrow_head_size = float(arrow_size)
    st.dxf.landing_gap_size = float(landing_gap)
    st.dxf.dogleg_length = float(dogleg_length)
    st.dxf.has_text_frame = int(bool(has_frame))
    ts = doc.styles.get(text_style)
    if ts is None:
        raise CadError(f"Text style '{text_style}' does not exist")
    st.dxf.text_style_handle = ts.dxf.handle
    return {"mleader_style": name}


@op(T, "leader_styled", mutates=True)
def leader_styled(ctx: Ctx, points, text: str, style: str = "Standard", space=None, **props):
    """Multileader using a named MLEADERSTYLE (see style.create_mleader_style)."""
    from ezdxf.render import mleader as ml

    if ctx.doc.mleader_styles.get(style) is None:
        raise CadError(f"Multileader style '{style}' does not exist")
    pts = [vec(p) for p in points]
    b = ctx.layout(space).add_multileader_mtext(style)
    b.set_content(text)
    tip, land = pts[0], pts[-1]
    side = ml.ConnectionSide.right if tip.x > land.x else ml.ConnectionSide.left
    b.add_leader_line(side, [Vec2(p) for p in pts[:-1]])
    b.build(insert=Vec2(land))
    return {"handles": [finish(ctx.doc, b.multileader, pick_props(props)).dxf.handle]}


@op(T, "mleader_align", mutates=True)
def mleader_align(ctx: Ctx, sel, x: float | None = None, y: float | None = None, spacing: float | None = None):
    """MLEADERALIGN: line up multileader texts on a common x (vertical column) or y (row); spacing distributes them evenly along that line. Arrow points stay."""
    mls = [e for e in select_from(ctx, sel) if e.dxftype() == "MULTILEADER"]
    if not mls:
        raise CadError("No multileaders selected")
    if x is None and y is None:
        x = Vec2(mls[0].context.mtext.insert).x
    key = 1 if x is not None else 0
    mls.sort(key=lambda m: -Vec2(m.context.mtext.insert)[key] if key == 1 else Vec2(m.context.mtext.insert)[key])
    start = Vec2(mls[0].context.mtext.insert)[key]
    for i, m in enumerate(mls):
        cur = Vec2(m.context.mtext.insert)
        tx = x if x is not None else cur.x
        ty = y if y is not None else cur.y
        if spacing:
            if key == 1:
                ty = start - i * spacing
            else:
                tx = start + i * spacing
        delta = Vec3(tx - cur.x, ty - cur.y, 0)
        m.context.mtext.insert = Vec3(m.context.mtext.insert) + delta
        m.context.base_point = Vec3(m.context.base_point) + delta
        for ld in m.context.leaders:
            ld.last_leader_point = Vec3(ld.last_leader_point) + delta
    return {"handles": handles(mls)}


ALIGNS = {a.name.lower(): a for a in TextEntityAlignment}


@op(T, "justify_text", mutates=True)
def justify_text(ctx: Ctx, sel, align: str):
    """JUSTIFYTEXT: change the justification of TEXT/MTEXT without moving the text on the drawing."""
    out = []
    for e in select_from(ctx, sel):
        t = e.dxftype()
        ext = bbox.extents([e])
        if not ext.has_data:
            continue
        (x0, y0), (x1, y1) = ext.extmin.vec2, ext.extmax.vec2
        if t == "TEXT":
            a = ALIGNS.get(align.lower())
            if a is None:
                raise CadError(f"align must be one of {sorted(ALIGNS)}")
            from ezdxf.tools.text_size import text_size

            size = text_size(e)
            w, cap, desc = size.width, size.cap_height, size.total_height - size.cap_height
            cur_align, p1, _p2 = e.get_placement()
            rot = math.radians(e.dxf.get("rotation", 0))
            ux, uy = Vec2(math.cos(rot), math.sin(rot)), Vec2(-math.sin(rot), math.cos(rot))

            def offsets(name: str, w=w, cap=cap, desc=desc) -> tuple[float, float]:
                """Local offset of the alignment point from the left end of the baseline."""
                hx = 0.0 if ("LEFT" in name or name in ("LEFT", "ALIGNED", "FIT")) else (
                    w if "RIGHT" in name else w / 2)
                if name in ("ALIGNED", "FIT"):
                    hx = 0.0
                vy = cap if name.startswith("TOP") else (cap / 2 if name.startswith("MIDDLE") else (
                    -desc if name.startswith("BOTTOM") else 0.0))
                if name == "MIDDLE":
                    vy = (cap - desc) / 2
                return hx, vy

            ox, oy = offsets(cur_align.name)
            base = Vec2(p1) - ux * ox - uy * oy  # left end of the baseline
            nx, ny = offsets(a.name)
            e.set_placement(base + ux * nx + uy * ny, align=a)
        elif t == "MTEXT":
            a = {m.name.lower(): m for m in MTextEntityAlignment}.get(align.lower())
            if a is None:
                raise CadError("MTEXT align: top_left ... bottom_right")
            n = a.name
            vx = x0 if n.endswith("LEFT") else (x1 if n.endswith("RIGHT") else (x0 + x1) / 2)
            vy = y1 if n.startswith("TOP") else (y0 if n.startswith("BOTTOM") else (y0 + y1) / 2)
            e.set_location((vx, vy), attachment_point=a)
        else:
            continue
        out.append(e)
    return {"handles": handles(out)}


@op("style", "create_mline_style", mutates=True)
def create_mline_style(ctx: Ctx, name: str, elements: list, fill_color=None, start_cap: bool = True,
                       end_cap: bool = True, description: str = ""):
    """MLSTYLE: multiline style with elements [{offset, color, linetype}], optional fill colour and end caps."""
    doc = ctx.doc
    if doc.mline_styles.get(name) is not None:
        doc.mline_styles.delete(name)
    st = doc.mline_styles.new(name)
    st.dxf.description = description
    flags = 0
    if fill_color is not None:
        aci, _rgb = parse_color(fill_color)
        st.dxf.fill_color = aci or 256
        flags |= 1
    if start_cap:
        flags |= 16
    if end_cap:
        flags |= 256
    st.dxf.flags = flags
    for el in elements:
        aci, _rgb = parse_color(el.get("color", 256))
        lt = el.get("linetype", "BYLAYER")
        ensure_linetype(doc, lt)
        st.elements.append(float(el["offset"]), aci if aci is not None else 256, lt)
    return {"mline_style": name, "elements": len(elements)}


# ---------------------------------------------------------------------------
# fields and associative dimensions (maintained by the MCP, refreshed on demand)
# ---------------------------------------------------------------------------


def _ensure_app(ctx: Ctx):
    if not ctx.doc.appids.has_entry(APP):
        ctx.doc.appids.new(APP)


def _field_value(ctx: Ctx, expr: str, handle: str | None, decimals: int, factor: float) -> str:
    from .ops_query import _area, _length

    if expr == "date":
        return _dt.date.today().isoformat()
    if expr == "filename":
        st = ctx.state
        return st.path.name if st.path else st.name
    if expr in ("area", "length", "perimeter", "radius", "count"):
        if expr == "count":
            return str(len(ctx.msp))
        e = ctx.entity(handle)
        if expr == "area":
            v = _area(e)[0]
        elif expr == "perimeter":
            v = _area(e)[1]
        elif expr == "radius":
            v = e.dxf.radius
        else:
            v = _length(e)
        return f"{v * factor:.{decimals}f}"
    raise CadError("expression: area, length, perimeter, radius, count, date, filename")


@op(T, "field", mutates=True)
def field(ctx: Ctx, insert, expression: str, handle: str | None = None, prefix: str = "", suffix: str = "",
          decimals: int = 2, factor: float = 1.0, height: float = 2.5, space=None, **props):
    """Field-like text that shows a live value: area/length/perimeter/radius of an object (handle), entity count, date or file name, with prefix/suffix and unit factor (e.g. 1e-6 for mm² -> m²). Refresh all with annotate.update_fields (the link is kept in the drawing; AutoCAD shows the last value as plain text)."""
    _ensure_app(ctx)
    txt = prefix + _field_value(ctx, expression, handle, decimals, factor) + suffix
    mt = ctx.layout(space).add_mtext(txt, dxfattribs={"char_height": float(height)})
    mt.set_location(vec(insert))
    mt.set_xdata(APP, [(1000, "FIELD"), (1000, expression), (1000, handle or ""), (1000, prefix), (1000, suffix),
                       (1070, int(decimals)), (1040, float(factor))])
    return {"handles": [finish(ctx.doc, mt, pick_props(props)).dxf.handle], "text": txt}


@op(T, "dim_associate", mutates=True)
def dim_associate(ctx: Ctx, dimension: str, p1_handle: str, p1_point: str, p2_handle: str, p2_point: str):
    """Make a linear/aligned dimension follow objects: its measured points are tied to p1/p2 of entities (point = start, end, center, mid). annotate.update_fields re-measures after the objects moved."""
    _ensure_app(ctx)
    d = ctx.entity(dimension)
    if d.dxftype() != "DIMENSION":
        raise CadError("dimension must be a DIMENSION handle")
    for h, w in ((p1_handle, p1_point), (p2_handle, p2_point)):
        _snap(ctx.entity(h), w)
    d.set_xdata(APP, [(1000, "DIMASSOC"), (1005, p1_handle), (1000, p1_point), (1005, p2_handle),
                      (1000, p2_point)])
    _update_dim(ctx, d)
    return {"handle": dimension}


def _snap(e, where: str) -> Vec3:
    t = e.dxftype()
    if where == "center" and t in ("CIRCLE", "ARC"):
        return Vec3(e.dxf.center)
    if t == "LINE":
        a, b = Vec3(e.dxf.start), Vec3(e.dxf.end)
        return {"start": a, "end": b, "mid": (a + b) / 2}.get(where) or _bad(where)
    if t == "ARC":
        return {"start": Vec3(e.start_point), "end": Vec3(e.end_point)}.get(where) or _bad(where)
    if t in ("INSERT", "POINT"):
        return Vec3(e.dxf.insert if t == "INSERT" else e.dxf.location)
    if t == "LWPOLYLINE":
        pts = list(e.get_points("xy"))
        return Vec3(*{"start": pts[0], "end": pts[-1]}.get(where, pts[0]))
    raise CadError(f"Cannot take point '{where}' of {t}")


def _bad(where):
    raise CadError(f"Unknown point '{where}': use start, end, mid, center")


def _update_dim(ctx: Ctx, d) -> bool:
    tags = d.get_xdata(APP)
    vals = [v for _c, v in tags]
    p1 = _snap(ctx.entity(vals[1]), vals[2])
    p2 = _snap(ctx.entity(vals[3]), vals[4])
    if p1.isclose(d.dxf.defpoint2) and p2.isclose(d.dxf.defpoint3):
        return False
    # keep the dimension line offset relative to the measured points
    off = Vec3(d.dxf.defpoint) - Vec3(d.dxf.defpoint3)
    d.dxf.defpoint2, d.dxf.defpoint3 = p1, p2
    d.dxf.defpoint = p2 + off
    _rerender(d)
    return True


@op(T, "update_fields", mutates=True)
def update_fields(ctx: Ctx):
    """Refresh all MCP fields (annotate.field) and associated dimensions (annotate.dim_associate)."""
    fields = dims = 0
    for lay in [ctx.msp] + [ctx.doc.paperspace(n) for n in ctx.doc.layout_names() if n != "Model"]:
        for e in lay:
            if not e.has_xdata(APP):
                continue
            tags = e.get_xdata(APP)
            kind = tags[0].value
            if kind == "FIELD":
                v = [t.value for t in tags]
                e.text = v[3] + _field_value(ctx, v[1], v[2] or None, int(v[5]), float(v[6])) + v[4]
                fields += 1
            elif kind == "DIMASSOC":
                dims += int(_update_dim(ctx, e))
    return {"fields_updated": fields, "dimensions_updated": dims}

