import os.path
import sys
from argparse import Namespace
from typing import Dict, Tuple,Callable, List, Any
import time
import datetime
import torch
import torch.optim as optim
import logging
from .tool import MovingAverage, gaussian_blur,resolution2sigma
from .models_mynerf import  INR, D_LOSS, I_REG, T_REG,MyNeRF,D_REG,REG_LOSS
from .transform import RigidTransform, transform_points
from .tool import Volume, Slice

from .sample_mynerf import sample_slice,sample_slice_pro

from matplotlib import pyplot as plt
import numpy as np
import SimpleITK as sitk

class LazyLog(object):
    def __init__(self, func: Callable[..., Any], *args, **kwargs) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __str__(self) -> str:
        return self.func(*self.args, **self.kwargs)

def _log_params(
    model: torch.nn.Module,
    name_len: int = 25,
    shape_len: int = 20,
    n_param_len: int = 20,
) -> str:
    sep_len = name_len + shape_len + n_param_len + 3
    sep = "-" * sep_len
    template = f"%{name_len}s %{shape_len}s %{n_param_len}s\n"
    args: List = ["Name", "Shape", "# Param"]
    for name, param in model.named_parameters():
        args.extend([name, list(param.shape), param.numel()])
    template = "trainable parameters in %s\n%s\n" + template * (len(args) // 3) + "%s"
    return template % (model.__class__.__name__, sep, *args, sep)

def log_params(model: torch.nn.Module) -> LazyLog:
    return LazyLog(_log_params, model)

class Dataset(object):
    def __init__(self, slices: List[Slice]) -> None:
        self.mask_threshold = 1  # args.mask_threshold
        # self.mask_threshold = 0.1  # args.mask_threshold
        # self.mask_threshold = 0.01  # args.mask_threshold
        # self.mask_threshold = 0  # args.mask_threshold
        self.slices =slices

        xyz_all = []
        xyz_erosion_all = []
        v_all = []
        v_erosion_all = []
        slice_idx_all = []
        slice_idx_erosion_all = []
        transformation_all = []
        resolution_all = []

        for i, slice in enumerate(slices):
            xyz = slice.xyz_masked_untransformed
            v = slice.v_masked
            xyz_erosion = slice.xyz_masked_erosion_untransformed
            v_erosion = slice.v_masked_erosion
            slice_idx = torch.full(v.shape, i, device=v.device)
            slice_idx_erosion = torch.full(v_erosion.shape, i, device=v.device)
            xyz_all.append(xyz)
            xyz_erosion_all.append(xyz_erosion)
            v_all.append(v)
            v_erosion_all.append(v_erosion)
            slice_idx_all.append(slice_idx)
            slice_idx_erosion_all.append(slice_idx_erosion)
            transformation_all.append(slice.transformation)
            resolution_all.append(slice.resolution_xyz)

        self.xyz = torch.cat(xyz_all)
        self.xyz_erosion = torch.cat(xyz_erosion_all)
        self.v = torch.cat(v_all)
        self.v_erosion = torch.cat(v_erosion_all)
        self.slice_idx = torch.cat(slice_idx_all)
        self.slice_idx_erosion = torch.cat(slice_idx_erosion_all)
        self.transformation = RigidTransform.cat(transformation_all)
        self.resolution = torch.stack(resolution_all, 0)
        # self.count = self.v.shape[0]
        self.count = self.v_erosion.shape[0]
        self.epoch = 0

        self.reg_xyz_all = xyz_all
        self.reg_v_all = v_all
        self.reg_slice_idx_all = slice_idx_all

        self.reg_xyz = None
        self.reg_v = None
        self.reg_slice_idx = None
        self.reg_count = 0
        self.reg_epoch = 0


    @property
    def bounding_box(self) -> torch.Tensor:
        max_r = self.resolution.max()
        xyz_transformed = self.xyz_transformed
        xyz_min = xyz_transformed.amin(0) - 2 * max_r
        xyz_max = xyz_transformed.amax(0) + 2 * max_r
        bounding_box = torch.stack([xyz_min, xyz_max], 0)
        return bounding_box

    @property
    def bounding_box_erosion(self) -> torch.Tensor:
        max_r = self.resolution.max()
        xyz_transformed = self.xyz_transformed_erosion
        xyz_min = xyz_transformed.amin(0) - 2 * max_r
        xyz_max = xyz_transformed.amax(0) + 2 * max_r
        bounding_box = torch.stack([xyz_min, xyz_max], 0)
        return bounding_box

    @property
    def mean(self) -> float:
        q1, q2 = torch.quantile(
            self.v if self.v.numel() < 256 * 256 * 256 else self.v[: 256 * 256 * 256],
            torch.tensor([0.1, 0.9], dtype=self.v.dtype, device=self.v.device),
        )
        return self.v[torch.logical_and(self.v > q1, self.v < q2)].mean().item()

    @property
    def mean_erosion(self) -> float:
        q1, q2 = torch.quantile(
            self.v_erosion if self.v_erosion.numel() < 256 * 256 * 256 else self.v_erosion[: 256 * 256 * 256],
            torch.tensor([0.1, 0.9], dtype=self.v_erosion.dtype, device=self.v_erosion.device),
        )
        return self.v_erosion[torch.logical_and(self.v_erosion > q1, self.v_erosion < q2)].mean().item()

    def get_batch(self, batch_size: int, device) -> Dict[str, torch.Tensor]:
        # if self.count + batch_size > self.xyz.shape[0]:  # new epoch, shuffle data
        if self.count + batch_size > self.xyz_erosion.shape[0]:  # new epoch, shuffle data
            self.count = 0
            self.epoch += 1

            idx = torch.randperm(self.xyz_erosion.shape[0], device=device)

            self.xyz_erosion = self.xyz_erosion[idx]

            self.v_erosion = self.v_erosion[idx]

            self.slice_idx_erosion = self.slice_idx_erosion[idx]
        # fetch a batch of data
        batch = {
            "xyz": self.xyz_erosion[self.count : self.count + batch_size],
            "v": self.v_erosion[self.count : self.count + batch_size],
            "slice_idx": self.slice_idx_erosion[self.count : self.count + batch_size],
        }
        self.count += batch_size
        # print("{}/{}".format(self.count, self.xyz.shape[0]))
        # print("slices",len(self.slices))
        return batch

    def set_reg_slice(self, slice_idx,spatial_scaling):

        self.reg_xyz = self.reg_xyz_all[slice_idx] / spatial_scaling
        self.reg_v = self.reg_v_all[slice_idx]
        self.reg_slice_idx = self.reg_slice_idx_all[slice_idx]
        self.reg_count = self.reg_v.shape[0]
        self.reg_epoch = 0
        print("reg_xyz_all", len(self.reg_xyz_all))
        print("reg_xyz", self.reg_xyz.shape)


    def get_reg_batch(self, batch_size: int,device) -> Dict[str, torch.Tensor]:
        if self.reg_count + batch_size > self.reg_v.shape[0]:  # new epoch, shuffle data
            self.reg_count = 0
            self.reg_epoch += 1
            idx = torch.randperm(self.reg_xyz.shape[0], device=device)
            self.reg_xyz = self.reg_xyz[idx]
            self.reg_v = self.reg_v[idx]
            self.reg_slice_idx = self.reg_slice_idx[idx]
        # fetch a batch of data
        batch = {
            "xyz": self.reg_xyz[self.reg_count : self.reg_count + batch_size],
            "v": self.reg_v[self.reg_count : self.reg_count + batch_size],
            "slice_idx": self.reg_slice_idx[self.reg_count : self.reg_count + batch_size],
        }
        self.reg_count += batch_size
        print("{}/{}".format(self.reg_count, self.reg_xyz.shape[0]))
        # print("slices",len(self.slices))
        return batch

    def get_reg_slice(self,slice_idx):
        return self.reg_xyz_all[slice_idx],self.reg_v_all[slice_idx]


    @property
    def xyz_transformed(self) -> torch.Tensor:
        return transform_points(self.transformation[self.slice_idx], self.xyz)

    @property
    def xyz_transformed_erosion(self) -> torch.Tensor:
        return transform_points(self.transformation[self.slice_idx_erosion], self.xyz_erosion)

    @property
    def mask(self) -> Volume:
        with torch.no_grad():
            resolution_min = self.resolution.min()
            resolution_max = self.resolution.max()
            xyz = self.xyz_transformed
            xyz_min = xyz.amin(0) - resolution_max * 10
            xyz_max = xyz.amax(0) + resolution_max * 10
            shape_xyz = ((xyz_max - xyz_min) / resolution_min).ceil().long()
            shape = (int(shape_xyz[2]), int(shape_xyz[1]), int(shape_xyz[0]))
            kji = ((xyz - xyz_min) / resolution_min).round().long()

            mask = torch.bincount(
                kji[..., 0]
                + shape[2] * kji[..., 1]
                + shape[2] * shape[1] * kji[..., 2],
                minlength=shape[0] * shape[1] * shape[2],
            )
            mask = mask.view((1, 1) + shape).float()
            mask_threshold = (
                self.mask_threshold
                * resolution_min**3
                / self.resolution.log().mean().exp() ** 3
            )
            mask_threshold *= mask.sum() / (mask > 0).sum()
            assert len(mask.shape) == 5
            mask = (
                gaussian_blur(mask, (resolution_max / resolution_min).item(), 3)
                > mask_threshold
            )[0, 0]

            xyz_c = xyz_min + (shape_xyz - 1) / 2 * resolution_min
            return Volume(
                mask.float(),
                mask,
                RigidTransform(torch.cat([0 * xyz_c, xyz_c])[None], True),
                resolution_min,
                resolution_min,
                resolution_min,
            )


def train(slices: List[Slice], args: Namespace) -> Tuple[INR, List[Slice], Volume]:
    # create training dataset

    dataset = Dataset(slices)

    use_scaling = True
    use_centering = True
    # perform centering and scaling
    spatial_scaling = 30.0 if use_scaling else 1
    bb = dataset.bounding_box_erosion
    center = (bb[0] + bb[-1]) / 2 if use_centering else torch.zeros_like(bb[0])
    ax = (
        RigidTransform(torch.cat([torch.zeros_like(center), -center])[None])
            .compose(dataset.transformation)
            .axisangle()
    )
    ax[:, -3:] /= spatial_scaling
    transformation = RigidTransform(ax)
    dataset.xyz /= spatial_scaling
    dataset.xyz_erosion /= spatial_scaling
    # dataset.xyz_cat /= spatial_scaling

    model = MyNeRF(
        transformation,
        dataset.resolution / spatial_scaling,
        dataset.mean_erosion,
        (bb - center) / spatial_scaling,
        spatial_scaling,
        args,
    )
    # poseRefiner = PoseRefiner(transformation).to(args.device)
    # init_train(frost, dataset, args)
    # torch.save(frost.state_dict(), os.path.join(save_path, "mynerf.pt"))
    # print(frost.state_dict())

    # frost.load_state_dict(torch.load(os.path.join(save_path,"mynerf.pt")))


    # inerf = INeRF( frost, args=args)
    # register(inerf,12,slices,dataset,args)
    #
    #
    # sys.exit()
    # setup optimizer
    # frost.args.deformable = True
    params_net = []
    params_encoding = []
    for name, param in model.named_parameters():
        if param.numel() > 0:
            if "_net" in name:
                params_net.append(param)
            else:
                params_encoding.append(param)
    # logging
    logging.debug(log_params(model))
    optimizer = torch.optim.AdamW(
        params=[
            {"name": "encoding", "params": params_encoding},
            {"name": "net", "params": params_net, "weight_decay": 1e-2},
        ],
        # lr=args.learning_rate,
        lr=5e-4,
        betas=(0.9, 0.99),
        eps=1e-15,
    )
    # optimizer_pose = torch.optim.Adam(params=poseRefiner.parameters(), lr=0.05)
    # setup scheduler for lr decay
    scheduler = optim.lr_scheduler.MultiStepLR(
        optimizer=optimizer,
        milestones=list(range(1, len(args.milestones) + 1)),
        gamma=args.gamma,
    )
    # scheduler_pose = optim.lr_scheduler.MultiStepLR(optimizer=optimizer_pose, milestones=list(range(1, len(args.milestones) + 1)), gamma=args.gamma)
    decay_milestones = [int(m * args.n_iter) for m in args.milestones]
    # setup grad scalar for mixed precision training
    fp16 = not args.single_precision
    scaler = torch.cuda.amp.GradScaler(
        init_scale=1.0, enabled=fp16, growth_factor=2.0, backoff_factor=0.5
    )
    # training
    model.train()

    loss_weights = {
        D_LOSS: 1,
        T_REG: 0.1,
        I_REG: 0.03,
        D_REG: args.weight_deform,
    }
    average = MovingAverage(1 - 0.001)
    # logging
    logging_header = False
    logging.info("FROST training starts.")
    train_time = 0.0
    for it in range(1, args.n_iter + 1):
        train_step_start = time.time()

        # forward
        model.train()
        batch = dataset.get_batch(args.batch_size, args.device)

        with torch.cuda.amp.autocast(fp16):
            # losses,results = frost(**batch,poseRefiner=poseRefiner)
            # losses,results = frost(**batch,return_all=True)
            # losses,results = frost(**batch)
            losses = model(**batch,train_step=it,total_step=args.n_iter)
            loss = 0
            for k in losses:
                if k in loss_weights and loss_weights[k]:
                    print(k,"loss_weight",loss_weights[k],"loss",losses[k])
                    loss = loss + loss_weights[k] * losses[k]
        print("epoch: {}, iter:{}, loss: {}, lr: {}".format(dataset.epoch,it,loss.item(),optimizer.param_groups[0]["lr"]))
        # backward
        scaler.scale(loss).backward()
        if args.debug:  # check nan grad
            for _name, _p in model.named_parameters():
                if _p.grad is not None and not _p.grad.isfinite().all():
                    logging.debug("iter %d: Found NaNs in the grad of %s", it, _name)
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad()

        train_time += time.time() - train_step_start
        for k in losses:
            average(k, losses[k].item())
        if (decay_milestones and it >= decay_milestones[0]) or it == args.n_iter:

            if it < args.n_iter:
                decay_milestones.pop(0)
                scheduler.step()


    # outputs



    transformation = model.transformation
    # transformation = poseRefiner.transformation


    # outputs

    # undo centering and scaling
    ax = transformation.axisangle()
    ax[:, -3:] *= spatial_scaling
    transformation = RigidTransform(ax)
    transformation = RigidTransform(
        torch.cat([torch.zeros_like(center), center])[None]
    ).compose(transformation)
    model.inr.bounding_box.copy_(bb)
    dataset.xyz *= spatial_scaling
    # dataset.xyz_cat *= spatial_scaling


    dataset.transformation = transformation
    mask = dataset.mask
    output_slices = []
    for i in range(len(slices)):
        output_slice = slices[i].clone()
        output_slice.transformation = transformation[i]
        output_slices.append(output_slice)

    return model.inr, output_slices,mask