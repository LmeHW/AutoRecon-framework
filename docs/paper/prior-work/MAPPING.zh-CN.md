# 已有工作到 4-page 结构的映射

松散对应，**不是贡献声明**（not a contribution claim）。用于避免后续会话把工程现状随口写进某一节，或漏掉已有可引用条目。定题、定贡献之后应改 [../claims/SCOPE.zh-CN.md](../claims/SCOPE.zh-CN.md) 并另开 ADR 再收紧本表。

默认结构按 ISBI 4-page 常见块：Introduction / Related Work / Method / Experiments / Conclusion。页数与栏数以 [../venue/ISBI2027.zh-CN.md](../venue/ISBI2027.zh-CN.md) 与官网模板为准。

| 可能章节 | 可引用的 INV | 允许怎么用 | 不得怎么用 |
| --- | --- | --- | --- |
| Introduction：问题与系统定位 | INV-001、INV-004、INV-010 | 用 `capability` CLAIM 陈述系统定位。 | 写成已发表临床系统；写未登记 RES 的数字 |
| Related Work | INV-009 | 指向 `docs/research/` 中的 FetalAgents 对照笔记。论文向文献另记 [../related-work/NOTES.zh-CN.md](../related-work/NOTES.zh-CN.md)。 | 假装已有系统综述或实验对比 |
| Method：编排 | INV-001、INV-006 | `capability` CLAIM。 | 写未实现的 agent 角色 |
| Method：确定性六步与后端 | INV-002、INV-003 | `capability` CLAIM。 | 宣称「最佳重建」 |
| Method：证据与报告 | INV-004、INV-005 | `capability` CLAIM。工程 `claim_id` 与论文 `CLAIM-*` 分开。 | 写 GA 常模百分位或自动诊断 |
| Experiments | INV-007、INV-008 | 仅说明「仓库里有验证入口」。要写结果必须先有 `EXP-*`（frozen）+ `RES-*` + `empirical` CLAIM。 | 把组会叙述或 INVENTORY 指针当成已批准实验；在数字冲突未解前引用语料条数 |
| Conclusion：局限 | INV-004 | 非诊断边界可作为局限。 | — |
| Conclusion：工程债（可选一句） | INV-011、INV-012 | 最多作为局限/未来工程，且不得进入 SCOPE 贡献列表。 | 写成论文贡献、future work 清单或实验计划 |

## 明确不要映射成论文贡献的条目

- INV-011 工程 backlog（可在局限中点到，不可进 SCOPE 贡献列表）
- INV-012 运维细节（同上，除非未来有专门 `contribution` CLAIM 且用户确认）
- `docs/design/SUGGESTIONS.zh-CN.md` 中的任何 S-xxx 任务
