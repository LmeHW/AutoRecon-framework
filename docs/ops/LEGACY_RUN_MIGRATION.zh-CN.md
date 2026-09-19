# 历史病例 Run 迁移记录

迁移日期：2026-08-24

## 目的

将原本平铺在源码根目录的历史病例运行结果收拢到统一目录，避免源码、运行数据和汇报材料混杂。为降低风险，本次只调整 run 根目录，不修改病例内部 subject 名、NIfTI 文件名或 Pipeline 输出 contract。

## 目录映射

| 原目录 | 新目录 |
| --- | --- |
| `AnHuiJing_run01` | `runs/legacy/AnHuiJing/run01` |
| `AnHuiJing_run02` | `runs/legacy/AnHuiJing/run02` |
| `AnHuiJing_raw_run01` | `runs/legacy/AnHuiJing/raw_run01` |
| `AnHuiJing_full_demo_run01` | `runs/legacy/AnHuiJing/full_demo_run01` |
| `BaiHuPing_run01` | `runs/legacy/BaiHuPing/run01` |
| `CaiYuYu_raw_run01` | `runs/legacy/CaiYuYu/raw_run01` |
| `CaoLi_run01` | `runs/legacy/CaoLi/run01` |
| `CaoLi_registered_run02` | `runs/legacy/CaoLi/registered_run02` |

迁移使用同一文件系统内的目录 rename，没有复制或删除 MRI 数据。新目录整体由 `.gitignore` 排除。

## 路径兼容

迁移脚本会重写以下文本产物中的旧绝对路径：

- `dashboard/run_state.json` 和 `qc_summary.json`。
- Dashboard HTML、交互 Viewer 和日志。
- Evidence Bank、报告、任务计划和演示 manifest。
- CSV、TSV、stats 以及其他已知文本 provenance。

少量历史 `agentic_runs` 文件由其他系统用户创建，当前用户无写权限，无法原位修改。它们属于旧 Agent 汇总快照，不是本次迁移后的病例主状态；具体清单保存在机器可读 migration manifest 的 `skipped_rewrites` 字段。新调用应直接使用 `runs/legacy/...` 下的病例 run。

## 验证

迁移后执行了：

- 8 个 run 的 `dashboard/run_state.json` 解析。
- `work_root` 与新目录一致性检查。
- 每步绝对 artifact 路径存在性检查。
- canonical reconstruction 和 registered NIfTI 的 SHA-256 校验。
- 36 项自动化单元/契约测试。
- `scripts/verify_goal_deliverables.py` 完整演示交付验收。

上述检查全部通过。机器可读的精确文件清单、哈希和未改写只读文件见：

```text
runs/migrations/legacy-case-runs-*.json
```

## 后续调用

导入示例：

```bash
python -m agentic.cli \
  "导入已有结果并生成研究报告" \
  --execution-mode import_existing \
  --existing-run-dir /mnt/sda/huangwei/projects/AutoRecon/runs/legacy/AnHuiJing/run02
```

这些目录仅用于历史兼容和演示。新的正式任务应将 `work_root` 指向源码仓库外的受控数据目录。

## 迁移工具

默认只检查，不写入：

```bash
python scripts/migrate_legacy_case_runs.py
```

执行迁移：

```bash
python scripts/migrate_legacy_case_runs.py --execute
```

脚本可幂等续跑：若源目录已经不存在且目标目录存在，会把该 run 识别为已迁移状态。
