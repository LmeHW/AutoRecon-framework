# Reconstruction backend 接口与验收

统一入口是 `run_backend.py`。四个 backend 都接收同一组 staging 数据，并把选中的结果发布到：

```text
outputs/recon/<subject>.nii.gz
```

各工具的原生结果、日志和可追溯 manifest 保存在：

```text
outputs/reconstruction/<backend>/<subject>.nii.gz
outputs/reconstruction/<backend>/backend.log
outputs/reconstruction/<backend>/result.json
```

`result.json` 只有在工具零退出、输出通过 3D/affine/spacing/finite/nonzero QC、canonical
链接成功后才会标记 `completed`。输入 stack、mask、容器校验和与 backend 配置共同生成
`input_fingerprint`；`--resume` 必须重新验证 fingerprint，不能仅凭旧文件存在跳过。

## Backend 特殊适配

- FROST：使用共享 `frost.sif`，逐病例优化隐式 3D 表示。
- NeSVoR：传入逐 stack 的同名 mask；不使用 v0.5.0 有缺陷的 `--output-json`。
- AutoSVRTK：只向官方脚本暴露原始 stack；将宿主 scratch 绑定到脚本硬编码的
  `/home/tmp_proc`，并提取 `reo-SVR-output.nii.gz`。
- NiftyMIC：在 backend 私有 scratch 中把 extraction mask 转成 `{0,1}` uint8，保持原
  shape 和 affine，不修改公共 staging mask。

## 单工具运行

```bash
bash pipeline/run_single_case_pipeline.sh \
  --subject-dir /path/to/subject \
  --work-root /path/to/run \
  --reconstruction-tool nesvor \
  --atlas /path/to/atlas.nii.gz \
  --ants-dir /path/to/ants/bin \
  --roi-warp-env /path/to/antspy/env \
  --roi-mode warp --ga 31 --surface on
```

可选值为 `frost|nesvor|autosvrtk|niftymic`。正式 registration 默认使用 `full`；
`--registration-preset fast` 仍遍历 48 个方向，但减少单方向迭代数。

## 四工具严格验收

每个 backend 必须有独立的 `backend_validation/full_pipeline_<backend>`，实际完成
extraction、reconstruction、registration、tissue、ROI 和 surface。最后运行：

```bash
python scripts/validate_full_pipeline.py \
  --work-root backend_validation/full_pipeline_<backend> \
  --subject AnHuiJing \
  --source-dir backend_validation/input/AnHuiJing \
  --backend <backend> \
  --require-surface
```

该命令为每个后端生成独立的 `acceptance.json`。四个后端都完成后，再运行聚合验证：

```bash
python scripts/verify_four_backend_acceptance.py \
  --root backend_validation \
  --subject AnHuiJing
```

验证器会检查总体零退出标记、六步非空日志、stack/mask geometry、backend fingerprint、
canonical 指向、registration summary、registered/tissue/ROI grid 一致性，以及左右半球
white/pial/inflated、四份 ROI surface projection 和两份统计文件。任何一项缺失或为空都会
返回非零状态。

技术验收通过不等于临床图像质量通过。`acceptance.json` 会保留输入序列适用性、重建 metric
告警、registration QC 分组、表面残留 intersections 和 handles；`suspicious` 结果必须继续
进入人工复核，不能因六步程序执行成功而被标成临床可用。

本病例的最终执行证据和已知质量限制见
`backend_validation/FOUR_BACKEND_ACCEPTANCE.md`；机器可读汇总见
`backend_validation/four_backend_acceptance.json`。
