"""Fase 1: descubre en la página índice los JSON vigentes y los descarga a la caché.

Las URL llevan un timestamp que cambia a diario, por eso no se hardcodean:
se parsea el índice y se clasifica cada enlace por el prefijo del fichero
(lo que va antes de ``__<timestamp>.json``).

Uso:
    python -m rentismo.fetch_opendata            # descarga
    python -m rentismo.fetch_opendata --inspect  # descarga y muestra la estructura de cada JSON
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import config
from .http import CachedFile, PoliteClient

log = logging.getLogger(__name__)

_FILE_RE = re.compile(r"^(?P<prefix>.+?)__(?P<ts>\d{8,14})\.json$", re.I)


@dataclass(frozen=True)
class DatasetLink:
    dataset: str      # prefijo del fichero, p. ej. "DiputadosActivos", "docacteco"
    timestamp: str    # p. ej. "20261002050008"
    url: str
    label: str        # texto del enlace en la página


def parse_index(html: str, base_url: str) -> list[DatasetLink]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, DatasetLink] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        fname = PurePosixPath(urlparse(url).path).name
        m = _FILE_RE.match(fname)
        if not m:
            continue
        link = DatasetLink(m["prefix"], m["ts"], url, " ".join(a.get_text().split()))
        prev = found.get(link.dataset)
        if prev is None or link.timestamp > prev.timestamp:  # si aparece dos veces, la más reciente
            found[link.dataset] = link
    return sorted(found.values(), key=lambda l: l.dataset)


def load_records(f: CachedFile) -> list[dict]:
    data = json.loads(f.read_bytes().decode("utf-8-sig"))
    if isinstance(data, list):
        return data
    raise ValueError(f"{f.url}: se esperaba una lista JSON, llegó {type(data).__name__}")


def fetch_all(cfg: config.Config, client: PoliteClient | None = None) -> list[tuple[DatasetLink, CachedFile]]:
    client = client or PoliteClient.from_config(cfg)
    index = client.get(cfg.indice_opendata, max_age_s=cfg.ttl_indice_h * 3600)
    links = parse_index(index.read_bytes().decode("utf-8", "replace"), cfg.indice_opendata)
    if not links:
        raise RuntimeError("No se encontró ningún enlace JSON en el índice: ¿ha cambiado la página?")
    out = []
    for link in links:
        f = client.get(link.url)
        log.info("%-40s %s %s", link.dataset, "cache" if f.from_cache else "nuevo", f.path)
        out.append((link, f))
    return out


def inspect(link: DatasetLink, f: CachedFile, examples: int = 2) -> str:
    recs = load_records(f)
    keys = Counter(k for r in recs for k in r)
    lines = [f"== {link.dataset} ({link.label!r}) — {len(recs)} registros", f"   {link.url}"]
    for k, n in keys.most_common():
        vals = [r[k] for r in recs if r.get(k) not in (None, "")][:examples]
        lines.append(f"   {k:<28} {n:>6}/{len(recs)}  ej: {vals!r}"[:220])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect", action="store_true", help="mostrar campos y ejemplos de cada dataset")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load()
    for link, f in fetch_all(cfg):
        if args.inspect:
            print(inspect(link, f))


if __name__ == "__main__":
    main()
