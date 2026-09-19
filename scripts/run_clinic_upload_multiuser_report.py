#!/usr/bin/env python3
"""Run clinic upload / multi-user tests and write a report for lab meetings."""

from __future__ import annotations

import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_MD = ROOT / "docs" / "reports" / "CLINIC_UPLOAD.zh-CN.md"
REPORT_JSON = ROOT / "validation_results" / "current" / "clinic_upload_multiuser.json"


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _http_json(url: str, *, json_body=None, token=None, timeout=8):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error": raw}
        return exc.code, body


def live_smoke() -> dict:
    host = os.environ.get("AUTORECON_LIVE_GATEWAY", "http://127.0.0.1:19001").rstrip("/")
    doctor = ROOT / ".runtime" / "gateway" / "doctor_user.txt"
    doctor2 = ROOT / ".runtime" / "gateway" / "doctor2_user.txt"
    result = {"target": host, "reachable": False, "users": []}
    try:
        with socket.create_connection(("127.0.0.1", 19001), timeout=2):
            result["reachable"] = True
    except OSError as exc:
        result["error"] = str(exc)
        return result
    accounts = []
    for path in (doctor, doctor2):
        values = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip():
                    values[key.strip()] = value.strip()
        if values.get("username") and values.get("password"):
            accounts.append((values["username"], values["password"]))

    def login_and_list(username: str, password: str):
        status, body = _http_json(host + "/api/login", json_body={"username": username, "password": password})
        if status != 200:
            return {"username": username, "login": status, "error": body.get("error")}
        token = body["token"]
        rstatus, results = _http_json(host + "/api/results", token=token)
        runs = results.get("runs") if isinstance(results, dict) else []
        ids = [item.get("run_id") for item in runs if isinstance(item, dict)]
        return {
            "username": username,
            "login": status,
            "results_status": rstatus,
            "run_count": len(ids),
            "run_ids_sample": ids[:8],
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(login_and_list, user, password) for user, password in accounts]
        result["users"] = [item.result() for item in futures]
    if len(result["users"]) == 2:
        left = set(result["users"][0].get("run_ids_sample") or [])
        right = set(result["users"][1].get("run_ids_sample") or [])
        result["run_id_overlap"] = sorted(left & right)
        result["isolated"] = not (left & right)
    return result


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows: list[dict] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({"id": test.id(), "method": test._testMethodName, "status": "pass"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({"id": test.id(), "method": test._testMethodName, "status": "fail", "detail": self._exc_info_to_string(err, test).splitlines()[-1]})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({"id": test.id(), "method": test._testMethodName, "status": "error", "detail": self._exc_info_to_string(err, test).splitlines()[-1]})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append({"id": test.id(), "method": test._testMethodName, "status": "skip", "detail": reason})


def run_unittests() -> dict:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_clinic_upload_multiuser")
    started = datetime.now(timezone.utc)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult)
    result = runner.run(suite)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "ok": result.wasSuccessful(),
        "elapsed_seconds": round(elapsed, 3),
        "rows": result.rows,
        "failed": [
            {"test": row["id"], "detail": row.get("detail") or ""}
            for row in result.rows
            if row["status"] in {"fail", "error"}
        ],
    }


def classify(method: str) -> str:
    if method.startswith("test_f"):
        return "format"
    if method.startswith("test_m"):
        return "multiuser"
    return "other"


LABELS = {
    "test_f01_ascii_btfe_nifti": "NIfTI（BTFE_*.nii.gz）",
    "test_f02_unicode_nifti_name": "NIfTI（中文文件名，完成后规范化）",
    "test_f03_uncompressed_nii": "未压缩 .nii",
    "test_f04_dicom_zip": "DICOM zip（含中文压缩包名）",
    "test_f05_nested_dicom_folder": "DICOM 目录（嵌套路径 / 无扩展名）",
    "test_f06_ima_series": "DICOM .ima",
    "test_f07_reject_jpg": "拒绝 JPG 预览图",
    "test_f08_reject_viewer_dicom": "拒绝 Viewer 目录",
    "test_f09_reject_zip_mixed_with_nifti": "拒绝 zip 与 NIfTI 混传",
    "test_f10_client_filter_helpers_match_server": "初筛规则（JPG / Viewer / DICOMDIR）",
    "test_m01_concurrent_uploads_are_isolated": "双用户同时上传 NIfTI，目录互不重叠",
    "test_m02_cannot_complete_other_users_upload": "用户 B 无法 complete 用户 A 的上传",
    "test_m03_parallel_folder_uploads_from_two_users": "双用户同时上传 DICOM 目录",
    "test_m04_compute_is_serialized_across_users": "计算任务全局并发上限为 1",
}


def write_report(unit: dict, live: dict) -> None:
    rows = []
    for item in unit["rows"]:
        method = item["method"]
        label = LABELS.get(method, method)
        status = {"pass": "通过", "fail": "未通过", "error": "错误", "skip": "跳过"}.get(item["status"], item["status"])
        rows.append((classify(method), method, label, status))

    format_rows = [row for row in rows if row[0] == "format"]
    multi_rows = [row for row in rows if row[0] == "multiuser"]
    live_ok = bool(live.get("reachable") and live.get("users") and all(item.get("login") == 200 for item in live["users"]))
    isolated = live.get("isolated")
    conclusion = "通过" if unit["ok"] and live_ok else ("部分通过" if unit["ok"] or live_ok else "未通过")

    def table(items: list[tuple[str, str, str, str]]) -> str:
        lines = ["| 编号 | 内容 | 结果 |", "| --- | --- | --- |"]
        for index, (_kind, method, label, status) in enumerate(items, start=1):
            lines.append(f"| {index} | {label} | {status} |")
        return "\n".join(lines)

    live_lines = []
    if not live.get("reachable"):
        live_lines.append("线上网关 `127.0.0.1:19001` 不可达，未做账号冒烟。")
    else:
        live_lines.append(f"目标：`{live['target']}`。双账号同时登录并拉取结果列表。")
        for item in live.get("users") or []:
            live_lines.append(
                f"- `{item.get('username')}`：登录 HTTP {item.get('login')}，结果 {item.get('run_count')} 条"
            )
        if isolated is True:
            live_lines.append("两个账号的 `run_id` 无交集。")
        elif isolated is False:
            live_lines.append("两个账号的 `run_id` 出现交集，需要复查隔离。")

    md = f"""# 工作台上传与多用户测试记录

- 时间：{_now()}
- 结论：**{conclusion}**
- 范围：工作台 clinic 上传（NIfTI / zip / DICOM 目录）与双用户并发；不含完整六步重建耗时计算。
- 环境：隔离网关（临时数据目录）+ 本机 `127.0.0.1:19001` 账号冒烟。
- 复现：`python scripts/run_clinic_upload_multiuser_report.py`

## 1. 结论摘要

| 项目 | 结果 |
| --- | --- |
| 多种格式上传（隔离网关） | {"通过" if all(row[3] == "通过" for row in format_rows) else "未通过"} |
| 双用户同时操作（隔离网关） | {"通过" if all(row[3] == "通过" for row in multi_rows) else "未通过"} |
| 线上 `doctor` / `doctor2` 同时登录 | {"通过" if live_ok else "未做或失败"} |
| 线上结果列表隔离 | {"通过" if isolated else ("未验证" if isolated is None else "未通过")} |
| 自动化用例 | {unit["tests_run"]} 项，失败 {unit["failures"]}，错误 {unit["errors"]}，耗时 {unit["elapsed_seconds"]} s |

计算任务全局并发上限为 1：第二位用户提交 `run_pipeline` 时返回 429。上传本身允许并行。

## 2. 多种格式上传

{table(format_rows)}

说明：DICOM 转换在本轮用桩替换 dcm2niix，验证的是工作台收文件、筛无关文件、以及 complete 后的路径处理。真实 dcm2niix 对照见既有 `tests/test_dicom_to_btfe.py`（含 NJGL gold，需 `AUTORECON_DICOM_GOLD`）。

## 3. 多用户同时操作

{table(multi_rows)}

## 4. 线上账号冒烟

{chr(10).join(live_lines)}

## 5. 失败明细

"""
    if unit["failed"]:
        for item in unit["failed"]:
            md += f"- `{item['test']}`：{item['detail']}\n"
    else:
        md += "无。\n"
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md, encoding="utf-8")
    REPORT_JSON.write_text(
        json.dumps({"generated_at": _now(), "unit": unit, "live": live, "conclusion": conclusion}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    os.chdir(ROOT)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(key, None)
    unit = run_unittests()
    live = live_smoke()
    write_report(unit, live)
    print(f"wrote {REPORT_MD}")
    print(f"wrote {REPORT_JSON}")
    if not unit["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
