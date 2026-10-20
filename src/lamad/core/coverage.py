"""Face coverage: which reference faces a reconstruction does, and does not, reproduce.

Every face on one side is sampled on its trimmed surface and each sample is
measured to the closest point on the other side's tessellation. A face is
`matched` when the 95th percentile of those distances is within the
tolerance, so a chamfer the script forgot, or a recess floor at the wrong
height, is reported as one unmatched face with its analytic parameters
instead of hundreds of indistinguishable face records.

A side is either a bare TopoDS_Shape (face ids f1..fN, as `re det faces`
numbers them) or a list of parts `{"id", "name", "shape"[, "faces"]}` (face
ids `<part id>:f<i>`, as `re inspect` numbers them; `faces` restricts which
of the part's faces are tested while ids still index the whole part).
OCP imports stay inside this module.
"""

import math

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher
from OCP.gp import gp_Pnt2d

from lamad.core.inspection import face_report, shapes
from lamad.core.runner import _compound

MIN_SAMPLES, MAX_SAMPLES = 8, 200
AREA_PER_SAMPLE = 4.0      # mm^2 per sample between the floor and the cap
CLASSIFIER_TOL = 1e-6      # 2D tolerance for the inside-face test
# The other side is tessellated finer than the tolerance so chordal error on
# curved faces cannot by itself push a true match over the threshold.
MESH_DIVISOR, MESH_MAX_MM, MESH_MIN_MM, MESH_ANGULAR = 5.0, 0.05, 1e-4, 0.2


def labeled_faces(side):
    """[(face id, part name or None, TopoDS_Face)] for a shape or a list of parts."""
    if isinstance(side, list):
        items = []
        for part in side:
            table = IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()
            TopExp.MapShapes_s(part["shape"], TopAbs_FACE, table)
            faces = part["faces"] if "faces" in part else shapes(part["shape"], TopAbs_FACE)
            for face in faces:
                items.append((f"{part['id']}:f{table.FindIndex(face)}", part.get("name"), face))
        return items
    return [(f"f{i}", None, face) for i, face in enumerate(shapes(side, TopAbs_FACE), start=1)]


def sample_count(area, samples_per_face=None):
    if samples_per_face is not None:
        return max(1, int(samples_per_face))
    return int(min(MAX_SAMPLES, max(MIN_SAMPLES, round(area / AREA_PER_SAMPLE))))


def sample_face(face, count):
    """`count`-ish points on the trimmed face, uniform in UV; (N, 3) array.

    Cell centres of a UV grid are kept when they classify inside the face's
    wires, so holes and trimmed corners are never sampled. Heavily trimmed
    faces refine the grid until enough points land inside; a sliver that
    still yields nothing is represented by its UV-centre point.
    """
    face = TopoDS.Face(face)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    surface = BRepAdaptor_Surface(face, True)
    classifier = BRepClass_FaceClassifier()
    k = max(2, math.ceil(math.sqrt(count)))
    for _ in range(4):
        inside = []
        for i in range(k):
            u = u0 + (u1 - u0) * (i + 0.5) / k
            for j in range(k):
                v = v0 + (v1 - v0) * (j + 0.5) / k
                classifier.Perform(face, gp_Pnt2d(u, v), CLASSIFIER_TOL)
                if classifier.State() == TopAbs_IN:
                    p = surface.Value(u, v)
                    inside.append((p.X(), p.Y(), p.Z()))
        if len(inside) >= max(3, count // 2):
            break
        k *= 2
    if not inside:
        p = surface.Value((u0 + u1) / 2, (v0 + v1) / 2)
        inside.append((p.X(), p.Y(), p.Z()))
    return np.array(inside, dtype=float)


def target_mesh(faces, tol):
    """Tessellate the faces of one side once, finer than `tol`, for proximity queries."""
    from lamad.core.mesh_compare import body_mesh
    deflection = min(MESH_MAX_MM, max(MESH_MIN_MM, tol / MESH_DIVISOR))
    return body_mesh(_compound([f for _, _, f in faces]), deflection, MESH_ANGULAR)


def cover(faces, mesh, tol, samples_per_face=None):
    """Coverage of `faces` (from labeled_faces) against a trimesh.Trimesh target."""
    import trimesh
    reports, points, owners = [], [], []
    for index, (fid, part, face) in enumerate(faces):
        report = face_report(face, fid)
        report.pop("uv_bounds", None)
        report["part"] = part
        sampled = sample_face(face, sample_count(report["area"], samples_per_face))
        report["samples"] = len(sampled)
        reports.append(report)
        points.append(sampled)
        owners.append(np.full(len(sampled), index))
    if not reports:
        return {"faces_total": 0, "matched": 0, "unmatched_count": 0,
                "area_total": 0.0, "area_matched_fraction": None, "unmatched": []}
    all_points, all_owners = np.concatenate(points), np.concatenate(owners)
    _, distances, _ = trimesh.proximity.closest_point(mesh, all_points)
    matched_area, total_area, unmatched = 0.0, 0.0, []
    for index, report in enumerate(reports):
        d = distances[all_owners == index]
        p95 = float(np.quantile(d, 0.95))
        total_area += report["area"]
        if p95 <= tol:
            matched_area += report["area"]
            continue
        report["distance"] = {"mean": round(float(d.mean()), 6), "p95": round(p95, 6),
                              "max": round(float(d.max()), 6)}
        unmatched.append(report)
    unmatched.sort(key=lambda r: -r["area"])
    return {"faces_total": len(reports), "matched": len(reports) - len(unmatched),
            "unmatched_count": len(unmatched), "area_total": round(total_area, 7),
            "area_matched_fraction": round(matched_area / total_area, 7) if total_area else None,
            "unmatched": unmatched}


def face_coverage(reference, reconstruction, tol, samples_per_face=None):
    """Both directions: reference faces against the reconstruction and vice versa.

    `reference` and `reconstruction` are each a TopoDS_Shape or a list of parts
    (see the module docstring). Returns the `coverage` report section.
    """
    ref_faces, rec_faces = labeled_faces(reference), labeled_faces(reconstruction)
    ref_mesh, rec_mesh = target_mesh(ref_faces, tol), target_mesh(rec_faces, tol)
    return {"tol_mm": tol,
            "criterion": "a face is matched when the 95th percentile of its sampled "
                         "point-to-surface distances is within tol_mm",
            "samples_per_face": samples_per_face or f"{MIN_SAMPLES}..{MAX_SAMPLES} by area",
            "reference": cover(ref_faces, rec_mesh, tol, samples_per_face),
            "reconstruction": cover(rec_faces, ref_mesh, tol, samples_per_face),
            "notes": ["unmatched faces are sorted by area, largest first.",
                      "Face ids follow `re inspect` (<part>:f<i>) when the side has parts, else "
                      "`re det faces` (f<i>); reconstruction parts are numbered in show_object order.",
                      "Distances are to the other side's tessellation (deflection well below tol_mm), "
                      "so a matched face still carries sub-tolerance chordal noise."]}


def mesh_coverage(reconstruction, mesh, tol, samples_per_face=None):
    """Mesh mode: reconstruction faces against a reference triangle mesh only."""
    rec_faces = labeled_faces(reconstruction)
    return {"tol_mm": tol,
            "criterion": "a face is matched when the 95th percentile of its sampled "
                         "point-to-mesh distances is within tol_mm",
            "samples_per_face": samples_per_face or f"{MIN_SAMPLES}..{MAX_SAMPLES} by area",
            "reference": None,
            "reconstruction": cover(rec_faces, mesh, tol, samples_per_face),
            "notes": ["Mesh mode covers the reconstruction side only: an STL has no faces to list.",
                      "Distances include the STL's own chordal error, so curved faces need "
                      "tol_mm above the STL's export deflection to match.",
                      "unmatched faces are sorted by area, largest first."]}
