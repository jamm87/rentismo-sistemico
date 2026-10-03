"""Carga en SQLite de los JSON de datos abiertos. Idempotente.

Uso:
    python -m rentismo.load          # descarga (o usa caché) y carga
    python -m rentismo.load --stats  # solo muestra recuentos
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

from . import config
from .fetch_opendata import DatasetLink, fetch_all, load_records
from .http import CachedFile
from .normalize import name_key, parse_fecha_es

log = logging.getLogger(__name__)

SCHEMA = config.ROOT / "db" / "schema.sql"

DOCACTECO_FIELDS = ["DECLARACION", "TIPO", "PERIODO", "EMPLEADOR", "SECTOR", "DESCRIPCION",
                    "DESTINATARIO", "BENEFACTOR", "OBSERVACIONES"]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def upsert_source_file(con: sqlite3.Connection, f: CachedFile, dataset: str) -> int:
    con.execute(
        """INSERT INTO source_file (url, dataset, sha256, fetched_at, local_path) VALUES (?,?,?,?,?)
           ON CONFLICT(url) DO UPDATE SET sha256=excluded.sha256""",
        (f.url, dataset, f.sha256, f.fetched_at, str(f.path.relative_to(config.ROOT))
         if f.path.is_relative_to(config.ROOT) else str(f.path)))
    return con.execute("SELECT id FROM source_file WHERE url=?", (f.url,)).fetchone()[0]


def record_hashes(records: list[dict]) -> list[str]:
    """Hash por contenido; los registros idénticos dentro del fichero se distinguen por ocurrencia."""
    seen: Counter = Counter()
    out = []
    for r in records:
        canon = json.dumps(r, sort_keys=True, ensure_ascii=False)
        seen[canon] += 1
        out.append(hashlib.sha256(f"{canon}\x00{seen[canon]}".encode()).hexdigest())
    return out


def load_raw(con: sqlite3.Connection, dataset: str, file_id: int, records: list[dict]) -> int:
    before = con.total_changes
    for rec, h in zip(records, record_hashes(records)):
        con.execute(
            """INSERT INTO opendata_raw (dataset, record_hash, record_json, first_file_id, last_file_id)
               VALUES (?,?,?,?,?)
               ON CONFLICT(dataset, record_hash) DO UPDATE SET last_file_id=excluded.last_file_id""",
            (dataset, h, json.dumps(rec, ensure_ascii=False), file_id, file_id))
    return con.total_changes - before


def _txt(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def load_docacteco(con: sqlite3.Connection) -> int:
    """Deriva interes_economico desde opendata_raw. Solo inserta las filas nuevas."""
    rows = con.execute(
        """SELECT r.id, r.record_json FROM opendata_raw r
           LEFT JOIN interes_economico i ON i.raw_id = r.id
           WHERE r.dataset = 'docacteco' AND i.id IS NULL""").fetchall()
    for raw_id, js in rows:
        rec = json.loads(js)
        nombre = _txt(rec.get("NOMBRE")) or ""
        fecha_orig = _txt(rec.get("FECHAREGISTRO"))
        fecha = parse_fecha_es(fecha_orig)
        con.execute(
            f"""INSERT INTO interes_economico
                (raw_id, nombre, nombre_key, fecha_registro, fecha_registro_original,
                 {', '.join(f.lower() for f in DOCACTECO_FIELDS)})
                VALUES (?,?,?,?,?, {', '.join('?' * len(DOCACTECO_FIELDS))})""",
            (raw_id, nombre, name_key(nombre), fecha.isoformat() if fecha else None, fecha_orig,
             *(_txt(rec.get(f)) for f in DOCACTECO_FIELDS)))
    return len(rows)


def run(cfg: config.Config, files: list[tuple[DatasetLink, CachedFile]]) -> None:
    con = connect(cfg.sqlite_path)
    with con:
        for link, f in files:
            fid = upsert_source_file(con, f, link.dataset)
            n = load_raw(con, link.dataset, fid, load_records(f))
            log.info("%-40s %d filas nuevas/actualizadas", link.dataset, n)
        log.info("interes_economico: %d filas nuevas", load_docacteco(con))
    print(stats(con))


def stats(con: sqlite3.Connection) -> str:
    lines = ["opendata_raw por dataset:"]
    for ds, n in con.execute("SELECT dataset, COUNT(*) FROM opendata_raw GROUP BY dataset ORDER BY dataset"):
        lines.append(f"  {ds:<40} {n:>7}")
    for t in ("source_file", "interes_economico", "revision_manual"):
        lines.append(f"{t}: {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    lines.append("interes_economico por tipo:")
    for tipo, n in con.execute("SELECT tipo, COUNT(*) FROM interes_economico GROUP BY tipo ORDER BY 2 DESC"):
        lines.append(f"  {str(tipo):<20} {n:>7}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load()
    if args.stats:
        print(stats(connect(cfg.sqlite_path)))
        return
    run(cfg, fetch_all(cfg))


if __name__ == "__main__":
    main()
