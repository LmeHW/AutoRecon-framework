from argparse import Namespace
from typing import List
import torch
from .transform import transform_points, RigidTransform
from .tool import Slice, Volume,load_volume, load_mask
# from .models_mynerf_back import INR,MyNeRF
from .models_mynerf import INR,MyNeRF,Mask
from typing import Dict, Optional, Tuple, Union, List
from .tool import resolution2sigma, meshgrid
import sys

from tqdm import tqdm


def sample_volume(
    model: INR,
    mask: Volume,
    psf_resolution: float,
    batch_size: int = 1024,
    n_samples: int = 128,
) -> Volume:
    model.eval()
    img = mask.clone()
    img.image[img.mask] = sample_points(
        model,
        img.xyz_masked,
        psf_resolution,
        batch_size,
        n_samples,
    )
    return img


def sample_points(
    model: INR,
    xyz: torch.Tensor,
    resolution: float = 0,
    batch_size: int = 1024,
    n_samples: int = 128,
) -> torch.Tensor:
    shape = xyz.shape[:-1]
    xyz = xyz.view(-1, 3)
    v = torch.empty(xyz.shape[0], dtype=torch.float32, device=xyz.device)
    # v = torch.empty(xyz.shape[0], dtype=torch.float16, device=xyz.device)
    with torch.no_grad():
        for i in tqdm(range(0, xyz.shape[0], batch_size)):
            xyz_batch = xyz[i : i + batch_size]
            # print(xyz_batch.shape)
            xyz_batch = model.sample_batch(
                xyz_batch,
                None,
                resolution2sigma(resolution, isotropic=True),
                0 if resolution <= 0 else n_samples,
            )
            v_b = model(xyz_batch,None,None,False).mean(-1)
            v[i : i + batch_size] = v_b
    return v.view(shape)

# def sample_volume(frost: INR, mask: Volume, args: Namespace) -> Volume:
#     frost.eval()
#     img = mask.resample(args.output_resolution, None)
#     img.image[img.mask] = sample_points(frost, img.xyz_masked, args)
#     return img
#
#
# def sample_points(frost: INR, xyz: torch.Tensor, args: Namespace) -> torch.Tensor:
#     shape = xyz.shape[:-1]
#     xyz = xyz.view(-1, 3)
#     v = torch.empty(xyz.shape[0], dtype=torch.float32, device=args.device)
#     # v = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
#     # v = torch.empty(xyz.shape[0], dtype=torch.float16)
#     batch_size = args.inference_batch_size
#     with torch.no_grad():
#         print("batch_size",batch_size)
#         print("xyz.shape[0]",xyz.shape[0])
#         for i in range(0, xyz.shape[0], batch_size):
#             xyz_batch = xyz[i : i + batch_size]
#             xyz_batch = frost.sample_batch(
#                 xyz_batch,
#                 None,
#                 resolution2sigma(args.output_resolution, isotropic=True),
#                 args.n_inference_samples if args.output_psf else 0,
#             )
#             v_b = frost(xyz_batch,None, False).mean(-1)
#             v[i : i + batch_size] = v_b
#     return v.view(shape)



def sample_slice(model: INR, slice: Slice, mask: Volume, args: Namespace) -> Slice:
    # clone the slice
    slice_sampled = slice.clone()
    slice_sampled.image = torch.zeros_like(slice_sampled.image)
    slice_sampled.mask = torch.zeros_like(slice_sampled.mask)
    xyz = meshgrid(slice_sampled.shape_xyz, slice_sampled.resolution_xyz).view(-1, 3)
    # xyz = meshgrid(slice_sampled.shape_xyz, slice_sampled.resolution_xyz).view(-1, 3)
    # print("meshgrid",xyz.dtype)
    # m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > 0
    m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > -1
    # m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > -1
    # print("xyz", xyz.shape)
    # print("xyz[0]", xyz[0])
    # print("mask", mask.image.shape)
    # print("xyz[m]", xyz[m].shape)
    # print("transform", slice_sampled.transformation.axisangle())


    if m.any():
        # v = torch.empty(xyz.shape[0], dtype=torch.float32, device=args.device)
        v = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
        batch_size = args.inference_batch_size
        with torch.no_grad():
            print("batch_size", batch_size)
            print("xyz.shape[0]", xyz.shape[0])
            # print("slice_sampled.mask.shape", slice_sampled.mask.shape)
            for i in range(0, xyz.shape[0], batch_size):
                xyz_batch = xyz[i: i + batch_size]
                xyz_masked = model.sample_batch(
                    xyz_batch,
                    slice_sampled.transformation,
                    resolution2sigma(slice_sampled.resolution_xyz, isotropic=False),
                    args.n_inference_samples if args.output_psf else 0,
                )
                # print("xyz_masked",xyz_masked.shape)
                # print("xyz_masked[0]",xyz_masked[0,0])
                v_b = model(xyz_masked, None,None,False).mean(-1)
                v[i: i + batch_size] = v_b



        slice_sampled.mask = m.view(slice_sampled.mask.shape)
        slice_sampled.image = v.to(slice_sampled.image.dtype).view(slice_sampled.mask.shape)
    return slice_sampled

# def sample_slice(frost: INR, slice: Slice, mask: Volume, args: Namespace) -> Slice:
#     # clone the slice
#     slice_sampled = slice.clone()
#     slice_sampled.image = torch.zeros_like(slice_sampled.image)
#     slice_sampled.mask = torch.zeros_like(slice_sampled.mask)
#     xyz = meshgrid(slice_sampled.shape_xyz, slice_sampled.resolution_xyz).view(-1, 3)
#     m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > 0
#     if m.any():
#         xyz_masked = frost.sample_batch(
#             xyz[m],
#             slice_sampled.transformation,
#             resolution2sigma(slice_sampled.resolution_xyz, isotropic=False),
#             args.n_inference_samples if args.output_psf else 0,
#         )
#         v = frost(xyz_masked, False).mean(-1)
#         slice_sampled.mask = m.view(slice_sampled.mask.shape)
#         slice_sampled.image[slice_sampled.mask] = v.to(slice_sampled.image.dtype)
#     return slice_sampled



def sample_slice_pro(model: MyNeRF, slice: Slice, mask: Volume,slice_idx:int,train_step:int,total_step: int, args: Namespace):
    # frost = frost.to(torch.device('cpu'))
    # slice = slice.to(torch.device('cpu'))
    # mask = mask.to(torch.device('cpu'))


    # clone the slice
    slice_sampled = slice.clone()
    slice_sampled.image = torch.zeros_like(slice_sampled.image)
    slice_sampled.mask = torch.zeros_like(slice_sampled.mask)
    # density2_sampled = slice.clone()
    # density2_sampled.image = torch.zeros_like(slice_sampled.image)
    # density2_sampled.mask = torch.zeros_like(slice_sampled.mask)
    mask_sampled = slice.clone()
    mask_sampled.image = torch.zeros_like(slice_sampled.image)
    mask_sampled.mask = torch.zeros_like(slice_sampled.mask)
    var_sampled = slice.clone()
    var_sampled.image = torch.zeros_like(slice_sampled.image)
    var_sampled.mask = torch.zeros_like(slice_sampled.mask)
    outlier_sampled = slice.clone()
    outlier_sampled.image = torch.zeros_like(slice_sampled.image)
    outlier_sampled.mask = torch.zeros_like(slice_sampled.mask)


    xyz = meshgrid(slice_sampled.shape_xyz, slice_sampled.resolution_xyz).view(-1, 3)
    # print("xyz[0]", xyz[0])
    # xyz /= spatial_scaling
    # print("scaling xyz",xyz)
    # print("transform_points(transformation, xyz)",transform_points(slice_sampled.transformation, xyz))
    # m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > 0
    # m = mask.sample_points(transform_points(transformation, xyz)) > 0
    # print("transform",slice_sampled.transformation.axisangle())
    # m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > 0
    m = mask.sample_points(transform_points(slice_sampled.transformation, xyz)) > -1
    # print("m",m.sum())
    # print("mask",mask.image.sum())
    # print("mask.xyz",mask.xyz_unmasked_untransformed)
    # print("mask.xyz_masked",mask.xyz_masked)
    if m.any():


        # v = torch.empty(xyz.shape[0], dtype=torch.float16, device=torch.device('cpu'))
        # mask = torch.empty(xyz.shape[0], dtype=torch.float16, device=torch.device('cpu'))
        # var = torch.empty(xyz.shape[0], dtype=torch.float16, device=torch.device('cpu'))

        v = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
        mask = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
        var = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
        outlier = torch.empty(xyz.shape[0], dtype=torch.float16, device=args.device)
        batch_size = args.inference_batch_size
        # batch_size = 1024

        with torch.no_grad():
            print("batch_size", batch_size)
            print("xyz.shape[0]", xyz.shape[0])
            # print("slice_sampled.mask.shape", slice_sampled.mask.shape)
            for i in tqdm(range(0, xyz.shape[0], batch_size)):
                xyz_batch = xyz[i: i + batch_size]
                xyz_masked = model.inr.sample_batch(
                    xyz_batch,
                    slice_sampled.transformation,
                    resolution2sigma(slice_sampled.resolution_xyz, isotropic=False),
                    # args.n_inference_samples if args.output_psf else 0,
                    args.n_samples,
                )
                slice_idx_full = torch.full((xyz_masked.shape[0],), slice_idx, device=xyz.device)
                # print("xyz_masked",xyz_masked.shape)
                # print("xyz_masked[0]",xyz_masked[0,0])
                # v_b = frost(xyz_masked, None, None, None, False).mean(-1)
                # print("pro",xyz_masked.shape)
                results = model(xyz_masked, v=None, slice_idx=slice_idx_full, train_step=train_step,
                                total_step=total_step, return_all=False)
                v[i: i + batch_size] = results['density'].mean(-1)
                # mask[i: i + batch_size] = results['mask'].mean(-1)
                # var[i: i + batch_size] = results['log_var'].exp().mean(-1)
                outlier[i: i + batch_size] = 1 -  results['log_outlier'].exp().mean(-1)
                # outlier[i: i + batch_size] = torch.sqrt(results['outlier'])


        # # xyz_masked = frost.inr.sample_batch(
        # #     xyz[m],
        # #     slice_sampled.transformation,
        # #     resolution2sigma(slice_sampled.resolution_xyz, isotropic=False),
        # #     args.n_samples if args.output_psf else 0,
        # # )
        # xyz_masked = frost.inr.sample_batch(
        #     xyz[m],
        #     slice_sampled.transformation,
        #     resolution2sigma(slice_sampled.resolution_xyz, isotropic=False),
        #     args.n_samples,
        #     # 0,
        # )
        #
        # # print("xyz_masked[0]",xyz_masked[0,0])
        # # print("xyz_masked",xyz_masked.shape)
        # slice_idx = torch.full((xyz_masked.shape[0],), slice_idx, device=xyz.device)
        # results = frost(xyz_masked,v=None,slice_idx=slice_idx,gt_mask=None,train_step=train_step,total_step=total_step,return_all= False)
        # # mask = frost(xyz_masked,v=None,slice_idx=slice_idx,return_all= False)
        #
        # v = results['density'].mean(-1)
        # #
        # # # density2 = results['density2'].mean(-1)
        # mask = results['mask'].exp().mean(-1)
        # # mask = mask.mean(-1)
        # # # mask = results['mask']
        # # # var = results['var'].mean(-1)
        # var = results['log_var'].exp().mean(-1)
        # #
        slice_sampled.mask = m.view(slice_sampled.mask.shape)
        slice_sampled.image[slice_sampled.mask] = v.to(slice_sampled.image.dtype)

        # # density2_sampled.mask = m.view(slice_sampled.mask.shape)
        # # density2_sampled.image[slice_sampled.mask] = density2.to(slice_sampled.image.dtype)
        #
        # mask_sampled.mask = m.view(slice_sampled.mask.shape)
        #
        # # mask_sampled.image[mask_sampled.mask] = mask.to(slice_sampled.image.dtype)
        #
        # var_sampled.mask = m.view(slice_sampled.mask.shape)
        # var_sampled.image[slice_sampled.mask] = var.to(slice_sampled.image.dtype)

        outlier_sampled.mask = m.view(slice_sampled.mask.shape)
        outlier_sampled.image[slice_sampled.mask] = outlier.to(slice_sampled.image.dtype)

    # return slice_sampled,density2_sampled,var_sampled
    # return slice_sampled,mask_sampled
    # return mask_sampled
    return slice_sampled,outlier_sampled
    # return slice_sampled,var_sampled,mask_sampled



def sample_slices(
    model: INR, slices: List[Slice], mask: Volume, args: Namespace
) -> List[Slice]:
    model.eval()
    with torch.no_grad():
        slices_sampled = []
        for i, slice in enumerate(slices):
            slices_sampled.append(sample_slice(model, slice, mask, args))
    return slices_sampled
