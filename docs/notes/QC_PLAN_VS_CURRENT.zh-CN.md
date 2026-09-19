# 计划修改与现有系统对照

> 内部笔记（非汇报终稿）。对外请用 [`docs/reports/EXPERIMENTS.zh-CN.md`](../reports/EXPERIMENTS.zh-CN.md)。


只对比 **准备改的合同/QC** 与 **现在仓库里在跑的东西**。六步流水线本身不换。未改代码前，下表「计划」不是已上线行为。

权威现状：[`agentic/qc.py`](../../agentic/qc.py)、配准默认值 [`run_ants_rigid_orient48_batch.py`](../../pipeline/scripts/registration/run_ants_rigid_orient48_batch.py)。问题定义见 [DEPENDENCY_CHAIN.zh-CN.md](DEPENDENCY_CHAIN.zh-CN.md)。4-page 测哪些 L0：见 [../paper/experiments/EXP-004.zh-CN.md](../paper/experiments/EXP-004.zh-CN.md)。

## 1. 三态合同（审查后写死）

| 状态 | 何时 | GPU / 下游 | 合同是否成功 | 报告 |
| --- | --- | --- | --- | --- |
| L0 FAIL | 缺文件、不可读、非有限、与上游几何不一致、fingerprint 变了 | **不启动**依赖该产物的下一步（执行器阻断） | 否 | 断点写死在这一步 |
| L1 REVIEW | 掩膜占比、覆盖、非零比例、Mattes/GC 等启发式触发 | **可以继续跑** | **否**（整步不得标合同 PASS） | 黄灯；下游不得假装「上游合同通过」 |
| L0 全过且无未解决 L0 | — | 允许启动下游 | 仅此时合同 PASS | 可写合同通过，仍非解剖正常 |

因此：

- 组会反例（掩膜约 2.9% 但文件在）→ **L1 REVIEW：重建仍可启动，但提取不得合同 PASS，报告黄灯。** 不承诺「不启动重建」，除非另有经医生标签校准的 L0（目前没有，也不在 4-page 里寻优 0.005）。
- 「REVIEW 一律断链」作废（会把大量现有可跑完病例整链停掉）。
- 「只有显示分数、脚本照跑」也不够：L0 FAIL 必须在 **executor / pipeline** 里不调下一步，不能只改 `qc_summary.json`。

实现面缺一不可：`qc.py` 分层 → 执行器按 L0 FAIL 阻断 → Dashboard / Evidence Bank / 报告同一断点。只改 QC JSON 测不到切断。

L2（医生：可用 / 需重跑 / 存疑）是工程后续，**不进 EXP-004 / 4-page 成功标准。** 有标签前不寻优 L1 切点。

## 2. 总原则

| | 现有 | 计划 |
| --- | --- | --- |
| 分层 | 合同、启发式、解剖混在一个 PASS；QC 写入 `qc_summary.json` 但不拦下一步 | L0 切断 / L1 黄灯可跑 / L2 医生档（后两者不放行合同）。**L0 已接入 `qc.py` + `run_single_case_pipeline.sh`：enforce/gate 失败则不启动下游脚本** |
| PASS | 阈值过了就可以往下走、并当成功 | 仅 L0 全过才是合同 PASS；L1 过不能当 PASS。实现：`contract_status` 只看 L0；Mattes 等 L1 失败不得切断 |
| 阈值 | 代码 heuristic 与 CLI 默认 | L0 来自依赖链；L1 无标签则只报连续量 |
| 优化目标 | 易变成多 PASS | 该断（L0）则断；L1 不误杀整链；不追求过关率 |
| 论文 | 组会数字不能进稿 | EXP-004 只测冻过的 L0；队列不做灵敏度 |

## 3. 逐步对照

| 步骤 | 现有 | 计划 |
| --- | --- | --- |
| Extraction | 掩膜全有且占比/覆盖过线 → 整步可 PASS | 缺掩膜/不可读 = L0 FAIL，**挡住重建**。占比、覆盖 = L1，整步最多 REVIEW |
| Reconstruction | 有限值/体素/强度为硬条件；非零过线可 PASS | 缺文件/NaN = L0 FAIL，**挡住配准**。非零比例 = L1。补重建相对提取的几何/指纹（规格未写进代码前不当已有 L0） |
| Registration | Mattes/GC 过线 → PASS；未过 REVIEW，图仍在、下游可跑 | 无配准图 = L0 FAIL。Mattes/GC = L1 连续量，不再单独当配准合同成功。叠图 = L2，不进 4-page |
| Tissue / ROI | 几何不一致已会 FAIL | **升为 L0 切断**。前景比例 = L1。上游 L0 FAIL 则本步不启动 |
| Surface | 8 个文件齐 = PASS | 不齐 = L0。拓扑 = L1。不写皮层正常 |
| 整链 | 各步独立；上游烂下游仍可「完成」 | L0 FAIL 不启动下游；L1 REVIEW 可跑但链上合同不成功；三处文本同一断点 |

## 4. 阈值

| | 现有 | 计划 |
| --- | --- | --- |
| 0.005、0.80、0.10、−0.25、−0.40 | 当 PASS 放行 | 不当放行。无 L2 标签前 **不改这些数字寻优** |
| 几何 atol=1e-3、文件、有限值 | 硬条件 | 明确为 L0 |
| 文献 | 无 | 只称项目合同 |

## 5. 和实验的关系

- 点 1 前缀忠实：不靠改 QC。
- 点 2 合同传播：靠 L0 执行器切断 + 报告一致。L1 解决的是「假 PASS」，不是「假启动」。
- EXP-004：描述性队列的成功只用 L0；故障示范只注入 L0 违约（缺产物/非零退出、几何不一致、fingerprint 或 SIGTERM 中的 2–3 类），对照 Exists-only。不进 Holm。L2 不测。

```text
现有：启发式过了 → PASS → 下游当上游成功
计划：L0 FAIL → 不启动下游
      L1 REVIEW → 可跑、合同不成功、报告黄灯
      L0 全过 → 合同 PASS（仍非解剖正常）
```
