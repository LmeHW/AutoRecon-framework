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
    refreshed_interactive_html,
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
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", stack)
        self.assertIn("矢状面", stack)
        self.assertIn("冠状面", stack)
        self.assertIn("轴状面", stack)
        self.assertIn("useTriplane", stack)
        self.assertIn("inferOrientation", stack)
        self.assertIn("sequencesFor", stack)
        self.assertIn("DEFAULT_VIEW_PX=420", stack)
        self.assertIn("naturalWidth", stack)
        self.assertIn("MIN_ZOOM=0.25", stack)
        self.assertNotIn("function zoomAt(", stack)
        self.assertIn("Ctrl + 滚轮缩放", stack)
        self.assertIn("Alt + 拖拽旋转", stack)
        self.assertIn("data-rotate", stack)
        self.assertIn("旋转", stack)
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
        self.assertIn('h:"y",v:"z",invertV:true', mpr)
        self.assertIn('h:"x",v:"z",invertV:true', mpr)
        self.assertIn('h:"x",v:"y",invertV:false', mpr)
        self.assertIn("(w*sy)/(h*sz)", mpr)
        self.assertIn("(w*sx)/(h*sz)", mpr)
        self.assertNotIn('h:"z",v:"y"', mpr)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", mpr)
        self.assertIn("planeAspect", mpr)
        self.assertIn("100cqh", mpr)
        self.assertIn("Ctrl + 滚轮缩放", mpr)
        self.assertIn("Alt + 拖拽旋转", mpr)
        self.assertIn('id="rotate"', mpr)
        self.assertIn("旋转 90°", mpr)
        self.assertIn("view-transform", mpr)
        self.assertIn("function applyLayerView(", mpr)
        self.assertIn("function unrotatePoint(", mpr)
        self.assertIn("rotations", mpr)
        self.assertIn("ctrlKey", mpr)
        self.assertIn("Math.max(0.25", mpr)
        self.assertIn('id="overlayOpacity"', mpr)
        self.assertIn('value="0"', mpr)
        self.assertNotIn('value="28"', mpr)
        self.assertIn("1-Number(q(\"overlayOpacity\")?.value ?? 0)/100", mpr)
        self.assertIn('q("overlayOpacity").oninput=applyOverlayOpacity', mpr)
        self.assertIn("function applyOverlayOpacity()", mpr)
        self.assertNotIn("oninput=render()", mpr)
        self.assertNotIn("||28", mpr)
        self.assertNotIn("Multiplanar review", mpr)

        surface = compose_surface_viewer_html(
            "XuJing: interactive surface",
            json.dumps([{"label": "LH white"}], ensure_ascii=False),
        )
        self.assertIn("复位视角", surface)
        self.assertIn("拖拽旋转视角", surface)
        self.assertIn("左侧白质面", surface)
        self.assertIn("脑区着色", surface)
        self.assertIn("max-height: 72vh", surface)
        self.assertIn("flex-wrap: nowrap", surface)
        self.assertIn("Ctrl + 滚轮缩放", surface)
        self.assertNotIn("Reset View", surface)

    def test_archived_mpr_opacity_slider_is_rewritten_to_live_update(self):
        mpr = compose_mpr_viewer_html(
            "XuJing: tissue segmentation",
            json.dumps({
                "dims": {"x": 2, "y": 2, "z": 2},
                "spacing": [1, 1, 1],
                "has_overlay": True,
                "overlay_label": "Tissue labels",
                "planes": {},
            }),
        )
        stale = mpr.replace(
            'q("overlayOpacity").oninput=applyOverlayOpacity',
            'q("overlayOpacity").oninput=render()',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "04_tissue_interactive.html"
            path.write_text(stale, encoding="utf-8")
            served = refreshed_interactive_html(path, stale.encode("utf-8"))
            self.assertIn(b'q("overlayOpacity").oninput=applyOverlayOpacity', served)
            self.assertNotIn(b"oninput=render()", served)
            self.assertEqual(refreshed_interactive_html(path, served), served)

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

    def test_extraction_mask_uses_brand_red_with_alpha(self):
        import numpy as np
        from PIL import Image
        from pipeline.vis.pipeline_dashboard import (
            EXTRACTION_MASK_ALPHA,
            EXTRACTION_MASK_RGB,
            LABEL_OVERLAY_ALPHA,
            make_overlay,
            save_mask_png,
        )

        self.assertEqual(EXTRACTION_MASK_RGB, (157, 24, 34))
        self.assertEqual(EXTRACTION_MASK_ALPHA, 0.45)
        self.assertEqual(LABEL_OVERLAY_ALPHA, 1.0)
        stack = compose_stack_viewer_html("Demo · 脑提取", "[]")
        self.assertIn('value="45"', stack)
        self.assertIn("不透明度", stack)
        self.assertNotIn('value="100"', stack)

        from pipeline.vis.pipeline_dashboard import pixel_aspect, physical_plane_size

        self.assertAlmostEqual(pixel_aspect(0.78125, 6.5), 0.78125 / 6.5)
        self.assertEqual(pixel_aspect(0.78125, 0.78125), 1.0)
        self.assertAlmostEqual(physical_plane_size((180, 28), 0.78125, 6.5)[0], 28 * 6.5)

        plane = np.zeros((4, 4), dtype="int32")
        plane[1:3, 1:3] = 1
        try:
            rgb, alpha = make_overlay(plane, "mask")
        except ModuleNotFoundError:
            rgb = alpha = None
        if rgb is not None:
            self.assertTrue(np.allclose(rgb[1, 1], np.asarray(EXTRACTION_MASK_RGB) / 255.0))
            self.assertAlmostEqual(float(alpha[1, 1]), EXTRACTION_MASK_ALPHA)
            self.assertEqual(float(alpha[0, 0]), 0.0)
            try:
                label_rgb, label_alpha = make_overlay(plane, "label")
            except ModuleNotFoundError:
                label_rgb = label_alpha = None
            if label_alpha is not None:
                self.assertAlmostEqual(float(label_alpha[1, 1]), LABEL_OVERLAY_ALPHA)
                self.assertEqual(float(label_alpha[0, 0]), 0.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mask.png"
            save_mask_png(path, plane)
            pixels = np.asarray(Image.open(path).convert("RGBA"))
            self.assertEqual(tuple(pixels[1, 1]), (*EXTRACTION_MASK_RGB, 255))
            self.assertEqual(tuple(pixels[0, 0]), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
