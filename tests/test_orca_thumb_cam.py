"""Source-free cam constraints and regressions for the complete thumb cuts."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from build123d import Axis, Vector

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"projects/orca-v1"))
recipe = importlib.import_module("part.finger_l_t_ap")
cam = importlib.import_module("part.finger_thumb_cam")


class ThumbCamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(builtins,"open",side_effect=AssertionError("Reference I/O")), \
                patch("io.open",side_effect=AssertionError("Reference I/O")):
            p = recipe._parameters()
            retention = recipe._retention_slot(p).rotate(Axis.X,-p["twist_angle"])
            cls.pieces = cam.cam_pieces(retention=retention)

    def test_all_seven_cutters_are_valid_independent_solids(self):
        self.assertEqual(len(self.pieces),7)
        for shape in self.pieces:
            self.assertTrue(shape.is_valid)
            self.assertEqual(len(shape.solids()),1)
            self.assertGreater(shape.volume,0)

    def test_u_profile_has_two_tangent_legs_per_side_and_round_caps(self):
        profile = cam.u_profile()
        self.assertTrue(profile.is_valid)
        self.assertEqual(len(profile.edges()),8)
        lines = [e for e in profile.edges() if e.geom_type.name=="LINE"]
        self.assertEqual(len(lines),4)
        for edge in lines:
            self.assertAlmostEqual(edge.length,2.2)
        circles = [e for e in profile.edges() if e.geom_type.name=="CIRCLE"]
        self.assertEqual(sum(abs(e.radius-1.5)<1e-6 for e in circles),2)

    def test_lower_exit_window_is_not_clipped_at_slot_bottom(self):
        for index,side in ((3,-1),(6,1)):
            # Independent native/source-section discrepancy location: the
            # flared exit must remove this material well below Z=-.45.
            self.assertTrue(self.pieces[index].is_inside((31.18,side*7.30,-2)))
            self.assertFalse(self.pieces[index].is_inside((30,0,-2)))

    def test_branch_floor_still_excludes_upstream_material(self):
        for index,side in ((1,-1),(4,1)):
            origin,direction,_ = cam._frame(side)
            station = 1
            xy = (origin[0]+station*direction[0],origin[1]+station*direction[1])
            floor_z = cam.SLOPE_START-cam.SLOPE*station
            self.assertFalse(self.pieces[index].is_inside((*xy,floor_z-.1)))
            self.assertTrue(self.pieces[index].is_inside((*xy,floor_z+.1)))

    def test_paired_skirts_remove_the_same_geometry(self):
        negative,positive = self.pieces[2],self.pieces[5]
        self.assertAlmostEqual(negative.volume,positive.volume,delta=1e-6)
        for vertex in positive.vertices():
            point = vertex.center()
            self.assertLess(negative.shells()[0].distance_to(Vector(point.X,-point.Y,point.Z)),1e-6)

    def test_flare_uses_forward_wall_roots_without_backside_lobes(self):
        for index,side in ((2,-1),(5,1)):
            self.assertFalse(self.pieces[index].is_inside((21.43334,side*4.12048,4)))


if __name__=="__main__":
    unittest.main()
