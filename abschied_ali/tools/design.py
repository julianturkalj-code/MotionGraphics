"""Geometrie des Abschiedsgeschenks (Einheit: mm, y nach oben, Ursprung = Mitte oben).

Aufbau von oben nach unten:
  1. 1887-Wappen mit Lorbeerkranz
  2. VOLKSPARK HAMBURG
  3. Namensband "ALI IHSAN YAVUZ" (Bogen parallel zum VOLKSPARK-Schwung)

Jedes Bauteil liefert zwei Ebenen:
  outline : Außenkontur (= schwarze Fläche im Aufnäher, wird zur tieferen Grundebene)
  raised  : erhabene Flächen (= graue Stickerei, bleibt auf voller Materialstärke stehen)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from fontTools.ttLib import TTFont
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from vectorize import load_rgba, outer_mask, grey_mask, mask_to_geom, smooth_geom

# --------------------------------------------------------------------------------------
# Parameter (hier anpassen)
# --------------------------------------------------------------------------------------
PARAMS = dict(
    # Größen der Bauteile (Breite der Außenkontur in mm)
    crest_width=195.0,       # 1887-Wappen (oben)
    vp_width=240.0,          # VOLKSPARK HAMBURG (Mitte)

    # Material / Relief
    thickness=8.0,           # Gesamtstärke Alu-Platte
    relief_depth=2.0,        # Tiefe der vertieften (im Aufnäher schwarzen) Flächen

    # Namensband (unten)
    name_text="ALI IHSAN YAVUZ",
    name_font="/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    name_cap_height=11.5,    # Versalhöhe der Schrift
    name_tracking=0.08,      # zusätzlicher Buchstabenabstand (Anteil der Schriftgröße)
    ribbon_width=150.0,      # Mindest-Sehnenlänge des Bandes (wird automatisch an den Namen angepasst)
    ribbon_end_margin=11.0,  # freier Platz zwischen Textende und Kerbenspitze
    ribbon_height=22.0,      # Höhe des erhabenen Bandes
    ribbon_sag=14.0,         # Wölbung (Bogen nach oben wie der VOLKSPARK-Schwung)
    ribbon_black_border=2.6, # schwarzer Rand ums Band
    ribbon_notch=7.0,        # Tiefe der Schwalbenschwanz-Kerbe an den Enden

    # Abstände / Verbindungen
    gap_raised=2.6,          # Mindestabstand erhabener Flächen benachbarter Bauteile
    junction_fillet=9.0,     # Radius der Ausrundung, mit der die Bauteile verbunden werden
    outline_tool_d=3.0,      # Fräser für die Außenkontur: Kerben schmaler als das werden geschlossen
    edge_smoothing=0.45,     # Glättung der aus dem Foto übernommenen Kanten (Gauß-Sigma in mm)
    min_pocket_width=1.2,    # schwarze Spalte zwischen erhabenen Inseln werden auf mind. diese Breite aufgeweitet
                             # (= kleinster nötiger Fräser für die Taschen)
)

SRC_CREST = "source/patch_1887.webp"
SRC_VP = "source/patch_volkspark.webp"


@dataclass
class Part:
    name: str
    outline: Polygon
    raised: object  # (Multi)Polygon
    extra: dict = field(default_factory=dict)

    def moved(self, dx=0.0, dy=0.0):
        return Part(self.name, affinity.translate(self.outline, dx, dy),
                    affinity.translate(self.raised, dx, dy), self.extra)


# --------------------------------------------------------------------------------------
# Bauteile aus den Aufnäher-Fotos
# --------------------------------------------------------------------------------------
def patch_part(name: str, path: str, width_mm: float, grey_thresh=70.0) -> Part:
    alpha, gray = load_rgba(path)
    outline = mask_to_geom(outer_mask(alpha), sigma=3.0, simplify_px=0.3)
    raised = mask_to_geom(grey_mask(gray, alpha, grey_thresh), sigma=1.6, simplify_px=0.3)
    raised = raised.intersection(outline.buffer(-1.0))
    minx, miny, maxx, maxy = outline.bounds
    s = width_mm / (maxx - minx)
    cx = (minx + maxx) / 2

    def tf(g):
        g = affinity.translate(g, -cx, -maxy)
        return affinity.scale(g, s, s, origin=(0, 0))

    outline = smooth_geom(tf(outline), PARAMS["edge_smoothing"] * 1.5)
    raised = smooth_geom(tf(raised), PARAMS["edge_smoothing"])
    if isinstance(outline, MultiPolygon):
        outline = max(outline.geoms, key=lambda p: p.area)
    outline = Polygon(outline.exterior)
    return Part(name, outline, raised, dict(px_to_mm=s))


# --------------------------------------------------------------------------------------
# Namensband mit vertiefter Schrift
# --------------------------------------------------------------------------------------
def _glyph_geom(tp: TextPath):
    geom = Polygon()
    polys = [Polygon(a) for a in tp.to_polygons() if len(a) >= 3]
    polys.sort(key=lambda q: -abs(q.area))
    for q in polys:
        geom = geom.symmetric_difference(q.buffer(0))
    return geom.buffer(0)


def _arc_point(R, cy, t):
    """Bogen nach oben (Mittelpunkt unterhalb): Scheitel bei t=0."""
    return R * math.sin(t), cy + R * math.cos(t)


def text_on_arc(text: str, font_path: str, cap: float, R: float, cy: float, tracking: float = 0.0):
    """Text entlang eines nach oben gewölbten Bogens. Die Versalmitte liegt auf Radius R."""
    fp = FontProperties(fname=font_path)
    cap_per_em = TextPath((0, 0), "H", size=1.0, prop=fp).get_extents().height
    em = cap / cap_per_em
    tt = TTFont(font_path)
    cmap, upm, hmtx = tt.getBestCmap(), tt["head"].unitsPerEm, tt["hmtx"]
    adv = [hmtx[cmap[ord(c)]][0] / upm * em + tracking * em for c in text]
    total = sum(adv) - tracking * em
    glyphs, pen = [], -total / 2
    for c, a in zip(text, adv):
        xc = pen + (a - tracking * em) / 2
        pen += a
        if c == " ":
            continue
        g = _glyph_geom(TextPath((0, 0), c, size=em, prop=fp))
        gx0, _, gx1, _ = g.bounds
        g = affinity.translate(g, -(gx0 + gx1) / 2, -cap / 2)
        th = xc / R
        g = affinity.rotate(g, -math.degrees(th), origin=(0, 0))
        g = affinity.translate(g, *_arc_point(R, cy, th))
        glyphs.append(g)
    return unary_union(glyphs), total


def arc_band(R, cy, half_h, th, n=240):
    ts = np.linspace(-th, th, n)
    outer = [_arc_point(R + half_h, cy, t) for t in ts]
    inner = [_arc_point(R - half_h, cy, t) for t in ts[::-1]]
    return Polygon(outer + inner)


def ribbon_part(p=PARAMS) -> Part:
    hh, sag = p["ribbon_height"] / 2, p["ribbon_sag"]
    # Bandlänge so wählen, dass der ganze Name plus Rand und Kerbe auf das Band passt
    _, text_len = text_on_arc(p["name_text"], p["name_font"], p["name_cap_height"], 1e4, -1e4,
                              p["name_tracking"])
    need_half_arc = text_len / 2 + p["ribbon_notch"] + p["ribbon_end_margin"]
    w = p["ribbon_width"]
    while True:
        R = (w * w / 4 + sag * sag) / (2 * sag)
        if R * math.asin((w / 2) / R) >= need_half_arc:
            break
        w += 0.5
    R = (w * w / 4 + sag * sag) / (2 * sag)
    cy = -R  # Scheitel der Bandmitte bei y=0
    th = math.asin((w / 2) / R)
    band = arc_band(R, cy, hh, th)
    # Schwalbenschwanz-Kerben an den Enden
    notches = []
    for s in (-1, 1):
        t = s * th
        c = np.array(_arc_point(R, cy, t))
        tangent = np.array([math.cos(t), -math.sin(t)]) * s  # nach außen
        normal = np.array([math.sin(t), math.cos(t)])
        tip = c - tangent * p["ribbon_notch"]
        a = c + normal * (hh + 1) + tangent * 1.0
        b = c - normal * (hh + 1) + tangent * 1.0
        notches.append(Polygon([tuple(a), tuple(tip), tuple(b)]))
    band = band.difference(unary_union(notches)).buffer(0)
    band = band.buffer(0.6, join_style="round").buffer(-0.6)  # Spitzen leicht entschärfen
    letters, text_len = text_on_arc(p["name_text"], p["name_font"], p["name_cap_height"], R, cy,
                                    p["name_tracking"])
    raised = band.difference(letters)
    outline = band.buffer(p["ribbon_black_border"], join_style="mitre", mitre_limit=2.5)
    outline = Polygon(outline.exterior)
    dy = -outline.bounds[3]
    return Part("namensband", affinity.translate(outline, 0, dy), affinity.translate(raised, 0, dy),
                dict(text_length=text_len, radius=R, chord=w))


# --------------------------------------------------------------------------------------
# Zusammensetzen
# --------------------------------------------------------------------------------------
def stack_below(upper: Part, lower: Part, gap: float) -> Part:
    """Schiebt `lower` von unten an `upper` heran, bis die erhabenen Flächen den Abstand `gap` haben."""
    cur = lower.moved(0, (upper.outline.bounds[1] - 5) - lower.outline.bounds[3])
    lo, hi = 0.0, (upper.outline.bounds[3] - upper.outline.bounds[1])
    for _ in range(40):  # binäre Suche
        mid = (lo + hi) / 2
        cand = cur.moved(0, mid)
        if cand.raised.distance(upper.raised) >= gap and not cand.raised.intersects(upper.raised):
            lo = mid
        else:
            hi = mid
    return cur.moved(0, lo)


def junction_fill(a: Polygon, b: Polygon, r: float):
    u = unary_union([a, b])
    closed = u.buffer(r, join_style="round").buffer(-r, join_style="round")
    zone = a.buffer(1.6 * r).intersection(b.buffer(1.6 * r))
    return closed.difference(u).intersection(zone)


def separate_raised(raised, outline, min_w: float):
    """Schwarze Spalte zwischen getrennten erhabenen Inseln (z. B. Lorbeerblätter, Buchstaben)
    auf mindestens min_w aufweiten, damit ein Fräser dieses Durchmessers durchpasst.
    Es wird nur lokal an den Engstellen ein paar Zehntel abgenommen."""
    from shapely.strtree import STRtree
    polys = [g for g in getattr(raised, "geoms", [raised]) if g.area > 0.01]
    tree = STRtree(polys)
    for i in range(len(polys)):
        for j in tree.query(polys[i].buffer(min_w)):
            j = int(j)
            if j <= i:
                continue
            a, b = polys[i], polys[j]
            d = a.distance(b)
            if d >= min_w - 1e-3:
                continue
            delta = (min_w - d) / 2 + 0.05
            a2 = a.difference(b.buffer(d + delta, quad_segs=16)).buffer(0)
            b2 = b.difference(a.buffer(d + delta, quad_segs=16)).buffer(0)
            polys[i] = max(getattr(a2, "geoms", [a2]), key=lambda g: g.area)
            polys[j] = max(getattr(b2, "geoms", [b2]), key=lambda g: g.area)
    raised = unary_union(polys)
    # schwarzer Rand zur Außenkontur ebenfalls mindestens min_w
    return raised.intersection(outline.buffer(-min_w, quad_segs=16)).buffer(0)


def build(p=PARAMS):
    crest = patch_part("wappen_1887", SRC_CREST, p["crest_width"])
    vp = patch_part("volkspark", SRC_VP, p["vp_width"])
    ribbon = ribbon_part(p)

    gap = p["gap_raised"]
    vp = stack_below(crest, vp, gap)
    ribbon = stack_below(vp, ribbon, gap)
    parts = [crest, vp, ribbon]

    outline = unary_union([q.outline for q in parts])
    fills = [junction_fill(parts[i].outline, parts[i + 1].outline, p["junction_fillet"])
             for i in range(len(parts) - 1)]
    outline = unary_union([outline] + fills)
    rt = p["outline_tool_d"] / 2
    outline = outline.buffer(rt, join_style="round").buffer(-rt, join_style="round")
    if isinstance(outline, MultiPolygon):
        raise RuntimeError("Bauteile hängen nicht zusammen: %d Teile" % len(outline.geoms))
    outline = Polygon(outline.exterior)  # keine Durchbrüche

    raised = unary_union([q.raised for q in parts])
    for _ in range(4):  # iterieren, bis alle Spalte die Mindestbreite haben
        raised = separate_raised(raised, outline, p["min_pocket_width"])
    minx, miny, maxx, maxy = outline.bounds
    dx, dy = -(minx + maxx) / 2, -maxy
    outline = affinity.translate(outline, dx, dy)
    raised = affinity.translate(raised, dx, dy)
    parts = [q.moved(dx, dy) for q in parts]
    return dict(outline=outline, raised=raised, pocket=outline.difference(raised), parts=parts, params=p)
