"""Farblogik für Auflager und Durchbiegungsmarkierungen nach der Berechnung."""
from dataclasses import dataclass
from typing import Optional

from trusscalc.core.models import SupportResult, DeflectionResult, Support
from trusscalc.core.fem_solver import solve


@dataclass
class SupportColor:
    support_id: str
    color: str          # "blue" | "green" | "yellow" | "red"
    tooltip: str


@dataclass
class DeflectionColor:
    color: str          # "green" | "yellow" | "red"
    tooltip: str


def classify_supports(
    support_results: list[SupportResult],
    deflection: DeflectionResult,
    sections,
    point_loads,
    distributed_loads,
    ei_n_m2: float,
    self_weight_kg_per_m: Optional[float],
    total_length_m: float,
) -> list[SupportColor]:
    colors: list[SupportColor] = []

    for sr in support_results:
        if not sr.is_active or sr.reaction_kg <= 0:
            colors.append(SupportColor(
                support_id=sr.support.id,
                color="blue",
                tooltip=f"Auflager abgehoben (Reaktion: {sr.reaction_kg:.1f} kg)",
            ))
            continue

        # Rot / Gelb nach Auslastung
        if sr.support.has_max_force:
            if sr.utilization > 1.0:
                colors.append(SupportColor(
                    support_id=sr.support.id,
                    color="red",
                    tooltip=(
                        f"ÜBERLASTET: {sr.reaction_kg:.1f} kg > "
                        f"{sr.support.max_force_kg:.1f} kg ({sr.utilization*100:.0f}%)"
                    ),
                ))
                continue
            if sr.utilization > 0.8:
                colors.append(SupportColor(
                    support_id=sr.support.id,
                    color="yellow",
                    tooltip=(
                        f"Warnung: {sr.reaction_kg:.1f} kg / "
                        f"{sr.support.max_force_kg:.1f} kg ({sr.utilization*100:.0f}%)"
                    ),
                ))
                continue

        # Grün: Prüfen ob Auflager entfernt werden könnte
        if deflection.allowable_deflection_mm and _can_remove_support(
            sr.support,
            support_results,
            point_loads,
            distributed_loads,
            ei_n_m2,
            self_weight_kg_per_m,
            total_length_m,
            deflection.allowable_deflection_mm,
        ):
            colors.append(SupportColor(
                support_id=sr.support.id,
                color="green",
                tooltip=(
                    f"Auflager könnte entfernt werden "
                    f"(Reaktion: {sr.reaction_kg:.1f} kg)"
                ),
            ))
        else:
            colors.append(SupportColor(
                support_id=sr.support.id,
                color="white",
                tooltip=f"OK – Reaktion: {sr.reaction_kg:.1f} kg",
            ))

    return colors


def classify_deflection(deflection: DeflectionResult) -> DeflectionColor:
    if deflection.allowable_deflection_mm is None:
        return DeflectionColor(
            color="green",
            tooltip=f"Max. Durchbiegung: {deflection.max_deflection_mm:.1f} mm (kein Grenzwert)",
        )

    limit = deflection.allowable_deflection_mm
    current = deflection.max_deflection_mm

    if current > limit:
        return DeflectionColor(
            color="red",
            tooltip=(
                f"ÜBERSCHRITTEN: {current:.1f} mm > {limit:.1f} mm "
                f"({current/limit*100:.0f}% des Grenzwerts)"
            ),
        )

    if current * 1.2 > limit:
        return DeflectionColor(
            color="yellow",
            tooltip=(
                f"Warnung: Bei 120%%-Last {current*1.2:.1f} mm > {limit:.1f} mm – "
                f"aktuell {current:.1f} mm"
            ),
        )

    return DeflectionColor(
        color="green",
        tooltip=f"OK – {current:.1f} mm von {limit:.1f} mm ({current/limit*100:.0f}%)",
    )


def _can_remove_support(
    target: Support,
    all_results: list[SupportResult],
    point_loads,
    distributed_loads,
    ei_n_m2: float,
    self_weight_kg_per_m: Optional[float],
    total_length_m: float,
    allowable_mm: float,
) -> bool:
    remaining = [r.support for r in all_results if r.support.id != target.id and r.is_active]
    if len(remaining) < 2:
        return False
    try:
        _, defl = solve(
            sections=[],
            supports=remaining,
            point_loads=point_loads,
            distributed_loads=distributed_loads,
            ei_n_m2=ei_n_m2,
            self_weight_kg_per_m=self_weight_kg_per_m,
            total_length_m=total_length_m,
        )
        return defl.max_deflection_mm <= allowable_mm * 0.20
    except Exception:
        return False
