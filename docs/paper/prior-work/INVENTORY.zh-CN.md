# 已有工作清单

仓库内可被论文引用的**能力与文档入口**。只登记，不复制工程文档正文。未出现在本表的能力，不得写入 [../claims/WORKING_CLAIMS.zh-CN.md](../claims/WORKING_CLAIMS.zh-CN.md)。

编号 `INV-*` 不是贡献声明。本表「一句话」和「已有结果指针」列 **禁止写入可进稿的实验结果数字**（例数、重复次数、指标值）。查找产物用路径；要把数字写进 CLAIM，必须先登记 `RES-*`。

权威工程文档之间若数字冲突，在本表「冲突」列标明，未开 ADR 前禁止把任一数字写入 CLAIM。

| ID | 条目 | 一句话 | 权威文档 | 代码 / 入口 | 结果查找指针 | 冲突 |
| --- | --- | --- | --- | --- | --- | --- |
| INV-001 | Agentic 编排链路 | Coordinator 解析需求，Planner 生成受白名单约束的任务 DAG，用户确认后由确定性执行器跑 pipeline，再经 Evidence Bank 出研究型报告。LLM 不执行任意 Shell，不替代重建/配准/分割算法。 | [docs/design/AGENTIC_WORKFLOW_PLAN.zh-CN.md](../../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md)；产品叙述见根 [README.md](../../../README.md) | `agentic/coordinator.py`、`agentic/planner.py`、`agentic/executor.py`、`agentic/reporter.py`、`agentic/cli.py` | `validation_results/current/natural_language_*.json` | — |
| INV-002 | 六步确定性 pipeline | extraction → reconstruction → registration → tissue → ROI → surface，每步技术 QC 与可视化。标准分析空间为 registered MRI。 | [pipeline/README.md](../../../pipeline/README.md) | `pipeline/run_single_case_pipeline.sh` 及 `pipeline/` 各步脚本 | `validation_results/current/real_pipeline/`、`real_pipeline_manifest.json` | — |
| INV-003 | 四种重建后端 | FROST、NeSVoR、AutoSVRTK、NiftyMIC 可作为重建工具选择。系统可跑多种后端并做技术比较，但不宣称最终最佳方法。 | 根 README「六步处理能力」；[docs/notes/STABILITY_PATHWAY.zh-CN.md](../../notes/STABILITY_PATHWAY.zh-CN.md) 中的拒绝边界 | `pipeline/` 重建后端封装；`--reconstruction-tool` | `backend_validation/`（工程验收，非论文 RES） | — |
| INV-004 | 技术 QC 与非诊断边界 | 每步状态为 PASS / REVIEW / FAIL。技术检查通过不代表胎儿医学正常。无常模与专家审阅时不写正常/异常/百分位；不连 HIS/PACS。 | 根 README；[docs/research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md](../../research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md) | `agentic/qc.py`、`agentic/reporter.py`、`agentic/prompts/medical_report_summarizer.md` | 报告回退行为见 [docs/validation/AGENTIC_E2E_VALIDATION.zh-CN.md](../../validation/AGENTIC_E2E_VALIDATION.zh-CN.md) | — |
| INV-005 | Evidence Bank 报告 | 工具输出转为 claim-level evidence（工程 `claim_id`，不是论文 `CLAIM-*`）；Summarizer 只基于证据改写。空回复、编造数字、写出诊断则回退模板。 | [docs/research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md](../../research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md) | `agentic/reporter.py`（`_build_evidence_bank`）；run 内 `evidence_bank.json` | `validation_results/current/real_reports/`、`historical_import/` | — |
| INV-006 | 三种执行模式 | `run_pipeline` / `import_existing` / `plan_only`。导入只看不开 GPU；计划须过 schema 与依赖检查才授权计算。 | 根 README「Dashboard 使用方式」；[docs/design/AGENTIC_WORKFLOW_PLAN.zh-CN.md](../../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md) | `agentic/models.py`、`agentic/schema_validation.py`、`agentic/schemas/` | `validation_results/current/historical_import/` | — |
| INV-007 | 自然语言规划验证 | 金标语料导出、fallback/LLM 规划重复；结构不合法的计划不拿去实算。 | [docs/validation/AGENTIC_E2E_VALIDATION.zh-CN.md](../../validation/AGENTIC_E2E_VALIDATION.zh-CN.md)；[docs/notes/STABILITY_PATHWAY.zh-CN.md](../../notes/STABILITY_PATHWAY.zh-CN.md) | `scripts/validate_agentic_e2e.py`；语料 `validation/nl_corpus.py` | `validation_results/current/natural_language_gold.json` 等；稳定性批次见组会文档中的 `validation_runs/stability_*` | 验证文档与组会材料对语料条数的陈述不一致。未开 ADR 并登记 RES 前，禁止把任一数字写入 CLAIM |
| INV-008 | 套 A / 套 B 稳定性叙述 | 套 A：新建分析。套 B：从已有产物继续。测范围执行、拒绝越权、中断续跑。此为组会/验证叙述，尚未登记为 `RES-*`。 | [docs/notes/STABILITY_PATHWAY.zh-CN.md](../../notes/STABILITY_PATHWAY.zh-CN.md) | 同 INV-007 | `validation_runs/stability_expand_20260907T1325Z`、`validation_runs/stability_continue_20260907T1325Z`（若本机存在） | 例数只存在于组会材料，未升格为 RES |
| INV-009 | FetalAgents 方法学笔记 | 将 FetalAgents 的 Coordinator / Expert / Summarizer 与证据先行原则对照到 AutoRecon 的 MRI pipeline 与报告边界。属研究笔记，不是本仓库已发表论文。 | [docs/research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md](../../research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md)、[docs/research/FETALAGENTS_MEDICAL_REPORT_ANALYSIS.zh-CN.md](../../research/FETALAGENTS_MEDICAL_REPORT_ANALYSIS.zh-CN.md) | 无独立代码路径 | 无实验产物 | — |
| INV-010 | Dashboard 与研究工作台 | 中文 Dashboard 为安全启动默认入口：描述需求、生成计划、确认后执行；结果中心只检索。 | 根 README；[docs/notes/STABILITY_PATHWAY.zh-CN.md](../../notes/STABILITY_PATHWAY.zh-CN.md) | `scripts/run_agentic_dashboard.sh`、`agentic/dashboard_cn.py` | 组会截图指针写在 STABILITY_PATHWAY 内，不复制到 paper | — |
| INV-011 | 工程下一阶段（非论文实验） | 数据边界、文件 API 收紧、subject 脱敏、运行资产迁出源码目录等。这些是工程 backlog，禁止当作 ISBI 实验或贡献。 | [docs/design/SUGGESTIONS.zh-CN.md](../../design/SUGGESTIONS.zh-CN.md) | 见该文档各 S-xxx | 无 | — |
| INV-012 | 运维与协作边界 | 外部协作网关、历史病例 run 迁移。支撑可复现，通常不进入 4-page 方法节，除非未来 claim 明确需要。 | [docs/ops/GATEWAY.zh-CN.md](../../ops/GATEWAY.zh-CN.md)、[docs/ops/LEGACY_RUN_MIGRATION.zh-CN.md](../../ops/LEGACY_RUN_MIGRATION.zh-CN.md) | `agentic/legacy_paths.py` 等 | 迁移记录见 ops 文档 | — |

## 使用规则

- 新增能力：先加 `INV-*` 行，再改 [MAPPING.zh-CN.md](MAPPING.zh-CN.md)。
- 权威文档冲突时，以该行「权威文档」列为准，数字冲突另见「冲突」列，并开 ADR。
- `pipeline/AGENTIC_WORKFLOW_PLAN.zh-CN.md` 若仍存在，视为 `docs/design/` 的非权威副本，不要在本表单列。
