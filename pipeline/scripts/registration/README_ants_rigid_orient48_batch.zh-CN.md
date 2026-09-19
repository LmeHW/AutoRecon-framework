# `run_ants_rigid_orient48_batch.py` 使用说明

## 1. 脚本做什么

这个脚本用于做 3D NIfTI 图像到 atlas 的 ANTs 刚体配准，但在正式配准前，会先穷举 `48` 种数组朝向候选：

- `6` 种轴顺序排列
- `8` 种翻转组合

每个候选都会执行一次刚体配准，然后用 `Mattes` 指标比较结果，保留最优候选；可选再计算 `GC` 指标用于质控分组。

脚本支持两种运行模式：

- `single`：单 atlas 模式。给一个输入目录、一个 atlas、一个输出目录，批量处理所有 NIfTI。
- `fetal-batch`：胎儿批处理模式。根据 Excel 里的胎龄信息，为每个 case 自动选择最接近的周龄 atlas，再执行配准。

## 2. 依赖

至少需要下面这些依赖可用：

- Python 包：`nibabel`、`numpy`
- ANTs 二进制：`antsRegistration`、`MeasureImageSimilarity`
- `libreoffice`
  - 仅在 `fetal-batch` 模式且主表是 `.xls` 时需要，用于转成 `.xlsx`

默认 ANTs 路径写死为：

```text
/home/huangwei/.conda/envs/ants/bin
```

如果你的环境不同，运行时显式传 `--ants-dir`。

## 3. 单 atlas 模式

最常见用法：

```bash
python /mnt/sda/huangwei/projects/registration/run_ants_rigid_orient48_batch.py \
  --mode single \
  --input-dir /path/to/input_dir \
  --atlas /path/to/24w.nii.gz \
  --output-dir /path/to/output_dir
```

常用可选参数：

```bash
--pattern '*.nii.gz'          # 输入匹配规则
--case-jobs 4                 # 并行 case 数
--itk-threads 2               # 每个 ANTs 进程的 ITK 线程数
--preset fast                 # 更快但更粗略
--skip-gc                     # 不计算 GC，节省时间
--keep-work                   # 保留中间目录，便于排查
--no-qc-sets                  # 不生成 acceptable_cases / suspicious_cases
```

## 4. 胎儿批处理模式

### 4.1 最小用法

```bash
python /mnt/sda/huangwei/projects/registration/run_ants_rigid_orient48_batch.py \
  --mode fetal-batch
```

这会使用脚本里的默认路径：

- `--fetal-root`: `/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain`
- `--atlas-dir`: `/mnt/sda/public/00_Shares/Fetal_brain/FBA-Chinese/atlas`
- 默认数据集：`IngeniaAmbition_patch2,uMR790_3T_patch2`

### 4.2 先只生成清单，不实际跑

建议先 dry run：

```bash
python /mnt/sda/huangwei/projects/registration/run_ants_rigid_orient48_batch.py \
  --mode fetal-batch \
  --dry-run \
  --manifest-out /tmp/fetal_manifest.csv
```

`manifest.csv` 里会列出：

- 哪些 case 可以运行（`status=runnable`）
- 哪些 case 被跳过
- 每个 case 选了哪个 atlas week
- atlas 是精确匹配、最近周龄替代，还是中间周龄回退

### 4.3 指定数据集或路径

```bash
python /mnt/sda/huangwei/projects/registration/run_ants_rigid_orient48_batch.py \
  --mode fetal-batch \
  --fetal-root /data/fetal_project \
  --atlas-dir /data/atlas \
  --master-xls /data/fetal_project/胎儿数据收集表.xls \
  --datasets IngeniaAmbition_patch2,uMR790_3T_patch2 \
  --manifest-out /tmp/fetal_manifest.csv
```

### 4.4 输出目录已存在时继续写入

胎儿模式默认会拒绝写入已有非空 `registration/` 目录，避免覆盖旧结果。确认要复用旧目录时，加：

```bash
--allow-existing-output
```

## 5. 输出结构

单 atlas 模式的输出目录大致如下：

```text
output_dir/
├── summary.csv
├── logs/
│   ├── case_a.csv
│   └── case_b.csv
├── acceptable_cases/
│   ├── summary_acceptable.csv
│   └── best/
└── suspicious_cases/
    ├── summary_suspicious.csv
    └── best/
```

说明：

- `summary.csv`
  - 每个 case 最终保留的最佳候选结果
- `logs/<case>.csv`
  - 该 case 的 48 个朝向候选完整指标
- `acceptable_cases/best/` 或 `suspicious_cases/best/`
  - 最终保留的 warped、affine、以及 `best.txt`

`best.txt` 里会记录：

- 输入文件
- atlas
- 最终 orientation
- `perm` / `flips`
- Mattes / GC

## 6. 胎儿批处理模式的匹配逻辑

脚本在 `fetal-batch` 模式下做了几层业务处理：

1. 从主表读取姓名、采集日期、胎龄。
2. 优先根据映射表里的中文姓名匹配主表。
3. 如果姓名缺失，会尝试根据拼音和采集日期补匹配。
4. 解析胎龄周数，选择最接近的 atlas 周龄。
5. 如果无法可靠匹配或胎龄解析失败，会回退到 atlas 目录中间周龄的模板。

因此，`manifest-out` 很重要。它能让你在正式跑之前就看到哪些 case 落到了回退逻辑。

## 7. 关键参数建议

资源紧张时：

```bash
--preset fast --case-jobs 2 --itk-threads 2 --skip-gc
```

追求结果稳定、可复现时：

```bash
--preset full --random-seed 1
```

调试单个问题 case 时：

```bash
--keep-work --case-jobs 1
```

## 8. 常见问题

### 8.1 提示找不到 `antsRegistration`

显式传：

```bash
--ants-dir /your/ants/bin
```

这个目录下必须同时有：

- `antsRegistration`
- `MeasureImageSimilarity`

### 8.2 胎儿模式提示已有输出目录

这是保护逻辑。脚本默认不往已有非空 `registration/` 目录继续写，避免新老结果混在一起。确认可以复用时再加：

```bash
--allow-existing-output
```

### 8.3 为什么有些 case 用的是 `middle_fallback_*`

这说明脚本无法可靠拿到该 case 的胎龄或主表匹配结果，于是退回到了 atlas 目录中间周龄的模板。优先检查：

- `master_xls` 是否正确
- 映射表里的 `ID` / `Files` 是否完整
- `recon/<case>.nii.gz` 是否存在

## 9. 这次整理后的改动

相对原始脚本，当前版本主要做了这几件事：

- 增加了显式 `--mode single|fetal-batch`
- 保留旧的 `--fetal-batch` 调用方式，兼容已有命令
- 按运行模式重组了 `--help` 输出
- 增加 `--manifest-out`，方便先审阅胎儿批处理清单
- 增加了更明确的参数校验和命令示例

查看帮助：

```bash
python /mnt/sda/huangwei/projects/registration/run_ants_rigid_orient48_batch.py --help
```
