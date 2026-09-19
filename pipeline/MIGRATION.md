# AutoRecon local migration

This directory is a runnable copy of the single-case pipeline from:

`/mnt/sda/public/00_Projects/2512_AutoRecon`

The upstream Git base observed during migration was `38b5282`. The source worktree also
contained uncommitted pipeline and dashboard changes; the runnable files were copied from
that working tree on 2026-07-08. Existing author information and the upstream repository
should be retained when this directory is turned into a standalone Git repository.

## Local changes

- extraction and tissue inference now use `${work_root}/scratch` instead of shared model folders;
- copied model folders are treated as read-only;
- the ROI atlas defaults to this directory's `data/FBA_Chinese_Atlas`;
- CUDA selection can be overridden with `CUDA_VISIBLE_DEVICES`;
- machine-specific environment paths are collected in `configs/local.env.example`.

## Verify and run

```bash
cd /mnt/sda/huangwei/projects/AutoRecon/pipeline
cp configs/local.env.example configs/local.env
source configs/local.env
bash check_runtime.sh

bash run_single_case_pipeline.sh \
  --subject-dir /path/to/subject \
  --work-root /mnt/sda/huangwei/projects/AutoRecon/runs/subject_run01 \
  --roi-warp-env /home/zhaojunyang/.conda/envs/zjy \
  --roi-mode warp \
  --ga 31 \
  --surface auto \
  --dashboard on
```

This example intentionally omits `--atlas`, so the separate 48-orientation rigid
registration step is skipped. ROI warp still uses the copied gestational-age atlas under
`data/FBA_Chinese_Atlas`. Pass `--atlas` and `--ants-dir` only when the rigid-registration
output is explicitly required.

For an SSH session, forward the printed dashboard port to the local machine. A completed
dashboard can also be opened directly from `work_root/dashboard/index.html`.
