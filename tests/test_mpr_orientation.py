from __future__ import annotations

import unittest

import numpy as np

from pipeline.vis.mpr_orientation import (
    anatomical_display_score,
    mirror_correlation,
    radiological_plane_arrays,
    radiological_plane_spacings,
)


class MprOrientationTests(unittest.TestCase):
    def test_radiological_planes_keep_si_vertical_for_sag_and_cor(self):
        volume = np.zeros((5, 4, 3), dtype=np.float32)
        volume[4, 1, 1] = 10  # superior marker
        volume[2, 3, 1] = 7  # posterior marker
        volume[2, 1, 2] = 5  # left marker
        planes = radiological_plane_arrays(volume, (2, 1, 1))

        self.assertEqual(planes["sagittal"].shape, (5, 4))
        self.assertEqual(planes["coronal"].shape, (5, 3))
        self.assertEqual(planes["axial"].shape, (4, 3))
        # flipud puts superior (z=4) at the top row
        self.assertEqual(float(planes["sagittal"][0, 1]), 10.0)
        self.assertEqual(float(planes["coronal"][0, 1]), 10.0)
        # axial keeps anterior (y=0) at the top for LPS
        self.assertEqual(float(planes["axial"][3, 1]), 7.0)
        self.assertEqual(float(planes["axial"][1, 2]), 5.0)

    def test_plane_spacings_match_radiological_axes(self):
        spacings = radiological_plane_spacings((1.0, 2.0, 3.0))
        self.assertEqual(spacings["sagittal"], (3.0, 2.0))
        self.assertEqual(spacings["coronal"], (3.0, 1.0))
        self.assertEqual(spacings["axial"], (2.0, 1.0))

    def test_mirror_score_prefers_true_left_right_axis(self):
        volume = np.zeros((8, 8, 8), dtype=np.float32)
        zz, yy, xx = np.indices(volume.shape)
        # Bilateral lobes symmetric across X; elongated and asymmetric along Z.
        volume[((xx - 2) ** 2 + (yy - 4) ** 2 + ((zz - 3) ** 2) / 4) < 3.2] = 1
        volume[((xx - 5) ** 2 + (yy - 4) ** 2 + ((zz - 3) ** 2) / 4) < 3.2] = 1
        volume[zz >= 6] *= 0.2
        self.assertGreater(mirror_correlation(volume, 2), mirror_correlation(volume, 0))
        self.assertGreater(anatomical_display_score(volume), 0.0)

    def test_score_prefers_ap_on_y_matching_fetal_atlas(self):
        # Longest axis AP (Y), medium SI (Z), bilateral LR (X) — same proportions as the atlas.
        volume = np.zeros((12, 18, 10), dtype=np.float32)
        zz, yy, xx = np.indices(volume.shape)
        volume[((xx - 3) ** 2 + ((yy - 9) ** 2) / 4.8 + ((zz - 6) ** 2) / 1.6) < 3.2] = 1
        volume[((xx - 6) ** 2 + ((yy - 9) ** 2) / 4.8 + ((zz - 6) ** 2) / 1.6) < 3.2] = 1
        swapped = np.transpose(volume, (1, 0, 2))
        self.assertGreater(anatomical_display_score(volume), anatomical_display_score(swapped))

    def test_score_prefers_superior_up_not_inverted(self):
        volume = np.zeros((20, 16, 14), dtype=np.float32)
        zz, yy, xx = np.indices(volume.shape)
        # Cone along Z: wide vault at high Z, narrow neck at low Z; bilateral on X.
        ry = 1.2 + 0.22 * zz
        rx = 0.9 + 0.12 * zz
        volume[(((xx - 5) / rx) ** 2 + ((yy - 8) / ry) ** 2 + ((zz - 10) / 7.0) ** 2) < 1.0] = 1
        volume[(((xx - 8) / rx) ** 2 + ((yy - 8) / ry) ** 2 + ((zz - 10) / 7.0) ** 2) < 1.0] = 1
        inverted = np.flip(volume, 0)
        self.assertGreater(anatomical_display_score(volume), anatomical_display_score(inverted))


if __name__ == "__main__":
    unittest.main()
