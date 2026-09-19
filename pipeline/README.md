# AutoRecon deterministic pipeline

本目录包含胎儿脑 MRI 的确定性处理层。Agent 只负责理解需求、规划和调度；实际影像计算由这里的脚本和已注册后端完成。

## 标准流程

```text
BTFE NIfTI
  -> extraction
  -> reconstruction (FROST / NeSVoR / AutoSVRTK / NiftyMIC)
  -> registration
  -> tissue segmentation
  -> ROI parcellation
  -> surface reconstruction
  -> QC + dashboard artifacts
```

Tissue、ROI 和 Surface 的标准分析空间是：

```text
<work_root>/outputs/registered_input/<subject>.nii.gz
```

## 唯一推荐入口

```bash
bash pipeline/run_single_case_pipeline.sh \
  --subject-dir /path/to/deidentified_subject \
  --work-root /data/autorecon/runs/subject_001/run01 \
  --atlas /path/to/31w.nii.gz \
  --ga 31 \
  --reconstruction-tool frost \
  --roi-mode warp \
  --surface auto \
  --dashboard on
```

局部执行和断点续跑：

```bash
bash pipeline/run_single_case_pipeline.sh \
  --subject-dir /path/to/deidentified_subject \
  --work-root /data/autorecon/runs/subject_001/run01 \
  --steps extraction,reconstruction,registration \
  --roi-mode skip \
  --surface off \
  --resume \
  --dashboard on
```

查看全部参数：

```bash
bash pipeline/run_single_case_pipeline.sh --help
```

## 目录职责

- `reconstruction/`：四种重建后端的统一适配、输出 contract 和对比执行。
- `scripts/registration/`：ANTs 配准实现。
- `src/ROI_warp/`：孕周图谱 ROI warp 和表面相关工具。
- `vis/`：病例 Dashboard、静态预览和统计展示。
- `configs/`：本机环境与共享 runtime 配置示例。
- `FROST/`、`Unet/`、`models/`、`data/`：算法源码、模型和图谱资源。
- `00_extraction_patch.sh`、`01_recon_patch.sh`、`02_seg_patch.sh`：由主入口调用的兼容步骤脚本，不建议用户单独调用。

## 输出约定

```text
<work_root>/
├── staging/                 # 输入工作副本和 extraction mask
├── scratch/                 # 可清理的中间文件
├── outputs/
│   ├── reconstruction/      # 各 backend 原生结果和 result.json
│   ├── recon/               # 当前选中 backend 的 canonical 输出
│   ├── registered_input/
│   ├── registration/
│   ├── Tissue/
│   ├── ROI/
│   └── surface_subjects/
├── logs/
└── dashboard/
    ├── run_state.json
    ├── qc_summary.json
    ├── logs/
    └── previews/
```

`--resume` 会重新检查输入 fingerprint 和产物有效性，不会仅凭同名文件存在就跳过步骤。重建后端的详细 contract 与严格验收方式见 [reconstruction/README.zh-CN.md](reconstruction/README.zh-CN.md)。

## 环境

优先使用共享 Apptainer runtime。配置示例：

```bash
cp pipeline/configs/runtime.env.example pipeline/configs/runtime.env
cp pipeline/configs/local.env.example pipeline/configs/local.env
source pipeline/configs/runtime.env
source pipeline/configs/local.env
bash pipeline/check_runtime.sh
```

模型、容器、病例输入和运行结果都属于大体积运行资产，不应提交到源码仓库。
