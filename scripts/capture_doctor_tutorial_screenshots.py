#!/usr/bin/env python3
"""Capture live clinic UI screenshots for docs/user/DOCTOR_TUTORIAL.zh-CN.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PROJECT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT / "docs" / "user" / "assets"
CREDENTIALS = PROJECT / ".runtime" / "gateway" / "vpn_test_user.txt"
SAMPLE_STACKS = sorted(
    (PROJECT / ".runtime/gateway/users/vpn-test/clinic/uploads/Test_Public_AnHuiJing").glob("BTFE_*.nii.gz")
)[:3]


def load_login() -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip():
            values[key.strip()] = value.strip()
    return values["username"], values["password"]


def mask_account(page) -> None:
    page.evaluate(
        """() => {
          const who = document.getElementById("who");
          if (who) who.textContent = "协作医生";
        }"""
    )


def shot(page, name: str, *, full_page: bool = False, locator=None) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / name
    if locator is not None:
        locator.screenshot(path=str(path))
    else:
        page.screenshot(path=str(path), full_page=full_page)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    return path


def open_completed(page) -> None:
    page.wait_for_function(
        """() => {
          const el = document.getElementById("result_id");
          return el && [...el.options].some(o => o.value && !o.text.includes("正在加载") && !o.text.includes("暂无"));
        }""",
        timeout=30000,
    )
    chosen = page.evaluate(
        """() => {
          const el = document.getElementById("result_id");
          const options = [...el.options];
          const hit = options.find(o => /AnHuiJing|已完成/.test(o.text)) || options.find(o => o.value);
          if (!hit) return "";
          el.value = hit.value;
          el.dispatchEvent(new Event("change", {bubbles: true}));
          return hit.value;
        }"""
    )
    if not chosen:
        raise RuntimeError("no completed result to open")
    page.wait_for_function(
        """() => {
          const report = document.getElementById("reportBox");
          const cards = document.querySelectorAll(".gallery .card");
          return report && !report.classList.contains("muted") && cards.length >= 3;
        }""",
        timeout=45000,
    )
    page.locator(".gallery .thumbnail img").first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(800)


def open_step_viewer(page, title: str) -> None:
    page.locator(".gallery .card").filter(has_text=title).locator("button[data-media]").click()
    dialog = page.locator("#viewerDialog")
    dialog.wait_for(state="visible", timeout=15000)
    frame = page.frame_locator("#viewerBody iframe")
    try:
        frame.locator("img, canvas").first.wait_for(state="visible", timeout=25000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(1200)


def close_viewer(page) -> None:
    if page.locator("#viewerDialog").is_visible():
        page.locator("#viewerClose").click()
        page.wait_for_timeout(400)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:19001")
    args = parser.parse_args()
    username, password = load_login()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--font-render-hinting=none",
                "--enable-webgl",
                "--use-gl=angle",
                "--use-angle=swiftshader",
            ],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        page.locator("#loginBtn").wait_for(state="visible", timeout=20000)
        page.wait_for_timeout(400)
        shot(page, "01_login.png")

        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        page.locator("#loginBtn").click()
        page.locator("#appMain").wait_for(state="visible", timeout=20000)
        page.locator("#result_id").wait_for(state="visible")
        mask_account(page)
        page.wait_for_timeout(600)
        shot(page, "02_results_center.png")

        open_completed(page)
        mask_account(page)
        shot(page, "03_opened_result.png", full_page=True)
        shot(page, "03b_report.png", locator=page.locator(".workspace .panel").nth(0))
        shot(page, "03c_gallery.png", locator=page.locator(".workspace .panel").nth(1))
        shot(page, "03d_intake.png", locator=page.locator("#caseIntake"))

        page.locator("#gestational_age").fill("32")
        page.locator('input[name="clinical_status"][value="present"]').check()
        page.locator("#clinical_condition").wait_for(state="visible")
        page.locator("#clinical_condition").fill("侧脑室轻度扩张")
        page.locator("#fetal_description").fill("单胎，头位，羊水量正常")
        page.locator("#clinical_notes").fill("重建伪影明显、组织分割边界不清")
        page.wait_for_timeout(300)
        shot(page, "03e_intake_filled.png", locator=page.locator("#caseIntake"))

        open_step_viewer(page, "脑提取")
        shot(page, "04_viewer_extraction.png", locator=page.locator("#viewerDialog"))
        close_viewer(page)

        open_step_viewer(page, "图像配准")
        shot(page, "05_viewer_mpr.png", locator=page.locator("#viewerDialog"))
        close_viewer(page)

        open_step_viewer(page, "组织分割")
        shot(page, "05b_viewer_tissue.png", locator=page.locator("#viewerDialog"))
        close_viewer(page)

        open_step_viewer(page, "表面重建")
        shot(page, "06_viewer_surface.png", locator=page.locator("#viewerDialog"))
        close_viewer(page)

        page.locator('.module-tab[data-module="newAnalysisPanel"]').click()
        page.locator("#newAnalysisPanel").wait_for(state="visible")
        page.locator("#request").fill(
            "孕周 31 周。完成全部六步（脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建），并生成含分步质控的技术报告。"
        )
        page.locator("#case_label").fill("示例病例")
        if SAMPLE_STACKS:
            page.locator("#files").set_input_files([str(path) for path in SAMPLE_STACKS])
            page.wait_for_timeout(400)
        mask_account(page)
        shot(page, "07_new_analysis.png", full_page=True)

        page.locator('.source-choice-btn[data-source="continue"]').click()
        page.wait_for_timeout(800)
        mask_account(page)
        page.locator("#request").fill("孕周 31 周。接着完成组织分割、脑区划分与表面重建。")
        shot(page, "08_continue.png", full_page=True)

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
