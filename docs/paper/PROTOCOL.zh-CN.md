# 跨 AI 会话协议

权威文件。改本文件必须同时追加 [log/DECISIONS.zh-CN.md](log/DECISIONS.zh-CN.md)。聊天里口头改规则不算数。

目标：不同 AI 会话对「已有工作写哪、实验规划写哪、什么可以进稿」保持同一套约定。Cursor 规则只做路由，细则以本文件为准。

## 1. 开场必读

仅当用户明确指向本闭环时才进入论文模式。触发条件（满足一条即可）：

- 消息含 `ISBI`、`docs/paper`、`投稿`、`论文实验`、中文「论文」（且不是在谈工程文档里的报告）
- 正在修改 `docs/paper/` 或 `.cursor/rules/isbi-2027-paper.mdc`

**不要**仅因英文 `paper`、`claim`、`claim_id` 或工程「做个实验」进入论文模式。仓库 Evidence Bank 使用 `claim_id`，与 `CLAIM-*` 不是同一命名空间。

进入论文模式后，按顺序读完再动手：

1. [README.md](README.md)
2. 本文件
3. [SOURCE_OF_TRUTH.zh-CN.md](SOURCE_OF_TRUTH.zh-CN.md)
4. [log/SESSION_HANDOFF.zh-CN.md](log/SESSION_HANDOFF.zh-CN.md)

未读完这四份，不得修改 `docs/paper/` 下其它文件，也不得把论文实验写进 `docs/design/`。

需要改会议日期或页数时，再读 [venue/ISBI2027.zh-CN.md](venue/ISBI2027.zh-CN.md)。引用仓库现状或撰写 `CLAIM-*` 前，必须先读 [prior-work/INVENTORY.zh-CN.md](prior-work/INVENTORY.zh-CN.md)，并对照其「权威文档 / 代码」列核对是否过期；过期则先改 INVENTORY，再写主张。

## 2. 硬规则

1. **一类事实一个权威文件。** 归属见 [SOURCE_OF_TRUTH.zh-CN.md](SOURCE_OF_TRUTH.zh-CN.md)。其它文件只能链接，禁止再写一份会过期的副本（含把截止日期抄进 HANDOFF）。
2. **工程与论文分离。** 系统设计、验证方法、运维、组会材料留在原 `docs/` 子目录。论文主张、实验规划、会议约束只进 `docs/paper/`。
3. **工程 backlog 不是论文实验。** [docs/design/SUGGESTIONS.zh-CN.md](../design/SUGGESTIONS.zh-CN.md) 只登记工程任务。论文实验只登记在 `docs/paper/experiments/`。禁止把 SUGGESTIONS 条目改写成贡献点。
4. **已有工作先登记再引用。** 仓库里已有的能力必须先出现在 INVENTORY，才能进入 claims。禁止把未登记现状直接写成新贡献。INVENTORY 的「一句话」禁止写入可进稿的实验结果数字。
5. **原始结果不进 paper。** 禁止把 `validation_results/`、`validation_runs/` 大段复制进本目录。可引用结果只在 [results/INDEX.zh-CN.md](results/INDEX.zh-CN.md) 登记为 `RES-*`。
6. **进稿只有一道门：`CLAIM.状态=ready`。** [writing/](writing/) 只能引用状态为 `ready` 的 `CLAIM-*`。`EXP-*`、`RES-*`、`FIG-*`、`INV-*` 都不得单独作为进稿依据；它们只做 CLAIM 的依据。禁止在写作时发明新 claim。禁止引用 `draft` / `dropped` 主张。
7. **未经用户明确要求，不得自行填写 `docs/paper/experiments/` 中的具体实验，不得把 CLAIM 标为 `ready`，不得起草投稿正文，不得写入题目。** 「继续」「下一步」不够明确。需要类似：规划实验、定题、这条可以进稿、开始写正文。工程上的验证、试跑、单元测试不是论文实验。
8. **改协议本身** 只能改本文件和 `SOURCE_OF_TRUTH.zh-CN.md`，并追加 ADR。不得在 SESSION_HANDOFF 里另立一套规则。已有 ADR 正文不改写；推翻时新增 ADR 并写明取代哪一条。
9. **语言。** 除 `writing/` 外使用中文。会议专有名词保留英文。
10. **数字。** 写入 CLAIM 或 writing 的实验结果数字（例数、重复次数、指标值等）必须来自已登记的 `RES-*`。权威工程文档之间的数字冲突未开 ADR 前，禁止把任一数字写入 CLAIM。
11. **图。** 投稿图必须先有 `FIG-*`。仓库内文件放 [figures/assets/](figures/assets/)；含病例影像或过大文件只登记外部路径，不入库。

## 3. 编号、类型与状态

下一号 = 该前缀当前最大编号 + 1。禁止复用已废弃 ID。禁止跳号。两个会话冲突时以先写入 INDEX / 主张表的编号为准，后者改用下一号。

| 对象 | 格式 | 分配位置 | 冲突时 |
| --- | --- | --- | --- |
| 已有工作 | `INV-001` 起 | [prior-work/INVENTORY.zh-CN.md](prior-work/INVENTORY.zh-CN.md) | 以 INVENTORY 为准 |
| 实验 | `EXP-001` 起 | [experiments/INDEX.zh-CN.md](experiments/INDEX.zh-CN.md) | **状态、是否 dropped 以 INDEX 为准**；设计正文以 `EXP-XXX.zh-CN.md` 为准 |
| 结果指针 | `RES-001` 起 | [results/INDEX.zh-CN.md](results/INDEX.zh-CN.md) | 以 results/INDEX 为准 |
| 主张 | `CLAIM-001` 起 | [claims/WORKING_CLAIMS.zh-CN.md](claims/WORKING_CLAIMS.zh-CN.md) | 以 WORKING_CLAIMS 为准 |
| 图 | `FIG-001` 起 | [figures/INDEX.zh-CN.md](figures/INDEX.zh-CN.md) | 以 figures/INDEX 为准 |
| 决策 | `ADR-001` 起 | [log/DECISIONS.zh-CN.md](log/DECISIONS.zh-CN.md) | 只追加 |

实验状态词固定为：`idea` | `planned` | `running` | `frozen` | `dropped`。

- `idea`：尚未批准执行。
- `planned`：用户已确认设计，尚未跑。
- `running`：已有进行中的 run 指针。
- `frozen`：至少一条对应 `RES-*` 已写入 results/INDEX。frozen 只表示结果已登记，**不表示可进稿**。
- `dropped`：文件移入 [experiments/archive/](experiments/archive/)，INDEX 保留该行，不删除。

主张类型固定为：`capability` | `empirical` | `contribution`。

- `capability`：描述已有能力。必须挂 `INV-*`；`EXP`/`RES` 为空。正文禁止实验结果数字。
- `empirical`：实验结果。必须挂状态为 `frozen` 的 `EXP-*`，以及至少一条 `RES-*`。数字必须来自这些 RES。
- `contribution`：新颖贡献。必须挂至少一条类型为 `empirical` 的 CLAIM；不得仅凭 INV 声称「首次证明」。

主张状态词固定为：`draft` | `ready` | `dropped`。只有用户明确确认后才能从 `draft` 改为 `ready`。AI 不得自行标 `ready`。

题目与贡献列表的权威在 [claims/SCOPE.zh-CN.md](claims/SCOPE.zh-CN.md)，不是 HANDOFF，也不是 WORKING_CLAIMS 的某一行。

禁止发明其它状态词或类型词。

## 4. 新增与修改流程

**新增实验：** 复制 [experiments/templates/EXPERIMENT.zh-CN.md](experiments/templates/EXPERIMENT.zh-CN.md) 为 `experiments/EXP-XXX.zh-CN.md`，在 INDEX 增加一行，状态从 `idea` 起。不得先写进 writing。INDEX 不要增加「可进 writing」列。

**新增主张：** 在 WORKING_CLAIMS 增加一行，填类型与依据。新行状态必须是 `draft`。不要增加「可进 writing」列；进稿只看 `ready`。

**登记结果：** 只改 `results/INDEX`，分配 `RES-*`。路径写仓库相对路径。外部数据必须写绝对路径并在备注标明 `external`。未另开 ADR 前，不默认某个 data root。不粘贴数值表全文；CLAIM 需要的数字在主张行或 RES 备注里写最小集合。

**废弃实验：** 改 INDEX 状态为 `dropped`，把实验文件移到 `experiments/archive/`，追加 CHANGELOG。

## 5. 收场必写

会话中只要改过 `docs/paper/` 或相关 Cursor 规则，结束前必须：

1. 在 [log/CHANGELOG.zh-CN.md](log/CHANGELOG.zh-CN.md) **追加**一条：日期、会话目标、改了哪些权威文件。
2. **覆盖更新** [log/SESSION_HANDOFF.zh-CN.md](log/SESSION_HANDOFF.zh-CN.md)：下一步、未决问题、不要做的事。截止日期只写「见 venue 文件」，不抄日期。

聊天结论不落地等于不存在。下一会话只认 HANDOFF 和权威文件，不认未写入的对话。
