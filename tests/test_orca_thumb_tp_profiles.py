"""Compact mechanical sketches for the orthogonal thumb-base yoke."""
import builtins
import importlib
from math import cos, radians, sin
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import GeomType

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
model = importlib.import_module("part.finger_t_tp")


class ThumbTPProfileTests(unittest.TestCase):
    def test_source_free_compact_circle_line_profiles(self):
        p = model._parameters()
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            profiles = [model._plan_profile(p),model._back_profile(p),
                        model._aperture_plan(p),model._clearance_profile(p),model._axle_profile(p)]
        for profile in profiles:
            self.assertTrue(profile.is_valid)
            self.assertLessEqual(len(profile.edges()),14)
            self.assertTrue(all(edge.geom_type in (GeomType.LINE,GeomType.CIRCLE) for edge in profile.edges()))

    def test_plan_circle_front_and_tangent_rounds(self):
        for radius in (12.5,13):
            p = model._parameters({"body_radius":radius})
            profile = model._plan_profile(p)
            self.assertAlmostEqual(profile.bounding_box().max.X,p["front"],places=5)
            self.assertAlmostEqual(profile.bounding_box().max.Y,radius,places=5)
            radii = sorted(edge.radius for edge in profile.edges() if edge.geom_type==GeomType.CIRCLE)
            self.assertEqual(sum(abs(r-3)<1e-5 for r in radii),2)
            self.assertGreaterEqual(sum(abs(r-radius)<1e-5 for r in radii),1)
            self.assertTrue(all(min(abs(r-3),abs(r-radius))<1e-5 for r in radii))

    def test_clearance_ramps_are_tangent_to_joint_circle(self):
        p = model._parameters()
        profile = model._clearance_profile(p)
        points = [(v.X,v.Z) for v in profile.vertices()]
        half = p["clearance_half_height"]
        for degrees,zsign,xsign in ((20,-1,-1),(42,1,1)):
            angle = radians(degrees)
            matches = [(x,z) for x,z in points
                       if abs(xsign*sin(angle)*x+cos(angle)*z-zsign*half)<1e-7]
            self.assertEqual(len(matches),2)
            # Unit plane normal and offset half-height establish tangency.
            self.assertAlmostEqual(sin(angle)**2+cos(angle)**2,1)

    def test_keyed_journal_size_is_independent_of_body_radius(self):
        for radius in (12.5,13):
            p = model._parameters({"body_radius":radius})
            profile = model._axle_profile(p)
            self.assertAlmostEqual(profile.bounding_box().size.X,2*1.634,places=6)
            self.assertAlmostEqual(profile.bounding_box().size.Y,2*1.9,places=6)

    def test_invalid_interface_parameters_fail(self):
        for params in ({"retention_depth":13},{"bearing_depth":7},
                       {"retention_radius":4.2},{"axle_radius":1.5},
                       {"axle_projection":1},{"scale_z":2}):
            with self.assertRaises(ValueError):
                model._parameters(params)


if __name__=="__main__":
    unittest.main()
