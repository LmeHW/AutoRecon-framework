# AutoRecon（framework 分支）

这条分支只含系统源码，给对照 **Agent 编排 + 确定性 Pipeline** 用。不是可安装的临床产品，也不是完整运行时打包。

> 科研分析工具，不是医疗器械。技术 QC 通过不代表胎儿医学正常。

## 代码怎么走

从 [`agentic/workflow.py`](agentic/workflow.py) 读起：

```text
自然语言 / 界面表单
  -> coordinator.py     意图：算哪几步、看哪几步、报告写哪几步
  -> planner.py         按依赖补上游，生成任务 DAG
  -> schema / runtime 校验
  -> executor.py        调 pipeline/run_single_case_pipeline.sh
       extraction -> reconstruction -> registration
         -> tissue / ROI -> surface
  -> qc.py + 可视化
  -> reporter.py        Evidence Bank 与技术报告
```

三个入口调用同一套模块：

| 入口 | 命令 | 确认行为 |
| --- | --- | --- |
| 研究页（英文） | `python -m agentic.dashboard_server` | 先生成计划，再点 Run 才计算 |
| 医生工作台（中文） | `python -m agentic.dashboard_cn` 或下面的启动脚本 | 「提交分析任务」校验通过后直接开跑 |
| CLI | `python -m agentic.cli` | 生成计划后立刻按该模式执行；`plan_only` 不算影像 |

## 克隆之后实际能做什么

| 目标 | 克隆这条分支后 |
| --- | --- |
| 读 workflow、跑不碰影像的单元测试、`plan_only` | 可以（要 Python + nibabel/numpy，计划阶段建议有 LLM Key） |
| 打开 Dashboard 看界面、导入已有 run | 可以（仍要 LLM 配置；导入需要你自己的 run 目录） |
| 对一例 BTFE 跑完六步 | **不行**，权重、图谱、容器和 conda 环境不在 Git 里 |

缺的运行时包括：`*.pth` / `*.nii.gz` / `*.sif`、`pipeline/data/`、`.runtime/`，以及本机 ANTs、nnU-Net、FROST 环境。脚本里若仍出现 `/home/wangxiao` 等路径，那是原实验室默认值，必须改成你自己的。

## 环境

```bash
git clone -b framework https://github.com/LmeHW/AutoRecon.git
cd AutoRecon
pip install nibabel numpy
```

```bash
cp .env.example .env
# 按本机修改 AUTORECON_ANTS_DIR、AUTORECON_ROI_WARP_ENV、LLM 地址和模型名
# 不要把 API Key 写入 .env

mkdir -p .secrets
cp config/llm.secret.env.example .secrets/glm.env
chmod 600 .secrets/glm.env
# 只在 .secrets/glm.env 里填 AUTORECON_LLM_API_KEY
```

智谱 BigModel 可另用非密钥配置（不改 `.env`）：

```bash
cp config/glm.env.example config/glm.env
# config/*.env 已被 gitignore；按需改模型名和本机路径
```

## 启动

工作台和 CLI 都需要：**配置文件存在**，且 Secret 文件里导出了 `AUTORECON_LLM_API_KEY`。

中文医生工作台（默认 `127.0.0.1:8899`）：

```bash
AUTORECON_CONFIG_FILE=.env \
AUTORECON_SECRET_FILE=.secrets/glm.env \
  scripts/run_agentic_dashboard.sh --host 127.0.0.1 --port 8899
```

或：

```bash
python -m agentic.dashboard_cn --host 127.0.0.1 --port 8899
```

英文研究页（先计划、再确认执行）：

```bash
python -m agentic.dashboard_server --host 127.0.0.1 --port 8899
```

浏览器打开终端打印的地址。端口占用时会尝试后续端口；要固定端口加 `--strict-port`。不要把无认证 Dashboard 暴露到公网。

只用 GLM 配置启动：

```bash
AUTORECON_CONFIG_FILE=config/glm.env \
AUTORECON_SECRET_FILE=.secrets/glm.env \
  scripts/run_agentic_dashboard.sh --host 127.0.0.1 --port 8899
```

医生网关（多用户上传）是另一入口：`scripts/run_gateway.sh`。需要先 `cp config/service.env.example config/service.env`，不要把网关密码写进仓库。

## CLI

只生成计划，不跑 GPU：

```bash
python -m agentic.cli \
  "检查输入并规划三维重建" \
  --execution-mode plan_only \
  --subject-dir /data/input/subject_001
```

导入已有结果：

```bash
python -m agentic.cli \
  "导入已有结果，展示六步 QC 并生成中文研究报告" \
  --execution-mode import_existing \
  --existing-run-dir /path/to/existing/run
```

从原始数据执行（本机必须已具备 Pipeline 运行时）：

```bash
python -m agentic.cli \
  "完成重建、配准、组织分割、ROI 和表面生成" \
  --execution-mode run_pipeline \
  --subject-dir /data/input/subject_001 \
  --work-root /data/autorecon/runs/subject_001/run01 \
  --ga 31 \
  --atlas /path/to/31w.nii.gz \
  --reconstruction-tool frost \
  --roi-mode warp \
  --surface auto
```

直接调确定性层：

```bash
bash pipeline/run_single_case_pipeline.sh --help
```

目录约定见 [`pipeline/README.md`](pipeline/README.md)。

## 测试

不依赖 GPU 的快速检查：

```bash
python -m unittest tests.test_agentic.WorkflowTests tests.test_failure_catalog -v
```

全量 `python -m unittest discover -s tests -v` 会跑到需要影像、容器或本机路径的用例，新克隆上多数会失败，这是预期。

## 目录

```text
agentic/       意图、规划、执行、QC、报告、两个 Dashboard
pipeline/      确定性六步；权重和图谱不在本分支
service/       医生网关
scripts/       启动脚本
tests/         单元与契约测试
validation/    自然语言评测语料
containers/    Apptainer 定义；SIF 不入库
config/        非密钥配置示例
```

产物默认在 `agentic_runs/<run_id>/` 和 Pipeline 的 `<work_root>/`，均不提交。

## 完整仓库

论文笔记、组会材料和本机运行时在 `main`：https://github.com/LmeHW/AutoRecon/tree/main  
不要把 `framework` 合回 `main`。
