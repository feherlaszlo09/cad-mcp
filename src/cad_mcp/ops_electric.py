"""Tool `electric` (villamos, közvilágítás): street lighting pole layout along an alignment,
photometric files (EULUMDAT .ldt, IES LM-63 .ies), point-by-point horizontal illuminance on the
road surface (Eav, Emin, U0, isolux lines), voltage drop along a radial cable, IEC 60617-style
single-line symbols and single-line diagrams (egyvonalas kapcsolási rajz).

Metres, EOV-style drawing coordinates (x = Y east, y = X north). Requirement values (lighting
class, voltage drop limit, maintenance factor …) are given by the designer; nothing is assumed."""

from __future__ import annotations

import math

import numpy as np

from .core import CadError, Ctx, ensure_layer, handles, op

T = "electric"


def _m(ctx: Ctx) -> float:
    from .ops_road import _m as road_m

    return road_m(ctx)


def _al(name: str):
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment[name]


# ---------------------------------------------------------------------------
# photometry
# ---------------------------------------------------------------------------


class Photometry:
    """Absolute intensities I(C, γ) in cd on a full 0–360° C grid."""

    def __init__(self, c_angles, g_angles, table, flux_lm, name="", watts=None):
        self.C = np.asarray(c_angles, float)
        self.G = np.asarray(g_angles, float)
        self.I = np.asarray(table, float)  # shape (len(C), len(G))
        self.flux = flux_lm
        self.name = name
        self.watts = watts

    @staticmethod
    def _full(c, table, sym: str):
        """Expand a symmetric C range to 0..360."""
        c = list(c)
        rows = [list(r) for r in table]
        if sym == "rot":
            return np.array([0.0, 360.0]), np.array([rows[0], rows[0]])
        if sym == "c0c180":  # 0..180 given
            ext_c = c + [360 - a for a in reversed(c[:-1])]
            ext_r = rows + list(reversed(rows[:-1]))
        elif sym == "quad":  # 0..90 given
            half_c = c + [180 - a for a in reversed(c[:-1])]
            half_r = rows + list(reversed(rows[:-1]))
            ext_c = half_c + [360 - a for a in reversed(half_c[:-1])]
            ext_r = half_r + list(reversed(half_r[:-1]))
        elif sym == "c90c270":  # 270..360..90 given (as -90..90)
            cc = [((a + 180) % 360) - 180 for a in c]  # -90..90
            half_c = cc + [180 - a for a in reversed(cc[:-1])]  # -90..270
            half_r = rows + list(reversed(rows[:-1]))
            ext = sorted(zip([a % 360 for a in half_c], half_r), key=lambda t: t[0])
            ext_c = [a for a, _ in ext]
            ext_r = [r for _, r in ext]
            if ext_c[0] > 0:
                ext_c = [0.0] + ext_c
                ext_r = [ext_r[-1]] + ext_r
        else:
            ext_c, ext_r = c, rows
        if ext_c[-1] < 360 - 1e-9:
            ext_c = ext_c + [360.0]
            ext_r = ext_r + [ext_r[0]]
        return np.array(ext_c, float), np.array(ext_r, float)

    def intensity(self, C, G):
        C = np.mod(np.asarray(C, float), 360.0)
        G = np.clip(np.asarray(G, float), self.G[0], self.G[-1])
        ci = np.clip(np.searchsorted(self.C, C, side="right") - 1, 0, len(self.C) - 2)
        gi = np.clip(np.searchsorted(self.G, G, side="right") - 1, 0, len(self.G) - 2)
        c0, c1 = self.C[ci], self.C[ci + 1]
        g0, g1 = self.G[gi], self.G[gi + 1]
        tc = np.where(c1 > c0, (C - c0) / np.maximum(c1 - c0, 1e-12), 0.0)
        tg = np.where(g1 > g0, (G - g0) / np.maximum(g1 - g0, 1e-12), 0.0)
        i00 = self.I[ci, gi]
        i01 = self.I[ci, gi + 1]
        i10 = self.I[ci + 1, gi]
        i11 = self.I[ci + 1, gi + 1]
        return (i00 * (1 - tc) * (1 - tg) + i10 * tc * (1 - tg) + i01 * (1 - tc) * tg + i11 * tc * tg)


def read_ldt(text: str) -> Photometry:
    ln = [x.strip() for x in text.replace("\r", "").split("\n")]
    num = lambda s: float(s.replace(",", "."))
    isym = int(num(ln[2]))
    mc, ng = int(num(ln[3])), int(num(ln[5]))
    name = ln[8]
    conv = num(ln[23]) or 1.0
    nsets = int(num(ln[25]))
    k = 26
    lamps = abs(num(ln[k]))
    lamp_flux = num(ln[k + 2])
    watts = num(ln[k + 5]) if ln[k + 5] else None
    k += 6 * nsets + 10  # lamp sets, then 10 direct ratios
    c = [num(x) for x in ln[k:k + mc]]
    k += mc
    g = [num(x) for x in ln[k:k + ng]]
    k += ng
    if isym == 0:
        idx = list(range(mc))
    elif isym == 1:
        idx = [0]
    elif isym == 2:
        idx = list(range(mc // 2 + 1))
    elif isym == 3:
        start = 3 * mc // 4
        idx = [(start + i) % mc for i in range(mc // 2 + 1)]
    elif isym == 4:
        idx = list(range(mc // 4 + 1))
    else:
        raise CadError(f"Unknown EULUMDAT symmetry {isym}")
    vals = [num(x) for x in ln[k:k + len(idx) * ng] if x]
    if len(vals) < len(idx) * ng:
        raise CadError("EULUMDAT file ends early (intensity table)")
    flux = lamps * lamp_flux
    table = [[v * conv * flux / 1000.0 for v in vals[i * ng:(i + 1) * ng]] for i in range(len(idx))]
    cs = [c[i] for i in idx]
    sym = {0: "none", 1: "rot", 2: "c0c180", 3: "c90c270", 4: "quad"}[isym]
    C, I = Photometry._full(cs, table, sym)
    return Photometry(C, g, I, flux, name, watts)


def read_ies(text: str) -> Photometry:
    lines = text.replace("\r", "").split("\n")
    i = next((k for k, x in enumerate(lines) if x.strip().upper().startswith("TILT=")), None)
    if i is None:
        raise CadError("IES file without TILT= line")
    if lines[i].strip().upper() != "TILT=NONE":
        raise CadError("Only TILT=NONE IES files are supported")
    name = next((x.split("]", 1)[1].strip() for x in lines[:i] if x.upper().startswith("[LUMINAIRE]")), "")
    nums = [float(t) for x in lines[i + 1:] for t in x.replace(",", " ").split()]
    n_lamps, lm_per_lamp, mult, nv, nh, ptype = nums[:6]
    watts = nums[12]
    k = 13
    nv, nh = int(nv), int(nh)
    v = nums[k:k + nv]
    k += nv
    h = nums[k:k + nh]
    k += nh
    cd = [[x * mult for x in nums[k + j * nv:k + (j + 1) * nv]] for j in range(nh)]
    if int(ptype) != 1:
        raise CadError("Only type C photometry is supported")
    span = h[-1] - h[0]
    sym = "rot" if nh == 1 else "quad" if abs(span - 90) < 1e-6 else "c0c180" if abs(span - 180) < 1e-6 else "none"
    if sym == "none" and h[0] > 0:
        raise CadError("Unsupported IES horizontal angle range")
    flux = n_lamps * lm_per_lamp if lm_per_lamp > 0 else None
    C, I = Photometry._full(h, cd, sym)
    return Photometry(C, v, I, flux, name, watts)


def load_photometry(ctx: Ctx, path: str) -> Photometry:
    p = ctx.resolve(path)
    if not p.is_file():
        raise CadError(f"File not found: {p}")
    text = p.read_bytes().decode("latin-1")
    if p.suffix.lower() == ".ies" or "TILT=" in text.upper():
        return read_ies(text)
    return read_ldt(text)


@op(T, "photometry")
def photometry(ctx: Ctx, path: str):
    """Read a luminaire photometric file (EULUMDAT .ldt or IES LM-63 .ies, type C): name, lamp flux, power, maximum intensity and its direction, light under 90°."""
    ph = load_photometry(ctx, path)
    ci, gi = np.unravel_index(int(np.argmax(ph.I)), ph.I.shape)
    return {"name": ph.name, "flux_lm": ph.flux, "watts": ph.watts, "c_planes": len(ph.C), "gamma_angles": len(ph.G),
            "max_cd": round(float(ph.I.max()), 1), "max_at": {"C": float(ph.C[ci]), "gamma": float(ph.G[gi])},
            "efficacy_lm_w": round(ph.flux / ph.watts, 1) if ph.flux and ph.watts else None}


# ---------------------------------------------------------------------------
# street lighting layout and calculation
# ---------------------------------------------------------------------------


def _store(ctx, key, data):
    from .ops_road import _store as store

    store(ctx, key, data)


def _load(ctx, key):
    from .ops_road import _load as load

    return load(ctx, key)


@op(T, "lighting_layout", mutates=True)
def lighting_layout(ctx: Ctx, name: str, alignment: str, spacing: float, arrangement: str = "right",
                    offset: float = 1.0, road_half_width: float = 3.5, from_station: float | None = None,
                    to_station: float | None = None, height: float = 8.0, overhang: float = 1.0, tilt: float = 0.0,
                    prefix: str = "KV", cable: bool = True, text_height: float = 0.5):
    """Street lighting poles (közvilágítási oszlopok) along an alignment: arrangement 'left', 'right', 'opposite' (szemközti) or 'staggered' (váltott); spacing between poles on one side; poles at offset outside the pavement edge (road_half_width + offset from the axis); mounting height, arm overhang towards the road and tilt (degrees). Numbers the poles, draws them with arms and the cable route connecting the poles of each side; stored for electric.illuminance and electric.voltage_drop."""
    from .ops_road import get_alignment

    if arrangement not in ("left", "right", "opposite", "staggered"):
        raise CadError("arrangement: left, right, opposite, staggered")
    al, _ = get_alignment(ctx, alignment)
    s0 = al.start_station if from_station is None else float(from_station)
    s1 = al.end_station if to_station is None else float(to_station)
    sp = float(spacing)
    poles = []
    s, k = s0, 0
    while s <= s1 + 1e-6:
        sides = {"left": ["L"], "right": ["R"], "opposite": ["L", "R"], "staggered": ["L" if k % 2 == 0 else "R"]}[arrangement]
        for side in sides:
            sgn = 1.0 if side == "L" else -1.0
            off = sgn * (float(road_half_width) + float(offset))
            x, y, h = al.point_at(s, off)
            u0 = (math.cos(h), math.sin(h))  # along the road (C0)
            u90 = (math.sin(h) * sgn, -math.cos(h) * sgn)  # towards the road (C90)
            lx, ly = x + u90[0] * float(overhang), y + u90[1] * float(overhang)
            poles.append({"name": f"{prefix}{len(poles) + 1}", "side": side, "station": round(s, 3), "offset": off,
                          "x": x, "y": y, "lum": [lx, ly], "height": float(height), "u0": list(u0), "u90": list(u90),
                          "tilt": float(tilt)})
        k += 1
        s += sp if arrangement != "staggered" else sp / 2
    if not poles:
        raise CadError("No poles in the station range")
    m = _m(ctx)
    ensure_layer(ctx.doc, "KOZVIL_OSZLOP")
    ctx.doc.layers.get("KOZVIL_OSZLOP").color = 6
    ensure_layer(ctx.doc, "KOZVIL_KABEL")
    ctx.doc.layers.get("KOZVIL_KABEL").color = 6
    msp = ctx.msp
    th = text_height * m
    out = []
    for p in poles:
        out.append(msp.add_circle((p["x"] * m, p["y"] * m), 0.25 * m, dxfattribs={"layer": "KOZVIL_OSZLOP"}))
        out.append(msp.add_line((p["x"] * m, p["y"] * m), (p["lum"][0] * m, p["lum"][1] * m),
                                dxfattribs={"layer": "KOZVIL_OSZLOP"}))
        lx, ly = p["lum"]
        a, b = p["u0"], p["u90"]
        box = [(lx - a[0] * 0.3, ly - a[1] * 0.3), (lx + a[0] * 0.3, ly + a[1] * 0.3),
               (lx + a[0] * 0.3 + b[0] * 0.25, ly + a[1] * 0.3 + b[1] * 0.25),
               (lx - a[0] * 0.3 + b[0] * 0.25, ly - a[1] * 0.3 + b[1] * 0.25)]
        out.append(msp.add_lwpolyline([(q[0] * m, q[1] * m) for q in box], close=True, dxfattribs={"layer": "KOZVIL_OSZLOP"}))
        t = msp.add_text(f"{p['name']} h={p['height']:g} m", height=th, dxfattribs={"layer": "KOZVIL_OSZLOP"})
        t.set_placement(((p["x"] - p["u90"][0] * 0.8) * m, (p["y"] - p["u90"][1] * 0.8) * m), align=_al("MIDDLE_CENTER"))
        out.append(t)
    cable_len = {}
    if cable:
        for side in ("L", "R"):
            ps = [p for p in poles if p["side"] == side]
            if len(ps) < 2:
                continue
            pts, length = [], 0.0
            for a, b in zip(ps, ps[1:]):
                seg = [al.point_at(s_, a["offset"])[:2] for s_ in np.linspace(a["station"], b["station"], 12)]
                pts += seg if not pts else seg[1:]
                length += sum(math.dist(u, v) for u, v in zip(seg, seg[1:]))
            out.append(msp.add_lwpolyline([(x * m, y * m) for x, y in pts], dxfattribs={"layer": "KOZVIL_KABEL",
                                                                                      "linetype": "DASHED"}
                                          if ctx.doc.linetypes.has_entry("DASHED") else {"layer": "KOZVIL_KABEL"}))
            cable_len[side] = round(length, 2)
    _store(ctx, "LIGHTING_" + name, {"alignment": alignment, "poles": poles, "road_half_width": road_half_width})
    return {"layout": name, "poles": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in p.items()
                                       if k in ("name", "side", "station", "offset", "x", "y")} for p in poles],
            "count": len(poles), "cable_length_m": cable_len, "handles": handles(out)}


def _illum(ph: Photometry, poles: list, X, Y, mf: float, flux_scale: float):
    E = np.zeros_like(X, dtype=float)
    for p in poles:
        lx, ly = p["lum"]
        h = p["height"]
        u0 = np.array([p["u0"][0], p["u0"][1], 0.0])
        u90 = np.array([p["u90"][0], p["u90"][1], 0.0])
        tau = math.radians(p.get("tilt", 0.0))
        up = np.array([0.0, 0.0, 1.0])
        u90t = math.cos(tau) * u90 + math.sin(tau) * up
        dn = math.cos(tau) * (-up) + math.sin(tau) * u90
        vx, vy, vz = X - lx, Y - ly, -h * np.ones_like(X)
        a = vx * u0[0] + vy * u0[1] + vz * u0[2]
        b = vx * u90t[0] + vy * u90t[1] + vz * u90t[2]
        c = vx * dn[0] + vy * dn[1] + vz * dn[2]
        r = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
        gamma = np.degrees(np.arctan2(np.hypot(a, b), c))
        C = np.degrees(np.arctan2(b, a)) % 360
        Iv = ph.intensity(C, gamma) * flux_scale
        E += Iv * h / r ** 3
    return E * mf


@op(T, "illuminance", mutates=True)
def illuminance(ctx: Ctx, layout: str, luminaire: str, maintenance_factor: float, from_station: float | None = None,
                to_station: float | None = None, left: float | None = None, right: float | None = None,
                grid_along: float = 1.0, grid_across: float = 1.0, flux_lm: float | None = None,
                requirements: dict | None = None, isolux: list | None = None, labels: bool = False,
                text_height: float = 0.3):
    """Point-by-point horizontal illuminance (megvilágítás) on the road surface from the poles of electric.lighting_layout and a photometric file (luminaire = .ldt / .ies; C0 along the road, C90 towards the road, tilt as in the layout): calculation field between from/to stations (default: the first two poles of one side) and offsets left/right of the axis (default the pavement), grid spacing grid_along × grid_across (m). maintenance_factor (karbantartási tényező) and the requirements (e.g. {"Eav_min": 15, "U0_min": 0.4} for the chosen lighting class) are given by the designer. flux_lm overrides the lamp flux. Returns Eav, Emin, Emax, U0 = Emin/Eav, Ud = Emin/Emax and draws isolux lines (lux values) and optionally the grid values. Luminance (L, cd/m²) needs road reflection tables and is not calculated."""
    lay = _load(ctx, "LIGHTING_" + layout)
    if not lay:
        raise CadError(f"No lighting layout '{layout}' (electric.lighting_layout)")
    from .ops_road import get_alignment

    al, _ = get_alignment(ctx, lay["alignment"])
    ph = load_photometry(ctx, luminaire)
    scale = 1.0
    if flux_lm is not None:
        if not ph.flux:
            raise CadError("The file has absolute photometry; flux_lm cannot rescale it")
        scale = float(flux_lm) / ph.flux
    poles = lay["poles"]
    side_poles = sorted({p["station"] for p in poles})
    s0 = float(from_station) if from_station is not None else side_poles[0]
    if to_station is not None:
        s1 = float(to_station)
    else:
        same = sorted(p["station"] for p in poles if p["side"] == poles[0]["side"])
        s1 = same[1] if len(same) > 1 else side_poles[-1]
    hw = float(lay.get("road_half_width", 3.5))
    oL = float(left) if left is not None else hw
    oR = -float(right) if right is not None else -hw
    na = max(1, int(round((s1 - s0) / float(grid_along))))
    nc = max(1, int(round((oL - oR) / float(grid_across))))
    ss = s0 + (np.arange(na) + 0.5) * (s1 - s0) / na
    oo = oR + (np.arange(nc) + 0.5) * (oL - oR) / nc
    X = np.zeros((nc, na))
    Y = np.zeros((nc, na))
    for j, s in enumerate(ss):
        for i, o in enumerate(oo):
            X[i, j], Y[i, j], _h = al.point_at(float(s), float(o))
    E = _illum(ph, poles, X, Y, float(maintenance_factor), scale)
    eav, emin, emax = float(E.mean()), float(E.min()), float(E.max())
    res = {"luminaire": ph.name, "flux_lm": (ph.flux or 0) * scale or None, "field": {"from": s0, "to": s1, "left": oL,
                                                                                      "right": -oR},
           "grid": [na, nc], "Eav_lx": round(eav, 2), "Emin_lx": round(emin, 2), "Emax_lx": round(emax, 2),
           "U0": round(emin / eav, 3) if eav else None, "Ud": round(emin / emax, 3) if emax else None,
           "maintenance_factor": float(maintenance_factor)}
    checks = []
    for key, val in (requirements or {}).items():
        got = {"Eav_min": eav, "Emin_min": emin, "U0_min": emin / eav if eav else 0, "Ud_min": emin / emax if emax else 0}.get(key)
        if got is None and key == "Eav_max":
            checks.append({"check": key, "value": round(eav, 3), "limit": val, "ok": eav <= float(val)})
            continue
        if got is None:
            raise CadError("requirements keys: Eav_min, Eav_max, Emin_min, U0_min, Ud_min")
        checks.append({"check": key, "value": round(got, 3), "limit": val, "ok": got >= float(val)})
    if checks:
        res["checks"] = checks
    m = _m(ctx)
    out = []
    ensure_layer(ctx.doc, "KOZVIL_IZOLUX")
    ctx.doc.layers.get("KOZVIL_IZOLUX").color = 30
    levels = isolux if isolux is not None else sorted({round(v, 1) for v in np.linspace(emin, emax, 7)[1:-1]})
    if levels and len(ss) > 1 and len(oo) > 1:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        try:
            cs = ax.contour(X, Y, E, levels=levels)
            segs = cs.allsegs
        finally:
            plt.close(fig)
        for lev, lines in zip(levels, segs):
            for arr in lines:
                if len(arr) < 2:
                    continue
                out.append(ctx.msp.add_lwpolyline([(x * m, y * m) for x, y in arr], dxfattribs={"layer": "KOZVIL_IZOLUX"}))
                mid = arr[len(arr) // 2]
                t = ctx.msp.add_text(f"{lev:g} lx", height=text_height * m, dxfattribs={"layer": "KOZVIL_IZOLUX"})
                t.set_placement((mid[0] * m, mid[1] * m), align=_al("MIDDLE_CENTER"))
                out.append(t)
    if labels:
        for i in range(nc):
            for j in range(na):
                t = ctx.msp.add_text(f"{E[i, j]:.1f}", height=text_height * m, dxfattribs={"layer": "KOZVIL_RACS"})
                t.set_placement((X[i, j] * m, Y[i, j] * m), align=_al("MIDDLE_CENTER"))
                out.append(t)
    res["handles"] = handles(out)
    return res


# ---------------------------------------------------------------------------
# voltage drop
# ---------------------------------------------------------------------------

RHO20 = {"Cu": 0.017241, "Al": 0.028264}  # Ω·mm²/m at 20 °C (annealed copper, aluminium)
ALPHA = {"Cu": 0.00393, "Al": 0.00403}  # 1/K


@op(T, "voltage_drop")
def voltage_drop(ctx: Ctx, cross_section_mm2: float, nodes: list | None = None, layout: str | None = None,
                 lamp_power_w: float | None = None, feeder_length: float = 0.0, side: str | None = None,
                 material: str = "Cu", voltage: float = 230.0, phases: int = 1, cos_phi: float = 1.0,
                 x_ohm_per_km: float = 0.0, conductor_temp_c: float = 20.0, limit_pct: float | None = None):
    """Voltage drop (feszültségesés) along a radial cable from the supply: nodes = [{"name","length" (m from the previous node), "load_w" or "load_a"}] in order, or the poles of a lighting layout (layout, side 'L'/'R', lamp_power_w per pole, feeder_length to the first pole). Single-phase: ΔU = 2·I·L·(R·cosφ + X·sinφ); three-phase: √3·I·L·(…) with the line voltage. Conductor resistance from the material resistivity at conductor_temp_c (Cu/Al); reactance x_ohm_per_km (default 0). Returns ΔU and ΔU % at every node, checked against limit_pct when given."""
    if material not in RHO20:
        raise CadError("material: Cu or Al")
    if phases not in (1, 3):
        raise CadError("phases: 1 or 3")
    if layout:
        lay = _load(ctx, "LIGHTING_" + layout)
        if not lay:
            raise CadError(f"No lighting layout '{layout}'")
        if lamp_power_w is None:
            raise CadError("Give lamp_power_w for the layout")
        from .ops_road import get_alignment

        al, _ = get_alignment(ctx, lay["alignment"])
        ps = [p for p in lay["poles"] if side is None or p["side"] == side]
        if side is None and len({p["side"] for p in ps}) > 1:
            raise CadError("The layout has poles on both sides: give side 'L' or 'R' (one circuit per side)")
        nodes = []
        for i, p in enumerate(ps):
            if i == 0:
                L = float(feeder_length)
            else:
                q = ps[i - 1]
                seg = [al.point_at(s_, q["offset"])[:2] for s_ in np.linspace(q["station"], p["station"], 12)]
                L = sum(math.dist(u, v) for u, v in zip(seg, seg[1:]))
            nodes.append({"name": p["name"], "length": L, "load_w": float(lamp_power_w)})
    if not nodes:
        raise CadError("Give nodes or a lighting layout")
    rho = RHO20[material] * (1 + ALPHA[material] * (float(conductor_temp_c) - 20.0))
    r_per_m = rho / float(cross_section_mm2)
    x_per_m = float(x_ohm_per_km) / 1000.0
    sin_phi = math.sqrt(max(0.0, 1 - float(cos_phi) ** 2))
    k = 2.0 if phases == 1 else math.sqrt(3)

    def amps(n_):
        if n_.get("load_a") is not None:
            return float(n_["load_a"])
        p = float(n_.get("load_w", 0.0))
        return p / (float(voltage) * float(cos_phi)) if phases == 1 else p / (math.sqrt(3) * float(voltage) * float(cos_phi))

    loads = [amps(n_) for n_ in nodes]
    du, rows = 0.0, []
    for i, n_ in enumerate(nodes):
        current = sum(loads[i:])  # everything downstream flows through this section
        du += k * current * float(n_["length"]) * (r_per_m * float(cos_phi) + x_per_m * sin_phi)
        rows.append({"node": n_["name"], "section_length_m": round(float(n_["length"]), 2), "section_current_a": round(current, 3),
                     "du_v": round(du, 3), "du_pct": round(du / float(voltage) * 100, 3)})
    out = {"material": material, "cross_section_mm2": float(cross_section_mm2), "phases": phases, "voltage": voltage,
           "resistance_ohm_per_km": round(r_per_m * 1000, 4), "total_current_a": round(sum(loads), 3), "nodes": rows,
           "max_du_pct": rows[-1]["du_pct"]}
    if limit_pct is not None:
        out["check"] = {"limit_pct": limit_pct, "ok": rows[-1]["du_pct"] <= float(limit_pct)}
    return out


# ---------------------------------------------------------------------------
# single-line symbols and diagrams
# ---------------------------------------------------------------------------

SYMBOLS = ["kapcsolo", "megszakito", "biztosito", "transzformator", "fogyasztasmero", "lampa", "dugalj", "motor",
           "foldeles", "elosztoszekreny", "tulfeszultseg_vedo", "kabelvegelzaro", "generator", "aramvalto"]


def _symbol_block(doc, kind: str) -> str:
    """IEC 60617-style symbol as a block, 1 unit high along +Y, connection points (0,0) and (0,1)."""
    name = f"VILL_{kind.upper()}"
    if doc.blocks.get(name) is not None:
        return name
    b = doc.blocks.new(name, base_point=(0, 0))
    L = b.add_line
    if kind == "kapcsolo":
        L((0, 0), (0, 0.3)), L((0, 0.3), (0.25, 0.75)), L((0, 0.75), (0, 1))
    elif kind == "megszakito":
        L((0, 0), (0, 0.3)), L((0, 0.3), (0.25, 0.75)), L((0, 0.75), (0, 1))
        L((-0.07, 0.68), (0.07, 0.82)), L((-0.07, 0.82), (0.07, 0.68))
    elif kind == "biztosito":
        b.add_lwpolyline([(-0.1, 0.25), (0.1, 0.25), (0.1, 0.75), (-0.1, 0.75)], close=True)
        L((0, 0), (0, 1))
    elif kind == "transzformator":
        b.add_circle((0, 0.37), 0.2), b.add_circle((0, 0.63), 0.2)
        L((0, 0), (0, 0.17)), L((0, 0.83), (0, 1))
    elif kind == "fogyasztasmero":
        b.add_lwpolyline([(-0.25, 0.25), (0.25, 0.25), (0.25, 0.75), (-0.25, 0.75)], close=True)
        L((-0.25, 0.6), (0.25, 0.6)), L((0, 0), (0, 0.25)), L((0, 0.75), (0, 1))
        b.add_text("kWh", height=0.1).set_placement((0, 0.42), align=_al("MIDDLE_CENTER"))
    elif kind == "lampa":
        b.add_circle((0, 0.6), 0.2)
        r = 0.2 / math.sqrt(2)
        L((-r, 0.6 - r), (r, 0.6 + r)), L((-r, 0.6 + r), (r, 0.6 - r)), L((0, 0), (0, 0.4))
    elif kind == "dugalj":
        b.add_arc((0, 0.6), 0.2, 0, 180), L((-0.2, 0.6), (0.2, 0.6)), L((0, 0), (0, 0.6))
    elif kind in ("motor", "generator"):
        b.add_circle((0, 0.6), 0.25), L((0, 0), (0, 0.35))
        b.add_text("M" if kind == "motor" else "G", height=0.2).set_placement((0, 0.6), align=_al("MIDDLE_CENTER"))
    elif kind == "foldeles":
        L((0, 1), (0, 0.4)), L((-0.25, 0.4), (0.25, 0.4)), L((-0.16, 0.3), (0.16, 0.3)), L((-0.07, 0.2), (0.07, 0.2))
    elif kind == "elosztoszekreny":
        b.add_lwpolyline([(-0.4, 0.2), (0.4, 0.2), (0.4, 0.8), (-0.4, 0.8)], close=True)
        L((0, 0), (0, 0.2)), L((0, 0.8), (0, 1))
    elif kind == "tulfeszultseg_vedo":
        b.add_lwpolyline([(-0.1, 0.3), (0.1, 0.3), (0.1, 0.7), (-0.1, 0.7)], close=True)
        L((0, 0.75), (0, 1)), L((0, 0.25), (0, 0.0)), L((0, 0.62), (-0.05, 0.5)), L((-0.05, 0.5), (0.05, 0.5))
        L((0.05, 0.5), (0, 0.38))
    elif kind == "kabelvegelzaro":
        b.add_lwpolyline([(-0.15, 0.4), (0.15, 0.4), (0, 0.65)], close=True), L((0, 0), (0, 0.4)), L((0, 0.65), (0, 1))
    elif kind == "aramvalto":
        b.add_circle((0, 0.5), 0.15), L((0, 0), (0, 1))
    else:
        raise CadError(f"kind must be one of {SYMBOLS}")
    return name


@op(T, "symbol", mutates=True)
def symbol(ctx: Ctx, kind: str, insert, size: float = 1.0, rotation: float = 0.0, label: str | None = None,
           layer: str = "VILLAMOS_JELKEP"):
    """Single-line electrical symbol (egyvonalas jelkép, IEC 60617 style) as a block: kapcsolo, megszakito, biztosito, transzformator, fogyasztasmero, lampa, dugalj, motor, generator, foldeles, elosztoszekreny, tulfeszultseg_vedo, kabelvegelzaro, aramvalto; size = height, connection points at the base point and size above it."""
    if kind not in SYMBOLS:
        raise CadError(f"kind must be one of {SYMBOLS}")
    bname = _symbol_block(ctx.doc, kind)
    ensure_layer(ctx.doc, layer)
    x, y = float(insert[0]), float(insert[1])
    ref = ctx.msp.add_blockref(bname, (x, y), dxfattribs={"layer": layer, "xscale": size, "yscale": size,
                                                          "rotation": float(rotation)})
    out = [ref]
    if label:
        t = ctx.msp.add_text(label, height=size * 0.18, dxfattribs={"layer": layer})
        t.set_placement((x + size * 0.35, y + size * 0.5), align=_al("MIDDLE_LEFT"))
        out.append(t)
    return {"block": bname, "handles": handles(out)}


@op(T, "single_line", mutates=True)
def single_line(ctx: Ctx, insert, feeders: list, supply: dict | None = None, bus_label: str = "",
                size: float = 10.0, spacing: float | None = None, layer: str = "VILLAMOS_EGYVONALAS"):
    """Single-line diagram (egyvonalas kapcsolási rajz): supply = {"elements": ["transzformator", "megszakito"], "label": "..."} drawn above a busbar, then feeders = [{"label": "F1", "elements": ["megszakito", "kapcsolo"], "load": "lampa", "text": "NYY-J 4×16 mm², 120 m"}, ...] hanging from the busbar, symbols size high, feeders spacing apart."""
    x0, y0 = float(insert[0]), float(insert[1])
    sp = float(spacing) if spacing is not None else size * 2.2
    ensure_layer(ctx.doc, layer)
    msp = ctx.msp
    out = []
    th = size * 0.16
    bus_y = y0
    n = max(1, len(feeders))
    bx0, bx1 = x0 - sp * 0.3, x0 + sp * (n - 1) + sp * 0.3
    out.append(msp.add_lwpolyline([(bx0, bus_y), (bx1, bus_y)], dxfattribs={"layer": layer, "const_width": size * 0.04}))
    if bus_label:
        t = msp.add_text(bus_label, height=th, dxfattribs={"layer": layer})
        t.set_placement((bx1 + size * 0.2, bus_y), align=_al("MIDDLE_LEFT"))
        out.append(t)
    if supply:
        cx = x0 + sp * (n - 1) / 2
        y = bus_y
        for kind in reversed(supply.get("elements", [])):
            r = symbol(ctx, kind, [cx, y], size=size, layer=layer)
            out += [ctx.doc.entitydb[h] for h in r["handles"]]
            y += size
        out.append(msp.add_line((cx, y), (cx, y + size * 0.3), dxfattribs={"layer": layer}))
        if supply.get("label"):
            t = msp.add_text(supply["label"], height=th, dxfattribs={"layer": layer})
            t.set_placement((cx, y + size * 0.45), align=_al("BOTTOM_CENTER"))
            out.append(t)
    for i, f in enumerate(feeders):
        cx = x0 + sp * i
        y = bus_y
        for kind in f.get("elements", []):
            r = symbol(ctx, kind, [cx, y], size=size, rotation=180, layer=layer)
            out += [ctx.doc.entitydb[h] for h in r["handles"]]
            y -= size
        if f.get("load"):
            r = symbol(ctx, f["load"], [cx, y], size=size, rotation=180, layer=layer)
            out += [ctx.doc.entitydb[h] for h in r["handles"]]
            y -= size
        if f.get("label"):
            t = msp.add_text(f["label"], height=th, dxfattribs={"layer": layer})
            t.set_placement((cx, y - size * 0.25), align=_al("TOP_CENTER"))
            out.append(t)
        if f.get("text"):
            t = msp.add_text(f["text"], height=th * 0.8, rotation=90, dxfattribs={"layer": layer})
            t.set_placement((cx + size * 0.45, bus_y - size * 0.2), align=_al("TOP_RIGHT"))
            out.append(t)
    return {"feeders": len(feeders), "handles": handles(out)}
