import sys
from argparse import Namespace
from math import log2
from typing import Optional, Dict, Any, Union, TYPE_CHECKING, Tuple
import logging
import torch
import torch.nn.functional as F
import torch.nn as nn
import tinycudann as tcnn
from .transform import RigidTransform, ax_transform_points, mat_transform_points
from .tool import resolution2sigma




# key for loss/regularization
D_LOSS = "MSE"
T_REG = "transReg"
I_REG = "imageReg"
D_REG = "deformReg"
REG_LOSS = "registration"
MASK_LOSS = "regionalMask"

def ange2mat(ang):
    # ang [N, 3]
    cos_angle = torch.cos(ang)
    sin_angle = torch.sin(ang)
    Rx = torch.zeros(size=(ang.shape[0], 3, 3), requires_grad=True).to(ang.device)
    Ry = torch.zeros(size=(ang.shape[0], 3, 3), requires_grad=True).to(ang.device)
    Rz = torch.zeros(size=(ang.shape[0], 3, 3), requires_grad=True).to(ang.device)

    Rx[:, 0, 0] = 1
    Rx[:, 1, 1] = cos_angle[:, 0]
    Rx[:, 1, 2] = -sin_angle[:, 0]
    Rx[:, 2, 1] = sin_angle[:, 0]
    Rx[:, 2, 2] = cos_angle[:, 0]

    Ry[:, 1, 1] = 1
    Ry[:, 0, 0] = cos_angle[:, 1]
    Ry[:, 0, 2] = sin_angle[:, 1]
    Ry[:, 2, 0] = -sin_angle[:, 1]
    Ry[:, 2, 2] = cos_angle[:, 1]

    Rz[:, 2, 2] = 1
    Rz[:, 0, 0] = cos_angle[:, 2]
    Rz[:, 0, 1] = -sin_angle[:, 2]
    Rz[:, 1, 0] = sin_angle[:, 2]
    Rz[:, 1, 1] = cos_angle[:, 2]
    R = torch.matmul(torch.matmul(Rz, Ry), Rx).permute(0, 2, 1)
    return R


class PoseRefiner(nn.Module):
    def __init__(self, value,transformation_optimization=True,trans_first=True):
        super(PoseRefiner, self).__init__()
        self.transformation = value
        self.trans_first = trans_first
        axisangle = value.axisangle(self.trans_first)
        if TYPE_CHECKING:
            self.axisangle_init: torch.Tensor
        self.register_buffer("axisangle_init", axisangle.detach().clone())
        if transformation_optimization:
            self.axisangle = nn.Parameter(axisangle.detach().clone())
        else:
            self.register_buffer("axisangle", axisangle.detach().clone())

    def forward(self, slice_idx: torch.Tensor,xyz,xyz_psf,psf_sigma):
        # N, 3, 3, -> N, 1, 3, 3
        # r = self.rotation_matrix[img_id].unsqueeze(1)
        t = self.axisangle[slice_idx][:, None]
        print("transform", self.axisangle[8][:, None])
        xyz = ax_transform_points(
            t, xyz[:, None] + xyz_psf * psf_sigma, self.trans_first
        )
        return xyz


def build_encoding(**config):
    # if USE_TORCH:
    #     encoding = HashEmbedder(**config)
    # else:
    n_input_dims = config.pop("n_input_dims")
    dtype = config.pop("dtype")
    try:
        encoding = tcnn.Encoding(
            n_input_dims=n_input_dims, encoding_config=config, dtype=dtype
        )
    except RuntimeError as e:
        if "TCNN was not compiled with half-precision support" in str(e):
            logging.error(
                "TCNN was not compiled with half-precision support! "
                "Try using --single-precision in the nesvor command! "
            )
        raise e
    return encoding


def build_network(**config):
    dtype = config.pop("dtype")
    assert dtype == torch.float16 or dtype == torch.float32
    # if dtype == torch.float16 and not USE_TORCH:
    if dtype == torch.float16 and not USE_TORCH:
        return tcnn.Network(
            n_input_dims=config["n_input_dims"],
            n_output_dims=config["n_output_dims"],
            network_config={
                "otype": "CutlassMLP",
                # "otype": "FullyFusedMLP",
                "activation": config["activation"],
                "output_activation": config["output_activation"],
                "n_neurons": config["n_neurons"],
                "n_hidden_layers": config["n_hidden_layers"],
            },
        )
    else:
        activation = (
            None
            if config["activation"] == "None"
            else getattr(nn, config["activation"])
        )
        output_activation = (
            None
            if config["output_activation"] == "None"
            else getattr(nn, config["output_activation"])
        )
        models = []
        if config["n_hidden_layers"] > 0:
            models.append(nn.Linear(config["n_input_dims"], config["n_neurons"]))
            for _ in range(config["n_hidden_layers"] - 1):
                if activation is not None:
                    models.append(activation())
                models.append(nn.Linear(config["n_neurons"], config["n_neurons"]))
            if activation is not None:
                models.append(activation())
            models.append(nn.Linear(config["n_neurons"], config["n_output_dims"]))
        else:
            models.append(nn.Linear(config["n_input_dims"], config["n_output_dims"]))
        if output_activation is not None:
            models.append(output_activation())
        return nn.Sequential(*models)


def compute_resolution_nlevel(
    bounding_box: torch.Tensor,
    coarsest_resolution: float,
    finest_resolution: float,
    level_scale: float,
    spatial_scaling: float,
) -> Tuple[int, int]:
    base_resolution = (
        (
            (bounding_box[1] - bounding_box[0]).max()
            * spatial_scaling
            / coarsest_resolution
        )
        .ceil()
        .int()
        .item()
    )
    n_levels = (
        (
            torch.log2(
                (bounding_box[1] - bounding_box[0]).max()
                * spatial_scaling
                / finest_resolution
                / base_resolution
            )
            / log2(level_scale)
            + 1
        )
        .ceil()
        .int()
        .item()
    )
    return int(base_resolution), int(n_levels)






class INR(nn.Module):
    def __init__(
        self, bounding_box: torch.Tensor, args: Namespace, spatial_scaling: float = 1.0,n_slices=0,
    ) -> None:
        super().__init__()
        if TYPE_CHECKING:
            self.bounding_box: torch.Tensor
        self.register_buffer("bounding_box", bounding_box)
        self.n_features_per_level = args.n_features_per_level
        self.n_slices = n_slices
        # hash grid encoding
        base_resolution, n_levels = compute_resolution_nlevel(
            self.bounding_box,
            args.coarsest_resolution,
            args.finest_resolution,
            args.level_scale,
            spatial_scaling,
        )
        n_levels = args.n_levels
        base_resolution = args.base_resolution
        # self.n_levels =n_levels

        self.deform_embedding = nn.Embedding(
            self.n_slices, args.n_features_deform
        )

        self.xyz_encoding = build_encoding(
            n_input_dims=3,
            # n_input_dims=5,
            otype="HashGrid",
            n_levels=n_levels,
            n_features_per_level=args.n_features_per_level,
            log2_hashmap_size=args.log2_hashmap_size,
            base_resolution=base_resolution,
            per_level_scale=args.level_scale,
            dtype=args.dtype,
        )

        self.surface_L = n_levels * (args.n_features_per_level-1) - (args.n_features_per_level-1)
        self.xyz_L = n_levels * args.n_features_per_level - args.n_features_per_level

        self.surface_encoding = build_encoding(
            n_input_dims=2,
            # n_input_dims=5,
            otype="HashGrid",
            n_levels=1,
            n_features_per_level=args.n_features_per_level,
            log2_hashmap_size=args.log2_hashmap_size,
            base_resolution=base_resolution,
            per_level_scale=args.level_scale,
            dtype=args.dtype,
        )
        print("n_levels", n_levels)
        print("n_features_per_level", args.n_features_per_level)
        print("base_resolution", base_resolution)
        print("log2_hashmap_size", args.log2_hashmap_size)
        print("level_scale", args.level_scale)

        # density net
        self.density_net = build_network(

            n_input_dims=n_levels * args.n_features_per_level ,

            n_output_dims=1,
            activation="ReLU",
            output_activation="None",
            n_neurons=args.width,
            n_hidden_layers=args.depth,

            dtype=args.dtype,
        )



        # logging
        logging.debug(
            "hyperparameters for hash grid encoding: "
            + "lowest_grid_size=%d, highest_grid_size=%d, scale=%1.2f, n_levels=%d",
            base_resolution,
            int(base_resolution * args.level_scale ** (n_levels - 1)),
            args.level_scale,
            n_levels,
        )
        logging.debug(
            "bounding box for reconstruction (mm): "
            + "x=[%f, %f], y=[%f, %f], z=[%f, %f]",
            self.bounding_box[0, 0],
            self.bounding_box[1, 0],
            self.bounding_box[0, 1],
            self.bounding_box[1, 1],
            self.bounding_box[0, 2],
            self.bounding_box[1, 2],
        )

    def forward(self, x: torch.Tensor,t:int,T:int, return_all: bool = True):
        x = (x - self.bounding_box[0]) / (self.bounding_box[1] - self.bounding_box[0])
        prefix_shape = x.shape[:-1]
        x = x.view(-1, x.shape[-1])


        xyz_pe = self.xyz_encoding(x)
        pe = []
        pe.append(xyz_pe)
        pe = torch.cat(pe, -1)


        # if not self.training:
        if not return_all:
            pe = pe.to(dtype=x.dtype)
        density = F.softplus(self.density_net(pe)).view(prefix_shape)

        if return_all:

            return density
        else:
            return density

    def sample_batch(
        self,
        xyz: torch.Tensor,
        transformation: Optional[RigidTransform],
        psf_sigma: Union[float, torch.Tensor],
        n_samples: int,
    ) -> torch.Tensor:
        if n_samples > 1:
            if isinstance(psf_sigma, torch.Tensor):
                psf_sigma = psf_sigma.view(-1, 1, 3)
            xyz_psf = torch.randn(
                xyz.shape[0], n_samples, 3, dtype=xyz.dtype, device=xyz.device
            )
            xyz = xyz[:, None] + xyz_psf * psf_sigma
        else:
            xyz = xyz[:, None]
        if transformation is not None:
            trans_first = transformation.trans_first
            mat = transformation.matrix(trans_first)
            xyz = mat_transform_points(mat[:, None], xyz, trans_first)
        return xyz





class Mask(nn.Module):
    def __init__(
        self, bounding_box: torch.Tensor, args: Namespace, spatial_scaling: float = 1.0
    ) -> None:
        super().__init__()
        if TYPE_CHECKING:
            self.bounding_box: torch.Tensor
        self.register_buffer("bounding_box", bounding_box)
        # hash grid encoding
        base_resolution, n_levels = compute_resolution_nlevel(
            bounding_box,
            args.coarsest_resolution_deform,
            args.finest_resolution_deform,
            args.level_scale_deform,
            spatial_scaling,
        )
        level_scale = args.level_scale_deform

        # n_levels = 6
        # n_levels = args.n_levels
        # base_resolution = 2

        self.encoding = build_encoding(
            n_input_dims=3,
            otype="HashGrid",
            n_levels=n_levels,
            n_features_per_level=args.n_features_per_level_deform,
            log2_hashmap_size=args.log2_hashmap_size,
            base_resolution=base_resolution,
            per_level_scale=level_scale,
            dtype=args.dtype,
            interpolation="Smoothstep",
        )
        self.mask_net = build_network(
            n_input_dims=n_levels * args.n_features_per_level_deform
            + args.n_features_deform,
            n_output_dims=1,
            activation="ReLU",
            output_activation="ReLU",
            n_neurons=args.width,
            n_hidden_layers=2,
            # dtype=torch.float32,
            dtype=args.dtype,
        )
        # for p in self.deform_net.parameters():
        #     torch.nn.init.uniform_(p, a=-1e-4, b=1e-4)
        logging.debug(
            "hyperparameters for hash grid encoding (deform net): "
            + "lowest_grid_size=%d, highest_grid_size=%d, scale=%1.2f, n_levels=%d",
            base_resolution,
            int(base_resolution * level_scale ** (n_levels - 1)),
            level_scale,
            n_levels,
        )

    def forward(self, x: torch.Tensor, e: torch.Tensor):
        x = (x - self.bounding_box[0]) / (self.bounding_box[1] - self.bounding_box[0])
        x_shape = x.shape
        prefix_shape = x.shape[:-1]
        # print("def",x.shape)
        x = x.view(-1, x.shape[-1])
        pe = self.encoding(x)
        inputs = torch.cat((pe, e.reshape(-1, e.shape[-1])), -1)
        outputs = self.mask_net(inputs)
        # outputs = self.deform_net(inputs)
        # outputs = (
        #     outputs * (self.bounding_box[1] - self.bounding_box[0])
        #     + self.bounding_box[0]
        # )
        return outputs.view(prefix_shape)


class DeformNet(nn.Module):
    def __init__(
        self, bounding_box: torch.Tensor,nsteps:int, args: Namespace, spatial_scaling: float = 1.0
    ) -> None:
        super().__init__()
        if TYPE_CHECKING:
            self.bounding_box: torch.Tensor
        self.register_buffer("bounding_box", bounding_box)
        self.nsteps = nsteps
        print("nsteps",nsteps)
        self.scale = 1.0 / (2 ** self.nsteps)
        # hash grid encoding
        base_resolution, n_levels = compute_resolution_nlevel(
            bounding_box,
            args.coarsest_resolution_deform,
            args.finest_resolution_deform,
            args.level_scale_deform,
            spatial_scaling,
        )
        level_scale = args.level_scale_deform
        self.n_levels = n_levels

        # n_levels = 6
        # n_levels = args.n_levels
        # base_resolution = 2

        self.encoding = build_encoding(
            n_input_dims=3,
            otype="HashGrid",
            n_levels=n_levels,
            n_features_per_level=args.n_features_per_level_deform,
            log2_hashmap_size=args.log2_hashmap_size,
            base_resolution=base_resolution,
            per_level_scale=level_scale,
            dtype=args.dtype,
            interpolation="Smoothstep",
        )
        self.deform_net = build_network(
            n_input_dims=n_levels * args.n_features_per_level_deform
            + args.n_features_deform,
            n_output_dims=3,
            # n_output_dims=6,
            activation="Tanh",
            output_activation="None",
            n_neurons=args.width,
            n_hidden_layers=2,
            # dtype=torch.float32,
            dtype=args.dtype,
        )
        # print(self.deform_net[2:])
        # sys.exit()
        for p in self.deform_net.parameters():
            torch.nn.init.uniform_(p, a=-1e-4, b=1e-4)
            # torch.nn.init.uniform_(p, a=-1e-3, b=1e-3)
        logging.debug(
            "hyperparameters for hash grid encoding (deform net): "
            + "lowest_grid_size=%d, highest_grid_size=%d, scale=%1.2f, n_levels=%d",
            base_resolution,
            int(base_resolution * level_scale ** (n_levels - 1)),
            level_scale,
            n_levels,
        )
    def integrate(self,source,target):
        vec = source + target
        return vec

    def forward(self, x: torch.Tensor, e: torch.Tensor,train_step:int):
        x = (x - self.bounding_box[0]) / (self.bounding_box[1] - self.bounding_box[0])
        x_shape = x.shape
        # print("def",x.shape)
        x = x.view(-1, x.shape[-1])
        pe = self.encoding(x)
        pe_mask = torch.zeros_like(pe)
        pe = pe * pe_mask
        inputs = torch.cat((pe, e.reshape(-1, e.shape[-1])), -1)
        vec = self.deform_net(inputs)
        #
        vec = vec * self.scale
        for _ in range(self.nsteps):
            vec = vec + self.integrate(vec, vec)
        outputs = vec + x


        outputs = (
            outputs * (self.bounding_box[1] - self.bounding_box[0])
            + self.bounding_box[0]
        )
        return outputs.view(x_shape)




class MyNeRF(nn.Module):
    def __init__(
        self,
        transformation: RigidTransform,
        resolution: torch.Tensor,
        v_mean: float,
        bounding_box: torch.Tensor,
        spatial_scaling: float,
        args: Namespace,
    ) -> None:
        super().__init__()
        if "cpu" in str(args.device):  # CPU mode
            global USE_TORCH
            USE_TORCH = True
        self.spatial_scaling = spatial_scaling
        self.args = args
        self.n_slices = 0
        self.trans_first = True
        self.transformation = transformation
        self.psf_sigma = resolution2sigma(resolution, isotropic=False)
        # self.delta = args.delta * v_mean
        self.delta = 0.2 * v_mean
        self.build_network(bounding_box)
        self.to(args.device)
        self.l1_loss = torch.nn.L1Loss()
        self.mse = torch.nn.MSELoss()
        self.bounding_box =bounding_box

    @property
    def transformation(self) -> RigidTransform:
        return RigidTransform(self.axisangle.detach(), self.trans_first)

    @transformation.setter
    def transformation(self, value: RigidTransform) -> None:
        if self.n_slices == 0:
            self.n_slices = len(value)
        else:
            assert self.n_slices == len(value)
        axisangle = value.axisangle(self.trans_first)
        if TYPE_CHECKING:
            self.axisangle_init: torch.Tensor
        self.register_buffer("axisangle_init", axisangle.detach().clone())
        if not self.args.no_transformation_optimization:
            self.axisangle = nn.Parameter(axisangle.detach().clone())
        else:
            self.register_buffer("axisangle", axisangle.detach().clone())

    def build_network(self, bounding_box) -> None:
        if self.args.n_features_slice:
            self.slice_embedding = nn.Embedding(
                self.n_slices, self.args.n_features_slice
            )
        if not self.args.no_slice_scale:
            self.logit_coef = nn.Parameter(
                torch.zeros(self.n_slices, dtype=torch.float32)
            )


        self.deform_net = DeformNet(bounding_box,nsteps=8, args=self.args, spatial_scaling=self.spatial_scaling)
        self.mask_net = Mask(bounding_box, self.args, self.spatial_scaling)


        # INR
        self.inr = INR(bounding_box, self.args, self.spatial_scaling,self.n_slices)



    def forward(
        self,
        xyz: torch.Tensor,
        v: torch.Tensor,
        slice_idx: torch.Tensor,
        # gt_mask: torch.Tensor,
        train_step:int,
        total_step: int,
        return_all = True
    ) -> Dict[str, Any]:
        # sample psf point
        batch_size = xyz.shape[0]
        n_samples = self.args.n_samples

        # gt_mask = torch.ones_like(gt_mask)
        # mask = gt_mask

        if return_all:

            xyz_psf = torch.randn(
                batch_size, n_samples, 3, dtype=xyz.dtype, device=xyz.device
            )
            # psf = 1
            psf_sigma = self.psf_sigma[slice_idx][:, None]
            # transform points
            t = self.axisangle[slice_idx][:, None]
            xyz = ax_transform_points(
                t, xyz[:, None] + xyz_psf * psf_sigma, self.trans_first
            )

        # deform
        xyz_ori = xyz
        de = self.inr.deform_embedding(slice_idx)[:, None].expand(-1, n_samples, -1)
        # if self.args.deformable and return_all:
        if self.args.deformable:


            fetus_xyz =  xyz_ori
            maternal_xyz = xyz_ori
            deform_fetus_xyz = self.deform_net(fetus_xyz, de,train_step)
            xyz = deform_fetus_xyz


        # inputs
        if self.args.n_features_slice:
            se = self.slice_embedding(slice_idx)[:, None].expand(-1, n_samples, -1)
        else:
            se = None
        # forward
        # results = self.net_forward(xyz,train_step,total_step, se)
        results = self.net_forward(xyz,train_step,total_step, de)
        # output
        density = results["density"]


        # imaging
        if not self.args.no_slice_scale:
            c: Any = F.softmax(self.logit_coef, 0)[slice_idx] * self.n_slices
        else:
            c = 1
        v_out = density.mean(-1)


        v_out = c * v_out

        if not return_all:

            return results



        losses = {D_LOSS: self.l1_loss(v_out, v)}


        if not self.args.no_transformation_optimization:
            losses[T_REG] = self.trans_loss(trans_first=self.trans_first)

        if self.args.deformable:
            losses[D_REG] = self.deform_reg(
                deform_fetus_xyz, fetus_xyz, de,train_step
                # deform_fetus_xyz, xyz*ori_mask[...,None], de*ori_mask[...,None],gt_mask,train_step
                # deform_fetus_xyz, xyz_ori, de,gt_mask,train_step
            )  # deform_reg_autodiff(self.deform_net, xyz_ori, de)
        # image regularization
        losses[I_REG] = self.img_reg(density, xyz)

        return losses

    def net_forward(
        self,
        x: torch.Tensor,
        train_step: int,
        total_step: int,
        de: Optional[torch.Tensor] = None,
    ) -> Dict[str, Any]:
        # density, pe, z = self.inr(x,w1w2,train_step,total_step)
        density = self.inr(x,train_step,total_step)
        prefix_shape = density.shape
        results = {"density": density}


        return results

    def trans_loss(self, trans_first: bool = True) -> torch.Tensor:
        x = RigidTransform(self.axisangle, trans_first=trans_first)
        y = RigidTransform(self.axisangle_init, trans_first=trans_first)
        err = y.inv().compose(x).axisangle(trans_first=trans_first)
        loss_R = torch.mean(err[:, :3] ** 2)
        loss_T = torch.mean(err[:, 3:] ** 2)
        return loss_R + 1e-3 * self.spatial_scaling * self.spatial_scaling * loss_T


    def deform_reg(self, out, xyz, e,train_step):
        if True:  # use autodiff
            n_sample = 4
            x = xyz[:, :n_sample].flatten(0, 1).detach()
            e = e[:, :n_sample].flatten(0, 1).detach()

            # print(x.shape)
            x.requires_grad_()
            # outputs = self.deform_net(x, e)
            # ori_mask = gt_mask[..., None].repeat(1, n_sample).flatten(0, 1).detach()
            # fetus_xyz = mask[...,None] * xyz_ori
            # maternal_xyz = (1-mask[...,None]) * xyz_ori



            outputs_fetus_xyz = self.deform_net(x, e,train_step)
            # outputs_fetus_xyz = self.deform_net(x*ori_mask, e*ori_mask,train_step)
            # outputs_maternal_xyz = self.maternaldeform_net(x, e)
            # xyz = deform_fetus_xyz
            # xyz =  mask[...,None] * deform_fetus_xyz + (1 - mask[...,None]) * deform_maternal_xyz

            # outputs = ori_mask[..., None] * outputs_fetus_xyz + (1 - ori_mask[..., None]) * outputs_maternal_xyz
            outputs =  outputs_fetus_xyz


            grads = []
            out_sum = []
            for i in range(3):
                out_sum.append(outputs[:, i].sum())
                grads.append(
                    torch.autograd.grad((out_sum[-1],), (x,), create_graph=True)[0]
                )
            jacobian = torch.stack(grads, -1)
            jtj = torch.matmul(jacobian, jacobian.transpose(-1, -2))
            I = torch.eye(3, dtype=jacobian.dtype, device=jacobian.device).unsqueeze(0)
            sq_residual = ((jtj - I) ** 2).sum((-2, -1))
            return torch.nan_to_num(sq_residual, 0.0, 0.0, 0.0).mean()
        else:
            out = out - xyz
            d_out2 = ((out - torch.flip(out, (1,))) ** 2).sum(-1) + 1e-6
            dx2 = ((xyz - torch.flip(xyz, (1,))) ** 2).sum(-1) + 1e-6
            dd_dx = d_out2.sqrt() / dx2.sqrt()
            return F.smooth_l1_loss(dd_dx, torch.zeros_like(dd_dx).detach(), beta=1e-3)

    def img_reg(self, density, xyz):
        if self.args.image_regularization == "none":
            return torch.zeros((1,), dtype=density.dtype, device=density.device)

        if self.args.img_reg_autodiff:
            n_sample = 4
            xyz = xyz[:, :n_sample].flatten(0, 1).detach()
            xyz.requires_grad_()
            density, _, _ = self.inr(xyz)
            grad = (
                torch.autograd.grad((density.sum(),), (xyz,), create_graph=True)[0]
                / self.spatial_scaling
            )
            grad2 = grad.pow(2)
        else:
            xyz = xyz * self.spatial_scaling
            d_density = density - torch.flip(density, (1,))
            dx2 = ((xyz - torch.flip(xyz, (1,))) ** 2).sum(-1) + 1e-6
            grad2 = d_density**2 / dx2

        if self.args.image_regularization == "TV":
            return grad2.sqrt().mean()
        elif self.args.image_regularization == "edge":
            return self.delta * (
                (1 + grad2 / (self.delta * self.delta)).sqrt().mean() - 1
            )
        elif self.args.image_regularization == "L2":
            return grad2.mean()
        else:
            raise ValueError("unknown image regularization!")
