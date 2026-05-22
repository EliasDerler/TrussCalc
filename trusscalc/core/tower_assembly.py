"""Adapter zwischen gezeichnetem Tower und bestehender Tower-Berechnung."""
from __future__ import annotations

import copy
import uuid

from trusscalc.core.models import (
    TowerAssembly, TowerAssemblyLoad, TowerAssemblySection, TowerConnector,
    TowerFoundation, TowerInput, TrussType,
)
from trusscalc.core.interpolator import LoadTableInterpolator

GRAVITY = 9.80665


def refresh_section_positions(assembly: TowerAssembly) -> None:
    """Setzt die Startpositionen der vertikalen Tower-Abschnitte lueckenlos."""
    pos = 0.0
    for section in assembly.sections:
        section.position_m = pos
        pos += max(section.length_m, 0.0)


def assembly_from_tower_input(data: TowerInput | None) -> TowerAssembly:
    """Migriert einen alten Formular-Tower in die neue zeichnungsbasierte Struktur."""
    data = data or TowerInput()
    assembly = TowerAssembly(
        foundation_name="Projekt-Fundament",
        foundation_source_id=None,
        foundation=copy.deepcopy(data.foundation),
        connector=copy.deepcopy(data.connector),
        gamma=data.gamma,
    )
    if data.height_m > 0 or data.truss_type_id:
        assembly.sections.append(
            TowerAssemblySection(
                id=str(uuid.uuid4()),
                length_m=max(data.height_m, 0.1),
                position_m=0.0,
                truss_type_id=data.truss_type_id,
            )
        )
    if data.horizontal_force_kn > 0:
        assembly.point_loads.append(
            TowerAssemblyLoad(
                id=str(uuid.uuid4()),
                direction="horizontal",
                height_m=max(0.0, data.force_height_m),
                value=data.horizontal_force_kn,
                x_m=-1.0 if data.horizontal_force_direction >= 0 else 1.0,
            )
        )
    if data.payload_kg > 0:
        assembly.point_loads.append(
            TowerAssemblyLoad(
                id=str(uuid.uuid4()),
                direction="vertical",
                height_m=max(0.0, data.height_m),
                value=data.payload_kg,
                eccentricity_m=data.payload_eccentricity_m,
                x_m=data.payload_eccentricity_m,
            )
        )
    refresh_section_positions(assembly)
    return assembly


def tower_input_from_assembly(
    assembly: TowerAssembly,
    truss_type: TrussType | None = None,
) -> tuple[TowerInput, list[str]]:
    """Erzeugt den bestehenden TowerInput für Rechner/PDF aus der Zeichnung.

    Gibt den Input plus Validierungsfehler zurueck. Fehler werden gesammelt, damit
    die UI dem Nutzer alle fehlenden Angaben in einer Meldung anzeigen kann.
    """
    refresh_section_positions(assembly)
    errors: list[str] = []
    if assembly.foundation is None:
        errors.append("Bitte zuerst ein Fundament aus der Fundamentbibliothek platzieren.")
    if not assembly.sections:
        errors.append("Bitte mindestens einen vertikalen Traversenabschnitt anlegen.")
    ids = assembly.truss_type_ids
    if not ids:
        errors.append("Bitte einen Traversentyp für den Tower auswählen.")
    elif len(ids) > 1:
        errors.append("Tower V3 unterstützt für die Berechnung nur einen Traversentyp pro Tower.")
    height = assembly.height_m
    if height <= 0:
        errors.append("Tower-Hoehe muss groesser als 0 m sein.")

    horizontal_loads = [
        load for load in assembly.point_loads
        if load.direction == "horizontal" and load.value > 0
    ]
    vertical_loads = [
        load for load in assembly.point_loads
        if load.direction == "vertical" and load.value > 0
    ]

    signed_horizontal_items = []
    for load in horizontal_loads:
        sign = -1.0 if getattr(load, "x_m", 0.0) > 0 else 1.0
        signed_horizontal_items.append((sign * load.value, max(load.height_m, 0.0)))
    signed_horizontal_force_kn = sum(force for force, _height in signed_horizontal_items)
    signed_horizontal_moment_knm = sum(force * height for force, height in signed_horizontal_items)
    horizontal_force_kn = abs(signed_horizontal_force_kn)
    horizontal_force_direction = -1 if signed_horizontal_moment_knm < 0 else 1
    if abs(signed_horizontal_force_kn) > 1e-9:
        force_height_m = abs(signed_horizontal_moment_knm / signed_horizontal_force_kn)
    elif horizontal_loads:
        total_abs = sum(abs(force) for force, _height in signed_horizontal_items)
        force_height_m = (
            sum(abs(force) * height for force, height in signed_horizontal_items) / total_abs
            if total_abs > 0 else height
        )
    else:
        force_height_m = height

    payload_items: list[tuple[float, float]] = []
    for load in vertical_loads:
        x_m = getattr(load, "x_m", load.eccentricity_m)
        payload_items.append((load.value, x_m))

    if truss_type and truss_type.has_weight:
        weight_per_m = truss_type.weight_per_meter_kg
        for cantilever in assembly.cantilevers:
            if cantilever.length_m <= 0:
                continue
            sign = -1.0 if cantilever.side == "left" else 1.0
            arm_weight_kg = cantilever.length_m * weight_per_m
            payload_items.append((arm_weight_kg, sign * cantilever.length_m / 2.0))

    payload_kg = sum(value for value, _x_m in payload_items)
    payload_eccentricity_m = (
        sum(value * x_m for value, x_m in payload_items) / payload_kg
        if payload_kg > 0 else 0.0
    )
    cantilever_deflections = cantilever_deflections_mm(
        assembly=assembly,
        truss_type=truss_type,
        gamma=max(assembly.gamma, 0.0),
    )
    cantilever_deflection_mm = max(cantilever_deflections.values(), default=0.0)

    data = TowerInput(
        truss_type_id=ids[0] if ids else 0,
        height_m=height if height > 0 else 0.0,
        horizontal_force_kn=horizontal_force_kn,
        force_height_m=min(max(force_height_m, 0.0), height) if height > 0 else 0.0,
        horizontal_force_direction=horizontal_force_direction,
        horizontal_moment_knm=signed_horizontal_moment_knm,
        payload_kg=payload_kg,
        payload_eccentricity_m=payload_eccentricity_m,
        cantilever_deflection_mm=cantilever_deflection_mm,
        gamma=max(assembly.gamma, 0.0),
        foundation=copy.deepcopy(assembly.foundation) if assembly.foundation else TowerFoundation(),
        connector=copy.deepcopy(assembly.connector) if assembly.connector else TowerConnector(),
    )
    return data, errors


def cantilever_deflections_mm(
    assembly: TowerAssembly,
    truss_type: TrussType | None,
    gamma: float,
) -> dict[str, float]:
    if not assembly.cantilevers or not truss_type:
        return {}
    try:
        ei = LoadTableInterpolator(truss_type).true_bending_ei()
    except Exception:
        ei = None
    if not ei or ei <= 0:
        return {}

    weight_per_m = truss_type.weight_per_meter_kg if truss_type.has_weight else 0.0
    result: dict[str, float] = {}
    tolerance_m = 0.35
    for cantilever in assembly.cantilevers:
        length = max(cantilever.length_m, 0.0)
        if length <= 0:
            continue
        sign = -1.0 if cantilever.side == "left" else 1.0
        deflection_m = 0.0
        if weight_per_m > 0:
            w_n_per_m = gamma * weight_per_m * GRAVITY
            deflection_m += w_n_per_m * length**4 / (8.0 * ei)
        for load in assembly.point_loads:
            if load.direction != "vertical" or load.value <= 0:
                continue
            x_m = getattr(load, "x_m", load.eccentricity_m)
            if sign * x_m <= 0:
                continue
            if abs(load.height_m - cantilever.height_m) > tolerance_m:
                continue
            distance = min(abs(x_m), length)
            force_n = gamma * load.value * GRAVITY
            deflection_m += force_n * distance**2 * (3.0 * length - distance) / (6.0 * ei)
        if cantilever.id:
            result[cantilever.id] = max(0.0, deflection_m * 1000.0)
    return result
