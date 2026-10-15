"""Descubrimiento y descarga de las declaraciones de bienes y rentas (ruta docbienes).

Cada diputado tiene una ficha en congreso.es con enlaces a sus PDF:
    /docbienes/leg15/000150/000150_000_e_0000648_20230808.pdf
                     id     id    tipo   nº reg   fecha

OJO: ese ``id`` de la ruta NO es el codParlamentario (difiere en 326 de 350 diputados de la
XV; p. ej. Abades Martínez: codParlamentario 160, id 150). Se guarda como ``id_docbienes`` y el
codParlamentario se toma siempre de otra fuente (ficha consultada o registro de xerraires).

El campo ``tipo`` ('000') codifica el tipo de declaración (0 = inicial, 1 = modificación,
2 = final). Verificado: 000 y 001 aparecen en fichas reales (001 con fecha posterior a la
inicial); 002 aún no se ha visto. Se guarda el código tal cual y la interpretación aparte.

Uso:
    python -m rentismo.fetch_docbienes --discover   # recorre fichas y registra URL
    python -m rentismo.fetch_docbienes --download   # descarga los PDF registrados
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode, urljoin

from . import config
from .http import PoliteClient

log = logging.getLogger(__name__)

BASE = "https://www.congreso.es"
_HREF_RE = re.compile(r'href="(/docbienes/[^"]+\.pdf)"', re.I)
_PATH_RE = re.compile(
    r"/docbienes/leg(?P<leg>\d+)/(?P<dir>\d+)/(?P<cod>\d+)_(?P<tipo>\d{3})_(?P<letra>[a-z])_"
    r"(?P<reg>\d+)_(?P<fecha>\d{8})\.pdf$", re.I)
TIPOS = {0: "inicial", 1: "modificacion", 2: "final"}
ROMANOS = {"XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15}


@dataclass(frozen=True)
class DocBienes:
    url: str
    id_docbienes: int      # id de la ruta del PDF; NO es el codParlamentario
    legislatura: int
    tipo_codigo: str
    tipo: str | None
    num_registro: str
    fecha: str | None


def parse_docbienes_url(url: str) -> DocBienes | None:
    m = _PATH_RE.search(url)
    if not m:
        return None
    f = m["fecha"]
    try:
        fecha = date(int(f[:4]), int(f[4:6]), int(f[6:])).isoformat()
    except ValueError:
        fecha = None
    return DocBienes(urljoin(BASE, m.group(0)), int(m["cod"]), int(m["leg"]), m["tipo"],
                     TIPOS.get(int(m["tipo"])), m["reg"], fecha)


def links_from_ficha(html: str) -> list[DocBienes]:
    out, seen = [], set()
    for href in _HREF_RE.findall(html):
        d = parse_docbienes_url(href)
        if d is None:
            log.warning("Enlace docbienes con formato no reconocido: %s", href)
        elif d.url not in seen:
            seen.add(d.url)
            out.append(d)
    return out


def register(con: sqlite3.Connection, d: DocBienes, cod_parlamentario: int, descubierta_por: str,
             ficha_url: str | None = None) -> bool:
    cur = con.execute(
        """INSERT INTO declaracion_bienes (url, cod_parlamentario, id_docbienes, legislatura, tipo_codigo,
               tipo, num_registro, fecha, ficha_url, descubierta_por)
           VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO NOTHING""",
        (d.url, cod_parlamentario, d.id_docbienes, d.legislatura, d.tipo_codigo, d.tipo, d.num_registro, d.fecha,
         ficha_url, descubierta_por))
    return cur.rowcount > 0


def known_codes(con: sqlite3.Connection) -> list[int]:
    # TODO: añadir la tabla `diputado` de datos abiertos cuando exista (Fase 1).
    return [r[0] for r in con.execute(
        "SELECT cod_parlamentario FROM ext_xerraires_diputado "
        "UNION SELECT cod_parlamentario FROM declaracion_bienes ORDER BY 1")]


def discover(cfg: config.Config, con: sqlite3.Connection, client: PoliteClient) -> int:
    nuevas = 0
    for leg in cfg.legislaturas:
        for cod in known_codes(con):
            url = f"{cfg.ficha_url}&{urlencode({'codParlamentario': cod, 'idLegislatura': leg})}"
            # La ficha cambia cuando se publica una declaración nueva: refresco diario.
            html = client.get(url, max_age_s=cfg.ttl_indice_h * 3600).read_bytes().decode("utf-8", "replace")
            docs = links_from_ficha(html)
            if not docs:
                log.info("cod %s: ficha sin declaraciones", cod)
            with con:
                nuevas += sum(register(con, d, cod, "ficha", url) for d in docs)
    return nuevas


def download(cfg: config.Config, con: sqlite3.Connection, client: PoliteClient) -> int:
    from .load import upsert_source_file
    rows = con.execute("SELECT id, url FROM declaracion_bienes WHERE source_file_id IS NULL "
                       "AND legislatura IN (%s)" % ",".join("?" * len(cfg.legislaturas)),
                       [ROMANOS[l] for l in cfg.legislaturas]).fetchall()
    for decl_id, url in rows:
        f = client.get(url)
        with con:
            fid = upsert_source_file(con, f, "docbienes")
            con.execute("UPDATE declaracion_bienes SET source_file_id=? WHERE id=?", (fid, decl_id))
    return len(rows)


def main(argv: list[str] | None = None) -> None:
    from .load import connect
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load()
    con, client = connect(cfg.sqlite_path), PoliteClient.from_config(cfg)
    if args.discover:
        print(f"declaraciones nuevas: {discover(cfg, con, client)}")
    if args.download:
        print(f"PDF descargados: {download(cfg, con, client)}")


if __name__ == "__main__":
    main()
