"""Mechanical regression checks for the analytical orthogonal thumb yoke."""
import builtins
import importlib
from math import cos, radians, sin
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
model = importlib.import_module("part.finger_t_tp")


class ThumbTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            cls.stages = model.stages()
        cls.body = list(cls.stages.values())[-1]

    def test_source_free_valid_stages(self):
        self.assertIs(importlib.import_module("part.orca_fingers__t_tp").build,model.build)
        for body in self.stages.values():
            self.assertTrue(body.is_valid)
            self.assertEqual(len(body.solids()),1)

    def test_bearing_seats_are_blind_with_retaining_shoulders(self):
        for side in (-1,1):
            self.assertFalse(self.body.is_inside((0,side*9,4)))
            self.assertFalse(self.body.is_inside((0,side*10.9,0)))
            self.assertTrue(self.body.is_inside((0,side*10.9,3.75)))
            self.assertTrue(self.body.is_inside((0,side*11.6,0)))
            self.assertFalse(self.body.is_inside((0,side*12.6,0)))

    def test_orthogonal_keyed_journals(self):
        for z in (-15,22):
            self.assertTrue(self.body.is_inside((0,0,z)))
            self.assertFalse(self.body.is_inside((1.8,0,z)))
            self.assertFalse(self.body.is_inside((0,2,z)))
        self.assertFalse(self.body.is_inside((0,0,0)))

    def test_lower_back_root_uses_constrained_circle_not_full_root_clip(self):
        # Independent source/native cylinder center; ordinary full-root
        # rounding would place its Z center at -14, not -13.3527860224.
        angle = radians(20)
        point = Vector(-3.134+1.5*cos(angle),0,-13.3527860224+1.5*sin(angle))
        self.assertLess(self.body.shells()[0].distance_to(point),2e-6)

    def test_printable_retention_slot_keeps_inner_land_and_outer_wall(self):
        for side in (-1,1):
            self.assertFalse(self.body.is_inside((0,side*8.5,17.5)))
            self.assertFalse(self.body.is_inside((0,side*8.5,18.05)))
            self.assertTrue(self.body.is_inside((0,side*7.5,17.5)))
            # Check behind the twenty-degree exits: farther forward the
            # intended exit wedge opens beyond the circular outer wall.
            self.assertTrue(self.body.is_inside((-2,side*9.5,17.5)))
            self.assertTrue(self.body.is_inside((0,side*8.5,18.2)))

    def test_front_opening_has_native_eight_tenths_round(self):
        angle = radians(45)
        point = Vector(8.2+.8*cos(angle),0,-9.3+.8*sin(angle))
        self.assertLess(self.body.shells()[0].distance_to(point),1e-6)

    def test_top_blend_retains_material_removed_by_older_step_revision(self):
        # The printable revision lacks the old broad rear connecting groove.
        # Its retained R3 surface has a documented ~.0067 mm kernel residual.
        point = Vector(-2.29441357,-1.08218265,14.81766129)
        self.assertLess(self.body.shells()[0].distance_to(point),.008)

    def test_slot_height_edit_opens_slot_without_recentering_rear_ports(self):
        body = model.build({"slot_height":1.2})
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()),1)
        self.assertTrue(self.body.is_inside((0,8.5,18.15)))
        self.assertFalse(body.is_inside((0,8.5,18.15)))
        profiles = model.sketches({"slot_height":1.2})
        ports = profiles["rear_access_ports_YZ"].bounding_box()
        self.assertAlmostEqual((ports.min.Z+ports.max.Z)/2,17.45,places=6)

    def test_slot_flare_trims_inner_round_behind_front_tangency(self):
        # These source vertices lie on both R8 and the lower flaring plane.
        # Starting the flare at X1 incorrectly leaves part of the R.2 torus.
        for side in (-1,1):
            point = Vector(.5234826,side*7.9828544,17.02978325)
            self.assertLess(self.body.shells()[0].distance_to(point),2e-6)

    def test_fine_absolute_export_is_closed_without_repairs(self):
        mesh = body_mesh(self.body,model.TESSELLATION_MM,model.ANGULAR_TOLERANCE_RAD)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)
        self.assertLess(abs(mesh.volume-self.body.volume),.1)

    def test_fork_gap_edit_moves_walls_without_scaling_journal(self):
        body = model.build({"fork_gap":16})
        self.assertTrue(body.is_valid)
        self.assertTrue(self.body.is_inside((0,7.8,7)))
        self.assertFalse(body.is_inside((0,7.8,7)))
        self.assertTrue(body.is_inside((0,0,22)))
        self.assertFalse(body.is_inside((1.8,0,22)))


if __name__=="__main__":
    unittest.main()
