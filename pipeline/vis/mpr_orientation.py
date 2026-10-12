"""Radiological MPR plane extraction and optional anatomical uprighting for display."""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np


def mirror_correlation(volume: np.ndarray, axis: int) -> float:
    data = np.asarray(volume, dtype=np.float32)
    flipped = np.flip(data, axis=axis)
    denom = float(np.linalg.norm(data) * np.linalg.norm(flipped)) + 1e-8
    return float(np.vdot(data, flipped) / denom)


def plane_lr_correlation(plane: np.ndarray) -> float:
    data = np.asarray(plane, dtype=np.float32)
    flipped = np.fliplr(data)
    denom = float(np.linalg.norm(data) ** 2) + 1e-8
    return float(np.vdot(data, flipped) / denom)


def _plane_bbox_hw(plane: np.ndarray) -> tuple[float, float]:
    data = np.asarray(plane, dtype=np.float32)
    positive = data[data > 0]
    threshold = float(np.percentile(positive, 30)) if positive.size else 0.0
    coords = np.argwhere(data > threshold)
    if coords.shape[0] < 8:
        rows, cols = data.shape[:2]
        return float(max(rows, 1)), float(max(cols, 1))
    r0, c0 = coords.min(axis=0)
    r1, c1 = coords.max(axis=0)
    return float(r1 - r0 + 1), float(c1 - c0 + 1)


def _si_ap_assignment_score(coronal: np.ndarray, axial: np.ndarray) -> float:
    """Prefer Y=AP / Z=SI to match the atlas: fetal AP extent is typically >= SI.

    Axial height is AP; coronal height is SI. A swapped assignment makes the
    coronal panel look like a top-down axial slice.
    """
    ch, cw = _plane_bbox_hw(coronal)
    ah, aw = _plane_bbox_hw(axial)
    coronal_aspect = ch / max(cw, 1.0)
    axial_aspect = ah / max(aw, 1.0)
    return float(np.log(max(axial_aspect, 1e-3)) - np.log(max(coronal_aspect, 1e-3)))


def _superior_up_score(coronal: np.ndarray) -> float:
    """After SI-up flipud, the cranial vault should be wider than the neck (top vs bottom)."""
    data = np.asarray(coronal, dtype=np.float32)
    positive = data[data > 0]
    if positive.size == 0:
        return 0.0
    threshold = float(np.percentile(positive, 30))
    if threshold >= float(positive.max()):
        threshold = 0.0
    mask = data > threshold
    widths = mask.sum(axis=1).astype(np.float64)
    occupied = np.flatnonzero(widths > 0)
    if occupied.size < 4 or float(widths.max()) < 4:
        return 0.0
    slab = widths[int(occupied[0]) : int(occupied[-1]) + 1]
    band = max(int(slab.shape[0] * 0.35), 1)
    top_w = float(slab[:band].mean())
    bot_w = float(slab[-band:].mean())
    return (top_w - bot_w) / (top_w + bot_w + 1e-8)


def anatomical_display_score(volume_zyx: np.ndarray) -> float:
    """Higher when X≈LR, Z≈SI (superior up), Y≈AP, and mid slices are left-right symmetric."""
    arr = np.asarray(volume_zyx, dtype=np.float32)
    z, y, x = arr.shape
    cz, cy, cx = z // 2, y // 2, x // 2
    sagittal = np.flipud(arr[:, :, cx])
    coronal = np.flipud(arr[:, cy, :])
    axial = arr[cz, :, :]
    return (
        mirror_correlation(arr, 2) * 3.0
        + plane_lr_correlation(coronal) * 1.5
        + plane_lr_correlation(axial) * 1.5
        + plane_lr_correlation(sagittal) * 0.2
        + _si_ap_assignment_score(coronal, axial) * 2.5
        + _superior_up_score(coronal) * 2.0
    )


def radiological_plane_arrays(
    volume_zyx: np.ndarray,
    center_zyx: tuple[int, int, int],
) -> dict[str, np.ndarray]:
    """Extract sag/cor/ax with superior-up (sag/cor) and anterior-up (axial) for LPS arrays."""
    cz, cy, cx = (int(v) for v in center_zyx)
    arr = np.asarray(volume_zyx)
    return {
        "sagittal": np.flipud(arr[:, :, cx]),  # (SI, AP)
        "coronal": np.flipud(arr[:, cy, :]),  # (SI, LR)
        "axial": arr[cz, :, :],  # (AP, LR), anterior at top in LPS
    }


def radiological_plane_spacings(spacing_xyz: tuple[float, float, float] | list[float]) -> dict[str, tuple[float, float]]:
    """Return (row_spacing, col_spacing) for each radiological plane."""
    sx, sy, sz = (float(v) for v in spacing_xyz)
    return {
        "sagittal": (sz, sy),
        "coronal": (sz, sx),
        "axial": (sy, sx),
    }


def _foreground_threshold(volume: np.ndarray) -> float:
    positive = volume[volume > 0]
    if positive.size == 0:
        return 0.0
    return float(np.percentile(positive, 30))


def _physical_corners(image: Any) -> np.ndarray:
    size = np.asarray(image.GetSize(), dtype=np.float64)
    corners = []
    for iz in (0.0, max(size[2] - 1.0, 0.0)):
        for iy in (0.0, max(size[1] - 1.0, 0.0)):
            for ix in (0.0, max(size[0] - 1.0, 0.0)):
                corners.append(image.TransformContinuousIndexToPhysicalPoint((float(ix), float(iy), float(iz))))
    return np.asarray(corners, dtype=np.float64)


def _resample_with_direction(image: Any, direction_xyz_cols: np.ndarray, center_index_zyx: np.ndarray, phys_points: np.ndarray) -> Any:
    import SimpleITK as sitk

    spacing = np.asarray(image.GetSpacing(), dtype=np.float64)
    direction = np.asarray(direction_xyz_cols, dtype=np.float64)
    if float(np.linalg.det(direction)) < 0:
        direction = direction.copy()
        direction[:, 0] *= -1
    sp = float(np.mean(spacing))
    center_phys = np.asarray(
        image.TransformContinuousIndexToPhysicalPoint(
            [float(center_index_zyx[2]), float(center_index_zyx[1]), float(center_index_zyx[0])]
        ),
        dtype=np.float64,
    )
    # Size the new grid from the original FOV corners, not just foreground, so rotation does not crop anatomy.
    corner_delta = _physical_corners(image) - center_phys
    projected = np.vstack((phys_points, corner_delta)) @ direction
    mins = projected.min(axis=0)
    maxs = projected.max(axis=0)
    sizes = np.maximum(np.ceil((maxs - mins) / sp).astype(int) + 8, 16)
    new = sitk.Image([int(v) for v in sizes], image.GetPixelID())
    new.SetSpacing((sp, sp, sp))
    new.SetDirection(tuple(direction.ravel().tolist()))
    half = (sizes.astype(np.float64) - 1.0) * sp / 2.0
    new.SetOrigin(tuple((center_phys - direction @ half).tolist()))
    return sitk.Resample(image, new, sitk.Transform(), sitk.sitkLinear, 0.0, image.GetPixelID())


def align_volume_anatomically(image: Any, overlay: Any | None = None, *, min_improvement: float = 0.12) -> tuple[Any, Any | None, bool]:
    """Rigidly upright a volume for MPR display when the current pose scores poorly.

    Keeps the volume unchanged when the current LPS array already looks anatomically labeled.
    Overlay is resampled with nearest-neighbor using the same geometry when provided.
    """
    import SimpleITK as sitk

    oriented = sitk.DICOMOrient(image, "LPS")
    oriented_overlay = sitk.DICOMOrient(overlay, "LPS") if overlay is not None else None
    arr = sitk.GetArrayFromImage(oriented).astype(np.float32)
    if arr.ndim != 3 or arr.size < 8:
        return oriented, oriented_overlay, False

    current_score = anatomical_display_score(arr)
    spacing = np.asarray(oriented.GetSpacing(), dtype=np.float64)
    threshold = _foreground_threshold(arr)
    coords = np.argwhere(arr > threshold)
    if coords.shape[0] < 64:
        return oriented, oriented_overlay, False

    center = coords.mean(axis=0)
    delta = coords - center
    phys = np.stack(
        [delta[:, 2] * spacing[0], delta[:, 1] * spacing[1], delta[:, 0] * spacing[2]],
        axis=1,
    )
    covariance = np.cov(phys.T)
    if not np.isfinite(covariance).all():
        return oriented, oriented_overlay, False
    evals, evecs = np.linalg.eigh(covariance)
    evecs = evecs[:, np.argsort(evals)[::-1]]

    best_score = current_score
    best_direction = None
    for perm in itertools.permutations((0, 1, 2)):
        for signs in itertools.product((-1.0, 1.0), repeat=3):
            direction = evecs[:, list(perm)] * np.asarray(signs, dtype=np.float64)
            if float(np.linalg.det(direction)) <= 0.5:
                continue
            candidate = _resample_with_direction(oriented, direction, center, phys)
            candidate_arr = sitk.GetArrayFromImage(candidate).astype(np.float32)
            score = anatomical_display_score(candidate_arr)
            if score > best_score:
                best_score = score
                best_direction = direction

    if best_direction is None or (best_score - current_score) < float(min_improvement):
        working = oriented
        working_overlay = oriented_overlay
        changed = False
    else:
        working = _resample_with_direction(oriented, best_direction, center, phys)
        working_overlay = None
        if oriented_overlay is not None:
            working_overlay = sitk.Resample(
                oriented_overlay,
                working,
                sitk.Transform(),
                sitk.sitkNearestNeighbor,
                0.0,
                oriented_overlay.GetPixelID(),
            )
        changed = True

    refined, refined_overlay, refined_changed = _refine_inplane_level(working, working_overlay)
    return refined, refined_overlay, changed or refined_changed


def _sagittal_level_score(volume_zyx: np.ndarray) -> float:
    """Prefer SI-up sagittal: brainstem/neck mass inferior, not SI laid along columns."""
    arr = np.asarray(volume_zyx, dtype=np.float32)
    threshold = _foreground_threshold(arr)
    sag = np.flipud(arr[:, :, arr.shape[2] // 2] > threshold)
    coords = np.argwhere(sag)
    if coords.shape[0] < 32:
        return 0.0
    covariance = np.cov(coords.T.astype(np.float64))
    if not np.isfinite(covariance).all():
        return 0.0
    _evals, evecs = np.linalg.eigh(covariance)
    major = evecs[:, -1]
    # major[0]=row/SI, major[1]=col/AP. Fetal profile is longer AP, so major axis is horizontal.
    horizontal = 1.0 - min(1.0, abs(float(major[0])))
    lower_frac = float(coords[coords[:, 0] >= sag.shape[0] / 2].shape[0]) / float(coords.shape[0])
    return horizontal * 1.2 + (1.0 - abs(lower_frac - 0.55))


def _refine_display_score(volume_zyx: np.ndarray) -> float:
    return anatomical_display_score(volume_zyx) + _sagittal_level_score(volume_zyx)


def _refine_inplane_level(image: Any, overlay: Any | None = None) -> tuple[Any, Any | None, bool]:
    """Small pitch/roll search to reduce residual head tilt after PCA uprighting."""
    import SimpleITK as sitk

    arr = sitk.GetArrayFromImage(image).astype(np.float32)
    best_score = _refine_display_score(arr)
    baseline_anatomy = anatomical_display_score(arr)
    threshold = _foreground_threshold(arr)
    coords = np.argwhere(arr > threshold)
    if coords.shape[0] < 64:
        return image, overlay, False
    center_idx = coords.mean(axis=0)
    center_phys = image.TransformContinuousIndexToPhysicalPoint(
        [float(center_idx[2]), float(center_idx[1]), float(center_idx[0])]
    )
    best = None
    for pitch in np.linspace(-0.9, 0.9, 13):
        for roll in np.linspace(-0.9, 0.9, 13):
            if abs(pitch) < 1e-6 and abs(roll) < 1e-6:
                continue
            transform = sitk.Euler3DTransform()
            transform.SetCenter(center_phys)
            transform.SetRotation(float(pitch), 0.0, float(roll))
            candidate = sitk.Resample(image, image, transform, sitk.sitkLinear, 0.0, image.GetPixelID())
            candidate_arr = sitk.GetArrayFromImage(candidate).astype(np.float32)
            anatomy = anatomical_display_score(candidate_arr)
            if anatomy + 1e-6 < baseline_anatomy:
                continue
            score = _refine_display_score(candidate_arr)
            if score > best_score + 0.05:
                best_score = score
                best = (candidate, transform)

    if best is None:
        return image, overlay, False
    _, transform = best
    pad = [max(int(s) // 4, 8) for s in image.GetSize()]
    reference = sitk.ConstantPad(image, pad, pad, 0.0)
    candidate = sitk.Resample(image, reference, transform, sitk.sitkLinear, 0.0, image.GetPixelID())
    refined_overlay = None
    if overlay is not None:
        refined_overlay = sitk.Resample(
            overlay,
            candidate,
            transform,
            sitk.sitkNearestNeighbor,
            0.0,
            overlay.GetPixelID(),
        )
    return candidate, refined_overlay, True


def prepare_mpr_volume(
    image: Any,
    overlay: Any | None = None,
    *,
    align_anatomical: bool = False,
) -> tuple[np.ndarray, np.ndarray | None, tuple[float, float, float], bool]:
    """Return display arrays (zyx), spacing xyz, and whether anatomical align ran."""
    import SimpleITK as sitk

    if align_anatomical:
        image, overlay, aligned = align_volume_anatomically(image, overlay)
    else:
        image = sitk.DICOMOrient(image, "LPS")
        overlay = sitk.DICOMOrient(overlay, "LPS") if overlay is not None else None
        aligned = False

    volume = np.asarray(sitk.GetArrayFromImage(image), dtype=np.float32)
    overlay_arr = None
    if overlay is not None:
        overlay_arr = np.asarray(sitk.GetArrayFromImage(overlay))
        if overlay_arr.ndim == 4:
            overlay_arr = overlay_arr[0]
        if overlay_arr.shape != volume.shape:
            overlay_arr = None
    if volume.ndim == 4:
        volume = volume[0]
    spacing = tuple(float(v) for v in image.GetSpacing())
    return volume, overlay_arr, spacing, aligned
