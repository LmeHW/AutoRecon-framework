from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.vis.clinic_viewers import (
    compose_mpr_viewer_html,
    compose_stack_viewer_html,
    compose_surface_viewer_html,
    localize_viewer_title,
    restyle_interactive_html,
)


class ClinicViewerTests(unittest.TestCase):
    def test_localize_english_pipeline_titles(self):
        self.assertEqual(
            localize_viewer_title("XuJing: all extraction stacks"),
            "XuJing · 脑提取",
        )
        self.assertEqual(
            localize_viewer_title("AnHuiJing: reconstructed MRI"),
            "AnHuiJing · 三维重建",
        )
        self.assertEqual(
            localize_viewer_title("CaoLi: ROI segmentation", Path("05_roi_interactive.html")),
            "CaoLi · 脑区划分",
        )
        self.assertEqual(
            localize_viewer_title("XuJing · 表面重建"),
            "XuJing · 表面重建",
        )

    def test_new_templates_are_chinese_clinic_chrome(self):
        stack = compose_stack_viewer_html("XuJing: all extraction stacks", "[]")
        self.assertIn("lang=\"zh-CN\"", stack)
        self.assertIn("播放", stack)
        self.assertIn("html.embedded", stack)
        self.assertIn("掩膜", stack)
        self.assertIn("--brand:#9d1822", stack)
        self.assertIn("grid-template-columns:minmax(210px,1.35fr)", stack)
        self.assertIn("grid-area:1/1", stack)
        self.assertIn("object-fit:contain", stack)
        self.assertIn("width:100%", stack)
        self.assertIn("DEFAULT_VIEW_PX=480", stack)
        self.assertIn("naturalWidth", stack)
        self.assertIn("fitScale", stack)
        self.assertIn("function zoomBy(", stack)
        self.assertIn("MIN_ZOOM=0.25", stack)
        self.assertNotIn("function zoomAt(", stack)
        self.assertNotIn("ox*(1-next/viewScale)", stack)
        self.assertIn("Ctrl + 滚轮缩放", stack)
        self.assertIn("Ctrl - 缩小", stack)
        self.assertIn('addEventListener("wheel"', stack)
        self.assertIn("ctrlKey", stack)
        self.assertIn("{passive:false}", stack)
        self.assertNotIn("Stack review", stack)

        mpr = compose_mpr_viewer_html(
            "XuJing: tissue segmentation",
            json.dumps({"overlay_label": "Tissue labels"}, ensure_ascii=False),
        )
        self.assertIn("矢状面", mpr)
        self.assertIn("十字线", mpr)
        self.assertIn("组织标签", mpr)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", mpr)
        self.assertIn("planeAspect", mpr)
        self.assertIn("100cqh", mpr)
        self.assertIn("Ctrl + 滚轮缩放", mpr)
        self.assertIn("ctrlKey", mpr)
        self.assertIn("Math.max(0.25", mpr)
        self.assertNotIn("Multiplanar review", mpr)

        surface = compose_surface_viewer_html(
            "XuJing: interactive surface",
            json.dumps([{"label": "LH white"}], ensure_ascii=False),
        )
        self.assertIn("复位视角", surface)
        self.assertIn("左侧白质面", surface)
        self.assertIn("脑区着色", surface)
        self.assertIn("max-height: 72vh", surface)
        self.assertIn("flex-wrap: nowrap", surface)
        self.assertIn("Ctrl + 滚轮缩放", surface)
        self.assertNotIn("Reset View", surface)

    def test_restyle_rewrites_archived_english_html(self):
        html = compose_stack_viewer_html("Demo: all extraction stacks", '[{"name":"BTFE_a.nii.gz"}]')
        english = html.replace("播放", "Play").replace("交互阅片", "Stack review")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "01_extraction_interactive.html"
            path.write_text(english, encoding="utf-8")
            self.assertTrue(restyle_interactive_html(path))
            updated = path.read_text(encoding="utf-8")
            self.assertIn("播放", updated)
            self.assertIn("Demo · 脑提取", updated)
            self.assertNotIn("Stack review", updated)
            self.assertFalse(restyle_interactive_html(path))

    def test_legacy_run_urls_are_rewritten_to_migrated_paths(self):
        from agentic.legacy_paths import resolve_relocated_run_file, rewrite_legacy_file_urls
        from urllib.parse import quote

        old = "/mnt/sda/huangwei/projects/AutoRecon/CaoLi_registered_run02/dashboard/previews/01_extraction_interactive_assets/sequence_00/mask_0023.png"
        new = "/mnt/sda/huangwei/projects/AutoRecon/runs/legacy/CaoLi/registered_run02/dashboard/previews/01_extraction_interactive_assets/sequence_00/mask_0023.png"
        html = f'/api/file?path={quote(old, safe="")}'
        rewritten = rewrite_legacy_file_urls(html)
        self.assertIn("runs%2Flegacy%2FCaoLi%2Fregistered_run02", rewritten)
        self.assertNotIn("CaoLi_registered_run02", rewritten)
        if Path(new).is_file():
            self.assertEqual(resolve_relocated_run_file(Path(old)), Path(new).resolve())


if __name__ == "__main__":
    unittest.main()
