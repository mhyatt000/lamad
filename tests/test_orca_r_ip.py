"""Right IP handedness, editable mechanics, and source-independent construction."""
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
sys.path.insert(0, str(PROJECT))
recipe = importlib.import_module("part.finger_r_ip")


class AnalyticalRIPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_open = builtins.open
        def fonts_only(file, mode="r", *args, **kwargs):
            if Path(file).suffix.lower() not in {".ttf", ".otf", ".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted reference file I/O: {file}")
            return real_open(file, mode, *args, **kwargs)
        with patch("builtins.open", side_effect=fonts_only), patch("io.open", side_effect=fonts_only):
            cls.body = recipe.build()

    def test_valid_single_solid_and_interfaces(self):
        registry = importlib.import_module("part.orca_fingers__r_ip")
        self.assertIs(registry.build,recipe.build)
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()), 1)
        self.assertTrue(self.body.is_inside((0,7.4,0)))
        self.assertFalse(self.body.is_inside((1.7,7.4,0)))
        self.assertFalse(self.body.is_inside((3.35,0,16)))
        self.assertTrue(self.body.is_inside((3.35,0,11.9)))
        self.assertFalse(self.body.is_inside((6,0,16)))
        self.assertTrue(self.body.is_inside((6,.8,16)))

    def test_groove_port_and_shallow_mouth_are_right_handed(self):
        self.assertTrue(self.body.is_inside((-3,0,0)))
        self.assertTrue(self.body.is_inside((-7.7,-1.875,0)))
        self.assertFalse(self.body.is_inside((-7.7,1.875,0)))
        center = recipe.left._port_frame().origin
        self.assertFalse(self.body.is_inside((center.X,4,center.Z)))
        self.assertTrue(self.body.is_inside((center.X,-4,center.Z)))
        self.assertFalse(self.body.is_inside((1.26468285,4.36,9.06188296)))

    def test_unengraved_reuse_and_fresh_text_placement(self):
        with patch.object(recipe.left,"_label_profile",side_effect=AssertionError("Left text built")):
            body = recipe.build()
            profiles = recipe.sketches()
        self.assertAlmostEqual(body.volume,self.body.volume,places=6)
        bounds = profiles["engraving_YZ"].bounding_box()
        self.assertAlmostEqual(bounds.min.X,7.5,places=6)
        self.assertAlmostEqual(bounds.min.Y,-1.62996078,places=5)
        self.assertAlmostEqual(bounds.max.Y,1.37003922,places=5)
        self.assertAlmostEqual(bounds.min.Z,5.47105980,places=5)
        self.assertGreater(profiles["pulley_groove_XZ"].center().Y,0)
        self.assertTrue(set(recipe.construction()) <= set(profiles))

    def test_width_and_groove_edits_remain_physical(self):
        edited = recipe.build({"body_width":9.2,"socket_outer_width":14,"pin_radius":.9})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()),1)
        self.assertFalse(self.body.is_inside((5,-4.5,4)))
        self.assertTrue(edited.is_inside((5,-4.5,4)))
        self.assertFalse(edited.is_inside((6,.8,16)))

    def test_absolute_export_is_watertight(self):
        mesh = body_mesh(self.body,.002,.05)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)


if __name__ == "__main__":
    unittest.main()
