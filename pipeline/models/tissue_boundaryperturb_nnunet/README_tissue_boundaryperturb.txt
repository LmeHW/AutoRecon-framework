Fetal brain tissue nnUNet model package for AutoRecon scripts.

Source model:
/home/zhaojunyang/codes/nnunet/nnUNet_data/nnUNet_results/Dataset003_Full/nnUNetTrainerBoundaryPerturb_250epochs__nnUNetPlans__3d_fullres

Use with:
- nnUNet_results=<this package>/nnUNet_results
- dataset: Dataset003_Full or -d 3
- trainer: nnUNetTrainerBoundaryPerturb_250epochs
- configuration: 3d_fullres
- fold: all
- checkpoint: checkpoint_best.pth

Label 13 is corpus callosum. Training labels were checked: no training case has label13 missing.
