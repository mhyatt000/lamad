"""Derived thumb transition law and shared primitive helper regressions."""
import importlib
from math import sqrt
from pathlib import Path
import sys
import unittest

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
recipe = importlib.import_module("part.finger_l_t_ap")


class ThumbGuideTests(unittest.TestCase):
    def test_six_controls_derive_only_from_two_corners(self):
        first,last = recipe._transition_sections(recipe._parameters())
        for start,end in zip(first,last):
            points = recipe._guide_controls(start,end)
            self.assertEqual(len(points),6)
            self.assertEqual(points[0],start)
            self.assertEqual(points[-1],end)
            speed = sqrt(sum((b-a)**2 for a,b in zip(start,end)))
            self.assertAlmostEqual(5*(points[1][0]-points[0][0]),speed)
            self.assertAlmostEqual(5*(points[-1][0]-points[-2][0]),speed)
            for i in (1,2):
                self.assertEqual(points[0][i],points[1][i])
                self.assertEqual(points[1][i],points[2][i])
                self.assertEqual(points[-1][i],points[-2][i])
                self.assertEqual(points[-2][i],points[-3][i])

    def test_rectangles_have_mechanical_dimensions(self):
        first,last = recipe._transition_sections(recipe._parameters())
        self.assertTrue(all(point[0]==13.5 for point in first))
        self.assertTrue(all(point[0]==19.5 for point in last))
        lengths = [sqrt(sum((b-a)**2 for a,b in zip(x,y)))
                   for x,y in zip(last,last[1:]+last[:1])]
        for observed,expected in zip(lengths,(17,14.7,17,14.7)):
            self.assertAlmostEqual(observed,expected)

    def test_loft_is_valid_and_tangent_to_untwisted_sections(self):
        for angle in (15,20,25):
            body = recipe._transition(recipe._parameters({"twist_angle":angle}))
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)
            self.assertAlmostEqual(body.bounding_box().min.X,13.5,places=5)
            self.assertAlmostEqual(body.bounding_box().max.X,19.5,places=5)

    def test_nose_uses_outer_cheek_not_inner_retention_radius(self):
        p = recipe._parameters()
        profile = recipe._nose_outline(p)
        circles = [edge.radius for edge in profile.edges()
                   if edge.geom_type.name=="CIRCLE"]
        self.assertTrue(any(abs(r-8.5)<1e-6 for r in circles))
        self.assertFalse(any(abs(r-7.5)<1e-6 for r in circles))
        self.assertEqual(sum(abs(r-.5)<1e-6 for r in circles),2)

    def test_invalid_dimensions(self):
        for params in ({"joint_spacing":20},{"bridge_height":18},
                       {"twist_angle":60},{"axle_half_length":8},{"copied_faces":1}):
            with self.assertRaises(ValueError):
                recipe._parameters(params)

    def test_retained_rim_has_tangent_one_mm_cheek_joins(self):
        profile = recipe._retained_rim_profile(recipe._parameters())
        circles = [edge for edge in profile.edges() if edge.geom_type.name=="CIRCLE"]
        self.assertEqual(len(circles),3)
        self.assertEqual(sum(abs(edge.radius-1)<1e-6 for edge in circles),2)
        self.assertEqual(sum(abs(edge.radius-7.5)<1e-6 for edge in circles),1)
        for point in ((30.24057772,7.4961405,0),(31.14819332,6.15463496,0)):
            from build123d import Vector
            self.assertLess(profile.outer_wire().distance_to(Vector(*point)),1e-6)

    def test_retaining_cutter_preserves_both_sides(self):
        from build123d import Axis
        p = recipe._parameters()
        tool = recipe._retention_slot(p).rotate(Axis.X,-p["twist_angle"])
        self.assertTrue(tool.is_valid)
        self.assertEqual(len(tool.solids()),2)
        pieces = sorted(tool.solids(),key=lambda shape:shape.center().Y)
        self.assertLess(pieces[0].center().Y,0)
        self.assertGreater(pieces[1].center().Y,0)
        # Allow numerical volume-integration noise in large temporary stock
        # after the frame round trip; the two retained components agree.
        self.assertAlmostEqual(pieces[0].volume,pieces[1].volume,delta=1e-5)


if __name__=="__main__":
    unittest.main()
