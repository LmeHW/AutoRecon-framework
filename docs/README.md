# AutoRecon 文档索引

项目背景、快速启动和三种调用方式以根目录 [README](../README.md) 为准。运行时代码不读取本目录；提示词在 `agentic/prompts/`，验收语料在 `validation/nl_corpus.py`。

## 论文闭环（ISBI 2027）

跨 AI 会话的协议与知识目录在 [paper/README.md](paper/README.md)。触发词与开场必读见 [paper/PROTOCOL.zh-CN.md](paper/PROTOCOL.zh-CN.md)。工程 backlog 仍在下方「设计」中的优化建议，不是论文实验。

- [入口与目录职责](paper/README.md)
- [跨会话协议](paper/PROTOCOL.zh-CN.md)
- [事实归属](paper/SOURCE_OF_TRUTH.zh-CN.md)
- [题目与贡献范围](paper/claims/SCOPE.zh-CN.md)
- [已有工作清单](paper/prior-work/INVENTORY.zh-CN.md)
- [实验规划总表](paper/experiments/INDEX.zh-CN.md)
- [会话交接](paper/log/SESSION_HANDOFF.zh-CN.md)

## 汇报

- [实验汇报（全实验，持续更新）](reports/EXPERIMENTS.zh-CN.md)
- [工作台上传与多用户](reports/CLINIC_UPLOAD.zh-CN.md)

## 内部笔记（非汇报）

- [稳定性叙述](notes/STABILITY_PATHWAY.zh-CN.md)
- [实验规划中间稿](notes/EXPERIMENT_BRIEF.zh-CN.md)
- [依赖链概念](notes/DEPENDENCY_CHAIN.zh-CN.md)
- [QC 计划对照](notes/QC_PLAN_VS_CURRENT.zh-CN.md)


## 验证

- [自然语言到报告的分阶段验证](validation/AGENTIC_E2E_VALIDATION.zh-CN.md)

## 设计

- [Agentic 工作流设计](design/AGENTIC_WORKFLOW_PLAN.zh-CN.md)
- [下一阶段优化建议](design/SUGGESTIONS.zh-CN.md)

## 研究

- [研究报告方法学](research/FETALAGENTS_AUTORECON_MEDICAL_REPORT_METHODOLOGY.zh-CN.md)
- [医学报告分析](research/FETALAGENTS_MEDICAL_REPORT_ANALYSIS.zh-CN.md)

## 医生使用

- [医生使用说明 · 医院一](user/DOCTOR_TUTORIAL.zh-CN.md)
- [医生使用说明 · 医院二](user/DOCTOR_TUTORIAL.hospital2.zh-CN.md)

## 运维

- [外部协作网关](ops/GATEWAY.zh-CN.md)
- [历史病例 run 迁移记录](ops/LEGACY_RUN_MIGRATION.zh-CN.md)

## 仓库内相关说明

- [Pipeline 调用与输出约定](../pipeline/README.md)
- [容器与共享 runtime](../containers/README.zh-CN.md)
- [项目完成度审计（2026-07）](../presentation/PROJECT_COMPLETION_AUDIT.zh-CN.md)
