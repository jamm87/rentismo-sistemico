from datetime import date
from decimal import Decimal

import pytest

from rentismo.matching import Candidate, Matcher
from rentismo.normalize import name_key, name_tokens, parse_fecha_es, parse_importe_es


@pytest.mark.parametrize("raw,key", [
    ("Sánchez Pérez-Castejón,Pedro", "SANCHEZ PEREZ CASTEJON, PEDRO"),
    ("sánchez pérez-castejón, PEDRO", "SANCHEZ PEREZ CASTEJON, PEDRO"),
    ("  Muñoz  López ,  María Jesús ", "MUNOZ LOPEZ, MARIA JESUS"),
])
def test_name_key(raw, key):
    assert name_key(raw) == key


def test_name_tokens_ignores_order_and_particles():
    assert name_tokens("García de la Fuente,Ana") == name_tokens("Ana García Fuente")


@pytest.mark.parametrize("s,expected", [
    ("1.234,56 €", Decimal("1234.56")),
    ("1.234.567,8", Decimal("1234567.8")),
    ("250", Decimal("250")),
    ("-3.000,00 euros", Decimal("-3000.00")),
    ("0,5", Decimal("0.5")),
    ("756.715'12", Decimal("756715.12")),
    ("141.600’00 €", Decimal("141600.00")),
    ("12'345", None),       # apóstrofo seguido de 3 cifras: no es decimal, no se adivina
    ("1,234.56", None),     # formato anglosajón: ambiguo
    ("12.34", None),        # ¿miles o decimales? no se adivina
    ("1.2345,00", None),
    ("ilegible", None),
    ("", None),
    (None, None),
])
def test_parse_importe_es(s, expected):
    assert parse_importe_es(s) == expected


def test_parse_fecha_es():
    assert parse_fecha_es("02/10/2026") == date(2026, 10, 2)
    assert parse_fecha_es("31/02/2026") is None
    assert parse_fecha_es("2026-10-02") is None


def test_matcher_unique_ambiguous_and_missing():
    m = Matcher([Candidate(1, "Pérez García, Juan"), Candidate(2, "López Ruiz, Ana"),
                 Candidate(3, "López Ruiz, Ana")])
    assert m.match("PEREZ GARCIA,Juan").diputado_id == 1
    assert m.match("Juan Pérez García").metodo == "tokens"
    amb = m.match("López Ruiz,Ana")
    assert amb.diputado_id is None and amb.metodo == "ambiguo" and len(amb.candidatos) == 2
    assert m.match("Nadie, Nadie").metodo == "sin_candidatos"
