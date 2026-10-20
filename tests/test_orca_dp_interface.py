"""DP mating features tested independently of the fingertip envelope."""
import builtins
import importlib
from math import cos, sin, radians, pi
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import Solid, Plane

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
recipe = importlib.import_module("part.finger_dp")


class DPInterfaceTests(unittest.TestCase):
    @staticmethod
    def model(params=None):
        p = recipe._parameters(params)
        pad = Solid.make_box(25,10.2513458584,p["height"],
                            Plane(origin=(-25,-5.1256729292,0)))
        return recipe._mounting_stages(p,pad)

    @staticmethod
    def point(u,v,z,angle=25):
        a = radians(angle)
        return (u*cos(a)+v*sin(a),-u*sin(a)+v*cos(a),z)

    def test_source_free_single_solid(self):
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            stages = self.model()
        for body in stages.values():
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)

    def test_bore_is_true_through_cylinder(self):
        stages = self.model()
        before,after = stages.values()
        self.assertAlmostEqual(before.volume-after.volume,pi*.8**2*4,places=6)
        for v in (-1.99,0,1.99):
            self.assertFalse(after.is_inside(self.point(4,v,6.5)))
            self.assertFalse(after.is_inside(self.point(4,v,7.29)))
            self.assertTrue(after.is_inside(self.point(4,v,7.31)))

    def test_tongue_section_and_rounded_tip(self):
        body = list(self.model().values())[-1]
        self.assertTrue(body.is_inside(self.point(5,1.99,3)))
        self.assertFalse(body.is_inside(self.point(5,2.01,3)))
        self.assertFalse(body.is_inside(self.point(5,0,2.49)))
        self.assertTrue(body.is_inside(self.point(7.49,0,6.5)))
        self.assertFalse(body.is_inside(self.point(7.51,0,6.5)))
        self.assertFalse(body.is_inside(self.point(7.4,0,2.6)))

    def test_meaningful_bore_and_tongue_edits(self):
        body = list(self.model({"bore_radius":1.,"tongue_length":8.5}).values())[-1]
        self.assertTrue(body.is_valid)
        self.assertTrue(body.is_inside(self.point(8.49,0,6.5)))
        self.assertFalse(body.is_inside(self.point(4,0,7.49)))
        self.assertTrue(body.is_inside(self.point(4,0,7.51)))

    def test_invalid_parameters(self):
        for params in ({"bore_radius":float("nan")},{"tongue_height":14},
                       {"bore_station":7.4},{"unknown":1}):
            with self.assertRaises(ValueError):
                recipe._parameters(params)


if __name__ == "__main__":
    unittest.main()
