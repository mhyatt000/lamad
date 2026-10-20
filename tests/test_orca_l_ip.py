"""Mechanical checks for the analytical L-IP recipe; physical fit is unverified."""
import builtins
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from lamad.core.mesh_compare import body_mesh

_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PATH = Path(__file__).resolve().parents[1] / "projects/orca-v1/part/finger_l_ip.py"


class AnalyticalLIPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("lip_analytical_test", PATH)
        cls.recipe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.recipe)
        real_open = builtins.open
        def fonts_only(file, mode="r", *args, **kwargs):
            if Path(file).suffix.lower() not in {".ttf", ".otf", ".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted reference file I/O: {file}")
            return real_open(file, mode, *args, **kwargs)
        with patch("builtins.open", side_effect=fonts_only), patch("io.open", side_effect=fonts_only):
            cls.body = cls.recipe.build()

    def test_single_solid_and_keyed_axis_along_y(self):
        self.assertTrue(self.body.is_valid)
        self.assertEqual(len(self.body.solids()), 1)
        for y in (-7.4, 7.4):
            self.assertTrue(self.body.is_inside((0,y,0)))
            self.assertFalse(self.body.is_inside((1.7,y,0)))
        self.assertFalse(self.body.is_inside((0,7.6,0)))

    def test_socket_floor_and_rounds(self):
        self.assertFalse(self.body.is_inside((3.35,0,16)))
        self.assertTrue(self.body.is_inside((3.35,0,11.9)))
        self.assertFalse(self.body.is_inside((3.35,3,12.1)))
        self.assertTrue(self.body.is_inside((3.35,4,12.1)))

    def test_cross_pin_and_front_counterbore(self):
        self.assertFalse(self.body.is_inside((6,0,16)))
        self.assertTrue(self.body.is_inside((6,.8,16)))
        self.assertFalse(self.body.is_inside((7,1.5,16)))
        self.assertTrue(self.body.is_inside((7,1.8,16)))

    def test_width_and_pin_edits_are_physical(self):
        edited = self.recipe.build({"body_width":9.2,"socket_outer_width":14,"pin_radius":.9})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()), 1)
        self.assertFalse(self.body.is_inside((5,4.5,4)))
        self.assertTrue(edited.is_inside((5,4.5,4)))
        self.assertFalse(self.body.is_inside((6,6.7,20)))
        self.assertTrue(edited.is_inside((6,6.7,20)))
        self.assertFalse(edited.is_inside((6,.8,16)))

    def test_construction_is_display_only(self):
        self.assertTrue(set(self.recipe.construction()) <= set(self.recipe.sketches()))
        with patch.object(self.recipe, "construction", side_effect=AssertionError("Construction used")):
            body = self.recipe.build()
        self.assertAlmostEqual(body.volume, self.body.volume, places=6)

    def test_target_revision_retains_center_and_has_one_sided_groove(self):
        self.assertTrue(self.body.is_inside((-3,0,0)))  # Older STEP cuts this away.
        self.assertFalse(self.body.is_inside((-7.7,-1.875,0)))
        self.assertTrue(self.body.is_inside((-7.7,1.875,0)))

    def test_port_and_shallow_entry_pocket_are_present(self):
        center = self.recipe._port_frame().origin
        self.assertFalse(self.body.is_inside((center.X,-4,center.Z)))
        self.assertTrue(self.body.is_inside((center.X,4,center.Z)))
        # Above Z8 the shell widens. The cone alone leaves material here; a
        # separate shallow rectangular pocket is required by source sections.
        self.assertFalse(self.body.is_inside((1.26468285,-4.36,9.06188296)))

    def test_groove_land_radius_edit_changes_material(self):
        edited = self.recipe.build({"groove_inner_radius":7.35})
        self.assertTrue(edited.is_valid)
        self.assertEqual(len(edited.solids()), 1)
        self.assertFalse(self.body.is_inside((-7.3,-1.875,0)))
        self.assertTrue(edited.is_inside((-7.3,-1.875,0)))

    def test_export_is_watertight_without_filling_geometric_holes(self):
        mesh = body_mesh(self.body,.002,.05)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_volume)
        self.assertEqual(mesh.metadata["degenerate_triangles_removed"], 2)


if __name__ == "__main__":
    unittest.main()
