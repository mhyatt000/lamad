"""Analytical DP envelope, mounting features, and printable export regressions."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from lamad.core.mesh_compare import body_mesh

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
recipe = importlib.import_module("part.finger_dp")


class AnalyticalDPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            cls.stages = recipe.stages()
        cls.body = cls.stages["transverse_retention_bore"]

    def test_registered_source_free_valid_body(self):
        registry = importlib.import_module("part.orca_fingers__dp")
        self.assertIs(registry.build,recipe.build)
        for body in self.stages.values():
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)

    def test_mechanical_envelope_bounds(self):
        b = self.body.bounding_box()
        self.assertAlmostEqual(b.min.X,-25,places=5)
        self.assertAlmostEqual(b.max.X,7.64254475,places=5)
        self.assertAlmostEqual(b.min.Y,-5.1256729292,places=5)
        self.assertAlmostEqual(b.max.Y,5.1256729292,places=5)
        self.assertAlmostEqual(b.min.Z,0,places=5)
        self.assertAlmostEqual(b.max.Z,13,places=5)
        self.assertTrue(self.body.is_inside((-23,1,6.5)))
        self.assertFalse(self.body.is_inside((-23,-1,6.5)))
        self.assertTrue(self.body.is_inside((-5,0,6.5)))

    def test_round_before_spine_feature_sequence(self):
        names = list(self.stages)
        self.assertLess(names.index("rounded_lower_side_and_restored_spine"),
                        names.index("rounded_upper_side"))
        self.assertLess(names.index("rounded_rear_cap"),names.index("rounded_mounting_tongue"))
        self.assertLess(self.stages["rounded_rear_cap"].volume,
                        self.stages["intersected_profile_envelope"].volume)

    def test_export_fine_enough_without_repairs(self):
        mesh = body_mesh(self.body,recipe.TESSELLATION_MM,recipe.ANGULAR_TOLERANCE_RAD)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)
        self.assertEqual(mesh.metadata["degenerate_triangles_removed"],0)
        self.assertLess(abs(mesh.volume-self.body.volume),.04)

    def test_representative_mechanical_edits(self):
        for params in ({"bore_radius":1.,"tongue_length":8.5},
                       {"height":14},{"tongue_width":4.2}):
            body = recipe.build(params)
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)
            self.assertTrue(body_mesh(body,.001,.05).is_volume)
        taller = recipe.build({"height":14})
        self.assertAlmostEqual(taller.bounding_box().max.Z,14,places=5)

    def test_actual_sketches_and_display_only_guides(self):
        profiles,guides = recipe.sketches(),recipe.construction()
        self.assertEqual(len(profiles),3)
        for name,profile in profiles.items():
            self.assertTrue(profile.is_valid,name)
        self.assertEqual(set(guides),{"pad_outline_XY","pad_thickness_XZ"})
        self.assertTrue(all(not guide.solids() for guide in guides.values()))


if __name__ == "__main__":
    unittest.main()
