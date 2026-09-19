# -*- coding: utf-8 -*-
# ------------------------------------
# @Author  : Jiangjie Wu
# @FileName: recon_body.py
# @Software: PyCharm
# @Email   : wujj@shanghaitech.edu.cn
# @Date    : 2023-03-20


import argparse
import sys
# from .commands import *
# from ..utils import setup_logger
import torch
import random
import numpy as np
import string
# from dnesvor.cli.io import outputs, inputs
# from dnesvor.image import Stack, Slice
from typing import List, Optional, Tuple
from frost.train_mynerf import train
from frost.sample_mynerf import sample_volume
from typing import Dict, Tuple, Any
from argparse import Namespace
# from dnesvor.image import Volume, save_slices, load_slices, load_stack, save_slices_transform
# import base.stack as st
# import base.slice as sl
from frost.tool import load_stack
import SimpleITK as sitk
import pysitk.python_helper as ph
import re
import os
import logging

import numpy as np
from scipy.ndimage import binary_dilation


def find_files3(file_dir,seg_dir,out_dir):
    # logging.basicConfig(filename=file_dir + '/log.log',
    #                     format='%(asctime)s - %(name)s - %(levelname)s -%(module)s:  %(message)s',
    #                     datefmt='%Y-%m-%d %H:%M:%S %p',
    #                     level=10)
    ph.create_directory(os.path.join(file_dir + "/out"))
    # ph.create_directory(os.path.join(file_dir + "/out/slices"))
    log = ""
    files = {}
    files['files'] = []
    # files['mask_output'] = file_dir + "/seg/"
    files['mask_output'] = seg_dir
    files['masked_recon'] = file_dir + "/masked_recon/"
    # files["out"] = file_dir + "/out"
    files["out"] = out_dir + "/out"
    files["crop"] = file_dir + "/out/crop"
    # ph.create_directory(files["crop"])
    # ph.create_directory(os.path.dirname(files['masked_recon']))
    imgs_dict = {}
    global global_path
    g = os.walk(file_dir)
    for path, dir_list, file_list in g:
        global_path = path

        # if "seg" in path or "out" in path or "masked_recon" in path  or "bestData" in path or "results" in path or "ini" in path or "reorientation" in path or "log" in path :
        if "seg" in path or "out" in path or "masked_recon" in path  or "bestData" in path or "results" in path or  "reorientation" in path or "log" in path :
            continue
        for file_name in file_list:
            # if file_name.endswith(".nii.gz") and "stack" in file_name:
            # if file_name.endswith(".nii.gz") and "trufi" in file_name:

            # if file_name.endswith(".nii.gz") and "crop" not in file_name:
            if file_name.endswith(".nii.gz") and "crop" not in file_name:
            # if file_name.endswith(".nii.gz") and "338254" in file_name:
                # names = file_name.split('t2haste')
                # names = re.findall(r"\d+",file_name)
                names = re.findall(r"\d+\_\d+",file_name)
                # names = re.findall(r"202\d+", file_name)
                # names = re.findall(r"2019\d+", file_name)
                # names = re.findall(r"MR\d+\_v\d+", file_name)
                if len(names) == 0:
                    names = re.findall(r"MR\d+", file_name)
                # print(file_name)
                # name = names[0]
                name = names[-1]
                if not name in imgs_dict.keys():
                    imgs = []
                    imgs.append(os.path.join(path,file_name))
                    imgs_dict[name] = imgs
                else:
                    imgs_dict[name].append(os.path.join(path,file_name))
    for name,file_list in imgs_dict.items():
        print(name)
        print(file_list)
        file = {}
        file['img'] = []
        file['mask'] = []
        for file_name in file_list:
            name = file_name.split('/')[-1]
            # names = re.findall(r"\d+",file_name)
            names = re.findall(r"\d+\_\d+",file_name)
            # names = re.findall(r"202\d+", file_name)
            # names = re.findall(r"2019\d+", file_name)
            # names = re.findall(r"MR\d+\_v\d+", file_name)
            if len(names) == 0:
                names = re.findall(r"MR\d+", file_name)
            # file['name'] = names[0]
            file['name'] = names[-1]
            file['img'].append(file_name)
            file['mask'].append(os.path.join(files['mask_output'], name))
        print(file['img'])
        print(file['mask'])
        file['recon_out'] = file_dir + "/out/out_" + file['name']
        # file['recon_out'] = file_dir + "/out/out_"
        # file['nesvor_noreg'] = file_dir + "/out/NeSVoR_" + file['name'] + ".nii.gz"

        file['our'] = out_dir + "/our_" + file['name'] + ".nii.gz"
        file["slices"] =  file_dir + "/out/slices/" + file['name']
        file['nesvor_noreg_slices'] = file["slices"] + "/NeSVoR_" + file['name']
        file['nesvor_noreg_slices_gt'] = file["slices"] + "/GT_NeSVoR_" + file['name']
        file['nesvor_slices'] = file["slices"] + "/NeSVoR+SVoRT_" + file['name']
        file['nesvor_slices_gt'] = file["slices"] + "/GT_NeSVoR+SVoRT_" + file['name']




        file['recon_subject'] = file['recon_out'] + "/recon_subject_space/" + file['name'] + "subject.nii.gz"
        file['recon_subject_mask'] = file['recon_out'] + "/recon_subject_space/" + file['name'] + "subject_mask.nii.gz"
        file['recon_template'] = file['recon_out'] + "/recon_template_space/" + file['name'] + "template.nii.gz"
        file['recon_template_mask'] = file['recon_out'] + "/recon_template_space/" + file['name'] + "template_mask.nii.gz"
        file['masked_recon'] = file_dir + "/masked_recon/" + file['name']
        files['files'].append(file)
    log += file_dir + "共有" + str(len(files['files'])) + "个subject"
    print("共有" + str(len(files['files'])) + "个文件")
    print("log\n"+log)
    return files


def find_files3_v2(file_dir, seg_dir, out_dir):
    file_dir = os.path.abspath(file_dir)
    seg_dir = os.path.abspath(seg_dir)
    out_dir = os.path.abspath(out_dir)

    subject_name = os.path.basename(os.path.normpath(file_dir))

    ph.create_directory(out_dir)

    # 中间文件仍然放在原个体文件夹的 out 下
    subject_out_dir = os.path.join(file_dir, "out")
    ph.create_directory(subject_out_dir)

    files = {}
    files["files"] = []
    files["mask_output"] = seg_dir
    files["masked_recon"] = os.path.join(file_dir, "masked_recon")
    files["out"] = out_dir
    files["crop"] = os.path.join(subject_out_dir, "crop")

    img_list = []
    mask_list = []

    exclude_dirs = {
        "seg",
        "out",
        "masked_recon",
        "bestData",
        "results",
        "ini",
        "reorientation",
        "log",
    }

    for path, dir_list, file_list in os.walk(file_dir):
        # 原地修改 dir_list，避免继续走入这些目录
        dir_list[:] = [
            d for d in dir_list
            if d not in exclude_dirs
        ]

        for file_name in sorted(file_list):
            if not file_name.endswith(".nii.gz"):
                continue

            if not (file_name.startswith("t2_haste") or file_name.startswith("t2_trufi")):
                continue

            if "crop" in file_name:
                continue

            img_path = os.path.join(path, file_name)
            mask_path = os.path.join(seg_dir, file_name)

            img_list.append(img_path)
            mask_list.append(mask_path)

    if len(img_list) == 0:
        raise RuntimeError(f"No .nii.gz image files found in file_dir: {file_dir}")

    missing_masks = [
        m for m in mask_list
        if not os.path.exists(m)
    ]

    if len(missing_masks) > 0:
        print("❌ Missing mask files:")
        for m in missing_masks:
            print(m)
        raise FileNotFoundError(
            f"{len(missing_masks)} mask files are missing in seg_dir: {seg_dir}"
        )

    file = {}
    file["name"] = subject_name
    file["img"] = img_list
    file["mask"] = mask_list

    # 中间重建输出目录
    file["recon_out"] = os.path.join(subject_out_dir, "out_" + subject_name)

    # 最终重建结果：out_dir/个体文件夹名.nii.gz
    file["our"] = os.path.join(out_dir, subject_name + ".nii.gz")

    # 其他中间路径，保持原来的字段名，避免后续 main 里引用时报错
    # file["slices"] = os.path.join(subject_out_dir, "slices", subject_name)
    # file["nesvor_noreg_slices"] = os.path.join(file["slices"], "NeSVoR_" + subject_name)
    # file["nesvor_noreg_slices_gt"] = os.path.join(file["slices"], "GT_NeSVoR_" + subject_name)
    # file["nesvor_slices"] = os.path.join(file["slices"], "NeSVoR+SVoRT_" + subject_name)
    # file["nesvor_slices_gt"] = os.path.join(file["slices"], "GT_NeSVoR+SVoRT_" + subject_name)

    file["recon_subject"] = os.path.join(
        file["recon_out"],
        "recon_subject_space",
        subject_name + "subject.nii.gz"
    )

    file["recon_subject_mask"] = os.path.join(
        file["recon_out"],
        "recon_subject_space",
        subject_name + "subject_mask.nii.gz"
    )

    file["recon_template"] = os.path.join(
        file["recon_out"],
        "recon_template_space",
        subject_name + "template.nii.gz"
    )

    file["recon_template_mask"] = os.path.join(
        file["recon_out"],
        "recon_template_space",
        subject_name + "template_mask.nii.gz"
    )

    file["masked_recon"] = os.path.join(file_dir, "masked_recon", subject_name)

    files["files"].append(file)

    print("======================================")
    print(f"Subject name: {subject_name}")
    print(f"Image folder: {file_dir}")
    print(f"Seg folder: {seg_dir}")
    print(f"Final output: {file['our']}")
    print(f"Number of input images: {len(file['img'])}")
    print("Images:")
    for img in file["img"]:
        print("  IMG :", img)
    print("Masks:")
    for mask in file["mask"]:
        print("  MASK:", mask)
    print("======================================")

    print("共有" + str(len(files["files"])) + "个subject")

    return files

class Formatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=50, width=None)

class FormatterMetavar(Formatter, argparse.MetavarTypeHelpFormatter):
    pass

def update_defaults(parser, **kwargs):
    parser.set_defaults(**kwargs)


# def register(args: argparse.Namespace, data: List[Stack]) -> List[Slice]:
#     slices = []
#     for stack in data:
#         idx_nonempty = stack.mask.flatten(1).any(1)
#         stack.slices /= torch.quantile(stack.slices[stack.mask], 0.99)
#         slices.extend(stack[idx_nonempty])
#     dataset = slices
#     return dataset



def inputs(args: Namespace,input_stacks,stack_masks,device):
    input_dict: Dict[str, Any] = dict()

    input_dict["input_stacks"] = []
    slices = []
    for i, (f,m) in enumerate(zip(input_stacks,stack_masks)):
        print(f,m)
        stack = load_stack(
            f,
            m,
            device=device,
        )
        if args.thicknesses is not None:
            stack.thickness = args.thicknesses[i]
        if stack.mask.sum() == 0:
            print(f"⚠️ 跳过空mask的stack: {f}")
            continue
        idx_nonempty = stack.mask.flatten(1).any(1)
        stack.slices /= torch.quantile(stack.slices[stack.mask], 0.99)
        slices.extend(stack[idx_nonempty])

    return slices



def main(file_dir=None,seg_dir=None,out_dir=None) -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--file_dir", type=str, default=None)
    parser.add_argument("--seg_dir", type=str, default=None)
    parser.add_argument("--out_dir", type=str, default=None)

    # data organization parameters
    parser.add_argument(
        "--n-features-per-level",
        default=2,
        type=int,
        help="Length of the feature vector at each level.",
    )
    parser.add_argument(
        "--log2-hashmap-size",
        default=19,
        type=int,
        help="Max log2 size of the hash grid per level.",
    )
    parser.add_argument(
        "--level-scale",
        default=1.3819,
        type=float,
        help="Scaling factor between two levels.",
    )

    parser.add_argument(
        "--n-levels",
        default=12,
        type=int,
        help="n-levels.",
    )

    parser.add_argument(
        "--base-resolution",
        default=15,
        type=int,
        help="base_resolution.",
    )


    parser.add_argument(
        "--coarsest-resolution",
        default=16.0,
        type=float,
        help="Resolution of the coarsest grid in millimeter.",
    )
    parser.add_argument(
        "--finest-resolution",
        default=0.5,
        type=float,
        help="Resolution of the finest grid in millimeter.",
    )
    # implicit network
    parser.add_argument(
        # "--depth", default=3 , type=int, help="Number of hidden layers in MLPs."
        "--depth", default=2, type=int, help="Number of hidden layers in MLPs."
    )
    parser.add_argument(
        "--width", default=64, type=int, help="Number of neuron in each hidden layer."
    )

    parser.add_argument(
        "--n-features-slice",
        default=20,
        type=int,
        help="Length of the slice embedding vector e.",
    )
    parser.add_argument(
        "--no-transformation-optimization",
        action="store_true",
        help="Disable optimization for rigid slice transfromation, i.e., the slice transformations are fixed",
    )
    parser.add_argument(
        "--no-slice-scale",
        action="store_true",
        help="Disable adaptive scaling for slices.",
    )

    parser.add_argument(
        "--no-mask-net",
        action="store_true",
        help="Disable mask.",
    )
    parser.add_argument(
        "--single-precision",
        action="store_true",
        help="use float32 (default: float16)",
    )
    # loss function
    parser.add_argument(
        "--weight-transformation",
        # default=2,
        default=0.1,
        type=float,
        help="Weight of transformation regularization.",
    )

    parser.add_argument(
        "--image-regularization",
        default="edge",
        type=str,
        choices=["TV", "edge", "L2"],
        help="Type of image regularization (TV: total variation, edge: edge-preserving, L2: L2 regularization of image gradient).",
    )
    parser.add_argument(
        "--weight-image",
        default=1.0 * 2,
        # default=0.01,
        type=float,
        help="Weight of image regularization.",
    )
    parser.add_argument(
        "--img-reg-autodiff",
        action="store_true",
        help=(
            "Use auto diff to compute the image graident in the image regularization. "
            "By default, the finite difference is used."
        ),
    )

    # deformable net
    parser.add_argument(
        "--deformable",
        action="store_true",
        help="Enable implicit deformation field.",
    )
    parser.add_argument(
        "--n-features-deform",
        default=8,
        type=int,
        help="Length of the deformation embedding vector.",
    )
    parser.add_argument(
        "--n-features-per-level-deform",
        # default=4,
        default=2,
        type=int,
        help="Length of the feature vector at each level (deformation field).",
    )
    parser.add_argument(
        "--level-scale-deform",
        default=1.3819,
        type=float,
        help="Scaling factor between two levels (deformation field).",
    )
    parser.add_argument(
        "--coarsest-resolution-deform",
        default=32.0,
        type=float,
        help="Resolution of the coarsest grid in millimeter (deformation field).",
    )
    parser.add_argument(
        "--finest-resolution-deform",
        default=8.0,
        type=float,
        help="Resolution of the finest grid in millimeter (deformation field).",
    )
    parser.add_argument(
        "--weight-deform",
        default=0.1,
        type=float,
        help="Weight of deformation regularization ",
    )

    # training
    parser.add_argument(
        "--learning-rate",
        # default=5e-3,
        default=5e-3,
        type=float,
        help="Learning rate of Adam optimizer.",
    )
    parser.add_argument(
        "--gamma",
        default=0.33,
        type=float,
        help="Multiplicative factor of learning rate decay.",
    )
    parser.add_argument(
        "--milestones",
        nargs="+",
        type=float,
        default=[0.5, 0.75, 0.9],
        help="List of milestones of learning rate decay. Must be in (0, 1) and increasing.",
    )
    parser.add_argument(
        "--n-iter", default=6000, type=int, help="Number of iterations for training."
    )
    parser.add_argument(
        "--batch-size",
        default=1024 * 8,
        type=int, help="Batch size for training."
    )
    parser.add_argument(
        "--n-samples",
        # default=128 * 2,
        default=128,
        # default=64,
        type=int,
        help="Number of sample for PSF during training.",
    )
    parser.add_argument(
        "--output-resolution",
        default=0.8,
        type=float,
        help="Isotropic resolution of the reconstructed volume",
    )
    parser.add_argument(
        "--output-intensity-mean",
        default=700.0,
        type=float,
        help="mean intensity of the output volume",
    )
    parser.add_argument(
        "--inference-batch-size", type=int,
        # default=1024*4*8,
        default=1024*2,
        help="batch size for inference"
    )
    parser.add_argument(
        "--n-inference-samples",
        type=int,
        # default=0,
        default=128*2*2,
        # default=128*2,
        # default=128,
        help="number of sample for PSF during inference",
    )
    parser.add_argument(
        "--no-output-psf",
        action="store_true",
        help="Disable psf for generating output volume",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--debug", action="store_true", help="Debug mode.")
    parser.add_argument("--mask-threshold", type=float, default=1.0)
    parser.add_argument('--gpu', default='0', help='GPU ID number(s), comma-separated (default: 3)')
    args = parser.parse_args()

    # ====== 路径参数统一在 parse_args 后处理 ======
    file_dir = args.file_dir
    if file_dir is None:
        file_dir = "data/auto_recon"

    seg_dir = args.seg_dir
    if seg_dir is None:
        seg_dir = os.path.join(file_dir, "seg")

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = os.path.join(file_dir, "out")
    file_dir = os.path.abspath(file_dir)
    seg_dir = os.path.abspath(seg_dir)
    out_dir = os.path.abspath(out_dir)

    ph.create_directory(out_dir)

    print("file_dir:", file_dir)
    print("seg_dir:", seg_dir)
    print("out_dir:", out_dir)


    print(args)
    # if len(sys.argv) == 2:
    #     locals()["parser_" + args.command.replace("-", "_")].print_help(sys.stdout)
    #     return
    device = torch.device('cuda:{}'.format(args.gpu) if args.gpu is not None else 'cpu')
    args.device = device
    # args.dtype = torch.float16
    args.dtype = torch.float32
    # args.no_transformation_optimization = True
    args.stack_masks = None
    args.thicknesses = None
    args.output_psf = True


    # args.output_resolution = spacing[0]
    args.output_resolution = 0.6
    # args.output_resolution = 0.8
    # args.output_resolution = 1.0
    args.pose_learning_rate = 0.01

    # args.no_transformation_optimization = True
    # args.no_slice_scale = True
    # print(args.n_levels_bias)
    # args.n_levels_bias = 12
    args.single_precision = True
    # args.deformable = True
    # args.deformable = False

    args.n_levels = 12
    args.n_features_per_level = 2
    args.base_resolution = 10
    args.log2_hashmap_size = 19
    args.level_scale = 1.3819



    if args.seed is not None:
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        random.seed(args.seed)

    files = find_files3_v2(file_dir, seg_dir=seg_dir, out_dir=out_dir)
    total = len(files['files'])
    logging.basicConfig(filename=file_dir + '/log.log',
                        format='%(asctime)s - %(name)s - %(levelname)s -%(module)s:  %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S %p',
                        level=10)
    logs = ""
    for i, f in enumerate(files['files']):
        # if i <= 58 or i >80:

        log = ""
        print("重建%s/%s  %s"%(i+1,total,f['name']))
        log += "重建%s/%s"%(i+1,total) + "\n"
        output = f["recon_out"]
        input_stacks = []
        input_stacks_masks = []
        input_stacks = f['img']
        input_stacks_masks = f['mask']





        # try:
        slices = inputs(args, input_stacks=input_stacks, stack_masks=input_stacks_masks,
                        device=device)
        model, output_slices, mask = train(slices, args)
        mask = mask.resample(args.output_resolution,None)
        # mask.save("data/body/IPMCH1120/out/volume_mask.nii.gz")


        # self.new_timer("Results saving")
        output_volume = sample_volume(model, mask,args.output_resolution, args.inference_batch_size,args.n_inference_samples)
        output_volume.rescale(700)
        # output_volume.save("data/body/GFYannotation/out/recon_20240319100051.nii.gz")
        # sys.exit()
        output_volume.save(f['our'])
        # except Exception as e:
        #     # raise RuntimeError("the number '%s' reconstruction failed" % i)
        #     print("file '%s' reconstruction failed" % f['name'])
        #     log += "file '%s' reconstruction failed" % f['name'] + "\n"


        logs += log
        logging.info(log)

    logging.info(logs)





if __name__ == "__main__":

    # file_dir = "data/auto_recon"
    # seg_dir = "data/auto_recon/seg"
    # out_dir = "data/auto_recon/out"


    # ph.create_directory(out_dir)

    # main(file_dir,seg_dir,out_dir)
    main()
