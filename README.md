# AutoRecon：基于 Agent 的胎儿脑 MRI 研究工具链

AutoRecon 把原本需要人工准备环境、拼接命令、跟踪日志和整理结果的胎儿脑 MRI 流程，组织成一个可确认、可追踪、可复核的研究工作台。

研究者可以直接描述目标，例如：

> 对 31 周胎儿的多组 BTFE 影像完成脑提取、三维重建和配准；展示每一步结果，并生成中文技术报告。

系统先把这段话转换成结构化需求和执行计划，检查路径、依赖、运行环境及工具能力。只有用户确认计划后，才会调用确定性影像工具。每一步都会保存状态、日志、产物、可视化和技术质量证据。

> AutoRecon 当前用于科研分析和专家复核，不是医疗器械，也不生成临床诊断。技术 QC 通过不代表胎儿医学正常。

## 从需求到结果

```text
自然语言需求
  -> Coordinator：LLM 可用时采用模型给出的步骤范围、目标与参数；规则解析只在 LLM 不可用或调用失败时使用
  -> Planner：生成受工具白名单约束的任务 DAG
  -> Schema / dependency / runtime validation
  -> 用户确认
  -> Deterministic Pipeline
       extraction
       -> reconstruction
       -> registration
          |-> tissue --|
          |-> ROI -----|-> surface
                |-------> metrics
  -> per-step QC + visualization
  -> Evidence Bank
  -> research report
```

LLM 不执行任意 Shell，也不替代重建、配准或分割算法。请求解析阶段采用模型给出的 execution / display / report 步骤，不在成功解析后再用步骤别名覆盖意图。规则解析只在模型不可用或调用失败时使用。实际影像计算由 `pipeline/` 中的确定性工具完成。

## 六步处理能力

| 步骤 | 作用 | 主要技术检查 |
| --- | --- | --- |
| Extraction | 从多组 BTFE stack 提取胎儿脑 | 掩膜成功率、前景比例、切片覆盖 |
| Reconstruction | 用 FROST、NeSVoR、AutoSVRTK 或 NiftyMIC 重建 3D MRI | finite/nonzero、体素、强度、affine、输入 fingerprint |
| Registration | 将重建 MRI 对齐到指定或孕周图谱 | Mattes、GC、输出存在性 |
| Tissue | 在 registered MRI 上生成组织标签 | 标签数、前景比例、空间一致性 |
| ROI | 使用孕周图谱 warp 或 SegResNet 完成脑区分区 | 标签数、前景比例、空间一致性 |
| Surface | 生成 white、pial、inflated surface 和统计文件 | 必要表面及统计文件完整性 |

状态含义：

- `PASS`：自动技术检查通过，仍建议人工查看影像。
- `REVIEW`：产物已生成，但存在需要人工复核的技术信号。
- `FAIL`：关键技术检查失败，不应直接使用相关下游结果。

## 快速开始

### 1. 配置非敏感参数

```bash
cp .env.example .env
```

`.env` 用于 LLM 地址、模型名、ANTs 和 ROI 环境路径等非敏感配置。API Key 不要写入项目 `.env`、源码或命令历史。

推荐把 Secret 单独保存在仅当前用户可读的文件中：

```dotenv
AUTORECON_LLM_API_KEY='<your-key>'
```

### 2. 启动中文 Dashboard

```bash
AUTORECON_SECRET_FILE=/path/to/secret.env \
  scripts/run_agentic_dashboard.sh \
  --host 127.0.0.1 \
  --port 8899
```

浏览器访问：

```text
http://127.0.0.1:8899
```

SSH / VS Code Remote 场景需要把远程端口 `8899` 转发到本机。端口被占用时，服务会自动尝试后续端口并在终端打印实际地址；需要固定端口时增加 `--strict-port`。

也可以在已导出 Key 的环境中直接启动：

```bash
python -m agentic.dashboard_cn --host 127.0.0.1 --port 8899
```

### 使用独立 GLM 配置（不改现有 `.env`）

项目提供了 `config/glm.env`，接口地址与认证方式对应智谱 BigModel 的
OpenAI 兼容对话补全接口。首次使用时只需创建本地 Secret：

```bash
cp .secrets/glm.env.example .secrets/glm.env
chmod 600 .secrets/glm.env
# 在 .secrets/glm.env 中填入真实 Key；该文件已被 Git 忽略。
```

使用 GLM 配置启动：

```bash
AUTORECON_CONFIG_FILE=config/glm.env \
AUTORECON_SECRET_FILE=.secrets/glm.env \
  scripts/run_agentic_dashboard.sh --host 127.0.0.1 --port 8899
```

上述方式不会读取或修改现有 `.env`。也可用同样两个变量运行 CLI；先安全加载
Secret，再执行命令：

```bash
set -a
source .secrets/glm.env
set +a
AUTORECON_CONFIG_FILE=config/glm.env python -m agentic.cli --help
```

英文界面入口为 `python -m agentic.dashboard_server`。

## Dashboard 使用方式

### 第一步：描述需求

建议明确写出：

- 从原始数据新运行，还是导入已有结果。
- 受试者输入目录或已有 run 目录。
- 孕周、图谱和重建后端。
- 实际执行、页面展示、报告引用哪些步骤。
- 是否允许从已验证中间结果断点继续。

### 第二步：选择模式

| 模式 | 用途 | 是否运行 GPU Pipeline |
| --- | --- | --- |
| `Run full pipeline` | 从原始 BTFE 新运行或断点继续 | 是 |
| `Import existing run demo` | 读取已有 run，查看 QC、可视化和报告 | 否 |
| `Plan only` | 只理解需求、检查依赖并生成计划 | 否 |

### 第三步：生成并检查计划

点击 `生成计划` 后，系统只进行需求解析和预检，不启动 Pipeline。重点检查：

- `execution_mode`：是否符合新运行、导入或仅规划。
- `subject_dir`、`work_root`、`existing_run_dir`：路径是否正确。
- `execution_steps`：真正执行哪些步骤。
- `display_steps`：页面展示哪些步骤。
- `report_steps`：报告使用哪些证据；空数组表示使用全部已有证据。
- `missing`、`warnings`、`unfulfilled_requests`：是否存在阻塞或能力边界。

### 第四步：确认执行

点击 `运行 / 演示` 后：

- 新任务异步运行，并持续更新步骤状态和简短日志。
- 导入模式只读取已有结果，不重复计算。
- 页面展示静态预览、交互式 MPR、QC 指标、产物链接和最终报告。
- 报告生成较慢时，已经完成的影像和 QC 会先显示。

## 三个范围为什么分开

| 字段 | 控制内容 | 是否影响计算 |
| --- | --- | --- |
| `execution_steps` | 实际调用哪些 Pipeline 步骤 | 是 |
| `display_steps` | Dashboard 展示哪些步骤 | 否 |
| `report_steps` | 报告引用哪些步骤的证据 | 否 |

例如，“只展示 reconstruction，但基于全部结果生成报告”应解析为：

```text
display_steps = [reconstruction]
report_steps = []
```

页面可以保持简洁，Evidence Bank 和报告仍检查所有已有证据。

## 命令行调用

### Agentic CLI

仅生成计划：

```bash
python -m agentic.cli \
  "检查输入并规划三维重建" \
  --execution-mode plan_only \
  --subject-dir /data/input/subject_001
```

导入已有 run：

```bash
python -m agentic.cli \
  "导入已有结果，展示六步 QC 并生成中文研究报告" \
  --execution-mode import_existing \
  --existing-run-dir /data/autorecon/runs/subject_001/run01
```

执行新任务：

```bash
python -m agentic.cli \
  "完成重建、配准、组织分割、ROI 和表面生成" \
  --execution-mode run_pipeline \
  --subject-dir /data/input/subject_001 \
  --work-root /data/autorecon/runs/subject_001/run02 \
  --ga 31 \
  --atlas /data/atlas/31w.nii.gz \
  --reconstruction-tool frost \
  --roi-mode warp \
  --surface auto
```

### 直接运行确定性 Pipeline

```bash
bash pipeline/run_single_case_pipeline.sh \
  --subject-dir /data/input/subject_001 \
  --work-root /data/autorecon/runs/subject_001/run01 \
  --atlas /data/atlas/31w.nii.gz \
  --ga 31 \
  --reconstruction-tool frost \
  --roi-mode warp \
  --surface auto \
  --dashboard on
```

只运行前三步：

```bash
bash pipeline/run_single_case_pipeline.sh \
  --subject-dir /data/input/subject_001 \
  --work-root /data/autorecon/runs/subject_001/run01 \
  --atlas /data/atlas/31w.nii.gz \
  --steps extraction,reconstruction,registration \
  --roi-mode skip \
  --surface off \
  --dashboard on
```

完整参数以脚本为准：

```bash
bash pipeline/run_single_case_pipeline.sh --help
```

Pipeline 的输出 contract 和目录说明见 [`pipeline/README.md`](pipeline/README.md)，四重建后端的验收规则见 [`pipeline/reconstruction/README.zh-CN.md`](pipeline/reconstruction/README.zh-CN.md)。

## 输出与证据

每个 Agentic run 默认保存在：

```text
agentic_runs/<run_id>/
├── agentic_state.json
├── intent_spec.json
├── task_plan.json
├── evidence_bank.json
├── medical_evidence.json
└── report.md
```

每个 Pipeline run 使用独立工作目录：

```text
<work_root>/
├── staging/
├── scratch/
├── outputs/
├── logs/
└── dashboard/
    ├── run_state.json
    ├── qc_summary.json
    ├── logs/
    └── previews/
```

`--resume` 会验证输入 fingerprint、图像可读性和必要产物，不会仅凭同名文件存在就跳过步骤。

## 工程目录

```text
AutoRecon/
├── agentic/               # 意图解析、规划、执行、QC、报告和服务端
├── pipeline/              # 确定性医学影像处理层
├── tests/                 # 单元和契约测试
├── scripts/               # 启动、验收、演示和汇报构建脚本
├── docs/                  # 组会报告、验证说明、设计、研究方法和运维文档
├── containers/            # 可复现容器定义；SIF 不进入源码仓库
├── showcase/              # 独立的公开静态项目展示站点
├── presentation/          # 汇报源文件和交付材料
├── runs/legacy/           # 已迁移的历史病例 run；不进入源码仓库
├── .runtime/              # 本机模型、容器和缓存；不进入源码仓库
└── runs/migrations/       # 历史 run 迁移清单和验证记录
```

源码目录与运行数据应分开。新部署推荐：

```text
/path/to/AutoRecon/             # 源码
/data/autorecon/inputs/         # 去标识化输入
/data/autorecon/runs/           # Pipeline run
/data/autorecon/agentic-runs/   # Agent 状态与报告
/data/autorecon/runtime/        # 容器、模型和缓存
```

原本平铺在根目录的历史病例已迁移到 `runs/legacy/<subject>/<run-name>/`。新任务仍建议写入源码仓库之外的 `/data/autorecon/runs/`；历史迁移记录见 [`docs/ops/LEGACY_RUN_MIGRATION.zh-CN.md`](docs/ops/LEGACY_RUN_MIGRATION.zh-CN.md)，后续改造见 [`docs/design/SUGGESTIONS.zh-CN.md`](docs/design/SUGGESTIONS.zh-CN.md)。

## 验证

运行快速自动化测试：

```bash
python -m unittest discover -s tests -v
```

检查演示、Evidence Bank 和汇报交付物：

```bash
python scripts/verify_goal_deliverables.py
```

四后端完整验收：

```bash
python scripts/verify_four_backend_acceptance.py \
  --root backend_validation \
  --subject AnHuiJing
```

这些验收确认程序、产物和证据链完整，不等同于临床质量验证。

## 文档导航

索引见 [`docs/README.md`](docs/README.md)。

- [`docs/reports/STABILITY_PATHWAY.zh-CN.md`](docs/reports/STABILITY_PATHWAY.zh-CN.md)：组会材料（功能、约束与稳定性）。
- [`docs/validation/AGENTIC_E2E_VALIDATION.zh-CN.md`](docs/validation/AGENTIC_E2E_VALIDATION.zh-CN.md)：自然语言到报告的分阶段验证。
- [`docs/design/AGENTIC_WORKFLOW_PLAN.zh-CN.md`](docs/design/AGENTIC_WORKFLOW_PLAN.zh-CN.md)：Agentic 工作流设计背景。
- [`docs/design/SUGGESTIONS.zh-CN.md`](docs/design/SUGGESTIONS.zh-CN.md)：下一阶段工程与医学优化路线。
- [`docs/research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md`](docs/research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md)：研究报告方法学。
- [`docs/research/FETALAGENTS_MEDICAL_REPORT_ANALYSIS.zh-CN.md`](docs/research/FETALAGENTS_MEDICAL_REPORT_ANALYSIS.zh-CN.md)：医学报告分析说明。
- [`docs/ops/GATEWAY.zh-CN.md`](docs/ops/GATEWAY.zh-CN.md)：外部协作网关。
- [`docs/ops/LEGACY_RUN_MIGRATION.zh-CN.md`](docs/ops/LEGACY_RUN_MIGRATION.zh-CN.md)：历史病例 run 的目录映射和验证记录。
- [`containers/README.zh-CN.md`](containers/README.zh-CN.md)：共享容器和 runtime。
- [`presentation/PROJECT_COMPLETION_AUDIT.zh-CN.md`](presentation/PROJECT_COMPLETION_AUDIT.zh-CN.md)：2026-07 完成度审计。

## 安全与能力边界

- API Key 只从进程环境读取，不写入状态、报告、日志或 Pipeline 子进程。
- LLM 只能组合注册工具，不能生成任意命令执行。
- 对外部模型发送信息前必须去标识化，并遵循机构的数据治理要求。
- Dashboard 默认仅绑定 `127.0.0.1`；当前版本不应在无认证情况下直接暴露到公网。
- 自动 QC 是工程完整性和技术合理性检查，不是孕周常模或疾病判断。
- 在没有正式解剖标签映射、经验证常模、异常检测器和专家签署时，报告不判断医学正常或异常。
