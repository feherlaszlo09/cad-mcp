"""Tool `terrain`: survey points (e.g. EOV x,y,z CSV), triangulated terrain
surface (TIN), contour lines, spot elevations and terrain along an alignment."""

from __future__ import annotations

import csv
import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.tri import LinearTriInterpolator, Triangulation  # noqa: E402

from .core import CadError, Ctx, ensure_layer, op, select_from, vec  # noqa: E402

T = "terrain"
_CACHE: dict = {}


def _registry(ctx: Ctx) -> dict:
    from .ops_road import _load

    return _load(ctx, "SURFACES") or {}


def _save_registry(ctx: Ctx, reg: dict) -> None:
    from .ops_road import _store

    _store(ctx, "SURFACES", reg)


@op(T, "import_points", mutates=True)
def import_points(ctx: Ctx, path: str | None = None, text: str | None = None, order: str = "id,x,y,z,code",
                  delimiter: str | None = None, layer: str = "GEODEZIA_PONTOK", label: bool = True,
                  text_height: float = 0.5, decimals: int = 2, space=None):
    """Load survey points from a CSV/TXT file (or pasted text). order = column meaning, e.g. "id,x,y,z,code", "x,y,z", "id,y,x,z" (EOV: Y east, X north -> map to x,y). Creates 3D POINT entities and elevation labels."""
    if path:
        p = ctx.resolve(path)
        if not p.is_file():
            raise CadError(f"File not found: {p}")
        raw = p.read_text(encoding="utf-8-sig", errors="replace")
    elif text:
        raw = text
    else:
        raise CadError("Give path or text")
    cols = [c.strip().lower() for c in order.split(",")]
    for need in ("x", "y", "z"):
        if need not in cols:
            raise CadError(f"order must contain x, y and z (got {order})")
    if delimiter is None:
        sample = raw[:2000]
        delimiter = ";" if sample.count(";") > sample.count(",") else ("," if "," in sample else None)
    rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter)) if delimiter else [
        ln.split() for ln in raw.splitlines()]
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    n, skipped, hs = 0, 0, []
    for r in rows:
        r = [c.strip() for c in r if c.strip() != ""] if delimiter is None else [c.strip() for c in r]
        if len(r) < len(cols) - (1 if "code" in cols else 0):
            skipped += 1
            continue
        rec = dict(zip(cols, r))
        try:
            x, y, z = float(rec["x"].replace(",", ".")), float(rec["y"].replace(",", ".")), float(
                rec["z"].replace(",", "."))
        except ValueError:
            skipped += 1  # header or bad line
            continue
        e = lay.add_point((x, y, z), dxfattribs={"layer": layer})
        hs.append(e.dxf.handle)
        if label:
            lbl = f"{z:.{decimals}f}"
            if rec.get("id"):
                lbl = f"{rec['id']}  {lbl}"
            lay.add_text(lbl, height=text_height, dxfattribs={"layer": layer + "_FELIRAT"}).set_placement(
                (x + text_height * 0.5, y + text_height * 0.2))
        n += 1
    if n == 0:
        raise CadError("No point rows recognised; check order and delimiter")
    return {"points": n, "skipped_lines": skipped, "handles": hs[:50], "layer": layer}


def _collect_xyz(ctx: Ctx, sel, points) -> np.ndarray:
    pts = []
    if points:
        pts += [tuple(vec(p)) for p in points]
    if sel is not None:
        for e in select_from(ctx, sel):
            t = e.dxftype()
            if t == "POINT":
                pts.append(tuple(e.dxf.location))
            elif t == "POLYLINE":
                pts += [tuple(v) for v in e.points()]
            elif t == "LWPOLYLINE":
                z = e.dxf.get("elevation", 0)
                pts += [(x, y, z) for x, y in e.get_points("xy")]
            elif t == "3DFACE":
                pts += [tuple(v) for v in e.wcs_vertices()]
            elif t == "INSERT":
                pts.append(tuple(e.dxf.insert))
    if len(pts) < 3:
        raise CadError("Need at least 3 points with elevations (POINT, 3D polylines, contours or points=[[x,y,z],...])")
    arr = np.unique(np.round(np.array(pts, dtype=float), 6), axis=0)
    return arr


@op(T, "surface", mutates=True)
def surface(ctx: Ctx, name: str, sel=None, points: list | None = None, max_edge: float | None = None,
            layer: str | None = None, space=None):
    """Triangulated terrain surface (TIN) from points/3D polylines/contours (sel) or points=[[x,y,z],...]. max_edge drops long triangles at the outer edge. Stored as a MESH on layer TEREP_<name>."""
    xyz = _collect_xyz(ctx, sel, points)
    try:
        tri = Triangulation(xyz[:, 0], xyz[:, 1])
    except Exception as exc:
        raise CadError(f"Triangulation failed (points collinear?): {exc}") from exc
    triangles = tri.triangles
    if max_edge:
        x, y = xyz[:, 0], xyz[:, 1]
        keep = []
        for t in triangles:
            ok = all(math.hypot(x[t[i]] - x[t[(i + 1) % 3]], y[t[i]] - y[t[(i + 1) % 3]]) <= max_edge for i in range(3))
            keep.append(ok)
        triangles = triangles[np.array(keep)]
    if len(triangles) == 0:
        raise CadError("No triangles left; increase max_edge")
    lay_name = layer or f"TEREP_{name}"
    ensure_layer(ctx.doc, lay_name)
    mesh = ctx.layout(space).add_mesh(dxfattribs={"layer": lay_name, "color": 8})
    with mesh.edit_data() as data:
        data.vertices = [tuple(v) for v in xyz]
        data.faces = [list(map(int, t)) for t in triangles]
    reg = _registry(ctx)
    reg[name] = mesh.dxf.handle
    _save_registry(ctx, reg)
    _CACHE.pop((id(ctx.doc), name), None)
    z = xyz[:, 2]
    return {"surface": name, "handle": mesh.dxf.handle, "points": len(xyz), "triangles": int(len(triangles)),
            "z_min": round(float(z.min()), 3), "z_max": round(float(z.max()), 3)}


def _surface_tri(ctx: Ctx, name: str):
    reg = _registry(ctx)
    if name not in reg:
        raise CadError(f"No terrain surface '{name}'. Surfaces: {list(reg)}")
    key = (id(ctx.doc), name)
    mesh = ctx.entity(reg[name])
    sig = (len(mesh.vertices), len(mesh.faces))
    if key in _CACHE and _CACHE[key][0] == sig:
        return _CACHE[key][1]
    v = np.array([tuple(p) for p in mesh.vertices], dtype=float)
    faces = np.array([list(f)[:3] for f in mesh.faces], dtype=int)
    tri = Triangulation(v[:, 0], v[:, 1], faces)
    _CACHE[key] = (sig, (tri, v[:, 2]))
    return tri, v[:, 2]


def surface_interpolator(ctx: Ctx, name: str):
    tri, z = _surface_tri(ctx, name)
    f = LinearTriInterpolator(tri, z)

    def at(x: float, y: float):
        val = f(x, y)
        return None if np.ma.is_masked(val) else float(val)

    return at


@op(T, "elevation")
def elevation(ctx: Ctx, name: str, points: list):
    """Terrain elevation at points [[x,y], ...] (None outside the surface)."""
    f = surface_interpolator(ctx, name)
    out = []
    for p in points:
        x, y = vec(p).vec2
        z = f(x, y)
        out.append({"point": [x, y], "z": None if z is None else round(z, 4)})
    return {"elevations": out}


@op(T, "contours", mutates=True)
def contours(ctx: Ctx, name: str, interval: float = 1.0, major_every: int = 5, label: bool = True,
             text_height: float = 1.0, layer: str = "SZINTVONAL", major_layer: str = "SZINTVONAL_FO", space=None):
    """Contour lines (szintvonalak) of a surface every interval; every major_every-th on the major layer with elevation labels. Polylines carry their elevation."""
    tri, z = _surface_tri(ctx, name)
    lo = math.ceil(z.min() / interval) * interval
    hi = math.floor(z.max() / interval) * interval
    if hi < lo:
        raise CadError("Surface is flatter than one contour interval")
    levels = list(np.arange(lo, hi + interval / 2, interval))
    fig, ax = plt.subplots()
    try:
        cs = ax.tricontour(tri, z, levels=levels)
        segs = cs.allsegs
    finally:
        plt.close(fig)
    ensure_layer(ctx.doc, layer)
    ensure_layer(ctx.doc, major_layer)
    ctx.doc.layers.get(major_layer).color = 1 if ctx.doc.layers.get(major_layer).color == 7 else ctx.doc.layers.get(major_layer).color
    lay = ctx.layout(space)
    n = 0
    for lev, lines in zip(levels, segs):
        major = major_every and round(lev / interval) % major_every == 0
        lname = major_layer if major else layer
        for arr in lines:
            if len(arr) < 2:
                continue
            closed = bool(np.allclose(arr[0], arr[-1]))
            pts = [tuple(p) for p in (arr[:-1] if closed else arr)]
            e = lay.add_lwpolyline(pts, close=closed, dxfattribs={"layer": lname, "elevation": float(lev)})
            n += 1
            if label and major and len(arr) > 4:
                i = len(arr) // 2
                (x0, y0), (x1, y1) = arr[i - 1], arr[i + 1]
                ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
                if 90 < ang % 360 < 270:
                    ang += 180
                from ezdxf.enums import TextEntityAlignment

                lay.add_text(f"{lev:.1f}", height=text_height, rotation=ang,
                             dxfattribs={"layer": major_layer}).set_placement(
                    tuple(arr[i]), align=TextEntityAlignment.MIDDLE_CENTER)
            _ = e
    return {"contours": n, "levels": [round(float(v), 3) for v in levels]}


@op(T, "along_alignment")
def along_alignment(ctx: Ctx, name: str, alignment: str, step: float = 10.0):
    """Terrain elevations along an alignment: [[station, z], ...] (feeds road.profile terrain)."""
    from .ops_road import _m, get_alignment

    al, _ = get_alignment(ctx, alignment)
    f = surface_interpolator(ctx, name)
    m = _m(ctx)
    out = []
    for s in al.stations(step):
        x, y, _h = al.point_at(s)
        zz = f(x * m, y * m)
        if zz is not None:
            out.append([round(s, 3), round(zz / m, 4)])
    return {"terrain": out}


@op(T, "list")
def surfaces(ctx: Ctx):
    """Terrain surfaces stored in the drawing."""
    out = []
    for n, h in _registry(ctx).items():
        try:
            tri, z = _surface_tri(ctx, n)
            out.append({"name": n, "handle": h, "triangles": int(len(tri.triangles)),
                        "z_min": round(float(z.min()), 3), "z_max": round(float(z.max()), 3)})
        except CadError:
            out.append({"name": n, "handle": h, "missing": True})
    return {"surfaces": out}
