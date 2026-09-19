# 决策记录

只追加，不改写已有 ADR 正文。若必须推翻旧决策，新增 ADR 并写明取代哪一条。

## ADR-001 建立 ISBI 2027 论文闭环目录与跨会话协议

- 日期：2026-09-13
- 状态：accepted

决定：

- 在 `docs/paper/` 建立实验–论文闭环知识根，目标 venue 为 ISBI 2027 的 4-page paper。
- 一类事实一个权威文件，归属见 `SOURCE_OF_TRUTH.zh-CN.md`。
- 现有 `docs/design/`、`docs/validation/`、`docs/research/`、`docs/ops/`、`docs/reports/` 不迁移、不复制正文。
- 工程 backlog 继续只写在 `docs/design/SUGGESTIONS.zh-CN.md`；论文实验只写在 `docs/paper/experiments/`。
- 原始验证产物留在 `validation_results/` 与 `validation_runs/`；paper 侧只登记指针。
- 协议与清单用中文；仅 `writing/` 用英文。
- Cursor 规则 `.cursor/rules/isbi-2027-paper.mdc` 只做路由，细则留在 `PROTOCOL.zh-CN.md`。
- 本轮（建立目录时）不定题、不写 abstract、不选 baseline、不填写具体实验。

## ADR-002 统一进稿门槛并收紧协议（取代 ADR-001 末条的时效解读）

- 日期：2026-09-13
- 状态：accepted
- 取代：ADR-001 最后一条「本轮不定题…」不得再被读成长期禁令。长期规则改为 PROTOCOL 第 2 节第 7 条：未经用户明确要求不得填实验、不得标 ready、不得写正文。

决定：

- `writing/` 只引用 `CLAIM.状态=ready`。EXP / RES / INV / FIG 不得单独进稿。
- 主张必须标明类型 `capability` | `empirical` | `contribution`；状态词 `draft` | `ready` | `dropped` 为强制而非建议。AI 不得自行标 `ready`。
- 删除各 INDEX 上重复的「可进 writing」列。
- INVENTORY 一句话禁止可进稿数字；验证文档与组会材料的语料条数冲突未解前禁止写入 CLAIM。
- 题目与贡献列表权威为 `claims/SCOPE.zh-CN.md`。
- 增加 `RES-*`、`INV-*` 编号规则；实验状态以 experiments/INDEX 为准。
- Cursor 规则只保留触发与开场指针，不复制禁止列表。触发词不含单独的英文 `paper` / `claim`。
- HANDOFF 不得抄截止日期。空表不得放占位数据行。
- INV-011 / INV-012 可在局限中点到，不得进入 SCOPE 贡献列表。

## ADR-003 汇报与中间稿分目录

- 日期：2026-09-19
- 决定：`docs/reports/` 只放对外/组会汇报 Markdown；原 ISBI2027_* 与 STABILITY 等长中间稿迁至 `docs/notes/`，并去掉文件名中的 `ISBI2027` 前缀。全实验持续更新的汇报权威为 `docs/reports/EXPERIMENTS.zh-CN.md`。
- 理由：汇报需要短、有逻辑与结果视图；中间稿给自己/AI，二者混在同一目录会过期并被误读成定论。
- 后果：SOURCE_OF_TRUTH 同步改归属；paper/INDEX/INVENTORY 等链接改指 `docs/notes/`；汇报数字仍受「未登记 RES 不得进 CLAIM」约束。

