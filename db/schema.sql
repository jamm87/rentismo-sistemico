-- Esquema SQLite. Se aplica con CREATE ... IF NOT EXISTS: relanzar no rompe nada.
PRAGMA foreign_keys = ON;

-- Cada fichero descargado (JSON o PDF) del que procede algún dato.
CREATE TABLE IF NOT EXISTS source_file (
    id          INTEGER PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    dataset     TEXT,                 -- prefijo del JSON (DiputadosActivos, docacteco...) o 'BOCG-D'
    sha256      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    local_path  TEXT NOT NULL
);

-- Copia literal de cada registro de los JSON de datos abiertos (staging).
-- Permite rehacer las tablas derivadas sin volver a descargar y no pierde campos
-- aunque el Congreso añada columnas nuevas.
CREATE TABLE IF NOT EXISTS opendata_raw (
    id              INTEGER PRIMARY KEY,
    dataset         TEXT NOT NULL,
    record_hash     TEXT NOT NULL,     -- sha256(json canónico + nº de ocurrencia en el fichero)
    record_json     TEXT NOT NULL,
    first_file_id   INTEGER NOT NULL REFERENCES source_file(id),
    last_file_id    INTEGER NOT NULL REFERENCES source_file(id),
    UNIQUE (dataset, record_hash)
);

-- PENDIENTE: tabla `diputado` (y legislatura/grupo/circunscripción). Se diseñará tras
-- inspeccionar los JSON reales (python -m rentismo.fetch_opendata --inspect).

-- Declaración de Intereses Económicos (dataset docacteco). Campos verificados.
CREATE TABLE IF NOT EXISTS interes_economico (
    id              INTEGER PRIMARY KEY,
    raw_id          INTEGER NOT NULL UNIQUE REFERENCES opendata_raw(id),
    nombre          TEXT NOT NULL,          -- tal cual: "Apellidos,Nombre"
    nombre_key      TEXT NOT NULL,          -- normalizado: "APELLIDOS, NOMBRE"
    diputado_id     INTEGER,                -- NULL hasta enlazar; los dudosos van a revision_manual
    fecha_registro  TEXT,                   -- ISO 8601; NULL si no se pudo leer
    fecha_registro_original TEXT,
    declaracion     TEXT,                   -- "Declaración inicial" / "Modificación de ..."
    tipo            TEXT,                   -- ACTIVIDAD | DONACION | FUNDACIONES | OBSERVACIONES
    periodo         TEXT,
    empleador       TEXT,
    sector          TEXT,
    descripcion     TEXT,
    destinatario    TEXT,
    benefactor      TEXT,
    observaciones   TEXT
);
CREATE INDEX IF NOT EXISTS ix_interes_nombre_key ON interes_economico(nombre_key);

-- Emparejamientos nombre -> diputado que no se resolvieron de forma inequívoca.
CREATE TABLE IF NOT EXISTS revision_manual (
    id              INTEGER PRIMARY KEY,
    origen_tabla    TEXT NOT NULL,          -- 'interes_economico', 'declaracion_bienes', ...
    nombre_original TEXT NOT NULL,
    nombre_key      TEXT NOT NULL,
    motivo          TEXT NOT NULL,          -- 'sin_candidatos' | 'ambiguo'
    candidatos_json TEXT NOT NULL,          -- [{"id":..,"nombre":..}, ...]
    diputado_id_resuelto INTEGER,           -- lo rellena una persona
    resuelto_por    TEXT,
    resuelto_at     TEXT,
    UNIQUE (origen_tabla, nombre_key)
);
