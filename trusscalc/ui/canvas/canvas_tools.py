"""Werkzeugzustände für den TrussCanvas (LTSpice-Verb-Objekt-Modell)."""
from enum import Enum, auto


class CanvasTool(Enum):
    SELECT = auto()
    ADD_SECTION = auto()
    ADD_SUPPORT = auto()
    ADD_POINT_LOAD = auto()
    ADD_DIST_LOAD = auto()
