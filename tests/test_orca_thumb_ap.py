"""Whole-recipe checks: thumb interfaces, handedness and real parameter edits."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import Axis, Vector
from lamad.core.mesh_compare import body_mesh

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
left = importlib.import_module("part.finger_l_t_ap")
right = importlib.import_module("part.finger_r_t_ap")


class ThumbAPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Installed fonts are an explicit engraving dependency; initialize
        # their registry before forbidding all geometry/reference file access.
        left._label_profile(left._parameters())
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            cls.stages = left.stages()
        cls.body = list(cls.stages.values())[-1]

    def test_source_free_valid_body_and_monotonic_cam_cuts(self):
        for side,recipe in (("l",left),("r",right)):
            canonical = importlib.import_module(f"part.orca_fingers__{side}_t_ap")
            self.assertIs(canonical.build,recipe.build)
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()),1)
        previous = self.stages["rounded_conical_nose_relief"].volume
        for name,shape in self.stages.items():
            if name.startswith("cam_"):
                self.assertTrue(shape.is_valid)
                self.assertEqual(len(shape.solids()),1)
                self.assertLess(shape.volume,previous)
                previous = shape.volume
        self.assertLess(self.body.volume,previous)

    def test_keyed_axle_and_half_mm_tip_joins(self):
        local = self.body.rotate(Axis.X,-20)
        self.assertTrue(local.is_inside((30,0,10)))
        self.assertFalse(local.is_inside((32,0,10)))
        self.assertFalse(local.is_inside((30,0,11)))
        # Independent exact native-cylinder check, not a sampled mesh target.
        for y,z in ((3.665617006,6.555317487),(-3.665617006,7.111619108)):
            self.assertLess(local.shells()[0].distance_to(Vector(30.423463134,y,z)),1e-6)

    def test_rounded_pocket_does_not_block_lower_exit_window(self):
        local = self.body.rotate(Axis.X,-20)
        for side in (-1,1):
            self.assertFalse(local.is_inside((31.18,side*7.30,-2)))
            self.assertTrue(local.is_inside((21.43334,side*4.12048,4)))

    def test_fine_absolute_export_is_closed_without_hole_filling(self):
        mesh = body_mesh(self.body,left.TESSELLATION_MM,left.ANGULAR_TOLERANCE_RAD)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)
        self.assertLess(abs(mesh.volume-self.body.volume),.1)

    def test_right_mechanics_mirror_without_mirrored_lettering(self):
        body = right.build()
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()),1)
        for point in ((30,0,10),(31.18,7.30,-2),(31.18,-7.30,-2)):
            self.assertEqual(self.body.rotate(Axis.X,-20).is_inside(point),
                             body.rotate(Axis.X,20).is_inside((point[0],-point[1],point[2])))
        self.assertNotAlmostEqual(body.volume,self.body.volume,places=2)

    def test_spacing_edit_moves_axle_without_scaling_its_section(self):
        body = left.build({"joint_spacing":32})
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()),1)
        local = body.rotate(Axis.X,-20)
        self.assertTrue(local.is_inside((32,0,10)))
        self.assertFalse(local.is_inside((30,0,10)))
        self.assertFalse(local.is_inside((34,0,10)))

    def test_twist_edit_preserves_keyed_distal_interface(self):
        body = left.build({"twist_angle":25})
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()),1)
        local = body.rotate(Axis.X,-25)
        self.assertTrue(local.is_inside((30,0,10)))
        self.assertFalse(local.is_inside((32,0,10)))


if __name__=="__main__":
    unittest.main()
