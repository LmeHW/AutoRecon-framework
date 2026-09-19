# AutoRecon Agentic 总体目标完成度审计

审计日期：2026-07-21

## 审计结论

总体工程闭环已经实现：自然语言需求可经过结构化意图解析和白名单工具规划形成 DAG，经用户确认后执行或导入结果；每一步均生成可追溯的技术 QC；Evidence Bank 将原始需求、计划、逐步证据、结论和限制持久化；最终生成专业研究型胎儿 MRI 报告并在 Dashboard 展示。

这里的“专业医学报告”严格指研究决策支持报告，不等同于临床诊断报告。系统不会在缺少孕周常模、解剖标签映射、异常检测器和专家签署时判断正常或异常。

## 逐项验收

| 需求 | 权威实现/产物 | 验收证据 | 状态 |
|---|---|---|---|
| LLM 理解自由自然语言 | `agentic/coordinator.py::coordinate_with_llm` | 两阶段请求解析事件；OpenAI-compatible/Anthropic 双协议；规则 fallback | 完成 |
| LLM 动态规划工具 | `agentic/planner.py::plan_with_llm` | 工具注册表、依赖闭包、JSON 校验、一次修复、白名单与拓扑检查 | 完成 |
| 未确认计划不执行 | Dashboard Generate Plan / Run 分离 | `/api/plan` 只保存计划，Run 单独触发异步执行 | 完成 |
| 只执行计划而非固定全流程 | `agentic/executor.py`、pipeline `--steps/--resume` | 执行步骤及依赖闭包传入 pipeline | 完成 |
| Step 4/5/6 基于 Step 3 | pipeline registered input 规范 | Tissue/ROI 使用 `outputs/registered_input/<subject>.nii.gz`；Surface 依赖 Tissue+ROI；几何一致性进入 QC | 完成 |
| 每一步都有可见 QC | `agentic/qc.py`、Dashboard QC cards | 六步分别有 2–4 个指标；Step 3 含 Mattes、GC 和配准产物存在性 | 完成 |
| 正确证据链 | `evidence_bank.json` | request → plan → step_qc/sources → claims → report_limits | 完成 |
| 报告使用证据而非臆测 | `agentic/reporter.py` | 报告逐步引用指标、阈值、状态和源文件；包含能力边界 | 完成 |
| 三个 scope 相互独立 | `execution_steps/display_steps/report_steps` | 回归测试覆盖“只展示 reconstruction、完整报告” | 完成 |
| 实时可视化和日志 | Dashboard incremental DOM、`/api/log-tail` | 每步 Live log、QC card、交互 Viewer；iframe 不因轮询重建 | 完成 |
| 服务重启恢复 | `dashboard_server.py::_recover_state_if_needed` | 读取 pipeline dashboard/pid 恢复完成或失败结果 | 完成 |
| Secret 安全 | 环境变量与启动脚本 | Key 不写代码、项目 `.env`、日志或 pipeline 子进程；脱敏错误测试 | 完成 |
| 用户视角样例与截图 | `demo_runs/`、`presentation/screenshots/` | 三个不同 QC/显示范围场景 | 完成 |
| 组会 PPT | `AutoRecon_Agentic_Group_Meeting.zh-CN.pptx` | 14 页；包含三类用户原始需求、系统理解和正确性证据；经 LibreOffice 渲染检查 | 完成 |

## 六步 QC 规范

| Step | 主要指标 | 自动状态含义 |
|---|---|---|
| Extraction | 掩膜成功率、前景占比、有效切片覆盖率 | 技术完整性和覆盖检查 |
| Reconstruction | 有限值比例、非零比例、稳健强度范围、体素数 | 可读取性和数值完整性 |
| Registration | Mattes、GC、规范化配准图像存在 | 自动配准技术 QC；仍要求视觉叠加复核 |
| Tissue | 标签数、前景占比、与 registered MRI 几何一致 | 标签产物和空间一致性 |
| ROI | 标签数、前景占比、与 registered MRI 几何一致 | 分区产物和空间一致性 |
| Surface | 6 个必要 surface 文件、2 个统计文件 | 输出完整性；不替代拓扑/解剖复核 |

所有自动阈值均标注来源或声明为 technical heuristic；除配准 CLI 阈值外，它们不是胎儿发育参考区间。

## 隐私与 LLM 边界

工程支持真实 LLM 解析和规划，但本次含受试者路径与影像衍生数据的演示采用本地确定性隐私模式，没有把患者衍生证据发送到外部网关。生产部署应使用经批准的本地模型，或只向外部模型发送脱敏、最小化的意图数据；医学结论始终由本地 Evidence Bank 约束。

## 仍需临床科研团队提供的增强项

- 图谱 `Seg####` 到正式神经解剖名称的版本化映射。
- 经验证的孕周匹配常模和百分位曲线。
- 运动、覆盖、组织边界、ROI 合理性和 surface 拓扑的专家评分标准。
- 临床使用前的独立验证、审计和专家签署流程。

这些属于医学验证和临床转化，不是当前编排、证据追踪与研究报告工程闭环的缺失。
