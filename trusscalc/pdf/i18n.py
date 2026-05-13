"""Übersetzungen für PDF-Reports (DE / EN)."""

STRINGS = {
    "de": {
        "report_title_header": "TRAVERSEN-BERECHNUNGSREPORT",
        "date": "DATUM",
        "software": "SOFTWARE",
        "truss_type": "TRAVERSENTYP",
        "total_length": "GESAMTLÄNGE",
        "support_left": "AUFLAGER LINKS",
        "support_middle": "AUFLAGER MITTE",
        "support_right": "AUFLAGER RECHTS",
        "support_n": "AUFLAGER {n}",
        "max_deflection_card": "MAX. DURCHBIEGUNG",
        "main_load": "Hauptlast",
        "tolerance_share": "{pct:.1f}% der Toleranz",
        "section_static": "Statisches System",
        "section_static_sub": "Lastannahmen und Biegelinie",
        "section_reactions": "Auflagerkräfte",
        "section_reactions_sub": "Vertikale Reaktionen",
        "section_deflection": "Durchbiegungsanalyse",
        "section_deflection_sub": "Alle erkannten Biegungen im Vergleich zum Datenblatt-Grenzwert",
        "section_partlist": "Stückliste",
        "section_partlist_sub": "Verbaute Traversenabschnitte",
        "col_position": "POSITION",
        "col_reaction_kg": "REAKTIONSKRAFT",
        "col_reaction_n": "IN NEWTON",
        "col_utilization": "AUSLASTUNG",
        "col_status": "STATUS",
        "col_truss_type": "TRAVERSENTYP",
        "col_length": "LÄNGE",
        "col_pieces": "STÜCK",
        "partlist_support": "Auflager {n}",
        "partlist_max_force": "max. {force}",
        "partlist_unlimited": "unbegrenzt",
        "status_ok": "OK",
        "status_warning": "Warnung",
        "status_overload": "Überlastet",
        "status_lifted": "Abgehoben",
        "max_deflection": "MAXIMALE DURCHBIEGUNG",
        "detected_n_deflections": "Die Berechnung hat {n} maßgebliche Durchbiegungs-Stelle{plural} erkannt.",
        "datasheet_limit": "Zulässig laut Datenblatt",
        "utilization": "Auslastung",
        "assessment": "Bewertung",
        "assessment_safe": "Im sicheren Bereich",
        "assessment_warn": "Achtung – nahe Grenzwert",
        "assessment_over": "Grenzwert überschritten",
        "field_label": "FELD {i}",
        "field_label_left": "FELD {i} (LINKS)",
        "field_label_right": "FELD {i} (RECHTS)",
        "field_label_middle": "FELD {i} (MITTE)",
        "position_at": "Stelle:",
        "important_notice": "WICHTIGER HINWEIS",
        "important_notice_text": (
            "Diese Berechnung stellt eine softwaregestützte Auslegung dar und ersetzt keine "
            "individuelle statische Prüfung durch einen Sachverständigen. Die Verantwortung "
            "für die korrekte Eingabe der Lastannahmen sowie für den fachgerechten Aufbau der "
            "Traversenkonstruktion liegt beim Anwender. Vor der Inbetriebnahme ist die "
            "Übereinstimmung mit den Herstellerangaben sowie den geltenden Normen "
            "(u. a. DIN EN 17206, BGV C1) zu überprüfen."
        ),
        "signed_by": "ERSTELLT DURCH",
        "approved_by": "GEPRÜFT / FREIGEGEBEN",
        "sig_line": "Name · Datum · Unterschrift",
        "page_of": "Seite {p} von {total}",
        "company_address": "NoiseGate Eventtechnik GmbH · Viertelfeistritz 38, 8184 Anger",
    },
    "en": {
        "report_title_header": "TRUSS CALCULATION REPORT",
        "date": "DATE",
        "software": "SOFTWARE",
        "truss_type": "TRUSS TYPE",
        "total_length": "TOTAL LENGTH",
        "support_left": "LEFT SUPPORT",
        "support_middle": "CENTER SUPPORT",
        "support_right": "RIGHT SUPPORT",
        "support_n": "SUPPORT {n}",
        "max_deflection_card": "MAX. DEFLECTION",
        "main_load": "Main load",
        "tolerance_share": "{pct:.1f}% of tolerance",
        "section_static": "Static System",
        "section_static_sub": "Load assumptions and bending line",
        "section_reactions": "Support Reactions",
        "section_reactions_sub": "Vertical reactions",
        "section_deflection": "Deflection Analysis",
        "section_deflection_sub": "All detected deflections vs. datasheet limit",
        "section_partlist": "Bill of Materials",
        "section_partlist_sub": "Installed truss sections",
        "col_position": "POSITION",
        "col_reaction_kg": "REACTION",
        "col_reaction_n": "IN NEWTONS",
        "col_utilization": "UTILIZATION",
        "col_status": "STATUS",
        "col_truss_type": "TRUSS TYPE",
        "col_length": "LENGTH",
        "col_pieces": "QTY",
        "partlist_support": "Support {n}",
        "partlist_max_force": "max. {force}",
        "partlist_unlimited": "unlimited",
        "status_ok": "OK",
        "status_warning": "Warning",
        "status_overload": "Overloaded",
        "status_lifted": "Lifted",
        "max_deflection": "MAXIMUM DEFLECTION",
        "detected_n_deflections": "Calculation detected {n} significant deflection point{plural}.",
        "datasheet_limit": "Allowable per datasheet",
        "utilization": "Utilization",
        "assessment": "Assessment",
        "assessment_safe": "Within safe range",
        "assessment_warn": "Caution – near limit",
        "assessment_over": "Limit exceeded",
        "field_label": "FIELD {i}",
        "field_label_left": "FIELD {i} (LEFT)",
        "field_label_right": "FIELD {i} (RIGHT)",
        "field_label_middle": "FIELD {i} (CENTER)",
        "position_at": "Position:",
        "important_notice": "IMPORTANT NOTICE",
        "important_notice_text": (
            "This calculation represents a software-assisted design and does not replace "
            "an individual structural review by a qualified engineer. Responsibility for the "
            "correct input of load assumptions and the proper assembly of the truss structure "
            "lies with the user. Before commissioning, compliance with manufacturer "
            "specifications and applicable standards (incl. DIN EN 17206, BGV C1) must be "
            "verified."
        ),
        "signed_by": "PREPARED BY",
        "approved_by": "REVIEWED / APPROVED",
        "sig_line": "Name · Date · Signature",
        "page_of": "Page {p} of {total}",
        "company_address": "NoiseGate Eventtechnik GmbH · Viertelfeistritz 38, 8184 Anger",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    """Übersetzt einen String. Fallback auf DE wenn Sprache unbekannt."""
    lang_map = STRINGS.get(lang) or STRINGS["de"]
    template = lang_map.get(key) or STRINGS["de"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
