"""Export der Geometrie: SVG (2D), DXF (2D, CAM-Layer), STL + STEP (3D)."""
from __future__ import annotations

import numpy as np
import ezdxf
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from vectorize import as_polys


def rings(geom):
    """Alle Ringe als (N,2)-Arrays (offen, ohne doppelten Endpunkt)."""
    out = []
    for p in as_polys(geom):
        out.append(np.asarray(p.exterior.coords)[:-1])
        out += [np.asarray(i.coords)[:-1] for i in p.interiors]
    return out


# --------------------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------------------
def _path_d(geom, ox, oy):
    parts = []
    for r in rings(geom):
        pts = " ".join(f"{x - ox:.3f},{oy - y:.3f}" for x, y in r)
        parts.append(f"M{pts}Z")
    return " ".join(parts)


def write_svg(path, outline, raised, margin=10.0, title=""):
    minx, miny, maxx, maxy = outline.bounds
    W, H = maxx - minx + 2 * margin, maxy - miny + 2 * margin
    ox, oy = minx - margin, maxy + margin
    pocket = outline.difference(raised)
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- {title} | Einheit: mm, Maßstab 1:1 -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.3f} {H:.3f}">
  <g inkscape:groupmode="layer" inkscape:label="TASCHE (vertieft)" id="tasche">
    <path d="{_path_d(pocket, ox, oy)}" fill="#1a1a1a" fill-rule="evenodd" stroke="none"/>
  </g>
  <g inkscape:groupmode="layer" inkscape:label="ERHABEN (volle Stärke)" id="erhaben">
    <path d="{_path_d(raised, ox, oy)}" fill="#c8c8c8" fill-rule="evenodd" stroke="#0057b8" stroke-width="0.15"/>
  </g>
  <g inkscape:groupmode="layer" inkscape:label="KONTUR (durchfräsen)" id="kontur">
    <path d="{_path_d(outline, ox, oy)}" fill="none" stroke="#e00000" stroke-width="0.3"/>
  </g>
</svg>
'''
    with open(path, "w") as f:
        f.write(svg)


# --------------------------------------------------------------------------------------
# DXF
# --------------------------------------------------------------------------------------
def write_dxf(path, outline, raised, info_lines=()):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("KONTUR_DURCH", color=1)       # rot
    doc.layers.add("ERHABEN_INSELN", color=5)     # blau
    doc.layers.add("TASCHE_GRENZE", color=8)      # grau
    doc.layers.add("INFO", color=7)
    for r in rings(outline):
        msp.add_lwpolyline(r.tolist(), close=True, dxfattribs={"layer": "KONTUR_DURCH"})
    for r in rings(raised):
        msp.add_lwpolyline(r.tolist(), close=True, dxfattribs={"layer": "ERHABEN_INSELN"})
    pocket = outline.difference(raised)
    for r in rings(pocket):
        msp.add_lwpolyline(r.tolist(), close=True, dxfattribs={"layer": "TASCHE_GRENZE"})
    minx, miny, maxx, maxy = outline.bounds
    y = miny - 8
    for line in info_lines:
        msp.add_text(line, height=3.0, dxfattribs={"layer": "INFO"}).set_placement((minx, y))
        y -= 5
    doc.saveas(path)


# --------------------------------------------------------------------------------------
# 3D: Manifold (STL)
# --------------------------------------------------------------------------------------
def build_manifold(outline, raised, thickness, relief):
    from manifold3d import CrossSection, FillRule

    def cs(geom):
        return CrossSection([r.tolist() for r in rings(geom)], FillRule.EvenOdd)

    base = cs(outline).extrude(thickness - relief)
    top = cs(raised).extrude(relief).translate([0, 0, thickness - relief])
    return base + top


def write_stl(path, manifold):
    import trimesh
    m = manifold.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(m.vert_properties)[:, :3],
                         faces=np.asarray(m.tri_verts), process=True)
    tm.export(path)
    return tm


# --------------------------------------------------------------------------------------
# 3D: STEP (OpenCascade) – Volumenkörper aus extrudierten Polygonen (Sehnenfehler ≤ tol)
# --------------------------------------------------------------------------------------
def write_step(path, outline, raised, thickness, relief, tol=0.02):
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder

    def wire(ring, z):
        poly = BRepBuilderAPI_MakePolygon()
        for x, y in ring:
            poly.Add(gp_Pnt(float(x), float(y), z))
        poly.Close()
        return poly.Wire()

    def face(p: Polygon, z):
        ext = np.asarray(p.exterior.coords)[:-1]
        if Polygon(ext).exterior.is_ccw is False:
            ext = ext[::-1]
        mf = BRepBuilderAPI_MakeFace(wire(ext, z), True)
        for i in p.interiors:
            r = np.asarray(i.coords)[:-1]
            if Polygon(r).exterior.is_ccw:
                r = r[::-1]
            mf.Add(wire(r, z))
        return mf.Face()

    def prism(geom, z0, h):
        shapes = []
        for p in as_polys(geom.simplify(tol, preserve_topology=True)):
            f = face(p, z0)
            shapes.append(BRepPrimAPI_MakePrism(f, gp_Vec(0, 0, h)).Shape())
        return shapes

    base = prism(outline, 0.0, thickness - relief)
    tops = prism(raised, thickness - relief, relief)
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for t in tops:
        builder.Add(comp, t)
    assert len(base) == 1
    fuse = BRepAlgoAPI_Fuse(base[0], comp)
    if not fuse.IsDone():
        raise RuntimeError("STEP: Boolesche Vereinigung fehlgeschlagen")
    shape = fuse.Shape()
    unify = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    unify.Build()
    shape = unify.Shape()
    fix = ShapeFix_Shape(shape)
    fix.Perform()
    shape = fix.Shape()
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    if w.Write(path) != IFSelect_RetDone:
        raise RuntimeError("STEP-Export fehlgeschlagen")
    return shape


# --------------------------------------------------------------------------------------
# Fräsbarkeits-Check
# --------------------------------------------------------------------------------------
def machinability_report(outline, raised):
    """Engstellen, die den kleinsten nötigen Fräser bestimmen."""
    import shapely
    from shapely.strtree import STRtree
    polys = [g for g in getattr(raised, "geoms", [raised])]
    tree = STRtree(polys)
    min_gap, gap_at = 1e9, None
    for i, a in enumerate(polys):
        for j in tree.query(a.buffer(3.0)):
            j = int(j)
            if j <= i:
                continue
            d = a.distance(polys[j])
            if d < min_gap:
                min_gap = d
                gap_at = shapely.shortest_line(a, polys[j]).centroid
    border = raised.distance(outline.exterior)
    pocket = outline.difference(raised)
    comps = sorted(getattr(pocket, "geoms", [pocket]), key=lambda g: -g.area)
    strokes = [2 * shapely.maximum_inscribed_circle(c, 0.01).length for c in comps[1:]]
    return dict(
        min_spalt_zwischen_inseln_mm=round(min_gap, 2),
        min_spalt_ort_mm=[round(gap_at.x, 1), round(gap_at.y, 1)] if gap_at else None,
        min_rand_zur_aussenkontur_mm=round(border, 2),
        duennste_vertiefte_schrift_mm=round(min(strokes), 2) if strokes else None,
        anzahl_erhabene_inseln=len(polys),
        anzahl_vertiefte_schriftzeichen=len(comps) - 1,
    )
