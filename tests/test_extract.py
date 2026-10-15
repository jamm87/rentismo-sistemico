import json
from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

from rentismo import extract, secciones
from rentismo.load import connect

HDR = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*lineas):
    rows = [HDR]
    for li, palabras in enumerate(lineas, 1):
        for wi, w in enumerate(palabras.split(" "), 1):
            rows.append(f"5\t1\t1\t1\t{li}\t{wi}\t0\t0\t1\t1\t95\t{w}")
    return "\n".join(rows)


def test_numeros_tsv_une_cifras_partidas_y_ignora_texto():
    c = extract.numeros_tsv(tsv("PRESTAMO SANTANDER 2021 60.000 € 56 .419€", "Acciones 756.715'12", "ruido 12.34"))
    assert c[Decimal("56419")] == 1          # '56' + '.419€' unidos
    assert c[Decimal("60000")] == 1 and c[Decimal("756715.12")] == 1
    assert Decimal("12.34") not in c         # ambiguo: no se interpreta


def test_consenso_acepta_solo_si_coinciden_y_consume():
    cif = {3: Counter({Decimal("185005.78"): 1, Decimal("141600.00"): 1})}
    assert extract.consenso("141.600'00", 3, cif) == ("141600.00", "coinciden", None)
    assert extract.consenso("141.600'00", 3, cif)[1] == "discrepan"   # la cifra ya se usó
    imp, est, tes = extract.consenso("195.005'79", 3, cif)
    assert (imp, est) == (None, "discrepan") and "185005.78" in tes       # se guarda la lectura de Tesseract
    assert extract.consenso(None, 3, cif)[1] == "vacio"
    assert extract.consenso("12.34", 3, cif)[:2] == (None, "ilegible")
    assert extract.consenso("1.000", 9, cif)[1] == "discrepan"          # otra página: no vale


def _datos():
    return {"cabecera": {"nombre": "JUAN PÉREZ", "estado_civil": "CASADO", "regimen_economico": None,
                         "fecha_eleccion": None, "fecha_credencial": None, "circunscripcion": "JAÉN",
                         "motivo": "toma_posesion", "lugar_firma": "MADRID", "fecha_firma": None,
                         "cuota_irpf_texto": "1.234,00", "cuota_irpf_pagina": 1},
            "partidas": [
                {"pagina": 4, "seccion": "deuda", "clase": None, "descripcion": "HIPOTECA", "situacion": None,
                 "fecha": "2021", "derecho_titulo": None, "importe_texto": "56.419 €",
                 "importe2_texto": "60.000 €", "dudoso": False},
                {"pagina": 3, "seccion": "valores", "clase": None, "descripcion": "Acciones X", "situacion": None,
                 "fecha": None, "derecho_titulo": None, "importe_texto": "195.005'79", "importe2_texto": None,
                 "dudoso": True},
                {"pagina": 3, "seccion": "vehiculo", "clase": None, "descripcion": "BMW", "situacion": None,
                 "fecha": "2016", "derecho_titulo": None, "importe_texto": None, "importe2_texto": None,
                 "dudoso": False}]}


def test_guardar_idempotente_y_cola_de_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(extract.config, "ROOT", tmp_path)
    con = connect(tmp_path / "t.sqlite")
    with con:
        con.execute("INSERT INTO declaracion_bienes (url, cod_parlamentario, id_docbienes, legislatura, tipo_codigo,"
                    " descubierta_por) VALUES ('https://x/a.pdf', 12, 14, 15, '000', 'ficha')")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-falso")
    rv = extract.RespuestaVision(_datos(), "claude-opus-5-5", 100, 50, tmp_path / "v.json")
    cifras = {1: Counter({Decimal("1234.00"): 1}),
              3: Counter({Decimal("185005.78"): 1}),
              4: Counter({Decimal("56419"): 1, Decimal("60000"): 1})}
    for _ in range(2):
        est = extract.guardar(con, 1, pdf, rv, cifras, None)
    assert est == {"coinciden": 2, "discrepan": 1, "vacio": 1}
    rows = con.execute("SELECT seccion, importe, importe_estado, importe2, importe2_estado, dudoso "
                       "FROM decl_partida ORDER BY orden").fetchall()
    assert rows == [("deuda", "56419", "coinciden", "60000", "coinciden", 0),
                    ("valores", None, "discrepan", None, "vacio", 1),
                    ("vehiculo", None, "vacio", None, "vacio", 0)]
    assert con.execute("SELECT COUNT(*) FROM extraccion").fetchone()[0] == 1
    assert con.execute("SELECT cuota_irpf, cuota_irpf_estado FROM decl_cabecera").fetchone() == ("1234.00", "coinciden")
    rev = con.execute("SELECT cod_parlamentario, url, pagina, vision, tesseract FROM v_revision_importes").fetchall()
    assert rev == [(12, "https://x/a.pdf", 3, "195.005'79", "185005.78")]


class FakeStream:
    def __init__(self, calls, payload):
        self.calls, self.payload = calls, payload

    def __call__(self, **kw):
        self.calls.append(kw)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        d = {"model": "claude-opus-5-5", "stop_reason": "end_turn",
             "usage": {"input_tokens": 13000, "output_tokens": 4000},
             "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(self.payload)}]}
        return SimpleNamespace(stop_reason="end_turn", to_dict=lambda: d)


def test_vision_pdf_parametros_y_cache(tmp_path):
    calls = []
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=FakeStream(calls, _datos()))))
    cfg = SimpleNamespace(modelo_vision="claude-opus-5-5", esfuerzo_vision="medium")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-falso")
    for _ in range(2):
        rv = extract.vision_pdf(pdf, cfg, tmp_path, client=client)
    assert len(calls) == 1                                   # la segunda vez sale de la caché
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["format"]["schema"] is extract.SCHEMA
    assert kw["messages"][0]["content"][0]["source"]["media_type"] == "application/pdf"
    assert rv.datos == _datos() and (rv.tokens_entrada, rv.tokens_salida) == (13000, 4000)


def test_schema_estricto():
    """Salida estructurada: todo objeto con additionalProperties=false y todas sus claves requeridas."""
    def check(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                check(v)
        if s.get("type") == "array":
            check(s["items"])
    check(extract.SCHEMA)
    assert set(extract.SCHEMA["properties"]["partidas"]["items"]["properties"]["seccion"]["enum"]) == set(secciones.TODAS)
