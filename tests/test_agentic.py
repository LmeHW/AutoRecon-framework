from __future__ import annotations

import io
import json
import os
import fcntl
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from agentic.coordinator import _dashboard_conflicts, coordinate, coordinate_with_llm
from agentic.env_config import LLMConfig, load_llm_config
from agentic.llm_client import LLMError, OpenAICompatibleClient
from agentic.models import PlanStep, TaskPlan, normalize_unfulfilled_requests
from agentic.planner import _plan_from_json, plan, plan_with_llm, validate_plan
from agentic.schema_validation import validate_agentic_objects
from agentic.qc import evaluate_run
import nibabel as nib
import numpy as np


def _minimal_zip() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("series/1.dcm", b"dicom-bytes")
    return buffer.getvalue()


def config(provider: str = "auto") -> LLMConfig:
    return LLMConfig(True, provider, "https://gateway.example/v1", "model", "top-secret", 1, 0, 0, 32,
                     True, True, True, True, True, True, False, True, "/ants", "/roi")


class Response:
    def __init__(self, data: dict):
        self.data = json.dumps(data).encode()
        self.headers = {}
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return self.data


class AgenticTests(unittest.TestCase):
    def test_import_always_uses_deterministic_plan(self):
        request = coordinate(
            "导入已有案例并展示完整 pipeline",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        result, event = plan_with_llm(request, object())
        self.assertEqual([step.id for step in result.steps], ["input_check", "visualization", "metrics"])
        self.assertEqual(event["reason"], "deterministic_import_plan")

    def test_reporting_import_state_is_not_recovered_as_pipeline(self):
        from agentic.dashboard_server import AgenticHandler
        state = {
            "status": "running",
            "plan": {"execution_mode": "import_existing"},
            "report_json": {"phase": "reporting"},
            "step_results": [{"step_id": "visualization", "status": "completed"}],
        }
        self.assertIs(AgenticHandler._recover_state_if_needed(None, state), state)

    def test_reporting_recovers_when_pipeline_already_finished(self):
        from agentic.dashboard_server import AgenticHandler
        from agentic.models import RunState

        with tempfile.TemporaryDirectory() as directory:
            dashboard_dir = Path(directory) / "dashboard"
            dashboard_dir.mkdir()
            dashboard_state = dashboard_dir / "run_state.json"
            dashboard_state.write_text(json.dumps({
                "run": {"status": "completed", "subject_name": "Upload_normal"},
                "steps": [{"id": "extraction", "status": "completed", "preview_relpath": "previews/01_extraction.png"}],
            }), encoding="utf-8")
            state = {
                "run_id": "run_report_hang",
                "status": "running",
                "request": {},
                "plan": {"execution_mode": "compute", "work_root": directory, "steps": []},
                "report_markdown": "# 报告生成中\n",
                "report_json": {"phase": "reporting"},
                "dashboard": {"dashboard_state": str(dashboard_state)},
                "step_results": [],
            }
            saved: list[dict] = []

            class FakeExecutor:
                def collect_pipeline_results(self, task_plan, run_id):
                    return (
                        [{"step_id": "extraction", "status": "completed"}],
                        {"dashboard_state": str(dashboard_state)},
                    )

            class FakeStore:
                def save(self, value):
                    data = value.to_dict() if isinstance(value, RunState) else dict(value)
                    saved.append(data)
                    return data

            handler = type("Handler", (), {"executor": FakeExecutor(), "store": FakeStore()})()
            with patch("agentic.dashboard_server.task_plan_from_dict", return_value=object()), patch(
                "agentic.dashboard_server.build_report",
                return_value=("# 已完成", {"medical_report": {"impression": "ok"}}),
            ):
                recovered = AgenticHandler._recover_state_if_needed(handler, state)
            self.assertEqual(recovered["status"], "completed")
            self.assertEqual(saved[0]["status"], "completed")
            self.assertNotEqual(recovered["report_json"].get("phase"), "reporting")

    def test_dashboard_conflicts_report_selected_values(self):
        conflicts = _dashboard_conflicts(
            {
                "subject_dir": "/data/CaiYuYu",
                "reconstruction_tool": "nesvor",
                "reconstruction_compare_tools": [],
                "gestational_age": 31,
                "surface": True,
            },
            {
                "subject_dir": "mnt/data/CaiYuYu ",
                "reconstruction_tool": "frost",
                "reconstruction_compare_tools": "all",
                "gestational_age": "31",
                "surface": "on",
            },
            {"subject_dir", "reconstruction_tool", "reconstruction_compare_tools", "gestational_age", "surface"},
        )
        self.assertEqual(
            [item["field"] for item in conflicts],
            ["subject_dir", "reconstruction_tool", "reconstruction_compare_tools"],
        )
        self.assertTrue(all(item["selected"] == "dashboard" for item in conflicts))

    def test_dashboard_conflicts_ignore_unmentioned_llm_defaults(self):
        conflicts = _dashboard_conflicts(
            {"surface": "off", "reconstruction_compare_tools": []},
            {"surface": "on", "reconstruction_compare_tools": "all"},
            {"surface", "reconstruction_compare_tools"},
            "导入已有案例，运行完整 pipeline 并展示所有步骤和日志",
        )
        self.assertEqual(conflicts, [])

    def test_pipeline_rejects_concurrent_writer_for_same_work_root(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            subject = temporary / "CaseA"
            subject.mkdir()
            (subject / "BTFE_01.nii.gz").touch()
            work = temporary / "run"
            work.mkdir()
            with (work / ".pipeline.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                completed = subprocess.run([
                    "bash", str(root / "pipeline/run_single_case_pipeline.sh"),
                    "--subject-dir", str(subject), "--work-root", str(work),
                    "--steps", "reconstruction", "--dashboard", "off", "--surface", "off",
                ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 75)
            self.assertIn("already using work root", completed.stderr)

    def test_protocol_auto_falls_back_to_anthropic(self):
        calls = []
        def fake(request, timeout=0):
            calls.append(request.full_url)
            if request.full_url.endswith("chat/completions"):
                raise HTTPError(request.full_url, 404, "missing", {}, io.BytesIO())
            return Response({"content": [{"type": "text", "text": '{"ok":true}'}]})
        client = OpenAICompatibleClient(config())
        with patch("agentic.llm_client.urlopen", fake):
            self.assertEqual(client.complete_json("system", "user"), {"ok": True})
        self.assertEqual(client.active_provider, "anthropic")
        self.assertEqual(len(calls), 2)

    def test_glm_uses_v4_chat_completions_endpoint(self):
        calls = []
        glm = config("openai_compatible")
        glm = LLMConfig(**{**glm.__dict__, "base_url": "https://open.bigmodel.cn/api/paas/v4"})

        def fake(request, timeout=0):
            calls.append(request.full_url)
            return Response({"choices": [{"message": {"content": "ok"}}]})

        with patch("agentic.llm_client.urlopen", fake):
            self.assertEqual(OpenAICompatibleClient(glm).complete("system", "user"), "ok")
        self.assertEqual(calls, ["https://open.bigmodel.cn/api/paas/v4/chat/completions"])

    def test_llm_retries_rebuild_post_request(self):
        methods = []
        glm = LLMConfig(**{**config("openai_compatible").__dict__, "max_retries": 2})
        self.assertEqual(glm.max_retries, 2)

        def fake(request, timeout=0):
            methods.append(request.get_method())
            if len(methods) == 1:
                return Response({"error": {"message": "Request method 'GET' not supported", "code": "500"}})
            return Response({"choices": [{"message": {"content": "ok"}}]})

        with patch("agentic.llm_client.urlopen", fake):
            self.assertEqual(OpenAICompatibleClient(glm).complete("system", "user"), "ok")
        self.assertEqual(methods, ["POST", "POST"])

    def test_alternate_config_does_not_modify_default_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("AUTORECON_LLM_MODEL=existing-model\n", encoding="utf-8")
            (root / "glm.env").write_text("AUTORECON_LLM_MODEL=glm-test\n", encoding="utf-8")
            with patch.dict(os.environ, {"AUTORECON_CONFIG_FILE": "glm.env"}, clear=False):
                self.assertEqual(load_llm_config(root).model, "glm-test")
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "AUTORECON_LLM_MODEL=existing-model\n")

    def test_selected_config_file_beats_ambient_llm_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "glm.env").write_text(
                "AUTORECON_LLM_ENABLED=true\n"
                "AUTORECON_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4\n"
                "AUTORECON_LLM_MODEL=glm-5.3-flash\n"
                "AUTORECON_LLM_MAX_RETRIES=4\n",
                encoding="utf-8",
            )
            ambient = {
                "AUTORECON_CONFIG_FILE": "glm.env",
                "AUTORECON_LLM_BASE_URL": "https://api.claudecode.net.cn/api/claudecode",
                "AUTORECON_LLM_MODEL": "anthropic/claude-sonnet-4-6",
                "AUTORECON_LLM_MAX_RETRIES": "2",
            }
            with patch.dict(os.environ, ambient, clear=False):
                loaded = load_llm_config(root)
            self.assertEqual(loaded.model, "glm-5.3-flash")
            self.assertEqual(loaded.base_url, "https://open.bigmodel.cn/api/paas/v4")
            self.assertEqual(loaded.max_retries, 4)

    def test_secret_is_redacted(self):
        public = config().public_dict()
        self.assertNotIn("api_key", public)
        self.assertNotIn("top-secret", json.dumps(public))

    def test_scopes_are_independent(self):
        request = coordinate("Import existing_run_dir=/tmp/demo; only show reconstruction; complete report")
        self.assertEqual(request.display_steps, ["reconstruction"])
        self.assertEqual(request.report_steps, [])
        self.assertEqual(request.execution_steps, [])
        self.assertEqual(validate_plan(plan(request)), [])

    def test_only_display_does_not_limit_complete_report(self):
        request = coordinate(
            "导入已有 run，只展示 reconstruction，但用全部可用证据生成完整中文报告。",
            {"execution_mode": "import_existing", "existing_run_dir": "/tmp/example"},
        )
        self.assertEqual(request.display_steps, ["reconstruction"])
        self.assertEqual(request.report_steps, [])

    def test_dashboard_split_columns_can_shrink_evenly(self):
        from agentic.dashboard_server import INDEX_HTML

        self.assertIn("grid-template-columns:minmax(0,1fr) minmax(0,1fr)", INDEX_HTML)
        self.assertIn(".split>div{min-width:0}", INDEX_HTML)

    def test_dashboard_defaults_point_to_existing_local_inputs(self):
        from agentic.dashboard_server import INDEX_HTML

        root = Path(__file__).resolve().parents[1]
        self.assertIn(f'value="{root / "backend_validation/input/AnHuiJing"}"', INDEX_HTML)
        self.assertIn(f'value="{root / "pipeline/data/FBA_Chinese_Atlas/img/31w.nii.gz"}"', INDEX_HTML)
        self.assertIn(f'value="{root / "runs/legacy/CaiYuYu/raw_run01"}"', INDEX_HTML)
        self.assertIn('<option value="run_pipeline" selected>', INDEX_HTML)

    def test_dashboard_plan_status_distinguishes_llm_and_fallback(self):
        from agentic.dashboard_server import INDEX_HTML

        self.assertIn('state.plan?.planner_source==="llm"&&planning.used', INDEX_HTML)
        self.assertIn('planning.status==="fallback"', INDEX_HTML)
        self.assertIn('planning.reason==="deterministic_import_plan"', INDEX_HTML)

    def test_chinese_dashboard_is_a_clinician_product_page(self):
        from agentic.dashboard_cn import _translated_html

        html = _translated_html()
        self.assertIn("ShanghaiTech · SmileLab", html)
        self.assertIn("/brand/smilelab.svg", html)
        self.assertIn("linear-gradient", html)
        self.assertIn("结果中心", html)
        self.assertIn("新建影像分析", html)
        self.assertIn("从已有结果继续", html)
        self.assertIn("上传新影像", html)
        self.assertIn("source-choice", html)
        self.assertIn('id="continue_result_id"', html)
        self.assertIn("continue_from_run", html)
        self.assertIn("/brand/results-center.png", html)
        self.assertIn("/brand/new-analysis.png", html)
        self.assertEqual(html.count('data-module='), 2)
        self.assertNotIn('<span class="module-icon">', html)
        self.assertNotIn("不启动计算任务", html)
        self.assertNotIn("本次处理结果与待审事项", html)
        self.assertNotIn("按处理阶段浏览影像、交互视图与步骤日志", html)
        self.assertIn("病例记录", html)
        self.assertNotIn('id="caseRecordPanel"', html)
        self.assertNotIn('id="intake_result_id"', html)
        self.assertIn('id="caseIntake"', html)
        self.assertIn("/api/clinic-intake", html)
        self.assertIn("function saveIntake", html)
        self.assertNotIn("看过上面的流程影像后再填写", html)
        self.assertLess(html.find('id="gallery"'), html.find('id="caseIntake"'))
        self.assertIn('id="result_id"', html)
        self.assertIn('id="renameResultBtn"', html)
        self.assertIn('id="renameDialog"', html)
        self.assertIn(">改名<", html)
        self.assertIn('$("renameDialog").showModal()', html)
        self.assertNotIn("resultSelectWrap", html)
        self.assertNotIn("resultRenameWrap", html)
        self.assertIn("/api/results", html)
        self.assertIn("/api/clinic-upload", html)
        self.assertIn("提交分析任务", html)
        self.assertIn("选择文件、文件夹，或拖放至此", html)
        self.assertIn("选择文件夹", html)
        self.assertIn("webkitdirectory", html)
        self.assertIn("function isIrrelevantUpload", html)
        self.assertIn("function filesFromDataTransfer", html)
        self.assertIn("upload-scroll", html)
        self.assertNotIn("不再逐条列出", html)
        self.assertIn("正在把 DICOM 转为 NIfTI", html)
        self.assertIn("function isZipName", html)
        self.assertNotIn("请上传 BTFE_*.nii.gz，或一个 DICOM 的 .zip。", html)
        self.assertNotIn("一次最多上传 20 个文件。", html)
        self.assertIn("病例名称", html)
        self.assertIn("function renderUploadList", html)
        self.assertIn("function discardUpload", html)
        self.assertIn("可再选一批", html)
        self.assertIn("selectedFiles.push(file)", html)
        self.assertIn("/api/clinic-upload/${uploadedCaseId}/rename", html)
        self.assertIn("完成全部六步（脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建）", html)
        self.assertIn("/api/analyze", html)
        self.assertIn("localStorage", html)
        self.assertIn("history.replaceState", html)
        self.assertIn("restoreClinicSession", html)
        self.assertIn("persistClinicView", html)
        self.assertIn("clinic.ui", html)
        self.assertIn("lastGallerySignature", html)
        self.assertIn("function progressLine", html)
        self.assertIn('parts=["处理中"', html)
        self.assertIn('parts.join(" · ")', html)
        self.assertIn("未完成 ·", html)
        self.assertIn("已完成", html)
        self.assertIn("分析已完成", html)
        self.assertIn("正在生成报告", html)
        self.assertIn("function putUploadChunk", html)
        self.assertIn("XMLHttpRequest", html)
        refresh_fn = html.split("async function refresh", 1)[1].split("function formatSize", 1)[0]
        self.assertIn("await loadResults(runId)", refresh_fn)
        self.assertIn('id="viewerDialog"', html)
        self.assertNotIn("任务计划", html)
        self.assertNotIn("planBox", html)
        self.assertNotIn('id="case_id"', html)
        self.assertNotIn("已有病例", html)
        self.assertNotIn('id="work_root"', html)
        self.assertNotIn("工作根目录", html)
        self.assertNotIn('id="execution_mode"', html)
        self.assertIn('id="gestational_age"', html)
        self.assertIn("胎龄（周）", html)
        self.assertIn("胎儿描述", html)
        self.assertIn('id="clinical_notes"', html)
        self.assertIn("重建伪影明显", html)
        self.assertIn("default_middle", html)
        self.assertIn("临床所见", html)
        self.assertNotIn("是否有病", html)
        self.assertIn("存在异常", html)
        self.assertIn('<span>临床所见</span>', html)
        self.assertIn('<div class="field">', html)
        self.assertIn('name="clinical_status"', html)
        self.assertIn('id="conditionField"', html)
        self.assertIn("[hidden]{display:none!important}", html)
        self.assertIn("function syncConditionField", html)
        self.assertIn('wrap.hidden=status!=="present"&&status!=="unknown"', html)
        self.assertIn("function readIntake", html)
        self.assertIn("请填写胎龄", html)
        payload_fn = html.split("async function payload", 1)[1].split("function statusBadge", 1)[0]
        self.assertNotIn("readIntake", payload_fn)
        self.assertNotIn("attachIntake", payload_fn)
        self.assertIn("dev-only", html)
        open_existing = html.split("async function openExistingResult", 1)[1].split("async function boot", 1)[0]
        self.assertIn("refresh(runId)", open_existing)
        self.assertNotIn("/api/analyze", open_existing)
        self.assertNotIn("查看分析结果", html)
        self.assertNotIn("openResultBtn", html)
        gallery_renderer = html.split("function gallerySteps", 1)[1].split("function openViewer", 1)[0]
        self.assertIn("thumbnail", gallery_renderer)
        self.assertIn("statusBadge(step.status)", gallery_renderer)
        self.assertNotIn("background:#111", html.split(".thumbnail img", 1)[1][:120])
        self.assertIn("height:auto", html.split(".thumbnail img", 1)[1][:120])
        self.assertNotIn("object-fit:contain", html.split(".thumbnail img", 1)[1][:80])
        self.assertIn("pickInteractiveViewer(step)", gallery_renderer)
        self.assertIn("查看日志", gallery_renderer)
        self.assertIn("/api/log-tail", html)
        self.assertIn("function stickLogToBottom(", html)
        self.assertIn("loadOpenLog(true)", html)
        self.assertIn("view.scrollTop=view.scrollHeight", html)
        self.assertIn("data-log", gallery_renderer)
        self.assertNotIn("<iframe", gallery_renderer)
        self.assertIn('step.status!=="skipped"', gallery_renderer)
        self.assertIn('step.status!=="pending"', gallery_renderer)
        self.assertIn("未执行内容见报告", gallery_renderer)
        picker = html.split("function pickInteractiveViewer", 1)[1].split("function gallerySteps", 1)[0]
        self.assertIn("_interactive", picker)
        self.assertIn(".html", picker)
        self.assertIn("交互", picker)
        self.assertIn("callout checklist", html)
        self.assertIn("待审清单", html)
        self.assertIn("refusal-heading", html)
        module_switch = html.split("async function selectModule", 1)[1].split('const dropzone=', 1)[0]
        self.assertIn("clearDisplayedResult()", module_switch)
        self.assertIn("latestRunId||$(\"result_id\").value", module_switch)
        self.assertIn("await refresh(runId)", module_switch)
        self.assertNotIn("else if(latestRunId)await selectModule", html)
        restore_fn = html.split("async function restoreClinicSession", 1)[1].split("async function api", 1)[0]
        self.assertIn('if(!latestRunId&&(runs||[]).length) latestRunId=runs[0].run_id', restore_fn)
        self.assertIn('else await selectModule("resultsPanel")', restore_fn)
        fill_fn = html.split("function fillResultSelect", 1)[1].split("async function loadResults", 1)[0]
        self.assertIn("runs[0]&&runs[0].run_id", fill_fn)
        self.assertIn("previewContinueResult()", module_switch)
        self.assertNotIn("caseRecordPanel", module_switch)
        self.assertIn("applyIntakeFromState", html)
        source_switch = html.split("function selectAnalysisSource", 1)[1].split("async function boot", 1)[0]
        self.assertIn('source==="continue"', source_switch)
        self.assertIn("uploadSource", source_switch)
        self.assertIn("continueSource", source_switch)
        self.assertIn("六步顺序：脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建。", source_switch)
        analyze_fn = html.split("async function analyze", 1)[1].split("function resultLabel", 1)[0]
        self.assertIn("continue_from_run", html.split("async function payload", 1)[1].split("function statusBadge", 1)[0])
        self.assertIn("run_pipeline", html.split("async function payload", 1)[1].split("function statusBadge", 1)[0])
        self.assertNotIn("await uploadFiles()", analyze_fn.split('if(analysisSource==="upload")', 1)[0])

    def test_result_picker_does_not_keep_another_case_report(self):
        from agentic.dashboard_cn import _translated_html

        html = _translated_html()
        self.assertIn("function onResultPickerChange()", html)
        self.assertIn('$("result_id").addEventListener("change"', html)
        self.assertIn("function showMissingResult(", html)
        self.assertIn("function bindOpenedRun(", html)
        picker = html.split("async function onResultPickerChange()", 1)[1].split("async function openExistingResult", 1)[0]
        self.assertIn("await openExistingResult()", picker)
        self.assertNotIn("查看分析结果", picker)
        open_existing = html.split("async function openExistingResult", 1)[1].split("async function previewContinueResult", 1)[0]
        self.assertIn("showMissingResult(\"当前没有可打开的分析结果。\")", open_existing)
        self.assertIn("正在打开已有结果", open_existing)
        refresh_fn = html.split("async function refresh", 1)[1].split("function formatSize", 1)[0]
        self.assertIn("if(!s.run_id)", refresh_fn)
        self.assertIn("该分析记录还没有可查看的报告。", refresh_fn)
        self.assertIn("openedRunId!==runId", refresh_fn)
        self.assertIn("function withPreservedScroll(", html)
        self.assertIn("function showReportPlaceholder(", html)
        self.assertIn("showReportPlaceholder(empty)", refresh_fn)
        self.assertIn("withPreservedScroll", refresh_fn)
        self.assertNotIn("renderIdleWorkspace(", refresh_fn)
        self.assertNotIn("step.message", refresh_fn)
        self.assertIn("window.scrollTo(0,y)", html)

    def test_default_result_catalog_includes_curated_cases_without_duplicates(self):
        from agentic.state_store import StateStore

        root = Path(__file__).resolve().parents[1]
        rows = StateStore(root / "agentic_runs").list_runs()
        curated = [row for row in rows if row.get("source") == "validated"]
        self.assertEqual([row["case_id"] for row in curated], ["I01", "I02", "N01", "N02", "N03", "N04", "C01"])
        subjects = [row["subject"].strip().casefold() for row in rows]
        self.assertEqual(len(subjects), len(set(subjects)))
        self.assertNotIn("未命名病例", {row["subject"] for row in rows})

    def test_list_runs_includes_failed_and_subjectless_plan_only(self):
        from agentic.state_store import StateStore

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            store.save({
                "run_id": "E18_run", "status": "failed",
                "request": {"raw_text": "完整处理这个病例。", "subject_dir": "/data/ShiYuQing"},
                "plan": {"goal": "interrupt"},
                "report_markdown": "中断后的技术报告",
            })
            store.save({
                "run_id": "E20_run", "status": "completed",
                "request": {"raw_text": "帮我处理一下这个。", "subject_dir": None},
                "plan": {"goal": "plan_only"},
                "report_markdown": "缺少输入",
            })
            rows = {row["run_id"]: row for row in store.list_runs()}
            self.assertIn("E18_run", rows)
            self.assertEqual(rows["E18_run"]["subject"], "ShiYuQing")
            self.assertIn("E20_run", rows)
            self.assertEqual(rows["E20_run"]["subject"], "E20_run")

    def test_list_runs_collapses_same_case_imported_twice(self):
        from agentic.state_store import StateStore

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            work = str(Path(directory) / "work" / "WangTingYan_HASTE" / "run1")
            Path(work).mkdir(parents=True)
            store.save({
                "run_id": "older_haste",
                "status": "completed",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "WangTingYan_HASTE"),
                    "work_root": work,
                    "case_label": "WangTingYan(MR00217253)",
                },
                "plan": {"goal": "first import"},
                "report_markdown": "old",
            })
            store.save({
                "run_id": "newer_full",
                "status": "completed",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "WangTingYan_MR00217253"),
                    "work_root": work,
                    "case_label": "WangTingYan(MR00217253)",
                },
                "plan": {"goal": "official import"},
                "report_markdown": "new",
            })
            newer_state = store.run_dir("newer_full") / "agentic_state.json"
            older_mtime = (store.run_dir("older_haste") / "agentic_state.json").stat().st_mtime
            os.utime(newer_state, (older_mtime + 2, older_mtime + 2))
            rows = store.list_runs()
            self.assertEqual([row["run_id"] for row in rows], ["newer_full"])
            store.save({
                "run_id": "other_patient",
                "status": "completed",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "CaoLi"),
                    "work_root": str(Path(directory) / "work" / "CaoLi" / "run1"),
                    "case_label": "CaoLi",
                },
                "plan": {"goal": "another case"},
                "report_markdown": "other",
            })
            ids = {row["run_id"] for row in store.list_runs()}
            self.assertEqual(ids, {"newer_full", "other_patient"})

    def test_list_runs_prefers_newer_success_over_failed_mtime(self):
        from agentic.state_store import StateStore

        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            work = str(Path(directory) / "work" / "Upload_normal" / "20260921T103152Z")
            Path(work).mkdir(parents=True)
            store.save({
                "run_id": "2026-09-21T104248Z0000_success",
                "status": "running",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "Upload_normal"),
                    "work_root": work,
                    "case_label": "正常胎儿",
                },
                "plan": {"goal": "full llm"},
                "report_markdown": "placeholder",
            })
            store.save({
                "run_id": "2026-09-21T045902Z0000_failed",
                "status": "failed",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "Upload_normal"),
                    "work_root": str(Path(directory) / "work" / "Upload_normal" / "older"),
                    "case_label": "正常胎儿",
                },
                "plan": {"goal": "continue"},
                "report_markdown": "fail",
            })
            failed_state = store.run_dir("2026-09-21T045902Z0000_failed") / "agentic_state.json"
            success_state = store.run_dir("2026-09-21T104248Z0000_success") / "agentic_state.json"
            older = success_state.stat().st_mtime
            os.utime(failed_state, (older + 10, older + 10))
            rows = store.list_runs()
            self.assertEqual([row["run_id"] for row in rows], ["2026-09-21T104248Z0000_success"])
            store.save({
                "run_id": "2026-09-21T104248Z0000_success",
                "status": "completed",
                "request": {
                    "subject_dir": str(Path(directory) / "uploads" / "Upload_normal"),
                    "work_root": work,
                    "case_label": "正常胎儿",
                },
                "plan": {"goal": "full llm"},
                "report_markdown": "done",
            })
            self.assertEqual([row["run_id"] for row in store.list_runs()], ["2026-09-21T104248Z0000_success"])

    def test_enriched_dashboard_restores_existing_visualization_metadata(self):
        from agentic.dashboard_server import load_enriched_dashboard_state

        with tempfile.TemporaryDirectory() as directory:
            dashboard = Path(directory)
            previews = dashboard / "previews"
            previews.mkdir()
            (previews / "01_extraction.png").write_bytes(b"png")
            (previews / "01_extraction_interactive.html").write_text("<html></html>", encoding="utf-8")
            state = dashboard / "run_state.json"
            state.write_text(json.dumps({
                "run": {"work_root": str(dashboard.parent)},
                "steps": [{"id": "extraction", "status": "completed", "preview_relpath": None, "artifacts": []}],
            }), encoding="utf-8")
            enriched = load_enriched_dashboard_state(state)
            step = enriched["steps"][0]
            self.assertEqual(step["preview_relpath"], "previews/01_extraction.png")
            self.assertTrue(any(item["path"].endswith("01_extraction_interactive.html") for item in step["artifacts"]))

    def test_curated_cases_expose_all_existing_standard_previews(self):
        from agentic.dashboard_server import load_enriched_dashboard_state
        from agentic.state_store import StateStore

        root = Path(__file__).resolve().parents[1]
        store = StateStore(root / "agentic_runs")
        expected = {"I01": 5, "I02": 6, "N01": 2, "N02": 3, "N03": 6, "N04": 6, "C01": 3}
        for row in (item for item in store.list_runs() if item.get("source") == "validated"):
            state = store.load(row["run_id"])
            dashboard = load_enriched_dashboard_state(Path(state["dashboard"]["dashboard_state"]))
            visible = [step for step in dashboard["steps"] if step.get("preview_relpath")]
            self.assertEqual(len(visible), expected[row["case_id"]], row["case_id"])
            dashboard_dir = Path(state["dashboard"]["dashboard_dir"])
            for step in visible:
                viewer = dashboard_dir / str(step["preview_relpath"]).replace(".png", "_interactive.html")
                if not viewer.is_file():
                    continue
                self.assertTrue(
                    any(str(item.get("path") or "").endswith(viewer.name) for item in step.get("artifacts") or []),
                    f"{row['case_id']} {step['id']} missing interactive artifact",
                )

    def test_clinic_upload_endpoint_accepts_btfe_stack(self):
        import gzip
        import urllib.request
        from scripts.run_case_acceptance import start_doctor_dashboard

        with tempfile.TemporaryDirectory() as directory:
            upload_dir = Path(directory) / "uploads"
            with patch("agentic.dashboard_server.upload_root", return_value=upload_dir):
                server, base = start_doctor_dashboard(Path(directory) / "runs")
                try:
                    payload = gzip.compress(b"nifti-placeholder")
                    init_request = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({"files": [{"name": "BTFE_01.nii.gz", "size": len(payload)}]}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    init = json.loads(urllib.request.urlopen(init_request, timeout=5).read())
                    chunk_request = urllib.request.Request(
                        f"{base}/api/clinic-upload/{init['case_id']}/0?offset=0",
                        data=payload,
                        headers={"Content-Type": "application/octet-stream"},
                        method="PUT",
                    )
                    self.assertTrue(json.loads(urllib.request.urlopen(chunk_request, timeout=5).read())["ok"])
                    complete_request = urllib.request.Request(
                        f"{base}/api/clinic-upload/{init['case_id']}/complete",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    complete = json.loads(urllib.request.urlopen(complete_request, timeout=5).read())
                    self.assertEqual(complete["case"]["stack_count"], "1")
                    self.assertTrue((upload_dir / init["case_id"] / "BTFE_01.nii.gz").is_file())
                    rename_request = urllib.request.Request(
                        f"{base}/api/clinic-upload/{init['case_id']}/rename",
                        data=json.dumps({"label": "AnHuiJing"}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    renamed = json.loads(urllib.request.urlopen(rename_request, timeout=5).read())
                    self.assertEqual(renamed["case"]["label"], "AnHuiJing")
                    named = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({
                            "files": [{"name": "BTFE_02.nii.gz", "size": len(payload)}],
                            "label": "CaseDemo",
                        }).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    named_init = json.loads(urllib.request.urlopen(named, timeout=5).read())
                    self.assertEqual(named_init["case_id"], "CaseDemo")
                    self.assertEqual(named_init["label"], "CaseDemo")
                    zip_payload = _minimal_zip()
                    zip_init_req = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({"files": [{"name": "dicom.zip", "size": len(zip_payload)}]}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    zip_init = json.loads(urllib.request.urlopen(zip_init_req, timeout=5).read())
                    zip_chunk = urllib.request.Request(
                        f"{base}/api/clinic-upload/{zip_init['case_id']}/0?offset=0",
                        data=zip_payload,
                        headers={"Content-Type": "application/octet-stream"},
                        method="PUT",
                    )
                    self.assertTrue(json.loads(urllib.request.urlopen(zip_chunk, timeout=5).read())["ok"])

                    def fake_convert(archive, directory, **_kwargs):
                        import gzip as gzip_mod
                        (directory / "BTFE_01.nii.gz").write_bytes(gzip_mod.compress(b"stack-one"))
                        (directory / "BTFE_02.nii.gz").write_bytes(gzip_mod.compress(b"stack-two"))
                        return {
                            "ok": True,
                            "btfe": ["BTFE_01.nii.gz", "BTFE_02.nii.gz"],
                            "series": [
                                {"name": "BTFE_01.nii.gz", "series_number": 201, "description": "BTFE"},
                                {"name": "BTFE_02.nii.gz", "series_number": 301, "description": "BTFE"},
                            ],
                            "dropped": ["SURVEY_BFFE（序列 101）"],
                        }

                    with patch("agentic.dashboard_server.convert_dicom_zip", side_effect=fake_convert):
                        zip_complete_req = urllib.request.Request(
                            f"{base}/api/clinic-upload/{zip_init['case_id']}/complete",
                            data=b"{}",
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        zip_complete = json.loads(urllib.request.urlopen(zip_complete_req, timeout=5).read())
                    self.assertEqual(zip_complete["case"]["stack_count"], "2")
                    case_dir = upload_dir / zip_init["case_id"]
                    self.assertTrue((case_dir / "BTFE_01.nii.gz").is_file())
                    self.assertTrue((case_dir / "BTFE_02.nii.gz").is_file())
                    self.assertFalse((case_dir / "dicom.zip").exists())

                    chinese = gzip.compress(b"unicode-nifti")
                    chinese_init_req = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({"files": [{"name": "张三 扫描.nii.gz", "size": len(chinese)}]}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    chinese_init = json.loads(urllib.request.urlopen(chinese_init_req, timeout=5).read())
                    chinese_chunk = urllib.request.Request(
                        f"{base}/api/clinic-upload/{chinese_init['case_id']}/0?offset=0",
                        data=chinese,
                        headers={"Content-Type": "application/octet-stream"},
                        method="PUT",
                    )
                    self.assertTrue(json.loads(urllib.request.urlopen(chinese_chunk, timeout=5).read())["ok"])
                    chinese_complete = json.loads(urllib.request.urlopen(urllib.request.Request(
                        f"{base}/api/clinic-upload/{chinese_init['case_id']}/complete",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    ), timeout=5).read())
                    self.assertEqual(chinese_complete["case"]["stack_count"], "1")
                    self.assertTrue((upload_dir / chinese_init["case_id"] / "stack_01.nii.gz").is_file())

                    nested = b"dicom-bytes"
                    nested_init_req = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({
                            "files": [
                                {"name": "Study/201/1.dcm", "size": len(nested)},
                                {"name": "Study/IM_0001", "size": len(nested)},
                            ]
                        }).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    nested_init = json.loads(urllib.request.urlopen(nested_init_req, timeout=5).read())
                    for index in (0, 1):
                        nested_chunk = urllib.request.Request(
                            f"{base}/api/clinic-upload/{nested_init['case_id']}/{index}?offset=0",
                            data=nested,
                            headers={"Content-Type": "application/octet-stream"},
                            method="PUT",
                        )
                        self.assertTrue(json.loads(urllib.request.urlopen(nested_chunk, timeout=5).read())["ok"])
                    self.assertTrue((upload_dir / nested_init["case_id"] / "Study" / "201" / "1.dcm").is_file())

                    junk_req = urllib.request.Request(
                        base + "/api/clinic-upload",
                        data=json.dumps({"files": [{"name": "Case/201_JPG/1.jpg", "size": 12}]}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as junk_ctx:
                        urllib.request.urlopen(junk_req, timeout=5)
                    self.assertEqual(junk_ctx.exception.code, 400)

                    def fake_dir_convert(source, directory, **_kwargs):
                        import gzip as gzip_mod
                        (directory / "BTFE_01.nii.gz").write_bytes(gzip_mod.compress(b"from-folder"))
                        return {"ok": True, "btfe": ["BTFE_01.nii.gz"], "series": [], "dropped": []}

                    with patch("agentic.dashboard_server.convert_dicom_dir", side_effect=fake_dir_convert):
                        nested_complete = json.loads(urllib.request.urlopen(urllib.request.Request(
                            f"{base}/api/clinic-upload/{nested_init['case_id']}/complete",
                            data=b"{}",
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        ), timeout=5).read())
                    self.assertEqual(nested_complete["case"]["stack_count"], "1")
                    self.assertTrue((upload_dir / nested_init["case_id"] / "BTFE_01.nii.gz").is_file())
                    self.assertFalse((upload_dir / nested_init["case_id"] / "Study" / "201" / "1.dcm").exists())
                finally:
                    server.shutdown()
                    server.server_close()

    def test_dashboard_automatically_uses_next_available_port(self):
        import errno
        from http.server import BaseHTTPRequestHandler
        from agentic.dashboard_server import _bind_server

        available_server = object()
        with patch(
            "agentic.dashboard_server.ThreadingHTTPServer",
            side_effect=[OSError(errno.EADDRINUSE, "occupied"), available_server],
        ) as server_cls:
            server = _bind_server(
                "127.0.0.1", 8901, BaseHTTPRequestHandler, auto_port=True
            )
        self.assertIs(server, available_server)
        self.assertEqual(server_cls.call_args_list[0].args[:1], (("127.0.0.1", 8901),))
        self.assertEqual(server_cls.call_args_list[1].args[:1], (("127.0.0.1", 8902),))

    def test_dashboard_strict_port_still_fails_when_occupied(self):
        import errno
        from http.server import BaseHTTPRequestHandler
        from agentic.dashboard_server import _bind_server

        with patch(
            "agentic.dashboard_server.ThreadingHTTPServer",
            side_effect=OSError(errno.EADDRINUSE, "occupied"),
        ) as server_cls:
            with self.assertRaises(OSError):
                _bind_server(
                    "127.0.0.1",
                    8901,
                    BaseHTTPRequestHandler,
                    auto_port=False,
                )
        server_cls.assert_called_once()

    def test_dynamic_dependency_closure(self):
        request = coordinate("Run surface", {"execution_mode": "run_pipeline", "subject_dir": "/tmp", "work_root": "/tmp/w", "atlas": "/tmp/a", "gestational_age": 28})
        result = plan(request)
        self.assertEqual(request.execution_steps, ["surface"])
        self.assertEqual(result.execution_steps, ["surface"])
        self.assertEqual(
            [step.id for step in result.steps],
            ["input_check", "extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )

    def test_import_reanalyze_ignores_paraphrased_fresh_run_goal(self):
        request = coordinate(
            "再分析一次。",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        request.intent = "无法确定要重跑的具体管线与范围。"
        self.assertFalse(request.resume)
        task_plan = plan(request)
        self.assertEqual(task_plan.raw_text, "再分析一次。")
        self.assertIn("重跑", task_plan.goal)
        self.assertEqual(validate_plan(task_plan), [])

    def test_import_scratch_phrase_still_conflicts(self):
        request = coordinate(
            "从原始BTFE完整重跑。",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        self.assertEqual(request.execution_mode, "import_existing")
        errors = validate_plan(plan(request))
        self.assertTrue(any("Fresh-run request conflicts" in item for item in errors))

    def test_plan_does_not_expand_continue_request_steps(self):
        request = coordinate(
            "配准我看不准，就在原目录把配准重跑一遍，前面提取和重建别动。",
            {
                "execution_mode": "continue_from_run",
                "existing_run_dir": "/tmp/run",
                "work_root": "/tmp/run",
                "subject_dir": "/tmp/subject",
                "atlas": "/tmp/35w.nii.gz",
                "gestational_age": 35,
                "execution_steps": ["registration", "tissue", "roi", "surface"],
                "explicit_fields": [
                    "execution_mode", "existing_run_dir", "work_root", "subject_dir",
                    "atlas", "gestational_age", "execution_steps",
                ],
            },
        )
        result = plan(request)
        self.assertEqual(request.execution_steps, ["registration", "tissue", "roi", "surface"])
        self.assertEqual(result.execution_steps, ["registration", "tissue", "roi", "surface"])
        self.assertEqual(
            [step.id for step in result.steps],
            ["input_check", "extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )

    def test_keep_existing_clause_is_not_an_execution_step(self):
        request = coordinate(
            "配准我看不准，就在原目录把配准重跑一遍，前面提取和重建别动。",
            {
                "execution_mode": "continue_from_run",
                "existing_run_dir": "/tmp/run",
                "work_root": "/tmp/run",
                "subject_dir": "/tmp/subject",
                "atlas": "/tmp/35w.nii.gz",
                "gestational_age": 35,
                "explicit_fields": [
                    "execution_mode", "existing_run_dir", "work_root",
                    "subject_dir", "atlas", "gestational_age",
                ],
            },
        )
        self.assertEqual(request.execution_steps, ["registration"])
        self.assertNotIn("extraction", request.execution_steps)
        self.assertNotIn("reconstruction", request.execution_steps)

    def test_empty_full_pipeline_request_defaults_to_all_six_steps(self):
        request = coordinate(
            "",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "gestational_age": 31,
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age"],
            },
        )
        self.assertEqual(
            request.execution_steps,
            ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )

    def test_llm_keeps_narrow_execution_steps_when_form_omits_scope(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}

        request, event = coordinate_with_llm(
            "",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "gestational_age": 31,
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction"])

    def test_llm_execution_steps_not_overwritten_by_step_aliases(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}

        request, event = coordinate_with_llm(
            "从原始数据跑完整流程，只要重建。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction"])

    def test_llm_display_and_report_steps_not_overwritten_by_keywords(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "run_pipeline",
                    "execution_steps": ["extraction"],
                    "display_steps": ["extraction"],
                    "report_steps": ["extraction"],
                }

        request, event = coordinate_with_llm(
            "只做 extraction。显示 reconstruction 结果，报告里写 surface。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction"])
        self.assertEqual(request.display_steps, ["extraction"])
        self.assertEqual(request.report_steps, ["extraction"])

    def test_llm_clears_display_and_report_when_request_has_no_scope_clause(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "run_pipeline",
                    "execution_steps": ["extraction"],
                    "display_steps": ["extraction"],
                    "report_steps": ["extraction"],
                }

        request, event = coordinate_with_llm(
            "重新运行脑提取。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction"])
        self.assertEqual(request.display_steps, [])
        self.assertEqual(request.report_steps, [])

    def test_viewing_constraint_fills_empty_llm_display(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "import_existing",
                    "execution_steps": [],
                    "display_steps": [],
                    "report_steps": [],
                }

        request, event = coordinate_with_llm(
            "把做好的重建图摊开给我看，别再算。",
            {"existing_run_dir": "/tmp/example", "explicit_fields": ["existing_run_dir"]},
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_mode, "import_existing")
        self.assertEqual(request.display_steps, ["reconstruction"])
        self.assertEqual(request.report_steps, [])

    def test_review_existing_run_is_import_not_continue(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "continue_from_run",
                    "execution_steps": ["extraction", "reconstruction"],
                    "display_steps": [],
                    "report_steps": [],
                }

        request, event = coordinate_with_llm(
            "打开旧结果，页面只给我看重建，报告照旧写全。",
            {"existing_run_dir": "/tmp/example", "explicit_fields": ["existing_run_dir"]},
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_mode, "import_existing")
        self.assertEqual(request.execution_steps, [])
        self.assertEqual(request.display_steps, ["reconstruction"])
        self.assertEqual(request.report_steps, [])

    def test_full_rerun_phrase_does_not_keep_short_llm_scope(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}

        request, event = coordinate_with_llm(
            "switch the reconstructor to SVRTK",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(
            request.execution_steps,
            ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )
        self.assertEqual(request.reconstruction_tool, "autosvrtk")

    def test_full_rerun_chinese_does_not_keep_short_llm_scope(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}

        request, event = coordinate_with_llm(
            "从原始BTFE完整重跑。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(
            request.execution_steps,
            ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )

    def test_only_recon_phrase_does_not_expand_to_full_pipeline(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}

        request, event = coordinate_with_llm(
            "只重建并评价技术质量，不做临床诊断。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["reconstruction"])

    def test_llm_writes_reconstruction_tool_when_text_is_silent(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "run_pipeline",
                    "reconstruction_tool": "niftymic",
                    "execution_steps": ["extraction", "reconstruction"],
                }

        request, event = coordinate_with_llm(
            "从头跑重建。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.reconstruction_tool, "niftymic")

    def test_text_backend_alias_beats_llm_frost(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "run_pipeline",
                    "reconstruction_tool": "frost",
                    "execution_steps": ["extraction", "reconstruction"],
                }

        request, event = coordinate_with_llm(
            "用 SVRTK 那一套重建。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.reconstruction_tool, "autosvrtk")

    def test_llm_keeps_registration_qc_without_adding_roi(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                self.system = system
                return {
                    "execution_mode": "run_pipeline",
                    "execution_steps": ["extraction", "reconstruction", "registration"],
                    "report_steps": ["registration"],
                }

        llm = FakeLLM()
        request, event = coordinate_with_llm(
            "对这个case做registration QC；如果可疑，明确写进报告，不要下诊断。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            llm,
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertNotIn("roi", request.execution_steps)
        self.assertNotIn("tissue", request.execution_steps)
        self.assertEqual(request.report_steps, ["registration"])
        self.assertIn("Do not put metrics, visualization, or", llm.system)
        self.assertIn("does not add roi", llm.system.lower())

    def _run_forced_pipeline(self, utterance, payload):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return payload

        return coordinate_with_llm(
            utterance,
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )

    def test_skip_alignment_strips_tissue_without_replacing_model_steps(self):
        request, event = self._run_forced_pipeline(
            "skull-strip then 3D volume, skip alignment",
            {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction", "tissue"]},
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction"])
        for step in ("tissue", "registration", "roi", "surface"):
            self.assertNotIn(step, request.execution_steps)

    def test_skip_alignment_chinese_strips_downstream_compute(self):
        request, event = self._run_forced_pipeline(
            "把脑子抠出来再堆成3D，先不要对到标准空间。",
            {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction", "tissue"]},
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction"])
        for step in ("tissue", "registration", "roi", "surface"):
            self.assertNotIn(step, request.execution_steps)

    def test_skip_alignment_only_forbidden_steps_do_not_expand_to_full_pipeline(self):
        request, event = self._run_forced_pipeline(
            "skull-strip then 3D volume, skip alignment",
            {"execution_mode": "run_pipeline", "execution_steps": ["tissue", "registration", "roi", "surface"]},
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, [])

    def test_roi_surface_rerun_is_not_stripped(self):
        request, event = self._run_forced_pipeline(
            "重跑ROI和surface。",
            {"execution_mode": "run_pipeline", "execution_steps": ["roi", "surface"]},
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["roi", "surface"])

    def test_registration_rerun_and_do_not_miss_registration_keep_registration(self):
        kept, event = self._run_forced_pipeline(
            "重新运行registration和组织分割。",
            {"execution_mode": "run_pipeline", "execution_steps": ["registration", "tissue"]},
        )
        self.assertTrue(event["used"])
        self.assertEqual(kept.execution_steps, ["registration", "tissue"])
        missed, missed_event = self._run_forced_pipeline(
            "不要漏掉配准。",
            {
                "execution_mode": "run_pipeline",
                "execution_steps": ["extraction", "reconstruction", "registration"],
            },
        )
        self.assertTrue(missed_event["used"])
        self.assertEqual(missed.execution_steps, ["extraction", "reconstruction", "registration"])

    def test_empty_report_steps_fill_from_constrained_report_scope(self):
        request, event = self._run_forced_pipeline(
            "对这个case做registration QC；如果可疑，明确写进报告，不要下诊断。",
            {
                "execution_mode": "run_pipeline",
                "execution_steps": ["extraction", "reconstruction", "registration"],
                "report_steps": [],
            },
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.report_steps, ["registration"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertNotIn("roi", request.execution_steps)
        self.assertNotIn("tissue", request.execution_steps)

    def test_llm_metrics_step_is_dropped_and_does_not_add_roi(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {
                    "execution_mode": "run_pipeline",
                    "execution_steps": ["reconstruction", "metrics"],
                    "display_steps": [],
                    "report_steps": [],
                }

        request, event = coordinate_with_llm(
            "只重建并评价技术质量，不做临床诊断。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "gestational_age": 31,
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["reconstruction"])
        self.assertNotIn("roi", request.execution_steps)
        self.assertNotIn("metrics", request.execution_steps)
        self.assertEqual([step.id for step in plan(request).steps], ["input_check", "extraction", "reconstruction"])

    def test_colloquial_refusals_match_keyword_rules(self):
        from agentic.capability_catalog import DESTRUCTIVE, HOSPITAL, NORMALITY, NORMATIVE

        self.assertIn(NORMATIVE, coordinate("和同龄胎儿比一比谁大谁小。").unfulfilled_requests)
        self.assertIn(NORMALITY, coordinate("这例发育得好不好？").unfulfilled_requests)
        self.assertIn(NORMALITY, coordinate("帮我看看这脑子长得行不行。").unfulfilled_requests)
        self.assertIn(DESTRUCTIVE, coordinate("把工作目录清空再从头来。").unfulfilled_requests)
        self.assertIn(DESTRUCTIVE, coordinate("wipe previous runs then process again").unfulfilled_requests)
        self.assertIn(HOSPITAL, coordinate("把报告甩到医院 PACS 里。").unfulfilled_requests)

    def test_llm_empty_execution_steps_defaults_to_full_pipeline(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": []}

        request, event = coordinate_with_llm(
            "",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(
            request.execution_steps,
            ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
        )

    def test_llm_error_falls_back_to_rules(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                raise LLMError("timeout", status=504, provider="openai_compatible")

        request, event = coordinate_with_llm(
            "只跑 reconstruction",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/input",
                "work_root": "/tmp/output",
                "atlas": "/tmp/31w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
            FakeLLM(),
        )
        self.assertFalse(event["used"])
        self.assertEqual(event["status"], "fallback")
        self.assertEqual(request.execution_steps, ["reconstruction"])

    def test_reconstruction_backend_is_inferred_and_planned(self):
        request = coordinate(
            "用 NeSVoR 重跑 reconstruction",
            {"subject_dir": "/tmp", "work_root": "/tmp/run", "explicit_fields": ["subject_dir", "work_root"]},
        )
        result = plan(request)
        self.assertEqual(request.reconstruction_tool, "nesvor")
        self.assertEqual(result.reconstruction_tool, "nesvor")
        self.assertEqual(result.steps[-1].tool, "nesvor_reconstruction")
        self.assertEqual(validate_plan(result), [])

    def test_svrtk_and_nifty_mic_aliases_map_to_backends(self):
        self.assertEqual(coordinate("用 SVRTK 那一套重建。").reconstruction_tool, "autosvrtk")
        self.assertEqual(coordinate("用 nifty-mic 跑重建。").reconstruction_tool, "niftymic")
        self.assertEqual(coordinate("switch the reconstructor to SVRTK").reconstruction_tool, "autosvrtk")
        self.assertEqual(coordinate("use nifty mic").reconstruction_tool, "niftymic")
        self.assertEqual(coordinate("use AutoSVRTK").reconstruction_tool, "autosvrtk")

    def test_explicit_reconstruction_backend_wins(self):
        request = coordinate(
            "用 FROST 重跑 reconstruction",
            {"reconstruction_tool": "niftymic", "explicit_fields": ["reconstruction_tool"]},
        )
        self.assertEqual(request.reconstruction_tool, "niftymic")

    def test_all_reconstruction_comparison_is_preserved_in_plan(self):
        request = coordinate(
            "compare all reconstruction backends",
            {"reconstruction_compare_tools": "all", "explicit_fields": ["reconstruction_compare_tools"]},
        )
        result = plan(request)
        self.assertEqual(request.reconstruction_compare_tools, ["frost", "nesvor", "autosvrtk", "niftymic"])
        self.assertEqual(result.reconstruction_compare_tools, request.reconstruction_compare_tools)
        self.assertIn("comparison", [step.id for step in result.steps])
        self.assertEqual(validate_plan(result), [])

    def test_comparison_is_a_plan_step_but_not_a_bash_step(self):
        from agentic.planner import BASH_STEPS

        request = coordinate(
            "从原始数据运行四个重建方法，比较全部结果并推荐最佳方法。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp",
                "work_root": "/tmp/work",
                "atlas": "/tmp/29w.nii.gz",
                "execution_steps": ["extraction", "reconstruction", "registration"],
                "reconstruction_compare_tools": "all",
                "explicit_fields": [
                    "execution_mode", "subject_dir", "work_root", "atlas",
                    "execution_steps", "reconstruction_compare_tools",
                ],
            },
        )
        result = plan(request)
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertEqual(result.execution_steps, ["extraction", "reconstruction", "registration"])
        ids = [step.id for step in result.steps]
        self.assertEqual(ids, ["input_check", "extraction", "reconstruction", "comparison", "registration"])
        self.assertEqual(result.steps[ids.index("comparison")].tool, "reconstruction_comparison")
        self.assertNotIn("comparison", BASH_STEPS)
        self.assertEqual(validate_plan(result), [])

    def test_fresh_rerun_beats_unmodified_form_defaults(self):
        request = coordinate(
            "请对31周胎儿 AnHuiJing 从原始 BTFE 输入完整重跑 extraction、reconstruction、registration。"
            "然后对于每一步骤给出报告并且给出所有步骤的最终报告",
            {"execution_mode": "import_existing", "existing_run_dir": "/tmp/BaiHuPing_run01", "explicit_fields": []},
        )
        self.assertEqual(request.execution_mode, "run_pipeline")
        self.assertIsNone(request.existing_run_dir)
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertEqual(request.report_steps, ["extraction", "reconstruction", "registration"])
        self.assertEqual(request.report_layout, "per_step_and_final")
        self.assertEqual(request.gestational_age, 31)
        self.assertEqual(request.missing, ["atlas", "subject_dir", "work_root"])

    def test_explicit_execution_mode_still_wins(self):
        request = coordinate(
            "重跑 reconstruction",
            {"execution_mode": "plan_only", "explicit_fields": ["execution_mode"]},
        )
        self.assertEqual(request.execution_mode, "plan_only")
        self.assertEqual(set(request.missing), {"atlas", "subject_dir", "work_root"})

    def test_supported_reports_are_not_marked_unfulfilled(self):
        self.assertEqual(
            normalize_unfulfilled_requests([
                "extraction_report", "registration_report", "final_report_zh",
                "完整中文报告(无对应报告生成工具)", "unsupported_custom_analysis",
            ]),
            ["unsupported_custom_analysis"],
        )

    def test_fallback_plan_lists_are_not_mutated_by_candidate(self):
        request = coordinate(
            "重跑 extraction 并生成每一步报告和最终报告",
            {"subject_dir": "/tmp", "work_root": "/tmp/run", "explicit_fields": ["subject_dir", "work_root"]},
        )
        fallback = plan(request)
        request.unfulfilled_requests.append("final_report")
        self.assertEqual(fallback.unfulfilled_requests, [])
        self.assertEqual(fallback.report_steps, ["extraction"])

    def test_numbered_llm_step_ids_are_canonicalized_from_tools(self):
        request = coordinate(
            "重跑 extraction reconstruction registration",
            {"subject_dir": "/tmp", "work_root": "/tmp/run", "atlas": "/tmp/atlas", "explicit_fields": ["subject_dir", "work_root", "atlas"]},
        )
        candidate = _plan_from_json(request, {"steps": [
            {"id": "step1", "tool": "input_check", "depends_on": []},
            {"id": "step2", "tool": "brain_extraction", "depends_on": ["step1"]},
            {"id": "step3", "tool": "frost_reconstruction", "depends_on": ["step2"]},
            {"id": "step4", "tool": "rigid_registration", "depends_on": ["step3"]},
        ]})
        self.assertEqual([step.id for step in candidate.steps], ["input_check", "extraction", "reconstruction", "registration"])
        self.assertEqual(candidate.steps[-1].depends_on, ["reconstruction"])
        self.assertEqual(validate_plan(candidate), [])

    def test_qc_evidence_has_metrics_for_all_pipeline_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject = "Demo"
            image = nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.float32), np.eye(4))
            label = nib.Nifti1Image(np.pad(np.ones((4, 4, 4), dtype=np.uint8), 2), np.eye(4))
            for path, value in [
                (root / "staging" / subject / "BTFE_demo.nii.gz", image),
                (root / "staging" / subject / "seg" / "BTFE_demo.nii.gz", label),
                (root / "outputs" / "recon" / f"{subject}.nii.gz", image),
                (root / "outputs" / "registered_input" / f"{subject}.nii.gz", image),
                (root / "outputs" / "Tissue" / f"{subject}.nii.gz", label),
                (root / "outputs" / "ROI" / f"{subject}.nii.gz", label),
            ]:
                path.parent.mkdir(parents=True, exist_ok=True); nib.save(value, path)
            registration = root / "outputs" / "registration"; registration.mkdir(parents=True)
            (registration / "summary.csv").write_text(
                "mattes_lower_is_better,gc_lower_is_better,warped\n-0.30,-0.50," + str(root / "outputs" / "registered_input" / f"{subject}.nii.gz") + "\n"
            )
            surface = root / "outputs" / "surface_subjects" / subject
            for name in ("lh.white", "rh.white", "lh.pial", "rh.pial", "lh.inflated", "rh.inflated"):
                path = surface / "surf" / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            for name in ("roi86_basic.stats", "roi86_thicknessproxy_cortexonly.stats"):
                path = surface / "stats" / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            qc = evaluate_run(root, subject)
            self.assertEqual([item["step_id"] for item in qc["steps"]], ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"])
            self.assertTrue(all(len(item["metrics"]) >= 2 for item in qc["steps"]))

    def test_unknown_tool_is_rejected(self):
        request = coordinate("plan")
        result = plan(request)
        result.steps = [PlanStep("bad", "shell_exec", [])]
        self.assertTrue(any("Unknown tool" in error for error in validate_plan(result)))

    def test_json_schemas_accept_current_objects(self):
        root = Path(__file__).resolve().parents[1]
        request = coordinate("show reconstruction")
        result = plan(request)
        self.assertEqual(validate_agentic_objects(root, request.to_dict(), result.to_dict()), [])

    def test_refusals_are_explained_in_plan_and_chinese_report(self):
        from agentic.reporter import build_report

        request = coordinate(
            "导入已有结果并发送到医院系统，判断是否正常。",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        self.assertIn("external_hospital_delivery_unsupported", request.unfulfilled_requests)
        self.assertIn("normality_assessment_requires_validated_GA_reference_and_expert_review", request.unfulfilled_requests)
        titles = {item["title"] for item in request.refusal_explanations}
        self.assertIn("未发送到医院系统", titles)
        self.assertIn("不能判断是否正常", titles)
        request.report_language = "zh"
        markdown, payload = build_report(plan(request), [])
        self.assertIn("未发送到医院系统", markdown)
        self.assertIn("不能判断是否正常", markdown)
        self.assertIn("未完成与拒绝", markdown)
        self.assertIn("> [!refusal]", markdown)
        self.assertIn("阅片复核清单", markdown)
        self.assertEqual(payload["language"], "zh")

    def test_which_is_best_is_a_catalog_refusal(self):
        request = coordinate("排名再看一眼，直接告诉我哪个最好。")
        self.assertIn("best_method_requires_expert_blind_review", request.unfulfilled_requests)

    def test_continue_without_a_run_does_not_invent_six_steps(self):
        request = coordinate(
            "接着上次的做。",
            {"execution_mode": "continue_from_run", "explicit_fields": ["execution_mode"]},
        )
        self.assertEqual(request.execution_mode, "continue_from_run")
        self.assertEqual(request.execution_steps, [])
        self.assertIn("existing_run_dir", request.missing)
        self.assertIsNone(request.existing_run_dir)
        self.assertEqual([step.id for step in plan(request).steps], ["input_check"])

    def test_best_method_is_a_catalog_refusal(self):
        from agentic.reporter import build_report

        request = coordinate("比较全部结果并推荐最佳方法。")
        self.assertIn("best_method_requires_expert_blind_review", request.unfulfilled_requests)
        self.assertTrue(any(item["title"] == "不能宣称最佳重建方法" for item in request.refusal_explanations))
        request.report_language = "zh"
        markdown, payload = build_report(plan(request), [])
        self.assertIn("不能宣称最佳重建方法", markdown)
        self.assertIn("方法比较", markdown)
        self.assertIn("frost", markdown)
        self.assertEqual(payload["language"], "zh")

    def test_percentile_refusal_appears_in_chinese_report(self):
        from agentic.reporter import build_report

        request = coordinate(
            "完整处理这个病例，使用35周图谱，并给出孕周百分位。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/subject",
                "work_root": "/tmp/work",
                "atlas": "/tmp/35w.nii.gz",
                "gestational_age": 36.714,
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age"],
            },
        )
        request.report_language = "zh"
        markdown, _ = build_report(plan(request), [])
        self.assertIn("不能给出孕周百分位", markdown)
        self.assertIn("未完成与拒绝", markdown)
        self.assertIn("> [!refusal]", markdown)
        self.assertIn("阅片复核清单", markdown)

    def test_dice_auc_and_ventricle_refusals_appear_in_chinese_report(self):
        from agentic.reporter import build_report

        request = coordinate(
            "孕31周，胎儿脑提取，图像配准，组织分割，侧脑室分割并提取，划分扩张侧脑室及周围皮质下组织，生成技术报告，提供Dice系数、AUC(95%C)数值",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        self.assertIn("supervised_metrics_require_ground_truth", request.unfulfilled_requests)
        self.assertIn("ventricle_dilation_subregioning_unsupported", request.unfulfilled_requests)
        titles = {item["title"] for item in request.refusal_explanations}
        self.assertIn("不能计算 Dice / AUC", titles)
        self.assertIn("不能划分扩张侧脑室及周围皮质下组织", titles)
        request.report_language = "zh"
        markdown, payload = build_report(plan(request), [])
        self.assertIn("不能计算 Dice / AUC", markdown)
        self.assertIn("不能划分扩张侧脑室及周围皮质下组织", markdown)
        self.assertIn("未完成与拒绝", markdown)
        self.assertIn("> [!refusal]", markdown)
        self.assertLess(markdown.find("未完成与拒绝"), markdown.find("阅片要点"))
        self.assertEqual(payload["language"], "zh")
        self.assertNotIn("已执行步骤质控", markdown)
        self.assertNotIn("影像与测量", markdown)

    def test_doctor_report_hides_qc_dump_and_leads_with_refusals(self):
        from agentic.reporter import build_report

        request = coordinate(
            "孕31周，提供Dice系数",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        request.report_language = "zh"
        results = [{
            "step_id": "pipeline",
            "status": "completed",
            "outputs": {"technical_analysis": {
                "case_info": {
                    "conversion": {
                        "kept_family": "t2_ssfse",
                        "kept_family_label": "T2 HASTE / SSFSE",
                        "stacks": ["t2_haste_cor_p2_2.nii.gz", "t2_haste_cor_p2_3.nii.gz"],
                        "drop_reasons": [
                            {"family": "t1", "reason": "other_modality"},
                            {"family": "dwi", "reason": "not_3d"},
                        ],
                    },
                },
                "step_summary": {"completed": ["extraction", "reconstruction"], "failed": [], "skipped": ["roi"]},
                "image_checks": {"reconstruction": "PASS: valid NIfTI dims=(209, 178, 182)"},
                "surface_checks": {},
                "registration_summary": {"available": True, "status": "ok", "qc_group": "acceptable"},
                "quantitative_summary": {},
                "step_qc": {"steps": [
                    {"step_id": "extraction", "status": "pass", "metrics": [{"name": "mask_success_rate", "value": 1.0}]},
                    {"step_id": "reconstruction", "status": "pass", "metrics": [{"name": "nonzero_voxel_fraction", "value": 0.361895}]},
                    {"step_id": "roi", "status": "skipped"},
                ]},
            }},
        }]
        markdown, _ = build_report(plan(request), results)
        self.assertLess(markdown.find("未完成与拒绝"), markdown.find("本次完成"))
        self.assertLess(markdown.find("本次完成"), markdown.find("阅片要点"))
        self.assertIn("T2 HASTE / SSFSE", markdown)
        self.assertIn("未做：脑区划分", markdown)
        self.assertIn("> [!finding]", markdown)
        self.assertNotIn("0.361895", markdown)
        self.assertNotIn("t2_haste_cor_p2_2.nii.gz", markdown)
        self.assertNotIn("已执行步骤质控", markdown)
        self.assertNotIn("dims=", markdown)

    def _zh_report_llm_plan(self):
        request = coordinate(
            "孕31周，提供Dice系数、AUC(95%C)数值，划分扩张侧脑室及周围皮质下组织",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        request.report_language = "zh"
        return plan(request)

    def _zh_report_analysis_results(self):
        return [{
            "step_id": "pipeline",
            "status": "completed",
            "outputs": {"technical_analysis": {
                "case_info": {"subject": "Demo"},
                "step_summary": {"completed": [], "failed": [], "skipped": []},
                "image_checks": {},
                "surface_checks": {},
                "registration_summary": {},
                "quantitative_summary": {},
                "step_qc": {"steps": []},
            }},
        }]

    @staticmethod
    def _zh_llm_report(*, dice_score: str | None = None) -> str:
        return (
            "# AutoRecon 分析报告\n\n"
            "## 本次请求与执行范围\n"
            "- 请求：孕31周，提供Dice系数、划分扩张侧脑室\n\n"
            "## 未完成与拒绝\n\n"
            "> [!refusal]\n"
            "> **不能计算 Dice / AUC**\n"
            "> 没有金标准分割或诊断标签。\n\n"
            "> [!refusal]\n"
            "> **不能划分扩张侧脑室及周围皮质下组织**\n"
            "> 当前没有侧脑室扩张分区专用工具。\n\n"
            "## 阅片要点\n"
            "> [!finding]\n"
            "> **技术产物可读，可供阅片**\n"
            f"{'> Dice 系数为 ' + dice_score + '。\n' if dice_score else ''}"
            "> 不能替代临床诊断。\n\n"
            "## 能力边界\n"
            "本报告用于科研阅片支持，不能替代临床诊断。\n\n"
            "## 阅片复核清单\n"
            "- [ ] 如需 Dice / AUC，请另行提供金标准分割或诊断标签\n"
            "- [ ] 侧脑室扩张分区需专用标注或工具\n"
        )

    def test_llm_report_retries_once_with_validation_errors(self):
        from agentic.reporter import build_report

        calls: list[str] = []

        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {
                "use_for_reporting": True, "fallback_to_rules": True, "model": "glm-test",
            })()

            def complete(self, system, user):
                calls.append(user)
                if "Validation errors to repair" in user:
                    return AgenticTests._zh_llm_report()
                return AgenticTests._zh_llm_report(dice_score="0.91")

        markdown, payload = build_report(
            self._zh_report_llm_plan(),
            self._zh_report_analysis_results(),
            llm=FakeLLM(),
        )
        self.assertEqual(len(calls), 2)
        self.assertIn("Validation errors to repair", calls[1])
        self.assertIn("0.91", calls[1])
        self.assertNotIn("0.91", markdown)
        reporting = payload["llm"]["reporting"]
        self.assertTrue(reporting["used"])
        self.assertEqual(reporting["attempt"], 2)
        self.assertTrue(reporting["repaired"])

    def test_llm_report_falls_back_after_one_failed_repair(self):
        from agentic.reporter import build_report

        calls: list[str] = []

        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {
                "use_for_reporting": True, "fallback_to_rules": True, "model": "glm-test",
            })()

            def complete(self, system, user):
                calls.append(user)
                return AgenticTests._zh_llm_report(dice_score="0.91")

        markdown, payload = build_report(
            self._zh_report_llm_plan(),
            self._zh_report_analysis_results(),
            llm=FakeLLM(),
        )
        self.assertEqual(len(calls), 2)
        self.assertIn("Validation errors to repair", calls[1])
        self.assertIn("不能计算 Dice / AUC", markdown)
        reporting = payload["llm"]["reporting"]
        self.assertFalse(reporting["used"])
        self.assertEqual(reporting["status"], "fallback")
        self.assertIn("0.91", reporting["error"])

    def test_llm_report_does_not_repair_retry_transport_errors(self):
        from agentic.reporter import build_report

        calls = {"n": 0}

        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {
                "use_for_reporting": True, "fallback_to_rules": True, "model": "glm-test",
            })()

            def complete(self, system, user):
                calls["n"] += 1
                raise LLMError("LLM HTTP 503", status=503, provider="openai_compatible")

        markdown, payload = build_report(
            self._zh_report_llm_plan(),
            self._zh_report_analysis_results(),
            llm=FakeLLM(),
        )
        self.assertEqual(calls["n"], 1)
        self.assertIn("不能计算 Dice / AUC", markdown)
        reporting = payload["llm"]["reporting"]
        self.assertFalse(reporting["used"])
        self.assertIn("503", reporting["error"])

    def test_continue_from_run_reuses_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject = "Demo"
            (root / "dashboard").mkdir()
            (root / "dashboard" / "run_state.json").write_text(
                json.dumps({"run": {"subject_name": subject}}), encoding="utf-8"
            )
            recon = root / "outputs" / "recon" / f"{subject}.nii.gz"
            recon.parent.mkdir(parents=True)
            nib.save(nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), str(recon))
            mask_dir = root / "staging" / subject / "seg"
            mask_dir.mkdir(parents=True)
            nib.save(nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.float32), np.eye(4)), str(mask_dir / "BTFE_1.nii.gz"))
            request = coordinate(
                "接着做配准",
                {
                    "execution_mode": "continue_from_run",
                    "existing_run_dir": str(root),
                    "work_root": str(root),
                    "subject_dir": str(root / "staging" / subject),
                    "atlas": "/tmp/atlas.nii.gz",
                    "explicit_fields": ["execution_mode", "existing_run_dir", "work_root", "subject_dir", "atlas"],
                },
            )
            self.assertEqual(request.execution_mode, "continue_from_run")
            self.assertTrue(request.resume)
            self.assertIn("reconstruction", request.reused_steps)
            self.assertIn("extraction", request.reused_steps)
            self.assertNotIn("reconstruction_artifact", request.missing)
            result = plan(request)
            self.assertTrue(result.resume)
            self.assertEqual(result.execution_mode, "continue_from_run")
            from agentic.reporter import build_report
            request.report_language = "zh"
            markdown, _ = build_report(result, [])
            self.assertIn("复用已有结果", markdown)
            self.assertIn("三维重建", markdown)
            self.assertIn("阅片复核清单", markdown)

    def test_restore_rewrites_refusal_callouts_and_appends_review_checklist(self):
        from agentic.reporter import _restore_chinese_invariants

        request = coordinate(
            "导入已有结果并发送到医院系统。",
            {
                "execution_mode": "import_existing",
                "existing_run_dir": "/tmp/existing",
                "explicit_fields": ["execution_mode", "existing_run_dir"],
            },
        )
        request.report_language = "zh"
        task_plan = plan(request)
        rewritten = _restore_chinese_invariants(
            "# 报告\n\n## 本次请求与执行范围\n- 请求：导入已有结果\n\n"
            "## 未完成与拒绝\n- **未发送到医院系统**\n  - 不会外送\n\n"
            "## 能力边界\n本系统只调度已注册的确定工具并汇总结构化结果。",
            task_plan,
        )
        self.assertIn("> [!refusal]", rewritten)
        self.assertIn("**未发送到医院系统**", rewritten)
        self.assertIn("阅片复核清单", rewritten)
        self.assertIn("- [ ]", rewritten)

    def test_restore_replaces_truncated_review_checklist(self):
        from agentic.reporter import _restore_chinese_invariants
        from agentic.models import task_plan_from_dict

        task_plan = task_plan_from_dict(plan(coordinate(
            "完整分析，不要 Dice。划分扩张侧脑室。",
            {"subject_dir": "/tmp/Upload", "gestational_age": 29, "explicit_fields": ["subject_dir", "gestational_age"]},
        )).to_dict())
        truncated = (
            "# 胎儿脑 MRI 技术分析报告\n\n"
            "## 未完成与拒绝\n> [!refusal]\n> **不能计算 Dice / AUC**\n> 无金标准。\n\n"
            "## 本次完成\n- 已做：表面重建\n\n"
            "## 阅片要点\n> [!finding]\n> **技术产物可读，可供阅片**\n> 仍须目视 overlay。\n\n"
            "## 阅片复核清单\n\n- [ ] 目视复核配准 overlay（质控为“需复核”，相似性度量不能代替目视\n\n"
            "## 能力边界\n本报告用于科研阅片支持，不能替代临床诊断；没有金标准时不计算 Dice、AUC。\n"
        )
        rewritten = _restore_chinese_invariants(
            truncated,
            task_plan,
            {
                "registration_summary": {"available": True, "qc_group": "suspicious"},
                "surface_checks": {"present_surface_files": ["lh.pial", "rh.pial"]},
                "step_summary": {"failed": [], "skipped": []},
            },
        )
        self.assertIn("相似性度量不能代替目视检查", rewritten)
        self.assertIn("目视复核双侧表面拓扑与解剖正确性", rewritten)
        self.assertNotIn("不能代替目视\n", rewritten)
        self.assertGreaterEqual(rewritten.count("- [ ]"), 2)

    def test_curated_chinese_reports_keep_refusals_and_review_checklist(self):
        root = Path(__file__).resolve().parents[1] / "validation_runs/case_acceptance_20260904T0819Z/cases"
        for case_id in ("I01", "I02", "N01", "N02", "N03", "N04", "C01"):
            markdown = (root / case_id / "report.md").read_text(encoding="utf-8")
            self.assertIn("阅片复核清单", markdown, case_id)
        for case_id, title in (
            ("I01", "不能判断是否正常"),
            ("I02", "未发送到医院系统"),
            ("N04", "不能给出孕周百分位"),
            ("C01", "不能宣称最佳重建方法"),
        ):
            markdown = (root / case_id / "report.md").read_text(encoding="utf-8")
            self.assertIn("> [!refusal]", markdown, case_id)
            self.assertIn(title, markdown, case_id)
        i02 = (root / "I02" / "report.md").read_text(encoding="utf-8")
        self.assertIn("目视复核配准 overlay", i02)
        self.assertIn("确认报告仅留本机", i02)

    def test_continue_without_recon_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dashboard").mkdir()
            (root / "dashboard" / "run_state.json").write_text(
                json.dumps({"run": {"subject_name": "Demo"}}), encoding="utf-8"
            )
            request = coordinate(
                "接着做配准",
                {
                    "execution_mode": "continue_from_run",
                    "existing_run_dir": str(root),
                    "work_root": str(root),
                    "subject_dir": "/tmp/Demo",
                    "atlas": "/tmp/atlas.nii.gz",
                    "explicit_fields": ["execution_mode", "existing_run_dir", "work_root", "subject_dir", "atlas"],
                },
            )
            self.assertIn("reconstruction_artifact", request.missing)
            self.assertIn("缺少重建结果", {item["title"] for item in request.refusal_explanations})
            errors = validate_plan(plan(request))
            self.assertTrue(any("Missing required" in item or "reconstruction_artifact" in item for item in errors))

    def test_clinic_defaults_reuse_latest_run(self):
        from agentic.clinic_paths import apply_clinic_defaults

        with tempfile.TemporaryDirectory() as directory:
            case_id = "DemoCase"
            latest = Path(directory) / case_id / "run01"
            (latest / "dashboard").mkdir(parents=True)
            (latest / "dashboard" / "run_state.json").write_text("{}", encoding="utf-8")
            with patch("agentic.clinic_paths.work_root", return_value=Path(directory)):
                payload = apply_clinic_defaults({
                    "raw_text": "接着做配准",
                    "case_id": case_id,
                    "gestational_age": "31",
                    "clinic": True,
                })
            self.assertEqual(payload["execution_mode"], "continue_from_run")
            self.assertEqual(payload["work_root"], str(latest))
            self.assertEqual(payload["gestational_age"], 31.0)
            self.assertEqual(payload["report_language"], "zh")
            self.assertIn("gestational_age", payload["explicit_fields"])

    def test_clinic_defaults_to_middle_installed_atlas_week(self):
        from agentic.clinic_paths import apply_clinic_defaults

        with tempfile.TemporaryDirectory() as directory:
            atlas_root = Path(directory) / "atlas"
            atlas_root.mkdir()
            for week in (22, 23, 24, 25):
                (atlas_root / f"{week}w.nii.gz").write_bytes(b"atlas")
            with (
                patch("agentic.clinic_paths.atlas_dir", return_value=atlas_root),
                patch("agentic.clinic_paths.find_latest_run", return_value=None),
                patch("agentic.clinic_paths.cases_root", return_value=Path(directory) / "cases"),
                patch("agentic.clinic_paths.work_root", return_value=Path(directory) / "runs"),
            ):
                payload = apply_clinic_defaults({"raw_text": "完成重建与配准", "case_id": "Demo"})
            self.assertEqual(payload["atlas"], str(atlas_root / "24w.nii.gz"))
            self.assertEqual(payload["atlas_week"], 24)
            self.assertEqual(payload["atlas_rule"], "default_middle")
            self.assertIsNone(payload.get("gestational_age"))
            self.assertNotIn("gestational_age", payload["explicit_fields"])
            self.assertEqual(payload["roi_mode"], "warp")

    def test_clinic_defaults_read_gestational_age_from_natural_language(self):
        from agentic.clinic_paths import apply_clinic_defaults

        with tempfile.TemporaryDirectory() as directory:
            atlas_root = Path(directory) / "atlas"
            atlas_root.mkdir()
            for week in (22, 23, 24, 32, 33):
                (atlas_root / f"{week}w.nii.gz").write_bytes(b"atlas")
            with (
                patch("agentic.clinic_paths.atlas_dir", return_value=atlas_root),
                patch("agentic.clinic_paths.find_latest_run", return_value=None),
                patch("agentic.clinic_paths.cases_root", return_value=Path(directory) / "cases"),
                patch("agentic.clinic_paths.work_root", return_value=Path(directory) / "runs"),
            ):
                payload = apply_clinic_defaults({"raw_text": "32周，完成全部六步", "case_id": "Demo"})
            self.assertEqual(payload["gestational_age"], 32.0)
            self.assertEqual(payload["atlas_week"], 32)
            self.assertEqual(payload["atlas_rule"], "exact")
            self.assertIn("gestational_age", payload["explicit_fields"])

    def test_clinic_intake_requires_ga_description_and_disease(self):
        from agentic.clinic_paths import clinic_intake_errors

        self.assertIn("请填写胎龄（周）。", clinic_intake_errors({"clinic": True}))
        self.assertIn(
            "请填写胎儿描述。",
            clinic_intake_errors({"gestational_age": 32, "clinical_status": "none"}),
        )
        self.assertIn(
            "请选择临床所见。",
            clinic_intake_errors({
                "gestational_age": 32,
                "fetal_description": "单胎",
            }),
        )
        self.assertIn(
            "请填写疾病名称。",
            clinic_intake_errors({
                "gestational_age": 32,
                "fetal_description": "单胎",
                "clinical_status": "present",
            }),
        )
        self.assertEqual(
            clinic_intake_errors({
                "gestational_age": 32,
                "fetal_description": "单胎，头位",
                "clinical_status": "none",
            }),
            [],
        )

    def test_clinic_intake_is_copied_into_request_and_chinese_report(self):
        from agentic.reporter import build_report

        request = coordinate(
            "完成全部六步",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/case",
                "work_root": "/tmp/case/run",
                "gestational_age": 32,
                "fetal_description": "单胎，头位",
                "clinical_status": "present",
                "clinical_condition": "侧脑室轻度扩张",
                "clinical_notes": "重建伪影明显",
                "explicit_fields": [
                    "execution_mode", "subject_dir", "work_root",
                    "gestational_age", "fetal_description", "clinical_status", "clinical_condition", "clinical_notes",
                ],
            },
        )
        self.assertEqual(request.gestational_age, 32)
        self.assertEqual(request.fetal_description, "单胎，头位")
        self.assertEqual(request.clinical_status, "present")
        self.assertEqual(request.clinical_condition, "侧脑室轻度扩张")
        self.assertEqual(request.clinical_notes, "重建伪影明显")
        request.report_language = "zh"
        markdown, _ = build_report(plan(request), [])
        self.assertIn("## 病例信息", markdown)
        self.assertIn("胎龄：32 周", markdown)
        self.assertIn("描述：单胎，头位", markdown)
        self.assertIn("临床所见：存在异常", markdown)
        self.assertIn("疾病：侧脑室轻度扩张", markdown)
        self.assertIn("备注：重建伪影明显", markdown)

    def test_refresh_case_record_inserts_intake_into_existing_report(self):
        from agentic.reporter import refresh_case_record_section

        request = coordinate(
            "完成全部六步",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/case",
                "work_root": "/tmp/case/run",
                "gestational_age": 28,
                "fetal_description": "单胎",
                "clinical_status": "unknown",
                "explicit_fields": [
                    "execution_mode", "subject_dir", "work_root",
                    "gestational_age", "fetal_description", "clinical_status",
                ],
            },
        )
        request.report_language = "zh"
        rewritten = refresh_case_record_section(
            "# 胎儿脑 MRI 技术分析报告\n\n## 本次完成\n- 已做：三维重建\n",
            plan(request),
        )
        self.assertLess(rewritten.find("## 病例信息"), rewritten.find("## 本次完成"))
        self.assertIn("胎龄：28 周", rewritten)
        self.assertIn("临床所见：不确定", rewritten)


if __name__ == "__main__":
    unittest.main()
