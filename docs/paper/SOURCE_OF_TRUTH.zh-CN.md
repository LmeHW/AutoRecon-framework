# 事实归属表

哪类信息只允许出现在哪个文件。其它位置若需要同一事实，只允许链接到权威文件。改归属须同时改 [PROTOCOL.zh-CN.md](PROTOCOL.zh-CN.md) 并追加 ADR。

| 信息类型 | 唯一权威位置 | 其它位置怎么用 |
| --- | --- | --- |
| 跨会话怎么读、怎么改 | [PROTOCOL.zh-CN.md](PROTOCOL.zh-CN.md) | `.cursor/rules/isbi-2027-paper.mdc` 只做指针，不复制禁止列表或状态词 |
| 哪类事实写在哪 | 本文件 | [README.md](README.md) 只做目录摘要，不写「本轮是否空表」 |
| 论文题目、轨道确认、贡献列表 | [claims/SCOPE.zh-CN.md](claims/SCOPE.zh-CN.md) | 不得只写在 HANDOFF 或 writing 里 |
| ISBI 日期、页数、投稿轨道 | [venue/ISBI2027.zh-CN.md](venue/ISBI2027.zh-CN.md) | 禁止把截止日期抄进实验文档或 HANDOFF |
| 仓库里已经有什么 | [prior-work/INVENTORY.zh-CN.md](prior-work/INVENTORY.zh-CN.md) | 工程细节仍以原 docs / 代码为准；一句话里禁止可进稿数字 |
| 已有工作如何对应论文结构 | [prior-work/MAPPING.zh-CN.md](prior-work/MAPPING.zh-CN.md) | 不是最终贡献声明 |
| 未来实验规划 | [experiments/INDEX.zh-CN.md](experiments/INDEX.zh-CN.md) 与 `experiments/EXP-XXX.zh-CN.md` | **不要**写入 [../design/SUGGESTIONS.zh-CN.md](../design/SUGGESTIONS.zh-CN.md)。状态以 INDEX 为准 |
| 单实验字段约定 | [experiments/templates/EXPERIMENT.zh-CN.md](experiments/templates/EXPERIMENT.zh-CN.md) | 新实验必须从该模板复制 |
| 废弃实验 | [experiments/archive/](experiments/archive/) | INDEX 保留 `dropped` 行，不删 ID |
| 工程 backlog | [../design/SUGGESTIONS.zh-CN.md](../design/SUGGESTIONS.zh-CN.md) | 不是论文实验 |
| 系统设计 | [../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md](../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md) | paper 只引用。`pipeline/AGENTIC_WORKFLOW_PLAN.zh-CN.md` 不是权威副本 |
| 验证怎么跑 | [../validation/AGENTIC_E2E_VALIDATION.zh-CN.md](../validation/AGENTIC_E2E_VALIDATION.zh-CN.md) | 原始输出在 `validation_results/` |
| 对外实验汇报（持续更新） | [../reports/EXPERIMENTS.zh-CN.md](../reports/EXPERIMENTS.zh-CN.md) | 只写问题/逻辑/现状/已标注数字；不写实现细节；非 locked 数字不得进 CLAIM |
| 稳定性叙述与其它中间稿 | [../notes/](../notes/)（如 STABILITY_PATHWAY） | 给自己/AI 用的长稿；汇报勿直接贴全文；数字未登记 RES 前不得进 CLAIM |
| 相关工作的工程笔记 | [../research/](../research/) | [related-work/NOTES.zh-CN.md](related-work/NOTES.zh-CN.md) 只追加论文向条目 |
| 可写进稿的主张 | [claims/WORKING_CLAIMS.zh-CN.md](claims/WORKING_CLAIMS.zh-CN.md) | `writing/` 只引用 `状态=ready` 的 CLAIM |
| 可引用结果 | [results/INDEX.zh-CN.md](results/INDEX.zh-CN.md) | 指向原 run 路径；数字进稿必须经 empirical CLAIM |
| 图编号与来源 | [figures/INDEX.zh-CN.md](figures/INDEX.zh-CN.md) | 仓库内文件在 [figures/assets/](figures/assets/) |
| 英文投稿稿 | [writing/](writing/) | 只能引用 ready CLAIM |
| 决策 | [log/DECISIONS.zh-CN.md](log/DECISIONS.zh-CN.md) | 只追加 |
| 会话变更 | [log/CHANGELOG.zh-CN.md](log/CHANGELOG.zh-CN.md) | 只追加 |
| 下一会话从哪继续 | [log/SESSION_HANDOFF.zh-CN.md](log/SESSION_HANDOFF.zh-CN.md) | 每会话结束覆盖更新；不另立规则、不抄截止日期 |
| 产品使用与启动 | 仓库根 [README.md](../../README.md) | 论文闭环不是运行时入口 |
| 外部数据根 | 未另开 ADR 前无默认根 | results 行备注 `external` + 绝对路径 |
