# Four-backend full-pipeline acceptance

Subject: `AnHuiJing`  
Required stages: extraction → reconstruction → registration → tissue → ROI → surface

## Execution result

All four reconstruction backends completed the same six-stage pipeline and passed the strict artifact and provenance verifier.

| Backend | Technical result | Reconstruction shape / spacing | Registration QC | Mattes / GC |
|---|---|---|---|---|
| FROST | PASS | 182×178×154 / 0.6 mm | acceptable (`pyxz_fy`) | -0.408737 / -0.763876 |
| NeSVoR | PASS | 123×150×120 / 0.8 mm | acceptable (`pxyz_fnone`) | -0.411505 / -0.775260 |
| AutoSVRTK | PASS with QC warning | 141×170×150 / 0.8 mm | suspicious (`pxyz_fnone`) | -0.224568 / -0.155386 |
| NiftyMIC | PASS with QC warning | 129×132×155 / 0.8 mm | suspicious (`pzxy_fx`) | -0.169952 / -0.098869 |

“PASS” here means the program, six-stage control flow, provenance, geometry, labels, logs and required artifacts passed. It is not a clinical image-quality approval.

## Verified invariants

- Extraction source hashes, staging copies, masks and extraction-container SHA256 match.
- Reconstruction manifests are completed and their input/container fingerprints match current files.
- The canonical reconstruction symlink resolves to the selected backend's native output.
- Reconstruction and registered MRI are finite, nonempty 3D NIfTI volumes with valid affine matrices.
- Tissue and ROI outputs match the registered MRI grid and contain finite, nonempty integer labels.
- All 12 required surface, ROI-projection and statistics artifacts are present and nonempty.
- All six stage logs are present and nonempty.
- The current main pipeline script reuses all verified stages successfully with `--resume` for every backend.

## QC findings that must remain visible

- The shared extraction result has internal empty mask slices in `BTFE_..._201` (7–10) and `BTFE_..._501` (9, 11, 22).
- NeSVoR, AutoSVRTK and NiftyMIC explicitly report that BTFE is not an officially validated input sequence.
- NiftyMIC logged 8,148 pairs of zero-point/no-valid-point metric warnings, but completed three cycles and rejected only four low-NCC slices in the final cycle.
- AutoSVRTK and NiftyMIC atlas registrations are in the `suspicious` QC group; FROST and NeSVoR are `acceptable`.
- Surface generation completed for every backend, but topology is not clean. Remaining intersections were reported, especially for pial surfaces (AutoSVRTK up to 1,029; NiftyMIC up to 2,350), together with nonzero handles. These surfaces are experimental outputs and should not be treated as topology-correct clinical meshes.

## Evidence

- Machine-readable aggregate: `backend_validation/four_backend_acceptance.json`
- Per-backend strict evidence: `backend_validation/full_pipeline_<backend>/acceptance.json`
- Per-stage logs: `backend_validation/full_pipeline_<backend>/logs/`
- Backend manifests and logs: `backend_validation/full_pipeline_<backend>/outputs/reconstruction/<backend>/`
