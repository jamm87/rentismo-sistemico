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

-- ---------------------------------------------------------------------------
-- Declaraciones de bienes y rentas (ruta docbienes: un PDF por diputado y declaración)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS declaracion_bienes (
    id                  INTEGER PRIMARY KEY,
    url                 TEXT NOT NULL UNIQUE,   -- https://www.congreso.es/docbienes/leg15/...
    cod_parlamentario   INTEGER NOT NULL,
    legislatura         INTEGER NOT NULL,
    tipo_codigo         TEXT NOT NULL,          -- campo tal cual del nombre de fichero ('000', ...)
    tipo                TEXT,                   -- inicial | modificacion | final (inferido del código)
    num_registro        TEXT,
    fecha               TEXT,                   -- ISO, del nombre de fichero
    ficha_url           TEXT,                   -- página donde se descubrió el enlace
    descubierta_por     TEXT NOT NULL,          -- 'ficha' | 'xerraires'
    source_file_id      INTEGER REFERENCES source_file(id)  -- cuando el PDF está descargado
);

-- ---------------------------------------------------------------------------
-- Fuente externa: xerraires/diputados (OCR Tesseract + revisión manual de terceros).
-- Tablas separadas a propósito: nunca se mezclan con la extracción propia.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ext_xerraires_diputado (
    cod_parlamentario   INTEGER PRIMARY KEY,
    source_file_id      INTEGER NOT NULL REFERENCES source_file(id),
    apellidos_nombre    TEXT NOT NULL,
    nombre_key          TEXT NOT NULL,
    apellidos           TEXT,
    nombre              TEXT,
    genero              INTEGER,
    formacion           TEXT,
    grupo               TEXT,
    id_circunscripcion  INTEGER,
    circunscripcion     TEXT,
    fecha_alta          TEXT,
    fecha_baja          TEXT,
    pdf_url             TEXT
);

CREATE TABLE IF NOT EXISTS ext_xerraires_bien (
    id                  INTEGER PRIMARY KEY,
    source_file_id      INTEGER NOT NULL REFERENCES source_file(id),
    record_hash         TEXT NOT NULL UNIQUE,
    ocurrencia          INTEGER NOT NULL,       -- >1 = fila idéntica repetida en el origen
    cod_parlamentario   INTEGER NOT NULL,
    nombre              TEXT NOT NULL,
    seccion_original    TEXT NOT NULL,
    seccion             TEXT NOT NULL,          -- canónica (ver secciones.py)
    descripcion         TEXT,
    situacion           TEXT,
    fecha               TEXT,
    derecho             TEXT,                   -- texto original del campo 'derecho'
    titulo              TEXT,                   -- texto original del campo 'titulo'
    -- Importes interpretados según la sección. TEXT con el Decimal exacto (sin floats).
    valor               TEXT,   -- saldo / valor / saldo pendiente de la deuda
    valor_flag          TEXT,   -- NULL=ok | 'ilegible' (hay cifras pero no se interpretan) | 'ausente'
    importe_concedido   TEXT,   -- solo deudas
    importe_concedido_flag TEXT,
    audit               TEXT,
    fuente_nota         TEXT,
    pr                  TEXT
);
CREATE INDEX IF NOT EXISTS ix_xbien_cod ON ext_xerraires_bien(cod_parlamentario, seccion);
