"""Independent mathematical checks of the thumb rolling-ball construction."""
import builtins
import importlib
from math import sqrt,sin,cos,radians
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import Vector
from OCP.BRepAdaptor import BRepAdaptor_Curve

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
nose = importlib.import_module("part.finger_thumb_nose")
recipe = importlib.import_module("part.finger_l_t_ap")


class ThumbNoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            cls.tool = nose.relief(recipe._parameters())

    def test_source_free_valid_single_solid(self):
        self.assertTrue(self.tool.is_valid)
        self.assertEqual(len(self.tool.solids()),1)

    def test_five_pole_contact_curve_matches_exact_formula(self):
        radius,pivot,extent = 3,30,20
        curve = BRepAdaptor_Curve(nose.contact_edge(radius,pivot,extent).wrapped)
        self.assertEqual(curve.Bezier().NbPoles(),5)
        limit = extent/(sqrt(radius**2+extent**2)+radius)
        a = radius*nose.SLOPE/sqrt(1+nose.SLOPE**2)
        for i in range(31):
            t = i/30
            u = -limit+2*limit*t
            center_y = 2*radius*u/(1-u*u)
            factor = 1-a/sqrt(radius**2+center_y**2)
            expected = (pivot+radius*factor,center_y*factor,-40)
            actual = curve.Value(t).Coord()
            self.assertLess(sqrt(sum((x-y)**2 for x,y in zip(actual,expected))),1e-10)

    def test_tool_follows_rolling_sphere_envelope(self):
        radius,angle = 3,radians(20)
        for center_y in (-2.5,0,2.5):
            radial = sqrt(radius**2+center_y**2)
            center_z = nose.APEX+nose.SLOPE*radial-radius*sqrt(1+nose.SLOPE**2)
            derivative = nose.SLOPE*center_y/radial
            phi = radians(150)
            x = 30+radius+radius*cos(phi)
            y = center_y-radius*sin(phi)*derivative/sqrt(1+derivative**2)
            z = center_z+radius*sin(phi)/sqrt(1+derivative**2)
            for side in (-1,1):
                world = Vector(x,y*cos(angle)-side*z*sin(angle),y*sin(angle)+side*z*cos(angle))
                self.assertLess(self.tool.shells()[0].distance_to(world),5e-6)


if __name__=="__main__":
    unittest.main()
