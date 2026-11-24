"""Tool `road` (continued): traffic sign block library (KRESZ-tábla jelképek) and a
roundabout (körforgalom) layout generator."""

from __future__ import annotations

import math

from ezdxf.math import Vec2
from shapely.geometry import Polygon, box
from shapely.affinity import rotate as srotate

from .core import CadError, Ctx, ensure_layer, op, vec
from .ops_road import _m, get_alignment

T = "road"

RED, BLUE, YELLOW, WHITE, BLACK = (204, 0, 0), (0, 84, 166), (255, 204, 0), (255, 255, 255), (0, 0, 0)

# type -> (description, shape, fill, border, inner)
SIGNS = {
    "sebesseg": ("Sebességkorlátozás (szám: TEXT)", "circle", WHITE, RED, "text"),
    "behajtani_tilos": ("Behajtani tilos", "circle", RED, RED, "bar"),
    "megallni_tilos": ("Megállni tilos", "circle", BLUE, RED, "cross"),
    "varakozni_tilos": ("Várakozni tilos", "circle", BLUE, RED, "slash"),
    "elozni_tilos": ("Előzni tilos / egyéb tilalom (szöveg: TEXT)", "circle", WHITE, RED, "text"),
    "stop": ("Állj! Elsőbbségadás kötelező", "octagon", RED, WHITE, "stop"),
    "elsobbsegadas": ("Elsőbbségadás kötelező", "triangle_down", WHITE, RED, None),
    "foutvonal": ("Főútvonal", "diamond", YELLOW, WHITE, None),
    "veszely": ("Veszélyt jelző tábla (jel: TEXT)", "triangle", WHITE, RED, "text"),
    "kotelezo_irany": ("Kötelező haladási irány (nyíl, forgatással)", "circle", BLUE, BLUE, "arrow"),
    "korforgalom": ("Körforgalom", "circle", BLUE, BLUE, "text"),
    "tajekoztato": ("Tájékoztató tábla (szöveg: TEXT)", "square", BLUE, WHITE, "text"),
    "gyalogos_atkelo": ("Kijelölt gyalogos-átkelőhely", "square", BLUE, WHITE, "triangle"),
    "helysegnev": ("Helységnévtábla (név: TEXT)", "rect", WHITE, BLACK, "text"),
}


def _poly(shape: str, r: float = 0.5) -> list[tuple[float, float]]:
    if shape == "circle":
        return [(r * math.cos(2 * math.pi * i / 48), r * math.sin(2 * math.pi * i / 48)) for i in range(48)]
    if shape == "octagon":
        return [(r * math.cos(math.pi / 8 + math.pi * i / 4), r * math.sin(math.pi / 8 + math.pi * i / 4)) for i in range(8)]
    if shape == "triangle":
        return [(0, r), (-r * 0.95, -r * 0.65), (r * 0.95, -r * 0.65)]
    if shape == "triangle_down":
        return [(0, -r), (r * 0.95, r * 0.65), (-r * 0.95, r * 0.65)]
    if shape == "diamond":
        return [(0, r), (r, 0), (0, -r), (-r, 0)]
    if shape == "square":
        return [(-r * 0.85, -r * 0.85), (r * 0.85, -r * 0.85), (r * 0.85, r * 0.85), (-r * 0.85, r * 0.85)]
    if shape == "rect":
        return [(-r * 1.4, -r * 0.5), (r * 1.4, -r * 0.5), (r * 1.4, r * 0.5), (-r * 1.4, r * 0.5)]
    raise CadError(f"Unknown shape {shape}")


def _scaled(pts, f):
    return [(x * f, y * f) for x, y in pts]


def _ensure_sign_block(ctx: Ctx, kind: str) -> str:
    if kind not in SIGNS:
        raise CadError(f"Unknown sign type '{kind}'. Types: {sorted(SIGNS)}")
    name = "KRESZ_" + kind.upper()
    doc = ctx.doc
    if doc.blocks.get(name) is not None:
        return name
    _desc, shape, fill, border, inner = SIGNS[kind]
    blk = doc.blocks.new(name, base_point=(0, 0))
    cy = 0.95  # sign centre above the post base

    def hatch(outer, holes=(), rgb=WHITE):
        h = blk.add_hatch(dxfattribs={"layer": "0"})
        h.rgb = rgb
        h.dxf.hatch_style = 0
        h.paths.add_polyline_path([(x, y + cy) for x, y in outer], is_closed=True, flags=1)
        for hole in holes:
            h.paths.add_polyline_path([(x, y + cy) for x, y in hole], is_closed=True, flags=0)

    outer = _poly(shape)
    inner_border = _scaled(outer, 0.78)
    blk.add_line((0, 0), (0, cy - 0.5), dxfattribs={"layer": "0"})  # post
    blk.add_circle((0, 0), 0.06, dxfattribs={"layer": "0"})
    hatch(outer, [inner_border], border)
    hatch(inner_border, [], fill)
    edge = blk.add_lwpolyline([(x, y + cy) for x, y in outer], close=True, dxfattribs={"layer": "0"})
    edge.rgb = BLACK
    if inner == "bar":
        hatch([(-0.3, -0.07), (0.3, -0.07), (0.3, 0.07), (-0.3, 0.07)], [], WHITE)
    elif inner in ("cross", "slash"):
        for ang in ((45, -45) if inner == "cross" else (45,)):
            b = srotate(box(-0.36, -0.045, 0.36, 0.045), ang, origin=(0, 0))
            hatch(list(b.exterior.coords)[:-1], [], RED)
    elif inner == "arrow":
        hatch([(-0.06, -0.28), (0.06, -0.28), (0.06, 0.08), (0.16, 0.08), (0, 0.3), (-0.16, 0.08), (-0.06, 0.08)],
              [], WHITE)
    elif inner == "triangle":
        hatch([(0, 0.3), (-0.3, -0.22), (0.3, -0.22)], [], WHITE)
    if inner == "stop":
        t = blk.add_text("STOP", height=0.22, dxfattribs={"layer": "0"})
        t.rgb = WHITE
        from ezdxf.enums import TextEntityAlignment

        t.set_placement((0, cy), align=TextEntityAlignment.MIDDLE_CENTER)
    if inner == "text":
        from ezdxf.enums import TextEntityAlignment

        a = blk.add_attdef("TEXT", (0, cy), text="", dxfattribs={"layer": "0", "height": 0.28 if shape != "rect" else 0.22,
                                                                  "prompt": "Felirat"})
        a.set_placement((0, cy), align=TextEntityAlignment.MIDDLE_CENTER)
        a.rgb = WHITE if fill == BLUE else BLACK
    return name


@op(T, "sign_types")
def sign_types(ctx: Ctx):
    """Available traffic sign symbol types (simplified KRESZ-style plan symbols)."""
    return {"types": {k: v[0] for k, v in SIGNS.items()}}


@op(T, "sign", mutates=True)
def sign(ctx: Ctx, type: str, insert, size: float = 3.0, rotation: float = 0.0, text: str | None = None,
         layer: str = "KRESZ_TABLA", space=None):
    """Place a traffic sign symbol (post + sign face) as a block reference. size = symbol height in drawing units (e.g. 3 m on a 1:1000 plan); text fills the TEXT attribute (e.g. speed '50')."""
    bname = _ensure_sign_block(ctx, type)
    ensure_layer(ctx.doc, layer)
    ref = ctx.layout(space).add_blockref(bname, vec(insert), dxfattribs={
        "layer": layer, "xscale": size, "yscale": size, "zscale": size, "rotation": float(rotation)})
    if ctx.doc.blocks.get(bname).attdefs():
        ref.add_auto_attribs({"TEXT": text or ""})
        fits = 6.0 if SIGNS[type][1] == "rect" else 2.6  # characters that fit at full width
        for a in ref.attribs:
            if len(a.dxf.text) > fits:
                a.dxf.width = fits / len(a.dxf.text)  # squeeze long labels into the sign face
    return {"handle": ref.dxf.handle, "block": bname}


@op(T, "sign_at", mutates=True)
def sign_at(ctx: Ctx, name: str, station: float, type: str, offset: float = -6.0, text: str | None = None,
            size: float = 3.0, facing: str = "forward", layer: str = "KRESZ_TABLA", space=None):
    """Place a traffic sign at a station of an alignment, offset from the axis (+ left, - right, default 6 m right), turned to face traffic travelling forward (or backward)."""
    al, _ = get_alignment(ctx, name)
    m = _m(ctx)
    x, y, h = al.point_at(float(station), float(offset))
    rot = math.degrees(h) - 90 if facing == "forward" else math.degrees(h) + 90
    return sign(ctx, type=type, insert=(x * m, y * m), size=size, rotation=rot, text=text, layer=layer, space=space)


@op(T, "roundabout", mutates=True)
def roundabout(ctx: Ctx, center, outer_radius: float, ring_width: float, approaches: list,
               corner_radius: float = 12.0, apron_width: float = 0.0, splitter: bool = True,
               layer: str = "KORFORGALOM", space=None):
    """Roundabout (körforgalom) layout with exact geometry: outer edge arcs (inscribed circle = 2 x outer_radius), circulating roadway ring_width, central island (+ optional truck apron), approaches [{angle deg, width m, length m}] joined to the ring by tangent corner arcs of corner_radius, splitter islands."""
    c = Vec2(vec(center))
    m = _m(ctx)
    R, ring, r = outer_radius * m, ring_width * m, corner_radius * m
    r_in = R - ring
    if r_in <= 0:
        raise CadError("ring_width must be smaller than outer_radius")
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    ensure_layer(ctx.doc, layer + "_SZIGET")
    at, ai = {"layer": layer}, {"layer": layer + "_SZIGET"}
    created = []
    mouths = []  # (angle of right tangent on ring, angle of left tangent) per approach
    for ap in sorted(approaches, key=lambda a: float(a["angle"]) % 360):
        ang = math.radians(float(ap["angle"]))
        w = float(ap.get("width", 7.0)) * m
        L = float(ap.get("length", 40.0)) * m
        if w / 2 >= R:
            raise CadError("Approach wider than the roundabout")
        u = Vec2(math.cos(ang), math.sin(ang))
        n = Vec2(-u.y, u.x)
        t = math.sqrt((R + r) ** 2 - (w / 2 + r) ** 2)
        ring_angles = {}
        for side in (-1, 1):
            f = c + u * t + n * (side * (w / 2 + r))          # corner arc centre
            t_ring = c + (f - c) * (R / (R + r))               # tangent point on the outer circle
            t_line = c + u * t + n * (side * w / 2)            # tangent point on the approach edge
            end = c + u * (R + L) + n * (side * w / 2)
            created.append(lay.add_line(t_line, end, dxfattribs=at))
            a1 = math.degrees(math.atan2(t_ring.y - f.y, t_ring.x - f.x))
            a2 = math.degrees(math.atan2(t_line.y - f.y, t_line.x - f.x))
            if (a2 - a1) % 360 > 180:
                a1, a2 = a2, a1
            created.append(lay.add_arc(f, r, a1, a2, dxfattribs=at))
            ring_angles[side] = math.degrees(math.atan2(t_ring.y - c.y, t_ring.x - c.x))
        mouths.append((ring_angles[-1], ring_angles[1]))
    for i, (_right, left) in enumerate(mouths):
        nxt_right = mouths[(i + 1) % len(mouths)][0]
        if len(mouths) > 1 and (nxt_right - left) % 360 >= 360 - 1e-9:
            raise CadError("Approaches overlap: reduce widths or corner_radius")
        created.append(lay.add_arc(c, R, left, nxt_right, dxfattribs=at))
    created.append(lay.add_circle(c, r_in, dxfattribs=ai))
    if apron_width:
        created.append(lay.add_circle(c, r_in - apron_width * m, dxfattribs=ai))
    if splitter:
        for ap in approaches:
            ang = math.radians(float(ap["angle"]))
            u = Vec2(math.cos(ang), math.sin(ang))
            n = Vec2(-u.y, u.x)
            w = float(ap.get("width", 7.0)) * m
            s0, s1 = R + 1.5 * m, R + min(float(ap.get("length", 40.0)) * m * 0.6, 25 * m)
            half = min(1.5 * m, w * 0.2)
            tri = Polygon([c + u * s0 + n * 0.3 * m, c + u * s1 + n * half, c + u * s1 - n * half,
                           c + u * s0 - n * 0.3 * m]).buffer(0.3 * m, join_style="round")
            created.append(lay.add_lwpolyline(list(tri.exterior.coords)[:-1], close=True, dxfattribs=ai))
    return {"handles": [e.dxf.handle for e in created], "inscribed_diameter": round(2 * outer_radius, 3),
            "central_island_radius": round(outer_radius - ring_width, 3), "approaches": len(approaches)}
