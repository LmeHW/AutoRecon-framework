import os
import numpy as np
import nibabel as nib
import SimpleITK as sitk


def get_surface_area(dsubj_dir, surface_name):
    coords, faces = nib.freesurfer.read_geometry(os.path.join(dsubj_dir, surface_name))
    tri = coords[faces]                                   # (F,3,3)
    area = 0.5 * np.linalg.norm(np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0]), axis=1).sum()
    return area


def cal_volume(seg_path, low_threshold=0.1, up_threshold=2.1):
    img = nib.load(seg_path)
    data = img.get_fdata() 
    hdr = img.header

    zooms = hdr.get_zooms()[:3]
    voxel_volume_mm3 = float(zooms[0] * zooms[1] * zooms[2])

    mask = (data > low_threshold) & (data < up_threshold)
    n = int(mask.sum())
    vol_mm3 = n * voxel_volume_mm3
    vol_ml = vol_mm3 / 1000.0

    # print("Voxel count:", n)
    # print("Volume: %.2f mm^3 (%.3f mL)" % (vol_mm3, vol_ml))
    return n, vol_ml