"""Carga de config.toml (decisiones del proyecto) y .env (secretos)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    legislaturas: tuple[str, ...]
    campos_bienes: str
    metodo_extraccion: str
    destino: str
    sqlite_path: Path
    cache_dir: Path
    user_agent: str
    min_intervalo_s: float
    reintentos: int
    backoff_base_s: float
    timeout_s: float
    ttl_indice_h: float
    indice_opendata: str
    ficha_url: str
    xerraires_repo: str
    xerraires_commit: str


def load(path: Path | None = None) -> Config:
    _load_dotenv(ROOT / ".env")
    path = path or Path(os.environ.get("RENTISMO_CONFIG", ROOT / "config.toml"))
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    d = raw["descargas"]
    cfg = Config(
        legislaturas=tuple(raw["alcance"]["legislaturas"]),
        campos_bienes=raw["bienes_rentas"]["campos"],
        metodo_extraccion=raw["bienes_rentas"].get("metodo_extraccion", ""),
        destino=raw["destino"]["tipo"],
        sqlite_path=ROOT / raw["destino"]["sqlite_path"],
        cache_dir=ROOT / d["cache_dir"],
        user_agent=d["user_agent"],
        min_intervalo_s=max(1.0, float(d["min_intervalo_s"])),  # nunca por debajo de 1 s
        reintentos=int(d["reintentos"]),
        backoff_base_s=float(d["backoff_base_s"]),
        timeout_s=float(d["timeout_s"]),
        ttl_indice_h=float(d["ttl_indice_h"]),
        indice_opendata=raw["fuentes"]["indice_opendata"],
        ficha_url=raw["docbienes"]["ficha_url"],
        xerraires_repo=raw["xerraires"]["repo"],
        xerraires_commit=raw["xerraires"]["commit"],
    )
    if cfg.campos_bienes not in {"completo", "agregados"}:
        raise ValueError(f"bienes_rentas.campos inválido: {cfg.campos_bienes!r}")
    if cfg.destino != "sqlite":
        raise NotImplementedError(f"Destino {cfg.destino!r} no implementado (solo sqlite)")
    return cfg
