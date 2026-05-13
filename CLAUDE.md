# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

Key dataclasses: `TrussType`, `LoadTableEntry`, `TrussSection`, `Support`, `PointLoad`, `DistributedLoad`, `Project`, `CalculationResult`, `SupportResult`, `DeflectionResult`.

`Project.total_length_m` is a computed property (sum of section lengths). `Support.has_max_force` guards utilization calculations.

### Database (`database/db_manager.py`)

SQLite via stdlib. DB path: `~/TrussCalc/trusscalc.db`, overridable via `TRUSSCALC_DB` env var. On first `init_db()`, if the DB is empty, `seed_default_truss_types_if_empty()` loads `trusscalc/resources/default_truss_types.json` (195 entries, 5 truss types). The `_resources_path()` helper resolves to either the dev-tree or `sys._MEIPASS` in a PyInstaller bundle.

### UI (`ui/`)

- **`main_window.py`**: LTSpice-style layout — library panel (left), `TrussCanvas` (center), properties panel (right). Calculation is triggered via F5 / toolbar button. `_generate_pdf()` shows `ReportMetadataDialog` first, then `QFileDialog`, then calls `pdf_generator.generate_report()`.
- **`canvas/truss_canvas.py`**: `QGraphicsView` with tool states (`CanvasTool` enum). Click handlers emit signals that open dialogs.
- **`canvas/canvas_items.py`**: `QGraphicsItem` subclasses for truss sections, supports, loads. Colors come from `core/color_rules.py` after calculation.

### PDF Report (`pdf/`)

- **`pdf_generator.py`**: ReportLab `BaseDocTemplate` with two frames (header-bleed frame for page 1, normal frame for subsequent pages). Uses `_NumberedCanvas` for footer/page numbers. Logo is loaded from `resources/logo_noisegate.pdf`, rendered at 150 DPI via PyMuPDF, then black→white inverted via PIL (black ink on white → white on dark header). Datasheet PDF pages are appended via PyMuPDF after ReportLab build.
- **`pdf/i18n.py`**: DE/EN string table, accessed via `tr(lang, key, **kwargs)`. All user-visible strings in reports must go through `tr()`.
- **`ui/dialogs/report_metadata_dialog.py`**: `ReportMetadataDialog` asks for language, project name, sub-project name, and creator email before PDF generation. Persists email + language in `QSettings("NoiseGate", "TrussCalc")`.

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
