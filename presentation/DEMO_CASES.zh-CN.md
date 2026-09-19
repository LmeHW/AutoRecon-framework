# AutoRecon 用户视角样例

## 样例 1：AnHuiJing，完整六步通过

用户需求：导入 AnHuiJing 现有 run，展示完整六步可视化和每一步 QC，基于 Evidence Bank 生成完整中文专业研究报告。

结果：六步 QC 均为 `pass`。Step 3 的 Mattes 为 `-0.33959`、GC 为 `-0.546999`；Tissue 与 ROI 均和 registered MRI 几何一致。报告保留全部指标、来源文件、结论置信度和解释边界。

- [样例清单](../demo_runs/2026-07-20T170535Z0000_6f4bbefc/demo_manifest.json)
- [Evidence Bank](../demo_runs/2026-07-20T170535Z0000_6f4bbefc/evidence_bank.json)
- [最终报告](../demo_runs/2026-07-20T170535Z0000_6f4bbefc/report.md)
- [用户流程截图](screenshots/01_anhuijing_user_flow.png)
- [Extraction 逐切片 Viewer 截图](screenshots/04_anhuijing_extraction_viewer.png)

## 样例 2：CaoLi，自动 QC 要求复核

用户需求：导入 CaoLi 注册空间 run，展示全部步骤、QC 和日志，生成完整中文研究报告。

结果：Extraction、Reconstruction、Tissue、ROI、Surface 通过；Registration 自动状态为 `review`。系统不把“流程完成”误写成“配准合格”，而是保留指标并要求查看 MPR overlay。

- [样例清单](../demo_runs/2026-07-20T170547Z0000_ff7bd5da/demo_manifest.json)
- [Evidence Bank](../demo_runs/2026-07-20T170547Z0000_ff7bd5da/evidence_bank.json)
- [最终报告](../demo_runs/2026-07-20T170547Z0000_ff7bd5da/report.md)
- [QC Review 截图](screenshots/02_caoli_qc_review.png)
- [Registration MPR 截图](screenshots/05_caoli_registration_mpr.png)

## 样例 3：BaiHuPing，只展示 Reconstruction、报告使用全部证据

用户需求：只展示 reconstruction，但用全部可用证据生成完整中文报告，并明确列出需复核的 QC 问题。

解析结果：`display_steps=[reconstruction]`；`report_steps=[]`，表示报告消费全部可用证据。Dashboard 不展示其它 pipeline 卡片，但 Evidence Bank 保留六步 QC。

结果：系统发现 Tissue 和 ROI 与 registered MRI 几何不一致并标记为 `fail`，证明显示范围不会裁剪证据或掩盖问题。

- [样例清单](../demo_runs/2026-07-20T172019Z0000_e47e3b68/demo_manifest.json)
- [Evidence Bank](../demo_runs/2026-07-20T172019Z0000_e47e3b68/evidence_bank.json)
- [最终报告](../demo_runs/2026-07-20T172019Z0000_e47e3b68/report.md)
- [范围与证据截图](screenshots/03_baihu_scope_evidence.png)

## 演示说明

这三个样例使用本地确定性隐私模式生成，以免把受试者路径和影像衍生数据发送给未经批准的外部 LLM。生产框架中的真实 LLM 仍负责自然语言结构化和白名单 DAG 规划；工具执行、QC、Evidence Bank 和报告约束均由本地确定性代码完成。
