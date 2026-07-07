# Format Import Test Plan

This project must treat imported files as editable project 3MF files, not as
sliced G-code bundles. The automated tests cover real slicer archive layouts and
the manual plan below is the release gate for real exported files.

## Automated Coverage

- PrusaSlicer/MMU: `Metadata/Slic3r_PE.config`,
  `Metadata/Slic3r_PE_model.config`, Prusa namespace attributes and MMU paint
  data are converted into Orca/Bambu project metadata.
- Cura: `Cura/quality_changes/global.cfg` plus multiple
  `Cura/quality_changes/extruder_N.cfg` files are parsed into material slots,
  temperatures, bed temperatures, nozzle diameter and colours.
- Geometry-only: a 3MF with only `3D/3dmodel.model` gets safe Generic PLA
  defaults and generated Orca sidecars.

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest tests
```

## Real Fixtures Checked

These public upstream files were inspected and converted during validation:

- PrusaSlicer official repository:
  `tests/data/seam_test_object.3mf`. Detected as PrusaSlicer, parsed
  `Metadata/Slic3r_PE.config`, rebuilt Orca sidecars, and stripped Prusa-only
  metadata.
- Cura official repository: `resources/meshes/creality_ender3.3mf`. This is a
  real Cura-distributed 3MF mesh asset without `Cura/quality_changes` slicer
  metadata, so it validates the geometry-only route rather than Cura project
  settings.

Cura project settings still need a real user-exported `.3mf` for final manual
acceptance, because the public Cura repository fixtures found here are platform
mesh assets, not saved workspace projects.

## Real File Gate

Before declaring a slicer version fully validated, export these project files
from the slicer itself and run them through the desktop app and the pytest
fixture harness:

- PrusaSlicer current stable: one PLA single-colour project, one two-material
  MMU project with object assignment, and one MMU painted project.
- Cura current stable: one single-extruder project, one dual-extruder project,
  and one project using `.fdm_material` material metadata.
- Geometry-only: a 3MF created by a CAD tool or mesh tool with no slicer
  metadata and at least two model objects.

For every converted output:

- Snapmaker Orca opens the file as a project without repair prompts.
- The output contains `Metadata/project_settings.config`,
  `Metadata/model_settings.config` and `Metadata/slice_info.config`.
- Foreign slicer metadata is removed from the output:
  `Metadata/Slic3r_PE*.config` and `Cura/**`.
- Material count, material names, colours and temperatures match the source
  intent where the source format exposes them.
- Object/extruder assignments survive for PrusaSlicer and Cura multi-material
  projects.
- Painted Prusa MMU geometry no longer contains `slic3rpe:*` attributes and
  carries Orca-readable paint metadata.
- Re-slicing in Snapmaker Orca succeeds, and generated tool changes match the
  expected material routing.
