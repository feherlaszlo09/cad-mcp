"""Tool `utility` (közmű): gravity sewer networks (csatornahálózat) with automatic invert design,
partial-flow hydraulics (Manning or Prandtl–Colebrook) and the sewer long section
(csatorna hossz-szelvény); pressurised water networks (vízhálózat) solved by the global
gradient method (Hazen–Williams or Darcy–Weisbach); utility lines with type, status, size
and depth; clearance check between utilities (közműegyeztetés, rules from the designer /
MSZ 7487 / the operators) and utilities drawn into road cross sections.

Coordinates in metres (EOV: drawing x = Y east, y = X north); elevations in metres (Balti);
pipe diameters in metres; flows in l/s. Design limits (minimum slope, cover, velocities,
clearances) are never assumed: they are given by the designer."""

from __future__ import annotations

import json
import math

import numpy as np

from .core import CadError, Ctx, ensure_layer, handles, op, select_from

T = "utility"
G = 9.81
NU = 1.31e-6  # kinematic viscosity of water at 10 °C, m²/s

KINDS = {
    "viz": ("VIZ", 5), "szennyviz": ("SZENNYVIZ", 30), "csapadek": ("CSAPADEK", 140), "egyesitett": ("EGYESITETT", 34),
    "gaz": ("GAZ", 2), "villany": ("VILLAMOS", 1), "villany_kozep": ("VILLAMOS_KOZEP", 1),
    "villany_kis": ("VILLAMOS_KIS", 10), "kozvilagitas": ("KOZVILAGITAS", 6), "tavkozles": ("TAVKOZLES", 3),
    "tavho": ("TAVHO", 200), "olaj": ("OLAJ", 42), "egyeb": ("EGYEB", 8),
}
STATUS = {"meglevo": (0.25, "Continuous"), "tervezett": (0.5, "Continuous"), "megszuntetendo": (0.25, "DASHDOT")}


def _m(ctx: Ctx) -> float:
    from .ops_road import _m as road_m

    return road_m(ctx)


def _load(ctx: Ctx, key: str):
    from .ops_road import _load as load

    return load(ctx, key)


def _store(ctx: Ctx, key: str, data) -> None:
    from .ops_road import _store as store

    store(ctx, key, data)


def _al(name: str):
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment[name]


# ---------------------------------------------------------------------------
# hydraulics of circular pipes
# ---------------------------------------------------------------------------


def circ_section(D: float, h: float) -> tuple[float, float, float]:
    """Area, wetted perimeter, top width of a circular pipe flowing h deep."""
    h = min(max(h, 0.0), D)
    th = 2 * math.acos(max(-1.0, min(1.0, 1 - 2 * h / D)))
    A = D * D / 8 * (th - math.sin(th))
    P = D * th / 2
    return A, P, D * math.sin(th / 2)


def velocity(D: float, h: float, S: float, method: str, n: float | None, k_mm: float | None) -> float:
    A, P, _ = circ_section(D, h)
    if A <= 0 or S <= 0:
        return 0.0
    R = A / P
    if method == "manning":
        return (1.0 / n) * R ** (2 / 3) * math.sqrt(S)
    Dh = 4 * R
    k = k_mm / 1000.0
    root = math.sqrt(2 * G * Dh * S)
    return -2.0 * root * math.log10(k / (3.71 * Dh) + 2.51 * NU / (Dh * root))


def flow(D, h, S, method, n, k_mm) -> float:
    return velocity(D, h, S, method, n, k_mm) * circ_section(D, h)[0]


def partial_depth(D, Q, S, method, n, k_mm) -> float | None:
    """Flow depth for Q (m³/s); None if Q exceeds the maximum (≈ 0.94 D) capacity."""
    if Q <= 0:
        return 0.0
    hs = np.linspace(0, D, 401)
    qs = [flow(D, h, S, method, n, k_mm) for h in hs]
    i_max = int(np.argmax(qs))
    if Q > qs[i_max]:
        return None
    lo, hi = 0.0, hs[i_max]
    for _ in range(80):
        mid = (lo + hi) / 2
        if flow(D, mid, S, method, n, k_mm) < Q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# sewer network
# ---------------------------------------------------------------------------


def _surface_z(ctx: Ctx, surface: str | None, y: float, x: float) -> float | None:
    if not surface:
        return None
    from .ops_terrain import surface_interpolator

    m = _m(ctx)
    z = surface_interpolator(ctx, surface)(y * m, x * m)
    return None if z is None else z / m


@op(T, "sewer", mutates=True)
def sewer(ctx: Ctx, name: str, manholes: list, pipes: list, kind: str = "szennyviz", surface: str | None = None,
          min_slope_permille: float | None = None, min_cover: float | None = None, drop: float = 0.0,
          match: str = "invert", method: str = "manning", n: float = 0.013, k_mm: float | None = None,
          inflows: dict | None = None, min_velocity: float | None = None, max_velocity: float | None = None,
          max_fill_ratio: float | None = None, manhole_diameter: float = 1.0, draw: bool = True,
          text_height: float = 0.5, status: str = "tervezett"):
    """Gravity sewer network (gravitációs csatornahálózat): manholes = [{"name","point":[Y,X], "rim": fedlapszint (or from surface), optional "invert"}], pipes = [{"from","to","diameter" (m), optional "material", "slope_permille", "invert_from", "invert_to", "n", "k_mm"}] draining as a tree to the outfall. Missing inverts are designed downstream from min_cover (to the pipe crown) and min_slope_permille, following the terrain, with a drop (bukás) in manholes and invert or crown matching. Hydraulics: full-flow capacity and, with inflows {"manhole": l/s} (accumulated downstream), flow depth h/D and velocity (Manning n or Prandtl–Colebrook k_mm), checked against min/max velocity and max fill ratio when given. Draws manholes, pipes, labels and flow arrows; stores the network for utility.sewer_profile."""
    if method not in ("manning", "colebrook"):
        raise CadError("method: manning or colebrook")
    if method == "colebrook" and k_mm is None:
        raise CadError("colebrook needs k_mm (wall roughness, mm)")
    mh = {}
    for h in manholes:
        y, x = float(h["point"][0]), float(h["point"][1])
        rim = h.get("rim")
        rim = float(rim) if rim is not None else _surface_z(ctx, surface, y, x)
        if rim is None:
            raise CadError(f"Manhole {h['name']}: give rim or a terrain surface covering it")
        mh[str(h["name"])] = {"name": str(h["name"]), "y": y, "x": x, "rim": rim,
                              "invert": None if h.get("invert") is None else float(h["invert"])}
    P = []
    for i, p in enumerate(pipes):
        a, b = str(p["from"]), str(p["to"])
        if a not in mh or b not in mh:
            raise CadError(f"Pipe {i}: unknown manhole {a if a not in mh else b}")
        L = math.hypot(mh[b]["y"] - mh[a]["y"], mh[b]["x"] - mh[a]["x"])
        P.append({"id": i + 1, "from": a, "to": b, "D": float(p["diameter"]), "L": L, "material": p.get("material", ""),
                  "slope": None if p.get("slope_permille") is None else float(p["slope_permille"]) / 1000,
                  "inv_a": None if p.get("invert_from") is None else float(p["invert_from"]),
                  "inv_b": None if p.get("invert_to") is None else float(p["invert_to"]),
                  "n": float(p.get("n", n)), "k_mm": p.get("k_mm", k_mm)})
    out_of = {}
    for p in P:
        if p["from"] in out_of:
            raise CadError(f"Manhole {p['from']} has two outlet pipes; a gravity network must be a tree")
        out_of[p["from"]] = p
    into: dict = {}
    for p in P:
        into.setdefault(p["to"], []).append(p)
    # topological order: upstream first
    order, seen = [], set()

    def visit(p):
        if p["id"] in seen:
            return
        for q in into.get(p["from"], []):
            visit(q)
        seen.add(p["id"])
        order.append(p)

    for p in P:
        visit(p)
    # inverts
    for p in order:
        a, b = mh[p["from"]], mh[p["to"]]
        if p["inv_a"] is None:
            cands = []
            if a["invert"] is not None and not into.get(p["from"]):
                cands.append(a["invert"])
            for q in into.get(p["from"], []):
                cands.append(q["inv_b"] - drop - ((p["D"] - q["D"]) if match == "crown" else 0.0))
            if min_cover is not None:
                cands.append(a["rim"] - float(min_cover) - p["D"])
            if not cands:
                raise CadError(f"Pipe {p['from']}->{p['to']}: give invert_from or min_cover")
            p["inv_a"] = min(cands)
        if p["inv_b"] is None:
            if p["slope"] is not None:
                p["inv_b"] = p["inv_a"] - p["L"] * p["slope"]
            else:
                if min_slope_permille is None:
                    raise CadError(f"Pipe {p['from']}->{p['to']}: give invert_to, slope_permille or min_slope_permille")
                c = [p["inv_a"] - p["L"] * float(min_slope_permille) / 1000]
                if min_cover is not None:
                    c.append(b["rim"] - float(min_cover) - p["D"])
                if b["invert"] is not None and p["to"] not in out_of:
                    c.append(b["invert"])
                p["inv_b"] = min(c)
        p["slope"] = (p["inv_a"] - p["inv_b"]) / p["L"] if p["L"] > 0 else 0.0
    # flows accumulated downstream
    q_in = {k: float(v) / 1000.0 for k, v in (inflows or {}).items()}
    acc = {}
    for p in order:
        acc[p["id"]] = q_in.get(p["from"], 0.0) + sum(acc[q["id"]] for q in into.get(p["from"], []))
    rows, fails = [], []
    for p in sorted(P, key=lambda r: r["id"]):
        a, b = mh[p["from"]], mh[p["to"]]
        S = p["slope"]
        kk = None if p["k_mm"] is None else float(p["k_mm"])
        q_full = flow(p["D"], p["D"], S, method, p["n"], kk) if S > 0 else 0.0
        v_full = velocity(p["D"], p["D"], S, method, p["n"], kk) if S > 0 else 0.0
        row = {"pipe": f"{p['from']}-{p['to']}", "D": p["D"], "material": p["material"], "L": round(p["L"], 2),
               "slope_permille": round(S * 1000, 3), "invert_from": round(p["inv_a"], 3), "invert_to": round(p["inv_b"], 3),
               "cover_from": round(a["rim"] - p["inv_a"] - p["D"], 3), "cover_to": round(b["rim"] - p["inv_b"] - p["D"], 3),
               "Q_full_l_s": round(q_full * 1000, 2), "v_full_m_s": round(v_full, 3)}
        checks = []
        if S <= 0:
            checks.append("nincs esés")
        if min_slope_permille is not None and S * 1000 < float(min_slope_permille) - 1e-9:
            checks.append(f"esés < {min_slope_permille} ‰")
        if min_cover is not None and min(row["cover_from"], row["cover_to"]) < float(min_cover) - 1e-6:
            checks.append(f"takarás < {min_cover} m")
        if acc[p["id"]] > 0:
            Q = acc[p["id"]]
            h = partial_depth(p["D"], Q, S, method, p["n"], kk) if S > 0 else None
            row["Q_l_s"] = round(Q * 1000, 2)
            if h is None:
                checks.append("túlterhelt (Q > kapacitás)")
            else:
                v = velocity(p["D"], h, S, method, p["n"], kk)
                row.update({"h_D": round(h / p["D"], 3), "v_m_s": round(v, 3)})
                if min_velocity is not None and v < float(min_velocity):
                    checks.append(f"v < {min_velocity} m/s")
                if max_velocity is not None and v > float(max_velocity):
                    checks.append(f"v > {max_velocity} m/s")
                if max_fill_ratio is not None and h / p["D"] > float(max_fill_ratio):
                    checks.append(f"h/D > {max_fill_ratio}")
        row["status"] = "OK" if not checks else "HIBA: " + ", ".join(checks)
        if checks:
            fails.append(row["pipe"])
        rows.append(row)
    for k, h in mh.items():
        invs = [p["inv_a"] for p in P if p["from"] == k] + [p["inv_b"] for p in P if p["to"] == k]
        h["invert"] = min(invs) if invs else h["invert"]
    mrows = [{"manhole": k, "rim": round(h["rim"], 3), "invert": None if h["invert"] is None else round(h["invert"], 3),
              "depth": None if h["invert"] is None else round(h["rim"] - h["invert"], 3)} for k, h in mh.items()]
    _store(ctx, "SEWER_" + name, {"kind": kind, "manholes": mh, "manhole_diameter": manhole_diameter,
                                  "pipes": [{k: v for k, v in p.items()} for p in P], "method": method})
    out = {"network": name, "pipes": rows, "manholes": mrows, "failures": fails,
           "outfalls": [k for k in mh if k not in out_of]}
    if draw:
        out["handles"] = _draw_sewer(ctx, name, kind, mh, P, manhole_diameter, text_height, status)
    return out


def _draw_sewer(ctx, name, kind, mh, P, dmh, th0, status):
    m = _m(ctx)
    lname, color = KINDS.get(kind, KINDS["egyeb"])
    layer = f"KOZMU_{lname}_{status.upper()}"
    lw, lt = STATUS.get(status, STATUS["tervezett"])
    ensure_layer(ctx.doc, layer)
    la = ctx.doc.layers.get(layer)
    la.color = color
    la.dxf.lineweight = int(lw * 100)
    tl = layer + "_FELIRAT"
    ensure_layer(ctx.doc, tl)
    msp = ctx.msp
    th = th0 * m
    out = []
    r = dmh / 2
    for h in mh.values():
        out.append(msp.add_circle((h["y"] * m, h["x"] * m), r * m, dxfattribs={"layer": layer}))
        t = msp.add_text(f"{h['name']}  Fsz {h['rim']:.2f}", height=th, dxfattribs={"layer": tl})
        t.set_placement(((h["y"] + r) * m + th * 0.3, (h["x"] + r) * m + th * 0.3))
        out.append(t)
        if h["invert"] is not None:
            t = msp.add_text(f"Ff {h['invert']:.2f}", height=th, dxfattribs={"layer": tl})
            t.set_placement(((h["y"] + r) * m + th * 0.3, (h["x"] + r) * m - th * 1.1))
            out.append(t)
    for p in P:
        a, b = mh[p["from"]], mh[p["to"]]
        dy, dx = b["y"] - a["y"], b["x"] - a["x"]
        L = math.hypot(dy, dx)
        if L <= dmh:
            continue
        uy, ux = dy / L, dx / L
        s = (a["y"] + uy * r, a["x"] + ux * r)
        e = (b["y"] - uy * r, b["x"] - ux * r)
        out.append(msp.add_line((s[0] * m, s[1] * m), (e[0] * m, e[1] * m), dxfattribs={"layer": layer, "linetype": lt}
                                if lt != "Continuous" and ctx.doc.linetypes.has_entry(lt) else {"layer": layer}))
        mid = ((a["y"] + b["y"]) / 2, (a["x"] + b["x"]) / 2)
        ang = math.degrees(math.atan2(dx, dy))
        if ang > 90 or ang < -90:
            ang += 180
        label = f"{p.get('material', '')} DN{int(round(p['D'] * 1000))}  L={p['L']:.1f} m  I={p['slope'] * 1000:.1f}‰".strip()
        t = msp.add_text(label, height=th, rotation=ang, dxfattribs={"layer": tl})
        t.set_placement((mid[0] * m - ux * th * 0.6, mid[1] * m + uy * th * 0.6), align=_al("BOTTOM_CENTER"))
        out.append(t)
        # flow arrow
        tip = (mid[0] + uy * 1.5, mid[1] + ux * 1.5)
        base = (mid[0] - uy * 0.5, mid[1] - ux * 0.5)
        w = 0.35
        out.append(msp.add_solid([(tip[0] * m, tip[1] * m), ((base[0] + ux * w) * m, (base[1] - uy * w) * m),
                                  ((base[0] - ux * w) * m, (base[1] + uy * w) * m)], dxfattribs={"layer": layer}))
    return handles(out)


@op(T, "sewer_profile", mutates=True)
def sewer_profile(ctx: Ctx, name: str, insert, path: list | None = None, start: str | None = None,
                  v_exag: float = 10.0, surface: str | None = None, datum: float | None = None,
                  text_height: float = 2.0, grid_elev: float = 1.0):
    """Sewer long section (csatorna hossz-szelvény) along manholes: path = [manhole names in flow order] or start = upstream manhole (followed to the outfall). Draws terrain (from a surface, else the rim levels), pipe invert and crown, manhole shafts, elevation grid and the data band: manhole, distance, rim level, invert, depth, pipe (DN, material, slope ‰, length). Horizontal true scale, vertical exaggerated v_exag times."""
    net = _load(ctx, "SEWER_" + name)
    if not net:
        raise CadError(f"No sewer network '{name}' (utility.sewer)")
    mh = net["manholes"]
    pipes = {(p["from"], p["to"]): p for p in net["pipes"]}
    nxt = {p["from"]: p["to"] for p in net["pipes"]}
    if path is None:
        if start is None:
            ups = [k for k in mh if k not in {p["to"] for p in net["pipes"]}]
            if not ups:
                raise CadError("Give path or start")
            start = ups[0]
        path = [start]
        while path[-1] in nxt and len(path) <= len(mh):
            path.append(nxt[path[-1]])
    path = [str(k) for k in path]
    segs = []
    for a, b in zip(path, path[1:]):
        if (a, b) not in pipes:
            raise CadError(f"No pipe {a} -> {b} in '{name}'")
        segs.append(pipes[(a, b)])
    if not segs:
        raise CadError("The path needs at least two manholes")
    m = _m(ctx)
    ox, oy = insert[0] / m, insert[1] / m
    st = [0.0]
    for p in segs:
        st.append(st[-1] + p["L"])
    # terrain
    terr = []
    if surface:
        for i, p in enumerate(segs):
            a, b = mh[p["from"]], mh[p["to"]]
            k = max(2, int(p["L"] / 2))
            for j in range(k + (1 if i == len(segs) - 1 else 0)):
                t = j / k
                z = _surface_z(ctx, surface, a["y"] + (b["y"] - a["y"]) * t, a["x"] + (b["x"] - a["x"]) * t)
                if z is not None:
                    terr.append((st[i] + p["L"] * t, z))
    if len(terr) < 2:
        terr = [(s, mh[k]["rim"]) for s, k in zip(st, path)]
    zs = [z for _, z in terr] + [p["inv_a"] for p in segs] + [p["inv_b"] for p in segs]
    if datum is None:
        datum = math.floor(min(zs) / grid_elev) * grid_elev - grid_elev
    top = math.ceil(max(zs) / grid_elev) * grid_elev + grid_elev
    X = lambda s: (ox + s) * m
    Y = lambda z: (oy + (z - datum) * v_exag) * m
    th = text_height * m
    lname, color = KINDS.get(net.get("kind", "egyeb"), KINDS["egyeb"])
    from .ops_road import _attribs

    a_g = _attribs(ctx, "CSATORNA_HOSSZ_RACS", color=8)
    a_t = _attribs(ctx, "CSATORNA_HOSSZ_TEREP", color=3)
    a_p = _attribs(ctx, "CSATORNA_HOSSZ_CSO", color=color)
    a_x = _attribs(ctx, "CSATORNA_HOSSZ_FELIRAT", color=7)
    lay = ctx.msp
    out = []
    z = datum
    while z <= top + 1e-9:
        out.append(lay.add_line((X(0), Y(z)), (X(st[-1]), Y(z)), dxfattribs=a_g))
        t = lay.add_text(f"{z:.2f}", height=th * 0.8, dxfattribs=a_x)
        t.set_placement((X(0) - th, Y(z)), align=_al("MIDDLE_RIGHT"))
        out.append(t)
        z += grid_elev
    out.append(lay.add_lwpolyline([(X(s), Y(z)) for s, z in terr], dxfattribs=a_t))
    inv_pts, crown_pts = [], []
    for i, p in enumerate(segs):
        inv_pts += [(X(st[i]), Y(p["inv_a"])), (X(st[i + 1]), Y(p["inv_b"]))]
        crown_pts += [(X(st[i]), Y(p["inv_a"] + p["D"])), (X(st[i + 1]), Y(p["inv_b"] + p["D"]))]
    out.append(lay.add_lwpolyline(inv_pts, dxfattribs=a_p))
    out.append(lay.add_lwpolyline(crown_pts, dxfattribs=a_p))
    half = net.get("manhole_diameter", 1.0) / 2
    for s, k in zip(st, path):
        h = mh[k]
        bot = min([p["inv_b"] for p in segs if p["to"] == k] + [p["inv_a"] for p in segs if p["from"] == k])
        out.append(lay.add_lwpolyline([(X(s - half), Y(bot - 0.1)), (X(s + half), Y(bot - 0.1)),
                                       (X(s + half), Y(h["rim"])), (X(s - half), Y(h["rim"]))], close=True,
                                      dxfattribs=a_p))
        t = lay.add_text(k, height=th, dxfattribs=a_x)
        t.set_placement((X(s), Y(h["rim"]) + th), align=_al("BOTTOM_CENTER"))
        out.append(t)
    for i, p in enumerate(segs):
        mid = (st[i] + st[i + 1]) / 2
        zc = (p["inv_a"] + p["inv_b"]) / 2 + p["D"]
        ang = math.degrees(math.atan2((p["inv_b"] - p["inv_a"]) * v_exag, p["L"]))
        t = lay.add_text(f"DN{int(round(p['D'] * 1000))} {p.get('material', '')} I={p['slope'] * 1000:.1f}‰", height=th * 0.8,
                         rotation=ang, dxfattribs=a_p)
        t.set_placement((X(mid), Y(zc) + th * 0.5), align=_al("BOTTOM_CENTER"))
        out.append(t)
    rows = ["Akna", "Távolság (m)", "Fedlapszint", "Folyásfenék", "Mélység (m)", "Cső"]
    rh = th * 3
    band_top = Y(datum)
    for i in range(len(rows) + 1):
        out.append(lay.add_line((X(0) - th * 14, band_top - i * rh), (X(st[-1]), band_top - i * rh), dxfattribs=a_g))
    for i, r in enumerate(rows):
        t = lay.add_text(r, height=th, dxfattribs=a_x)
        t.set_placement((X(0) - th * 13.5, band_top - (i + 0.5) * rh), align=_al("MIDDLE_LEFT"))
        out.append(t)
    band = []
    for j, (s, k) in enumerate(zip(st, path)):
        h = mh[k]
        invs = [p["inv_b"] for p in segs if p["to"] == k] + [p["inv_a"] for p in segs if p["from"] == k]
        inv_txt = "/".join(f"{v:.2f}" for v in invs)
        vals = [k, f"{s:.2f}", f"{h['rim']:.2f}", inv_txt, f"{h['rim'] - min(invs):.2f}"]
        for i, v in enumerate(vals):
            t = lay.add_text(v, height=th * 0.8, rotation=90, dxfattribs=a_x)
            t.set_placement((X(s), band_top - (i + 0.5) * rh), align=_al("MIDDLE_CENTER"))
            out.append(t)
        out.append(lay.add_line((X(s), band_top), (X(s), band_top - 5 * rh), dxfattribs=a_g))
        band.append({"manhole": k, "station": round(s, 2), "rim": round(h["rim"], 3), "inverts": [round(v, 3) for v in invs]})
    for i, p in enumerate(segs):
        t = lay.add_text(f"DN{int(round(p['D'] * 1000))} {p.get('material', '')} {p['slope'] * 1000:.1f}‰ L={p['L']:.1f}",
                         height=th * 0.8, dxfattribs=a_x)
        t.set_placement((X((st[i] + st[i + 1]) / 2), band_top - 5.5 * rh), align=_al("MIDDLE_CENTER"))
        out.append(t)
    return {"path": path, "length": round(st[-1], 2), "datum": datum, "band": band, "handles": handles(out)}


# ---------------------------------------------------------------------------
# water network (global gradient algorithm)
# ---------------------------------------------------------------------------


def solve_gga(Aj, Af, H0, dem, loss, Q0, tol_q: float = 1e-9, tol_h: float = 1e-7, it_max: int = 200):
    """Global gradient (Todini–Pilati) solution of a pipe network: pipe i from a to b with A[i,a] = -1,
    A[i,b] = +1; loss(Q) returns (signed potential drop, derivative). Returns flows, node potentials, iterations."""
    Q = np.array(Q0, dtype=float)
    H = np.full(Aj.shape[1], float(np.max(H0)))
    for it in range(1, it_max + 1):
        h, g = loss(Q)
        F1 = h + Aj @ H + Af @ H0
        F2 = Aj.T @ Q - dem
        Gi = 1.0 / g
        Mx = Aj.T @ (Gi[:, None] * Aj)
        try:
            dH = np.linalg.solve(Mx, F2 - Aj.T @ (Gi * F1))
        except np.linalg.LinAlgError as exc:
            raise CadError("Network is not connected to a source (singular system)") from exc
        dQ = -Gi * (F1 + Aj @ dH)
        Q = Q + dQ
        H = H + dH
        if np.max(np.abs(dQ)) < tol_q and np.max(np.abs(dH)) < tol_h:
            return Q, H, it
    raise CadError("Hydraulic solution did not converge")


def _incidence(pipes, jidx: dict, fidx: dict):
    Aj = np.zeros((len(pipes), len(jidx)))
    Af = np.zeros((len(pipes), len(fidx)))
    for i, p in enumerate(pipes):
        for k, sgn in ((str(p["from"]), -1.0), (str(p["to"]), 1.0)):
            if k in jidx:
                Aj[i, jidx[k]] = sgn
            elif k in fidx:
                Af[i, fidx[k]] = sgn
            else:
                raise CadError(f"Pipe {i}: unknown node {k}")
    return Aj, Af


def swamee_jain(Re, rel_rough):
    """Darcy friction factor (laminar 64/Re below Re 2000)."""
    Re = np.maximum(Re, 1e-9)
    f = 0.25 / np.log10(rel_rough / 3.7 + 5.74 / Re ** 0.9) ** 2
    return np.where(Re < 2000, 64 / Re, f)


@op(T, "water_network", mutates=True)
def water_network(ctx: Ctx, name: str, nodes: list, pipes: list, sources: list, method: str = "hazen",
                  min_pressure: float | None = None, max_pressure: float | None = None,
                  max_velocity: float | None = None, draw: bool = True, text_height: float = 0.5,
                  status: str = "tervezett"):
    """Pressurised water network (vízhálózat) hydraulics by the global gradient method (as EPANET): nodes = [{"name","point":[Y,X],"elevation","demand" (l/s)}], sources = [{"name","point","head"}] (reservoir / fixed hydraulic grade, m), pipes = [{"from","to","diameter" (m, inner), optional "length" (default plan length), "C" (Hazen–Williams) or "k_mm" (Darcy–Weisbach with Swamee–Jain), optional "minor_loss" K}]. Loops are allowed. Returns flows, velocities, head losses and node heads/pressures (m and bar), checked against min/max pressure and max velocity when given, and labels them in the drawing."""
    if method not in ("hazen", "darcy"):
        raise CadError("method: hazen or darcy")
    junc = [str(n_["name"]) for n_ in nodes]
    fixed = [str(s["name"]) for s in sources]
    if not fixed:
        raise CadError("Give at least one source (fixed head)")
    allpos = {str(n_["name"]): (float(n_["point"][0]), float(n_["point"][1])) for n_ in list(nodes) + list(sources)}
    jidx = {k: i for i, k in enumerate(junc)}
    fidx = {k: i for i, k in enumerate(fixed)}
    elev = np.array([float(n_.get("elevation", 0.0)) for n_ in nodes])
    dem = np.array([float(n_.get("demand", 0.0)) / 1000.0 for n_ in nodes])
    H0 = np.array([float(s["head"]) for s in sources])
    npipe = len(pipes)
    Aj = np.zeros((npipe, len(junc)))
    Af = np.zeros((npipe, len(fixed)))
    L, D, rough, Km = [], [], [], []
    for i, p in enumerate(pipes):
        a, b = str(p["from"]), str(p["to"])
        for k, sgn in ((a, -1.0), (b, 1.0)):
            if k in jidx:
                Aj[i, jidx[k]] = sgn
            elif k in fidx:
                Af[i, fidx[k]] = sgn
            else:
                raise CadError(f"Pipe {i}: unknown node {k}")
        length = p.get("length")
        L.append(float(length) if length is not None else math.dist(allpos[a], allpos[b]))
        D.append(float(p["diameter"]))
        if method == "hazen":
            if p.get("C") is None:
                raise CadError(f"Pipe {a}-{b}: give C (Hazen–Williams)")
            rough.append(float(p["C"]))
        else:
            if p.get("k_mm") is None:
                raise CadError(f"Pipe {a}-{b}: give k_mm (Darcy–Weisbach)")
            rough.append(float(p["k_mm"]) / 1000.0)
        Km.append(float(p.get("minor_loss", 0.0)))
    L, D, rough, Km = map(np.array, (L, D, rough, Km))
    area = math.pi * D ** 2 / 4
    mcoef = Km / (2 * G * area ** 2)

    def loss(Q):
        aq = np.abs(Q)
        if method == "hazen":
            r = 10.67 * L / (rough ** 1.852 * D ** 4.87)
            h = r * aq ** 1.852
            dh = 1.852 * r * np.maximum(aq, 1e-6) ** 0.852
        else:
            v = np.maximum(aq / area, 1e-6)
            Re = v * D / NU
            f = 0.25 / np.log10(rough / (3.7 * D) + 5.74 / Re ** 0.9) ** 2
            f = np.where(Re < 2000, 64 / Re, f)
            h = f * L / D * v ** 2 / (2 * G) * (aq > 0)
            dh = 2 * f * L / D * v / (2 * G) / area
        h = h + mcoef * aq ** 2
        dh = dh + 2 * mcoef * aq
        return np.sign(Q) * h, np.maximum(dh, 1e-8)

    Q, H, it = solve_gga(Aj, Af, H0, dem, loss, area * 0.5)
    h, _g = loss(Q)
    press = H - elev
    prow, nrow, fails = [], [], []
    for i, p in enumerate(pipes):
        v = abs(Q[i]) / area[i]
        st = "OK"
        if max_velocity is not None and v > float(max_velocity):
            st = f"HIBA: v > {max_velocity} m/s"
            fails.append(f"{p['from']}-{p['to']}")
        prow.append({"pipe": f"{p['from']}-{p['to']}", "D": float(D[i]), "L": round(float(L[i]), 2),
                     "Q_l_s": round(float(Q[i]) * 1000, 3), "v_m_s": round(float(v), 3),
                     "headloss_m": round(float(abs(h[i])), 4),
                     "unit_headloss_m_km": round(float(abs(h[i]) / L[i] * 1000), 3) if L[i] > 0 else None, "status": st})
    for k, i in jidx.items():
        st = "OK"
        if min_pressure is not None and press[i] < float(min_pressure):
            st = f"HIBA: p < {min_pressure} m"
        if max_pressure is not None and press[i] > float(max_pressure):
            st = f"HIBA: p > {max_pressure} m"
        if st != "OK":
            fails.append(k)
        nrow.append({"node": k, "elevation": float(elev[i]), "demand_l_s": round(float(dem[i]) * 1000, 3),
                     "head": round(float(H[i]), 3), "pressure_m": round(float(press[i]), 3),
                     "pressure_bar": round(float(press[i]) * 0.0980665, 3), "status": st})
    _store(ctx, "WATER_" + name, {"nodes": nodes, "pipes": pipes, "sources": sources, "method": method})
    out = {"network": name, "iterations": it, "pipes": prow, "nodes": nrow, "failures": fails,
           "continuity_error_l_s": round(float(np.max(np.abs(Aj.T @ Q - dem))) * 1000, 6)}
    if draw:
        m = _m(ctx)
        layer = f"KOZMU_VIZ_{status.upper()}"
        ensure_layer(ctx.doc, layer)
        ctx.doc.layers.get(layer).color = 5
        tl = layer + "_FELIRAT"
        ensure_layer(ctx.doc, tl)
        th = text_height * m
        hs = []
        for i, p in enumerate(pipes):
            a, b = allpos[str(p["from"])], allpos[str(p["to"])]
            hs.append(ctx.msp.add_line((a[0] * m, a[1] * m), (b[0] * m, b[1] * m), dxfattribs={"layer": layer}))
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            if ang > 90 or ang < -90:
                ang += 180
            t = ctx.msp.add_text(f"D{int(round(D[i] * 1000))} Q={prow[i]['Q_l_s']:.2f} l/s v={prow[i]['v_m_s']:.2f}",
                                 height=th, rotation=ang, dxfattribs={"layer": tl})
            t.set_placement((((a[0] + b[0]) / 2) * m, ((a[1] + b[1]) / 2) * m + th * 0.4), align=_al("BOTTOM_CENTER"))
            hs.append(t)
        for r in nrow:
            y, x = allpos[r["node"]]
            hs.append(ctx.msp.add_circle((y * m, x * m), 0.3 * m, dxfattribs={"layer": layer}))
            t = ctx.msp.add_text(f"{r['node']} p={r['pressure_m']:.1f} m", height=th, dxfattribs={"layer": tl})
            t.set_placement((y * m + th * 0.6, x * m + th * 0.3))
            hs.append(t)
        for s in sources:
            y, x = allpos[str(s["name"])]
            hs.append(ctx.msp.add_lwpolyline([((y - 0.6) * m, (x - 0.6) * m), ((y + 0.6) * m, (x - 0.6) * m),
                                              ((y + 0.6) * m, (x + 0.6) * m), ((y - 0.6) * m, (x + 0.6) * m)],
                                             close=True, dxfattribs={"layer": layer}))
            t = ctx.msp.add_text(f"{s['name']} H={float(s['head']):.2f}", height=th, dxfattribs={"layer": tl})
            t.set_placement((y * m + th, x * m + th))
            hs.append(t)
        out["handles"] = handles(hs)
    return out


# ---------------------------------------------------------------------------
# gas and district heating networks
# ---------------------------------------------------------------------------

P_ATM = 101325.0
T_N = 273.15


def _draw_net(ctx: Ctx, layer: str, color: int, allpos: dict, pipes: list, pipe_labels: list, node_labels: dict,
              sources: list, text_height: float) -> list[str]:
    m = _m(ctx)
    ensure_layer(ctx.doc, layer)
    ctx.doc.layers.get(layer).color = color
    tl = layer + "_FELIRAT"
    ensure_layer(ctx.doc, tl)
    th = text_height * m
    hs = []
    for p, lab in zip(pipes, pipe_labels):
        a, b = allpos[str(p["from"])], allpos[str(p["to"])]
        hs.append(ctx.msp.add_line((a[0] * m, a[1] * m), (b[0] * m, b[1] * m), dxfattribs={"layer": layer}))
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if ang > 90 or ang < -90:
            ang += 180
        t = ctx.msp.add_text(lab, height=th, rotation=ang, dxfattribs={"layer": tl})
        t.set_placement((((a[0] + b[0]) / 2) * m, ((a[1] + b[1]) / 2) * m + th * 0.4), align=_al("BOTTOM_CENTER"))
        hs.append(t)
    for k, lab in node_labels.items():
        y, x = allpos[k]
        hs.append(ctx.msp.add_circle((y * m, x * m), 0.3 * m, dxfattribs={"layer": layer}))
        t = ctx.msp.add_text(lab, height=th, dxfattribs={"layer": tl})
        t.set_placement((y * m + th * 0.6, x * m + th * 0.3))
        hs.append(t)
    for s in sources:
        y, x = allpos[str(s)]
        hs.append(ctx.msp.add_lwpolyline([((y - 0.6) * m, (x - 0.6) * m), ((y + 0.6) * m, (x - 0.6) * m),
                                          ((y + 0.6) * m, (x + 0.6) * m), ((y - 0.6) * m, (x + 0.6) * m)],
                                         close=True, dxfattribs={"layer": layer}))
    return handles(hs)


def _net_geometry(nodes, sources, pipes, k_mm):
    junc = [str(n_["name"]) for n_ in nodes]
    fixed = [str(s_["name"]) for s_ in sources]
    if not fixed:
        raise CadError("Give at least one source")
    allpos = {str(n_["name"]): (float(n_["point"][0]), float(n_["point"][1])) for n_ in list(nodes) + list(sources)}
    jidx = {k: i for i, k in enumerate(junc)}
    fidx = {k: i for i, k in enumerate(fixed)}
    Aj, Af = _incidence(pipes, jidx, fidx)
    L = np.array([float(p["length"]) if p.get("length") is not None else math.dist(allpos[str(p["from"])], allpos[str(p["to"])])
                  for p in pipes])
    D = np.array([float(p["diameter"]) for p in pipes])
    kk = []
    for p in pipes:
        k = p.get("k_mm", k_mm)
        if k is None:
            raise CadError(f"Pipe {p['from']}-{p['to']}: give k_mm (wall roughness, mm) for the pipe or the network")
        kk.append(float(k) / 1000.0)
    return junc, fixed, allpos, jidx, fidx, Aj, Af, L, D, np.array(kk)


@op(T, "gas_network", mutates=True)
def gas_network(ctx: Ctx, name: str, nodes: list, pipes: list, sources: list, pressure_level: str = "low",
                k_mm: float | None = None, density_n: float = 0.73, viscosity: float = 1.1e-5,
                temperature_c: float = 10.0, z_factor: float = 1.0, min_pressure: float | None = None,
                max_velocity: float | None = None, draw: bool = True, text_height: float = 0.5,
                status: str = "tervezett"):
    """Gas network (gázhálózat) pressure drop, loops allowed: nodes = [{"name","point","demand" (m³/h at normal conditions), optional "elevation"}], sources = [{"name","point","pressure"}] (pressure_level 'low': mbar gauge, Darcy–Weisbach with the gas density and the buoyancy of gas in height; 'medium': bar gauge, isothermal p₁² − p₂² equation), pipes = [{"from","to","diameter" (inner, m), optional "length", "k_mm"}] (k_mm for all pipes as a parameter, too). Gas properties default to typical natural gas (density 0.73 kg/m³ at 0 °C, 1.01325 bar, viscosity 1.1e-5 Pa·s), change them for the actual gas. Returns node pressures, flows, actual velocities and pressure drops, checked against min_pressure (same unit as the sources) and max_velocity when given."""
    if pressure_level not in ("low", "medium"):
        raise CadError("pressure_level: low (mbar) or medium (bar)")
    junc, fixed, allpos, jidx, fidx, Aj, Af, L, D, kk = _net_geometry(nodes, sources, pipes, k_mm)
    T = float(temperature_c) + T_N
    area = math.pi * D ** 2 / 4
    dem = np.array([float(n_.get("demand", 0.0)) / 3600.0 for n_ in nodes])  # m³/s normal
    unit = 100.0 if pressure_level == "low" else 1e5  # mbar or bar -> Pa
    p_src = np.array([float(s_["pressure"]) * unit for s_ in sources])
    mu = float(viscosity)
    rho_n = float(density_n)
    if pressure_level == "low":
        p_abs = P_ATM + float(np.max(p_src))
        rho = rho_n * (p_abs / P_ATM) * (T_N / T) / float(z_factor)
        rho_air = 1.293 * (p_abs / P_ATM) * (T_N / T)
        z = {str(n_["name"]): float(n_.get("elevation", 0.0)) for n_ in list(nodes) + list(sources)}
        lift = np.array([-(rho_air - rho) * G * (z[str(p["to"])] - z[str(p["from"])]) for p in pipes])
        conv = (P_ATM / p_abs) * (T / T_N) * float(z_factor)  # normal -> actual volume

        def loss(Q):
            v = np.abs(Q) * conv / area
            f = swamee_jain(np.maximum(v, 1e-6) * D * rho / mu, kk / D)
            h = f * L / D * rho * v ** 2 / 2
            g = np.maximum(2 * h / np.maximum(np.abs(Q), 1e-9), 1e-3)
            return np.sign(Q) * h + lift, g

        Q, P, it = solve_gga(Aj, Af, p_src, dem, loss, area * 2.0 / conv, tol_q=1e-10, tol_h=1e-3)
        node_p = P / unit
        vel = np.abs(Q) * conv / area
        drop = np.abs(loss(Q)[0] - lift) / unit
    else:
        p2_src = (p_src + P_ATM) ** 2
        const = 16 * rho_n * P_ATM * T * float(z_factor) / (math.pi ** 2 * T_N)

        def loss(Q):
            Re = 4 * rho_n * np.abs(Q) / (math.pi * D * mu)
            f = swamee_jain(np.maximum(Re, 1.0), kk / D)
            K = const * f * L / D ** 5
            h = K * Q * np.abs(Q)
            return h, np.maximum(2 * K * np.abs(Q), 1.0)

        Q, P2, it = solve_gga(Aj, Af, p2_src, dem, loss, area * 5.0, tol_q=1e-10, tol_h=1.0)
        p_node_abs = np.sqrt(np.maximum(P2, 0.0))
        node_p = (p_node_abs - P_ATM) / unit
        allp = {**{k: p_node_abs[i] for k, i in jidx.items()}, **{k: p_src[i] + P_ATM for k, i in fidx.items()}}
        p_mean = np.array([(allp[str(p["from"])] + allp[str(p["to"])]) / 2 for p in pipes])
        vel = np.abs(Q) * (P_ATM / p_mean) * (T / T_N) * float(z_factor) / area
        drop = np.array([abs(allp[str(p["from"])] - allp[str(p["to"])]) for p in pipes]) / unit
    pu = "mbar" if pressure_level == "low" else "bar"
    prow, nrow, fails = [], [], []
    for i, p in enumerate(pipes):
        st = "OK"
        if max_velocity is not None and vel[i] > float(max_velocity):
            st = f"HIBA: v > {max_velocity} m/s"
            fails.append(f"{p['from']}-{p['to']}")
        prow.append({"pipe": f"{p['from']}-{p['to']}", "D": float(D[i]), "L": round(float(L[i]), 2),
                     "Q_m3_h": round(float(Q[i]) * 3600, 3), "v_m_s": round(float(vel[i]), 3),
                     f"drop_{pu}": round(float(drop[i]), 4), "status": st})
    for k, i in jidx.items():
        st = "OK"
        if min_pressure is not None and node_p[i] < float(min_pressure):
            st = f"HIBA: p < {min_pressure} {pu}"
            fails.append(k)
        nrow.append({"node": k, "demand_m3_h": round(float(dem[i]) * 3600, 3), f"pressure_{pu}": round(float(node_p[i]), 4),
                     "status": st})
    _store(ctx, "GAS_" + name, {"nodes": nodes, "pipes": pipes, "sources": sources, "level": pressure_level})
    out = {"network": name, "pressure_level": pressure_level, "unit": pu, "iterations": it, "pipes": prow, "nodes": nrow,
           "failures": fails, "continuity_error_m3_h": round(float(np.max(np.abs(Aj.T @ Q - dem))) * 3600, 8),
           "gas": {"density_n": rho_n, "viscosity": mu, "temperature_c": temperature_c, "z": z_factor}}
    if draw:
        out["handles"] = _draw_net(ctx, f"KOZMU_GAZ_{status.upper()}", 2, allpos, pipes,
                                   [f"D{int(round(r['D'] * 1000))} Q={r['Q_m3_h']:.1f} m³/h" for r in prow],
                                   {r["node"]: f"{r['node']} p={r[f'pressure_{pu}']:.2f} {pu}" for r in nrow},
                                   [s_["name"] for s_ in sources], text_height)
    return out


def water_props(t_c: float) -> tuple[float, float]:
    """Density (kg/m³) and dynamic viscosity (Pa·s) of water at t °C (0–150 °C, empirical fits)."""
    rho = 1000.0 * (1 - (t_c + 288.9414) / (508929.2 * (t_c + 68.12963)) * (t_c - 3.9863) ** 2)
    mu = 2.414e-5 * 10 ** (247.8 / (t_c + 133.15))
    return rho, mu


@op(T, "heat_network", mutates=True)
def heat_network(ctx: Ctx, name: str, plant: dict, consumers: list, pipes: list, supply_temp_c: float,
                 return_temp_c: float, k_mm: float | None = None, nodes: list | None = None,
                 consumer_dp_kpa: float | None = None, max_velocity: float | None = None,
                 max_specific_loss_pa_m: float | None = None, cp: float = 4.19, draw: bool = True,
                 text_height: float = 0.5, status: str = "tervezett"):
    """District heating network (távhőhálózat), two-pipe supply/return: plant = {"name","point"}, consumers = [{"name","point","load_kw"}], optional plain junction nodes = [{"name","point"}], pipes = [{"from","to","diameter" (inner, m), optional "length", "k_mm"}] along the supply route (the return pipe is the same). Flows from the heat loads and ΔT (ṁ = P / (c·ΔT)), Darcy–Weisbach with water properties at the mean temperature; loops allowed. Returns flows, velocities, specific pressure loss (Pa/m), the supply+return loss to each consumer and the differential pressure needed at the plant (plus consumer_dp_kpa required at the substation, if given), checked against max_velocity / max_specific_loss_pa_m when given."""
    dT = float(supply_temp_c) - float(return_temp_c)
    if dT <= 0:
        raise CadError("supply_temp_c must be above return_temp_c")
    rho, mu = water_props((float(supply_temp_c) + float(return_temp_c)) / 2)
    nn = [{"name": c["name"], "point": c["point"], "demand": float(c["load_kw"]) / (float(cp) * dT) / rho}
          for c in consumers] + [{"name": n_["name"], "point": n_["point"], "demand": 0.0} for n_ in (nodes or [])]
    src = [{"name": plant["name"], "point": plant["point"]}]
    junc, fixed, allpos, jidx, fidx, Aj, Af, L, D, kk = _net_geometry(nn, src, pipes, k_mm)
    area = math.pi * D ** 2 / 4
    dem = np.array([n_["demand"] for n_ in nn])

    def loss(Q):
        v = np.abs(Q) / area
        f = swamee_jain(np.maximum(v, 1e-6) * D * rho / mu, kk / D)
        h = f * L / D * rho * v ** 2 / 2
        return np.sign(Q) * h, np.maximum(2 * h / np.maximum(np.abs(Q), 1e-9), 1e-3)

    Q, P, it = solve_gga(Aj, Af, np.array([0.0]), dem, loss, area * 1.0, tol_q=1e-10, tol_h=1e-3)
    h, _g = loss(Q)
    prow, crow, fails = [], [], []
    for i, p in enumerate(pipes):
        v = abs(Q[i]) / area[i]
        R = abs(h[i]) / L[i] if L[i] > 0 else 0.0
        st = []
        if max_velocity is not None and v > float(max_velocity):
            st.append(f"v > {max_velocity} m/s")
        if max_specific_loss_pa_m is not None and R > float(max_specific_loss_pa_m):
            st.append(f"R > {max_specific_loss_pa_m} Pa/m")
        if st:
            fails.append(f"{p['from']}-{p['to']}")
        prow.append({"pipe": f"{p['from']}-{p['to']}", "D": float(D[i]), "L": round(float(L[i]), 2),
                     "m_kg_s": round(float(Q[i]) * rho, 4), "Q_m3_h": round(float(Q[i]) * 3600, 3),
                     "v_m_s": round(float(v), 3), "R_Pa_m": round(float(R), 2),
                     "status": "OK" if not st else "HIBA: " + ", ".join(st)})
    req = float(consumer_dp_kpa or 0.0) * 1000
    need = 0.0
    for c in consumers:
        i = jidx[str(c["name"])]
        loop = -2 * P[i]  # supply + return
        need = max(need, loop + req)
        crow.append({"consumer": c["name"], "load_kw": float(c["load_kw"]),
                     "flow_m3_h": round(float(dem[i]) * 3600, 3), "network_loss_kpa": round(float(loop) / 1000, 3)})
    _store(ctx, "HEAT_" + name, {"plant": plant, "consumers": consumers, "nodes": nodes or [], "pipes": pipes,
                                 "supply_temp_c": supply_temp_c, "return_temp_c": return_temp_c})
    out = {"network": name, "iterations": it, "water": {"density": round(rho, 2), "viscosity": mu, "dT": dT},
           "total_load_kw": sum(float(c["load_kw"]) for c in consumers),
           "total_flow_m3_h": round(float(dem.sum()) * 3600, 3), "pipes": prow, "consumers": crow,
           "plant_differential_kpa": round(need / 1000, 3), "pump_head_m": round(need / (rho * G), 3),
           "failures": fails}
    if consumer_dp_kpa is None:
        out["note"] = "A hőközpontban szükséges nyomáskülönbséget (consumer_dp_kpa) nem adtad meg: a hálózati veszteség szerepel."
    if draw:
        out["handles"] = _draw_net(ctx, f"KOZMU_TAVHO_{status.upper()}", 200, allpos, pipes,
                                   [f"DN{int(round(r['D'] * 1000))} {r['Q_m3_h']:.1f} m³/h R={r['R_Pa_m']:.0f} Pa/m" for r in prow],
                                   {c["consumer"]: f"{c['consumer']} {c['load_kw']:.0f} kW" for c in crow},
                                   [plant["name"]], text_height)
    return out


# ---------------------------------------------------------------------------
# utility lines, clearance check, cross sections
# ---------------------------------------------------------------------------


def _lines(ctx: Ctx) -> dict:
    reg = _load(ctx, "UTILITY_LINES") or {}
    return {h: v for h, v in reg.items() if ctx.doc.entitydb.get(h) is not None and ctx.doc.entitydb[h].is_alive}


@op(T, "line", mutates=True)
def utility_line(ctx: Ctx, points: list, kind: str, status: str = "meglevo", size: float = 0.1,
                 depth: float | None = None, elevations: list | None = None, surface: str | None = None,
                 material: str = "", owner: str = "", label: bool = True, label_every: float = 50.0,
                 text_height: float = 0.5, name: str | None = None):
    """Utility line (közművezeték) in plan: points [[Y,X],...]; kind = viz, szennyviz, csapadek, egyesitett, gaz, villany, villany_kozep, villany_kis, kozvilagitas, tavkozles, tavho, olaj, egyeb (layer KOZMU_<KIND>_<STATUS> with the usual colours, changeable); status = meglevo / tervezett / megszuntetendo; size = outer diameter or width (m); height of the axis from elevations [per vertex] or from depth (cover to the top) below a terrain surface. Labels like 'G KPE D110 1,0 m' along the line. Remembered for utility.clearance_check and utility.cross_section."""
    if kind not in KINDS:
        raise CadError(f"kind must be one of {list(KINDS)}")
    if status not in STATUS:
        raise CadError(f"status must be one of {list(STATUS)}")
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 2:
        raise CadError("Give at least two points")
    if elevations is not None:
        if len(elevations) != len(pts):
            raise CadError("Give one elevation (axis) per vertex")
        zs = [float(z) for z in elevations]
    elif depth is not None and surface:
        zs = []
        for y, x in pts:
            g = _surface_z(ctx, surface, y, x)
            if g is None:
                raise CadError(f"Point {y:.2f},{x:.2f} is outside surface {surface}")
            zs.append(g - float(depth) - float(size) / 2)
    else:
        zs = None
    m = _m(ctx)
    lname, color = KINDS[kind]
    layer = f"KOZMU_{lname}_{status.upper()}"
    lw, lt = STATUS[status]
    ensure_layer(ctx.doc, layer)
    la = ctx.doc.layers.get(layer)
    la.color = color
    la.dxf.lineweight = int(lw * 100)
    if lt != "Continuous":
        from .core import ensure_linetype

        ensure_linetype(ctx.doc, lt)
        la.dxf.linetype = lt
    pl = ctx.msp.add_lwpolyline([(y * m, x * m) for y, x in pts], dxfattribs={"layer": layer})
    reg = _load(ctx, "UTILITY_LINES") or {}
    reg[pl.dxf.handle] = {"kind": kind, "status": status, "size": float(size), "z": zs, "depth": depth,
                          "material": material, "owner": owner, "name": name}
    _store(ctx, "UTILITY_LINES", reg)
    out = [pl]
    if label:
        short = {"viz": "V", "szennyviz": "Sz", "csapadek": "Cs", "egyesitett": "E", "gaz": "G", "villany": "EL",
                 "villany_kozep": "EKF", "villany_kis": "EKI", "kozvilagitas": "KÖZV", "tavkozles": "HÍR", "tavho": "TH",
                 "olaj": "O", "egyeb": "K"}[kind]
        txt = " ".join(x for x in (short, material, f"D{int(round(size * 1000))}" if size else "",
                                   f"{depth:.2f} m".replace(".", ",") if depth is not None else "") if x)
        th = text_height * m
        acc = 0.0
        nxt = label_every / 2
        for (y0, x0), (y1, x1) in zip(pts, pts[1:]):
            seg = math.hypot(y1 - y0, x1 - x0)
            while seg > 0 and nxt <= acc + seg:
                t = (nxt - acc) / seg
                ang = math.degrees(math.atan2(x1 - x0, y1 - y0))
                if ang > 90 or ang < -90:
                    ang += 180
                e = ctx.msp.add_text(txt, height=th, rotation=ang, dxfattribs={"layer": layer})
                e.set_placement(((y0 + (y1 - y0) * t) * m, (x0 + (x1 - x0) * t) * m + th * 0.3), align=_al("BOTTOM_CENTER"))
                out.append(e)
                nxt += label_every
            acc += seg
    return {"handle": pl.dxf.handle, "layer": layer, "handles": handles(out), "axis_elevations": zs}


def _z_along(meta: dict, line, d: float) -> float | None:
    """Axis elevation at chainage d of a utility line (linear between vertices)."""
    zs = meta.get("z")
    if not zs:
        return None
    coords = list(line.coords)
    acc = 0.0
    for i in range(len(coords) - 1):
        seg = math.dist(coords[i], coords[i + 1])
        if d <= acc + seg + 1e-9:
            t = 0.0 if seg == 0 else (d - acc) / seg
            return zs[i] + (zs[i + 1] - zs[i]) * min(max(t, 0.0), 1.0)
        acc += seg
    return zs[-1]


@op(T, "clearance_rules_template")
def clearance_rules_template(ctx: Ctx, path: str, kinds: list | None = None):
    """Write an empty clearance rules JSON (horizontal and vertical clear distance in m per pair of utility kinds, plus a default) to fill from MSZ 7487-2 and the utility operators' requirements; utility.clearance_check reads it. Nothing is pre-filled on purpose."""
    ks = kinds or ["viz", "szennyviz", "csapadek", "gaz", "villany", "kozvilagitas", "tavkozles", "tavho"]
    pairs = {}
    for i, a in enumerate(ks):
        for b in ks[i:]:
            pairs[f"{a}|{b}"] = {"horizontal_m": None, "vertical_m": None}
    data = {"source": "Töltsd ki az MSZ 7487-2 és a közműüzemeltetők előírásai alapján",
            "default": {"horizontal_m": None, "vertical_m": None}, "pairs": pairs}
    p = ctx.resolve(path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"written": str(p), "pairs": len(pairs)}


def _rule(rules: dict, a: str, b: str, key: str):
    pairs = rules.get("pairs", {})
    for k in (f"{a}|{b}", f"{b}|{a}"):
        if k in pairs and pairs[k].get(key) is not None:
            return float(pairs[k][key])
    d = rules.get("default", {}).get(key)
    return None if d is None else float(d)


@op(T, "clearance_check", mutates=True)
def clearance_check(ctx: Ctx, rules: dict | None = None, rules_file: str | None = None, sel=None,
                    parallel_angle: float = 30.0, step: float = 0.5, mark: bool = True,
                    layer: str = "KOZMU_UTKOZES"):
    """Utility clearance check (közmű-ütközésvizsgálat) between the utility lines (utility.line; sel limits them): at crossings the vertical clear distance (axis elevations minus half sizes) against vertical_m; along roughly parallel runs (angle < parallel_angle) the horizontal clear distance (minus half sizes) against horizontal_m. rules = {"default": {...}, "pairs": {"gaz|viz": {"horizontal_m": .., "vertical_m": ..}}} or rules_file (utility.clearance_rules_template). Conflicts are listed and marked."""
    from shapely.geometry import LineString

    if rules_file:
        rules = json.loads(ctx.resolve(rules_file).read_text(encoding="utf-8"))
    if not rules:
        raise CadError("Give rules or rules_file (utility.clearance_rules_template writes one to fill)")
    m = _m(ctx)
    reg = _lines(ctx)
    if sel is not None:
        keep = {e.dxf.handle for e in select_from(ctx, sel)}
        reg = {h: v for h, v in reg.items() if h in keep}
    geo = {}
    for h, meta in reg.items():
        e = ctx.doc.entitydb[h]
        geo[h] = LineString([(x / m, y / m) for x, y in e.get_points("xy")])
    hs = list(geo)
    conflicts, checked = [], 0
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            a, b = hs[i], hs[j]
            ma, mb = reg[a], reg[b]
            la, lb = geo[a], geo[b]
            half = (ma["size"] + mb["size"]) / 2
            vrule = _rule(rules, ma["kind"], mb["kind"], "vertical_m")
            hrule = _rule(rules, ma["kind"], mb["kind"], "horizontal_m")
            inter = la.intersection(lb)
            crossings = [g for g in getattr(inter, "geoms", [inter]) if g.geom_type == "Point"] if not inter.is_empty else []
            for c in crossings:
                checked += 1
                za, zb = _z_along(ma, la, la.project(c)), _z_along(mb, lb, lb.project(c))
                if za is None or zb is None:
                    conflicts.append({"type": "keresztezés", "lines": [a, b], "kinds": [ma["kind"], mb["kind"]],
                                      "at": [round(c.x, 3), round(c.y, 3)], "status": "NINCS MAGASSÁG",
                                      "note": "Add elevations or depth+surface to check the vertical clearance"})
                    continue
                clear = abs(za - zb) - half
                if vrule is not None and clear < vrule:
                    conflicts.append({"type": "keresztezés", "lines": [a, b], "kinds": [ma["kind"], mb["kind"]],
                                      "at": [round(c.x, 3), round(c.y, 3)], "clear_m": round(clear, 3), "limit_m": vrule,
                                      "status": "HIBA"})
            if hrule is None:
                continue
            run = []
            L = la.length
            ns = max(2, int(L / step))
            for k in range(ns + 1):
                d = L * k / ns
                p = la.interpolate(d)
                if any(p.distance(c) < hrule + half + step for c in crossings):
                    if run:
                        conflicts.append(run[0] | {"to": run[-1]["at"], "min_clear_m": min(r["clear_m"] for r in run)})
                        run = []
                    continue
                q_d = lb.project(p)
                q = lb.interpolate(q_d)
                dist = p.distance(q)
                ta = la.interpolate(min(L, d + 0.5))
                tb = la.interpolate(max(0.0, d - 0.5))
                ua = math.atan2(ta.y - tb.y, ta.x - tb.x)
                qa = lb.interpolate(min(lb.length, q_d + 0.5))
                qb = lb.interpolate(max(0.0, q_d - 0.5))
                ub = math.atan2(qa.y - qb.y, qa.x - qb.x)
                angle = abs(((ua - ub + math.pi / 2) % math.pi) - math.pi / 2)
                clear = dist - half
                checked += 1
                if math.degrees(angle) < parallel_angle and clear < hrule:
                    run.append({"type": "párhuzamos", "lines": [a, b], "kinds": [ma["kind"], mb["kind"]],
                                "at": [round(p.x, 3), round(p.y, 3)], "clear_m": round(clear, 3), "limit_m": hrule,
                                "status": "HIBA"})
                elif run:
                    conflicts.append(run[0] | {"to": run[-1]["at"], "min_clear_m": min(r["clear_m"] for r in run)})
                    run = []
            if run:
                conflicts.append(run[0] | {"to": run[-1]["at"], "min_clear_m": min(r["clear_m"] for r in run)})
    marked = []
    if mark and conflicts:
        ensure_layer(ctx.doc, layer)
        ctx.doc.layers.get(layer).color = 1
        for c in conflicts:
            x, y = c["at"]
            marked.append(ctx.msp.add_circle((x * m, y * m), 1.0 * m, dxfattribs={"layer": layer}))
            val, lim = c.get("min_clear_m", c.get("clear_m")), c.get("limit_m")
            txt = f"{c['type']}: {'/'.join(c['kinds'])}"
            if val is not None and lim is not None:
                txt += f" {val:.2f} < {lim} m"
            t = ctx.msp.add_text(txt, height=0.4 * m, dxfattribs={"layer": layer})
            t.set_placement((x * m + 1.2 * m, y * m + 1.2 * m))
            marked.append(t)
    return {"lines": len(hs), "checked_points": checked, "conflicts": conflicts,
            "errors": sum(1 for c in conflicts if c["status"] == "HIBA"), "handles": handles(marked)}


@op(T, "cross_section", mutates=True)
def utility_cross_section(ctx: Ctx, alignment: str, station: float, insert, center_elevation: float | None = None,
                          scale: float = 1.0, half_width: float = 30.0, text_height: float = 0.25):
    """Utilities in a road cross section (közművek a keresztszelvényben): finds where the utility lines cross the section line at the station and draws each as a circle of its size at its offset and axis elevation, using the same placement as road.cross_section (insert, center elevation = design level at the station by default, scale), with kind, size and elevation labels."""
    from shapely.geometry import LineString

    from .ops_road import get_alignment, get_profile

    al, _ = get_alignment(ctx, alignment)
    m = _m(ctx)
    s = float(station)
    xl, yl, _h = al.point_at(s, half_width)
    xr, yr, _h = al.point_at(s, -half_width)
    cut = LineString([(xl, yl), (xr, yr)])
    if center_elevation is None:
        prof, _d = get_profile(ctx, alignment)
        if prof is None:
            raise CadError("Give center_elevation or create road.profile")
        center_elevation = prof.elevation(s)
    cz = float(center_elevation)
    ox, oy = insert[0] / m, insert[1] / m
    P = lambda o, z: ((ox + o * scale) * m, (oy + (z - cz) * scale) * m)
    found, out = [], []
    for h, meta in _lines(ctx).items():
        e = ctx.doc.entitydb[h]
        ln = LineString([(x / m, y / m) for x, y in e.get_points("xy")])
        inter = ln.intersection(cut)
        for g in [g for g in getattr(inter, "geoms", [inter]) if not inter.is_empty and g.geom_type == "Point"]:
            _s, o_left = al.station_of(g.x, g.y)
            z = _z_along(meta, ln, ln.project(g))
            lname, color = KINDS[meta["kind"]]
            found.append({"kind": meta["kind"], "offset_right": round(-o_left, 3), "axis_elevation": None if z is None else round(z, 3),
                          "size": meta["size"], "status": meta["status"]})
            if z is None:
                continue
            layer = f"KERESZT_KOZMU_{lname}"
            ensure_layer(ctx.doc, layer)
            ctx.doc.layers.get(layer).color = color
            c = P(-o_left, z)
            out.append(ctx.msp.add_circle(c, max(meta["size"] / 2, 0.05) * scale * m, dxfattribs={"layer": layer}))
            t = ctx.msp.add_text(f"{lname} D{int(round(meta['size'] * 1000))} {z:.2f}", height=text_height * scale * m,
                                 rotation=90, dxfattribs={"layer": layer})
            t.set_placement((c[0], c[1] + (meta["size"] / 2 + 0.1) * scale * m), align=_al("MIDDLE_LEFT"))
            out.append(t)
    found.sort(key=lambda r: r["offset_right"])
    return {"station": s, "center_elevation": cz, "utilities": found, "handles": handles(out)}
