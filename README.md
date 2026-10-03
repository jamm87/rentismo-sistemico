# rentismo-sistemico

Pipeline reproducible para construir una base de datos de diputados del Congreso con sus
declaraciones de intereses económicos (datos abiertos) y de bienes y rentas (PDF del BOCG, Serie D).

## Decisiones (en `config.toml`)

| Parámetro | Valor |
|---|---|
| Alcance temporal | Solo legislatura **XV** |
| Bienes y rentas | **Formulario completo** |
| Destino | **SQLite** (`db/rentismo.sqlite`) |
| Método de extracción de PDF | *pendiente* (tras explorar muestras) |

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env   # solo si hace falta alguna clave
```

## Fases

### Fase 1 · Datos abiertos → SQLite

```bash
.venv/bin/python -m rentismo.fetch_opendata --inspect   # descarga y muestra campos de cada JSON
.venv/bin/python -m rentismo.load                       # carga (idempotente) y muestra recuentos
.venv/bin/python -m rentismo.load --stats               # solo recuentos
```

- Las URL de los JSON llevan un timestamp diario: se descubren parseando la página índice.
- Todos los registros se guardan literalmente en `opendata_raw` (con hash para no duplicar)
  y de ahí se derivan las tablas normalizadas (`interes_economico`, …).
- Estado: la tabla `diputado` se diseñará tras inspeccionar los JSON reales.

### Fase 2 · Exploración de PDFs del BOCG — *pendiente*
### Fase 3 · Extracción y carga de bienes y rentas — *pendiente*

## Descargas

`src/rentismo/http.py`: ≥1 s entre peticiones, User-Agent identificable, reintentos con backoff
exponencial en 429/5xx/errores de red, y caché en `data/raw/` (fuera del repo) con un `.meta.json`
por fichero (URL, fecha, sha256). Nada se descarga dos veces; el índice se refresca cada 20 h.

## Estructura

```
config.toml              decisiones del proyecto
db/schema.sql            esquema SQLite
src/rentismo/
  config.py              carga config.toml y .env
  http.py                cliente HTTP educado con caché
  normalize.py           nombres, fechas e importes en formato español
  matching.py            nombre → diputado (solo coincidencias únicas; el resto a revision_manual)
  fetch_opendata.py      índice + JSON de diputados e intereses
  load.py                carga en SQLite
tests/                   tests (fixtures sintéticos)
```

Cambio respecto a la estructura propuesta: el código vive en un paquete (`src/rentismo/`) para que
los módulos se importen entre sí y desde los tests sin tocar `sys.path`, y se ejecuten con `python -m`.
La lógica común (HTTP y normalización) está en módulos propios porque la usan varias fases.

## Tests

```bash
.venv/bin/pytest
```
