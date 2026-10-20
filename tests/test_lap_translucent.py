"""Verify transparent diagnostic rays include internal surfaces exactly once."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import trimesh


_PROJECT = Path(__file__).resolve().parents[1] / "projects/orca-v1"
if not _PROJECT.exists():
    raise unittest.SkipTest("requires projects/orca-v1 (ORCA project sources are not shipped with lamad)")
PATH = Path(__file__).resolve().parents[1] / "projects/orca-v1/analysis/lap_translucent.py"
spec = importlib.util.spec_from_file_location("lap_translucent_diagnostic", PATH)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class TranslucentTests(unittest.TestCase):
    def setUp(self):
        self.cube = trimesh.creation.box(extents=(10, 10, 10))
        self.size = 120
        self.camera = diagnostic.camera([(self.cube.vertices, self.cube.faces)], (0, 0, 1), self.size)

    def render(self, mesh, camera=None):
        return np.asarray(diagnostic.transparent_raster(mesh, camera or self.camera, self.size,
                                                       opacity=0.22, edge_opacity=0))

    def test_center_ray_composites_two_surface_layers(self):
        image = self.render(self.cube)
        transmission = (1 - 0.22) ** 2
        # Both plane normals, flipped toward this camera, have lighting .91.
        shade = float(np.float32(0.5 + 0.5 * 0.82))
        expected = np.rint(diagnostic.BG * transmission + diagnostic.BLUE * shade * (1 - transmission)).astype(np.uint8)
        np.testing.assert_array_equal(image[60, 60], expected)
        np.testing.assert_array_equal(image[0, 0], diagnostic.BG)

    def test_internal_surfaces_are_visible_through_front_shell(self):
        inner = trimesh.creation.box(extents=(4, 4, 4))
        inner.invert()
        shell = trimesh.util.concatenate([self.cube, inner])
        original, hollow = self.render(self.cube), self.render(shell)
        self.assertTrue(np.all(hollow[60, 60] < original[60, 60]))
        np.testing.assert_array_equal(hollow[30, 30], original[30, 30])

    def test_duplicate_faces_and_triangle_order_do_not_change_opacity(self):
        camera = diagnostic.camera([(self.cube.vertices, self.cube.faces)], (1, -1, 1), self.size)
        original = self.render(self.cube, camera)
        faces = np.concatenate([self.cube.faces, self.cube.faces])
        np.random.default_rng(42).shuffle(faces)
        duplicated = trimesh.Trimesh(self.cube.vertices, faces, process=False)
        np.testing.assert_array_equal(original, self.render(duplicated, camera))

    def test_triangle_subdivision_does_not_add_surface_layers(self):
        np.testing.assert_array_equal(self.render(self.cube), self.render(self.cube.subdivide()))

    def test_identical_translucent_images_subtract_to_white(self):
        panel = self.render(self.cube)
        delta = np.asarray(diagnostic.image_difference(panel, panel))
        np.testing.assert_array_equal(delta, np.full_like(panel, 255))

    def test_signed_difference_distinguishes_brighter_and_darker(self):
        ours = np.full((1, 1, 3), 200, dtype=np.uint8)
        theirs = np.full((1, 1, 3), 100, dtype=np.uint8)
        positive = np.asarray(diagnostic.image_difference(ours, theirs))[0, 0]
        negative = np.asarray(diagnostic.image_difference(theirs, ours))[0, 0]
        self.assertGreater(positive[0], positive[1])  # Red = ours brighter.
        self.assertLess(negative[0], negative[1])  # Teal = ours darker.
        self.assertTrue(np.all(positive < 255))
        self.assertTrue(np.all(negative < 255))

    def test_difference_uses_fixed_gain_without_normalizing_each_image(self):
        ours = np.full((1, 2, 3), 200, dtype=np.uint8)
        theirs = np.array([[[190, 190, 190], [150, 150, 150]]], dtype=np.uint8)
        result = np.asarray(diagnostic.image_difference(ours, theirs))
        self.assertLess(int(result[0, 1].sum()), int(result[0, 0].sum()))
        separate = np.asarray(diagnostic.image_difference(ours[:, :1], theirs[:, :1]))
        np.testing.assert_array_equal(result[:, :1], separate)
        boosted = np.asarray(diagnostic.image_difference(ours, theirs, gain=2))
        self.assertTrue(np.all(boosted <= result))

    def test_four_row_layout_has_white_third_column_for_identical_models(self):
        with tempfile.TemporaryDirectory(prefix="lap-translucent-test-") as directory:
            output = Path(directory) / "comparison.png"
            diagnostic.render(self.cube, self.cube, output, size=self.size, edge_opacity=0)
            with Image.open(output) as image:
                pixels = np.asarray(image)
                self.assertEqual(image.size, (3 * self.size, 115 + 4 * (self.size + 34)))
                for row in range(4):
                    y = 115 + row * (self.size + 34) + 34
                    panel = pixels[y:y + self.size, 2 * self.size:3 * self.size]
                    np.testing.assert_array_equal(panel, np.full_like(panel, 255))


if __name__ == "__main__":
    unittest.main()
