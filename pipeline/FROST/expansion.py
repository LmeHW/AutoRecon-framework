import os
import nibabel as nib
import numpy as np
from scipy.ndimage import binary_dilation, generate_binary_structure

def dilate_nii(input_path, output_path=None, dilation_iter=1):
    """
    对 NIfTI 图像进行 3D 膨胀操作（Dilation）
    --------------------------------------------
    input_path   : 输入 .nii 或 .nii.gz 文件路径
    output_path  : 输出路径（默认在同目录下生成 *_dilated.nii.gz）
    dilation_iter: 膨胀迭代次数（相当于膨胀半径，整数，默认=1）
    """

    # === 1. 读取 NIfTI 图像 ===
    nii = nib.load(input_path)
    data = nii.get_fdata()
    print(f"✅ Loaded image: {input_path}, shape = {data.shape}, dtype = {data.dtype}")

    # === 2. 将数据二值化（如果是mask/分割图） ===
    # 若输入是分割掩膜，则将非零值视为1
    bin_data = (data > 0).astype(np.uint8)

    # === 3. 创建结构元素（3x3x3 立方体） ===
    structure = generate_binary_structure(rank=3, connectivity=1)

    # === 4. 执行膨胀操作 ===
    dilated = binary_dilation(bin_data, structure=structure, iterations=dilation_iter)
    dilated = dilated.astype(np.uint8)

    # === 5. 保存结果 ===
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        if ext == ".gz":  # 处理 .nii.gz 双扩展名
            base = base.replace(".nii", "")
        output_path = base + ".nii.gz"

    nib.save(nib.Nifti1Image(dilated, nii.affine, nii.header), output_path)
    print(f"💾 Dilation complete! Saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    # 示例用法
    input_path = "/home/wangxiao/FROST/data/recon_hyj/seg/20240329124854_601_3.nii.gz"  # ← 修改为你的文件路径
    dilate_nii(input_path, dilation_iter=2)
