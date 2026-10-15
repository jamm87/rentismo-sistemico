"""Normalización de nombres, fechas e importes en formato español."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

_PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "I", "DA", "DI", "VAN", "VON"}


def strip_accents(s: str) -> str:
    # Conserva la Ñ como N: el Congreso no es consistente con ella en todas las fuentes.
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _clean(s: str) -> str:
    s = strip_accents(s).upper()
    s = re.sub(r"[^A-Z, ]+", " ", s.replace("-", " "))
    return re.sub(r"\s+", " ", s).strip()


def name_key(nombre: str) -> str:
    """Clave canónica 'APELLIDOS, NOMBRE' a partir de 'Apellidos,Nombre' (con o sin espacio).

    Si no hay coma no se puede saber qué parte es el nombre: se devuelve el texto limpio
    y el emparejamiento se apoya en ``name_tokens``.
    """
    s = _clean(nombre)
    if "," in s:
        apellidos, _, nom = s.partition(",")
        return f"{apellidos.strip()}, {nom.replace(',', ' ').strip()}".strip(", ")
    return s


def name_tokens(nombre: str) -> frozenset[str]:
    """Conjunto de palabras significativas, independiente del orden y de partículas."""
    return frozenset(t for t in _clean(nombre).replace(",", " ").split() if t not in _PARTICULAS)


def parse_fecha_es(s: str | None) -> date | None:
    """'dd/mm/aaaa' -> date. Devuelve None si no encaja (nunca inventa)."""
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", s)
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


_IMPORTE_RE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$|^-?\d+(,\d{1,2})?$")


def parse_importe_es(s: str | None) -> Decimal | None:
    """'1.234,56 €' -> Decimal('1234.56'). Si el formato no es inequívoco devuelve None.

    Acepta separador de miles '.' y decimal ',' (o apóstrofo, como en 756.715'12). Rechaza mezclas ambiguas como
    '1,234.56' o '12.34' (¿miles o decimal?) para no inventar valores.
    """
    if s is None:
        return None
    t = re.sub(r"\s+|€|euros?|EUR", "", s, flags=re.I)
    # Algunos formularios escriben el decimal con apóstrofo (756.715'12): equivale a la coma.
    t = re.sub(r"['’´`](?=\d{1,2}$)", ",", t)
    if not t or not _IMPORTE_RE.match(t):
        return None
    try:
        return Decimal(t.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
