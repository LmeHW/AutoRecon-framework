from __future__ import annotations


TOOL_REGISTRY: dict[str, dict[str, object]] = {
    "input_check": {
        "description": "Validate input directories, 3D stacks, and requested parameters.",
        "expected_artifacts": [],
        "capability_level": "stable",
        "requires": [], "stage": 0, "visualization": "status",
    },
    "brain_extraction": {
        "description": "Run 2D fetal brain extraction on input stacks.",
        "expected_artifacts": ["staging_subject_dir", "extraction_seg_dir"],
        "capability_level": "stable",
        "requires": ["input_check"], "stage": 1, "visualization": "stack_viewer",
    },
    "frost_reconstruction": {
        "description": "Reconstruct 3D fetal brain MRI from extracted stacks.",
        "expected_artifacts": ["recon_image"],
        "capability_level": "stable",
        "requires": ["brain_extraction"], "stage": 2, "visualization": "mpr",
    },
    "nesvor_reconstruction": {
        "description": "Reconstruct 3D fetal brain MRI with NeSVoR.",
        "expected_artifacts": ["recon_image"], "capability_level": "experimental",
        "requires": ["brain_extraction"], "stage": 2, "visualization": "mpr",
    },
    "autosvrtk_reconstruction": {
        "description": "Reconstruct 3D fetal brain MRI with auto-proc-svrtk.",
        "expected_artifacts": ["recon_image"], "capability_level": "experimental",
        "requires": ["brain_extraction"], "stage": 2, "visualization": "mpr",
    },
    "niftymic_reconstruction": {
        "description": "Reconstruct 3D fetal brain MRI with NiftyMIC.",
        "expected_artifacts": ["recon_image"], "capability_level": "experimental",
        "requires": ["brain_extraction"], "stage": 2, "visualization": "mpr",
    },
    "reconstruction_comparison": {
        "description": "Score multiple reconstruction backends on the same extracted stacks; ranking is automatic-only.",
        "expected_artifacts": ["reconstruction_comparison"],
        "capability_level": "experimental",
        "requires": ["frost_reconstruction|nesvor_reconstruction|autosvrtk_reconstruction|niftymic_reconstruction"],
        "stage": 2, "visualization": "table",
    },
    "rigid_registration": {
        "description": "Register reconstructed MRI to an atlas/template.",
        "expected_artifacts": ["registration_root"],
        "capability_level": "experimental",
        "requires": ["frost_reconstruction|nesvor_reconstruction|autosvrtk_reconstruction|niftymic_reconstruction"],
        "stage": 3, "visualization": "mpr",
    },
    "tissue_segmentation": {
        "description": "Run 3D tissue segmentation.",
        "expected_artifacts": ["tissue_image"],
        "capability_level": "stable",
        "requires": ["rigid_registration"], "stage": 4, "visualization": "label_overlay",
    },
    "ga_atlas_roi_warp": {
        "description": "Select gestational-age atlas and warp ROI labels.",
        "expected_artifacts": ["roi_image"],
        "capability_level": "experimental",
        "requires": ["rigid_registration"], "stage": 5, "visualization": "label_overlay",
    },
    "segresnet_roi": {
        "description": "Run direct ROI segmentation model.",
        "expected_artifacts": ["roi_image"],
        "capability_level": "experimental",
        "requires": ["rigid_registration"], "stage": 5, "visualization": "label_overlay",
    },
    "surface_reconstruction": {
        "description": "Generate white, pial, inflated surfaces and surface stats.",
        "expected_artifacts": ["surface_subject_dir", "surface_stats_dir"],
        "capability_level": "experimental",
        "requires": ["tissue_segmentation", "ga_atlas_roi_warp|segresnet_roi"], "stage": 6, "visualization": "surface",
    },
    "roi_volume_statistics": {
        "description": "Collect ROI/surface metric files and summarize availability.",
        "expected_artifacts": ["metrics_files"],
        "capability_level": "stable",
        "requires": ["ga_atlas_roi_warp|segresnet_roi"], "stage": 7, "visualization": "table",
    },
    "visualization_dashboard": {
        "description": "Expose run state, previews, MPR viewers, logs, and report in a dashboard.",
        "expected_artifacts": ["dashboard_dir", "dashboard_state"],
        "capability_level": "stable",
        "requires": ["input_check"], "stage": 8, "visualization": "dashboard",
    },
}


def assert_known_tool(tool: str) -> None:
    if tool not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {tool}")


STEP_TO_TOOL = {
    "input_check": "input_check", "extraction": "brain_extraction",
    "reconstruction": "frost_reconstruction", "comparison": "reconstruction_comparison",
    "registration": "rigid_registration",
    "tissue": "tissue_segmentation", "roi": "ga_atlas_roi_warp",
    "surface": "surface_reconstruction", "metrics": "roi_volume_statistics",
    "visualization": "visualization_dashboard",
}
TOOL_TO_STEP = {value: key for key, value in STEP_TO_TOOL.items()}
TOOL_TO_STEP.update({
    "nesvor_reconstruction": "reconstruction",
    "autosvrtk_reconstruction": "reconstruction",
    "niftymic_reconstruction": "reconstruction",
})
