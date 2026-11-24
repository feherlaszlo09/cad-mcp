"""Tool `geo`: georeference (EOV = EPSG:23700 by default): coordinate conversion
EOV <-> WGS84 (GPS) <-> any EPSG, GPS points into the drawing, AutoCAD geographic
location (GEODATA) and Google Earth KML export. Drawing x = EOV Y (east),
drawing y = EOV X (north)."""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from ezdxf import path as ezpath

from .core import CadError, Ctx, ensure_layer, op, select_from, vec

T = "geo"
DEFAULT_CRS = "EPSG:23700"


def _tr(src: str, dst: str):
    try:
        from pyproj import Transformer
    except ImportError as exc:  # pragma: no cover
        raise CadError("pyproj is not installed: pip install pyproj") from exc
    try:
        return Transformer.from_crs(src, dst, always_xy=True)
    except Exception as exc:
        raise CadError(f"Unknown coordinate system {src} or {dst}: {exc}") from exc


def _drawing_crs(ctx: Ctx, crs: str | None) -> str:
    if crs:
        return crs
    from .ops_road import _load

    return (_load(ctx, "GEO") or {}).get("crs", DEFAULT_CRS)


@op(T, "convert")
def convert(ctx: Ctx, points: list, from_crs: str = DEFAULT_CRS, to_crs: str = "EPSG:4326"):
    """Convert coordinates between systems (EPSG codes). EPSG:4326 (GPS) is [lon, lat] in degrees; EOV (EPSG:23700) is [Y east, X north]. Accuracy of HD72->WGS84 without correction grid: about 1 m."""
    t = _tr(from_crs, to_crs)
    out = []
    for p in points:
        x, y = float(p[0]), float(p[1])
        a, b = t.transform(x, y)
        out.append([round(a, 9 if to_crs == "EPSG:4326" else 4), round(b, 9 if to_crs == "EPSG:4326" else 4)])
    return {"from": from_crs, "to": to_crs, "points": out}


@op(T, "gps_points", mutates=True)
def gps_points(ctx: Ctx, points: list, latlon: bool = True, crs: str | None = None, layer: str = "GPS_PONTOK",
               labels: list | None = None, text_height: float = 1.0, space=None):
    """Put GPS (WGS84) positions into the drawing: points [[lat, lon], ...] (or [lon, lat] with latlon=false), converted to the drawing CRS (default EOV)."""
    t = _tr("EPSG:4326", _drawing_crs(ctx, crs))
    lay = ctx.layout(space)
    ensure_layer(ctx.doc, layer)
    hs, out = [], []
    for i, p in enumerate(points):
        lat, lon = (p[0], p[1]) if latlon else (p[1], p[0])
        x, y = t.transform(float(lon), float(lat))
        z = float(p[2]) if len(p) > 2 else 0.0
        hs.append(lay.add_point((x, y, z), dxfattribs={"layer": layer}).dxf.handle)
        out.append([round(x, 3), round(y, 3)])
        if labels and i < len(labels):
            lay.add_text(str(labels[i]), height=text_height, dxfattribs={"layer": layer}).set_placement(
                (x + text_height * 0.5, y + text_height * 0.3))
    return {"handles": hs, "drawing_coords": out}


def _ll(t, x, y):
    lon, lat = t.transform(x, y)
    return lon, lat


@op(T, "set_location", mutates=True)
def set_location(ctx: Ctx, crs: str = DEFAULT_CRS, design_point=None):
    """Store the drawing's coordinate system and write AutoCAD geographic location (GEODATA) so AutoCAD can place the drawing on a map. Uses a World Mercator local grid fitted at design_point (default: centre of the drawing)."""
    from ezdxf import bbox

    from .ops_road import _store

    if not ctx.doc.units:
        raise CadError("Set drawing units first (drawing.set_units units='m')")
    if design_point is None:
        ext = bbox.extents(ctx.msp, fast=True)
        if not ext.has_data:
            raise CadError("Empty drawing: give design_point")
        dp = ext.center
    else:
        dp = vec(design_point)
    to_ll = _tr(crs, "EPSG:4326")
    lon, lat = _ll(to_ll, dp.x, dp.y)
    merc = _tr("EPSG:4326", "EPSG:3395")
    mx, my = merc.transform(lon, lat)
    # grid north of the drawing vs geographic north (meridian convergence)
    back = _tr("EPSG:4326", crs)
    nx, ny = back.transform(lon, lat + 0.001)
    north = (nx - dp.x, ny - dp.y)
    ln = math.hypot(*north)
    north = (north[0] / ln, north[1] / ln)
    msp = ctx.msp
    geo = msp.get_geodata() or msp.new_geodata()
    geo.setup_local_grid(design_point=(dp.x, dp.y, 0), reference_point=(mx, my), north_direction=north)
    _store(ctx, "GEO", {"crs": crs, "design_point": [dp.x, dp.y], "lon": lon, "lat": lat})
    conv = math.degrees(math.atan2(north[0], north[1]))
    return {"crs": crs, "design_point": [round(dp.x, 3), round(dp.y, 3)], "lat": round(lat, 8),
            "lon": round(lon, 8), "meridian_convergence_deg": round(conv, 5),
            "note": "Geographic location written as World Mercator local grid (check with GEOGRAPHICLOCATION in AutoCAD)."}


@op(T, "location")
def location(ctx: Ctx):
    """Read the stored coordinate system and geographic location of the drawing."""
    from .ops_road import _load

    g = _load(ctx, "GEO")
    geo = ctx.msp.get_geodata()
    return {"crs": (g or {}).get("crs"), "stored": g, "has_geodata": geo is not None}


def _coords_of(e, t):
    kind = e.dxftype()
    if kind == "POINT":
        return "Point", [_ll(t, *tuple(e.dxf.location)[:2])]
    if kind == "INSERT":
        return "Point", [_ll(t, *tuple(e.dxf.insert)[:2])]
    if kind in ("TEXT", "MTEXT"):
        return "Point", [_ll(t, *tuple(e.dxf.insert)[:2])]
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        return None, []
    pts = [(v.x, v.y) for v in p.flattening(0.25)]
    if len(pts) < 2:
        return None, []
    return "LineString", [_ll(t, x, y) for x, y in pts]


@op(T, "export_kml")
def export_kml(ctx: Ctx, path: str, sel=None, crs: str | None = None, name: str = "Terv"):
    """Export entities to KML for Google Earth / Google Maps (lines, polylines, arcs, splines as paths; points, blocks, texts as placemarks), grouped by layer. Coordinates converted from the drawing CRS (default EOV)."""
    t = _tr(_drawing_crs(ctx, crs), "EPSG:4326")
    ents = select_from(ctx, sel if sel is not None else {"all": True})
    by_layer: dict[str, list[str]] = {}
    n = 0
    for e in ents:
        kind, coords = _coords_of(e, t)
        if not kind:
            continue
        label = ""
        if e.dxftype() == "TEXT":
            label = e.dxf.text
        elif e.dxftype() == "MTEXT":
            label = e.plain_text()
        elif e.dxftype() == "INSERT":
            label = e.dxf.name
        cs = " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in coords)
        geom = f"<{kind}><coordinates>{cs}</coordinates></{kind}>"
        by_layer.setdefault(e.dxf.layer, []).append(
            f"<Placemark><name>{escape(label or e.dxftype())}</name><styleUrl>#s</styleUrl>{geom}</Placemark>")
        n += 1
    if not n:
        raise CadError("Nothing exportable in the selection")
    folders = "".join(f"<Folder><name>{escape(layer)}</name>{''.join(items)}</Folder>"
                      for layer, items in by_layer.items())
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{escape(name)}</name><Style id=\"s\"><LineStyle><color>ff0000ff</color><width>2</width>"
           f"</LineStyle></Style>{folders}</Document></kml>")
    p = ctx.resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(kml, encoding="utf-8")
    return {"exported": str(p), "placemarks": n, "layers": list(by_layer)}


def _features(path, fmt: str):
    """Yield (geometry type, list of coordinate rings/lines/points, properties) in the file's own CRS."""
    import json
    import xml.etree.ElementTree as ET

    if fmt in ("geojson", "json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        feats = data["features"] if data.get("type") == "FeatureCollection" else [data]
        for f in feats:
            g = f.get("geometry") or {}
            props = f.get("properties") or {}
            t, c = g.get("type"), g.get("coordinates")
            if t == "Point":
                yield "point", [c], props
            elif t == "MultiPoint":
                for q in c:
                    yield "point", [q], props
            elif t == "LineString":
                yield "line", c, props
            elif t == "MultiLineString":
                for ln in c:
                    yield "line", ln, props
            elif t == "Polygon":
                for ring in c:
                    yield "polygon", ring, props
            elif t == "MultiPolygon":
                for poly in c:
                    for ring in poly:
                        yield "polygon", ring, props
    elif fmt == "shp":
        import shapefile

        with shapefile.Reader(str(path)) as r:
            names = [f[0] for f in r.fields[1:]]
            for sr in r.iterShapeRecords():
                props = dict(zip(names, sr.record))
                sh = sr.shape
                pts = [tuple(q) for q in sh.points]
                parts = list(sh.parts) + [len(pts)]
                zs = list(getattr(sh, "z", []) or [])
                if zs:
                    pts = [(x, y, z) for (x, y), z in zip(pts, zs)]
                kind = {1: "point", 11: "point", 21: "point", 8: "point", 18: "point", 28: "point",
                        3: "line", 13: "line", 23: "line", 5: "polygon", 15: "polygon", 25: "polygon"}.get(sh.shapeType)
                if kind == "point":
                    for q in pts:
                        yield "point", [q], props
                elif kind:
                    for a, b in zip(parts, parts[1:]):
                        yield kind, pts[a:b], props
    elif fmt in ("kml", "gpx"):
        root = ET.parse(path).getroot()
        if fmt == "kml":
            for pm in root.iter():
                if not pm.tag.endswith("Placemark"):
                    continue
                name = next((c.text for c in pm if c.tag.endswith("name")), "")
                for g in pm.iter():
                    tag = g.tag.split("}")[-1]
                    if tag in ("Point", "LineString", "LinearRing"):
                        co = next((c.text for c in g if c.tag.endswith("coordinates")), "") or ""
                        pts = [tuple(float(v) for v in t.split(",")) for t in co.split()]
                        kind = {"Point": "point", "LineString": "line", "LinearRing": "polygon"}[tag]
                        yield kind, pts, {"name": name}
        else:
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag == "wpt":
                    name = next((c.text for c in el if c.tag.endswith("name")), "")
                    ele = next((float(c.text) for c in el if c.tag.endswith("ele")), 0.0)
                    yield "point", [(float(el.get("lon")), float(el.get("lat")), ele)], {"name": name}
                elif tag in ("trkseg", "rte"):
                    pts = [(float(c.get("lon")), float(c.get("lat"))) for c in el if c.tag.split("}")[-1] in ("trkpt", "rtept")]
                    if pts:
                        yield "line", pts, {}
    else:
        raise CadError("Supported: .geojson/.json, .shp, .kml, .gpx")


@op(T, "import_vector", mutates=True)
def import_vector(ctx: Ctx, path: str, source_crs: str | None = None, crs: str | None = None,
                  layer: str = "GIS", layer_field: str | None = None, label_field: str | None = None,
                  text_height: float = 1.0, space=None):
    """Import GIS data (GeoJSON, Shapefile, KML, GPX) into the drawing, converted to the drawing CRS (default EOV): points -> POINT (+label), lines -> polylines, polygons -> closed polylines. source_crs defaults to WGS84 for GeoJSON/KML/GPX and to the .prj of a shapefile. layer_field puts features on layers by an attribute."""
    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    fmt = p.suffix.lower().lstrip(".")
    src = source_crs
    if src is None:
        if fmt == "shp" and p.with_suffix(".prj").is_file():
            src = p.with_suffix(".prj").read_text(encoding="utf-8", errors="replace")
        elif fmt == "shp":
            src = _drawing_crs(ctx, crs)  # assume already in the drawing CRS
        else:
            src = "EPSG:4326"
    dst = _drawing_crs(ctx, crs)
    t = _tr(src, dst) if src != dst else None
    lay = ctx.layout(space)
    counts = {"point": 0, "line": 0, "polygon": 0}
    for kind, coords, props in _features(p, fmt):
        lname = layer
        if layer_field and props.get(layer_field) not in (None, ""):
            lname = f"{layer}_{props[layer_field]}"
        ensure_layer(ctx.doc, lname)
        pts = []
        for c in coords:
            x, y = (t.transform(c[0], c[1]) if t else (c[0], c[1]))
            pts.append((x, y, c[2] if len(c) > 2 else 0.0))
        if kind == "point":
            lay.add_point(pts[0], dxfattribs={"layer": lname})
            if label_field and props.get(label_field) not in (None, ""):
                lay.add_text(str(props[label_field]), height=text_height, dxfattribs={"layer": lname}).set_placement(
                    (pts[0][0] + text_height * 0.5, pts[0][1] + text_height * 0.3))
        elif len(pts) >= 2:
            closed = kind == "polygon"
            if closed and len(pts) > 2 and pts[0][:2] == pts[-1][:2]:
                pts = pts[:-1]
            if any(abs(q[2]) > 0 for q in pts):
                lay.add_polyline3d(pts, close=closed, dxfattribs={"layer": lname})
            else:
                lay.add_lwpolyline([q[:2] for q in pts], close=closed, dxfattribs={"layer": lname})
            if label_field and props.get(label_field) not in (None, ""):
                cx = sum(q[0] for q in pts) / len(pts)
                cy = sum(q[1] for q in pts) / len(pts)
                lay.add_text(str(props[label_field]), height=text_height, dxfattribs={"layer": lname}).set_placement((cx, cy))
        counts[kind] += 1
    return {"imported": counts, "from_crs": src if len(str(src)) < 40 else "(.prj)", "to_crs": dst}
