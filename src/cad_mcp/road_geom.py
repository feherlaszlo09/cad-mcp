"""Road geometry: horizontal alignments built from tangents, clothoids (Euler
spirals) and circular arcs; vertical profiles with parabolic vertical curves.
Pure math, no ezdxf. Units: meters, radians internally."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from shapely.geometry import LineString, Point


class GeomError(ValueError):
    pass


def _integrate(theta, length: float, step: float = 0.25) -> tuple[float, float]:
    """∫0..length (cos θ(u), sin θ(u)) du with Simpson's rule."""
    if length <= 0:
        return 0.0, 0.0
    n = max(8, int(math.ceil(length / step)))
    if n % 2:
        n += 1
    h = length / n
    sx = sy = 0.0
    for i in range(n + 1):
        w = 1 if i in (0, n) else (4 if i % 2 else 2)
        t = theta(i * h)
        sx += w * math.cos(t)
        sy += w * math.sin(t)
    return sx * h / 3, sy * h / 3


@dataclass
class Element:
    kind: str  # line | arc | spiral
    s0: float  # start station
    length: float
    x0: float
    y0: float
    h0: float  # start heading (rad)
    k0: float = 0.0  # signed curvature at start (left = +)
    k1: float = 0.0  # signed curvature at end

    def heading(self, u: float) -> float:
        if self.kind == "line":
            return self.h0
        if self.kind == "arc":
            return self.h0 + self.k0 * u
        return self.h0 + self.k0 * u + (self.k1 - self.k0) * u * u / (2 * self.length)

    def point(self, u: float) -> tuple[float, float]:
        u = min(max(u, 0.0), self.length)
        if self.kind == "line":
            return self.x0 + u * math.cos(self.h0), self.y0 + u * math.sin(self.h0)
        if self.kind == "arc":
            k = self.k0
            return (self.x0 + (math.sin(self.h0 + k * u) - math.sin(self.h0)) / k,
                    self.y0 - (math.cos(self.h0 + k * u) - math.cos(self.h0)) / k)
        dx, dy = _integrate(self.heading, u)
        return self.x0 + dx, self.y0 + dy

    @property
    def end(self) -> tuple[float, float, float]:
        x, y = self.point(self.length)
        return x, y, self.heading(self.length)

    def radius(self) -> float | None:
        return abs(1 / self.k0) if self.kind == "arc" else None


@dataclass
class Curve:
    """One horizontal curve at an intersection point (PI)."""
    index: int
    pi: tuple[float, float]
    deflection_deg: float  # signed, left = +
    radius: float
    spiral_length: float
    tangent_length: float
    arc_length: float
    spiral_param_A: float
    shift_p: float
    stations: dict  # KE, IE, IV, KV (or IE, IV without spirals)


def spiral_end_local(R: float, L: float) -> tuple[float, float]:
    """Local end point of a clothoid starting tangent along +X, curvature 0 -> 1/R over L."""
    return _integrate(lambda u: u * u / (2 * R * L), L, step=min(0.25, L / 64))


class Alignment:
    def __init__(self, elements: list[Element], curves: list[Curve], start_station: float = 0.0):
        self.elements = elements
        self.curves = curves
        self.start_station = start_station
        self._dense: LineString | None = None

    @property
    def length(self) -> float:
        return sum(e.length for e in self.elements)

    @property
    def end_station(self) -> float:
        return self.start_station + self.length

    # --- building -------------------------------------------------------
    @classmethod
    def from_pis(cls, points, radii, spiral_lengths=None, start_station: float = 0.0) -> "Alignment":
        pts = [(float(p[0]), float(p[1])) for p in points]
        if len(pts) < 2:
            raise GeomError("Need at least a start and an end point")
        n_pi = len(pts) - 2
        radii = list(radii or [])
        spirals = list(spiral_lengths or [])
        if len(radii) != n_pi:
            raise GeomError(f"Give one radius per intersection point: {n_pi} needed, got {len(radii)}")
        spirals = (spirals + [0.0] * n_pi)[:n_pi]

        def unit(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            d = math.hypot(dx, dy)
            if d < 1e-9:
                raise GeomError("Two consecutive points coincide")
            return dx / d, dy / d, d

        curves: list[Curve] = []
        tangents = []
        for i in range(1, len(pts) - 1):
            ux, uy, _ = unit(pts[i - 1], pts[i])
            vx, vy, _ = unit(pts[i], pts[i + 1])
            delta = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
            R = float(radii[i - 1] or 0)
            L = float(spirals[i - 1] or 0)
            if R <= 0:
                tangents.append((0.0, delta, R, L, 0.0, 0.0, 0.0))
                continue
            tau = L / (2 * R) if L > 0 else 0.0
            if 2 * tau >= abs(delta) - 1e-9 and L > 0:
                raise GeomError(
                    f"PI {i}: clothoids too long for the deflection {math.degrees(abs(delta)):.3f}°: "
                    f"need L < {R * abs(delta):.2f} m with R = {R}")
            if L > 0:
                xs, ys = spiral_end_local(R, L)
                p = ys - R * (1 - math.cos(tau))
                k = xs - R * math.sin(tau)
            else:
                p = k = 0.0
            T = (R + p) * math.tan(abs(delta) / 2) + k
            arc_len = R * (abs(delta) - 2 * tau)
            tangents.append((T, delta, R, L, arc_len, p, math.sqrt(R * L) if L else 0.0))
        # check that curves fit between the points
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1])
            t_prev = tangents[i - 1][0] if i >= 1 else 0.0
            t_next = tangents[i][0] if i < len(tangents) else 0.0
            if t_prev + t_next > seg + 1e-6:
                raise GeomError(
                    f"Curves overlap on segment {i}->{i + 1}: tangent lengths {t_prev:.2f} + {t_next:.2f} "
                    f"> segment length {seg:.2f} m. Reduce radius or clothoid length.")
        elements: list[Element] = []
        s = start_station
        cx, cy = pts[0]
        h = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
        for i in range(1, len(pts) - 1):
            T, delta, R, L, arc_len, p, A = tangents[i - 1]
            ux, uy, _ = unit(pts[i - 1], pts[i])
            ts = (pts[i][0] - ux * T, pts[i][1] - uy * T)
            dl = math.dist((cx, cy), ts)
            if dl > 1e-9:
                elements.append(Element("line", s, dl, cx, cy, h))
                s += dl
            if R <= 0:
                cx, cy = pts[i]
                h = math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
                continue
            sign = 1.0 if delta > 0 else -1.0
            k = sign / R
            st = {}
            x, y = ts
            if L > 0:
                st["KE"] = s
                e1 = Element("spiral", s, L, x, y, h, 0.0, k)
                elements.append(e1)
                s += L
                x, y, h = e1.end
            st["IE"] = s
            if arc_len > 1e-9:
                e2 = Element("arc", s, arc_len, x, y, h, k, k)
                elements.append(e2)
                s += arc_len
                x, y, h = e2.end
            st["IV"] = s
            if L > 0:
                e3 = Element("spiral", s, L, x, y, h, k, 0.0)
                elements.append(e3)
                s += L
                x, y, h = e3.end
                st["KV"] = s
            curves.append(Curve(i, pts[i], math.degrees(delta), R, L, T, arc_len, A, p, st))
            cx, cy = x, y
            h = math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
        dl = math.dist((cx, cy), pts[-1])
        if dl > 1e-9:
            elements.append(Element("line", s, dl, cx, cy, h))
        return cls(elements, curves, start_station)

    # --- queries --------------------------------------------------------
    def element_at(self, station: float) -> Element:
        if not (self.start_station - 1e-6 <= station <= self.end_station + 1e-6):
            raise GeomError(f"Station {station:.3f} outside {self.start_station:.3f}..{self.end_station:.3f}")
        for e in self.elements:
            if station <= e.s0 + e.length + 1e-9:
                return e
        return self.elements[-1]

    def point_at(self, station: float, offset: float = 0.0) -> tuple[float, float, float]:
        """(x, y, heading) at station; offset > 0 is left of the direction of travel."""
        e = self.element_at(station)
        u = station - e.s0
        x, y = e.point(u)
        h = e.heading(u)
        if offset:
            x -= offset * math.sin(h)
            y += offset * math.cos(h)
        return x, y, h

    def dense(self, step: float = 0.5) -> LineString:
        if self._dense is None:
            pts = [self.point_at(s)[:2] for s in self.stations(step)]
            self._dense = LineString(pts)
        return self._dense

    def stations(self, step: float, include_ends: bool = True) -> list[float]:
        s0, s1 = self.start_station, self.end_station
        out = []
        first = math.ceil(s0 / step - 1e-9) * step
        s = first
        while s <= s1 + 1e-9:
            out.append(round(s, 9))
            s += step
        if include_ends:
            if not out or out[0] > s0 + 1e-9:
                out.insert(0, s0)
            if out[-1] < s1 - 1e-9:
                out.append(s1)
        return out

    def station_of(self, x: float, y: float) -> tuple[float, float]:
        """(station, offset) of a point; offset > 0 left."""
        line = self.dense(min(0.5, self.length / 200))
        d = line.project(Point(x, y))
        s = self.start_station + d
        # refine with a few Newton steps on the exact geometry
        for _ in range(4):
            px, py, h = self.point_at(min(max(s, self.start_station), self.end_station))
            along = (x - px) * math.cos(h) + (y - py) * math.sin(h)
            s += along
            if abs(along) < 1e-7:
                break
        s = min(max(s, self.start_station), self.end_station)
        px, py, h = self.point_at(s)
        off = -(x - px) * math.sin(h) + (y - py) * math.cos(h)
        return s, off

    def to_dict(self) -> dict:
        return {"start_station": self.start_station,
                "elements": [asdict(e) for e in self.elements],
                "curves": [asdict(c) for c in self.curves]}

    @classmethod
    def from_dict(cls, d: dict) -> "Alignment":
        return cls([Element(**e) for e in d["elements"]],
                   [Curve(**{**c, "pi": tuple(c["pi"])}) for c in d["curves"]], d["start_station"])


def format_station(s: float, decimals: int = 2) -> str:
    """Hungarian/EU style chainage: 1+234.56 (km + m)."""
    sign = "-" if s < 0 else ""
    s = abs(s)
    km = int(s // 1000)
    m = s - km * 1000
    if round(m, decimals) >= 1000:
        km += 1
        m = 0.0
    width = 4 + decimals if decimals else 3
    return f"{sign}{km}+{m:0{width}.{decimals}f}"


# ---------------------------------------------------------------------------
# Vertical profile
# ---------------------------------------------------------------------------


@dataclass
class VCurve:
    station: float  # VPI
    elevation: float
    radius: float
    g_in: float  # grade as fraction
    g_out: float
    length: float
    start: float
    end: float
    kind: str  # crest | sag


class Profile:
    """Grade line through VPIs with parabolic vertical curves of given radius."""

    def __init__(self, vpis, radii=None):
        self.vpis = [(float(s), float(z)) for s, z in vpis]
        if len(self.vpis) < 2:
            raise GeomError("Need at least two profile points")
        if any(b[0] <= a[0] for a, b in zip(self.vpis, self.vpis[1:])):
            raise GeomError("Profile stations must increase")
        n = len(self.vpis) - 2
        radii = list(radii or [])
        radii = (radii + [0.0] * n)[:n]
        self.grades = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(self.vpis, self.vpis[1:])]
        self.curves: list[VCurve] = []
        for i in range(1, len(self.vpis) - 1):
            R = float(radii[i - 1] or 0)
            g1, g2 = self.grades[i - 1], self.grades[i]
            if R <= 0 or abs(g2 - g1) < 1e-12:
                continue
            L = R * abs(g2 - g1)
            s, z = self.vpis[i]
            self.curves.append(VCurve(s, z, R, g1, g2, L, s - L / 2, s + L / 2,
                                      "crest" if g2 < g1 else "sag"))
        for a, b in zip(self.curves, self.curves[1:]):
            if a.end > b.start + 1e-6:
                raise GeomError(f"Vertical curves at {a.station} and {b.station} overlap; reduce radii")
        for c in self.curves:
            i = [v[0] for v in self.vpis].index(c.station)
            if c.start < self.vpis[i - 1][0] - 1e-6 or c.end > self.vpis[i + 1][0] + 1e-6:
                raise GeomError(f"Vertical curve at {c.station} is longer than its grades; reduce radius")

    def elevation(self, s: float) -> float:
        for c in self.curves:
            if c.start <= s <= c.end:
                x = s - c.start
                z0 = c.elevation - c.g_in * c.length / 2
                return z0 + c.g_in * x + (c.g_out - c.g_in) * x * x / (2 * c.length)
        for (s0, z0), (s1, z1) in zip(self.vpis, self.vpis[1:]):
            if s0 - 1e-9 <= s <= s1 + 1e-9:
                return z0 + (z1 - z0) * (s - s0) / (s1 - s0)
        raise GeomError(f"Station {s} outside profile {self.vpis[0][0]}..{self.vpis[-1][0]}")

    def to_dict(self) -> dict:
        return {"vpis": self.vpis, "radii": [c.radius for c in self.curves],
                "curves": [asdict(c) for c in self.curves], "grades": self.grades}


# ---------------------------------------------------------------------------
# Superelevation (túlemelés)
# ---------------------------------------------------------------------------


def superelevation_at(al: "Alignment", spec: dict | None, s: float) -> tuple[float, float]:
    """Outward cross slopes in % of the left and right lanes at station s (negative = falls away
    from the axis). Normal crown -n/-n; in curves the outer lane rotates about the axis linearly
    along the clothoid (or a runoff length without clothoids) up to the full one-way slope e."""
    if not spec:
        return (-2.5, -2.5)
    n = float(spec.get("normal", 2.5))
    curves = spec.get("curves", {})
    for idx, c in enumerate(al.curves, 1):
        cs = curves.get(str(idx))
        if not cs:
            continue
        e = float(cs["e"])
        st = c.stations
        if "KE" in st:
            up, down = (st["KE"], st["IE"]), (st["IV"], st["KV"])
        else:
            lr = float(cs.get("runoff") or 40.0)
            up = (st["IE"] - 2 * lr / 3, st["IE"] + lr / 3)
            down = (st["IV"] - lr / 3, st["IV"] + 2 * lr / 3)
        if up[0] - 1e-9 <= s <= down[1] + 1e-9:
            if s < up[1]:
                t = (s - up[0]) / max(up[1] - up[0], 1e-9)
            elif s > down[0]:
                t = (down[1] - s) / max(down[1] - down[0], 1e-9)
            else:
                t = 1.0
            outer = -n + t * (n + e)
            inner = -max(n, outer)
            # left-turning curve: centre on the left, outer edge is the right side
            return (inner, outer) if c.deflection_deg > 0 else (outer, inner)
    return (-n, -n)
