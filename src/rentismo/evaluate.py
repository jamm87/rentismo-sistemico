"""Evalúa una extracción de bienes contra la referencia de xerraires (ext_xerraires_bien).

La referencia NO es verdad absoluta (OCR + revisión manual de terceros), así que las
discrepancias hay que revisarlas contra el PDF; sirve para comparar métodos entre sí.

Emparejamiento, por diputado y sección: se emparejan filas de forma voraz por la mayor
puntuación, que combina similitud de la descripción y coincidencia exacta del importe.

Uso:
    python -m rentismo.evaluate pred.json [--detalle]
pred.json: lista de {cod_parlamentario, seccion, descripcion, valor, importe_concedido?}
           con 'valor' como texto decimal ("1234.56") o null. Solo se evalúan los
           diputados presentes en pred.json.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from . import config
from .load import connect
from .normalize import strip_accents

UMBRAL = 0.55


def _norm(s: str | None) -> str:
    return " ".join(strip_accents(s or "").lower().split())


def _dec(v) -> Decimal | None:
    return Decimal(str(v)) if v not in (None, "") else None


def score(pred: dict, ref: dict) -> float:
    sim = SequenceMatcher(None, _norm(pred.get("descripcion")), _norm(ref.get("descripcion"))).ratio()
    pv, rv = _dec(pred.get("valor")), _dec(ref.get("valor"))
    if pv is not None and pv == rv:
        return max(sim, 0.6) + 0.4      # mismo importe: casi seguro la misma fila
    return sim


@dataclass
class SeccionStats:
    ref: int = 0
    pred: int = 0
    emparejadas: int = 0
    valor_evaluables: int = 0          # pares con importe legible en la referencia
    valor_exactos: int = 0
    pares: list = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.emparejadas / self.ref if self.ref else float("nan")

    @property
    def precision(self) -> float:
        return self.emparejadas / self.pred if self.pred else float("nan")

    @property
    def acierto_valor(self) -> float:
        return self.valor_exactos / self.valor_evaluables if self.valor_evaluables else float("nan")


def evaluar(preds: list[dict], refs: list[dict]) -> dict[str, SeccionStats]:
    cods = {int(p["cod_parlamentario"]) for p in preds}
    grupos: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
    for p in preds:
        grupos[(int(p["cod_parlamentario"]), p["seccion"])][0].append(p)
    for r in refs:
        if int(r["cod_parlamentario"]) in cods:
            grupos[(int(r["cod_parlamentario"]), r["seccion"])][1].append(r)

    stats: dict[str, SeccionStats] = defaultdict(SeccionStats)
    for (cod, sec), (ps, rs) in grupos.items():
        st = stats[sec]
        st.pred += len(ps)
        st.ref += len(rs)
        cand = sorted(((score(p, r), i, j) for i, p in enumerate(ps) for j, r in enumerate(rs)), reverse=True)
        usados_p, usados_r = set(), set()
        for s, i, j in cand:
            if s < UMBRAL or i in usados_p or j in usados_r:
                continue
            usados_p.add(i), usados_r.add(j)
            st.emparejadas += 1
            rv = _dec(rs[j].get("valor"))
            if rv is not None:
                st.valor_evaluables += 1
                st.valor_exactos += _dec(ps[i].get("valor")) == rv
            st.pares.append((cod, ps[i], rs[j], round(s, 2)))
    return dict(stats)


def referencia(con: sqlite3.Connection) -> list[dict]:
    con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT cod_parlamentario, seccion, descripcion, valor, importe_concedido
                          FROM ext_xerraires_bien WHERE ocurrencia = 1""").fetchall()
    return [dict(r) for r in rows]


def informe(stats: dict[str, SeccionStats]) -> str:
    lines = [f"{'sección':<18}{'ref':>6}{'pred':>6}{'recall':>8}{'precis.':>8}{'importe ok':>12}"]
    tot = SeccionStats()
    for sec, s in sorted(stats.items()):
        lines.append(f"{sec:<18}{s.ref:>6}{s.pred:>6}{s.recall:>8.1%}{s.precision:>8.1%}"
                     f"{s.valor_exactos:>6}/{s.valor_evaluables:<5}")
        for a in ("ref", "pred", "emparejadas", "valor_evaluables", "valor_exactos"):
            setattr(tot, a, getattr(tot, a) + getattr(s, a))
    lines.append(f"{'TOTAL':<18}{tot.ref:>6}{tot.pred:>6}{tot.recall:>8.1%}{tot.precision:>8.1%}"
                 f"{tot.valor_exactos:>6}/{tot.valor_evaluables:<5}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pred")
    ap.add_argument("--detalle", action="store_true", help="listar pares con importe distinto")
    args = ap.parse_args(argv)
    preds = json.load(open(args.pred, encoding="utf-8"))
    stats = evaluar(preds, referencia(connect(config.load().sqlite_path)))
    print(informe(stats))
    if args.detalle:
        for sec, s in sorted(stats.items()):
            for cod, p, r, sc in s.pares:
                if _dec(r.get("valor")) is not None and _dec(p.get("valor")) != _dec(r.get("valor")):
                    print(f"[{sec}] cod={cod} pred={p.get('valor')} ref={r.get('valor')} "
                          f"| {p.get('descripcion')!r} ~ {r.get('descripcion')!r} ({sc})")


if __name__ == "__main__":
    main()
