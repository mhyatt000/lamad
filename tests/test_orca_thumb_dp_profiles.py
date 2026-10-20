"""Mechanical sketch constraints of the thumb distal paddle, without sources."""
import builtins
import importlib
from math import sqrt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
model = importlib.import_module("part.finger_l_t_dp")


class ThumbDPProfileTests(unittest.TestCase):
    def test_source_free_compact_profiles(self):
        p = model._parameters()
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            profiles = [model._side_profile(p),model._width_profile(p),model._roof_profile(p)]
        for profile in profiles:
            self.assertTrue(profile.is_valid)
            self.assertLess(len(profile.edges()),15)

    def test_rear_quadratic_is_tangent_to_joint_circle(self):
        points = model.REAR_CONTROLS
        self.assertEqual(len(points),3)
        self.assertAlmostEqual(sqrt(sum(x*x for x in points[0])),8)
        tangent = tuple(points[1][i]-points[0][i] for i in (0,1))
        self.assertAlmostEqual(sum(points[0][i]*tangent[i] for i in (0,1)),0,places=6)

    def test_paddle_turns_derive_from_slope_and_thickness(self):
        for thickness in (2,2.25):
            p = model._parameters({"paddle_thickness":thickness})
            lower,upper = model._paddle_centers(p)
            self.assertAlmostEqual(upper[0]+p["paddle_turn_radius"],model.FRONT-thickness)
            self.assertAlmostEqual((upper[0]-lower[0])/(upper[1]-lower[1]),p["paddle_slope"])
            self.assertAlmostEqual(lower[1]-p["paddle_turn_radius"],model.REAR_CONTROLS[-1][1])

    def test_height_edit_moves_roof_not_joint_or_rear_support(self):
        p = model._parameters()
        taller = model._parameters({"paddle_height":p["paddle_height"]+2})
        self.assertEqual(model._paddle_centers(p),model._paddle_centers(taller))
        for params in (p,taller):
            roof = model._roof_profile(params)
            self.assertAlmostEqual(roof.bounding_box().max.Z,params["paddle_height"],places=5)
            circles = [e for e in roof.edges() if e.geom_type.name=="CIRCLE"]
            self.assertEqual(len(circles),1)
            self.assertAlmostEqual(circles[0].radius,params["roof_radius"])

    def test_invalid_parameters_fail_explicitly(self):
        for p in ({"paddle_height":20},{"roof_radius":6},{"paddle_width":8},
                  {"paddle_thickness":.5},{"axle_radius":1},{"scale_z":2}):
            with self.assertRaises(ValueError):
                model._parameters(p)


if __name__=="__main__":
    unittest.main()
