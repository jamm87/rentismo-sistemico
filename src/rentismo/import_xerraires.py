"""Importa el snapshot de xerraires/diputados (fijado a un commit) en tablas ext_xerraires_*.

Es una fuente externa: OCR con Tesseract + revisión manual de terceros, solo declaraciones
iniciales, sin rentas y sin nº de página. Se usa (1) como referencia para evaluar nuestra
extracción y (2) como dato consultable, siempre separado de lo que extraemos nosotros.

Interpretación de importes (en el origen están en los campos 'titulo'/'derecho'):
  - depósitos, valores, otros bienes: valor = titulo
  - deudas: valor (saldo pendiente) = titulo; importe_concedido = derecho
Si el texto tiene cifras pero no un importe inequívoco -> NULL + flag 'ilegible'.

Uso:
    python -m rentismo.import_xerraires
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from . import config, secciones
from .fetch_docbienes import parse_docbienes_url, register
from .http import CachedFile, PoliteClient
from .load import connect, record_hashes, upsert_source_file
from .normalize import name_key, parse_fecha_es, parse_importe_es

log = logging.getLogger(__name__)


def raw_url(cfg: config.Config, fname: str) -> str:
    return f"https://raw.githubusercontent.com/{cfg.xerraires_repo}/{cfg.xerraires_commit}/{fname}"


def _t(v) -> str | None:
    v = (str(v) if v is not None else "").strip()
    return v or None


def importe(texto: str | None) -> tuple[str | None, str | None]:
    """-> (Decimal como texto | None, flag | None)."""
    if not texto:
        return None, "ausente"
    v = parse_importe_es(texto)
    if v is not None:
        return str(v), None
    return None, "ilegible" if re.search(r"\d", texto) else "ausente"


def interpretar_importes(seccion: str, derecho: str | None, titulo: str | None) -> dict:
    out = {"valor": None, "valor_flag": None, "importe_concedido": None, "importe_concedido_flag": None}
    if seccion in secciones.CON_IMPORTE:
        out["valor"], out["valor_flag"] = importe(titulo)
    if seccion == secciones.DEUDA:
        out["importe_concedido"], out["importe_concedido_flag"] = importe(derecho)
    return out


def load_diputados(con: sqlite3.Connection, f: CachedFile) -> int:
    fid = upsert_source_file(con, f, "xerraires:diputados")
    n = 0
    for d in json.loads(f.read_bytes()):
        alta, baja = parse_fecha_es(d.get("fchAlta")), parse_fecha_es(d.get("fchBaja"))
        con.execute(
            """INSERT INTO ext_xerraires_diputado VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(cod_parlamentario) DO UPDATE SET source_file_id=excluded.source_file_id,
                 apellidos_nombre=excluded.apellidos_nombre, nombre_key=excluded.nombre_key,
                 formacion=excluded.formacion, grupo=excluded.grupo, fecha_baja=excluded.fecha_baja,
                 pdf_url=excluded.pdf_url""",
            (int(d["codParlamentario"]), fid, d["apellidosNombre"], name_key(d["apellidosNombre"]),
             _t(d.get("apellidos")), _t(d.get("nombre")), d.get("genero"), _t(d.get("formacion")),
             _t(d.get("grupo")), d.get("idCircunscripcion"), _t(d.get("nombreCircunscripcion")),
             alta.isoformat() if alta else None, baja.isoformat() if baja else None,
             _t(d.get("url_ficha_bienes"))))
        doc = parse_docbienes_url(d.get("url_ficha_bienes") or "")
        if doc:
            register(con, doc, "xerraires")
        n += 1
    return n


def load_bienes(con: sqlite3.Connection, f: CachedFile) -> int:
    fid = upsert_source_file(con, f, "xerraires:bienes")
    recs = json.loads(f.read_bytes())
    seen: dict[str, int] = {}
    nuevas = 0
    for r, h in zip(recs, record_hashes(recs)):
        canon = json.dumps(r, sort_keys=True, ensure_ascii=False)
        seen[canon] = seen.get(canon, 0) + 1
        sec = secciones.from_xerraires(r["seccion"])
        derecho, titulo = _t(r.get("derecho")), _t(r.get("titulo"))
        imp = interpretar_importes(sec, derecho, titulo)
        cur = con.execute(
            """INSERT INTO ext_xerraires_bien (source_file_id, record_hash, ocurrencia, cod_parlamentario,
                   nombre, seccion_original, seccion, descripcion, situacion, fecha, derecho, titulo,
                   valor, valor_flag, importe_concedido, importe_concedido_flag, audit, fuente_nota, pr)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(record_hash) DO NOTHING""",
            (fid, h, seen[canon], int(r["cod"]), r["nombre"], r["seccion"], sec, _t(r.get("descripcion")),
             _t(r.get("situacion")), _t(r.get("fecha")), derecho, titulo, imp["valor"], imp["valor_flag"],
             imp["importe_concedido"], imp["importe_concedido_flag"], _t(r.get("_audit")),
             _t(r.get("_fuente")), _t(r.get("_pr"))))
        nuevas += cur.rowcount
    return nuevas


def run(cfg: config.Config, client: PoliteClient | None = None) -> sqlite3.Connection:
    client = client or PoliteClient.from_config(cfg)
    con = connect(cfg.sqlite_path)
    dip = client.get(raw_url(cfg, "diputados.json"))
    bie = client.get(raw_url(cfg, "bienes.json"))
    with con:
        log.info("diputados: %d", load_diputados(con, dip))
        log.info("bienes nuevos: %d", load_bienes(con, bie))
    return con


def stats(con: sqlite3.Connection) -> str:
    q = lambda sql: con.execute(sql).fetchall()
    lines = [f"ext_xerraires_diputado: {q('SELECT COUNT(*) FROM ext_xerraires_diputado')[0][0]}",
             f"ext_xerraires_bien: {q('SELECT COUNT(*) FROM ext_xerraires_bien')[0][0]} "
             f"(repetidas: {q('SELECT COUNT(*) FROM ext_xerraires_bien WHERE ocurrencia>1')[0][0]})",
             f"declaracion_bienes: {q('SELECT COUNT(*) FROM declaracion_bienes')[0][0]}",
             "", f"{'sección':<18}{'filas':>7}{'valor ok':>10}{'ilegible':>10}{'ausente':>9}"]
    for sec, n, ok, ileg, aus in q(
            """SELECT seccion, COUNT(*), SUM(valor IS NOT NULL), SUM(valor_flag='ilegible'),
                      SUM(valor_flag='ausente') FROM ext_xerraires_bien GROUP BY seccion ORDER BY 2 DESC"""):
        lines.append(f"{sec:<18}{n:>7}{ok or 0:>10}{ileg or 0:>10}{aus or 0:>9}")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(stats(run(config.load())))


if __name__ == "__main__":
    main()
