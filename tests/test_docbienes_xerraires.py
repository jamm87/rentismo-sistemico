import json

from rentismo import secciones
from rentismo.evaluate import evaluar
from rentismo.fetch_docbienes import links_from_ficha, parse_docbienes_url
from rentismo.import_xerraires import interpretar_importes, load_bienes, load_diputados
from rentismo.http import CachedFile
from rentismo.load import connect


def test_parse_docbienes_url():
    d = parse_docbienes_url("/docbienes/leg15/000150/000150_000_e_0000648_20230808.pdf")
    assert (d.cod_parlamentario, d.legislatura, d.tipo_codigo, d.tipo, d.num_registro, d.fecha) == (
        150, 15, "000", "inicial", "0000648", "2023-08-08")
    assert d.url == "https://www.congreso.es/docbienes/leg15/000150/000150_000_e_0000648_20230808.pdf"
    assert parse_docbienes_url("/docbienes/leg15/x.pdf") is None


def test_links_from_ficha_dedupes_and_keeps_all_types():
    html = ('<a href="/docbienes/leg15/000001/000001_000_e_0000001_20230801.pdf">I</a>'
            '<a href="/docbienes/leg15/000001/000001_001_e_0000002_20240101.pdf">M</a>'
            '<a href="/docbienes/leg15/000001/000001_000_e_0000001_20230801.pdf">dup</a>')
    assert [d.tipo for d in links_from_ficha(html)] == ["inicial", "modificacion"]


def test_interpretar_importes_por_seccion():
    assert interpretar_importes(secciones.DEUDA, "140.505,00€", "67.230,26€") == {
        "valor": "67230.26", "valor_flag": None, "importe_concedido": "140505.00", "importe_concedido_flag": None}
    d = interpretar_importes(secciones.DEPOSITO, None, "44.130,00 17.188,27")
    assert d["valor"] is None and d["valor_flag"] == "ilegible"
    assert interpretar_importes(secciones.VEHICULO, "", "")["valor_flag"] is None


def test_import_idempotent_and_flags_duplicates(tmp_path):
    dip = [{"codParlamentario": 150, "apellidosNombre": "Abades Martínez, Cristina", "fchAlta": "08/08/2023",
            "fchBaja": "", "url_ficha_bienes":
            "https://www.congreso.es/docbienes/leg15/000150/000150_000_e_0000648_20230808.pdf"}]
    bie = [{"seccion": "Depósito o cuenta", "descripcion": "Cuenta", "titulo": "1.000,00", "derecho": "",
            "cod": "150", "nombre": "Abades Martínez, Cristina"}] * 2
    files = []
    for name, data in (("d.json", dip), ("b.json", bie)):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        files.append(CachedFile(f"https://x.test/{name}", p, "h", "2026-10-04T00:00:00+00:00", True))
    con = connect(tmp_path / "t.sqlite")
    for _ in range(2):
        with con:
            load_diputados(con, files[0])
            load_bienes(con, files[1])
    assert con.execute("SELECT ocurrencia, valor FROM ext_xerraires_bien").fetchall() == [(1, "1000.00"), (2, "1000.00")]
    assert con.execute("SELECT COUNT(*), MIN(tipo) FROM declaracion_bienes").fetchone() == (1, "inicial")
    assert con.execute("SELECT fecha_alta, fecha_baja FROM ext_xerraires_diputado").fetchone() == ("2023-08-08", None)


def test_evaluar_matches_by_description_and_amount():
    refs = [{"cod_parlamentario": 1, "seccion": "deposito", "descripcion": "Cuenta corriente Banco X", "valor": "100.00"},
            {"cod_parlamentario": 1, "seccion": "deposito", "descripcion": "Plazo fijo", "valor": "50.00"},
            {"cod_parlamentario": 2, "seccion": "deposito", "descripcion": "no evaluado", "valor": "1"}]
    preds = [{"cod_parlamentario": 1, "seccion": "deposito", "descripcion": "Cta. corriente Banco X", "valor": "100.00"},
             {"cod_parlamentario": 1, "seccion": "deposito", "descripcion": "Plazo fijo", "valor": "5.00"},
             {"cod_parlamentario": 1, "seccion": "deposito", "descripcion": "Inventada", "valor": None}]
    s = evaluar(preds, refs)["deposito"]
    assert (s.ref, s.pred, s.emparejadas, s.valor_evaluables, s.valor_exactos) == (2, 3, 2, 2, 1)
