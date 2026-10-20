"""Recovered proximal-family constraints and interfaces; routing audit ongoing."""
import builtins
import importlib
from math import hypot
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
sys.path.insert(0,str(PROJECT))
recipe = importlib.import_module("part.finger_pp")


class AnalyticalPPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_open = builtins.open
        def fonts_only(file,mode="r",*args,**kwargs):
            if Path(file).suffix.lower() not in {".ttf",".otf",".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted reference file I/O: {file}")
            return real_open(file,mode,*args,**kwargs)
        with patch("builtins.open",side_effect=fonts_only),patch("io.open",side_effect=fonts_only):
            cls.body = recipe.build()

    def test_quadratic_is_tangent_to_both_joint_circles_at_all_family_lengths(self):
        for spacing in (33,38,46,48):
            points = recipe._rear_controls(recipe._parameters({"joint_spacing":spacing}))
            self.assertEqual(points[1],(0,0,spacing/2))
            for end,center,radius in ((points[0],(0,0,0),8.5),(points[-1],(.5,0,spacing),8)):
                radial = (end[0]-center[0],end[2]-center[2])
                tangent = (points[1][0]-end[0],points[1][2]-end[2])
                self.assertAlmostEqual(hypot(*radial),radius,places=10)
                self.assertAlmostEqual(sum(a*b for a,b in zip(radial,tangent)),0,places=9)

    def test_width_curve_has_constant_width_tangencies(self):
        p = recipe._parameters()
        points = recipe._width_controls(p)
        self.assertEqual(points[0][1],points[1][1])
        self.assertEqual(points[2][1],points[3][1])
        self.assertEqual(points[1][2],(46+8.5)/2)
        self.assertEqual(points[2][2],points[1][2])

    def test_valid_body_and_proximal_keyed_axle(self):
        registry = importlib.import_module("part.orca_fingers__l_m_pp")
        self.assertIs(registry.build,recipe.build)
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()),1)
        self.assertTrue(self.body.is_inside((0,7.4,0)))
        self.assertFalse(self.body.is_inside((1.7,7.4,0)))
        self.assertFalse(self.body.is_inside((0,7.6,0)))

    def test_printable_revision_bearing_radius_and_retaining_lip(self):
        for side in (-1,1):
            self.assertFalse(self.body.is_inside((.5,side*6,46-4.15)))
            self.assertTrue(self.body.is_inside((.5,side*6,46-4.2)))
            self.assertTrue(self.body.is_inside((.5,side*8.5,46-4)))
            self.assertFalse(self.body.is_inside((.5,side*8.5,46-3.4)))
        self.assertFalse(self.body.is_inside((.5,0,46)))
        self.assertFalse(self.body.is_inside((.5,6,51)))

    def test_spacing_edit_moves_distal_interface_without_scaling_axle(self):
        edited = recipe.build({"joint_spacing":48})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()),1)
        # The bearing center moves 2 mm; its derived snap-opening angle changes
        # with the rear tangent, so the cropped top is not a rigid translation.
        height_change = edited.bounding_box().max.Z-self.body.bounding_box().max.Z
        self.assertGreater(height_change,1.8)
        self.assertLess(height_change,2.2)
        self.assertAlmostEqual(edited.bounding_box().min.Z,self.body.bounding_box().min.Z,places=5)
        self.assertFalse(edited.is_inside((.5,6,48-4.15)))
        self.assertTrue(edited.is_inside((0,7.4,0)))
        self.assertFalse(edited.is_inside((1.7,7.4,0)))

    def test_guides_are_display_only(self):
        self.assertTrue(set(recipe.construction()) <= set(recipe.sketches()))
        with patch.object(recipe,"construction",side_effect=AssertionError("Guide used in body")):
            body = recipe.build()
        self.assertAlmostEqual(body.volume,self.body.volume,places=6)

    def test_lower_cam_groove_is_on_positive_y(self):
        self.assertFalse(self.body.is_inside((-8,2,0)))
        self.assertTrue(self.body.is_inside((-8,-3.2,0)))
        self.assertTrue(self.body.is_inside((-7.7,2,0)))
        frame = recipe.finger_cam.port_frame(8.25,1)
        self.assertFalse(self.body.is_inside((frame.origin.X,4,frame.origin.Z)))

    def test_routing_junction_leaves_no_triangular_fin_below_bore(self):
        for y in (-2.7,-1.775,-.85):
            self.assertFalse(self.body.is_inside((-.9,y,-.1)))
        # The relief has actual side walls; this is not a through-width cut.
        self.assertTrue(self.body.is_inside((-.9,-3,-.1)))
        self.assertTrue(self.body.is_inside((-.9,0,-.1)))

    def test_invalid_parameters_are_rejected(self):
        for params in ({"joint_spacing":20},{"body_width":float("nan")},
                       {"bearing_radius":3.4},{"fork_gap":20},{"scale_x":1.1}):
            with self.assertRaises(ValueError):
                recipe.build(params)


if __name__ == "__main__":
    unittest.main()
