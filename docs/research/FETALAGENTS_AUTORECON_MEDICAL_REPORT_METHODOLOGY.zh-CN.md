# AutoRecon-FetalAgents 医学报告方法学

## 摘要

本文提出一套面向胎儿脑 MRI 重建 pipeline 的证据驱动医学报告方法。方法借鉴 FetalAgents 的 agentic clinical workflow：由 Coordinator 解析任务，专用工具生成结构化证据，Summarizer 只基于证据生成报告。与 FetalAgents 面向胎儿超声的 plane classification、segmentation、biometry 和 clinical report 不同，AutoRecon 面向多栈胎儿脑 MRI 的重建、配准、组织分割、ROI、surface 和 dashboard 可视化。本文方法的核心创新是将 pipeline 产物组织为 Evidence Bank，再由确定性模板或受约束 LLM 生成专业、可审计、可复现的研究型医学报告。

## 1. 背景与 FetalAgents 启发

FetalAgents 论文指出，胎儿影像分析需要从视觉感知、分割、测量到报告生成的完整 workflow，而不是单一模型的点预测。其系统包含三个角色：Coordinator 解释用户问题并分派专家；Expert Agents 调用专用视觉模型并输出结构化 JSON；Summarizer 汇总专家输出和工具决策，形成结构化临床报告。论文还强调 WHO 生长曲线 percentile sanity check、异常测量反思替换、视频关键帧聚合和 patient metadata 交叉验证。

GitHub 仓库显示 FetalAgents 支持 classification、segmentation、biometry 和 reporting 四类任务；项目结构中包含 `main.py`、`tools/`、`external_tools/` 和 `reference/`，其中 reference 表用于 HC/AC/GA 相关参考。其工程启发是：报告生成不是直接让 LLM 诊断，而是先产生可机器校验的中间证据，再进行受限汇总。

资料来源：

- FetalAgents paper: <https://arxiv.org/abs/2603.09733>
- FetalAgents HTML: <https://arxiv.org/html/2603.09733>
- FetalAgents GitHub: <https://github.com/huang-jw22/FetalAgents>

## 2. AutoRecon 可获得的数据

| Pipeline 阶段 | 当前可用产物 | 可支持的报告内容 | 不应越界的内容 |
| --- | --- | --- | --- |
| 2D extraction | staging subject、BTFE stack、seg 输入 | 输入栈数量、数据组织完整性 | 不能判断全部扫描覆盖是否充分，除非加入覆盖 QC |
| 3D reconstruction | `outputs/recon/<subject>.nii.gz`、MPR viewer | NIfTI 可读性、维度、重建可视化入口 | 不能自动诊断脑结构异常 |
| registration | `summary.csv`、warped image、registration viewer | atlas、status、QC group、相似性指标 | 不能直接等同于解剖配准完美 |
| tissue | Tissue NIfTI、overlay viewer | 组织分割文件存在性、可视化复核入口 | 不能自动报告组织异常 |
| ROI | ROI NIfTI、ROI viewer | ROI parcellation 完整性、统计准备度 | 无 label map 时不能解释具体脑区 |
| surface | pial/white/inflated、area、sulc、curvature、stats | surface 完整性、皮层/表面量化准备度 | 不能声称皮层成熟正常或异常 |
| stats | `roi86_basic.stats`、`roi86_thicknessproxy_cortexonly.stats` | ROI 数量、总体积、最大区域、cortex-only 量化 | 无 GA reference 时不能给 percentile/z-score |
| dashboard/logs | run_state、step logs、interactive viewers | 步骤状态、错误模式、人工 reviewer checklist | 不能替代专家阅片 |

## 3. 方法：Evidence Bank 到专业报告

### 3.1 Agent 分工

1. Coordinator  
   解析用户意图、GA、subject、existing run、执行模式和需要的分析范围。

2. Deterministic Experts  
   从 pipeline 结果中提取结构化证据：NIfTI header、step status、registration summary、surface 文件完整性、stats 体积、log findings。

3. Evidence Bank Builder  
   将工具输出转换为 claim-level evidence，每条证据包含 `claim_id`、`claim_level`、`statement`、`evidence`、`confidence`。

4. Report Summarizer  
   只允许根据 Evidence Bank 生成报告。可使用模板生成，也可由 LLM 进行语言润色，但 LLM 不能添加 Evidence Bank 中不存在的诊断结论。

### 3.2 报告结构

推荐 dashboard 中渲染英文报告，结构如下：

1. Case and Acquisition Context
2. Reconstruction and Registration Quality
3. Tissue, ROI, and Surface Evidence
4. Quantitative Findings
5. Evidence Bank
6. Interpretation Limits
7. Suggested Impression
8. Reviewer Checklist

### 3.3 LLM 生成协议

LLM 输入必须是：

- User request
- Evidence Bank JSON
- Capability boundary
- Missing evidence list
- Report schema

LLM 允许：

- 将证据改写成专业、精简、连贯的医学风格语言
- 汇总已经存在的限制
- 要求补充缺失的 reference、label map 或 reviewer score

LLM 禁止：

- 根据图像路径或体积数字直接诊断异常
- 在没有 GA reference 时写 normal、abnormal、percentile、growth delay
- 将 `Seg####` 编造成具体脑区名称
- 隐藏失败步骤、缺失文件或日志错误

工程模板已保存为 `agentic/prompts/medical_report_summarizer.md`。该 prompt 是报告生成的最小安全边界；后续即使替换模型或 API provider，也应保持相同输入契约和禁止项。

## 4. 当前报告模板

### Fetal Brain MRI Professional Report

- Report type: research-use fetal brain MRI reconstruction and quantification report.
- Case context: subject, GA, source stack count, run status.
- Technical image evidence: reconstruction, tissue, ROI NIfTI validity and dimensions.
- Registration quality: status, QC group, atlas path, registration viewer.
- Quantitative evidence: ROI86 count, total segmented volume, cortex-only volume, largest generic regions.
- Surface evidence: bilateral white/pial/inflated completeness, stats availability, 3D viewer.
- Evidence Bank: claim-by-claim support and confidence.
- Interpretation limits: missing label map, missing normative curves, no automated abnormality detector.
- Suggested impression: technical readiness for expert review and research quantification.

## 5. BaiHuPing 示例的证据化总结

在当前 BaiHuPing demo 中，pipeline 可支持以下结论：

- 3 个 BTFE stack 已进入工作流。
- reconstruction、tissue、ROI NIfTI 文件可读，维度一致。
- registration summary 标记为 `ok`，QC group 为 `acceptable`。
- bilateral white/pial/inflated surface 文件完整。
- ROI86 stats 和 cortex-only stats 存在，可计算 region count、总体积和最大通用区域。
- dashboard 提供 reconstruction、registration、tissue、ROI、surface 的交互式复核入口。

该 case 仍不能自动生成临床诊断，因为缺少：

- ROI label map：无法把 `Seg####` 解释为具体脑区。
- GA-matched normative reference：无法输出 percentile 或 z-score。
- visual QC scoring：无法量化 motion、coverage、boundary plausibility、surface topology。
- 专家签名：无法作为临床报告。

## 6. 建议新增的 pipeline 方法

### 6.1 Label Map Adapter

新增 `roi_label_map.csv/json`，字段至少包括 `seg_id`、`label_name`、`hemisphere`、`tissue_group`、`clinical_group`。报告中所有 region-level 描述必须从该文件映射。

### 6.2 GA Normative Reference Adapter

接入 GA-matched 胎儿脑 MRI 参考曲线，字段包括 `ga_week`、`metric_name`、`p2_5`、`p50`、`p97_5` 或 mean/std。只有该模块通过验证时，报告才允许输出 percentile、z-score 和 growth plausibility。

### 6.3 Visual QC Module

在 dashboard 中增加 reviewer 表单或自动 QC 占位字段：

- stack coverage
- motion severity
- reconstruction sharpness
- registration plausibility
- tissue boundary plausibility
- ROI plausibility
- surface topology quality

### 6.4 Evidence Bank Export

每次 run 输出 `medical_evidence.json` 和 `report.md`，作为 LLM、Markdown report 和人工复核的稳定输入。这样报告可复现、可审计，也便于后续论文实验统计。

## 7. 方法创新性

1. 将 FetalAgents 的多专家胎儿超声流程迁移到胎儿脑 MRI reconstruction pipeline。
2. 从“pipeline completed”提升为“evidence-backed medical-style reporting”。
3. 用 Evidence Bank 约束 LLM，降低 hallucination 和越界诊断风险。
4. 将可视化 dashboard 纳入报告证据链，使报告、图像、日志和统计结果可相互追溯。
5. 在缺少 label map/reference 时主动降级为研究型报告，保证专业边界。

## 8. 验证计划

最小验证：

- `python -m py_compile agentic/*.py`
- import existing run，确认 `report_json.medical_report.evidence_bank` 存在
- 确认 run 目录自动写出 `medical_evidence.json` 和 `report.md`
- 确认 dashboard Markdown 渲染包含 `Fetal Brain MRI Professional Report`
- 确认 `.env` 不可通过 dashboard file API 读取

扩展验证：

- 人工 reviewer 对 dashboard 五个 viewer 打分
- 对多个 GA case 统计 missing evidence rate
- 接入 label map 后验证 region label 准确性
- 接入 reference 后验证 percentile/z-score 的数值正确性

## 9. 自审与优化结论

本方法当前已经满足“专业但不越界”的第一阶段目标：报告可解释 pipeline 产物、重建质量和量化准备度，但不会伪造诊断。下一阶段最重要的提升不是让 LLM 更自由，而是补齐 label map、GA reference 和 visual QC，使 Evidence Bank 能支持更强的医学解释。
