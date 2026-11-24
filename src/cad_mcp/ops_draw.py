"""Tools `draw` (2D geometry) and `draw3d` (3D faces and meshes)."""

from __future__ import annotations

import math

from ezdxf import path as ezpath
from ezdxf.math import ConstructionArc, Matrix44, Vec3
from ezdxf.render import forms

from .core import CadError, Ctx, finish, op, pick_props, vec, vecs

T = "draw"
T3 = "draw3d"


def _done(*ents):
    ents = [e for e in ents if e is not None]
    return {"handles": [e.dxf.handle for e in ents], "type": ents[0].dxftype() if ents else None}


def _lay(ctx: Ctx, space):
    return ctx.layout(space)


@op(T, "line", mutates=True)
def line(ctx: Ctx, start, end, space=None, **props):
    """Straight line from start to end. Props for every draw op: layer, color, linetype, lineweight, ltscale, transparency."""
    e = _lay(ctx, space).add_line(vec(start), vec(end))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "lines", mutates=True)
def lines(ctx: Ctx, segments, space=None, **props):
    """Many separate lines at once: segments=[[[x1,y1],[x2,y2]], ...]."""
    lay = _lay(ctx, space)
    out = [finish(ctx.doc, lay.add_line(vec(a), vec(b)), pick_props(props)) for a, b in segments]
    return _done(*out)


@op(T, "polyline", mutates=True)
def polyline(ctx: Ctx, points, closed: bool = False, bulges=None, width: float | None = None,
             space=None, **props):
    """2D polyline (LWPOLYLINE). points=[[x,y],...]; bulges=[b0,b1,...] per vertex for arc segments (bulge=tan(angle/4)); width=constant width."""
    pts = vecs(points, 2)
    data = []
    for i, p in enumerate(pts):
        b = float(bulges[i]) if bulges and i < len(bulges) and bulges[i] else 0.0
        data.append((p.x, p.y, 0, 0, b))
    attribs = {}
    if width:
        attribs["const_width"] = float(width)
    e = _lay(ctx, space).add_lwpolyline(data, format="xyseb", close=closed, dxfattribs=attribs)
    if pts[0].z:
        e.dxf.elevation = pts[0].z
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "polyline3d", mutates=True)
def polyline3d(ctx: Ctx, points, closed: bool = False, space=None, **props):
    """3D polyline through [[x,y,z],...]."""
    e = _lay(ctx, space).add_polyline3d(vecs(points, 2), close=closed)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "rectangle", mutates=True)
def rectangle(ctx: Ctx, corner1, corner2, rotation: float = 0, fillet: float = 0, space=None, **props):
    """Closed rectangle from two opposite corners, optional rotation (deg, about corner1) and corner fillet radius."""
    a, b = vec(corner1), vec(corner2)
    x1, x2 = sorted((a.x, b.x))
    y1, y2 = sorted((a.y, b.y))
    if fillet and fillet > 0:
        r = min(fillet, (x2 - x1) / 2, (y2 - y1) / 2)
        bulge = math.tan(math.radians(90) / 4)
        data = [
            (x1 + r, y1, 0, 0, 0), (x2 - r, y1, 0, 0, bulge), (x2, y1 + r, 0, 0, 0),
            (x2, y2 - r, 0, 0, bulge), (x2 - r, y2, 0, 0, 0), (x1 + r, y2, 0, 0, bulge),
            (x1, y2 - r, 0, 0, 0), (x1, y1 + r, 0, 0, bulge),
        ]
    else:
        data = [(x1, y1, 0, 0, 0), (x2, y1, 0, 0, 0), (x2, y2, 0, 0, 0), (x1, y2, 0, 0, 0)]
    e = _lay(ctx, space).add_lwpolyline(data, format="xyseb", close=True)
    if rotation:
        e.transform(Matrix44.chain(Matrix44.translate(-a.x, -a.y, 0),
                                   Matrix44.z_rotate(math.radians(rotation)),
                                   Matrix44.translate(a.x, a.y, 0)))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "polygon", mutates=True)
def polygon(ctx: Ctx, center, radius: float, sides: int, inscribed: bool = True,
            rotation: float = 0, space=None, **props):
    """Regular polygon. inscribed=true: radius to corners; false: radius to edge midpoints."""
    if sides < 3:
        raise CadError("sides must be >= 3")
    c = vec(center)
    r = radius if inscribed else radius / math.cos(math.pi / sides)
    pts = [(c.x + r * math.cos(math.radians(rotation) + 2 * math.pi * i / sides),
            c.y + r * math.sin(math.radians(rotation) + 2 * math.pi * i / sides)) for i in range(sides)]
    e = _lay(ctx, space).add_lwpolyline(pts, close=True)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "circle", mutates=True)
def circle(ctx: Ctx, center, radius: float, space=None, **props):
    """Circle by center and radius."""
    e = _lay(ctx, space).add_circle(vec(center), float(radius))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "circle_3p", mutates=True)
def circle_3p(ctx: Ctx, p1, p2, p3, space=None, **props):
    """Circle through three points."""
    arc = ConstructionArc.from_3p(vec(p1), vec(p3), vec(p2))
    e = _lay(ctx, space).add_circle(arc.center, arc.radius)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "arc", mutates=True)
def arc(ctx: Ctx, center, radius: float, start_angle: float, end_angle: float, space=None, **props):
    """Arc counter-clockwise from start_angle to end_angle (degrees, 0 = +X)."""
    e = _lay(ctx, space).add_arc(vec(center), float(radius), float(start_angle), float(end_angle))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "arc_3p", mutates=True)
def arc_3p(ctx: Ctx, start, through, end, space=None, **props):
    """Arc from start through a middle point to end."""
    a, m, b = vec(start), vec(through), vec(end)
    carc = ConstructionArc.from_3p(a, b, m)
    e = _lay(ctx, space).add_arc(carc.center, carc.radius, carc.start_angle, carc.end_angle)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "ellipse", mutates=True)
def ellipse(ctx: Ctx, center, major_axis, ratio: float, start_angle: float = 0,
            end_angle: float = 360, space=None, **props):
    """Ellipse: major_axis is the vector from center to the end of the major axis; ratio = minor/major. Partial ellipse with start/end angle (deg)."""
    e = _lay(ctx, space).add_ellipse(
        vec(center), vec(major_axis), float(ratio),
        math.radians(start_angle), math.radians(end_angle),
    )
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "spline", mutates=True)
def spline(ctx: Ctx, fit_points=None, control_points=None, degree: int = 3, closed: bool = False,
           space=None, **props):
    """Spline through fit_points, or defined by control_points."""
    lay = _lay(ctx, space)
    if fit_points:
        e = lay.add_spline(vecs(fit_points, 2), degree=degree)
    elif control_points:
        e = lay.add_open_spline(vecs(control_points, degree + 1), degree=degree)
    else:
        raise CadError("Give fit_points or control_points")
    if closed:
        e.closed = True
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "point", mutates=True)
def point(ctx: Ctx, location, space=None, **props):
    """Point entity."""
    e = _lay(ctx, space).add_point(vec(location))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "xline", mutates=True)
def xline(ctx: Ctx, point, direction, space=None, **props):
    """Infinite construction line through point along direction vector."""
    e = _lay(ctx, space).add_xline(vec(point), vec(direction))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "ray", mutates=True)
def ray(ctx: Ctx, start, direction, space=None, **props):
    """Half-infinite ray from start along direction."""
    e = _lay(ctx, space).add_ray(vec(start), vec(direction))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "solid", mutates=True)
def solid(ctx: Ctx, points, space=None, **props):
    """Filled 2D triangle or quadrilateral (SOLID); give 3 or 4 points in drawing order around the shape."""
    pts = vecs(points, 3)
    if len(pts) == 4:  # SOLID vertex order is 0,1,3,2
        pts = [pts[0], pts[1], pts[3], pts[2]]
    e = _lay(ctx, space).add_solid(pts)
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "donut", mutates=True)
def donut(ctx: Ctx, center, inner_diameter: float, outer_diameter: float, space=None, **props):
    """Filled ring (like DONUT): a closed polyline with width."""
    c = vec(center)
    r = (inner_diameter + outer_diameter) / 4
    w = (outer_diameter - inner_diameter) / 2
    e = _lay(ctx, space).add_lwpolyline(
        [(c.x - r, c.y, 0, 0, 1), (c.x + r, c.y, 0, 0, 1)], format="xyseb", close=True,
        dxfattribs={"const_width": w},
    )
    return _done(finish(ctx.doc, e, pick_props(props)))


def _signed_area(p) -> float:
    pts = list(p.flattening(0.01))
    return sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def _orient(paths):
    """Largest loop counter-clockwise, all others clockwise, so inner loops are holes."""
    if not paths:
        return paths
    areas = [_signed_area(p) for p in paths]
    outer = max(range(len(paths)), key=lambda i: abs(areas[i]))
    out = []
    for i, (p, a) in enumerate(zip(paths, areas)):
        want_ccw = i == outer
        out.append(p if (a > 0) == want_ccw else p.reversed())
    return out


def _boundary_paths(ctx: Ctx, boundary, boundary_handles):
    paths = []
    if boundary:
        loops = boundary if isinstance(boundary[0][0], (list, tuple)) else [boundary]
        for loop in loops:
            paths.append(ezpath.from_vertices(vecs(loop, 3), close=True))
    for h in boundary_handles or []:
        e = ctx.entity(h)
        try:
            p = ezpath.make_path(e)
        except TypeError as exc:
            raise CadError(f"Entity {h} ({e.dxftype()}) cannot be used as hatch boundary") from exc
        if not p.is_closed:
            p.close()
        paths.append(p)
    if not paths:
        raise CadError("Give boundary points or boundary_handles (closed polylines, circles, ellipses, splines)")
    return _orient(paths)


@op(T, "hatch", mutates=True)
def hatch(ctx: Ctx, boundary=None, boundary_handles=None, pattern: str = "SOLID",
          scale: float = 1.0, angle: float = 0, color=None, space=None, **props):
    """Hatch or solid fill. boundary=[[x,y],...] or list of loops (inner loops become islands), or boundary_handles of closed entities. pattern: SOLID, ANSI31, ANSI37, AR-CONC, AR-B816, BRICK, DOTS, EARTH, GRAVEL, HONEY, NET, ..."""
    paths = _boundary_paths(ctx, boundary, boundary_handles)
    hatches = list(ezpath.render_hatches(_lay(ctx, space), paths, edge_path=True))
    if color is not None:
        props["color"] = color
    for h in hatches:
        h.dxf.hatch_style = 0  # normal: nested loops alternate filled/empty (islands)
        if pattern.upper() != "SOLID":
            try:
                h.set_pattern_fill(pattern.upper(), scale=float(scale), angle=float(angle), style=0)
            except Exception as exc:
                raise CadError(f"Unknown hatch pattern '{pattern}': {exc}") from exc
        finish(ctx.doc, h, pick_props(props))
    return _done(*hatches)


@op(T, "wipeout", mutates=True)
def wipeout(ctx: Ctx, points, space=None, **props):
    """Masking area (WIPEOUT) that hides what is underneath."""
    e = _lay(ctx, space).add_wipeout(vecs(points, 3))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T, "image", mutates=True)
def image(ctx: Ctx, path: str, insert, width: float, space=None, **props):
    """Attach a raster image (PNG/JPG) at insert, scaled to width in drawing units."""
    from PIL import Image as PILImage  # matplotlib ships pillow

    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"Image not found: {p}")
    with PILImage.open(p) as im:
        px = im.size
    idef = ctx.doc.add_image_def(filename=str(p), size_in_pixel=px)
    height = width * px[1] / px[0]
    e = _lay(ctx, space).add_image(idef, insert=vec(insert), size_in_units=(width, height))
    return _done(finish(ctx.doc, e, pick_props(props)))


# ---------------------------------------------------------------------------
# 3D
# ---------------------------------------------------------------------------


def _mesh(ctx: Ctx, mt, space, props, at=None):
    """Every 3D primitive accepts solid=true for a real (faceted ACIS) 3DSOLID instead of a MESH."""
    from .ops_solid import emit

    solid = bool(props.pop("solid", False))
    if at is not None:
        mt.translate(*vec(at).xyz)
    return _done(emit(ctx, mt, space, props, solid))


@op(T3, "face", mutates=True)
def face(ctx: Ctx, points, space=None, **props):
    """3DFACE with 3 or 4 corner points."""
    e = _lay(ctx, space).add_3dface(vecs(points, 3))
    return _done(finish(ctx.doc, e, pick_props(props)))


@op(T3, "box", mutates=True)
def box(ctx: Ctx, origin, size, space=None, **props):
    """Box mesh with its min corner at origin and size=[dx,dy,dz]."""
    sx, sy, sz = vec(size).xyz
    mt = forms.cube(center=False)
    mt.scale(sx, sy, sz)
    return _mesh(ctx, mt, space, props, origin)


@op(T3, "cylinder", mutates=True)
def cylinder(ctx: Ctx, base_center, radius: float, height: float, top_radius: float | None = None,
             segments: int = 32, space=None, **props):
    """Cylinder (or truncated cone with top_radius) mesh standing on base_center along +Z."""
    mt = forms.cylinder(count=segments, radius=radius, top_radius=top_radius,
                        top_center=(0, 0, height))
    return _mesh(ctx, mt, space, props, base_center)


@op(T3, "cone", mutates=True)
def cone(ctx: Ctx, base_center, radius: float, height: float, segments: int = 32, space=None, **props):
    """Cone mesh on base_center with apex at +Z height."""
    mt = forms.cone(count=segments, radius=radius, apex=(0, 0, height))
    return _mesh(ctx, mt, space, props, base_center)


@op(T3, "sphere", mutates=True)
def sphere(ctx: Ctx, center, radius: float, segments: int = 32, stacks: int = 16, space=None, **props):
    """Sphere mesh."""
    mt = forms.sphere(count=segments, stacks=stacks, radius=radius)
    return _mesh(ctx, mt, space, props, center)


@op(T3, "torus", mutates=True)
def torus(ctx: Ctx, center, major_radius: float, minor_radius: float, space=None, **props):
    """Torus mesh lying in the XY plane."""
    mt = forms.torus(major_count=32, minor_count=16, major_radius=major_radius,
                     minor_radius=minor_radius)
    return _mesh(ctx, mt, space, props, center)


@op(T3, "extrude", mutates=True)
def extrude(ctx: Ctx, profile=None, profile_handle: str | None = None, height: float | None = None,
            path=None, space=None, **props):
    """Extrude a closed 2D profile (points or a closed polyline/circle handle) by height along +Z, or along a path of points."""
    if profile_handle:
        p = ezpath.make_path(ctx.entity(profile_handle))
        pts = list(p.flattening(0.01))
        if pts[0].isclose(pts[-1]):
            pts.pop()
    elif profile:
        pts = vecs(profile, 3)
    else:
        raise CadError("Give profile points or profile_handle")
    if path:
        route = vecs(path, 2)
    elif height is not None:
        base = pts[0].z
        route = [Vec3(0, 0, base), Vec3(0, 0, base + float(height))]
        pts = [Vec3(v.x, v.y, 0) for v in pts]
    else:
        raise CadError("Give height or path")
    # profile must be counter-clockwise
    area = sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts.reverse()
    mt = forms.extrude(pts, route, close=True, caps=True)
    return _mesh(ctx, mt, space, props)


@op(T3, "revolve", mutates=True)
def revolve(ctx: Ctx, profile, axis=(0, 1, 0), angle: float = 360, segments: int = 32,
            space=None, **props):
    """Revolve a profile polyline (points) around an axis through the origin (default Y axis)."""
    mt = forms.rotation_form(segments, vecs(profile, 2), angle=math.radians(angle), axis=vec(axis),
                             caps=False)
    return _mesh(ctx, mt, space, props)


@op(T3, "mesh", mutates=True)
def mesh(ctx: Ctx, vertices, faces, space=None, **props):
    """Free-form mesh: vertices=[[x,y,z],...], faces=[[i0,i1,i2(,i3)],...]."""
    e = _lay(ctx, space).add_mesh()
    with e.edit_data() as data:
        data.vertices = vecs(vertices, 3)
        data.faces = [list(map(int, f)) for f in faces]
    return _done(finish(ctx.doc, e, pick_props(props)))
