"""Source-free full thumb paddles, semantic finishing and real edits."""
import builtins
import importlib
from math import sqrt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import Vector
from lamad.core.mesh_compare import body_mesh

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
left = importlib.import_module("part.finger_l_t_dp")
right = importlib.import_module("part.finger_r_t_dp")
rounds = importlib.import_module("part.finger_thumb_paddle_rounds")


class ThumbDPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        left._label_profile()  # Installed font dependency, not source geometry.
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            cls.stages = left.stages()
        cls.body = list(cls.stages.values())[-1]

    def test_source_free_valid_stages(self):
        for side,recipe in (("l",left),("r",right)):
            self.assertIs(importlib.import_module(f"part.orca_fingers__{side}_t_dp").build,recipe.build)
        for body in self.stages.values():
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)
        self.assertLess(self.stages["variable_perimeter_rounds"].volume,
                        self.stages["front_roof_round"].volume-40)
        previous = self.stages["keyed_proximal_axle"].volume
        for name in ("pulley_groove","chamfered_and_flared_access_port","identification_engraving"):
            self.assertLess(self.stages[name].volume,previous)
            previous = self.stages[name].volume

    def test_keyed_axle_and_thin_paddle(self):
        for y in (-7,7):
            self.assertTrue(self.body.is_inside((0,y,0)))
            self.assertFalse(self.body.is_inside((1.8,y,0)))
            self.assertFalse(self.body.is_inside((0,y,2)))
        self.assertTrue(self.body.is_inside((7,0,28)))
        self.assertFalse(self.body.is_inside((5.5,0,28)))
        self.assertFalse(self.body.is_inside((7,0,31)))

    def test_true_zero_roof_endpoint_is_preserved(self):
        self.assertEqual(rounds.ROOF_RADIUS,0)
        p = left.DEFAULTS
        z = p["paddle_height"]-p["roof_radius"]+sqrt(p["roof_radius"]**2-(p["paddle_width"]/2)**2)
        shell = self.stages["variable_perimeter_rounds"].shells()[0]
        for side in (-1,1):
            self.assertLess(shell.distance_to(Vector(6,side*6.5,z)),1e-6)

    def test_port_cone_slot_intersection_is_sharp_not_ip_round(self):
        # Independent reference vertex on the native cone AND slot plane.
        # The incorrectly borrowed IP R.75 round missed it by .251 mm.
        point = Vector(5.021122,-4.092917,5.382257)
        self.assertLess(self.body.shells()[0].distance_to(point),2e-6)

    def test_fine_absolute_export_is_closed(self):
        mesh = body_mesh(self.body,left.TESSELLATION_MM,left.ANGULAR_TOLERANCE_RAD)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)
        self.assertLess(abs(mesh.volume-self.body.volume),.05)

    def test_mirrored_mechanics_and_fresh_right_label(self):
        stages = right.stages()
        body = list(stages.values())[-1]
        self.assertTrue(body.is_valid)
        self.assertAlmostEqual(stages["chamfered_and_flared_access_port"].volume,
                               self.stages["chamfered_and_flared_access_port"].volume,places=6)
        for point in ((0,-7,0),(1.8,-7,0),(7,0,28),(5.5,0,28),(3,-3,7)):
            self.assertEqual(self.stages["chamfered_and_flared_access_port"].is_inside(point),
                             stages["chamfered_and_flared_access_port"].is_inside((point[0],-point[1],point[2])))
        self.assertNotAlmostEqual(self.body.volume,body.volume,places=2)
        self.assertAlmostEqual(right._label_profile().bounding_box().max.Z,21.4847870523,places=5)

    def test_height_edit_preserves_joint(self):
        body = left.build({"paddle_height":31.2})
        self.assertTrue(body.is_valid)
        self.assertTrue(body.is_inside((0,7,0)))
        self.assertFalse(body.is_inside((1.8,7,0)))
        self.assertGreater(body.bounding_box().max.Z,self.body.bounding_box().max.Z+.4)

    def test_radius_scale_edit_is_a_real_feature_edit(self):
        body = left.build({"perimeter_radius":1.4})
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()),1)
        self.assertGreater(body.volume,self.body.volume+5)
        self.assertTrue(body.is_inside((0,7,0)))


if __name__=="__main__":
    unittest.main()
