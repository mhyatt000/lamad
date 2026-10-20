"""Right middle proximal-link handedness and shared analytical construction."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from lamad.core.mesh_compare import body_mesh

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
sys.path.insert(0,str(PROJECT))
recipe = importlib.import_module("part.finger_r_m_pp")


class AnalyticalRMPPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_open = builtins.open
        def fonts_only(file,mode="r",*args,**kwargs):
            if Path(file).suffix.lower() not in {".ttf",".otf",".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted reference file I/O: {file}")
            return real_open(file,mode,*args,**kwargs)
        with patch("builtins.open",side_effect=fonts_only),patch("io.open",side_effect=fonts_only):
            cls.body = recipe.build()

    def test_valid_single_solid_and_interfaces(self):
        registry = importlib.import_module("part.orca_fingers__r_m_pp")
        self.assertIs(registry.build,recipe.build)
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()),1)
        self.assertFalse(self.body.is_inside((.5,6,46-4.15)))
        self.assertTrue(self.body.is_inside((.5,8.5,46-4)))
        self.assertTrue(self.body.is_inside((0,7.4,0)))
        self.assertFalse(self.body.is_inside((1.7,7.4,0)))

    def test_handed_groove_routing_and_blind_bores(self):
        self.assertFalse(self.body.is_inside((-8,-2,0)))
        self.assertTrue(self.body.is_inside((-8,3.2,0)))
        self.assertFalse(self.body.is_inside((1.31045421,7.4,1.075)))
        self.assertTrue(self.body.is_inside((1.31045421,-7.4,1.075)))
        self.assertFalse(self.body.is_inside((-.9,1.775,-.1)))
        self.assertTrue(self.body.is_inside((-.9,3,-.1)))

    def test_fresh_right_text_and_no_left_engraving_intermediate(self):
        with patch.object(recipe.left,"_label_profile",side_effect=AssertionError("Left text built")):
            body = recipe.build()
            profiles = recipe.sketches()
        self.assertAlmostEqual(body.volume,self.body.volume,places=6)
        bounds = profiles["engraving_YZ"].bounding_box()
        self.assertAlmostEqual(bounds.min.X,8,places=6)
        self.assertAlmostEqual(bounds.max.Y,1.800196767,places=5)
        self.assertAlmostEqual(bounds.min.Z,12.111529350,places=5)
        self.assertLess(profiles["pulley_groove_XZ"].center().Y,0)

    def test_spacing_edit_preserves_mating_sizes(self):
        edited = recipe.build({"joint_spacing":48})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()),1)
        self.assertFalse(edited.is_inside((.5,6,48-4.15)))
        self.assertTrue(edited.is_inside((.5,8.5,48-4)))
        self.assertAlmostEqual(edited.bounding_box().min.Z,-8.5,places=5)
        self.assertTrue(edited.is_inside((0,-7.4,0)))

    def test_absolute_export_is_watertight(self):
        mesh = body_mesh(self.body,.002,.05)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)


if __name__ == "__main__":
    unittest.main()
