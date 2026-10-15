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
    diputado_id     INTEGER REFERENCES diputado(id),  -- NULL si no hay emparejamiento único (ver revision_manual)
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
    cod_parlamentario   INTEGER NOT NULL,   -- del registro de origen, NO de la ruta del PDF
    id_docbienes        INTEGER NOT NULL,   -- id en la ruta /docbienes/legNN/{id}/ (≠ codParlamentario)
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
    diputado_id         INTEGER REFERENCES diputado(id),
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

-- ---------------------------------------------------------------------------
-- Diputados de la legislatura (datos abiertos: DiputadosActivos + DiputadosDeBaja).
-- Los JSON oficiales NO traen codParlamentario ni ningún id: el enlace es por nombre.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS diputado (
    id                  INTEGER PRIMARY KEY,
    legislatura         TEXT NOT NULL,          -- de config.toml (los datasets son 'legislatura actual')
    nombre              TEXT NOT NULL,          -- "Apellidos, Nombre" tal cual
    nombre_key          TEXT NOT NULL,
    circunscripcion     TEXT,
    formacion           TEXT,
    grupo               TEXT,
    fecha_condicion_plena TEXT,
    fecha_alta          TEXT NOT NULL,
    fecha_baja          TEXT,                   -- NULL = en activo
    fecha_alta_grupo    TEXT,
    fecha_baja_grupo    TEXT,
    biografia           TEXT,
    raw_id              INTEGER NOT NULL UNIQUE REFERENCES opendata_raw(id),
    UNIQUE (legislatura, nombre_key, fecha_alta)
);
CREATE INDEX IF NOT EXISTS ix_diputado_key ON diputado(nombre_key);

-- ---------------------------------------------------------------------------
-- Extracción propia de declaraciones de bienes y rentas (método híbrido).
--   visión (Claude) -> estructura + importes tal cual impresos
--   Tesseract       -> verificador independiente de cifras, por página
-- Un importe solo se acepta si ambos coinciden; si no, NULL + estado y ambas lecturas.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS extraccion (
    id                  INTEGER PRIMARY KEY,
    declaracion_id      INTEGER NOT NULL REFERENCES declaracion_bienes(id),
    metodo              TEXT NOT NULL,          -- 'hibrido'
    modelo              TEXT NOT NULL,          -- modelo de visión que respondió
    prompt_version      TEXT NOT NULL,
    pdf_sha256          TEXT NOT NULL,
    cache_path          TEXT NOT NULL,          -- respuesta cruda de la API (data/derived/...)
    tokens_entrada      INTEGER,
    tokens_salida       INTEGER,
    creada_at           TEXT NOT NULL,
    UNIQUE (declaracion_id, metodo, modelo, prompt_version)
);

CREATE TABLE IF NOT EXISTS decl_cabecera (
    declaracion_id      INTEGER PRIMARY KEY REFERENCES declaracion_bienes(id),
    extraccion_id       INTEGER NOT NULL REFERENCES extraccion(id),
    nombre_declarado    TEXT,
    estado_civil        TEXT,
    regimen_economico   TEXT,
    fecha_eleccion      TEXT,                   -- texto tal cual
    fecha_credencial    TEXT,
    circunscripcion     TEXT,
    motivo              TEXT,                   -- toma_posesion | cese | otra | NULL
    lugar_firma         TEXT,
    fecha_firma         TEXT,
    cuota_irpf          TEXT,                   -- Decimal si hay consenso
    cuota_irpf_texto    TEXT,                   -- lectura de visión tal cual
    cuota_irpf_estado   TEXT,                   -- ver decl_partida.importe_estado
    pagina_irpf         INTEGER
);

CREATE TABLE IF NOT EXISTS decl_partida (
    id                  INTEGER PRIMARY KEY,
    declaracion_id      INTEGER NOT NULL REFERENCES declaracion_bienes(id),
    extraccion_id       INTEGER NOT NULL REFERENCES extraccion(id),
    pagina              INTEGER NOT NULL,       -- página del PDF (1..n)
    orden               INTEGER NOT NULL,       -- orden de la fila dentro de la declaración
    seccion             TEXT NOT NULL,          -- canónica (secciones.py)
    clase               TEXT,                   -- p. ej. clase de bien / procedencia de la renta
    descripcion         TEXT,
    situacion           TEXT,
    fecha               TEXT,                   -- texto tal cual (fecha de adquisición / concesión)
    derecho_titulo      TEXT,
    -- Importe principal: renta, saldo, valor o saldo pendiente de la deuda.
    importe             TEXT,                   -- Decimal exacto; NULL si no hay consenso
    importe_texto       TEXT,                   -- lectura de visión tal cual impresa
    importe_estado      TEXT,                   -- coinciden | discrepan | ilegible | vacio
    importe_tesseract   TEXT,                   -- cifras de Tesseract más parecidas (si discrepan)
    -- Importe concedido (solo deudas).
    importe2            TEXT,
    importe2_texto      TEXT,
    importe2_estado     TEXT,
    importe2_tesseract  TEXT,
    dudoso              INTEGER NOT NULL DEFAULT 0,  -- la visión marcó la fila como dudosa
    metodo              TEXT NOT NULL,          -- 'hibrido'
    UNIQUE (declaracion_id, orden)
);
CREATE INDEX IF NOT EXISTS ix_partida_decl ON decl_partida(declaracion_id, seccion);

-- Cola de revisión: importes sin consenso, con todo lo necesario para mirar el PDF.
CREATE VIEW IF NOT EXISTS v_revision_importes AS
SELECT p.id AS partida_id, d.cod_parlamentario, d.url, p.pagina, p.seccion, p.descripcion,
       'importe' AS campo, p.importe_texto AS vision, p.importe_tesseract AS tesseract, p.importe_estado AS estado
  FROM decl_partida p JOIN declaracion_bienes d ON d.id = p.declaracion_id
 WHERE p.importe_estado IN ('discrepan', 'ilegible')
UNION ALL
SELECT p.id, d.cod_parlamentario, d.url, p.pagina, p.seccion, p.descripcion,
       'importe2', p.importe2_texto, p.importe2_tesseract, p.importe2_estado
  FROM decl_partida p JOIN declaracion_bienes d ON d.id = p.declaracion_id
 WHERE p.importe2_estado IN ('discrepan', 'ilegible');
