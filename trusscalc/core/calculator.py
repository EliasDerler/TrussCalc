"""Berechnungs-Orchestrator: verbindet Interpolation, FEM und Farbregeln."""
from typing import Optional

from trusscalc.core.models import (
    TrussType, Project, CalculationResult, SupportResult, DeflectionResult,
    LoadType,
)
from trusscalc.core.interpolator import LoadTableInterpolator
from trusscalc.core import fem_solver
from trusscalc.core import color_rules


def _detect_load_pattern(project: Project) -> Optional[LoadType]:
    """Versucht, das dominierende Lastmuster zu erkennen, damit EI
    aus der passenden Datenblatt-Zeile kalibriert werden kann."""
    span = project.total_length_m
    if span <= 0:
        return None

    has_pl = bool(project.point_loads)
    has_dl = bool(project.distributed_loads)

    # Reine Streckenlast → UDL
    if has_dl and not has_pl:
        return LoadType.UDL

    # Nur Punktlasten ohne Streckenlast: spezifische Muster prüfen
    if has_pl and not has_dl:
        positions = sorted(p.position_m for p in project.point_loads)
        n = len(positions)
        tol = max(0.05 * span, 0.1)  # Toleranz für „symmetrisch verteilt"
        cluster_tol = 0.10 * span     # mehrere Lasten "an einer Stelle"

        # Mehrere Lasten dicht beieinander: als äquivalente Einzellast werten
        if n >= 1 and (max(positions) - min(positions)) <= cluster_tol:
            avg = sum(positions) / n
            if abs(avg - span / 2) <= tol:
                return LoadType.CPL  # nahe Mitte = CPL-Pattern

        # 1 Last in der Mitte → CPL
        if n == 1 and abs(positions[0] - span / 2) <= tol:
            return LoadType.CPL
        # 2 Lasten bei L/3 und 2L/3 → 1/3-Punkt
        if n == 2 and abs(positions[0] - span / 3) <= tol \
                and abs(positions[1] - 2 * span / 3) <= tol:
            return LoadType.THIRD
        # 3 Lasten bei L/4, L/2, 3L/4 → 1/4-Punkt
        if n == 3 and abs(positions[0] - span / 4) <= tol \
                and abs(positions[1] - span / 2) <= tol \
                and abs(positions[2] - 3 * span / 4) <= tol:
            return LoadType.QUARTER
        # 4 Lasten bei L/5..4L/5 → 1/5-Punkt
        if n == 4 and all(
            abs(positions[i] - (i + 1) * span / 5) <= tol for i in range(4)
        ):
            return LoadType.FIFTH

    # Mischung oder unklar → kein eindeutiges Muster
    return None


def calculate(project: Project, truss_type: TrussType) -> CalculationResult:
    warnings: list[str] = []

    if not project.supports:
        return CalculationResult(
            support_results=[], deflection=_empty_deflection(),
            total_load_kg=0, self_weight_kg=0,
            warnings=["Kein Auflager definiert."], is_valid=False,
        )

    if not project.sections:
        return CalculationResult(
            support_results=[], deflection=_empty_deflection(),
            total_load_kg=0, self_weight_kg=0,
            warnings=["Keine Traversenabschnitte definiert."], is_valid=False,
        )

    total_length = project.total_length_m
    interp = LoadTableInterpolator(truss_type)

    # Eigengewicht
    self_weight_kg_per_m: Optional[float] = None
    if truss_type.has_weight:
        self_weight_kg_per_m = truss_type.weight_per_meter_kg
    else:
        warnings.append(
            "Eigengewicht der Traverse nicht im Datenblatt angegeben – "
            "wird in der Berechnung nicht berücksichtigt."
        )

    # Lastpattern erkennen (für Datenblatt-Kalibrierung)
    pattern = _detect_load_pattern(project)

    # Echtes Biege-EI (konstant über die gesamte Traverse) – aus den
    # biegungs-limitierten Datenblatt-Einträgen. Damit liefert die FEM
    # physikalisch konsistente Reaktionen auch in statisch unbestimmten
    # Systemen, weil EI im realen Querschnitt konstant ist.
    ei_true = interp.true_bending_ei()
    if ei_true is None:
        warnings.append(
            "Keine Lasttabellen-Daten im Datenblatt – EI kann nicht bestimmt werden."
        )
        return CalculationResult(
            support_results=[], deflection=_empty_deflection(),
            total_load_kg=0, self_weight_kg=0,
            warnings=warnings, is_valid=False,
        )

    # FEM lösen mit konstantem echten EI
    s_results, defl_result = fem_solver.solve(
        sections=project.sections,
        supports=project.supports,
        point_loads=project.point_loads,
        distributed_loads=project.distributed_loads,
        ei_n_m2=ei_true,
        self_weight_kg_per_m=self_weight_kg_per_m,
        total_length_m=total_length,
    )

    # Empirische Durchbiegungs-Kalibrierung pro Sub-Feld auf Datenblatt-
    # Werte. Reaktionen und Momente bleiben unverändert (sind physikalisch
    # korrekt aus der FEM). Nur die Durchbiegungs-Magnitude wird pro
    # Sub-Feld so skaliert, dass sie zum empirischen Datenblatt-Verhalten
    # bei dieser Sub-Spannweite passt.
    calib_load_type = pattern or LoadType.CPL
    defl_result = _post_correct_deflections(
        defl_result, project, interp, calib_load_type, total_length,
    )

    # Zulässige Durchbiegung aus Datenblatttabelle
    allowable = interp.allowable_deflection_mm(total_length)
    if allowable is None:
        span_range = interp.span_range
        if span_range:
            warnings.append(
                f"Stützweite {total_length:.1f} m außerhalb Datenblatttabelle "
                f"({span_range[0]:.0f}–{span_range[1]:.0f} m). "
                "Durchbiegungsgrenzwert nicht verfügbar."
            )
    else:
        # Warnen, wenn die Spannweite über die größte tabellierte Stützweite
        # hinausgeht – Werte beruhen dann auf Extrapolation und sind
        # möglicherweise ungenau.
        max_table_span = 0.0
        min_table_span = float("inf")
        for _lt, (sp, _ld, _df) in interp._tables.items():
            if len(sp) > 0:
                max_table_span = max(max_table_span, float(sp[-1]))
                min_table_span = min(min_table_span, float(sp[0]))
        if max_table_span > 0 and total_length > max_table_span * 1.02:
            warnings.append(
                f"Stützweite {total_length:.1f} m liegt OBERHALB der "
                f"Datenblatt-Tabelle (max {max_table_span:.0f} m). "
                "Durchbiegung und Grenzwerte sind extrapoliert und können "
                "deutlich von der Realität abweichen – Ergebnisse mit Vorsicht "
                "verwenden!"
            )
        elif min_table_span < float("inf") and total_length < min_table_span * 0.98:
            warnings.append(
                f"Stützweite {total_length:.1f} m liegt UNTERHALB der "
                f"Datenblatt-Tabelle (min {min_table_span:.0f} m). "
                "Bei sehr kurzen Spannweiten dominieren oft andere "
                "Grenzkriterien (Schub, Verbindungen) – Ergebnisse mit "
                "Vorsicht verwenden!"
            )
    defl_result.allowable_deflection_mm = allowable

    # Gesamtlasten
    total_point = sum(p.load_kg for p in project.point_loads)
    total_dist = sum(d.total_load_kg for d in project.distributed_loads)
    total_load = total_point + total_dist
    self_weight = (self_weight_kg_per_m or 0.0) * total_length

    return CalculationResult(
        support_results=s_results,
        deflection=defl_result,
        total_load_kg=total_load,
        self_weight_kg=self_weight,
        warnings=warnings,
        is_valid=True,
    )


def _sub_span_length_at(x: float, supports_x: list[float],
                         total_length: float) -> float:
    """Liefert die relevante Sub-Spannweite an Position x:
    Distanz zwischen den beiden Auflagern, die x einschließen. Für
    Kragträger-Bereiche (Last außerhalb der Auflager) wird die Länge des
    Kragarms zurückgegeben."""
    if not supports_x:
        return total_length
    sups = sorted(supports_x)
    if x <= sups[0]:
        return max(sups[0], 1e-6)
    if x >= sups[-1]:
        return max(total_length - sups[-1], 1e-6)
    for i in range(len(sups) - 1):
        if sups[i] <= x <= sups[i + 1]:
            return sups[i + 1] - sups[i]
    return total_length


def _post_correct_deflections(
    defl_result: DeflectionResult,
    project: Project,
    interp: LoadTableInterpolator,
    load_type: LoadType,
    total_length: float,
) -> DeflectionResult:
    """Skaliert die FEM-Durchbiegung pro Sub-Feld so, dass sie zum Datenblatt-
    Verhalten bei dieser Sub-Spannweite passt. Reaktionen werden nicht
    angetastet – die FEM hat sie mit physikalisch konstantem EI berechnet,
    sie sind also bereits korrekt."""
    if not defl_result.positions_m or not defl_result.deflections_mm:
        return defl_result

    supports_x = [s.position_m for s in project.supports]
    corrected: list[float] = []
    for x, d in zip(defl_result.positions_m, defl_result.deflections_mm):
        L_sub = _sub_span_length_at(x, supports_x, total_length)
        K = interp.stiffness_correction(load_type, L_sub)
        corrected.append(d * K)

    abs_corr = [abs(v) for v in corrected]
    max_idx = max(range(len(abs_corr)), key=lambda i: abs_corr[i])
    return DeflectionResult(
        positions_m=list(defl_result.positions_m),
        deflections_mm=corrected,
        max_deflection_mm=abs_corr[max_idx],
        max_deflection_position_m=defl_result.positions_m[max_idx],
        allowable_deflection_mm=defl_result.allowable_deflection_mm,
    )


def _superposition_deflection_unused(
    project: Project,
    interp: LoadTableInterpolator,
    pattern: Optional[LoadType],
    self_weight_kg_per_m: Optional[float],
    span: float,
) -> Optional[float]:
    """Deprecated – ersetzt durch das physikalisch konsistente Verfahren
    'FEM mit echtem EI + Post-Korrektur pro Sub-Feld'. Wird nicht mehr aufgerufen."""
    if pattern is None:
        return None
    sups = sorted(project.supports, key=lambda s: s.position_m)
    if len(sups) != 2:
        return None
    if abs(sups[0].position_m) > 0.05 or abs(sups[-1].position_m - span) > 0.05:
        return None

    if pattern == LoadType.UDL:
        if not project.distributed_loads:
            return None
        # Nur anwenden, wenn die Streckenlast(en) (fast) die ganze Spannweite
        # abdecken. Bei Teil-UDL würde die Mittelung w = Σ kg / L die zentrale
        # Konzentration ignorieren und die Durchbiegung unterschätzen.
        covered = sum(d.length_m for d in project.distributed_loads)
        if covered < 0.95 * span:
            return None  # Teil-UDL → FEM-Ergebnis direkt verwenden
        total_load = sum(d.total_load_kg for d in project.distributed_loads)
        w = total_load / span
        return interp.predicted_deflection_mm(LoadType.UDL, w, span)

    if pattern == LoadType.CPL:
        # Eine oder mehrere Lasten an/nahe der Mitte: als äquivalente Einzellast
        total_kg = sum(p.load_kg for p in project.point_loads)
        return interp.predicted_deflection_mm(LoadType.CPL, total_kg, span)

    if pattern in (LoadType.THIRD, LoadType.QUARTER, LoadType.FIFTH):
        # Datenblatt-Wert ist je Punkt definiert → Mittelwert je Punkt verwenden
        n = len(project.point_loads)
        if n == 0:
            return None
        avg = sum(p.load_kg for p in project.point_loads) / n
        return interp.predicted_deflection_mm(pattern, avg, span)

    return None


def _empty_deflection() -> DeflectionResult:
    return DeflectionResult(
        positions_m=[], deflections_mm=[],
        max_deflection_mm=0.0, max_deflection_position_m=0.0,
    )
