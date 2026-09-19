# 自然语言到报告的分阶段验证

统一入口：

```bash
MPLCONFIGDIR=/tmp/autorecon-validation-mpl \
python scripts/validate_agentic_e2e.py \
  --mode both --repeats 3 \
  --output-root validation_results/current
```

默认命令执行以下低成本阶段：

1. 导出 60 条自然语言金标语料。
2. 索引 registration acceptable 清单并验证 8 个选定病例。
3. 验证 22w–35w atlas。
4. 运行单元测试、runtime 和 GPU 门禁。
5. 运行 fallback/GLM 解析与规划测试；未配置 Key 时 GLM 明确标记为 `blocked`。
6. 导入四个历史病例，完成 QC、Dashboard 链接、报告及病例隔离验证。
7. 生成八病例真实 Pipeline 清单，但不会默认启动耗时计算。

主要输出：

```text
validation_results/current/
├── natural_language_gold.json
├── natural_language_fallback.json
├── natural_language_llm.json
├── natural_language_runs.csv
├── data_preflight.json
├── runtime_preflight.json
├── historical_import.json
├── historical_import/<case>/
├── real_pipeline_manifest.json
├── summary.json
└── report.zh-CN.html
```

## 启用真实 GLM

非敏感配置使用 `config/glm.env`。Key 只通过进程环境提供：

```bash
AUTORECON_LLM_API_KEY='<key>' \
MPLCONFIGDIR=/tmp/autorecon-validation-mpl \
python scripts/validate_agentic_e2e.py --mode llm --repeats 3
```

运行结果不会保存 Key。若模型输出包含证据中不存在的数值或肯定性临床判断，Reporter 会拒绝该输出并回退到确定性报告。

### 重新生成七例中文报告

既往验收结果可在不重跑 Pipeline 的前提下重新生成报告：

```bash
python scripts/regenerate_case_reports.py
```

该命令固定读取 `config/glm.env` 并要求可用模型名为 `glm-*`。每个病例先构造确定性中文报告，再允许 GLM 基于 Evidence Bank 改写。以下任一情况都会回退到确定性中文版本：

- 中文字符不足或缺少“能力边界”；
- 遗漏机器码对应的拒绝标题；
- 引入证据中不存在的数值；
- 给出肯定性诊断、正常性或百分位结论。

旧版或续跑 Dashboard 若存在缩略图/交互 HTML，但状态 JSON 未记录其路径，医生端通过 `/api/dashboard-state` 按实际文件补全只读展示元数据；该操作不会修改验收产物，也不会触发 Pipeline。

## 启动八病例真实 Pipeline

只有 `runtime_preflight.json` 中所有硬门禁均通过时，以下命令才会开始实际计算：

```bash
MPLCONFIGDIR=/tmp/autorecon-validation-mpl \
python scripts/validate_agentic_e2e.py \
  --skip-corpus --execute-real --gpus 0,1 \
  --output-root validation_results/current
```

真实任务最多并行两个病例，`--gpus` 强制只接受一张或两张卡；任一批次失败即停止后续批次。每个病例使用独立的
`validation_results/current/real_pipeline/<case>`，公共病例和 atlas 目录始终只读。

每个病例的 `TMPDIR`、`APPTAINER_TMPDIR`、`APPTAINER_CACHEDIR`、Matplotlib cache 和
Pipeline scratch 都固定在该病例的工作目录下。`/tmp` 只可能保留系统工具自身的少量控制文件，
不会承载重建影像、容器缓存或大体积中间结果。

新病例目录已经包含与 BTFE 同几何的 validated extraction mask。真实 recon 批次会把原始
stack 和这些 mask 复制到独立 staging，生成带输入/容器 fingerprint 的
`extraction_state.json`，然后通过 `--resume` 复用。这样不会为每个病例重复展开 4.9 GiB 的
extraction 容器；清单会明确记录 `extraction_source=existing_validated_masks_from_public_nii`，
不会把该步骤误报为本轮重新推理。

中断后重复同一命令会携带 `--resume`，Pipeline 仍会重新验证输入 fingerprint，
不会仅凭同名产物跳过阶段。

## 状态解释

- `passed`：本阶段达到自动验收阈值。
- `failed`：代码、数据或金标不一致，需要修复。
- `blocked`：缺少 Key、GPU 或 runtime 等外部条件，不能算作通过或失败。
- `pending`：真实长任务已生成清单但尚未授权启动。

所有技术检查仅用于科研流程验证，不构成临床诊断或医学正常性判断。
