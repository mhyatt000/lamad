"""Native measured-body behavior and independent mesh difference checks."""

import unittest
from unittest.mock import patch
import numpy as np
from build123d import Cylinder
from OCP.BRepMesh import BRepMesh_IncrementalMesh

try:
    import trimesh
except ImportError:  # the reverse-engineering extra is optional
    raise unittest.SkipTest("requires trimesh (uv sync --extra reverse-engineering)")

from lamad.core.mesh_native import boundary_body
from lamad.core.mesh_compare import body_mesh, compare_meshes

try:  # trimesh's closest-point queries need the rtree extra as well
    import rtree  # noqa: F401
    HAS_RTREE = True
except ImportError:
    HAS_RTREE = False
needs_rtree = unittest.skipUnless(HAS_RTREE, "requires rtree (uv sync --extra reverse-engineering)")


class NativeBoundaryTests(unittest.TestCase):
    def test_body_mesh_passes_explicit_absolute_deflection_settings(self):
        source = trimesh.creation.box()
        with patch("lamad.core.mesh_compare.tessellate", return_value=(source.vertices, source.faces)) as mesh:
            native = object()
            result = body_mesh(native, .002, .05)
            mesh.assert_called_once_with(native, .002, .05)
            self.assertAlmostEqual(result.volume, 1)
        body = Cylinder(2, 4)
        with patch("lamad.core.viewer.BRepMesh_IncrementalMesh", wraps=BRepMesh_IncrementalMesh) as native_mesh:
            result = body_mesh(body, .002, .05)
            args = native_mesh.call_args.args
            self.assertEqual(args[1:], (.002, False, .05, True))
            self.assertTrue(result.is_watertight)

    @needs_rtree
    def test_sample_report_localizes_the_reported_maximum(self):
        source = trimesh.creation.box(extents=(10, 10, 10))
        shifted = source.copy()
        shifted.apply_translation((2, 0, 0))
        report = compare_meshes(source, shifted, samples=200)
        for direction in ("reference_to_generated", "generated_to_reference"):
            result = report[direction]
            delta = np.asarray(result["max_sampled_point_mm"]) - result["closest_point_mm"]
            self.assertAlmostEqual(np.linalg.norm(delta), result["max_sampled_mm"])
            self.assertAlmostEqual(result["max_sampled_mm"], 2)

    def test_exact_collapsed_triangles_are_removed_without_changing_volume(self):
        source = trimesh.creation.box()
        faces = np.vstack([source.faces, [0, 0, 1]])
        with patch("lamad.core.mesh_compare.tessellate", return_value=(source.vertices, faces)):
            result = body_mesh(object())
        self.assertTrue(result.is_watertight)
        self.assertAlmostEqual(result.volume, source.volume)
        self.assertEqual(len(result.faces), len(source.faces))
        self.assertEqual(result.metadata["degenerate_triangles_removed"], 1)

    @needs_rtree
    def test_native_solid_accepts_real_boolean_edits(self):
        source = trimesh.creation.box(extents=(10, 10, 10))
        data = {"components": [{"vertices": source.vertices.tolist(), "triangles": source.faces.tolist()}]}
        body = boundary_body(data)
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()), 1)
        report = compare_meshes(source, body_mesh(body), samples=200)
        self.assertAlmostEqual(report["relative_symmetric_difference"], 0)
        cut = body - Cylinder(2, 20)
        self.assertTrue(cut.is_valid)
        self.assertLess(cut.volume, body.volume)
        report = compare_meshes(source, body_mesh(cut), samples=200)
        self.assertGreater(report["missing_volume_mm3"], 120)
        self.assertLess(report["extra_volume_mm3"], 1e-5)

    def test_scaling_is_validated_and_geometric(self):
        source = trimesh.creation.box(extents=(2, 3, 4))
        data = {"components": [{"vertices": source.vertices.tolist(), "triangles": source.faces.tolist()}]}
        body = boundary_body(data, scale=(2, 1, 1))
        self.assertAlmostEqual(body.volume, 48)
        self.assertAlmostEqual(body.bounding_box().size.X, 4)
        for scale in ((0, 1, 1), (-1, 1, 1), (float("nan"), 1, 1)):
            with self.assertRaises(ValueError):
                boundary_body(data, scale=scale)


if __name__ == "__main__":
    unittest.main()
