# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
.venv/Scripts/python.exe main.py

# Install dependencies
pip install -r requirements.txt

# Validate all 195 datasheet entries against the FEM solver
.venv/Scripts/python.exe scripts/validate_truss_data.py

# Rebuild default_truss_types.json from raw PDFs (needs PaddleOCR)
.venv/Scripts/python.exe scripts/build_default_trusses.py

# Generate a test PDF report without the GUI
.venv/Scripts/python.exe -c "from trusscalc.pdf.pdf_generator import generate_report; ..."

# Database lives at %USERPROFILE%\TrussCalc\trusscalc.db (auto-created on first run)
# Override with: set TRUSSCALC_DB=path\to\custom.db
```

## Architecture Overview

TrussCalc is a PyQt6 desktop app for structural calculation of aluminium truss systems used in event technology (Veranstaltungstechnik). The UI language is **German**.

### Calculation Pipeline

The core calculation flows through three layers:

1. **`core/interpolator.py` — `LoadTableInterpolator`**
   - Reads the manufacturer's datasheet table (spans vs. max load + deflection)
   - Uses a **Timoshenko 2-parameter model** (EI + GA) fitted from all datasheet rows
   - `true_bending_ei()` → single global EI used by FEM (prefers CPL rows, falls back to longest span)
   - `stiffness_correction(load_type, L)` → post-FEM K-factor per sub-span to match datasheet deflections exactly
   - **Critical**: EI back-calculation in `_beam_ei()` subtracts self-weight contribution from the datasheet deflection before solving for EI — otherwise EI is contaminated at long spans.

2. **`core/fem_solver.py` — AnaStruct wrapper**
   - Builds a beam with 200 sub-elements + critical node points (supports, loads)
   - Iteratively removes supports with negative reaction (lift-off logic)
   - **AnaStruct `q_load` bug**: calling `q_load` multiple times on the same element overwrites (not adds). Fix: accumulate all UDL contributions per element in `element_q` dict, then call once per element.
   - AnaStruct sign convention: `uy > 0` = downward deflection

3. **`core/calculator.py` — Orchestrator**
   - Calls `fem_solver.solve()` with `ei_true = interp.true_bending_ei()`
   - Detects dominant load pattern (`_detect_load_pattern`) for K-factor selection
   - Applies `_post_correct_deflections()`: multiplies each deflection point by K(load_type, sub-span-length)
   - Returns `CalculationResult` with support reactions + corrected deflection curve

### Data Models (`core/models.py`)

Key dataclasses: `TrussType`, `LoadTableEntry`, `TrussSection`, `Support`, `PointLoad`, `DistributedLoad`, `Project`, `ProjectBundle`, `CalculationResult`, `SupportResult`, `DeflectionResult`.

`Project.total_length_m` is a computed property (sum of section lengths). `Support.has_max_force` guards utilization calculations.

`ProjectBundle` is the current multi-tab project container. Each `Project` inside `ProjectBundle.subprojects` is one Sub-Projekt. A Sub-Projekt can contain multiple independent `TrussSystem` entries; each system has its own truss type, geometry, loads, and calculation result. `Project.view_mode` is `"plan"` or `"compare"`: Planen shows `plan_system_id` only, Vergleichen shows `compare_system_ids` and allows visual X/Y system placement. Switching Planen→Vergleichen copies the plan system into the comparison set; switching back can keep the existing plan system or import a copied comparison system. Treat the active tab as a sub-project editor and the active system as the editing target; do not reintroduce global single-project assumptions in UI, persistence, or PDF code.

Tower tabs are `Project.kind == "tower"`. Tower V3 stores the editable drawing in `Project.tower_assembly` (`TowerAssembly`: one foundation snapshot, vertical `TowerAssemblySection` stack, horizontal `TowerAssemblyCantilever` arms, and horizontal/vertical `TowerAssemblyLoad` point forces with `x_m` positions). `core/tower_assembly.py` adapts this drawing to the existing `TowerInput` for `core/tower_calculator.py` and PDF export. Keep this adapter boundary intact: calculator/PDF can continue consuming `TowerInput`, while the UI/persistence source of truth is `tower_assembly`.

### Database (`database/db_manager.py`)

SQLite via stdlib. DB path: `~/TrussCalc/trusscalc.db`, overridable via `TRUSSCALC_DB` env var. On first `init_db()`, if the DB is empty, `seed_default_truss_types_if_empty()` loads `trusscalc/resources/default_truss_types.json` (195 entries, 5 truss types). The `_resources_path()` helper resolves to either the dev-tree or `sys._MEIPASS` in a PyInstaller bundle.

Tower foundations live in SQLite table `tower_foundations` and are manually maintained through the left library panel. There are intentionally no default foundation entries. When a foundation is placed in a Tower tab, the project stores a snapshot (`tower_assembly.foundation` + connector data), so old projects remain reproducible even if the DB library entry later changes.

### UI (`ui/`)

- **`main_window.py`**: LTSpice-style layout — library panel (left), `QTabWidget` + `TrussCanvas` (center), properties panel (right). Calculation is triggered via F5 / toolbar button and belongs only to the active Sub-Projekt. `_generate_pdf()` exports all calculated Sub-Projekte through `pdf_generator.generate_project_report()`; `generate_report()` remains the public single-report compatibility API. The PDF metadata dialog asks for project-level metadata only; Sub-Projekt names come from the tab names.
- **`canvas/truss_canvas.py`**: `QGraphicsView` with tool states (`CanvasTool` enum). Click handlers emit signals that open dialogs.
- **`canvas/canvas_items.py`**: `QGraphicsItem` subclasses for truss sections, supports, loads. Colors come from `core/color_rules.py` after calculation.
- **`panels/tower_panel.py`**: Tower V3 editor. Users place one foundation from the Fundamentbibliothek, append vertical truss sections, add horizontal Auskragungen left/right, place horizontal/vertical point forces, then press F5. Middle mouse pans, mouse wheel zooms. F5 validates the drawing, asks only remaining calculation data, builds `TowerInput`, and calls the existing tower calculator. V3 calculation supports only one truss type across vertical tower and all arms; block mixed truss types with a clear user message. Auskragungen are a Vorbemessungs input: their self-weight and vertical point loads become equivalent eccentric payload moments, and their local cantilever deflection is estimated separately from datasheet EI. Horizontalkräfte store their clicked side in `TowerAssemblyLoad.x_m`; left-side forces push to the right, right-side forces push to the left, and the adapter combines them into a signed horizontal moment. This is still not a full 2D frame/FEM proof. Auskragung heights describe the top edge of the horizontal truss, not its centerline.

### PDF Report (`pdf/`)

- **`pdf_generator.py`**: ReportLab `BaseDocTemplate` with two frames (header-bleed frame for page 1, normal frame for subsequent pages). Uses `_NumberedCanvas` for footer/page numbers. Logo is loaded from `resources/logo_noisegate.pdf`, rendered at 150 DPI via PyMuPDF, then black→white inverted via PIL (black ink on white → white on dark header). Datasheet PDF pages are appended via PyMuPDF after ReportLab build.
- **`pdf/i18n.py`**: DE/EN string table, accessed via `tr(lang, key, **kwargs)`. All user-visible strings in reports must go through `tr()`.
- **`ui/dialogs/report_metadata_dialog.py`**: `ReportMetadataDialog` asks for language, project name, sub-project name, and creator email before PDF generation. Persists email + language in `QSettings("NoiseGate", "TrussCalc")`.

### Project Persistence

- `.tcproj` files are format version `6` and contain `data.subprojects[].systems[]` for beam tabs plus `data.subprojects[].tower_assembly` for Tower tabs.
- Legacy files without `subprojects` or without `systems` are automatically migrated by `load_project_from_file()`.
- Legacy v4 form-based Tower tabs are migrated by `assembly_from_tower_input()` into one foundation snapshot, one vertical section, and equivalent point loads.
- Always call `_commit_active_subproject_state()` before saving, exporting PDF, or switching away from the active tab.
- `save_project()` / `load_project()` in `database/db_manager.py` use the same JSON structure as `.tcproj`.

### Copy / Mirror Interaction

- `Ctrl+C` immediately starts copy mode for the current selection.
- `Ctrl+V` restarts placement using the stored copy template.
- Right-click and `Esc` cancel only the active placement preview; the stored copy template remains available.
- `Ctrl+M` copies and mirrors the current selection around the active Sub-Projekt's total truss length.
- Sub-Projekt tabs are movable by drag & drop. When handling tab order, reorder `ProjectBundle.subprojects` and all parallel arrays (`_subproject_truss_types`, `_subproject_results`, `_subproject_undo_stacks`, `_subproject_redo_stacks`) together.
- Multiple systems inside one tab are statically independent. Planen displays only `plan_system_id`; Vergleichen displays `compare_system_ids`, keeps stored `canvas_x_m`/`canvas_y_m` offsets, and marks PDF chapters with `Vergleich` below the Sub-Projekt/System name. Copy/mirror/delete operate on the active system only.
- Use `calculator.project_from_system()` when an existing single-system path such as FEM or PDF needs a classic `Project` view.

### Color Rules (`core/color_rules.py`)

After calculation, `classify_supports()` assigns: blue (lifted), red (>100% utilization), yellow (>80%), green (removable without exceeding 20% of allowable deflection), white (OK). `classify_deflection()` assigns: red (current > limit), yellow (current × 1.2 > limit), green (safe).

## Critical Bugs Fixed (don't reintroduce)

- **AnaStruct q_load overwrite**: Never call `ss.q_load()` multiple times on the same element ID. Accumulate in a dict first.
- **EI self-weight contamination**: `_beam_ei()` must include `c_self * self_weight` term when back-calculating EI from datasheet deflections.
- **K-factor EI mismatch**: `stiffness_correction()` must use `self.true_bending_ei()` (global CPL-based EI), not a load-type-specific EI — because the FEM runs with the global EI.
- **PyMuPDF save-to-same-path**: Save to `.tmp` then `os.replace()` when appending datasheet pages.
- **ReportLab style alias clash**: Use namespaced style names (`tc_h1`, `tc_body`, etc.) to avoid conflicts with default style aliases.

## Deployment

No PyInstaller `.spec` file exists yet. The `_resources_path()` function in `db_manager.py` already handles `sys._MEIPASS`. Resources to bundle: `trusscalc/resources/` (default_truss_types.json, logo_noisegate.pdf, schema.sql).

## Codex Working Copy

- Codex development must happen in `C:\Claude_Projekte\TrussCalc_Codex`.
- Do not edit the original Claude project at `C:\Claude_Projekte\TrussCalc`.
- The current Codex copy intentionally contains uncommitted and untracked work from the copied project state; preserve unrelated changes.
- If Git reports Windows safe-directory warnings, use per-command `git -c safe.directory=C:/Claude_Projekte/TrussCalc_Codex ...`.

## Current Improvement Focus

The first improvement area is the PDF output. The visual reference is:

`C:\Users\elias\Downloads\Design2_NoiseGate_Branded_DE.pdf`

Maintain the public PDF entrypoint:

```python
from trusscalc.pdf.pdf_generator import generate_report
```

The report must keep DE/EN support through `trusscalc/pdf/i18n.py`; all user-visible report text should go through `tr(lang, key, **kwargs)`.

### PDF Report Requirements

- Match the Design2 NoiseGate report as closely as practical using ReportLab.
- Render the NoiseGate logo as white artwork on the dark header without a white background box.
- Keep page 1 focused on: dark header, metadata row, support/deflection cards, and the static-system drawing in a light framed card.
- Keep page 2 focused on: support reactions table, deflection analysis, field cards, bill of materials, important notice, and signature areas.
- Multi-Sub-Projekt PDFs should place all Sub-Projekt chapters first, then a final combined bill-of-materials page with Sub-Projekt names, notice, and signature fields, and only then append datasheets.
- Preserve datasheet appending with PyMuPDF by saving to a temporary `.tmp` file and replacing the final path via `os.replace()`.
- Keep ReportLab styles namespaced or locally managed to avoid collisions with default style aliases.

### PDF Smoke Test Pattern

Use a non-GUI smoke test with:

- EuroTruss XD from `trusscalc/resources/default_truss_types.json`
- 18 m total truss length
- Supports at 0 m, 9 m, and 18 m
- Point loads of 500 kg at 4.5 m and 13.5 m
- Expected output: 2 report pages before datasheet append, with readable header, support cards, static schema, reaction table, deflection analysis, part list, notice, and signature blocks.

Recommended verification commands:

```bash
.venv/Scripts/python.exe scripts/validate_truss_data.py
.venv/Scripts/python.exe -c "from trusscalc.pdf.pdf_generator import generate_report; ..."
```

When checking layout changes, render the first two PDF pages to PNG with PyMuPDF and visually compare them against `Design2_NoiseGate_Branded_DE.pdf`.
