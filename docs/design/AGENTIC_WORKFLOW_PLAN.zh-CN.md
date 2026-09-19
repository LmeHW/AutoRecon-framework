# 胎儿脑 MRI Agentic Workflow 建设计划

## 1. 项目目标

本项目计划在现有胎儿脑 MRI 自动处理流程之外增加大模型 Agent 编排层。大模型不直接执行医学图像重建、分割或测量，而是负责：

- 理解用户的自然语言请求；
- 识别任务目标并提取必要参数；
- 根据工具能力和步骤依赖生成执行计划；
- 调度已有医学图像处理模块；
- 跟踪任务状态并处理缺失参数或执行失败；
- 将结构化输出转换为用户可理解的结果说明。

系统由此从固定顺序的自动化脚本升级为支持自然语言交互、动态任务组合和结果解释的胎儿脑 MRI 分析助手。

一句话描述：

> 这个项目不是让大模型直接分析 MRI，而是让多个大模型 Agent 理解用户需求、组织专业工具，并把固定 pipeline 转化为可交互、可组合的胎儿脑 MRI 分析系统。

## 2. 现有处理能力

当前确定性处理流程包括：

```text
BTFE input
→ brain extraction
→ 3D reconstruction
→ registration
→ tissue segmentation
→ ROI atlas warp / ROI segmentation
→ surface reconstruction
→ metrics and visualization
```

这些模块继续承担实际的医学图像计算。Agent 层只通过受控工具接口调用它们，不替代其内部算法。

## 3. 目标工作流

```text
User Request
    ↓
Coordinator Agent
    ↓
Planner Agent
    ↓
Structured Task Plan
    ↓
Deterministic Tool Executor
    ├── Input Checking Tool
    ├── Brain Extraction Tool
    ├── Reconstruction Tool
    ├── Registration Tool
    ├── Tissue Segmentation Tool
    ├── ROI Tool
    ├── Surface Tool
    ├── Metrics Tool
    └── Visualization Tool
    ↓
Execution Verifier
    ↓
Report Agent
    ↓
Final Answer + Dashboard + Logs + Result Files
```

目标不是每次执行完整 pipeline，而是根据用户的实际请求选择必要模块。

例如，用户请求：

> 将这个胎儿的多组 BTFE 重建为 3D MRI。

对应计划为：

```text
input_check → extraction → reconstruction → visualization
```

用户请求：

> 这是一个 31.4 周胎儿，请完成重建并生成孕周匹配的 ROI 统计。

对应计划为：

```text
input_check
→ extraction
→ reconstruction
→ atlas_selection
→ ROI warp
→ ROI metrics
→ report
```

## 4. Agent 角色设计

### 4.1 Coordinator Agent

Coordinator 负责理解用户请求并维护任务上下文，主要职责包括：

- 识别用户期望的最终产物；
- 将请求映射到标准任务类型；
- 提取 subject directory、work root、孕周和 atlas 等参数；
- 判断是否缺少必要输入；
- 判断请求是否超出当前系统能力；
- 将标准化任务交给 Planner。

Coordinator 不直接执行 shell 命令，也不自由生成工具参数。

### 4.2 Planner Agent

Planner 根据任务目标、工具能力和步骤依赖生成结构化执行计划。例如：

```json
{
  "goal": "reconstruct_and_generate_roi_statistics",
  "subject_dir": "/data/sub-001",
  "work_root": "/results/sub-001",
  "gestational_age": 31.4,
  "steps": [
    {
      "id": "extract",
      "tool": "brain_extraction",
      "depends_on": []
    },
    {
      "id": "reconstruct",
      "tool": "frost_reconstruction",
      "depends_on": ["extract"]
    },
    {
      "id": "roi",
      "tool": "ga_atlas_roi_warp",
      "depends_on": ["reconstruct"]
    },
    {
      "id": "metrics",
      "tool": "roi_volume_statistics",
      "depends_on": ["roi"]
    }
  ]
}
```

执行计划必须经过 JSON Schema 校验和能力白名单检查，校验通过后才能进入执行器。

### 4.3 Expert Agents

每个 Expert Agent 对应一种专业能力：

| Expert Agent | 封装能力 |
| --- | --- |
| Input Agent | 输入文件、命名和必要参数检查 |
| Extraction Agent | 2D brain extraction |
| Reconstruction Agent | FROST 3D reconstruction |
| Registration Agent | rigid 或 SyN registration |
| Tissue Agent | tissue segmentation |
| ROI Agent | 孕周图谱选择、ROI warp 或直接分割 |
| Surface Agent | white、pial 和 inflated surface |
| Metrics Agent | ROI 体积及其他基础统计 |
| Visualization Agent | Dashboard、MPR 和交互式结果 |

Expert Agent 不应自由发挥。每个 Agent 接收固定输入 JSON，调用白名单中的确定性工具，并返回固定输出 JSON：

```json
{
  "agent": "reconstruction",
  "status": "completed",
  "inputs": {
    "subject_dir": "/results/sub-001/staging/sub-001"
  },
  "outputs": {
    "recon_image": "outputs/recon/sub-001.nii.gz",
    "viewer": "dashboard/previews/02_reconstruction_interactive.html",
    "log": "dashboard/logs/02_reconstruction.log"
  },
  "message": "3D reconstruction completed"
}
```

### 4.4 Execution Verifier

第一阶段暂不把医学图像质控作为建设重点，但必须保留最小执行验证，用于区分“脚本被调用”和“任务已完成”。验证内容包括：

- 子进程退出状态；
- 必要输出文件是否存在；
- 输出文件是否能够正常读取；
- 基本图像尺寸和空间信息是否有效；
- 上游依赖产物是否完整；
- 日志中是否存在明确错误。

该模块第一阶段不负责判断疾病、影像质量或临床正确性。

### 4.5 Report Agent

Report Agent 只根据结构化计划和执行结果生成总结，不重新解释原始 MRI。报告应包含：

- 用户请求及系统实际执行的任务；
- 已完成、失败和跳过的步骤；
- 主要结果文件及 Dashboard 入口；
- 缺少的输入或依赖；
- 实验性输出提示；
- 当前系统无法回答的医学问题。

## 5. 标准任务分类

| `task_type` | 用户意图 | 主要工具 |
| --- | --- | --- |
| `reconstruction` | 多组 BTFE 重建为 3D MRI | extraction + reconstruction |
| `visualization` | 浏览原始 stack、重建或分割结果 | Dashboard + MPR |
| `registration` | 配准到指定或孕周匹配模板 | rigid / SyN registration |
| `tissue_segmentation` | 组织或区域标签预测 | tissue model |
| `roi_parcellation` | 个体脑区 ROI 分区 | GA atlas warp / ROI model |
| `surface_analysis` | 生成 white、pial、inflated surface | surface tools |
| `basic_quantification` | ROI 体积等基础指标 | metrics tools |

明确不支持的任务包括：

```json
{
  "unsupported_tasks": [
    "clinical_diagnosis",
    "abnormality_detection",
    "normal_range_comparison",
    "standard_cortical_thickness",
    "longitudinal_development_analysis",
    "automatic_clinical_report"
  ]
}
```

## 6. 工具接口设计

每个现有脚本应注册为标准工具，并声明：

```text
tool_name
description
input_schema
output_schema
dependencies
command_template
expected_artifacts
timeout_policy
capability_level
```

示例：

```yaml
name: frost_reconstruction
description: Reconstruct a 3D fetal brain MRI from extracted BTFE stacks.
requires:
  - subject_dir
  - extraction_masks
produces:
  - recon_image
  - execution_log
capability_level: stable
```

大模型只能从注册表中选择工具和填写受 Schema 约束的参数，不能直接生成任意 shell 命令。

## 7. 核心结构化数据

系统至少需要定义以下数据对象：

### 7.1 User Request

保存原始请求、已提取参数和请求分类。

### 7.2 Task Plan

保存目标、步骤、依赖、输入参数、跳过步骤和能力边界。

### 7.3 Step Result

保存每个工具的状态、输入、输出、日志和错误。

### 7.4 Run State

保存整个任务的生命周期：

```text
created → planned → running → completed / failed / cancelled
```

步骤状态为：

```text
pending → running → completed / failed / skipped
```

### 7.5 User Report

保存面向用户的 Markdown 总结及机器可读 JSON 报告。

## 8. 建议代码结构

```text
agentic/
├── capabilities.yaml
├── tool_registry.yaml
├── schemas/
│   ├── user_request.schema.json
│   ├── task_plan.schema.json
│   ├── step_result.schema.json
│   └── report.schema.json
├── coordinator.py
├── planner.py
├── executor.py
├── verifier.py
├── reporter.py
├── state_store.py
└── tools/
    ├── extraction.py
    ├── reconstruction.py
    ├── registration.py
    ├── tissue.py
    ├── roi.py
    ├── surface.py
    ├── metrics.py
    └── visualization.py
```

## 9. 实施阶段

### 阶段一：现有模块 Tool 化

- 为现有脚本定义统一输入和输出；
- 将固定路径转换为显式参数；
- 支持按步骤选择执行；
- 为每个运行建立独立工作目录；
- 输出结构化 step result。

建议为主 pipeline 增加类似接口：

```bash
--steps extraction,reconstruction,roi,metrics
--resume
--force-step roi
--plan-file task_plan.json
```

### 阶段二：结构化任务与状态管理

- 定义 JSON Schema；
- 建立工具注册表；
- 实现步骤依赖检查；
- 实现任务状态持久化；
- 支持失败恢复和断点续跑。

### 阶段三：规则版 Coordinator 和 Planner

- 先通过规则映射标准用户请求；
- 验证任务分类和工具依赖是否完整；
- 建立不支持请求的明确响应；
- 在不依赖 LLM 的情况下跑通端到端编排。

### 阶段四：接入大模型

- 将自然语言请求转换为受约束的 User Request；
- 生成 Schema 合法的 Task Plan；
- 对缺失的关键参数发起澄清；
- 禁止模型越过工具注册表直接执行命令；
- 保留原始请求、模型输出和最终计划以便审计。

### 阶段五：Expert Agent 与报告生成

- 将各专业工具封装成 Expert Agent；
- 统一 Agent 间的结构化通信；
- 实现 Report Agent；
- 将结果路径、执行状态和 Dashboard 集成到最终回答。

### 医生端报告与可视化约束

- 医生端报告固定为中文。GLM 只能基于 Evidence Bank 和确定性报告进行专业改写，不能新增测量值、诊断或执行事实。
- GLM 输出必须保留全部拒绝标题和能力边界；若输出不是中文、遗漏拒绝、包含无证据数值或肯定性临床结论，Reporter 必须回退到确定性中文报告。
- 既往结果不得因查看操作重新运行 Pipeline。结果中心只加载已归档的状态、报告和 Dashboard 产物。
- Dashboard 元数据不是可视化文件存在性的唯一依据。旧版或续跑状态缺少 `preview_relpath` 时，服务端应根据实际存在的 `dashboard/previews/<序号>_<步骤>.png` 与交互 HTML 补全只读展示元数据。
- 交互式 HTML 只在用户点击“查看影像”后加载；列表页只显示缩略图，轮询不得重复重建未变化的影像组件。
- “结果中心”和“新建分析”保持独立展示状态：进入新建分析时清空下方既往报告与影像，但保留当前结果引用；返回结果中心时重新加载刚才选择的结果。

## 10. 第一版完成标准

第一版系统应能够完成以下闭环：

1. 接收一条自然语言请求；
2. 识别任务类型并提取 subject directory、work root 和孕周等参数；
3. 生成可校验的 Task Plan；
4. 根据计划选择性调用现有 pipeline 模块；
5. 保存每一步的结构化执行结果；
6. 对输出进行最小完成性验证；
7. 返回结果文件、Dashboard、失败信息和能力边界说明。

第一版不以自动医学质控、疾病诊断或异常判断为目标。

## 11. 项目介绍表述

> 本项目旨在构建一个面向胎儿脑 MRI 分析的多智能体工具调度系统。不同于使用大语言模型直接进行医学图像分析，本系统将脑提取、三维重建、图谱配准、组织分割、ROI 分区、表面生成和定量分析等现有算法封装为标准化工具。Coordinator Agent 负责理解用户自然语言请求并识别任务目标，Planner Agent 根据工具能力和步骤依赖生成结构化执行计划，多个 Expert Agents 分别调用专业医学影像模块，Report Agent 最终汇总执行状态、输出文件和能力边界。通过该架构，原有固定顺序的处理流程能够转化为一个支持自然语言交互、动态任务组合和结果解释的胎儿脑 MRI 分析助手。

