# ISBI 2027 论文闭环

本目录是 AutoRecon 面向 **IEEE ISBI 2027** 的实验–论文闭环知识根。运行时代码不读取此处。工程设计、验证方法和运维说明仍在 `docs/` 其它子目录；这里只登记论文主张、实验规划、会议约束，以及跨 AI 会话必须遵守的协议。

**进入论文模式后，先按这个顺序读完，再改其它文件：**

1. 本文件
2. [PROTOCOL.zh-CN.md](PROTOCOL.zh-CN.md)
3. [SOURCE_OF_TRUTH.zh-CN.md](SOURCE_OF_TRUTH.zh-CN.md)
4. [log/SESSION_HANDOFF.zh-CN.md](log/SESSION_HANDOFF.zh-CN.md)

触发词与例外见 PROTOCOL 第 1 节。语言：除 [writing/](writing/) 用英文撰写投稿物外，本目录一律中文。

当前实验/主张是否为空，以 INDEX 与 WORKING_CLAIMS 为准，不以本文件为准。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| [PROTOCOL.zh-CN.md](PROTOCOL.zh-CN.md) | 跨会话怎么读、怎么改 |
| [SOURCE_OF_TRUTH.zh-CN.md](SOURCE_OF_TRUTH.zh-CN.md) | 哪类事实只允许写在哪个文件 |
| [venue/ISBI2027.zh-CN.md](venue/ISBI2027.zh-CN.md) | 会议日期、页数、投稿轨道 |
| [prior-work/INVENTORY.zh-CN.md](prior-work/INVENTORY.zh-CN.md) | 仓库里已经有什么 |
| [prior-work/MAPPING.zh-CN.md](prior-work/MAPPING.zh-CN.md) | 已有工作如何松散对应 4-page 结构；**不是贡献声明** |
| [experiments/INDEX.zh-CN.md](experiments/INDEX.zh-CN.md) | 未来实验规划总表 |
| [claims/SCOPE.zh-CN.md](claims/SCOPE.zh-CN.md) | 题目、轨道、贡献列表 |
| [claims/WORKING_CLAIMS.zh-CN.md](claims/WORKING_CLAIMS.zh-CN.md) | 主张；进稿只认 `ready` |
| [results/INDEX.zh-CN.md](results/INDEX.zh-CN.md) | `RES-*` 结果指针 |
| [figures/INDEX.zh-CN.md](figures/INDEX.zh-CN.md) | `FIG-*`；文件在 `figures/assets/` |
| [writing/](writing/) | 英文投稿稿 |
| [related-work/NOTES.zh-CN.md](related-work/NOTES.zh-CN.md) | 论文向文献笔记；工程笔记仍在 `docs/research/` |
| [log/](log/) | 决策、变更、交接 |

## 闭环

```text
prior-work/INVENTORY  --能力登记-->  CLAIM (capability)
experiments/INDEX     --frozen-->    results/INDEX (RES-*)
RES-*                 --依据-->      CLAIM (empirical)
empirical CLAIM       --依据-->      CLAIM (contribution)
ready CLAIM           --唯一进稿门--> writing/
FIG-*                 --被 ready CLAIM 引用--> writing/
```

## 不要放进本目录的东西

- 工程 backlog：见 [../design/SUGGESTIONS.zh-CN.md](../design/SUGGESTIONS.zh-CN.md)
- 系统设计正文：见 [../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md](../design/AGENTIC_WORKFLOW_PLAN.zh-CN.md)
- 验证怎么跑：见 [../validation/AGENTIC_E2E_VALIDATION.zh-CN.md](../validation/AGENTIC_E2E_VALIDATION.zh-CN.md)
- 原始验证产物：`validation_results/`、`validation_runs/`（只允许在 `results/INDEX` 登记指针）
- 对外实验汇报：[../reports/EXPERIMENTS.zh-CN.md](../reports/EXPERIMENTS.zh-CN.md)
- 中间稿笔记：[../notes/](../notes/)
