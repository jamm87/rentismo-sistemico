"""Cliente HTTP educado: rate limiting, User-Agent, reintentos con backoff y caché en disco.

Cada URL se guarda una sola vez en ``cache_dir`` junto a un ``.meta.json`` con la URL,
la fecha de descarga, el código HTTP y el sha256. Las URL con timestamp (JSON del
Congreso) o numeradas (PDF del BOCG) son inmutables, así que la caché no expira.
Para páginas que cambian (el índice) se pasa ``max_age_s``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class CachedFile:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    from_cache: bool

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def cache_path(cache_dir: Path, url: str) -> Path:
    """Ruta estable y legible: host/ruta_saneada con hash corto para evitar colisiones."""
    p = urlparse(url)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", (p.path + ("?" + p.query if p.query else "")).strip("/"))
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    stem, dot, ext = name[-150:].rpartition(".")
    fname = f"{stem}.{digest}.{ext}" if dot else f"{name[-150:]}.{digest}"
    return cache_dir / p.netloc / fname


class PoliteClient:
    def __init__(self, cache_dir: Path, user_agent: str, min_interval_s: float = 1.0,
                 retries: int = 5, backoff_base_s: float = 2.0, timeout_s: float = 60,
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic):
        self.cache_dir = cache_dir
        self.min_interval_s = max(1.0, min_interval_s)
        self.retries = retries
        self.backoff_base_s = backoff_base_s
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_config(cls, cfg) -> "PoliteClient":
        return cls(cfg.cache_dir, cfg.user_agent, cfg.min_intervalo_s, cfg.reintentos,
                   cfg.backoff_base_s, cfg.timeout_s)

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval_s - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def get(self, url: str, max_age_s: float | None = None) -> CachedFile:
        path = cache_path(self.cache_dir, url)
        meta_path = path.with_name(path.name + ".meta.json")
        if path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            age = time.time() - datetime.fromisoformat(meta["fetched_at"]).timestamp()
            if max_age_s is None or age < max_age_s:
                return CachedFile(url, path, meta["sha256"], meta["fetched_at"], True)

        body, status = self._download(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(path)
        sha = hashlib.sha256(body).hexdigest()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta_path.write_text(json.dumps(
            {"url": url, "fetched_at": fetched_at, "status": status, "sha256": sha, "bytes": len(body)},
            ensure_ascii=False, indent=1))
        return CachedFile(url, path, sha, fetched_at, False)

    def _download(self, url: str) -> tuple[bytes, int]:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, timeout=self.timeout_s)
                if r.status_code in RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                log.info("GET %s -> %s (%d bytes)", url, r.status_code, len(r.content))
                return r.content, r.status_code
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                resp = getattr(exc, "response", None)
                if resp is not None and resp.status_code not in RETRY_STATUS:
                    raise  # 404 y similares: no tiene sentido reintentar
                last_exc = exc
                if attempt < self.retries:
                    delay = self.backoff_base_s * 2 ** attempt
                    log.warning("Fallo en %s (%s); reintento %d en %.0fs", url, exc, attempt + 1, delay)
                    self._sleep(delay)
        raise RuntimeError(f"No se pudo descargar {url} tras {self.retries + 1} intentos") from last_exc
