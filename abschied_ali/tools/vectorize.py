"""Raster-Masken der Aufnäher-Fotos -> saubere Shapely-Polygone (Einheit: Pixel, y nach oben).

Vorgehen pro Maske:
  1. Binärmaske aus Alpha (Umriss) bzw. Helligkeit (graue Stickerei = erhaben)
  2. Morphologisch glätten (Stick-Textur entfernen)
  3. Gauß-Weichzeichnung + Marching Squares bei 0.5 -> subpixel-genaue, glatte Kontur
  4. Konturen per Even-Odd (XOR) zu Polygonen mit Löchern zusammensetzen
"""
from __future__ import annotations

import numpy as np
import cv2
from PIL import Image
from scipy import ndimage
from skimage import measure
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import make_valid


def load_rgba(path: str) -> tuple[np.ndarray, np.ndarray]:
    a = np.array(Image.open(path).convert("RGBA"))
    alpha = a[..., 3].astype(np.float32)
    gray = a[..., :3].astype(np.float32).mean(axis=2)
    return alpha, gray


def disk(r: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def outer_mask(alpha: np.ndarray, close_r: int = 6) -> np.ndarray:
    m = (alpha > 128).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, disk(close_r))
    m = ndimage.binary_fill_holes(m).astype(np.uint8)
    # nur die größte Komponente behalten (Staub/Artefakte weg)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 2:
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m = (lab == keep).astype(np.uint8)
    return m


def grey_mask(gray: np.ndarray, alpha: np.ndarray, thresh: float = 70.0,
              blur: float = 1.6, open_r: int = 1, close_r: int = 2,
              min_area_px: int = 60) -> np.ndarray:
    g = cv2.GaussianBlur(gray, (0, 0), blur)
    m = ((g > thresh) & (alpha > 128)).astype(np.uint8)
    if close_r:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, disk(close_r))
    if open_r:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, disk(open_r))
    # kleine Inseln und kleine Löcher entfernen
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area_px:
            m[lab == i] = 0
    inv = 1 - m
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area_px:
            m[lab == i] = 1
    return m


def mask_to_geom(mask: np.ndarray, sigma: float = 1.8, simplify_px: float = 0.25,
                 min_area_px: float = 40.0):
    """Binärmaske -> (Multi)Polygon in Pixelkoordinaten, y nach oben (y = -row)."""
    pad = 4
    f = np.pad(mask.astype(np.float32), pad)
    f = ndimage.gaussian_filter(f, sigma)
    contours = measure.find_contours(f, 0.5)
    polys = []
    for c in contours:
        if len(c) < 8:
            continue
        xy = np.column_stack([c[:, 1] - pad, -(c[:, 0] - pad)])
        p = Polygon(xy)
        if not p.is_valid:
            p = make_valid(p)
        if p.area < min_area_px:
            continue
        polys.append(p)
    # Even-Odd-Kombination: größte zuerst, dann XOR
    polys.sort(key=lambda p: -p.area)
    geom = Polygon()
    for p in polys:
        geom = geom.symmetric_difference(p)
    geom = make_valid(geom).buffer(0)
    if simplify_px:
        geom = geom.simplify(simplify_px, preserve_topology=True).buffer(0)
    return geom


def as_polys(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    out = []
    for g in getattr(geom, "geoms", []):
        out += as_polys(g)
    return out


def smooth_ring(coords, sigma_mm: float, step_mm: float = 0.1):
    """Ring gleichmäßig neu abtasten und entlang der Bogenlänge gaußglätten (entfernt Stick-Wellen)."""
    a = np.asarray(coords)[:-1]
    seg = np.linalg.norm(np.diff(np.vstack([a, a[:1]]), axis=0), axis=1)
    L = seg.sum()
    if L < 20 * sigma_mm:
        return np.vstack([a, a[:1]])
    s = np.concatenate([[0], np.cumsum(seg)])
    n = max(int(L / step_mm), 16)
    t = np.linspace(0, L, n, endpoint=False)
    closed = np.vstack([a, a[:1]])
    x = np.interp(t, s, closed[:, 0])
    y = np.interp(t, s, closed[:, 1])
    sig = sigma_mm / (L / n)
    x = ndimage.gaussian_filter1d(x, sig, mode="wrap")
    y = ndimage.gaussian_filter1d(y, sig, mode="wrap")
    out = np.column_stack([x, y])
    return np.vstack([out, out[:1]])


def smooth_geom(geom, sigma_mm: float, simplify_mm: float = 0.01):
    polys = []
    for p in as_polys(geom):
        ext = smooth_ring(p.exterior.coords, sigma_mm)
        holes = [smooth_ring(i.coords, sigma_mm) for i in p.interiors]
        q = Polygon(ext, holes).buffer(0)
        polys.append(q)
    g = unary_union(polys)
    return g.simplify(simplify_mm, preserve_topology=True).buffer(0)
