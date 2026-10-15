"""Genera el explorador web (una sola página HTML con los datos incrustados) desde la BBDD.

Uso:
    python -m rentismo.web            # escribe data/web/explorador.html (fuera del repo)

La plantilla está en web/explorador.template.html; los datos se incrustan como JSON. La página
muestra solo lo que hay en la BBDD: si la extracción propia aún no ha corrido, lo indica.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .load import connect

TEMPLATE = config.ROOT / "web" / "explorador.template.html"


def _rows(con: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    cur = con.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def recopilar(con: sqlite3.Connection, legislatura: str) -> dict:
    cod_por_dip = {d: c for c, d in con.execute(
        "SELECT cod_parlamentario, diputado_id FROM ext_xerraires_diputado WHERE diputado_id IS NOT NULL")}

    intereses = defaultdict(list)
    for r in _rows(con, """SELECT diputado_id, fecha_registro, fecha_registro_original, declaracion, tipo, periodo,
                                  empleador, sector, descripcion, destinatario, benefactor, observaciones
                           FROM interes_economico WHERE diputado_id IS NOT NULL
                           ORDER BY fecha_registro, id"""):
        intereses[r.pop("diputado_id")].append(r)

    declaraciones = defaultdict(list)
    for r in _rows(con, """SELECT cod_parlamentario, tipo_codigo, tipo, fecha, num_registro, url
                           FROM declaracion_bienes ORDER BY fecha"""):
        declaraciones[r.pop("cod_parlamentario")].append(r)

    referencia = defaultdict(list)
    for r in _rows(con, """SELECT cod_parlamentario, seccion, descripcion, situacion, fecha, derecho, titulo,
                                  valor, valor_flag, importe_concedido, importe_concedido_flag
                           FROM ext_xerraires_bien WHERE ocurrencia = 1 ORDER BY id"""):
        referencia[r.pop("cod_parlamentario")].append(r)

    propias = defaultdict(list)
    for r in _rows(con, """SELECT d.cod_parlamentario, d.tipo_codigo, d.fecha AS fecha_declaracion, d.url,
                                  p.pagina, p.seccion, p.clase, p.descripcion, p.situacion, p.fecha,
                                  p.derecho_titulo, p.importe, p.importe_texto, p.importe_estado,
                                  p.importe_tesseract, p.importe2, p.importe2_texto, p.importe2_estado, p.dudoso
                           FROM decl_partida p JOIN declaracion_bienes d ON d.id = p.declaracion_id
                           ORDER BY d.fecha, p.orden"""):
        propias[r.pop("cod_parlamentario")].append(r)

    diputados = []
    for d in _rows(con, """SELECT id, nombre, circunscripcion, formacion, grupo, fecha_alta, fecha_baja, biografia
                           FROM diputado WHERE legislatura = ? ORDER BY nombre_key""", (legislatura,)):
        cod = cod_por_dip.get(d["id"])
        d.update(cod=cod, intereses=intereses.get(d["id"], []),
                 declaraciones=declaraciones.get(cod, []) if cod else [],
                 referencia=referencia.get(cod, []) if cod else [],
                 propias=propias.get(cod, []) if cod else [])
        diputados.append(d)

    one = lambda sql: con.execute(sql).fetchone()[0]
    resumen = {
        "legislatura": legislatura,
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "diputados": len(diputados),
        "en_activo": sum(1 for d in diputados if not d["fecha_baja"]),
        "con_codigo": sum(1 for d in diputados if d["cod"]),
        "intereses": one("SELECT COUNT(*) FROM interes_economico"),
        "decl_iniciales": one("SELECT COUNT(*) FROM declaracion_bienes WHERE tipo_codigo='000'"),
        "decl_modificaciones": one("SELECT COUNT(*) FROM declaracion_bienes WHERE tipo_codigo='001'"),
        "decl_finales": one("SELECT COUNT(*) FROM declaracion_bienes WHERE tipo_codigo='002'"),
        "ref_bienes": one("SELECT COUNT(*) FROM ext_xerraires_bien WHERE ocurrencia=1"),
        "ref_commit": config.load().xerraires_commit[:7],
        "extraidas": one("SELECT COUNT(DISTINCT declaracion_id) FROM decl_partida"),
        "partidas": one("SELECT COUNT(*) FROM decl_partida"),
        "en_revision": one("SELECT COUNT(*) FROM v_revision_importes"),
        "revision_nombres": one("SELECT COUNT(*) FROM revision_manual"),
    }
    return {"resumen": resumen, "diputados": diputados}


def render(datos: dict) -> str:
    js = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATOS__*/null", js)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(config.ROOT / "data" / "web" / "explorador.html"))
    args = ap.parse_args(argv)
    cfg = config.load()
    html = render(recopilar(connect(cfg.sqlite_path), cfg.legislaturas[0]))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{out} ({len(html.encode()) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
