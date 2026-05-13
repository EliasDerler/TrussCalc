"""Validierungs-Suite: prüft jeden Datenblatt-Eintrag der gebündelten
Traversentypen, indem die Berechnung mit der entsprechenden Last-Konfiguration
am simply-supported Träger durchgeführt und mit dem Datenblatt-Wert verglichen
wird.

Aufruf:
    python -m scripts.validate_truss_data         # Konsolen-Tabelle
    python -m scripts.validate_truss_data --csv   # CSV in validation_log.csv
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trusscalc.core.models import (  # noqa: E402
    Project, TrussSection, Support, PointLoad, DistributedLoad, LoadType,
)
from trusscalc.core.calculator import calculate  # noqa: E402
from trusscalc.database import db_manager  # noqa: E402


def _build_project_for_row(truss_id: int, L: float, lt: LoadType,
                            load_kg: float) -> Project:
    """Baut ein simply-supported Test-Projekt entsprechend einer Datenblatt-Zeile."""
    project = Project(name="VAL", truss_type_id=truss_id)
    project.sections.append(TrussSection(
        id=str(uuid.uuid4()), position_m=0.0, length_m=L,
        truss_type_id=truss_id,
    ))
    project.supports.append(Support(
        id=str(uuid.uuid4()), position_m=0.0, max_force_kg=None,
    ))
    project.supports.append(Support(
        id=str(uuid.uuid4()), position_m=L, max_force_kg=None,
    ))

    if lt == LoadType.UDL:
        project.distributed_loads.append(DistributedLoad(
            id=str(uuid.uuid4()), start_m=0.0, end_m=L,
            load_kg_per_m=load_kg,
        ))
    elif lt == LoadType.CPL:
        project.point_loads.append(PointLoad(
            id=str(uuid.uuid4()), position_m=L / 2, load_kg=load_kg,
        ))
    elif lt == LoadType.THIRD:
        for x in (L / 3, 2 * L / 3):
            project.point_loads.append(PointLoad(
                id=str(uuid.uuid4()), position_m=x, load_kg=load_kg,
            ))
    elif lt == LoadType.QUARTER:
        for x in (L / 4, L / 2, 3 * L / 4):
            project.point_loads.append(PointLoad(
                id=str(uuid.uuid4()), position_m=x, load_kg=load_kg,
            ))
    elif lt == LoadType.FIFTH:
        for x in (L / 5, 2 * L / 5, 3 * L / 5, 4 * L / 5):
            project.point_loads.append(PointLoad(
                id=str(uuid.uuid4()), position_m=x, load_kg=load_kg,
            ))
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", action="store_true",
                        help="Schreibt zusätzlich CSV mit allen Rows")
    args = parser.parse_args()

    # Default-DB aus User-Home (wie main.py)
    home = os.path.expanduser("~")
    db_path = Path(home) / "TrussCalc" / "trusscalc.db"
    db_manager._DB_PATH = db_path

    truss_types = db_manager.list_truss_types()
    if not truss_types:
        print("Keine Traversen in DB.")
        return 1

    csv_rows: list[list[str]] = [
        ["Truss", "Span_m", "LoadType", "MaxLoad_kg",
         "Datasheet_mm", "Predicted_mm", "AbsDiff_mm", "RelDiff_%"]
    ]

    print(f"{'Truss':<22}{'L':>5}{'Type':>7}{'Load':>10}"
          f"{'DS_mm':>9}{'Pred':>9}{'Δabs':>8}{'Δ%':>8}")
    print("-" * 86)

    stats_per_truss: dict[str, list[float]] = {}
    overall_abs_diffs: list[float] = []

    for tt in truss_types:
        diffs_truss: list[float] = []
        for entry in sorted(tt.load_table,
                             key=lambda e: (e.load_type.value, e.span_m)):
            project = _build_project_for_row(
                tt.id, entry.span_m, entry.load_type, entry.max_load_kg,
            )
            try:
                result = calculate(project, tt)
            except Exception as exc:
                print(f"  FEHLER: {tt.name} {entry.load_type.value} "
                      f"L={entry.span_m}m: {exc}")
                continue

            pred = result.deflection.max_deflection_mm
            ds = entry.deflection_mm
            abs_diff = pred - ds
            rel_diff = abs_diff / ds * 100 if ds > 0 else 0.0
            diffs_truss.append(abs(rel_diff))
            overall_abs_diffs.append(abs(rel_diff))
            print(f"{tt.name:<22}{entry.span_m:>5.0f}"
                  f"{entry.load_type.value:>7}"
                  f"{entry.max_load_kg:>10.0f}"
                  f"{ds:>9.2f}{pred:>9.2f}{abs_diff:>+8.2f}{rel_diff:>+7.2f}%")
            csv_rows.append([
                tt.name, f"{entry.span_m:.1f}",
                entry.load_type.value, f"{entry.max_load_kg:.1f}",
                f"{ds:.2f}", f"{pred:.2f}",
                f"{abs_diff:+.3f}", f"{rel_diff:+.3f}",
            ])
        if diffs_truss:
            stats_per_truss[tt.name] = diffs_truss
            print(f"{'':<22}  → Truss: mean |Δ|={sum(diffs_truss)/len(diffs_truss):.2f}%  "
                  f"max |Δ|={max(diffs_truss):.2f}%  n={len(diffs_truss)}")
            print("-" * 86)

    print("\n" + "=" * 86)
    print("ZUSAMMENFASSUNG")
    print("=" * 86)
    for name, diffs in stats_per_truss.items():
        print(f"  {name:<22} mean |Δ|={sum(diffs)/len(diffs):>6.3f}%  "
              f"max |Δ|={max(diffs):>6.3f}%  n={len(diffs)}")
    if overall_abs_diffs:
        n = len(overall_abs_diffs)
        avg = sum(overall_abs_diffs) / n
        mx = max(overall_abs_diffs)
        ok = sum(1 for d in overall_abs_diffs if d <= 1.0)
        print(f"\nGESAMT ({n} Einträge):  mean |Δ|={avg:.3f}%  "
              f"max |Δ|={mx:.3f}%  ≤1%: {ok}/{n}")

    if args.csv:
        out = ROOT / "validation_log.csv"
        with open(out, "w", encoding="utf-8") as f:
            for row in csv_rows:
                f.write(";".join(row) + "\n")
        print(f"\nCSV: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
