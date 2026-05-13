CREATE TABLE IF NOT EXISTS truss_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    manufacturer TEXT,
    model_code TEXT,
    width_mm REAL,
    height_mm REAL,
    weight_per_meter_kg REAL,
    material TEXT,
    source TEXT NOT NULL DEFAULT 'datasheet',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS load_table_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    truss_type_id INTEGER NOT NULL REFERENCES truss_types(id) ON DELETE CASCADE,
    span_m REAL NOT NULL,
    load_type TEXT NOT NULL,
    max_load_kg REAL NOT NULL,
    deflection_mm REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS truss_pdfs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    truss_type_id INTEGER NOT NULL REFERENCES truss_types(id) ON DELETE CASCADE,
    pdf_data BLOB NOT NULL,
    filename TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    project_data TEXT NOT NULL DEFAULT '{}'
);
