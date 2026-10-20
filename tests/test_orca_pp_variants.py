"""Analytical I/P variants: handedness, interfaces, text and meaningful edits."""
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
mechanics = importlib.import_module("part.finger_pp")
CODES = ("L-I-PP","R-I-PP","L-P-PP","R-P-PP")


class AnalyticalShortPPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {code:importlib.import_module("part.finger_"+code.lower().replace("-","_")) for code in CODES}
        real_open = builtins.open
        def fonts_only(file,mode="r",*args,**kwargs):
            if Path(file).suffix.lower() not in {".ttf",".otf",".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted reference file I/O: {file}")
            return real_open(file,mode,*args,**kwargs)
        with patch("builtins.open",side_effect=fonts_only),patch("io.open",side_effect=fonts_only),\
             patch.object(mechanics,"_label_profile",side_effect=AssertionError("M label built")):
            cls.bodies = {code:module.build() for code,module in cls.modules.items()}

    def test_all_four_are_valid_single_solids(self):
        for code,body in self.bodies.items():
            with self.subTest(code=code):
                registry = importlib.import_module("part.orca_fingers__"+code.lower().replace("-","_"))
                self.assertIs(registry.build,self.modules[code].build)
                self.assertTrue(body.is_valid)
                self.assertEqual(len(body.solids()),1)

    def test_shared_mating_diameters_and_family_lengths(self):
        for code,body in self.bodies.items():
            with self.subTest(code=code):
                spacing = self.modules[code].DEFAULTS["joint_spacing"]
                self.assertFalse(body.is_inside((.5,6,spacing-4.15)))
                self.assertTrue(body.is_inside((.5,6,spacing-4.2)))
                self.assertTrue(body.is_inside((.5,8.5,spacing-4)))
                self.assertTrue(body.is_inside((0,7.4,0)))
                self.assertFalse(body.is_inside((1.7,7.4,0)))

    def test_groove_and_blind_bores_are_correctly_handed(self):
        for code,body in self.bodies.items():
            with self.subTest(code=code):
                side = 1 if code.startswith("L") else -1
                self.assertFalse(body.is_inside((-8,side*2,0)))
                self.assertTrue(body.is_inside((-8,-side*3.2,0)))
                x,z = mechanics._routing_bore_centers(self.modules[code].DEFAULTS)[1]
                self.assertFalse(body.is_inside((x,-side*7.4,z)))
                self.assertTrue(body.is_inside((x,side*7.4,z)))
                self.assertFalse(body.is_inside((-.9,-side*1.775,-.1)))

    def test_fresh_text_uses_each_sources_own_anchor(self):
        for code,module in self.modules.items():
            with self.subTest(code=code):
                profiles = module.sketches()
                bounds = profiles["engraving_YZ"].bounding_box()
                anchor = module._OPTIONS["anchor"]
                self.assertAlmostEqual(bounds.min.X,anchor[0],places=6)
                self.assertAlmostEqual(bounds.max.Y,anchor[1],places=5)
                self.assertAlmostEqual(bounds.min.Z,anchor[2],places=5)
                self.assertTrue(set(module.construction()) <= set(profiles))

    def test_local_length_edits_preserve_mating_sizes(self):
        for code,module in self.modules.items():
            with self.subTest(code=code):
                spacing = module.DEFAULTS["joint_spacing"]+2
                body = module.build({"joint_spacing":spacing})
                self.assertTrue(body.is_valid)
                self.assertEqual(len(body.solids()),1)
                self.assertFalse(body.is_inside((.5,6,spacing-4.15)))
                self.assertTrue(body.is_inside((.5,8.5,spacing-4)))
                self.assertAlmostEqual(body.bounding_box().min.Z,-8.5,places=5)

    def test_absolute_exports_are_watertight(self):
        for code,body in self.bodies.items():
            with self.subTest(code=code):
                mesh = body_mesh(body,.002,.05)
                self.assertTrue(mesh.is_watertight)
                self.assertTrue(mesh.is_volume)

    def test_family_anchors_are_explicit_not_inferred_from_requested_length(self):
        medium = self.modules["L-I-PP"].DEFAULTS
        short = self.modules["L-P-PP"].DEFAULTS
        self.assertNotEqual(medium["routing_front_floor_setback"],short["routing_front_floor_setback"])
        self.assertEqual(mechanics.DEFAULTS["joint_spacing"],46)
        self.assertEqual(medium["joint_spacing"],38)
        self.assertEqual(short["joint_spacing"],33)


if __name__ == "__main__":
    unittest.main()
