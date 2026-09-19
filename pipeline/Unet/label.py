import argparse
import os
import nibabel as nib
import numpy as np

def binarize_nii_folder(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    for fname in os.listdir(input_dir):
        if fname.endswith(".nii") or fname.endswith(".nii.gz"):
            fpath = os.path.join(input_dir, fname)
            print(f"[INFO] 处理 {fpath}")

            img = nib.load(fpath)
            data = img.get_fdata().astype(np.int16)

            # data[data == 1] = 1
            # brain extractio
            data[data != 1] = 0
            # data[data == 9] = 0
            # data[data == 9] = 0

            # data[data == 2] = 8
            # data[data == 4] = 8
            # data[data == 6] = 8
            # data[data == 10] = 8
            new_img = nib.Nifti1Image(data, img.affine, img.header)
            out_path = os.path.join(output_dir, fname)
            nib.save(new_img, out_path)

            print(f"[DONE] 已保存 {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Binarize nnUNet extraction labels in place or to another folder.")
    parser.add_argument("input_dir")
    parser.add_argument("output_dir", nargs="?")
    args = parser.parse_args()
    binarize_nii_folder(args.input_dir, args.output_dir or args.input_dir)
