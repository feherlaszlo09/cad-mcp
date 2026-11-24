"""3D solids: more primitives (wedge, pyramid, sweep, loft, polysolid, presspull),
real 3DSOLID output (faceted ACIS), boolean union/subtract/intersect, slice, section,
flatshot and mass properties (2D regions and 3D bodies)."""

from __future__ import annotations

import math

import numpy as np
from ezdxf.math import Matrix44, Vec2, Vec3
from ezdxf.render import MeshBuilder, forms

from .core import CadError, Ctx, finish, handles, op, pick_props, select_from, vec, vecs

T3 = "draw3d"


# ---------------------------------------------------------------------------
# output: MESH or real 3DSOLID
# ---------------------------------------------------------------------------


def _triangulated(mb: MeshBuilder) -> MeshBuilder:
    out = MeshBuilder()
    for face in mb.faces_as_vertices():
        f = list(face)
        for i in range(1, len(f) - 1):
            out.add_face([f[0], f[i], f[i + 1]])
    return out


def emit(ctx: Ctx, mb: MeshBuilder, space, props, solid: bool):
    """Write a MeshBuilder as MESH, or as a faceted ACIS 3DSOLID (AutoCAD-native solid)."""
    lay = ctx.layout(space)
    if solid:
        from ezdxf.acis import api as acis

        if ctx.doc.dxfversion < "AC1015":
            raise CadError("3DSOLID needs a DXF R2000 or newer drawing")
        tri = _triangulated(mb)
        body = acis.body_from_mesh(tri)
        e = lay.add_3dsolid()
        acis.export_dxf(e, [body])
    else:
        e = mb.render_mesh(lay)
    return finish(ctx.doc, e, pick_props(props))


def _done(*ents):
    return {"handles": handles(ents), "type": ents[0].dxftype() if ents else None}


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


@op(T3, "wedge", mutates=True)
def wedge(ctx: Ctx, origin, size, solid: bool = False, space=None, **props):
    """WEDGE: base dx x dy at origin, height dz at the x=origin edge sloping down to x+dx."""
    o = vec(origin)
    dx, dy, dz = vec(size).xyz
    v = [o + Vec3(*p) for p in ((0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0), (0, 0, dz), (0, dy, dz))]
    mb = MeshBuilder()
    mb.add_mesh(vertices=v, faces=[(0, 3, 2, 1), (0, 1, 4), (3, 5, 2), (0, 4, 5, 3), (1, 2, 5, 4)])
    return _done(emit(ctx, mb, space, props, solid))


@op(T3, "pyramid", mutates=True)
def pyramid(ctx: Ctx, base_center, radius: float, height: float, sides: int = 4, top_radius: float = 0.0,
            rotation: float = 0.0, solid: bool = False, space=None, **props):
    """PYRAMID: regular n-sided pyramid (or frustum with top_radius) on base_center."""
    c = vec(base_center)
    a0 = math.radians(rotation)
    base = [c + Vec3(radius * math.cos(a0 + 2 * math.pi * i / sides), radius * math.sin(a0 + 2 * math.pi * i / sides), 0)
            for i in range(sides)]
    mb = MeshBuilder()
    if top_radius > 0:
        top = [c + Vec3(top_radius * math.cos(a0 + 2 * math.pi * i / sides),
                        top_radius * math.sin(a0 + 2 * math.pi * i / sides), height) for i in range(sides)]
        faces = [list(range(sides - 1, -1, -1)), list(range(sides, 2 * sides))]
        faces += [(i, (i + 1) % sides, sides + (i + 1) % sides, sides + i) for i in range(sides)]
        mb.add_mesh(vertices=base + top, faces=faces)
    else:
        apex = c + Vec3(0, 0, height)
        faces = [list(range(sides - 1, -1, -1))] + [(i, (i + 1) % sides, sides) for i in range(sides)]
        mb.add_mesh(vertices=base + [apex], faces=faces)
    return _done(emit(ctx, mb, space, props, solid))


def _points_of(ctx: Ctx, pts, handle, close_hint=False):
    if handle:
        from ezdxf import path as ezpath

        e = ctx.entity(handle)
        out = list(ezpath.make_path(e).flattening(0.01))
        if e.dxftype() == "LWPOLYLINE" and e.dxf.get("elevation"):
            out = [Vec3(p.x, p.y, e.dxf.elevation) for p in out]
        if len(out) > 2 and out[0].isclose(out[-1]):
            out.pop()
        return out
    if not pts:
        raise CadError("Give points or a handle")
    return vecs(pts, 2)


@op(T3, "sweep", mutates=True)
def sweep(ctx: Ctx, path=None, path_handle: str | None = None, profile=None, profile_handle: str | None = None,
          solid: bool = False, space=None, **props):
    """SWEEP: sweep a closed 2D profile (in its own XY plane, centred on the origin) along a path (points or a curve handle)."""
    prof = _points_of(ctx, profile, profile_handle)
    route = _points_of(ctx, path, path_handle)
    area = sum(a.x * b.y - b.x * a.y for a, b in zip(prof, prof[1:] + prof[:1]))
    if area < 0:
        prof = list(reversed(prof))
    mt = forms.sweep([Vec3(p.x, p.y, 0) for p in prof], route, close=True, caps=True)
    return _done(emit(ctx, mt, space, props, solid))


@op(T3, "loft", mutates=True)
def loft(ctx: Ctx, profiles: list | None = None, profile_handles: list | None = None, smooth: bool = False,
         solid: bool = False, space=None, **props):
    """LOFT: surface/solid through cross-section profiles (each a closed list of 3D points, or closed polylines at their elevation), all with the same number of points; smooth=true interpolates with splines."""
    profs = [vecs(p, 3) for p in (profiles or [])] + [_points_of(ctx, None, h) for h in (profile_handles or [])]
    if len(profs) < 2:
        raise CadError("Need at least two profiles")
    n = len(profs[0])
    if any(len(p) != n for p in profs):
        raise CadError("All profiles need the same number of points")
    mt = (forms.from_profiles_spline(profs, close=True, caps=True) if smooth
          else forms.from_profiles_linear(profs, close=True, caps=True))
    return _done(emit(ctx, mt, space, props, solid))


@op(T3, "polysolid", mutates=True)
def polysolid(ctx: Ctx, path=None, path_handle: str | None = None, width: float = 0.3, height: float = 3.0,
              justify: str = "center", solid: bool = True, space=None, **props):
    """POLYSOLID: wall-like solid of width x height following a 2D path (points or a curve); justify center|left|right."""
    route = _points_of(ctx, path, path_handle)
    off = {"center": 0.0, "left": width / 2, "right": -width / 2}.get(justify)
    if off is None:
        raise CadError("justify: center, left, right")
    # rectangular profile in the sweep plane: x across the path, y up
    prof = [Vec3(-width / 2 + off, 0, 0), Vec3(width / 2 + off, 0, 0), Vec3(width / 2 + off, height, 0),
            Vec3(-width / 2 + off, height, 0)]
    mt = forms.sweep(prof, [Vec3(p.x, p.y, p.z) for p in route], close=True, caps=True)
    return _done(emit(ctx, mt, space, props, solid))


@op(T3, "presspull", mutates=True)
def presspull(ctx: Ctx, point, height: float, sel=None, solid: bool = True, space=None, **props):
    """PRESSPULL: extrude the closed area around a point (bounded by existing lines/arcs/polylines, islands become holes) by height."""
    import manifold3d as mf
    from shapely.geometry.polygon import orient

    from .ops_more import boundary_polygon

    poly, holes = boundary_polygon(ctx, point, sel, space)
    # outer boundary counter-clockwise, islands clockwise -> holes for manifold's positive fill rule
    rings = [list(orient(poly, 1.0).exterior.coords)[:-1]] + [list(orient(h, -1.0).exterior.coords)[:-1] for h in holes]
    cs = mf.CrossSection([np.array(r, dtype=np.float64) for r in rings])
    body = mf.Manifold.extrude(cs, float(abs(height)))
    if height < 0:
        body = body.translate([0, 0, float(height)])
    return _done(emit(ctx, _to_builder(body), space, props, solid))


# ---------------------------------------------------------------------------
# conversion helpers
# ---------------------------------------------------------------------------


def _to_manifold(ctx: Ctx, ents):
    import manifold3d as mf

    from .render import _triangles

    tris = _triangles(ctx, ents)
    if not tris:
        raise CadError("No 3D body in the selection (MESH, 3DSOLID, polyface or 3DFACEs)")
    idx: dict = {}
    verts, faces = [], []
    for tri in tris:
        f = []
        for v in tri:
            key = (round(v.x, 9), round(v.y, 9), round(v.z, 9))
            if key not in idx:
                idx[key] = len(verts)
                verts.append(key)
            f.append(idx[key])
        if len(set(f)) == 3:
            faces.append(f)
    m = mf.Manifold(mf.Mesh(vert_properties=np.array(verts, dtype=np.float32),
                            tri_verts=np.array(faces, dtype=np.uint32)))
    if m.status() != mf.Error.NoError or m.is_empty():
        raise CadError(f"Not a closed solid body ({m.status()}): booleans need watertight bodies")
    return m


def _to_builder(m) -> MeshBuilder:
    mesh = m.to_mesh()
    mb = MeshBuilder()
    mb.add_mesh(vertices=[Vec3(*map(float, v[:3])) for v in mesh.vert_properties],
                faces=[tuple(int(i) for i in f) for f in mesh.tri_verts])
    return mb


def _delete(ents):
    for e in ents:
        e.get_layout().delete_entity(e)


@op(T3, "boolean", mutates=True)
def boolean(ctx: Ctx, kind: str, sel_a, sel_b, keep_originals: bool = False, solid: bool = True,
            space=None, **props):
    """UNION / SUBTRACT / INTERSECT of closed 3D bodies (MESH, faceted 3DSOLID): kind union | subtract (a minus b) | intersect. Result as 3DSOLID (or MESH with solid=false)."""
    a_ents, b_ents = select_from(ctx, sel_a), select_from(ctx, sel_b)
    a, b = _to_manifold(ctx, a_ents), _to_manifold(ctx, b_ents)
    op_ = kind.lower()
    if op_ == "union":
        r = a + b
    elif op_ == "subtract":
        r = a - b
    elif op_ in ("intersect", "intersection"):
        r = a ^ b
    else:
        raise CadError("kind: union, subtract, intersect")
    if r.is_empty():
        raise CadError("The result is empty")
    if not keep_originals:
        _delete(a_ents + b_ents)
    e = emit(ctx, _to_builder(r), space, props, solid)
    return {"handles": [e.dxf.handle], "volume": round(r.volume(), 6)}


def _plane(point, normal):
    n = vec(normal).normalize()
    if n.magnitude < 0.5:
        raise CadError("normal must not be zero")
    return n, n.dot(vec(point))


@op(T3, "slice", mutates=True)
def slice_(ctx: Ctx, sel, point, normal, keep: str = "both", solid: bool = True, space=None, **props):
    """SLICE: cut closed bodies with the plane through point with normal; keep both halves, or only the 'positive' (normal side) or 'negative' one."""
    ents = select_from(ctx, sel)
    m = _to_manifold(ctx, ents)
    n, d = _plane(point, normal)
    pos, neg = m.split_by_plane(list(n.xyz), d)
    out = []
    for part, name in ((pos, "positive"), (neg, "negative")):
        if keep in ("both", name) and not part.is_empty():
            out.append((name, emit(ctx, _to_builder(part), space, props, solid), part.volume()))
    _delete(ents)
    return {"parts": [{"side": s, "handle": e.dxf.handle, "volume": round(v, 6)} for s, e, v in out]}


def _frame(n: Vec3):
    """Matrix mapping the plane normal n to +Z (and its inverse)."""
    z = Vec3(0, 0, 1)
    if n.isclose(z):
        return Matrix44(), Matrix44()
    if n.isclose(-z):
        r = Matrix44.x_rotate(math.pi)
        return r, r
    axis = n.cross(z).normalize()
    ang = math.acos(max(-1.0, min(1.0, n.dot(z))))
    r = Matrix44.axis_rotate(axis, ang)
    return r, Matrix44.axis_rotate(axis, -ang)


def _affine(m: Matrix44):
    rows = [list(m.get_row(i)) for i in range(4)]
    # ezdxf uses row vectors (v * M); manifold wants a 3x4 column-vector matrix
    return [[rows[0][0], rows[1][0], rows[2][0], rows[3][0]],
            [rows[0][1], rows[1][1], rows[2][1], rows[3][1]],
            [rows[0][2], rows[1][2], rows[2][2], rows[3][2]]]


@op(T3, "section", mutates=True)
def section(ctx: Ctx, sel, point, normal, hatch: bool = False, layer: str | None = None, space=None):
    """SECTIONPLANE / SECTION: outline (and optional solid hatch) of the cross-section of closed bodies with a plane, drawn in 3D at its true position."""
    m = _to_manifold(ctx, select_from(ctx, sel))
    n, d = _plane(point, normal)
    to_z, back = _frame(n)
    mz = m.transform(_affine(to_z))
    cs = mz.slice(d)
    polys = cs.to_polygons()
    if not polys:
        raise CadError("The plane does not cut the bodies")
    lay = ctx.layout(space)
    at = {"layer": layer} if layer else {}
    if layer:
        from .core import ensure_layer

        ensure_layer(ctx.doc, layer)
    out = []
    for ring in polys:
        pts = [back.transform(Vec3(float(x), float(y), d)) for x, y in ring]
        out.append(lay.add_polyline3d(pts, close=True, dxfattribs=at))
    if hatch and n.isclose(Vec3(0, 0, 1)):
        from .ops_draw import hatch as draw_hatch

        draw_hatch(ctx, boundary=[[list(p) for p in ring] for ring in polys], pattern="SOLID", space=space)
    return {"handles": handles(out), "area": round(cs.area(), 6), "loops": len(polys)}


def _hidden_line_edges(V: np.ndarray, F: np.ndarray, crease_deg: float):
    """Visible and hidden 2D edge pieces of a closed triangle mesh seen from +Z (larger z = nearer).
    Drawn edges: boundary edges, creases sharper than crease_deg and silhouettes."""
    tri = V[F]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-15
    nrm[ok] /= ln[ok, None]
    size = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0))) or 1.0
    eps = 1e-9 * size
    front = nrm[:, 2] > 1e-9
    edges: dict = {}
    for fi, (a, b, c) in enumerate(F):
        for i, j in ((a, b), (b, c), (c, a)):
            edges.setdefault((min(i, j), max(i, j)), []).append(fi)
    cos_crease = math.cos(math.radians(crease_deg))
    cand, back_only = [], []
    for (i, j), fs in edges.items():
        if len(fs) == 2:
            f1, f2 = fs
            if front[f1] == front[f2] and float(np.dot(nrm[f1], nrm[f2])) >= cos_crease:
                continue
        if any(front[f] for f in fs):
            cand.append((i, j, set(fs)))
        else:  # on the far side of a closed body: never visible
            back_only.append((V[i], V[j]))
    occ = np.nonzero(front)[0]
    T = tri[occ]
    T2 = T[:, :, :2]
    tmin, tmax = T2.min(axis=1), T2.max(axis=1)
    # plane z = A x + B y + C of each occluding triangle
    n_occ = nrm[occ]
    A = -n_occ[:, 0] / n_occ[:, 2]
    B = -n_occ[:, 1] / n_occ[:, 2]
    C = T[:, 0, 2] - A * T[:, 0, 0] - B * T[:, 0, 1]
    orient = np.sign((T2[:, 1, 0] - T2[:, 0, 0]) * (T2[:, 2, 1] - T2[:, 0, 1])
                     - (T2[:, 1, 1] - T2[:, 0, 1]) * (T2[:, 2, 0] - T2[:, 0, 0]))
    visible, hidden = [], []
    for i, j, own in cand:
        P, Q = V[i], V[j]
        if np.linalg.norm(Q[:2] - P[:2]) < eps:
            continue
        lo2, hi2 = np.minimum(P[:2], Q[:2]), np.maximum(P[:2], Q[:2])
        m = np.all(tmax >= lo2 - eps, axis=1) & np.all(tmin <= hi2 + eps, axis=1)
        idx = np.nonzero(m)[0]
        idx = np.array([k for k in idx if occ[k] not in own], dtype=int)
        cover = []
        if len(idx):
            t0 = np.zeros(len(idx))
            t1 = np.ones(len(idx))
            d = Q - P
            for e0, e1 in ((0, 1), (1, 2), (2, 0)):
                a2, b2 = T2[idx, e0], T2[idx, e1]
                # inside: orient * cross(b-a, x-a) >= 0, linear in t
                g0 = orient[idx] * ((b2[:, 0] - a2[:, 0]) * (P[1] - a2[:, 1]) - (b2[:, 1] - a2[:, 1]) * (P[0] - a2[:, 0]))
                gd = orient[idx] * ((b2[:, 0] - a2[:, 0]) * d[1] - (b2[:, 1] - a2[:, 1]) * d[0])
                g0 = g0 - eps * np.linalg.norm(b2 - a2, axis=1)
                t0, t1 = _clip_linear(g0, gd, t0, t1)
            # in front of the edge: plane z - edge z > eps, linear in t
            h0 = A[idx] * P[0] + B[idx] * P[1] + C[idx] - P[2] - eps
            hd = A[idx] * d[0] + B[idx] * d[1] - d[2]
            t0, t1 = _clip_linear(h0, hd, t0, t1)
            cover = sorted((float(a), float(b)) for a, b in zip(t0, t1) if b - a > 1e-9)
        merged = []
        for a, b in cover:
            if merged and a <= merged[-1][1] + 1e-12:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        cur = 0.0
        for a, b in merged:
            if a > cur + 1e-9:
                visible.append((P + (Q - P) * cur, P + (Q - P) * a))
            hidden.append((P + (Q - P) * a, P + (Q - P) * b))
            cur = max(cur, b)
        if cur < 1 - 1e-9:
            visible.append((P + (Q - P) * cur, Q))
    hidden += [(a, b) for a, b in back_only if np.linalg.norm(b[:2] - a[:2]) > eps]
    if visible and hidden:  # an obscured edge lying under a visible one is not drawn twice
        from shapely.geometry import LineString
        from shapely.ops import unary_union

        cover = unary_union([LineString([a[:2], b[:2]]) for a, b in visible]).buffer(eps * 1e3)
        hidden = [(a, b) for a, b in hidden if not cover.contains(LineString([a[:2], b[:2]]))]
    return visible, hidden


def _merge_segments(segs, tol: float):
    """Chain touching 2D pieces into polylines and drop collinear in-between vertices."""
    from shapely.geometry import LineString
    from shapely.ops import linemerge

    lines = [LineString([(round(float(a[0]), 9), round(float(a[1]), 9)), (round(float(b[0]), 9), round(float(b[1]), 9))])
             for a, b in segs]
    lines = [ln for ln in lines if ln.length > tol]
    if not lines:
        return []
    merged = linemerge(lines)
    geoms = getattr(merged, "geoms", [merged])
    return [list(g.simplify(tol).coords) for g in geoms]


def _clip_linear(g0, gd, t0, t1):
    """Restrict [t0, t1] to where g0 + gd*t >= 0 (elementwise)."""
    t0, t1 = t0.copy(), t1.copy()
    zero = np.abs(gd) < 1e-15
    bad = zero & (g0 < 0)
    t1[bad] = -1.0
    pos = ~zero & (gd > 0)
    neg = ~zero & (gd < 0)
    t0[pos] = np.maximum(t0[pos], -g0[pos] / gd[pos])
    t1[neg] = np.minimum(t1[neg], -g0[neg] / gd[neg])
    return t0, t1


@op(T3, "flatshot", mutates=True)
def flatshot(ctx: Ctx, sel, direction=(0, 0, 1), origin=(0, 0), layer: str | None = None, hidden: bool = False,
             hidden_layer: str = "FLATSHOT_TAKART", crease_angle: float = 20.0, block: str | None = None,
             outline_only: bool = False, space=None):
    """FLATSHOT: 2D view of 3D bodies seen along direction (default from the top), placed at origin on the XY plane: visible edges (outline, silhouettes and edges sharper than crease_angle) as lines, and with hidden=True the obscured edges too (HIDDEN linetype, own layer). block='NAME' collects them into a block inserted at origin, like AutoCAD. outline_only=True gives just the outer outline polygons with holes."""
    from .core import ensure_layer, ensure_linetype

    m = _to_manifold(ctx, select_from(ctx, sel))
    n = vec(direction).normalize()
    to_z, _back = _frame(n)
    mz = m.transform(_affine(to_z))
    cs = mz.project()
    polys = cs.to_polygons()
    if not polys:
        raise CadError("Nothing to project")
    o = Vec2(vec(origin).vec2)
    at = {"layer": layer} if layer else {}
    if layer:
        ensure_layer(ctx.doc, layer)
    lay = ctx.layout(space)
    target = lay
    if block:
        if ctx.doc.blocks.get(block) is not None:
            raise CadError(f"Block {block} exists")
        target = ctx.doc.blocks.new(block, base_point=(0, 0))
    off = Vec2(0, 0) if block else o
    out = []
    if outline_only:
        out = [target.add_lwpolyline([(float(x) + off.x, float(y) + off.y) for x, y in ring], close=True, dxfattribs=at)
               for ring in polys]
        vis_n = hid_n = 0
    else:
        mesh = mz.to_mesh()
        V = np.asarray(mesh.vert_properties, float)[:, :3]
        F = np.asarray(mesh.tri_verts, int)
        vis, hid = _hidden_line_edges(V, F, float(crease_angle))
        size = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0))) or 1.0

        def draw(segs, attribs):
            for pts in _merge_segments(segs, size * 1e-9):
                pts = [(x + off.x, y + off.y) for x, y in pts]
                if len(pts) == 2:
                    out.append(target.add_line(pts[0], pts[1], dxfattribs=attribs))
                else:
                    closed = math.dist(pts[0], pts[-1]) < size * 1e-9
                    out.append(target.add_lwpolyline(pts[:-1] if closed else pts, close=closed, dxfattribs=attribs))

        draw(vis, at)
        vis_n, hid_n = len(vis), 0
        if hidden:
            ensure_linetype(ctx.doc, "HIDDEN")
            ensure_layer(ctx.doc, hidden_layer)
            hl = ctx.doc.layers.get(hidden_layer)
            hl.dxf.linetype = "HIDDEN"
            hl.color = 8
            draw(hid, {"layer": hidden_layer})
            hid_n = len(hid)
    res = {"projected_area": round(cs.area(), 6), "visible_edges": vis_n, "hidden_edges": hid_n}
    if block:
        ref = lay.add_blockref(block, (o.x, o.y), dxfattribs=at)
        res.update({"block": block, "handles": [ref.dxf.handle]})
    else:
        res["handles"] = handles(out)
    return res


@op(T3, "to_solid", mutates=True)
def to_solid(ctx: Ctx, sel, keep_originals: bool = False):
    """Convert closed MESH / polyface bodies to real 3DSOLID (faceted ACIS) entities."""
    ents = select_from(ctx, sel)
    out = []
    for e in ents:
        m = _to_manifold(ctx, [e])
        s = emit(ctx, _to_builder(m), None if e.get_layout().name == "Model" else e.get_layout().name,
                 {"layer": e.dxf.layer}, True)
        out.append(s)
    if not keep_originals:
        _delete(ents)
    return {"handles": handles(out)}


@op(T3, "to_mesh", mutates=True)
def to_mesh(ctx: Ctx, sel, keep_originals: bool = False):
    """Convert faceted 3DSOLIDs (e.g. made by this tool) to editable MESH entities."""
    ents = select_from(ctx, sel)
    out = []
    for e in ents:
        m = _to_manifold(ctx, [e])
        out.append(emit(ctx, _to_builder(m), None, {"layer": e.dxf.layer}, False))
    if not keep_originals:
        _delete(ents)
    return {"handles": handles(out)}


# ---------------------------------------------------------------------------
# MASSPROP
# ---------------------------------------------------------------------------


def _region_props(coords) -> dict:
    """Area, centroid and second moments of a simple polygon (Green's theorem)."""
    a = cx = cy = ixx = iyy = ixy = 0.0
    pts = list(coords)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * cr
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * cr
        ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cr
    return {"a": a / 2, "sx": cx / 6, "sy": cy / 6, "ixx": ixx / 12, "iyy": iyy / 12, "ixy": ixy / 24}


@op("query", "massprop")
def massprop(ctx: Ctx, sel):
    """MASSPROP: 2D (closed polylines, circles, ellipses, splines, hatches, islands subtracted): area, perimeter, centroid, moments of inertia about the centroid, principal moments; 3D bodies (MESH, faceted 3DSOLID): volume, surface area, centroid, bounding box."""
    from ezdxf import path as ezpath
    from shapely.geometry import Polygon

    ents = select_from(ctx, sel)
    solids = [e for e in ents if e.dxftype() in ("MESH", "3DSOLID", "POLYLINE") and
              (e.dxftype() != "POLYLINE" or e.is_poly_face_mesh)]
    flat = [e for e in ents if e not in solids]
    out = {}
    if flat:
        shape = None
        for e in flat:
            loops = list(ezpath.from_hatch(e)) if e.dxftype() == "HATCH" else [ezpath.make_path(e)]
            from . import geom

            tol = geom.flatten_distance(e) * 0.01  # size-relative: ~1e-6 of the object size
            for p in loops:
                pts = [(v.x, v.y) for v in p.flattening(tol)]
                if len(pts) >= 3:
                    poly = Polygon(pts).buffer(0)
                    shape = poly if shape is None else shape.symmetric_difference(poly)
        if shape is None or shape.area == 0:
            raise CadError("No closed 2D area in the selection")
        polys = list(shape.geoms) if shape.geom_type == "MultiPolygon" else [shape]
        tot = {"a": 0.0, "sx": 0.0, "sy": 0.0, "ixx": 0.0, "iyy": 0.0, "ixy": 0.0}
        for poly in polys:
            for ring, sgn in [(poly.exterior, 1)] + [(r, -1) for r in poly.interiors]:
                coords = list(ring.coords)[:-1]
                r = _region_props(coords)
                s = sgn * (1 if r["a"] > 0 else -1)
                for k in tot:
                    tot[k] += s * r[k]
        A = tot["a"]
        cx, cy = tot["sx"] / A, tot["sy"] / A
        ixc, iyc = tot["ixx"] - A * cy * cy, tot["iyy"] - A * cx * cx
        ixyc = tot["ixy"] - A * cx * cy
        avg, diff = (ixc + iyc) / 2, math.hypot((ixc - iyc) / 2, ixyc)
        out["region"] = {"area": round(A, 6), "perimeter": round(shape.length, 6),
                         "centroid": [round(cx, 6), round(cy, 6)],
                         "Ix_centroid": round(ixc, 6), "Iy_centroid": round(iyc, 6), "Ixy_centroid": round(ixyc, 6),
                         "principal_moments": [round(avg + diff, 6), round(avg - diff, 6)],
                         "principal_angle_deg": round(math.degrees(0.5 * math.atan2(-2 * ixyc, ixc - iyc)), 6),
                         "radii_of_gyration": [round(math.sqrt(ixc / A), 6), round(math.sqrt(iyc / A), 6)]}
    if solids:
        m = _to_manifold(ctx, solids)
        mesh = m.to_mesh()
        v = np.asarray(mesh.vert_properties, dtype=float)[:, :3]
        f = np.asarray(mesh.tri_verts, dtype=int)
        a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        vol6 = np.einsum("ij,ij->i", a, np.cross(b, c))
        centroid = ((a + b + c) * vol6[:, None]).sum(axis=0) / (4 * vol6.sum())
        lo, hi = v.min(axis=0), v.max(axis=0)
        out["solid"] = {"volume": round(m.volume(), 6), "surface_area": round(m.surface_area(), 6),
                        "centroid": [round(float(x), 6) for x in centroid],
                        "bbox": [[round(float(x), 6) for x in lo], [round(float(x), 6) for x in hi]]}
    return out
