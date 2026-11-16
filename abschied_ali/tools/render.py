"""Vorschaubilder: Draufsicht als 'gefrästes Alu' (Höhenkarte + Licht) und technische 2D-Zeichnung."""
from __future__ import annotations

import numpy as np
import cv2
from scipy import ndimage

from vectorize import as_polys


def rasterize(geom, bounds, ppm, ss=2):
    minx, miny, maxx, maxy = bounds
    W = int(np.ceil((maxx - minx) * ppm))
    H = int(np.ceil((maxy - miny) * ppm))
    s = ppm * ss
    img = np.zeros((H * ss, W * ss), np.uint8)
    shift = 4
    polys = sorted(as_polys(geom), key=lambda p: -p.area)
    for p in polys:
        def pts(c):
            a = np.asarray(c)
            xy = np.column_stack([(a[:, 0] - minx) * s, (maxy - a[:, 1]) * s])
            return np.round(xy * (1 << shift)).astype(np.int32)
        cv2.fillPoly(img, [pts(p.exterior.coords)], 255, lineType=cv2.LINE_AA, shift=shift)
        for i in p.interiors:
            cv2.fillPoly(img, [pts(i.coords)], 0, lineType=cv2.LINE_AA, shift=shift)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    return img.astype(np.float32) / 255.0


def render_metal(outline, raised, thickness, relief, path, ppm=5.0, painted=True, margin=12.0,
                 bg=(0.93, 0.93, 0.92)):
    minx, miny, maxx, maxy = outline.bounds
    b = (minx - margin, miny - margin, maxx + margin, maxy + margin)
    o = rasterize(outline, b, ppm)
    r = rasterize(raised, b, ppm)
    H = o * (thickness - relief) + r * relief  # Höhe in mm
    Hs = ndimage.gaussian_filter(H, 0.35 * ppm)  # leichte Kantenrundung
    gy, gx = np.gradient(Hs, 1.0 / ppm)
    n = np.dstack([-gx, gy, np.ones_like(H)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array([-0.55, 0.55, 0.63])
    L /= np.linalg.norm(L)
    diff = np.clip((n * L).sum(2), 0, 1)
    # Glanz (Blinn)
    V = np.array([0, 0, 1.0])
    Hh = (L + V) / np.linalg.norm(L + V)
    spec = np.clip((n * Hh).sum(2), 0, 1) ** 40
    # Schlagschatten entlang der Lichtrichtung
    elev = np.arctan2(L[2], np.hypot(L[0], L[1]))
    dirx, diry = L[0] / np.hypot(L[0], L[1]), -L[1] / np.hypot(L[0], L[1])
    shadow = np.zeros_like(H)
    max_len = int((thickness / np.tan(elev)) * ppm) + 2
    for k in range(1, max_len, 1):
        sx, sy = int(round(dirx * k)), int(round(diry * k))
        shifted = np.roll(np.roll(H, -sy, axis=0), -sx, axis=1)
        occl = shifted - H - (k / ppm) * np.tan(elev)
        shadow = np.maximum(shadow, np.clip(occl * 2.0, 0, 1))
    shadow = ndimage.gaussian_filter(shadow, 0.6 * ppm)
    # gebürstete Alu-Textur
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, (H.shape[0], 1)) * 0.6 + rng.normal(0, 1, H.shape) * 0.25
    noise = ndimage.gaussian_filter1d(noise, 18, axis=1)
    alu = 0.80 + 0.05 * noise
    top = r > 0.5
    base_mask = (o > 0.5) & ~top
    col = np.zeros(H.shape + (3,), np.float32)
    tint = np.array([0.97, 0.98, 1.0])
    shade = 0.35 + 0.65 * diff
    lum = alu * shade * (1 - 0.55 * shadow) + 0.35 * spec
    col[:] = lum[..., None] * tint
    if painted:
        # vertiefte Flächen schwarz lackiert (wie das Schwarz im Aufnäher)
        paint = 0.07 * shade * (1 - 0.5 * shadow) + 0.10 * spec
        col[base_mask] = (paint[..., None] * np.array([1, 1, 1.05]))[base_mask]
    else:
        # gefräster Taschengrund etwas matter/dunkler
        floor = (0.55 + 0.03 * noise) * shade * (1 - 0.6 * shadow) + 0.15 * spec
        col[base_mask] = (floor[..., None] * tint)[base_mask]
    # Hintergrund + weicher Bodenschatten
    drop = ndimage.gaussian_filter(np.roll(np.roll(o, int(2.5 * ppm), 0), int(2.5 * ppm), 1), 3 * ppm)
    bgc = np.array(bg)[None, None, :] * (1 - 0.35 * drop[..., None])
    a = np.clip(o, 0, 1)[..., None]
    out = col * a + bgc * (1 - a)
    out = np.clip(out, 0, 1)
    cv2.imwrite(path, (out[..., ::-1] * 255).astype(np.uint8))


def render_drawing(outline, raised, parts, params, path, mach=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.plotting import plot_polygon

    minx, miny, maxx, maxy = outline.bounds
    W, H = maxx - minx, maxy - miny
    fig = plt.figure(figsize=(8.27, 11.69))  # A4 hoch
    ax = fig.add_axes([0.08, 0.17, 0.84, 0.76])
    plot_polygon(outline.difference(raised), ax=ax, facecolor="#2a2a2a", edgecolor="none", add_points=False)
    plot_polygon(raised, ax=ax, facecolor="#d6d6d6", edgecolor="#0057b8", linewidth=0.25, add_points=False)
    xs, ys = outline.exterior.xy
    ax.plot(xs, ys, color="#e00000", lw=0.8)
    # Maßketten
    kw = dict(arrowstyle="<->", color="k", lw=0.7, shrinkA=0, shrinkB=0)
    ax.annotate("", (minx, miny - 10), (maxx, miny - 10), arrowprops=kw)
    ax.text((minx + maxx) / 2, miny - 16, f"{W:.1f} mm", ha="center", va="top", fontsize=9)
    ax.annotate("", (maxx + 10, miny), (maxx + 10, maxy), arrowprops=kw)
    ax.text(maxx + 13, (miny + maxy) / 2, f"{H:.1f} mm", rotation=90, ha="left", va="center", fontsize=9)
    for q in parts:
        x0, y0, x1, y1 = q.outline.bounds
        ax.annotate("", (minx - 8, y0), (minx - 8, y1), arrowprops=dict(arrowstyle="|-|", color="#666",
                                                                        lw=0.5, mutation_scale=3))
        ax.text(minx - 11, (y0 + y1) / 2, f"{q.name}\n{x1 - x0:.0f}×{y1 - y0:.0f}", rotation=90,
                ha="right", va="center", fontsize=6, color="#444")
    ax.set_xlim(minx - 30, maxx + 25)
    ax.set_ylim(miny - 25, maxy + 8)
    ax.set_aspect("equal")
    ax.axis("off")
    p = params
    fig.text(0.08, 0.955, "Abschiedsgeschenk Ali Ihsan Yavuz – 2D-Fräsvorlage (Maße in mm)",
             fontsize=11, weight="bold")
    legend = [
        ("#e00000", f"Außenkontur – durchfräsen ({p['thickness']:.1f} mm), Haltestege setzen"),
        ("#d6d6d6", f"Erhaben – bleibt auf voller Stärke {p['thickness']:.1f} mm"),
        ("#2a2a2a", f"Vertieft – Tasche {p['relief_depth']:.1f} mm tief (Boden bei "
                    f"{p['thickness'] - p['relief_depth']:.1f} mm), optional schwarz lackieren"),
    ]
    y = 0.135
    for c, t in legend:
        fig.patches.append(plt.Rectangle((0.08, y - 0.004), 0.025, 0.012, color=c, transform=fig.transFigure,
                                         figure=fig))
        fig.text(0.115, y, t, fontsize=8, va="bottom")
        y -= 0.022
    if mach:
        fig.text(0.08, y - 0.005,
                 f"Engster schwarzer Spalt: {mach['min_spalt_zwischen_inseln_mm']:.2f} mm  ·  "
                 f"schmalster Rand zur Kontur: {mach['min_rand_zur_aussenkontur_mm']:.2f} mm  ·  "
                 f"dünnste vertiefte Schrift: {mach['duennste_vertiefte_schrift_mm']:.2f} mm",
                 fontsize=7, color="#444")
        y -= 0.016
        fig.text(0.08, y - 0.005, "→ Taschen: Schruppen z. B. Ø3–4 mm, Restmaterial mit Ø1,0-mm-Fräser; "
                 "Innenecken erhalten dabei r = 0,5 mm (gewollt).", fontsize=7, color="#444")
        y -= 0.018
    fig.text(0.08, y - 0.01, f"Material: Aluminium-Platte ≥ {p['thickness']:.0f} mm. "
             "Haltestege beim Konturschnitt setzen, danach versäubern.", fontsize=7, color="#444")
    fig.savefig(path, dpi=200)
    plt.close(fig)
