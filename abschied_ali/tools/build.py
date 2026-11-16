"""Baut alle Ausgabedateien.  Aufruf (aus dem Ordner abschied_ali):  python3 tools/build.py"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from design import build, PARAMS  # noqa: E402
from export import (write_svg, write_dxf, build_manifold, write_stl, write_step,  # noqa: E402
                    machinability_report)
from render import render_metal, render_drawing  # noqa: E402

OUT = "output"
NAME = "Abschied_Ali"


def main(skip_step=False):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    r = build(PARAMS)
    outline, raised, parts, p = r["outline"], r["raised"], r["parts"], r["params"]
    minx, miny, maxx, maxy = outline.bounds
    print(f"Geometrie: {maxx - minx:.1f} x {maxy - miny:.1f} mm  ({time.time() - t0:.1f}s)")

    mach = machinability_report(outline, raised)
    print("Fräsbarkeit:", mach)

    info = [
        f"Abschiedsgeschenk Ali Ihsan Yavuz - Masse {maxx - minx:.1f} x {maxy - miny:.1f} mm",
        f"Staerke {p['thickness']} mm, Relief/Taschentiefe {p['relief_depth']} mm",
        "KONTUR_DURCH = durchfraesen | ERHABEN_INSELN = volle Staerke | TASCHE_GRENZE = Tasche",
    ]
    write_svg(f"{OUT}/{NAME}_2D.svg", outline, raised, title=info[0])
    write_dxf(f"{OUT}/{NAME}_2D.dxf", outline, raised, info)
    print("SVG/DXF ok")

    man = build_manifold(outline, raised, p["thickness"], p["relief_depth"])
    tm = write_stl(f"{OUT}/{NAME}_3D.stl", man)
    vol_cm3 = tm.volume / 1000
    print(f"STL ok: watertight={tm.is_watertight}, Volumen={vol_cm3:.1f} cm³, "
          f"Masse Alu≈{vol_cm3 * 2.7:.0f} g")

    if not skip_step:
        t = time.time()
        write_step(f"{OUT}/{NAME}_3D.step", outline, raised, p["thickness"], p["relief_depth"])
        print(f"STEP ok ({time.time() - t:.1f}s)")

    render_metal(outline, raised, p["thickness"], p["relief_depth"],
                 f"{OUT}/Vorschau_Alu_lackiert.png", painted=True)
    render_metal(outline, raised, p["thickness"], p["relief_depth"],
                 f"{OUT}/Vorschau_Alu_roh.png", painted=False)
    render_drawing(outline, raised, parts, p, f"{OUT}/{NAME}_2D_Zeichnung.png", mach=mach)
    render_drawing(outline, raised, parts, p, f"{OUT}/{NAME}_2D_Zeichnung.pdf", mach=mach)
    print("Vorschauen ok")

    stats = dict(
        breite_mm=round(maxx - minx, 1), hoehe_mm=round(maxy - miny, 1),
        staerke_mm=p["thickness"], relief_mm=p["relief_depth"],
        volumen_cm3=round(vol_cm3, 1), masse_alu_g=round(vol_cm3 * 2.7),
        stl_watertight=bool(tm.is_watertight),
        fraesbarkeit=mach,
        bauteile={q.name: [round(v, 1) for v in q.outline.bounds] for q in parts},
        params={k: v for k, v in p.items() if k != "name_font"},
    )
    with open(f"{OUT}/kennwerte.json", "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main(skip_step="--no-step" in sys.argv)
