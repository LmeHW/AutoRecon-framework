from __future__ import annotations


from math import log, sqrt

from os import PathLike

from typing import Dict, List, Any, Optional, Union, Collection, Iterable, Sequence, cast

import collections
from argparse import Namespace
import os
import random

import torch.nn.functional as F
from typing import Tuple, Union, Optional
import os
import nibabel as nib
import torch
import numpy as np
from scipy import ndimage



from frost.transform import (
    RigidTransform,
    transform_points,
    init_stack_transform,
    init_zero_transform,
)



def compare_resolution_shape(r1, r2, s1, s2) -> bool:
    r1 = np.array(r1)

    r2 = np.array(r2)

    if s1 != s2:
        return False
    if r1.shape != r2.shape:
        return False
    if np.amax(np.abs(r1 - r2)) > 1e-3:
        return False
    return True

def compare_resolution_affine(r1, a1, r2, a2, s1, s2) -> bool:
    r1 = np.array(r1)
    a1 = np.array(a1)
    r2 = np.array(r2)
    a2 = np.array(a2)
    if s1 != s2:
        return False
    if r1.shape != r2.shape:
        return False
    if np.amax(np.abs(r1 - r2)) > 1e-3:
        return False
    if a1.shape != a2.shape:
        return False
    if np.amax(np.abs(a1 - a2)) > 1e-3:
        return False
    return True


def affine2transformation(
    volume: torch.Tensor,
    mask: torch.Tensor,
    resolutions: np.ndarray,
    affine: np.ndarray,
) -> Tuple[torch.Tensor, torch.Tensor, RigidTransform]:
    device = volume.device
    d, h, w = volume.shape

    R = affine[:3, :3]
    negative_det = np.linalg.det(R) < 0

    T = affine[:3, -1:]  # T = R @ (-T0 + T_r)
    R = R @ np.linalg.inv(np.diag(resolutions))

    T0 = np.array([(w - 1) / 2 * resolutions[0], (h - 1) / 2 * resolutions[1], 0])
    T = np.linalg.inv(R) @ T + T0.reshape(3, 1)

    tz = (
        torch.arange(0, d, device=device, dtype=torch.float32) * resolutions[2]
        + T[2].item()
    )
    tx = torch.ones_like(tz) * T[0].item()
    ty = torch.ones_like(tz) * T[1].item()
    t = torch.stack((tx, ty, tz), -1).view(-1, 3, 1)
    R = torch.tensor(R, device=device).unsqueeze(0).repeat(d, 1, 1)

    if negative_det:
        volume = torch.flip(volume, (-1,))
        mask = torch.flip(mask, (-1,))
        t[:, 0, -1] *= -1
        R[:, :, 0] *= -1

    transformation = RigidTransform(
        torch.cat((R, t), -1).to(torch.float32), trans_first=True
    )

    return volume, mask, transformation


def transformation2affine(
    volume: torch.Tensor,
    transformation: RigidTransform,
    resolution_x: float,
    resolution_y: float,
    resolution_z: float,
) -> np.ndarray:
    mat = transformation.matrix(trans_first=True).detach().cpu().numpy()
    assert mat.shape[0] == 1
    R = mat[0, :, :-1]
    T = mat[0, :, -1:]
    d, h, w = volume.shape
    affine = np.eye(4)
    T[0] -= (w - 1) / 2 * resolution_x
    T[1] -= (h - 1) / 2 * resolution_y
    T[2] -= (d - 1) / 2 * resolution_z
    T = R @ T.reshape(3, 1)
    R = R @ np.diag([resolution_x, resolution_y, resolution_z])
    affine[:3, :] = np.concatenate((R, T), -1)
    return affine


def save_nii_volume(
    path: PathType,
    volume: Union[torch.Tensor, np.ndarray],
    affine: Optional[Union[torch.Tensor, np.ndarray]],
) -> None:
    assert len(volume.shape) == 3 or (len(volume.shape) == 4 and volume.shape[1] == 1)
    if len(volume.shape) == 4:
        volume = volume.squeeze(1)
    if isinstance(volume, torch.Tensor):
        volume = volume.detach().cpu().numpy().transpose(2, 1, 0)
    else:
        volume = volume.transpose(2, 1, 0)
    if isinstance(affine, torch.Tensor):
        affine = affine.detach().cpu().numpy()
    if affine is None:
        affine = np.eye(4)
    if volume.dtype == bool and isinstance(
        volume, np.ndarray
    ):  # bool type is not supported
        volume = volume.astype(np.int16)
    img = nib.nifti1.Nifti1Image(volume, affine)
    img.header.set_xyzt_units(2)
    img.header.set_qform(affine, code="aligned")
    img.header.set_sform(affine, code="scanner")
    nib.save(img, os.fspath(path))


def load_nii_volume(path: PathType) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    img = nib.load(os.fspath(path))

    dim = img.header["dim"]
    assert dim[0] == 3 or (dim[0] > 3 and all(d == 1 for d in dim[4:])), (
        "Expect a 3D volume but the input is %dD" % dim[0]
    )

    volume = img.get_fdata().astype(np.float32)
    while volume.ndim > 3:
        volume = volume.squeeze(-1)
    volume = volume.transpose(2, 1, 0)

    resolutions = img.header["pixdim"][1:4]

    affine = img.affine
    if np.any(np.isnan(affine)):
        affine = img.get_qform()

    return volume, resolutions, affine





class Image(object):
    def __init__(
            self,
            image: torch.Tensor,
            mask: Optional[torch.Tensor] = None,
            transformation: Optional[RigidTransform] = None,
            resolution_x: Union[float, torch.Tensor] = 1.0,
            resolution_y: Union[float, torch.Tensor] = 1.0,
            resolution_z: Union[float, torch.Tensor] = 1.0,
    ) -> None:
        assert image.ndim == 3
        self.image = image
        if mask is None:
            mask = torch.ones_like(image, dtype=torch.bool)
        self.mask = mask
        self.mask_erosion = ndimage.binary_dilation(mask.detach().cpu().numpy(), iterations=1)

        self.mask_erosion = torch.tensor(self.mask_erosion).to(
            mask.device)
        # self.mask_erosion = mask
        # self.mask_erosion = torch.tensor(ndimage.binary_dilation(mask.detach().cpu().numpy(), iterations=1)).to(mask.device)
        if transformation is None:
            transformation = RigidTransform(
                torch.zeros((1, 6), dtype=torch.float32, device=image.device)
            )
        self.transformation = transformation
        self.resolution_x = resolution_x
        self.resolution_y = resolution_y
        self.resolution_z = resolution_z

    def clone(self, zero: bool = False):
        raise NotImplementedError

    def _clone_image(self, zero: bool = False) -> Dict:
        return {
            "image": torch.zeros_like(self.image) if zero else self.image.clone(),
            "mask": torch.zeros_like(self.mask) if zero else self.mask.clone(),
            "transformation": self.transformation.clone(),
            "resolution_x": float(self.resolution_x),
            "resolution_y": float(self.resolution_y),
            "resolution_z": float(self.resolution_z),
        }

    @property
    def shape_xyz(self) -> torch.Tensor:
        return torch.tensor(self.image.shape[::-1], device=self.image.device)

    @property
    def resolution_xyz(self) -> torch.Tensor:
        return torch.tensor(
            [self.resolution_x, self.resolution_y, self.resolution_z],
            device=self.image.device,
        )

    def save(self, path: str, masked=True) -> None:
        affine = transformation2affine(
            self.image,
            self.transformation,
            float(self.resolution_x),
            float(self.resolution_y),
            float(self.resolution_z),
        )
        if masked:
            output_volume = self.image * self.mask.to(self.image.dtype)
        else:
            output_volume = self.image
        save_nii_volume(path, output_volume, affine)

    @property
    def xyz_masked(self) -> torch.Tensor:
        return transform_points(self.transformation, self.xyz_masked_untransformed)

    @property
    def xyz_masked_untransformed(self) -> torch.Tensor:
        # print("mask",self.mask.shape)
        kji = torch.flip(torch.nonzero(self.mask), (-1,))
        # print("kji",kji.shape)
        return (kji - (self.shape_xyz - 1) / 2) * self.resolution_xyz

    @property
    def v_masked(self) -> torch.Tensor:
        return self.image[self.mask]

    @property
    def xyz_masked_erosion(self) -> torch.Tensor:
        return transform_points(self.transformation, self.xyz_masked_erosion_untransformed)

    @property
    def xyz_masked_erosion_untransformed(self) -> torch.Tensor:
        # print("mask",self.mask.shape)
        kji = torch.flip(torch.nonzero(self.mask_erosion), (-1,))
        # print("kji",kji.shape)
        return (kji - (self.shape_xyz - 1) / 2) * self.resolution_xyz

    @property
    def v_masked_erosion(self) -> torch.Tensor:
        return self.image[self.mask_erosion]

    def rescale(self, intensity_mean: Union[float, torch.Tensor]) -> None:
        scale_factor = intensity_mean / self.image[self.mask].mean()
        self.image *= scale_factor


class Slice(Image):
    def __init__(
            self,
            image: torch.Tensor,
            mask: Optional[torch.Tensor] = None,
            transformation: Optional[RigidTransform] = None,
            resolution_x: Union[float, torch.Tensor] = 1.0,
            resolution_y: Union[float, torch.Tensor] = 1.0,
            resolution_z: Union[float, torch.Tensor] = 1.0,
            stack_idx: Optional[int] = None,
            slice_idx: Optional[int] = None,
    ) -> None:
        super().__init__(
            image, mask, transformation, resolution_x, resolution_y, resolution_z
        )
        self.stack_idx = stack_idx
        self.slice_idx = slice_idx

    def clone(self, zero: bool = False) -> Slice:
        return Slice(
            stack_idx=self.stack_idx,
            slice_idx=self.slice_idx,
            **self._clone_image(zero),
        )


class Volume(Image):
    def sample_points(self, xyz: torch.Tensor) -> torch.Tensor:
        shape = xyz.shape[:-1]
        xyz = transform_points(self.transformation.inv(), xyz.view(-1, 3))
        xyz = xyz / ((self.shape_xyz - 1) * self.resolution_xyz / 2)
        return F.grid_sample(
            self.image[None, None],
            xyz.view(1, 1, 1, -1, 3),
            align_corners=True,
        ).view(shape)

    def resample(
            self,
            resolution_new: Optional[Union[float, torch.Tensor]],
            transformation_new: Optional[RigidTransform],
    ) -> Volume:

        if transformation_new is None:
            transformation_new = self.transformation
        R = transformation_new.matrix()[0, :3, :3]
        dtype = R.dtype
        device = R.device
        if resolution_new is None:
            resolution_new = self.resolution_xyz
        elif isinstance(resolution_new, float) or resolution_new.numel == 1:
            resolution_new = torch.tensor(
                [resolution_new] * 3, dtype=dtype, device=device
            )

        xyz = self.xyz_masked
        # new rotation
        xyz = torch.matmul(torch.inverse(R), xyz.view(-1, 3, 1))[..., 0]

        xyz_min = xyz.amin(0) - resolution_new * 10
        xyz_max = xyz.amax(0) + resolution_new * 10
        shape_xyz = ((xyz_max - xyz_min) / resolution_new).ceil().long()

        mat = torch.zeros((1, 3, 4), dtype=R.dtype, device=R.device)
        mat[0, :, :3] = R
        mat[0, :, -1] = xyz_min + (shape_xyz - 1) / 2 * resolution_new

        xyz = meshgrid(shape_xyz, resolution_new, xyz_min, device, True)

        xyz = torch.matmul(R, xyz[..., None])[..., 0]

        v = self.sample_points(xyz)

        return Volume(
            v,
            v > 0,
            RigidTransform(mat, trans_first=True),
            resolution_new[0].item(),
            resolution_new[1].item(),
            resolution_new[2].item(),
        )

    def clone(self, zero: bool = False) -> Volume:
        return Volume(**self._clone_image(zero))


class Stack(object):
    def __init__(
            self,
            slices: torch.Tensor,
            mask: Optional[torch.Tensor] = None,
            transformation: Optional[RigidTransform] = None,
            score: float = 0.0,
            resolution_x: float = 1.0,
            resolution_y: float = 1.0,
            thickness: float = 1.0,
            gap: float = 1.0,
    ) -> None:
        self.slices = slices
        if mask is None:
            # mask = slices > 0.0
            mask = torch.ones_like(slices, dtype=torch.bool)
        self.mask = mask
        if transformation is None:
            t = torch.zeros(
                (slices.shape[0], 6), dtype=torch.float32, device=slices.device
            )
            t[:, -1] = (
                               torch.arange(slices.shape[0], dtype=torch.float32, device=slices.device)
                               - slices.shape[0] / 2
                       ) * gap
            transformation = RigidTransform(t)
        self.transformation = transformation
        if score is None:
            score = torch.ones(
                slices.shape[0], dtype=torch.float32, device=slices.device
            )
        self.score = score
        self.resolution_x = resolution_x
        self.resolution_y = resolution_y
        self.thickness = thickness
        self.gap = gap

    def __len__(self) -> int:
        return self.slices.shape[0]

    def __getitem__(self, idx):
        assert self.slices.ndim == 4
        slices = self.slices[idx]
        masks = self.mask[idx]

        transformation = self.transformation[idx]
        if slices.ndim < self.slices.ndim:
            return Slice(
                slices,
                masks,
                transformation,
                self.resolution_x,
                self.resolution_y,
                self.thickness,
            )
        else:
            return [
                Slice(
                    slices[i],
                    masks[i],
                    transformation[i],
                    self.resolution_x,
                    self.resolution_y,
                    self.thickness,
                )
                for i in range(len(transformation))
            ]


def get_rectangular_masked_region(nda):
    # Return in case no masked pixel available
    if np.sum(abs(nda)) == 0:
        return None, None, None

    # Get shape defining the dimension in each direction
    shape = nda.shape

    # Compute sum of pixels of each slice along specified directions
    sum_xy = np.sum(nda, axis=(0, 1))  # sum within x-y-plane
    sum_xz = np.sum(nda, axis=(0, 2))  # sum within x-z-plane
    sum_yz = np.sum(nda, axis=(1, 2))  # sum within y-z-plane

    # Find masked regions (non-zero sum!)
    range_x = np.zeros(2)
    range_y = np.zeros(2)
    range_z = np.zeros(2)

    # Non-zero elements of numpy array nda defining x_range
    ran = np.nonzero(sum_yz)[0]
    range_x[0] = np.max([0, ran[0]])
    range_x[1] = np.min([shape[0], ran[-1] + 1])

    # Non-zero elements of numpy array nda defining y_range
    ran = np.nonzero(sum_xz)[0]
    range_y[0] = np.max([0, ran[0]])
    range_y[1] = np.min([shape[1], ran[-1] + 1])

    # Non-zero elements of numpy array nda defining z_range
    ran = np.nonzero(sum_xy)[0]
    range_z[0] = np.max([0, ran[0]])
    range_z[1] = np.min([shape[2], ran[-1] + 1])

    # Numpy reads the array as z,y,x coordinates! So swap them accordingly
    return range_z.astype(int), range_y.astype(int), range_x.astype(int)


def save_nii_volume(
        path: str,
        volume: Union[torch.Tensor, np.ndarray],
        affine: Optional[Union[torch.Tensor, np.ndarray]],
) -> None:
    assert len(volume.shape) == 3 or (len(volume.shape) == 4 and volume.shape[1] == 1)
    if len(volume.shape) == 4:
        volume = volume.squeeze(1)
    if isinstance(volume, torch.Tensor):
        volume = volume.detach().cpu().numpy().transpose(2, 1, 0)
    else:
        volume = volume.transpose(2, 1, 0)
    if isinstance(affine, torch.Tensor):
        affine = affine.detach().cpu().numpy()
    if affine is None:
        affine = np.eye(4)
    img = nib.nifti1.Nifti1Image(volume, affine)
    img.header.set_xyzt_units(2)
    img.header.set_qform(affine, code="aligned")
    img.header.set_sform(affine, code="scanner")
    nib.save(img, path)


def load_nii_volume(path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    img = nib.load(path)

    dim = img.header["dim"]
    assert dim[0] == 3 or (dim[0] > 3 and all(d == 1 for d in dim[4:])), (
            "Expect a 3D volume but the input is %dD" % dim[0]
    )

    volume = img.get_fdata().astype(np.float32)
    while volume.ndim > 3:
        volume = volume.squeeze(-1)
    volume = volume.transpose(2, 1, 0)

    resolutions = img.header["pixdim"][1:4]

    affine = img.affine
    if np.any(np.isnan(affine)):
        affine = img.get_qform()

    return volume, resolutions, affine


def save_slices(folder: str, images: List[Slice]) -> None:
    for i, image in enumerate(images):
        image.save(os.path.join(folder, f"{i}.nii.gz"), True)




def load_slices(folder: str, device=torch.device("cpu")) -> List[Slice]:
    slices = []
    ids = []
    for f in os.listdir(folder):
        if not (f.endswith("nii") or f.endswith("nii.gz")):
            continue
        ids.append(int(f.split(".nii")[0]))
        slice, resolutions, affine = load_nii_volume(os.path.join(folder, f))
        slice_tensor = torch.tensor(slice, device=device)
        mask_tensor = slice_tensor > 0
        slice_tensor, mask_tensor, transformation = affine2transformation(
            slice_tensor, mask_tensor, resolutions, affine
        )
        slices.append(
            Slice(
                image=slice_tensor,
                mask=mask_tensor,
                transformation=transformation,
                resolution_x=resolutions[0],
                resolution_y=resolutions[1],
                resolution_z=resolutions[2],
            )
        )
    return [slice for _, slice in sorted(zip(ids, slices))]


def load_stack(
        path_vol: str, path_mask: Optional[str] = None, device=torch.device("cpu")
) -> Stack:
    slices, resolutions, affine = load_nii_volume(path_vol)
    if path_mask is None:
        # mask = slices > 0
        mask = slices > -1
    else:
        mask, resolutions_m, affine_m = load_nii_volume(path_mask)
        mask = mask > 0

        if not compare_resolution_affine(
                resolutions, affine, resolutions_m, affine_m, slices.shape, mask.shape
        ):
            print(affine)
            print(affine_m)
            raise Exception(
                "Error: the sizes/resolutions/affine transformations of the input stack and stack mask do not match!"
            )

    slices_tensor = torch.tensor(slices, device=device)
    mask_tensor = torch.tensor(mask, device=device)

    slices_tensor, mask_tensor, transformation = affine2transformation(
        slices_tensor, mask_tensor, resolutions, affine
    )

    return Stack(
        slices=slices_tensor.unsqueeze(1),
        mask=mask_tensor.unsqueeze(1),
        transformation=transformation,
        resolution_x=resolutions[0],
        resolution_y=resolutions[1],
        thickness=resolutions[2],
        gap=resolutions[2],
    )


def load_volume(
        path_vol,
        path_mask=None,
        device=torch.device("cpu"),
) -> Volume:
    vol, resolutions, affine = load_nii_volume(path_vol)
    if path_mask is None:
        # mask = vol > 0
        mask = np.ones_like(vol, dtype=bool)
    else:
        mask, resolutions_m, affine_m = load_nii_volume(path_mask)
        mask = mask > 0
        if not compare_resolution_affine(
                resolutions, affine, resolutions_m, affine_m, vol.shape, mask.shape
        ):
            raise Exception(
                "Error: the sizes/resolutions/affine transformations of the input stack and stack mask do not match!"
            )

    vol_tensor = torch.tensor(vol, device=device)
    mask_tensor = torch.tensor(mask, device=device)

    vol_tensor, mask_tensor, transformation = affine2transformation(
        vol_tensor, mask_tensor, resolutions, affine
    )

    transformation = RigidTransform(transformation.axisangle().mean(0, keepdim=True))

    return Volume(
        image=vol_tensor,
        mask=mask_tensor,
        transformation=transformation,
        resolution_x=resolutions[0],
        resolution_y=resolutions[1],
        resolution_z=resolutions[2],
    )


def load_mask(path_mask, device) -> Volume:
    return load_volume(path_mask, path_mask, device)


MASK_PREFIX = "mask_"


PathType = Union[str, PathLike[str]]
DeviceType = Union[torch.device, str, None]
GAUSSIAN_FWHM = 1 / (2 * sqrt(2 * log(2)))
SINC_FWHM = 1.206709128803223 * GAUSSIAN_FWHM


def set_seed(seed: Optional[int]) -> None:
    if seed is not None:
        torch.manual_seed(seed)
        np.random.seed(seed)
        random.seed(seed)


def makedirs(path: Union[str, Iterable[str]]) -> None:
    if isinstance(path, str):
        path = [path]
    for p in path:
        if p:
            try:
                os.makedirs(p, exist_ok=False)
            except FileExistsError:
                pass
            except Exception as e:
                raise e


def merge_args(args_old: Namespace, args_new: Namespace) -> Namespace:
    dict_old = vars(args_old)
    dict_new = vars(args_new)
    dict_old.update(dict_new)
    return Namespace(**dict_old)


def resample(
    x: torch.Tensor, res_xyz_old: Sequence, res_xyz_new: Sequence
) -> torch.Tensor:
    ndim = x.ndim - 2
    assert len(res_xyz_new) == len(res_xyz_old) == ndim
    if all(r_new == r_old for (r_new, r_old) in zip(res_xyz_new, res_xyz_old)):
        return x
    grids = []
    for i in range(ndim):
        fac = res_xyz_old[i] / res_xyz_new[i]
        size_new = int(x.shape[-i - 1] * fac)
        grid_max = (size_new - 1) / fac / (x.shape[-i - 1] - 1)
        grids.append(
            torch.linspace(
                -grid_max, grid_max, size_new, dtype=x.dtype, device=x.device
            )
        )
    grid = torch.stack(torch.meshgrid(*grids[::-1], indexing="ij")[::-1], -1)
    y = F.grid_sample(
        x, grid[None].expand((x.shape[0],) + (-1,) * (ndim + 1)), align_corners=True
    )
    return y


def meshgrid(
    shape_xyz: Collection,
    resolution_xyz: Collection,
    min_xyz: Optional[Collection] = None,
    device: DeviceType = None,
    stack_output: bool = True,
):
    assert len(shape_xyz) == len(resolution_xyz)
    if min_xyz is None:
        min_xyz = tuple(-(s - 1) * r / 2 for s, r in zip(shape_xyz, resolution_xyz))
    else:
        assert len(shape_xyz) == len(min_xyz)

    if device is None:
        if isinstance(shape_xyz, torch.Tensor):
            device = shape_xyz.device
        elif isinstance(resolution_xyz, torch.Tensor):
            device = resolution_xyz.device
        else:
            device = torch.device("cpu")
    dtype = torch.float32

    arr_xyz = [
        torch.arange(s, dtype=dtype, device=device) * r + m
        for s, r, m in zip(shape_xyz, resolution_xyz, min_xyz)
    ]
    grid_xyz = torch.meshgrid(arr_xyz[::-1], indexing="ij")[::-1]
    if stack_output:
        return torch.stack(grid_xyz, -1)
    else:
        return grid_xyz


def gaussian_blur(
    x: torch.Tensor, sigma: Union[float, collections.abc.Iterable], truncated: float
) -> torch.Tensor:
    spatial_dims = len(x.shape) - 2
    if not isinstance(sigma, collections.abc.Iterable):
        sigma = [sigma] * spatial_dims
    kernels = [gaussian_1d_kernel(s, truncated, x.device) for s in sigma]
    c = x.shape[1]
    conv_fn = [F.conv1d, F.conv2d, F.conv3d][spatial_dims - 1]
    for d in range(spatial_dims):
        s = [1] * len(x.shape)
        s[d + 2] = -1
        k = kernels[d].reshape(s).repeat(*([c, 1] + [1] * spatial_dims))
        padding = [0] * spatial_dims
        padding[d] = (k.shape[d + 2] - 1) // 2
        x = conv_fn(x, k, padding=padding, groups=c)
    return x


# from MONAI
def gaussian_1d_kernel(
    sigma: float, truncated: float, device: DeviceType
) -> torch.Tensor:
    tail = int(max(sigma * truncated, 0.5) + 0.5)
    x = torch.arange(-tail, tail + 1, dtype=torch.float, device=device)
    t = 0.70710678 / sigma
    kernel = 0.5 * ((t * (x + 0.5)).erf() - (t * (x - 0.5)).erf())
    return kernel.clamp(min=0)


class MovingAverage:
    def __init__(self, alpha: float) -> None:
        assert 0 <= alpha < 1
        self.alpha = alpha
        self._value: Dict[str, Any] = dict()

    def to_dict(self) -> Dict[str, Any]:
        return {"alpha": self.alpha, "value": self._value}

    def from_dict(self, d: Dict) -> None:
        self.alpha = d["alpha"]
        self._value = d["value"]

    def __getitem__(self, key: str) -> Any:
        if key not in self._value:
            return 0
        num, v = self._value[key]
        if self.alpha:
            return v / (1 - self.alpha**num)
        else:
            return v / num

    def __call__(self, key: str, value) -> None:
        if key not in self._value:
            self._value[key] = (0, 0)
        num, v = self._value[key]
        num += 1
        if self.alpha:
            v = v * self.alpha + value * (1 - self.alpha)
        else:
            v += value
        self._value[key] = (num, v)

    def __str__(self) -> str:
        s = ""
        for key in self._value:
            s += "%s = %.3e  " % (key, self[key])
        if len(self._value) > 0:
            return ("iter = %d  " % self._value[key][0]) + s
        else:
            return s

    @property
    def header(self) -> str:
        return "iter," + ",".join(self._value.keys())

    @property
    def value(self) -> List:
        values = []
        for key in self._value:
            values.append(self[key])
        if len(self._value) > 0:
            return [self._value[key][0]] + values
        else:
            return values




def resolution2sigma(rx, ry=None, rz=None, /, isotropic=False):
    if isotropic:
        fx = fy = fz = GAUSSIAN_FWHM
    else:
        fx = fy = SINC_FWHM
        fz = GAUSSIAN_FWHM
    assert not ((ry is None) ^ (rz is None))
    if ry is None:
        if isinstance(rx, float) or isinstance(rx, int):
            if isotropic:
                return fx * rx
            else:
                return fx * rx, fy * rx, fz * rx
        elif isinstance(rx, torch.Tensor):
            if isotropic:
                return fx * rx
            else:
                assert rx.shape[-1] == 3
                return rx * torch.tensor([fx, fy, fz], dtype=rx.dtype, device=rx.device)
        elif isinstance(rx, List) or isinstance(rx, Tuple):
            assert len(rx) == 3
            return resolution2sigma(rx[0], rx[1], rx[2], isotropic=isotropic)
        else:
            raise Exception(str(type(rx)))
    else:
        return fx * rx, fy * ry, fz * rz


def get_PSF(
    r_max: Optional[int] = None,
    res_ratio: Tuple[float, float, float] = (1, 1, 3),
    threshold: float = 1e-3,
    device: DeviceType = torch.device("cpu"),
    psf_type: str = "gaussian",
) -> torch.Tensor:
    sigma_x, sigma_y, sigma_z = resolution2sigma(res_ratio, isotropic=False)
    if r_max is None:
        r_max = max(int(2 * r + 1) for r in (sigma_x, sigma_y, sigma_z))
        r_max = max(r_max, 4)
    x = torch.linspace(-r_max, r_max, 2 * r_max + 1, dtype=torch.float32, device=device)
    grid_z, grid_y, grid_x = torch.meshgrid(x, x, x, indexing="ij")
    if psf_type == "gaussian":
        psf = torch.exp(
            -0.5
            * (
                grid_x**2 / sigma_x**2
                + grid_y**2 / sigma_y**2
                + grid_z**2 / sigma_z**2
            )
        )
    elif psf_type == "sinc":
        # psf = (
        #     torch.sinc(grid_x / res_ratio[0])
        #     * torch.sinc(grid_y / res_ratio[1])
        #     * torch.exp(-0.5 * grid_z**2 / sigma_z**2)
        # )
        psf = torch.sinc(
            torch.sqrt((grid_x / res_ratio[0]) ** 2 + (grid_y / res_ratio[1]) ** 2)
        ) ** 2 * torch.exp(-0.5 * grid_z**2 / sigma_z**2)
    else:
        raise TypeError(f"Unknown PSF type: <{psf_type}>!")
    psf[psf.abs() < threshold] = 0
    rx = int(torch.nonzero(psf.sum((0, 1)) > 0)[0, 0].item())
    ry = int(torch.nonzero(psf.sum((0, 2)) > 0)[0, 0].item())
    rz = int(torch.nonzero(psf.sum((1, 2)) > 0)[0, 0].item())
    psf = psf[
        rz : 2 * r_max + 1 - rz, ry : 2 * r_max + 1 - ry, rx : 2 * r_max + 1 - rx
    ].contiguous()
    psf = psf / psf.sum()
    return psf


def ncc_loss(
    I: torch.Tensor,
    J: torch.Tensor,
    mask: Optional[torch.Tensor] = None,
    win: Optional[int] = 9,
    level: int = 0,
    eps: float = 1e-6,
    reduction: str = "none",
) -> torch.Tensor:
    spatial_dims = len(I.shape) - 2
    assert spatial_dims in (1, 2, 3), "ncc_loss only support 3D, 4D, and 5D data"

    if mask is not None:
        I = I * mask
        J = J * mask

    c = I.shape[1]

    if win is None:
        I = torch.flatten(I, 1)
        J = torch.flatten(J, 1)
        if mask is not None:
            mask = torch.flatten(mask, 1)
            N = mask.sum(-1) + eps
            I_mean = I.sum(-1) / N
            J_mean = J.sum(-1) / N
            I2_mean = (I * I).sum(-1) / N
            J2_mean = (J * J).sum(-1) / N
            IJ_mean = (I * J).sum(-1) / N
        else:
            I_mean = I.mean(-1)
            J_mean = J.mean(-1)
            I2_mean = (I * I).mean(-1)
            J2_mean = (J * J).mean(-1)
            IJ_mean = (I * J).mean(-1)
    else:
        I = I.view(-1, 1, *I.shape[2:])
        J = J.view(-1, 1, *J.shape[2:])

        win = 2 * int(win / 2**level / 2) + 1

        mean_filt = torch.ones([1, 1] + [win] * spatial_dims, device=I.device) / (
            win**spatial_dims
        )
        conv_fn = [F.conv1d, F.conv2d, F.conv3d][spatial_dims - 1]

        I_mean = conv_fn(I, mean_filt, stride=1, padding=win // 2)
        J_mean = conv_fn(J, mean_filt, stride=1, padding=win // 2)
        I2_mean = conv_fn(I * I, mean_filt, stride=1, padding=win // 2)
        J2_mean = conv_fn(J * J, mean_filt, stride=1, padding=win // 2)
        IJ_mean = conv_fn(I * J, mean_filt, stride=1, padding=win // 2)

    cross = IJ_mean - I_mean * J_mean
    I_var = I2_mean - I_mean * I_mean
    J_var = J2_mean - J_mean * J_mean

    cc = cross * cross / (I_var * J_var + eps)

    if reduction == "mean":
        return -cc.mean()
    elif reduction == "sum":
        return -cc.sum()
    else:
        if win is None:
            return -cc.view(-1, c)
        else:
            return -cc.view(-1, c, *I.shape[2:])


def ssim_loss(
    I: torch.Tensor,
    J: torch.Tensor,
    mask: Optional[torch.Tensor] = None,
    win: int = 11,
    sigma: float = 1.5,
    reduction: str = "none",
) -> torch.Tensor:
    # normalization
    I_min = I.min()
    I_max = I.max()
    J_min = J.min()
    J_max = J.max()
    I = (I - I_min) / (I_max - I_min)
    J = (J - J_min) / (J_max - J_min)
    # params
    spatial_dims = len(I.shape) - 2
    C1 = 0.01**2
    C2 = 0.03**2
    truncated = win / 2 / sigma - 0.5
    compensation = 1.0

    mu1 = gaussian_blur(I, sigma, truncated)
    mu2 = gaussian_blur(J, sigma, truncated)

    mu1_sq = mu1.pow(2)
    mu2_sq = mu2.pow(2)
    mu1_mu2 = mu1 * mu2

    sigma1_sq = compensation * (gaussian_blur(I * I, sigma, truncated) - mu1_sq)
    sigma2_sq = compensation * (gaussian_blur(J * J, sigma, truncated) - mu2_sq)
    sigma12 = compensation * (gaussian_blur(I * J, sigma, truncated) - mu1_mu2)

    cs_map = (2 * sigma12 + C2) / (sigma1_sq + sigma2_sq + C2)  # set alpha=beta=gamma=1
    ssim_map = ((2 * mu1_mu2 + C1) / (mu1_sq + mu2_sq + C1)) * cs_map

    if mask is not None:
        ssim_map = ssim_map * mask

    if reduction == "mean":
        return -ssim_map.mean()
    elif reduction == "sum":
        return -ssim_map.sum()
    else:
        return -ssim_map



