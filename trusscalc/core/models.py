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
class TowerFoundation:
    """Fundamentdaten fuer einen freistehenden Tower."""
    type: str = "steel_plate"  # steel_plate | concrete_socket
    width_m: float = 1.0
    depth_m: float = 1.0
    weight_kg: float = 120.0
    ballast_kg: float = 0.0
    ballast_offset_m: float = 0.0
    clearance_mm: float = 0.0
    insertion_depth_m: float = 0.5


@dataclass
class TowerConnector:
    """Manuelle Verbinder-/Schraubenwerte fuer die Tower-Vorbemessung."""
    bolt_count: int = 4
    bolt_lever_arm_m: float = 0.25
    allowable_tension_kn: float = 5.0
    allowable_shear_kn: float = 5.0


@dataclass
class TowerFoundationPreset:
    """Manuell gepflegter Fundament-Bibliothekseintrag."""
    name: str
    foundation: TowerFoundation = field(default_factory=TowerFoundation)
    connector: TowerConnector = field(default_factory=TowerConnector)
    id: Optional[int] = None


@dataclass
class TowerAssemblySection:
    """Vertikaler Traversenabschnitt eines gezeichneten Einzeltowers."""
    length_m: float
    truss_type_id: int
    position_m: float = 0.0
    id: Optional[str] = None


@dataclass
class TowerAssemblyCantilever:
    """Horizontale Auskragung links oder rechts am Tower."""
    height_m: float
    side: str  # left | right
    length_m: float
    truss_type_id: int
    id: Optional[str] = None


@dataclass
class TowerAssemblyLoad:
    """Punktkraft in der Tower-Seitenansicht."""
    height_m: float
    direction: str  # horizontal | vertical
    value: float    # horizontal = kN, vertical = kg
    eccentricity_m: float = 0.0
    x_m: float = 0.0
    id: Optional[str] = None


@dataclass
class TowerAssembly:
    """Zeichnungsbasierter Einzeltower: Fundament, Stack und Punktkraefte."""
    foundation_name: str = ""
    foundation_source_id: Optional[int] = None
    foundation: Optional[TowerFoundation] = None
    connector: TowerConnector = field(default_factory=TowerConnector)
    sections: list[TowerAssemblySection] = field(default_factory=list)
    cantilevers: list[TowerAssemblyCantilever] = field(default_factory=list)
    point_loads: list[TowerAssemblyLoad] = field(default_factory=list)
    gamma: float = 1.30

    @property
    def height_m(self) -> float:
        return sum(max(section.length_m, 0.0) for section in self.sections)

    @property
    def truss_type_ids(self) -> list[int]:
        ids: list[int] = []
        for section in self.sections:
            if section.truss_type_id and section.truss_type_id not in ids:
                ids.append(section.truss_type_id)
        for cantilever in self.cantilevers:
            if cantilever.truss_type_id and cantilever.truss_type_id not in ids:
                ids.append(cantilever.truss_type_id)
        return ids


@dataclass
class TowerInput:
    """Eingaben fuer einen freistehenden Einzeltower."""
    truss_type_id: int = 0
    height_m: float = 4.0
    horizontal_force_kn: float = 1.0
    force_height_m: float = 4.0
    horizontal_force_direction: int = 1
    horizontal_moment_knm: float = 0.0
    payload_kg: float = 0.0
    payload_eccentricity_m: float = 0.0
    cantilever_deflection_mm: float = 0.0
    gamma: float = 1.30
    foundation: TowerFoundation = field(default_factory=TowerFoundation)
    connector: TowerConnector = field(default_factory=TowerConnector)


@dataclass
class TowerResult:
    """Ergebnis der Tower-Vorbemessung."""
    design_moment_knm: float
    resisting_moment_knm: float
    tipping_utilization: float
    required_ballast_kg: float
    tower_self_weight_kg: float
    total_vertical_load_kg: float
    base_shear_kn: float
    base_compression_kg: float
    bolt_tension_kn: float
    bolt_shear_kn: float
    bolt_utilization: float
    top_offset_mm: float
    bending_deflection_mm: float
    total_top_displacement_mm: float
    status: str
    warnings: list[str] = field(default_factory=list)
    is_valid: bool = True
    max_horizontal_force_kn: float = 0.0
    edge_force_kn: float = 0.0
    edge_force_kg: float = 0.0
    moment_direction: int = 1
    cantilever_deflection_mm: float = 0.0


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
    kind: str = "beam"  # beam | tower
    tower_input: Optional[TowerInput] = None
    tower_assembly: Optional[TowerAssembly] = None
    tower_result: Optional[TowerResult] = None
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
