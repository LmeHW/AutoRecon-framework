# FetalAgents 对 AutoRecon 医学方向报告的启发

## 资料来源

- FetalAgents 论文：<https://arxiv.org/html/2603.09733>
- FetalAgents GitHub 仓库：<https://github.com/huang-jw22/FetalAgents>

## FetalAgents 的核心技术路径

FetalAgents 的关键不是让一个大模型直接“看图下结论”，而是把任务拆成可审计的专家工具链：Coordinator 判断任务，选择 plane classification、segmentation、biometry 等专家工具；各专家输出结构化结果；Summarizer 再把图像、测量、参考表和病人元数据整合成报告。

这对 AutoRecon 的启发是：报告不应该只说 pipeline completed，而应该把每个结论绑定到证据来源。例如 reconstruction quality 来自 NIfTI 可读性、MPR 预览、日志和 registration QC；ROI findings 来自 stats 文件；surface findings 来自 white/pial/inflated surface、area/curvature/sulc 文件和 surface screenshot。

## 可迁移到 AutoRecon 的报告原则

1. 证据先行：每条结论必须能回溯到文件、统计表、日志、截图或人工审核项。
2. 结构化中间结果：工具输出 JSON/CSV/Stats，再由报告器生成 Markdown，而不是让 LLM 自由发挥。
3. 医学报告边界清楚：当前系统可以生成研究型影像分析报告，但不能自动给出临床诊断。
4. GA 参考必须显式接入：没有 GA-matched normative table 时，报告不能声称正常、偏小、偏大或发育异常。
5. 专家复核是报告的一部分：dashboard 应展示 reviewer checklist，而不是只展示最终 summary。

## AutoRecon 专业化报告模板

### Fetal Brain MRI Professional Report

- Report type: Research-use fetal brain MRI reconstruction and quantification report.
- Subject / GA / stack count.
- Acquisition adequacy: source stacks, coverage, motion/artifact notes if available.
- Reconstruction quality: NIfTI validity, MPR review, registration QC, atlas used.
- Tissue and ROI evidence: tissue output, ROI output, segmentation stats, label-map availability.
- Surface evidence: white/pial/inflated files, surface stats, curvature/sulcal artifacts, visualization.
- Quantitative findings: total ROI volume, cortex-only volume, largest regions, asymmetry if label map supports hemispheric mapping.
- GA comparison: percentile or z-score only when validated reference curves are attached.
- Impression: technical readiness, research interpretability, and unresolved limitations.
- Reviewer checklist: reconstruction, registration overlay, tissue overlay, ROI overlay, surface topology, quantitative plausibility.

## 当前 BaiHuPing 示例的解释边界

当前 dashboard 可以支持“技术完整性 + 研究量化准备度”的结论：reconstruction、tissue、ROI、surface 和 stats 文件均存在时，可以说该 case 已准备好进行专家视觉复核和研究量化。

当前还不能支持完整医学诊断，因为 ROI stats 仍是通用 `Seg####` 标签，缺少可读的脑区 label map；报告也没有接入 31 周胎儿脑 MRI 的正常参考曲线，因此不能输出百分位、发育迟缓、脑区异常等临床判断。

## 建议的下一步实现

1. 接入 ROI label map，把 `Seg####` 转成真实胎儿脑区名称。
2. 接入 GA-matched normative reference，输出 percentile/z-score 和参考来源。
3. 增加 visual QC 表单：motion、coverage、registration、tissue boundary、ROI plausibility、surface topology。
4. 把报告拆成 Evidence JSON 和 Rendered Markdown 两层，保证 dashboard 可渲染、可审计、可复现。
5. 后续如果接入 LLM，只允许它基于 Evidence JSON 改写语言，不允许生成 Evidence JSON 中不存在的诊断结论。
