"""Secciones canónicas del formulario de declaración de bienes y rentas."""
from __future__ import annotations

from .normalize import strip_accents

# Sección canónica -> campo que contiene el valor principal y si tiene importe concedido.
INMUEBLE_URBANO = "inmueble_urbano"
INMUEBLE_RUSTICO = "inmueble_rustico"
INMUEBLE_SOCIEDAD = "inmueble_sociedad"
DEPOSITO = "deposito"
VALORES = "valores"
OTROS_BIENES = "otros_bienes"
VEHICULO = "vehiculo"
DEUDA = "deuda"
OBSERVACIONES = "observaciones"
# Solo en nuestra extracción (xerraires no las tiene):
RENTA_SALARIAL = "renta_salarial"        # percepciones netas salariales, honorarios...
RENTA_DIVIDENDOS = "renta_dividendos"    # dividendos y participación en beneficios
RENTA_INTERESES = "renta_intereses"      # intereses o rendimientos de cuentas y activos
RENTA_OTRAS = "renta_otras"              # otras rentas o percepciones
SOCIEDAD_PARTICIPADA = "sociedad_participada"  # sociedades participadas >5% por otras sociedades

TODAS = (RENTA_SALARIAL, RENTA_DIVIDENDOS, RENTA_INTERESES, RENTA_OTRAS, INMUEBLE_URBANO,
         INMUEBLE_RUSTICO, INMUEBLE_SOCIEDAD, DEPOSITO, VALORES, SOCIEDAD_PARTICIPADA, VEHICULO,
         OTROS_BIENES, DEUDA, OBSERVACIONES)

# Secciones cuyo 'valor' es un importe en euros.
CON_IMPORTE = {DEPOSITO, VALORES, OTROS_BIENES, DEUDA,
               RENTA_SALARIAL, RENTA_DIVIDENDOS, RENTA_INTERESES, RENTA_OTRAS}

_XERRAIRES = {
    "inmueble urbano": INMUEBLE_URBANO,
    "inmueble rustico": INMUEBLE_RUSTICO,
    "inmueble de sociedad": INMUEBLE_SOCIEDAD,
    "deposito o cuenta": DEPOSITO,
    "valores, acciones y deuda publica": VALORES,
    "otros bienes o derechos": OTROS_BIENES,
    "vehiculo o embarcacion": VEHICULO,
    "deuda o credito": DEUDA,
    "observaciones": OBSERVACIONES,
}


def from_xerraires(label: str) -> str:
    key = strip_accents(label).strip().lower()
    try:
        return _XERRAIRES[key]
    except KeyError:
        raise ValueError(f"Sección desconocida en xerraires: {label!r}") from None
