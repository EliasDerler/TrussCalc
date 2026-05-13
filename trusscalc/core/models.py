"""Datenklassen für alle TrussCalc-Entitäten."""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class LoadType(str, Enum):
    UDL = "UDL"       # Gleichmäßige Streckenlast
    CPL = "CPL"       # Mittelpunkt-Einzellast
    THIRD = "1/3"     # 1/3-Punkt-Lasten
    QUARTER = "1/4"   # 1/4-Punkt-Lasten
    FIFTH = "1/5"     # 1/5-Punkt-Lasten


class TrussSource(str, Enum):
    DATASHEET = "datasheet"
    MANUAL = "manual"


class UnitSystem(str, Enum):
    KG_M = "kg_m"     # Kilogramm + Meter/cm
    N_M = "n_m"       # Newton/kN + Meter/cm


@dataclass
class LoadTableEntry:
    span_m: float
    load_type: LoadType
    max_load_kg: float
    deflection_mm: float
    id: Optional[int] = None
    truss_type_id: Optional[int] = None


@dataclass
class TrussType:
    name: str
    source: TrussSource = TrussSource.DATASHEET
    manufacturer: Optional[str] = None
    model_code: Optional[str] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    weight_per_meter_kg: Optional[float] = None
    material: Optional[str] = None
    id: Optional[int] = None
    load_table: list[LoadTableEntry] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        parts = [self.name]
        if self.manufacturer:
            parts.insert(0, self.manufacturer)
        return " – ".join(parts)

    @property
    def has_weight(self) -> bool:
        return self.weight_per_meter_kg is not None and self.weight_per_meter_kg > 0


@dataclass
class TrussSection:
    """Ein Abschnitt der Traversen-Strecke (ein Traversenstück)."""
    length_m: float
    position_m: float   # Startposition auf der Gesamtstrecke
    truss_type_id: int
    id: Optional[str] = None  # UUID für Canvas-Zuordnung


@dataclass
class Support:
    """Auflager an einer Position auf der Traversen-Strecke."""
    position_m: float           # Position auf der Gesamtstrecke
    max_force_kg: Optional[float] = None  # Max. aufnehmbare Kraft (None = unbegrenzt)
    id: Optional[str] = None

    @property
    def has_max_force(self) -> bool:
        return self.max_force_kg is not None and self.max_force_kg > 0


@dataclass
class PointLoad:
    """Einzelne Punktlast an einer Position."""
    position_m: float
    load_kg: float      # Positiv = nach unten
    id: Optional[str] = None


@dataclass
class DistributedLoad:
    """Gleichmäßige Streckenlast über einen Bereich."""
    start_m: float
    end_m: float
    load_kg_per_m: float    # Positiv = nach unten
    id: Optional[str] = None

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def total_load_kg(self) -> float:
        return self.load_kg_per_m * self.length_m


@dataclass
class TrussSystem:
    """Ein statisch unabhaengiges Traversensystem innerhalb eines Sub-Projekts."""
    name: str
    truss_type_id: int = 0
    canvas_x_m: float = 0.0
    canvas_y_m: float = 0.0
    sections: list[TrussSection] = field(default_factory=list)
    supports: list[Support] = field(default_factory=list)
    point_loads: list[PointLoad] = field(default_factory=list)
    distributed_loads: list[DistributedLoad] = field(default_factory=list)
    id: Optional[str] = None

    @property
    def total_length_m(self) -> float:
        if not self.sections:
            return 0.0
        last = max(self.sections, key=lambda s: s.position_m + s.length_m)
        return last.position_m + last.length_m


@dataclass
class SupportResult:
    """Berechnungsergebnis für ein Auflager."""
    support: Support
    reaction_kg: float          # Auflagerkraft (positiv = Druck nach oben)
    utilization: float          # Auslastung 0.0–1.0 (nur wenn max_force bekannt)
    is_active: bool = True      # False wenn abgehoben (wird aus Berechnung entfernt)
    lift_height_mm: float = 0.0 # Bei abgehobenem Auflager: Höhe der Traverse über
                                # der ursprünglichen Auflager-Position (mm, ≥ 0)

    @property
    def color(self) -> str:
        if not self.is_active or self.reaction_kg <= 0:
            return "blue"
        if self.support.has_max_force:
            if self.utilization > 1.0:
                return "red"
            if self.utilization > 0.8:
                return "yellow"
        return "green"

    @property
    def can_be_removed(self) -> bool:
        """Grün-Markierung: Auflager könnte entfernt werden (Durchbiegung < 20% Grenzwert)."""
        return getattr(self, "_can_be_removed", False)


@dataclass
class DeflectionResult:
    """Berechnungsergebnis der Durchbiegung."""
    positions_m: list[float]
    deflections_mm: list[float]     # Positiv = nach unten
    max_deflection_mm: float
    max_deflection_position_m: float
    allowable_deflection_mm: Optional[float] = None  # Aus Datenblatttabelle

    @property
    def color(self) -> str:
        if self.allowable_deflection_mm is None:
            return "green"
        if self.max_deflection_mm > self.allowable_deflection_mm:
            return "red"
        return "green"

    @property
    def warning_at_120_percent(self) -> bool:
        """Gelb: Bei 120%-Last würde Grenzwert überschritten."""
        if self.allowable_deflection_mm is None:
            return False
        return self.max_deflection_mm * 1.2 > self.allowable_deflection_mm


@dataclass
class CalculationResult:
    """Gesamtergebnis einer Berechnung."""
    support_results: list[SupportResult]
    deflection: DeflectionResult
    total_load_kg: float
    self_weight_kg: float
    warnings: list[str] = field(default_factory=list)
    is_valid: bool = True


@dataclass
class Project:
    """Komplettes TrussCalc-Projekt."""
    name: str
    truss_type_id: int
    sections: list[TrussSection] = field(default_factory=list)
    supports: list[Support] = field(default_factory=list)
    point_loads: list[PointLoad] = field(default_factory=list)
    distributed_loads: list[DistributedLoad] = field(default_factory=list)
    systems: list[TrussSystem] = field(default_factory=list)
    active_system_id: Optional[str] = None
    plan_system_id: Optional[str] = None
    compare_system_ids: list[str] = field(default_factory=list)
    view_mode: str = "plan"
    unit_system: UnitSystem = UnitSystem.KG_M
    description: str = ""
    id: Optional[int] = None

    @property
    def total_length_m(self) -> float:
        system = self.active_system
        if system is not None:
            return system.total_length_m
        if not self.sections:
            return 0.0
        last = max(self.sections, key=lambda s: s.position_m + s.length_m)
        return last.position_m + last.length_m

    @property
    def active_system(self) -> Optional[TrussSystem]:
        if not self.systems:
            return None
        if self.active_system_id:
            for system in self.systems:
                if system.id == self.active_system_id:
                    return system
        return self.systems[0]


@dataclass
class ProjectBundle:
    """Container fuer ein Gesamtprojekt mit mehreren Sub-Projekten."""
    name: str
    subprojects: list[Project] = field(default_factory=list)
    unit_system: UnitSystem = UnitSystem.KG_M
    description: str = ""
    id: Optional[int] = None

    @property
    def active_or_first_project(self) -> Optional[Project]:
        return self.subprojects[0] if self.subprojects else None
