#!/usr/bin/env python3
"""Render presentation-only assets from a completed single-case pipeline."""

import argparse
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from PIL import Image
from scipy import ndimage


PALETTE = np.array(
    [
        [0, 0, 0],
        [238, 92, 94],
        [73, 169, 221],
        [246, 196, 68],
        [104, 190, 120],
        [173, 116, 210],
        [244, 137, 74],
        [72, 201, 181],
        [222, 112, 170],
    ],
    dtype=np.uint8,
)


def read_array(path):
    return sitk.GetArrayFromImage(sitk.ReadImage(str(path)))


def largest_component(mask):
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == sizes.argmax()


def intensity_mask(volume):
    finite = volume[np.isfinite(volume)]
    positive = finite[finite > 0]
    if positive.size == 0:
        return np.zeros(volume.shape, dtype=bool)
    threshold = np.percentile(positive, 8)
    mask = volume > threshold
    mask = ndimage.binary_closing(mask, iterations=2)
    return largest_component(mask)


def principal_axis_transform(mask, size=220):
    coords = np.argwhere(mask)
    if coords.shape[0] < 100:
        raise ValueError("Not enough foreground voxels for principal-axis alignment")

    center = coords.mean(axis=0)
    covariance = np.cov((coords - center).T)
    values, vectors = np.linalg.eigh(covariance)
    vectors = vectors[:, np.argsort(values)]  # z=short, y=middle, x=long

    for axis in range(3):
        dominant = np.argmax(np.abs(vectors[:, axis]))
        if vectors[dominant, axis] < 0:
            vectors[:, axis] *= -1
    if np.linalg.det(vectors) < 0:
        vectors[:, 2] *= -1

    projected = (coords - center) @ vectors
    extent = np.max(projected.max(axis=0) - projected.min(axis=0)) * 1.22
    step = extent / (size - 1)
    matrix = vectors * step
    output_center = np.full(3, (size - 1) / 2.0)
    offset = center - matrix @ output_center
    return matrix, offset, (size, size, size)


def resample(volume, transform, order):
    matrix, offset, output_shape = transform
    return ndimage.affine_transform(
        volume,
        matrix=matrix,
        offset=offset,
        output_shape=output_shape,
        order=order,
        mode="constant",
        cval=0,
        prefilter=order > 1,
    )


def normalize(image):
    valid = image[np.isfinite(image) & (image != 0)]
    if valid.size == 0:
        return np.zeros(image.shape, dtype=np.float32)
    low, high = np.percentile(valid, [1, 99])
    if high <= low:
        high = low + 1
    return np.clip((image - low) / (high - low), 0, 1)


def plane(array, axis):
    index = array.shape[axis] // 2
    image = np.take(array, index, axis=axis)
    return np.flipud(image)


def compose(gray, labels=None):
    base = (normalize(gray)[..., None] * 255).astype(np.uint8)
    rgb = np.repeat(base, 3, axis=2)
    if labels is None:
        return rgb
    labels = labels.astype(np.int64)
    active = labels > 0
    colors = PALETTE[labels % len(PALETTE)]
    rgb[active] = (0.48 * rgb[active] + 0.52 * colors[active]).astype(np.uint8)
    return rgb


def save_orthogonal(prefix, image, out_dir, labels=None):
    names = ((0, "axial"), (1, "coronal"), (2, "sagittal"))
    for axis, name in names:
        gray_plane = plane(image, axis)
        label_plane = plane(labels, axis) if labels is not None else None
        Image.fromarray(compose(gray_plane, label_plane)).save(out_dir / f"{prefix}_{name}.png")


def crop_masked_slice(image, mask, pad=8):
    coords = np.argwhere(mask)
    if coords.size == 0:
        return compose(image)
    low = np.maximum(coords.min(axis=0) - pad, 0)
    high = np.minimum(coords.max(axis=0) + pad + 1, image.shape)
    image = image[low[0] : high[0], low[1] : high[1]]
    mask = mask[low[0] : high[0], low[1] : high[1]]
    rgb = compose(image)
    overlay = np.array([80, 222, 126], dtype=np.uint8)
    rgb[mask] = (0.42 * rgb[mask] + 0.58 * overlay).astype(np.uint8)
    return rgb


def save_extraction_slices(image_path, mask_path, out_dir):
    volume = read_array(image_path).astype(np.float32)
    masks = read_array(mask_path) > 0
    counts = masks.reshape(masks.shape[0], -1).sum(axis=1)
    valid = np.flatnonzero(counts > 0)
    if valid.size == 0:
        raise ValueError("Extraction mask contains no foreground slices")
    indices = np.linspace(valid.min(), valid.max(), 5).round().astype(int)
    for number, index in enumerate(indices, start=1):
        rgb = crop_masked_slice(volume[index], masks[index])
        asset = Image.fromarray(rgb).resize((210, 160), Image.Resampling.LANCZOS)
        asset.save(out_dir / f"step01_slice_{number}.png")


def first_file(directory, pattern="*.nii.gz"):
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} under {directory}")
    return files[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    subject_dirs = sorted(path for path in (work_root / "staging").iterdir() if path.is_dir())
    if not subject_dirs:
        raise FileNotFoundError("No staged subject directory found")
    subject_dir = subject_dirs[0]
    extraction_image = first_file(subject_dir, "BTFE_TRA_*.nii.gz")
    extraction_mask = subject_dir / "seg" / extraction_image.name
    save_extraction_slices(extraction_image, extraction_mask, out_dir)

    recon_path = first_file(work_root / "outputs" / "recon")
    tissue_path = work_root / "outputs" / "Tissue" / recon_path.name
    roi_path = work_root / "outputs" / "ROI" / recon_path.name
    registered_path = first_file(work_root / "outputs" / "registration", "**/*Warped.nii.gz")

    recon = read_array(recon_path).astype(np.float32)
    tissue = read_array(tissue_path)
    roi = read_array(roi_path)
    recon_mask = largest_component(tissue > 0)
    recon_transform = principal_axis_transform(recon_mask)
    aligned_recon = resample(recon, recon_transform, order=1)
    aligned_tissue = resample(tissue, recon_transform, order=0)
    aligned_roi = resample(roi, recon_transform, order=0)

    save_orthogonal("step02", aligned_recon, out_dir)

    registered = read_array(registered_path).astype(np.float32)
    registered_transform = principal_axis_transform(intensity_mask(registered))
    aligned_registered = resample(registered, registered_transform, order=1)
    save_orthogonal("step03", aligned_registered, out_dir)
    save_orthogonal("step04", aligned_recon, out_dir, aligned_tissue)
    save_orthogonal("step05", aligned_recon, out_dir, aligned_roi)

    print(f"Wrote slide assets to {out_dir}")


if __name__ == "__main__":
    main()
