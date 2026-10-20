"""Right AP handedness, feature reuse, and independent analytical construction."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
sys.path.insert(0, str(PROJECT))
recipe = importlib.import_module("part.finger_r_ap")


class AnalyticalRAPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real_open = builtins.open
        def fonts_only(file, mode="r", *args, **kwargs):
            if Path(file).suffix.lower() not in {".ttf", ".otf", ".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted non-font file I/O: {file}")
            return real_open(file, mode, *args, **kwargs)
        with patch("builtins.open", side_effect=fonts_only), patch("io.open", side_effect=fonts_only):
            cls.body = recipe.build()

    def test_valid_body_and_registry_use_analytical_recipe(self):
        registry = importlib.import_module("part.orca_fingers__r_ap")
        self.assertIs(registry.build, recipe.build)
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()), 1)
        self.assertTrue(self.body.is_inside((20, 0, 7.4)))
        self.assertFalse(self.body.is_inside((20, 0, 7.6)))

    def test_right_handed_tendon_profiles(self):
        profiles = recipe.sketches()
        starts = [(-3.2,-5.24666574),(-3.6,5.24666574),(3,1.45),(1.8,-1.45)]
        ends = [(-.8,-.75),(-.8,.75),(.8,.75),(.8,-.75)]
        for i, (start, end) in enumerate(zip(starts, ends), 1):
            for suffix, x, yz in (("entry", -3, start), ("exit", 20, end)):
                center = profiles[f"tendon_{i}_{suffix}_YZ"].center()
                for actual, expected in zip(center, (x, *yz)):
                    self.assertAlmostEqual(actual, expected, places=7)

    def test_slot_mouth_handedness_is_reversed(self):
        # R's rounded contraction is on -Y; its straight chamfer is on +Y.
        self.assertTrue(self.body.is_inside((11.2,-4,.8)))
        self.assertFalse(self.body.is_inside((11.2,4,.8)))
        profiles = recipe.sketches()
        self.assertLess(profiles["negative_slot_entry_XZ"].center().Y, 0)
        self.assertGreater(profiles["positive_slot_entry_XZ"].center().Y, 0)

    def test_unengraved_reuse_does_not_construct_left_label(self):
        with patch.object(recipe.left, "_label_profile", side_effect=AssertionError("Left label built")):
            body = recipe.build()
            profiles = recipe.sketches()
        self.assertAlmostEqual(body.volume, self.body.volume, places=6)
        bounds = profiles["engraving_XY"].bounding_box()
        self.assertAlmostEqual(bounds.min.X, 13.43054156, places=5)
        self.assertAlmostEqual(bounds.min.Y, -4.30500337, places=5)
        self.assertAlmostEqual(bounds.min.Z, 3.85, places=5)
        self.assertTrue(set(recipe.construction()) <= set(profiles))

    def test_spacing_and_width_remain_semantic_parameters(self):
        edited = recipe.build({"joint_spacing":22,"width":20})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()), 1)
        self.assertTrue(edited.is_inside((22,0,7.4)))
        self.assertFalse(self.body.is_inside((22,0,7.4)))
        self.assertAlmostEqual(edited.bounding_box().size.Y, 20, places=5)
        self.assertAlmostEqual(edited.bounding_box().size.Z, 17, places=5)


if __name__ == "__main__":
    unittest.main()
