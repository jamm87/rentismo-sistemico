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
- `diputado` se deriva de `DiputadosActivos` (137) + `DiputadosDeBaja` (275) = 412 de la XV. Los JSON
  oficiales **no traen ningún identificador** (ni `codParlamentario`), así que el enlace con
  `interes_economico` y con xerraires es por nombre normalizado, solo con coincidencia única; lo
  ambiguo o sin candidato va a `revision_manual`.
- Si cambia `db/schema.sql`, hay que borrar `db/rentismo.sqlite` y regenerarla (se reconstruye
  entera desde la caché, sin descargar nada): `CREATE TABLE IF NOT EXISTS` no altera tablas existentes.
- **User-Agent:** el cortafuegos del Congreso devuelve 403 a un UA con URL (`+https://…`). Se usa uno
  identificable pero sin URL (ver `config.toml`).

### Fase 1b · Fuente externa de referencia: xerraires/diputados

```bash
.venv/bin/python -m rentismo.import_xerraires   # idempotente; muestra recuentos
```

Importa [xerraires/diputados](https://github.com/xerraires/diputados) fijado al commit de `config.toml`
(diputados de la XV + 2.433 bienes extraídos con Tesseract y revisados a mano por su autor).
Va a tablas propias (`ext_xerraires_*`) y **nunca se mezcla con nuestra extracción**. Limitaciones:
solo declaraciones iniciales, sin rentas, sin nº de página. Los importes se interpretan por sección
(deudas: `titulo` = saldo pendiente, `derecho` = importe concedido); los que tienen cifras pero no un
importe inequívoco quedan `NULL` con `valor_flag='ilegible'`. Las filas idénticas repetidas se
conservan con `ocurrencia > 1`. Créditos: datos de xerraires (uso libre según su README).

### Fase 2 · Declaraciones de bienes y rentas (ruta docbienes)

Cada diputado tiene en su ficha del Congreso enlaces a sus PDF:
`/docbienes/leg15/{id:06d}/{id:06d}_{tipo}_e_{nºreg}_{aaaammdd}.pdf`. Un PDF por declaración, así
que no hace falta segmentar boletines. **Ese `id` no es el `codParlamentario`** (difiere en 326 de 350 diputados; p. ej. Abades Martínez:
cod 160, id 150), por eso se guarda aparte (`id_docbienes`). El código `tipo` se guarda tal cual:
000 = inicial y 001 = modificación están verificados en fichas reales; 002 = final aún no se ha visto.
Los PDF son escaneos puros (imagen CCITT a 300 ppi, sin capa de texto): hace falta OCR o visión.

```bash
.venv/bin/python -m rentismo.fetch_docbienes --discover   # recorre fichas y registra URL
.venv/bin/python -m rentismo.fetch_docbienes --download   # descarga a la caché
```

La Serie D del BOCG queda como fuente secundaria, solo si aparece algo que no esté en docbienes.

### Fase 3 · Extracción híbrida (visión + Tesseract)

Decisión: **híbrido** (`config.toml → bienes_rentas`). La visión de Claude lee el PDF entero y devuelve
cabecera + filas en JSON validado por esquema, copiando cada importe tal cual está impreso y la página
de cada fila. Tesseract hace el OCR de cada página y actúa de **verificador independiente de cifras**:
un importe solo se acepta (`importe_estado='coinciden'`) si la misma cifra aparece en el OCR de esa
página. Si no, queda `NULL` (`discrepan` / `ilegible`) con las dos lecturas guardadas, y la vista
`v_revision_importes` da URL + página + ambas lecturas para revisar a mano. Nunca se elige un valor.

```bash
.venv/bin/python -m rentismo.extract --cod 12 281 182 --tipo 000 --solo-ocr   # solo Tesseract, gratis
.venv/bin/python -m rentismo.extract --cod 12 281 182 --tipo 000              # híbrido (llama a la API)
.venv/bin/python -m rentismo.extract --export pred.json [--fuente vision]      # para evaluar
.venv/bin/python -m rentismo.evaluate pred.json --detalle
```

- Tablas: `extraccion` (modelo, versión del prompt, tokens, respuesta cruda), `decl_cabecera`,
  `decl_partida` (sección, página, campos, importe + texto + estado + lectura de Tesseract).
- Caché en `data/derived/` (OCR y respuestas de la API): relanzar no repite OCR ni vuelve a pagar.
  Cargar es idempotente (se reemplazan las filas de esa declaración).
- Clave de la API: `ANTHROPIC_API_KEY`, idealmente como *secreto de red* del entorno (no en el repo).
- Se usa `fallbacks: "default"` (respaldo en servidor si el modelo rechaza una petición).

Cualquier extracción se compara contra la referencia de xerraires con `rentismo.evaluate`
(recall, precisión e importes exactos por sección). La referencia también tiene errores: las
discrepancias se revisan contra el PDF.

## Explorador web

```bash
.venv/bin/python -m rentismo.web     # genera data/web/explorador.html desde la BBDD
```

Una sola página HTML con los datos incrustados (fuera del repo, como todo lo que contiene datos):
lista de diputados con buscador y filtros, y la ficha de cada uno con sus declaraciones (enlace al PDF
oficial), sus bienes (extracción propia cuando exista; referencia xerraires mientras tanto) y sus
intereses económicos. Se regenera después de cada fase. Plantilla: `web/explorador.template.html`.

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
  fetch_docbienes.py     descubrimiento y descarga de PDF de bienes (fichas → docbienes)
  import_xerraires.py    importación de la fuente externa de referencia
  secciones.py           secciones canónicas del formulario
  evaluate.py            evaluación de una extracción contra la referencia
  extract.py             extracción híbrida visión + Tesseract → decl_cabecera / decl_partida
  web.py                 genera el explorador HTML desde la BBDD
web/explorador.template.html   plantilla del explorador
tests/                   tests (fixtures sintéticos)
```

Cambio respecto a la estructura propuesta: el código vive en un paquete (`src/rentismo/`) para que
los módulos se importen entre sí y desde los tests sin tocar `sys.path`, y se ejecuten con `python -m`.
La lógica común (HTTP y normalización) está en módulos propios porque la usan varias fases.

## Dependencias del sistema

Para OCR: `apt-get install tesseract-ocr tesseract-ocr-spa poppler-utils` (no son paquetes de Python).
Exploración y medidas de extracción: [docs/exploracion_pdf.md](docs/exploracion_pdf.md).

## Tests

```bash
.venv/bin/pytest
```
