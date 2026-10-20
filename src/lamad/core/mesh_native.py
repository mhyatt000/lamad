"""Native faceted BRep from measured surface coordinates, with no mesh importer.

This preserves a measured boundary; it does not infer the original features.
Faces/edges are real OCCT topology, usable by build123d Boolean and split tools.
"""

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh, BRepBuilderAPI_MakeSolid
from OCP.Poly import Poly_Triangulation, Poly_Triangle
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS_Shell
from OCP.gp import gp_Pnt
from build123d import Compound, Solid

from lamad.core.inspection import shapes


def boundary_body(data, scale=(1, 1, 1), clean=True):
    if any(not np.isfinite(s) or s <= 0 for s in scale):
        raise ValueError("Boundary scales must be finite and positive.")
    solids = []
    cleanup = []
    for component in data["components"]:
        vertices = np.asarray(component["vertices"], dtype=float) * scale
        triangles = np.asarray(component["triangles"], dtype=int)
        mesh = Poly_Triangulation(len(vertices), len(triangles), False)
        for i, point in enumerate(vertices):
            mesh.SetNode(i + 1, gp_Pnt(*point))
        for i, tri in enumerate(triangles):
            mesh.SetTriangle(i + 1, Poly_Triangle(*map(int, tri + 1)))
        faces = BRepBuilderAPI_MakeShapeOnMesh(mesh).Shape()
        builder, shell = BRep_Builder(), TopoDS_Shell()
        builder.MakeShell(shell)
        for face in shapes(faces, TopAbs_FACE):
            builder.Add(shell, face)
        solid = Solid(BRepBuilderAPI_MakeSolid(shell).Solid())
        if not solid.is_valid or solid.volume <= 0:
            raise ValueError("Measured boundary did not create a valid positive-volume solid.")
        accepted = False
        if clean:
            # clean() mutates its wrapper. Keep a distinct wrapper for the raw
            # valid topology: OCCT merging can invalidate intricate trimmed faces.
            try:
                candidate = Solid(solid.wrapped).clean()
                if candidate.is_valid and abs(candidate.volume - solid.volume) <= max(1e-6, solid.volume * 1e-8):
                    solid, accepted = candidate, True
            except Exception:
                pass
        cleanup.append({"requested": clean, "coplanar_merge_accepted": accepted})
        solids.append(solid)
    if not solids:
        raise ValueError("Boundary data contains no solid components.")
    result = solids[0] if len(solids) == 1 else Compound(children=solids)
    result.boundary_cleanup = cleanup
    return result
