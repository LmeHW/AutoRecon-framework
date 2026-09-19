# 会话交接

每会话结束覆盖更新本文件。下一会话只认这里写下的「下一步」和权威文件，不认未落地的聊天。截止日期见 [../venue/ISBI2027.zh-CN.md](../venue/ISBI2027.zh-CN.md)，不要把日期抄到这里。

## 当前状态（2026-09-19）

EXP-001 **开发集离线试跑已完成**（非 locked）：`validation_runs/exp001_current` → `exp001_20260918T0325Z`，960/960，`development_pilot`，仅 GLM。INDEX 仍为 `running`（正式 locked 未开）。对外摘要：`docs/reports/EXPERIMENTS.zh-CN.md`。中间稿已迁到 `docs/notes/`（ADR-003）。无 CLAIM/RES，题目未定。网关计算并发：全局 2 / 每用户 1。

## 下一步（需用户明确要求后再做）

- 专家审 NL+约束并开 ADR 解决 INV-007 后，锁 FlowBench test。
- 冻 Qwen checkpoint，再跑第二 backbone。
- locked 跑完后才登 `RES-*` / 写 empirical CLAIM；更新 `docs/reports/EXPERIMENTS.zh-CN.md`。
- EXP-004 正式队列需用户再下令。

## 未决问题

- SCOPE 题目与贡献句仍空。
- Qwen checkpoint 未冻。
- INV-007 60 vs 72。
- EXP-001/002 正式 locked gold 尚未标注。

## 不要做

- 不要把开发集试跑率写成 locked / 投稿结果。
- 不要把 `docs/notes/` 长稿直接当组会终稿；对外用 `docs/reports/`。
- 不要把 L1 REVIEW 当成整链阻断。
- 不要在无医生标签时寻优掩膜占比或 Mattes 阈值。
- 不要恢复 EXP-004 的 10×6 确认性矩阵或 No-verifier Holm。
- 不要把组会 20+20 数字写入 CLAIM。
- 不要把 `docs/design/SUGGESTIONS.zh-CN.md` 改写成论文实验。
- 不要在本文件抄截止日期或另立规则。
