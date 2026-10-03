import json
from pathlib import Path

import requests

from rentismo import load
from rentismo.fetch_opendata import parse_index
from rentismo.http import PoliteClient, cache_path

FIX = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, timeout):
        self.calls.append(url)
        return self.responses.pop(0)


def make_client(tmp_path, responses):
    sleeps, t = [], [0.0]
    sess = FakeSession(responses)
    c = PoliteClient(tmp_path, "test-agent", min_interval_s=0.1, retries=3, backoff_base_s=2,
                     session=sess, sleep=sleeps.append, clock=lambda: t[0])
    return c, sess, sleeps


def test_parse_index_picks_latest_json_only():
    links = parse_index((FIX / "indice_sintetico.html").read_text(), "https://www.congreso.es/es/opendata/diputados")
    assert [(l.dataset, l.timestamp) for l in links] == [
        ("DiputadosActivos", "20261002050008"), ("docacteco", "20261002050010")]
    assert links[0].url.startswith("https://www.congreso.es/webpublica/")


def test_client_caches_retries_and_rate_limits(tmp_path):
    c, sess, sleeps = make_client(tmp_path, [FakeResponse(503), FakeResponse(200, b"[1]")])
    f = c.get("https://x.test/a__1.json")
    assert f.read_bytes() == b"[1]" and not f.from_cache
    assert sleeps[0] == 2                 # backoff tras el 503
    assert min(sleeps[1:]) >= 1.0         # el intervalo mínimo se fuerza a >= 1 s
    again = c.get("https://x.test/a__1.json")
    assert again.from_cache and len(sess.calls) == 2   # no vuelve a la red


def test_client_does_not_retry_404(tmp_path):
    c, sess, _ = make_client(tmp_path, [FakeResponse(404)])
    try:
        c.get("https://x.test/nope")
    except requests.HTTPError:
        pass
    assert len(sess.calls) == 1 and not cache_path(tmp_path, "https://x.test/nope").exists()


def test_load_is_idempotent(tmp_path, monkeypatch):
    recs = [
        {"NOMBRE": "Pérez García,Juan", "FECHAREGISTRO": "05/09/2023", "DECLARACION": "Declaración inicial",
         "TIPO": "ACTIVIDAD", "EMPLEADOR": "ACME", "SECTOR": "Privado"},
        {"NOMBRE": "Pérez García,Juan", "FECHAREGISTRO": "fecha rota", "TIPO": "OBSERVACIONES",
         "OBSERVACIONES": "  "},
    ]
    p = tmp_path / "docacteco__1.json"
    p.write_text(json.dumps(recs))
    monkeypatch.setattr(load.config, "ROOT", tmp_path)
    from rentismo.fetch_opendata import DatasetLink
    from rentismo.http import CachedFile
    files = [(DatasetLink("docacteco", "1", "https://x.test/docacteco__1.json", ""),
              CachedFile("https://x.test/docacteco__1.json", p, "abc", "2026-10-03T00:00:00+00:00", True))]
    con = load.connect(tmp_path / "t.sqlite")
    for _ in range(2):
        with con:
            fid = load.upsert_source_file(con, files[0][1], "docacteco")
            load.load_raw(con, "docacteco", fid, recs)
            load.load_docacteco(con)
    rows = con.execute("SELECT nombre_key, fecha_registro, fecha_registro_original, empleador, observaciones "
                       "FROM interes_economico ORDER BY id").fetchall()
    assert rows == [("PEREZ GARCIA, JUAN", "2023-09-05", "05/09/2023", "ACME", None),
                    ("PEREZ GARCIA, JUAN", None, "fecha rota", None, None)]
    assert con.execute("SELECT COUNT(*) FROM opendata_raw").fetchone()[0] == 2
