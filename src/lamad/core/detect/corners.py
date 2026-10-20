"""Sharp edges and corner vertices from face-to-face dihedral angles.

Convention (material-side interior angle)
-----------------------------------------
For each edge shared by two faces we take the edge midpoint, the *outward*
unit normals n_a, n_b of both faces there (surface normal flipped for
REVERSED faces, so it points out of the solid), and the edge tangent as it is
oriented inside each face. In OCCT the face interior lies to the left of an
edge when viewed from the outward normal, so `n x t` points into the face.
Moving a small step into face B and measuring that step against n_a tells on
which side of face A's tangent plane the neighbor lies:

* below  (negative)  -> `convex`:  the material wedge is narrower than a
  half-space; `angle` < 180, e.g. 90 for a box edge, 135 for a 45 deg chamfer.
* above  (positive)  -> `concave`: `angle` > 180, e.g. 270 where a boss
  meets the face it stands on, or the floor of a blind pocket.
* tangent            -> `angle` == 180 (fillets); never sharp.

`angle` is therefore the dihedral angle measured through the material, and
`normal_angle` = |180 - angle| is the angle between the two outward normals.
An edge is *sharp* when `normal_angle` > `angle_tol` (degrees).

Note that the rim of a through-hole (top plane meets hole wall) is **convex**
by this convention, exactly like the outer edges of the box: the material
wedge there is 90 degrees. Concave edges only appear where material is added
on top of a face (bosses, ribs) or at the bottom of pockets and blind holes.

Seam edges (same face on both sides) and edges with fewer than two faces are
reported with `angle: null` and are never sharp.
"""

import math

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d, BRepAdaptor_Surface
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt, gp_Vec

from lamad.core.detect import DEFAULT_ANGLE_TOL
from lamad.core.detect.common import entries, ident, indexed, rounded, xyz


def _unit(v):
    n = v.Magnitude()
    return v if n < 1e-12 else gp_Vec(v.X() / n, v.Y() / n, v.Z() / n)


def _outward_normal(face, u, v):
    """Outward unit normal of `face` at surface parameters (u, v), or None."""
    props = BRepLProp_SLProps(BRepAdaptor_Surface(face, False), u, v, 1, 1e-7)
    if not props.IsNormalDefined():
        return None
    d = props.Normal()
    n = gp_Vec(d.X(), d.Y(), d.Z())
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return n


def _side(edge_in_face, face):
    """(point, outward normal, inward tangent-plane direction) at the edge midpoint.

    `edge_in_face` must carry the orientation it has inside `face` (as yielded
    by TopExp_Explorer on the face), so the tangent follows the face's loop.
    """
    curve = BRepAdaptor_Curve(edge_in_face)
    t = (curve.FirstParameter() + curve.LastParameter()) / 2
    point, tangent = gp_Pnt(), gp_Vec()
    curve.D1(t, point, tangent)
    if edge_in_face.Orientation() == TopAbs_REVERSED:
        tangent.Reverse()
    pcurve = BRepAdaptor_Curve2d(edge_in_face, face)
    t2 = (pcurve.FirstParameter() + pcurve.LastParameter()) / 2
    uv = pcurve.Value(t2)
    normal = _outward_normal(face, uv.X(), uv.Y())
    if normal is None:
        return None
    return point, _unit(normal), _unit(normal.Crossed(_unit(tangent)))


def _owners(shape, edge_table):
    """edge index -> list of (face index, face, edge as oriented in that face)."""
    face_table = indexed(shape, TopAbs_FACE)
    owners = {}
    for fi, face in enumerate(entries(face_table), start=1):
        face = TopoDS.Face(face)
        explorer = TopExp_Explorer(face, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge(explorer.Current())
            owners.setdefault(edge_table.FindIndex(edge), []).append((fi, face, edge))
            explorer.Next()
    return owners


def dihedral(owners_of_edge):
    """(interior angle in degrees, 'convex'|'concave'|'tangent') or (None, reason)."""
    if len(owners_of_edge) < 2:
        return None, "open"
    (fa, face_a, edge_a), (fb, face_b, edge_b) = owners_of_edge[:2]
    if face_a.IsSame(face_b):
        return None, "seam"
    side_a, side_b = _side(edge_a, face_a), _side(edge_b, face_b)
    if side_a is None or side_b is None:
        return None, "singular"
    _, n_a, into_a = side_a
    _, n_b, into_b = side_b
    cos = max(-1.0, min(1.0, n_a.Dot(n_b)))
    between = math.degrees(math.acos(cos))
    # Step into B and look along A's outward normal (and the symmetric test).
    side = into_b.Dot(n_a) + into_a.Dot(n_b)
    if between < 1e-6:
        return 180.0, "tangent"
    if side < 0:
        return 180.0 - between, "convex"
    return 180.0 + between, "concave"


def detect_corners(shape, angle_tol=DEFAULT_ANGLE_TOL):
    """Returns (summary, sharp_edges, corners).

    sharp_edges: edges whose outward normals differ by more than `angle_tol`
    degrees, each with interior `angle`, `normal_angle`, `convexity`, and the
    two adjacent face ids. corners: vertices where >= 3 sharp edges meet.
    """
    edge_table = indexed(shape, TopAbs_EDGE)
    owners = _owners(shape, edge_table)
    sharp = []
    for i in range(1, edge_table.Extent() + 1):
        edge = TopoDS.Edge(edge_table.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        angle, kind = dihedral(owners.get(i, []))
        if angle is None:
            continue
        normal_angle = abs(180.0 - angle)
        if normal_angle > angle_tol:
            faces = [ident(TopAbs_FACE, fi) for fi, _, _ in owners[i][:2]]
            curve = BRepAdaptor_Curve(edge)
            mid = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
            sharp.append({"id": ident(TopAbs_EDGE, i), "angle": rounded(angle),
                          "normal_angle": rounded(normal_angle), "convexity": kind,
                          "faces": faces, "midpoint": xyz(mid)})
    sharp_ids = {e["id"] for e in sharp}
    corners = []
    vertex_table = indexed(shape, TopAbs_VERTEX)
    incident = {}
    for i in range(1, edge_table.Extent() + 1):
        eid = ident(TopAbs_EDGE, i)
        if eid not in sharp_ids:
            continue
        explorer = TopExp_Explorer(edge_table.FindKey(i), TopAbs_VERTEX)
        while explorer.More():
            incident.setdefault(vertex_table.FindIndex(explorer.Current()), set()).add(eid)
            explorer.Next()
    for vi in sorted(incident):
        ids = sorted(incident[vi], key=lambda s: int(s[1:]))
        if len(ids) >= 3:
            vertex = TopoDS.Vertex(vertex_table.FindKey(vi))
            corners.append({"id": ident(TopAbs_VERTEX, vi), "position": xyz(BRep_Tool.Pnt_s(vertex)),
                            "sharp_edges": ids, "sharp_edge_count": len(ids)})
    summary = {"angle_tol_degrees": angle_tol, "edges_total": edge_table.Extent(),
               "sharp_edges": len(sharp),
               "convex": sum(1 for e in sharp if e["convexity"] == "convex"),
               "concave": sum(1 for e in sharp if e["convexity"] == "concave"),
               "vertices_total": vertex_table.Extent(), "corners": len(corners)}
    return summary, sharp, corners
