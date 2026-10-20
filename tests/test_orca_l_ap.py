"""L-AP recipe independence and mechanical parameter behavior.

These checks exercise CAD editing, not mesh similarity or reconstruction status.
Run: .venv/bin/python -m unittest discover -s tests -p test_orca_l_ap.py -v
"""

import ast
import builtins
import importlib.util
from math import sqrt
from pathlib import Path
import unittest
from unittest.mock import patch
from scipy.optimize import minimize_scalar

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder


_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
RECIPE = Path(__file__).resolve().parents[1] / "projects/orca-v1/part/finger_l_ap.py"


def load_recipe():
    spec = importlib.util.spec_from_file_location("orca_l_ap_test_recipe", RECIPE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cylinders(body):
    found = []
    for face in body.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() == GeomAbs_Cylinder:
            found.append(surface.Cylinder())
    return found


class AnalyticalLAPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe = load_recipe()
        # Text legitimately uses installed fonts. No reference geometry,
        # serialized profiles, or other data files may be read to build CAD.
        real_open = builtins.open
        def fonts_only(file, mode="r", *args, **kwargs):
            if Path(file).suffix.lower() not in {".ttf", ".otf", ".ttc"} or any(c in mode for c in "wa+"):
                raise AssertionError(f"Recipe attempted non-font file I/O: {file}")
            return real_open(file,mode,*args,**kwargs)
        with patch("builtins.open", side_effect=fonts_only), \
             patch("io.open", side_effect=fonts_only):
            cls.default = cls.recipe.build()

    def assert_single_solid(self, body):
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()), 1)
        self.assertGreater(body.volume, 0)

    def assert_bearing_radius(self, body, radius):
        matching = []
        for cylinder in cylinders(body):
            axis, center = cylinder.Axis().Direction(), cylinder.Location()
            if (abs(abs(axis.Y()) - 1) < 1e-6
                    and abs(center.X()) < 1e-5 and abs(center.Z()) < 1e-5
                    and abs(cylinder.Radius() - radius) < 1e-6):
                matching.append(cylinder)
        self.assertGreaterEqual(len(matching), 2, "Expected both proximal bearing seats")

    def test_default_is_valid_single_solid_with_physical_interfaces(self):
        self.assert_single_solid(self.default)
        self.assert_bearing_radius(self.default, 4.1)
        bounds = self.default.bounding_box()
        self.assertAlmostEqual(bounds.size.Y, 19, places=5)
        self.assertAlmostEqual(bounds.size.Z, 17, places=5)
        self.assertTrue(self.default.is_inside((20, 0, 7.4)))
        self.assertFalse(self.default.is_inside((20, 0, 7.6)))

    def test_recipe_has_no_geometry_import_or_serialized_data_dependency(self):
        tree = ast.parse(RECIPE.read_text())
        imports = []
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "Recipe delegates to a local geometry helper")
                imports.append(node.module)
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    names.append(node.func.attr)
        # The model should be reviewable from standard math + build123d alone.
        self.assertTrue(set(imports) <= {"math", "build123d"}, imports)
        forbidden = {"import_stl", "import_step", "import_brep", "import_obj",
                     "boundary_body", "measured_body", "read_text", "read_bytes",
                     "open", "loads", "load", "eval", "exec", "__import__"}
        self.assertFalse(forbidden.intersection(names), forbidden.intersection(names))

    def test_construction_guides_do_not_participate_in_body(self):
        guides = self.recipe.construction()
        self.assertTrue(set(guides) <= set(self.recipe.sketches()))
        self.assertTrue(all(shape.edges() for shape in guides.values()))
        with patch.object(self.recipe, "construction", side_effect=AssertionError("Guides used in model")):
            body = self.recipe.build()
        self.assertAlmostEqual(body.volume,self.default.volume,places=6)

    def test_bearing_diameter_edit_changes_both_seats(self):
        edited = self.recipe.build({"bearing_radius": 4.2})
        self.assert_single_solid(edited)
        self.assert_bearing_radius(edited, 4.2)
        self.assertNotAlmostEqual(edited.volume, self.default.volume, places=3)
        self.assertTrue(self.default.is_inside((4.15, 6.5, 0)))
        self.assertFalse(edited.is_inside((4.15, 6.5, 0)))

    def test_joint_spacing_moves_axle_without_scaling_bearing(self):
        edited = self.recipe.build({"joint_spacing": 22})
        self.assert_single_solid(edited)
        self.assert_bearing_radius(edited, 4.1)
        self.assertTrue(edited.is_inside((22, 0, 7.4)))
        self.assertFalse(self.default.is_inside((22, 0, 7.4)))
        self.assertFalse(edited.is_inside((20, 0, 7.4)))
        self.assertAlmostEqual(edited.bounding_box().size.Y, 19, places=5)
        self.assertAlmostEqual(edited.bounding_box().size.Z, 17, places=5)

    def test_fork_gap_edit_opens_clearance_between_arms(self):
        edited = self.recipe.build({"fork_gap": 10})
        self.assert_single_solid(edited)
        self.assert_bearing_radius(edited, 4.1)
        for y in (-4.8, 4.8):
            self.assertTrue(self.default.is_inside((3, y, 6)))
            self.assertFalse(edited.is_inside((3, y, 6)))
        self.assertAlmostEqual(edited.bounding_box().size.Y, 19, places=5)
        self.assertLess(edited.volume, self.default.volume)

    def test_width_edit_preserves_tangent_connection_to_nose(self):
        edited = self.recipe.build({"width":20})
        self.assert_single_solid(edited)
        self.assertAlmostEqual(edited.bounding_box().size.Y,20,places=5)
        self.assertFalse(self.default.is_inside((2,9.75,6)))
        self.assertTrue(edited.is_inside((2,9.75,6)))

    def test_nose_blend_precedes_angled_cheek_cut(self):
        # Native-reference sections establish air at these four points. Rounding
        # after the angled cut instead leaves material here. Points are >.014 mm
        # from either candidate boundary, safely away from classifier tolerance.
        for y in (-3.25, 3.25):
            for z in (-3.6, 3.6):
                with self.subTest(y=y, z=z):
                    self.assertFalse(self.default.is_inside((20.6284516387, y, z)))
        self.assertTrue(self.default.is_inside((20.6284516387, 3.25, 3.8)))

    def test_nose_fillet_tracks_ideal_rolling_ball_at_difficult_section(self):
        # Independent geometric oracle: centers of radius-.7 balls tangent to
        # X20 and z=2.3+.4*r lie on the offset-plane/offset-cone intersection.
        # Check the envelope, not any imported reference face. This samples the
        # difficult region; it is not a certified whole-surface error bound.
        tool = self.recipe._nose_relief(self.recipe.DEFAULTS)
        x, radius = 20.2, .7
        reach = sqrt(radius**2-(x-20-radius)**2)
        for y in (1, 2, 3):
            def height(t):
                center_z = 2.3+.4*sqrt(radius**2+t*t)-radius*sqrt(1.16)
                return center_z+sqrt(max(0, reach**2-(y-t)**2))
            solution = minimize_scalar(lambda t: -height(t), bounds=(y-reach, y+reach),
                                       method="bounded", options={"xatol":1e-12})
            ray = self.recipe.Edge.make_line((x,y,-10),(x,y,10))
            pieces = ray.intersect(tool)
            actual = max(vertex.Z for piece in pieces for vertex in piece.vertices())
            with self.subTest(y=y):
                self.assertLess(abs(actual+solution.fun), .008)

    def test_other_exposed_dimensions_support_modest_edits(self):
        changes = {"shoulder_height":9,"tongue_thickness":9.2,"retention_radius":3.6,
                   "bearing_shoulder_y":7.8,"axle_radius":2,"axle_flat_halfwidth":1.7,
                   "axle_half_length":8,"edge_radius":1.3}
        for name,value in changes.items():
            with self.subTest(parameter=name,value=value):
                edited = self.recipe.build({name:value})
                self.assert_single_solid(edited)
                self.assertNotAlmostEqual(edited.volume,self.default.volume,places=3)


if __name__ == "__main__":
    unittest.main()
