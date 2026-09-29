Fetal brain tissue nnUNet model package for AutoRecon clinic.

This is the default tissue model as of 2026-09-20, replacing
tissue_boundaryperturb_nnunet after a side-by-side check on
Dataset003 holdout (Dice tied) and clinic/HASTE cases (left-right
hemisphere leak much lower).

Source model:
/mnt/sda/huangwei/datasets/nnunet_results/Dataset003_Full/nnUNetTrainer_BS5__nnUNetResEncUNetLPlans__3d_fullres

Use with:
- nnUNet_results=<this package>/nnUNet_results
- dataset: Dataset003_Full or -d 3
- trainer: nnUNetTrainer_BS5
- plans: nnUNetResEncUNetLPlans
- configuration: 3d_fullres
- fold: all
- checkpoint: checkpoint_best.pth
- PYTHONPATH must include /mnt/sda/huangwei/projects/nnUNet so the
  custom trainer class can be imported.

The previous BoundaryPerturb package remains at
pipeline/models/tissue_boundaryperturb_nnunet.
