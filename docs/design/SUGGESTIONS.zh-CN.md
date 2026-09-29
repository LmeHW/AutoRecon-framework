# AutoRecon 下一阶段优化建议

本文把下一阶段工作拆成可以直接进入 issue、迭代计划或验收表的任务。排序原则是：先保护数据和当前可运行能力，再降低维护成本，最后增强医学研究价值。

## 当前基线

截至本次结构整理，项目已经具备：

- 自然语言需求解析：LLM 给出步骤范围；规则解析只在模型不可用或调用失败时使用；工具白名单规划。
- `plan_only`、`import_existing`、`run_pipeline` 三种执行模式。
- Extraction、Reconstruction、Registration、Tissue、ROI、Surface 六步流程。
- FROST、NeSVoR、AutoSVRTK、NiftyMIC 四种重建后端。
- 每步技术 QC、静态预览、交互式查看器、Evidence Bank 和研究报告。
- 自动化单元/契约测试与完整后端验收脚本。

本轮已经完成的工程调整：

- 公开静态站点从仓库根目录收拢到 `showcase/`。
- 文档按主题放在 `docs/design/`、`docs/research/`、`docs/validation/`、`docs/ops/`、`docs/reports/`。
- 中文 Dashboard 成为安全启动脚本的默认入口。
- 重写根 README 和 Pipeline README，统一当前调用方式。
- 扩展 `.gitignore`，明确 runtime、病例结果和生成物不属于源码。

## P0：数据边界和部署安全

### S-001 限制 Dashboard 文件访问范围

**问题**

当前 `/api/file` 可以读取项目根目录、run root 和 `/tmp` 下除少数敏感文件外的内容。只要服务被错误绑定到外部网卡，源码、病例路径和研究产物就可能被浏览。

**落地方式**

1. 为每个 run 生成明确的 artifact allowlist。
2. 文件 API 只接受 `run_id + artifact_id`，不接受客户端提交绝对路径。
3. 只开放 `dashboard/`、批准的 `outputs/`、报告和 Evidence Bank。
4. 禁止目录遍历和任意目录列表。
5. 增加 `X-Content-Type-Options`、CSP、frame 和缓存策略。

**验收标准**

- 请求 `.env`、源码、其他病例和 `/tmp` 任意文件均返回 403。
- 当前 run 的静态预览、交互 Viewer、日志和报告仍可打开。
- 有针对路径穿越、符号链接逃逸和 URL 编码绕过的自动化测试。

### S-002 增加访问控制和数据脱敏

**落地方式**

- 保持默认监听 `127.0.0.1`。
- 非本机部署必须启用反向代理认证或应用层登录。
- 引入稳定的研究 subject ID，页面和 LLM payload 不显示真实姓名或原始目录名。
- 给 LLM 阶段增加 `local_only`、`deidentified_external`、`rules_only` 三种数据策略。
- Evidence Bank 记录使用的策略、模型端点类型和脱敏字段，不保存 Secret。

**验收标准**

- 外部 LLM 请求测试中不出现绝对病例路径、姓名或原始 DICOM 标识符。
- 未认证用户不能读取任务、日志和影像。
- 报告仍能通过内部 subject ID 追溯到授权数据。

### S-003 将运行资产迁出源码目录

**目标结构**

```text
/data/autorecon/
├── inputs/
├── runs/<subject>/<run_id>/
├── agentic-runs/<run_id>/
├── validation/
├── runtime/
│   ├── containers/
│   ├── models/
│   ├── atlas/
│   └── cache/
└── archive/
```

**迁移策略**

1. 先增加 `AUTORECON_DATA_ROOT`、`AUTORECON_RUN_ROOT`、`AUTORECON_AGENTIC_RUN_ROOT` 和 `AUTORECON_RUNTIME_ROOT`。
2. 所有新任务只写入新路径。
3. 旧路径保持只读兼容，建立迁移清单和校验和。
4. 验证 Dashboard、resume 和报告链接后，再归档旧 run。
5. 不使用一次性递归删除；每批迁移都生成 manifest。

**验收标准**

- 一个干净源码 checkout 不包含 NIfTI、SIF、病例日志或预览切片。
- 源码目录删除任意历史 run 后，测试仍可执行。
- 旧 run 经导入模式仍可读取，或具有清楚的迁移映射。

## P1：降低维护成本

### S-101 拆分主 Pipeline Shell

当前 `run_single_case_pipeline.sh` 同时负责参数解析、依赖闭包、进程调度、状态更新、预览生成和六步执行。建议逐步改成薄编排层：

```text
autorecon extract
autorecon reconstruct
autorecon register
autorecon segment-tissue
autorecon parcellate-roi
autorecon build-surface
autorecon qc
```

每个命令统一接受 manifest/config，返回固定 JSON：

```json
{
  "step_id": "reconstruction",
  "status": "completed",
  "inputs": {},
  "artifacts": [],
  "qc": {},
  "provenance": {},
  "error": null
}
```

**实施顺序**

1. 先抽出状态写入和 artifact 注册。
2. 再抽出 preview/QC。
3. 最后逐步替换六个 Shell 函数。
4. 旧 Shell 入口至少保留一个版本，内部调用新 CLI。

**验收标准**

- README 中的旧命令继续可用。
- 每一步可以独立运行和单独测试。
- resume、失败传播和 Dashboard 状态与重构前一致。

### S-102 建立版本化 Run Manifest

将 Agent state、Pipeline state、backend `result.json` 和 QC summary 通过一个稳定主键关联，而不是复制多份相似字段。

必需字段建议包括：

- `schema_version`、`run_id`、`subject_id`。
- 源码 commit、容器 SHA256、模型和 atlas 版本。
- 去标识化输入 fingerprint。
- 每一步状态、依赖、参数、开始/结束时间。
- artifact ID、相对路径、MIME、大小和 checksum。
- 自动 QC、人工复核状态及结论边界。

**验收标准**

- Manifest 可通过 JSON Schema 校验。
- Dashboard、Reporter 和 resume 都从同一 contract 读取。
- 新版本具备向后兼容迁移函数。

### S-103 统一配置

建议用一个强类型配置对象管理：

- LLM provider、模型和数据策略。
- run/runtime/model/atlas 根目录。
- ANTs、FreeSurfer、Apptainer 和 Python 环境。
- GPU、并发、超时和缓存策略。
- Dashboard host、port 和安全策略。

优先级：显式 CLI > 环境变量 > 配置文件 > 安全默认值。

**验收标准**

- `autorecon config check` 可以输出脱敏后的最终配置。
- 不再在 Python、Shell、HTML 和文档中维护不同默认端口。
- 不存在绑定个人用户名的默认生产路径。

### S-104 拆分 Dashboard 前后端资源

当前 HTML、CSS、JavaScript 内嵌在 Python，中文版通过字符串替换生成。建议拆成：

```text
agentic/web/
├── templates/index.html
├── static/app.css
├── static/app.js
└── locales/{zh-CN,en}.json
```

界面信息架构建议：

```text
任务配置 -> 计划确认 -> 执行监控 -> 结果质控 -> 研究报告
```

**展示规则**

- 计划确认页始终展示任务 DAG，不在中文版隐藏。
- 步骤卡默认显示状态、2–4 个关键指标和代表图。
- 日志、完整指标、产物和交互 Viewer 使用折叠区域。
- `execution/display/report` 三个范围同时以可读标签和原始 JSON 展示。

**验收标准**

- 修改英文文案不会破坏中文页面结构。
- 桌面端和移动端均可完成计划确认与结果查看。
- 轮询时不重载正在操作的 iframe。

### S-105 引入持久任务队列

当前后台线程适合单机演示。多病例或多用户环境建议增加：

- SQLite/PostgreSQL 任务表。
- 独立 worker 和 GPU resource slot。
- queued/running/reporting/completed/failed/cancelled 状态机。
- 取消、超时、失败重试和幂等执行。
- 结构化 JSON 日志和任务审计。

**验收标准**

- Dashboard 重启不影响正在执行的 worker。
- 相同 `work_root` 不能并发写入。
- 用户可以安全取消尚未开始的任务，并查看失败原因。

## P2：医学影像质量与科研价值

### S-201 输入质量评分

在 extraction 前增加 stack 级 QC：

- 运动、模糊、信噪、覆盖范围。
- 切片间强度异常和方向一致性。
- stack 与 mask 的 shape/affine 配对。
- 自动排除建议，但默认要求人工确认。

### S-202 重建后端选择和对比

在已有四后端接口基础上增加：

- 相同输入和空间上的统一客观指标。
- 失败原因分类，而不是只记录 exit code。
- 自动推荐主结果，但保留所有原生输出和人工选择。
- 防止“指标更好”被错误解释成“医学质量更好”。

### S-203 Registration 可视质控

增加：

- atlas/MRI 棋盘格。
- 边缘叠加和三视图同步。
- 关键解剖区域的局部放大。
- 自动状态与人工 `approved/rejected/pending` 分离。

### S-204 Tissue 和 ROI 合理性检查

增加：

- 连通域和孤立标签。
- 左右半球体积与空间对称性。
- 标签邻接关系和越界检查。
- 正式的 `Seg#### -> 解剖名称` 版本化映射。
- 图谱、标签映射和统计报告的版本绑定。

### S-205 Surface 拓扑质量

文件完整性之外增加：

- Euler number、handles、holes、自交和非流形边。
- white/pial 包含关系。
- 修复前后差异记录。
- 与 tissue/ROI 边界的投影一致性。

### S-206 孕周常模和报告边界

只有在数据来源、纳入标准、孕周分层、统计方法和独立验证明确后，才引入 percentile 或 z-score。

报告状态应明确拆分：

```text
technical_status = PASS | REVIEW | FAIL
visual_review = PENDING | APPROVED | REJECTED
clinical_interpretation = NOT_AVAILABLE
```

在完成医学验证和专家签署前，不把技术状态映射成正常/异常。

## P3：工程质量和可复现性

### S-301 CI 分层

- 每次提交：格式、静态检查、ShellCheck、单元测试、Schema test。
- 每日或手动：匿名小数据 integration test。
- GPU 环境手动触发：四后端完整 acceptance。
- GitHub Pages：只发布 `showcase/`，不打包运行数据。

### S-302 测试增强

优先补充：

- 文件 API 权限和路径穿越测试。
- 超大/错误 JSON 请求测试。
- Generate Plan 与 Confirm Run 并发测试。
- Dashboard 重启、worker 存活和 stale state 测试。
- 旧 manifest 到新 manifest 的迁移测试。
- 六步失败传播和下游跳过测试。

### S-303 可复现性清单

每个 run 自动记录：

- Git commit 或 source bundle checksum。
- 容器 SHA256。
- 模型、atlas、标签映射版本。
- 完整但脱敏的有效参数。
- CUDA、GPU、关键库版本。
- 输入和输出 artifact checksum。

### S-304 存储生命周期

建议将文件分为：

| 等级 | 内容 | 策略 |
| --- | --- | --- |
| 必须长期保存 | manifest、报告、QC、关键结果、provenance | 版本化归档 |
| 可压缩保存 | 日志、静态预览、交互 Viewer | 压缩并校验 |
| 可重新生成 | scratch、临时切片、缓存 | 完成验收后清理 |
| 本机 runtime | 容器、模型缓存 | 按版本和最后使用时间维护 |

清理工具必须先 `--dry-run`，输出精确清单，并按 run 目录执行，禁止对源码根目录或数据总根目录使用递归删除。

## 建议迭代顺序

### Milestone 1：安全且清晰

- S-001 文件访问范围。
- S-002 认证和脱敏。
- S-003 新运行资产迁出源码。
- S-103 配置统一。

**完成定义**：可以安全地在受控内网部署；干净源码仓库能够独立安装和测试。

### Milestone 2：可维护

- S-101 拆分 Pipeline。
- S-102 Run Manifest。
- S-104 Dashboard 解耦。
- S-301/S-302 CI 和测试。

**完成定义**：单步可测试、状态 contract 稳定、前端不再依赖字符串替换。

### Milestone 3：可扩展

- S-105 持久队列。
- S-303 可复现性。
- S-304 生命周期管理。

**完成定义**：支持多任务排队、重启恢复、审计和受控存储增长。

### Milestone 4：更强科研解释力

- S-201 至 S-206。

**完成定义**：工程 QC、人工视觉复核和医学解释有明确分层；新增指标均有来源、版本和验证记录。

## 首批 issue 建议

建议下一轮先建立以下 8 个 issue：

1. `security: replace absolute-path file API with artifact IDs`
2. `privacy: add LLM de-identification policy and audit event`
3. `config: introduce unified typed application config`
4. `storage: route new runs outside source tree`
5. `manifest: define versioned run/artifact schema`
6. `pipeline: extract dashboard state writer from shell orchestrator`
7. `dashboard: move HTML/CSS/JS to templates and locale files`
8. `ci: run unit, schema and security tests on every change`

这 8 项完成后，再开始队列系统和医学指标扩展，可以避免在不稳定的数据、配置和状态接口上继续叠加功能。
