"""Extracción híbrida de las declaraciones de bienes y rentas (PDF escaneados de docbienes).

1. Visión (Claude, API): lee el PDF entero y devuelve cabecera + filas en JSON validado por
   esquema, con cada importe copiado tal cual está impreso y la página de cada fila.
2. Tesseract: OCR de cada página a 300 ppi; de él solo se usan las cifras de cada página.
3. Consenso: un importe se acepta solo si la misma cifra aparece en el OCR de esa página.
   Si no, queda NULL con estado 'discrepan' (o 'ilegible') y se guardan ambas lecturas;
   la vista v_revision_importes lista lo que hay que mirar a mano en el PDF.

Todo se cachea en data/derived/ (fuera del repo): relanzar no repite OCR ni llamadas a la API.

Uso:
    python -m rentismo.extract --cod 12 281 182          # extrae y carga esos diputados
    python -m rentismo.extract --limit 20 --tipo 000      # las 20 primeras iniciales
    python -m rentismo.extract --cod 12 --solo-ocr        # solo Tesseract (sin coste)
    python -m rentismo.extract --export pred.json [--fuente vision]   # para rentismo.evaluate
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

from . import config, secciones
from .normalize import parse_importe_es

log = logging.getLogger(__name__)

METODO = "hibrido"
PROMPT_VERSION = "v1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# --------------------------------------------------------------------------------------------
# Tesseract: cifras por página
# --------------------------------------------------------------------------------------------
_NUMISH = re.compile(r"^[\d.,'’€-]*\d[\d.,'’€-]*$")


def _limpia_num(t: str) -> str:
    return t.replace("€", "").strip(".,-")


def numeros_tsv(tsv: str) -> Counter:
    """Cifras (Decimal) de un TSV de Tesseract. Además de cada token, prueba a unir 2-3 tokens
    numéricos consecutivos de la misma línea: Tesseract a veces parte una cifra ('56 .419€')."""
    lineas: dict[tuple, list[str]] = {}
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5" or not c[11].strip():
            continue
        lineas.setdefault((c[2], c[3], c[4]), []).append(c[11].strip())
    out: Counter = Counter()
    for toks in lineas.values():
        vistos: set[tuple[int, int]] = set()
        for i in range(len(toks)):
            for n in (1, 2, 3):
                grupo = toks[i:i + n]
                if len(grupo) < n or not all(_NUMISH.match(t) for t in grupo):
                    break
                v = parse_importe_es(_limpia_num("".join(grupo)))
                if v is not None and (i, n) not in vistos:
                    vistos.add((i, n))
                    out[v] += 1
    return out


def ocr_pdf(pdf: Path, cache_dir: Path, dpi: int, psm: int) -> dict[int, str]:
    """TSV de Tesseract por página (cacheado por sha256 del PDF)."""
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    d = cache_dir / "ocr" / f"{sha[:16]}_r{dpi}_psm{psm}"
    d.mkdir(parents=True, exist_ok=True)
    npag = int(re.search(r"Pages:\s+(\d+)", subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout)[1])
    out = {}
    for pg in range(1, npag + 1):
        tsv = d / f"p{pg}.tsv"
        if not tsv.exists():
            png = d / f"p{pg}"
            subprocess.run(["pdftoppm", "-f", str(pg), "-l", str(pg), "-r", str(dpi), "-gray", "-png",
                            "-singlefile", str(pdf), str(png)], check=True)
            res = subprocess.run(["tesseract", f"{png}.png", "-", "-l", "spa", "--psm", str(psm), "tsv"],
                                 capture_output=True, text=True, check=True)
            tsv.write_text(res.stdout, encoding="utf-8")
            Path(f"{png}.png").unlink()
        out[pg] = tsv.read_text(encoding="utf-8")
    return out


# --------------------------------------------------------------------------------------------
# Visión
# --------------------------------------------------------------------------------------------
_S = {"anyOf": [{"type": "string"}, {"type": "null"}]}

SCHEMA = {
    "type": "object",
    "properties": {
        "cabecera": {
            "type": "object",
            "properties": {
                "nombre": _S, "estado_civil": _S, "regimen_economico": _S, "fecha_eleccion": _S,
                "fecha_credencial": _S, "circunscripcion": _S,
                "motivo": {"anyOf": [{"type": "string", "enum": ["toma_posesion", "cese", "otra"]},
                                     {"type": "null"}]},
                "lugar_firma": _S, "fecha_firma": _S,
                "cuota_irpf_texto": _S,
                "cuota_irpf_pagina": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["nombre", "estado_civil", "regimen_economico", "fecha_eleccion",
                         "fecha_credencial", "circunscripcion", "motivo", "lugar_firma", "fecha_firma",
                         "cuota_irpf_texto", "cuota_irpf_pagina"],
            "additionalProperties": False,
        },
        "partidas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pagina": {"type": "integer"},
                    "seccion": {"type": "string", "enum": list(secciones.TODAS)},
                    "clase": _S, "descripcion": _S, "situacion": _S, "fecha": _S,
                    "derecho_titulo": _S, "importe_texto": _S, "importe2_texto": _S,
                    "dudoso": {"type": "boolean"},
                },
                "required": ["pagina", "seccion", "clase", "descripcion", "situacion", "fecha",
                             "derecho_titulo", "importe_texto", "importe2_texto", "dudoso"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cabecera", "partidas"],
    "additionalProperties": False,
}

PROMPT = """Eres un transcriptor de formularios oficiales. Recibes el PDF escaneado de una declaración
de bienes y rentas de un diputado del Congreso. Transcribe su contenido al esquema JSON pedido.

Reglas generales:
- Copia LITERALMENTE lo impreso. No corrijas, no calcules, no sumes, no traduzcas, no normalices.
- Los importes se copian exactamente como aparecen, con sus puntos, comas, apóstrofos, espacios y
  símbolo € (p. ej. "756.715'12", "86.066,40", "10.146", "4000,00", "662.839,97 €").
- Una partida por cada fila rellena. Ignora las filas vacías y los textos impresos de la plantilla
  (cabeceras, notas al pie). Mantén el orden en que aparecen. "pagina" es el número de página del PDF.
- Si un campo no existe en esa sección o está vacío, usa null.
- Si dudas de algún carácter, transcribe lo que ves y marca "dudoso": true. Si es ilegible, null y
  "dudoso": true. Nunca inventes ni completes un valor.

Secciones (campo "seccion") y qué va en cada campo:
- Rentas percibidas (pág. 1): renta_salarial (percepciones netas de tipo salarial, honorarios...),
  renta_dividendos, renta_intereses, renta_otras. clase = procedencia tal cual; descripcion = concepto;
  importe_texto = euros.
- Cuota pagada por IRPF: NO es partida; va a cabecera.cuota_irpf_texto (y su página).
- Inmuebles: inmueble_urbano, inmueble_rustico, inmueble_sociedad (propiedad de una sociedad o entidad
  participada). descripcion = clase y características; situacion; fecha = fecha de adquisición;
  derecho_titulo = derecho sobre el bien y título de adquisición. Sin importe.
- deposito: descripcion = descripción de los depósitos; importe_texto = saldo.
- valores (deuda pública, obligaciones, acciones y participaciones): descripcion; importe_texto = valor.
- sociedad_participada (sociedades participadas en más de un 5% por otras sociedades del declarante):
  una partida por sociedad mencionada, descripcion = el texto. Sin importe.
- vehiculo: fecha = fecha de adquisición; descripcion. Sin importe.
- otros_bienes (otros bienes, rentas o derechos de contenido económico no declarados en apartados
  anteriores): descripcion; importe_texto = valor.
- deuda: descripcion = préstamo (descripción y acreedor); fecha = fecha de concesión;
  importe2_texto = IMPORTE CONCEDIDO; importe_texto = SALDO PENDIENTE.
- observaciones: el texto del recuadro de observaciones, una partida por párrafo, sin importe.

Cabecera: nombre y apellidos, estado civil, régimen económico matrimonial, fecha de elección,
fecha de presentación de la credencial, circunscripción; motivo de la declaración (casilla marcada:
toma_posesion, cese u otra); lugar y fecha de la firma tal cual."""


@dataclass
class RespuestaVision:
    datos: dict
    modelo: str
    tokens_entrada: int | None
    tokens_salida: int | None
    cache_path: Path


def vision_pdf(pdf: Path, cfg: config.Config, cache_dir: Path, client=None) -> RespuestaVision:
    """Llama a la API (o usa la respuesta cacheada) y devuelve el JSON validado por esquema."""
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    path = cache_dir / "vision" / f"{sha[:16]}_{cfg.modelo_vision}_{PROMPT_VERSION}_{cfg.esfuerzo_vision}.json"
    if not path.exists():
        if client is None:
            import anthropic
            # La clave puede venir de ANTHROPIC_API_KEY o inyectarse en la salida de red
            # (secretos de red del entorno); en ese caso el valor local es un marcador.
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or "inyectada-por-proxy")
        b64 = base64.standard_b64encode(pdf.read_bytes()).decode()
        # Respaldo en servidor si el modelo rechaza la petición. Haiku no lo admite.
        respaldo = {} if cfg.modelo_vision.startswith("claude-haiku") else {
            "betas": [FALLBACK_BETA], "fallbacks": "default"}
        with client.beta.messages.stream(
            model=cfg.modelo_vision,
            max_tokens=64000,
            **respaldo,
            output_config={"effort": cfg.esfuerzo_vision,
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            system=PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": "Transcribe esta declaración al esquema."},
            ]}],
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason != "end_turn":
            raise RuntimeError(f"{pdf.name}: la API terminó con stop_reason={msg.stop_reason!r} "
                               f"({getattr(msg, 'stop_details', None)})")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(msg.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    raw = json.loads(path.read_text(encoding="utf-8"))
    texto = next(b["text"] for b in raw["content"] if b["type"] == "text")
    u = raw.get("usage") or {}
    return RespuestaVision(json.loads(texto), raw.get("model", cfg.modelo_vision),
                           u.get("input_tokens"), u.get("output_tokens"), path)


# --------------------------------------------------------------------------------------------
# Consenso
# --------------------------------------------------------------------------------------------
def _cercanos(texto: str, candidatos: Counter, n: int = 3) -> str | None:
    digs = re.sub(r"\D", "", texto)
    if not candidatos or not digs:
        return None
    orden = sorted(candidatos, key=lambda v: -SequenceMatcher(None, digs, re.sub(r"\D", "", str(v))).ratio())
    return "; ".join(str(v) for v in orden[:n])


def consenso(texto: str | None, pagina: int, cifras: dict[int, Counter]) -> tuple[str | None, str, str | None]:
    """-> (importe Decimal como texto | None, estado, cifras de Tesseract más parecidas | None).
    Consume la cifra del OCR usada, para que una lectura no respalde dos importes."""
    if not texto or not texto.strip():
        return None, "vacio", None
    v = parse_importe_es(_limpia_num(texto))
    if v is None:
        return None, "ilegible", _cercanos(texto, cifras.get(pagina, Counter()))
    pag = cifras.get(pagina, Counter())
    if pag[v] > 0:
        pag[v] -= 1
        return str(v), "coinciden", None
    return None, "discrepan", _cercanos(texto, +pag)


# --------------------------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------------------------
def pdf_local(con: sqlite3.Connection, decl_id: int, cfg: config.Config) -> Path:
    from .http import PoliteClient
    from .load import upsert_source_file
    row = con.execute("""SELECT d.url, s.local_path FROM declaracion_bienes d
                         LEFT JOIN source_file s ON s.id = d.source_file_id WHERE d.id=?""", (decl_id,)).fetchone()
    if row[1] and (config.ROOT / row[1]).exists():
        return config.ROOT / row[1]
    f = PoliteClient.from_config(cfg).get(row[0])
    with con:
        fid = upsert_source_file(con, f, "docbienes")
        con.execute("UPDATE declaracion_bienes SET source_file_id=? WHERE id=?", (fid, decl_id))
    return f.path


def guardar(con: sqlite3.Connection, decl_id: int, pdf: Path, rv: RespuestaVision,
            cifras: dict[int, Counter], cfg: config.Config) -> dict[str, int]:
    estados: Counter = Counter()
    with con:
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        con.execute(
            """INSERT INTO extraccion (declaracion_id, metodo, modelo, prompt_version, pdf_sha256, cache_path,
                   tokens_entrada, tokens_salida, creada_at) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(declaracion_id, metodo, modelo, prompt_version) DO UPDATE SET
                   pdf_sha256=excluded.pdf_sha256, cache_path=excluded.cache_path""",
            (decl_id, METODO, rv.modelo, PROMPT_VERSION, sha, str(rv.cache_path.relative_to(config.ROOT))
             if rv.cache_path.is_relative_to(config.ROOT) else str(rv.cache_path),
             rv.tokens_entrada, rv.tokens_salida, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        ext_id = con.execute("SELECT id FROM extraccion WHERE declaracion_id=? AND metodo=? AND modelo=? "
                             "AND prompt_version=?", (decl_id, METODO, rv.modelo, PROMPT_VERSION)).fetchone()[0]
        # Reemplazo completo: relanzar deja exactamente el mismo resultado (idempotente).
        con.execute("DELETE FROM decl_partida WHERE declaracion_id=?", (decl_id,))
        con.execute("DELETE FROM decl_cabecera WHERE declaracion_id=?", (decl_id,))
        cif = {p: Counter(c) for p, c in cifras.items()}   # copia: consenso() consume cifras
        cab = rv.datos["cabecera"]
        irpf, irpf_est, _ = consenso(cab.get("cuota_irpf_texto"), cab.get("cuota_irpf_pagina") or 1, cif)
        con.execute(
            """INSERT INTO decl_cabecera VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (decl_id, ext_id, cab.get("nombre"), cab.get("estado_civil"), cab.get("regimen_economico"),
             cab.get("fecha_eleccion"), cab.get("fecha_credencial"), cab.get("circunscripcion"), cab.get("motivo"),
             cab.get("lugar_firma"), cab.get("fecha_firma"), irpf, cab.get("cuota_irpf_texto"), irpf_est,
             cab.get("cuota_irpf_pagina")))
        for orden, p in enumerate(rv.datos["partidas"], 1):
            imp, est, tes = consenso(p.get("importe_texto"), p["pagina"], cif)
            imp2, est2, tes2 = consenso(p.get("importe2_texto"), p["pagina"], cif)
            estados[est] += 1
            if p["seccion"] == secciones.DEUDA:
                estados[est2] += 1
            con.execute(
                """INSERT INTO decl_partida (declaracion_id, extraccion_id, pagina, orden, seccion, clase,
                       descripcion, situacion, fecha, derecho_titulo, importe, importe_texto, importe_estado,
                       importe_tesseract, importe2, importe2_texto, importe2_estado, importe2_tesseract,
                       dudoso, metodo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (decl_id, ext_id, p["pagina"], orden, p["seccion"], p.get("clase"), p.get("descripcion"),
                 p.get("situacion"), p.get("fecha"), p.get("derecho_titulo"), imp, p.get("importe_texto"), est,
                 tes, imp2, p.get("importe2_texto"), est2, tes2, int(bool(p.get("dudoso"))), METODO))
    return dict(estados)


def seleccionar(con: sqlite3.Connection, cods: list[int] | None, tipo: str | None, limit: int | None) -> list[tuple]:
    sql = "SELECT id, cod_parlamentario, tipo_codigo, url FROM declaracion_bienes WHERE 1=1"
    args: list = []
    if cods:
        sql += f" AND cod_parlamentario IN ({','.join('?' * len(cods))})"
        args += cods
    if tipo:
        sql += " AND tipo_codigo=?"
        args.append(tipo)
    sql += " ORDER BY cod_parlamentario, fecha"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql, args).fetchall()


def exportar(con: sqlite3.Connection, fuente: str) -> list[dict]:
    """Filas en el formato de rentismo.evaluate. fuente='hibrido' usa solo importes con consenso;
    'vision' usa la lectura de visión sin verificar (para medir cada método por separado)."""
    out = []
    for cod, sec, desc, imp, imp_t, imp2, imp2_t in con.execute(
            """SELECT d.cod_parlamentario, p.seccion, p.descripcion, p.importe, p.importe_texto,
                      p.importe2, p.importe2_texto
               FROM decl_partida p JOIN declaracion_bienes d ON d.id=p.declaracion_id
               WHERE d.tipo_codigo='000'"""):
        if fuente == "vision":
            imp = parse_importe_es(_limpia_num(imp_t)) if imp_t else None
            imp2 = parse_importe_es(_limpia_num(imp2_t)) if imp2_t else None
        out.append({"cod_parlamentario": cod, "seccion": sec, "descripcion": desc,
                    "valor": str(imp) if imp is not None else None,
                    "importe_concedido": str(imp2) if imp2 is not None else None})
    return out


def main(argv: list[str] | None = None) -> None:
    from .load import connect
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cod", type=int, nargs="*", help="codParlamentario")
    ap.add_argument("--tipo", help="'000' inicial, '001' modificación")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--solo-ocr", action="store_true", help="solo Tesseract (sin llamadas a la API)")
    ap.add_argument("--export", help="escribir filas para rentismo.evaluate y salir")
    ap.add_argument("--fuente", choices=["hibrido", "vision"], default="hibrido")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load()
    con = connect(cfg.sqlite_path)
    if args.export:
        Path(args.export).write_text(json.dumps(exportar(con, args.fuente), ensure_ascii=False, indent=1))
        print(f"exportado a {args.export}")
        return
    cache = cfg.cache_dir.parent / "derived"
    total: Counter = Counter()
    for decl_id, cod, tipo, url in seleccionar(con, args.cod, args.tipo, args.limit):
        pdf = pdf_local(con, decl_id, cfg)
        tsvs = ocr_pdf(pdf, cache, cfg.ocr_dpi, cfg.tesseract_psm)
        cifras = {p: numeros_tsv(t) for p, t in tsvs.items()}
        if args.solo_ocr:
            log.info("cod %s %s: OCR listo (%d cifras)", cod, tipo, sum(sum(c.values()) for c in cifras.values()))
            continue
        rv = vision_pdf(pdf, cfg, cache)
        est = guardar(con, decl_id, pdf, rv, cifras, cfg)
        total.update(est)
        log.info("cod %s %s: %d partidas, importes %s", cod, tipo, len(rv.datos["partidas"]), est)
    if total:
        print("importes por estado:", dict(total))


if __name__ == "__main__":
    main()
