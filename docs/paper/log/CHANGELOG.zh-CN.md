## 2026-09-19 汇报目录重整 + EXP-001 试跑收口

- 会话目标：对齐 EXP-001 试跑结束状态；将 `docs/reports` 改为纯汇报目录；生成全实验汇报稿。
- 改：`docs/reports/EXPERIMENTS.zh-CN.md`（新建）；原 `ISBI2027_*` / `STABILITY_PATHWAY` → `docs/notes/`（去 ISBI2027 前缀）；`CLINIC_UPLOAD_MULTIUSER` → `CLINIC_UPLOAD`；`SOURCE_OF_TRUTH`、INVENTORY、EXP-001/004、docs/README、HANDOFF；ADR-003。
- 未改：未写 RES/CLAIM；未把试跑率当 locked 结果。

# 变更日志

只追加。每条记录一次会话对权威文件的改动。

## 2026-09-17 启动 EXP-001 开发集离线试跑

- 会话目标：按用户要求自动开炮 EXP-001，并在对话结束后仍在服务器上跑完。
- 改：`experiments/INDEX.zh-CN.md`、`experiments/EXP-001.zh-CN.md`——状态 `idea` → `running`；运行命令指针改为 `scripts/launch_exp001_detached.sh` 与 `validation_runs/exp001_20260917T1348Z`。
- 覆盖更新：`log/SESSION_HANDOFF.zh-CN.md`。
- 工程侧（非 paper 结果）：新增离线 plan-only runner；本跑使用旧开发语料 72 条，4 变体 × GLM，Qwen 因 checkpoint 未冻而跳过。
- 明确：不是 locked test；不得把本跑数字写入 CLAIM 或 RES。
- 未做：未锁 1000 条 gold、未跑 Qwen、未启动 EXP-004 GPU、未建 CLAIM/RES。

## 2026-09-13 建立论文闭环目录与跨会话协议

- 会话目标：按计划创建 `docs/paper/`，统一已有工作、未来实验规划与规范的存放位置；不规划具体实验。
- 新建：`docs/paper/` 全树（PROTOCOL、SOURCE_OF_TRUTH、venue、prior-work、experiments 骨架、claims/results/figures/writing/related-work、log）。
- 填实：PROTOCOL、SOURCE_OF_TRUTH、venue/ISBI2027、prior-work/INVENTORY 与 MAPPING、ADR-001。
- 空表：experiments/INDEX、WORKING_CLAIMS、results/INDEX、figures/INDEX、related-work/NOTES。
- 工程侧：新增 `.cursor/rules/isbi-2027-paper.mdc`；更新 `docs/README.md` 索引。
- 未做：定题、abstract、baseline、GPU 实验日历、投稿正文。

## 2026-09-13 按审查修订协议（ADR-002）

- 会话目标：消除进稿门槛互相打架、INVENTORY 数字泄漏、SSOT 自相矛盾。
- 改：PROTOCOL、SOURCE_OF_TRUTH、paper README、docs/README、Cursor rule、INVENTORY、MAPPING、venue 约定、WORKING_CLAIMS、experiments/INDEX 与模板、results/INDEX、figures、writing README、related-work NOTES。
- 新建：`claims/SCOPE.zh-CN.md`、`figures/assets/README.zh-CN.md`、ADR-002。
- 未做：定题、具体实验、登记 RES、起草正文。

## 2026-09-13 登记 ISBI 论文实验计划

- 会话目标：将经相关工作核查后收紧的 ISBI 实验方案保存到论文闭环。
- 新建：`experiments/EXP-001.zh-CN.md` 至 `EXP-004.zh-CN.md`，分别规划公开自然语言/DAG benchmark、安全压力测试、Evidence Bank 报告盲评、真实队列技术可靠性与故障恢复。
- 更新：`experiments/INDEX.zh-CN.md`，登记 4 个 `idea` 实验；覆盖更新 `log/SESSION_HANDOFF.zh-CN.md`。
- 明确：现有工程验证不直接作为论文结果；旧语料只作开发集；主实验固定 FROST；不宣称临床诊断、自动 QC 效能或最佳重建后端。
- 未做：未运行实验、未登记 RES/FIG、未创建 CLAIM、未填写题目或起草正文。

## 2026-09-14 收口 QC 三态并收缩 EXP-004

- 会话目标：按审查修改文档，消除「REVIEW 断链」与「只改分数不断执行」两种错误规格。
- 改：`docs/reports/ISBI2027_QC_PLAN_VS_CURRENT.zh-CN.md`（L0 FAIL 阻断 / L1 REVIEW 可跑但合同不成功）；`ISBI2027_DEPENDENCY_CHAIN.zh-CN.md`；`ISBI2027_EXPERIMENT_BRIEF.zh-CN.md`。
- 改：`experiments/EXP-004.zh-CN.md` 与 INDEX——改为描述性 L0 队列 + 2–3 类 L0 故障示范、Exists-only、不进 Holm；废止 10×6 与 No-verifier。
- 明确：掩膜占比偏低属 L1，不承诺拦住重建启动；切断必须在执行器，不只 qc.py。
- 未做：未改 `qc.py` 代码、未寻优阈值、未跑实验、未建 CLAIM。
