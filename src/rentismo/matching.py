"""Emparejamiento nombre -> diputado. Solo acepta coincidencias únicas; el resto va a revisión."""
from __future__ import annotations

from dataclasses import dataclass, field

from .normalize import name_key, name_tokens


@dataclass(frozen=True)
class Candidate:
    id: int
    nombre: str


@dataclass(frozen=True)
class MatchResult:
    diputado_id: int | None
    metodo: str                      # 'exacto' | 'tokens' | 'sin_candidatos' | 'ambiguo'
    candidatos: tuple[Candidate, ...] = field(default=())


class Matcher:
    def __init__(self, candidates: list[Candidate]):
        self._by_key: dict[str, list[Candidate]] = {}
        self._by_tokens: dict[frozenset, list[Candidate]] = {}
        for c in candidates:
            self._by_key.setdefault(name_key(c.nombre), []).append(c)
            self._by_tokens.setdefault(name_tokens(c.nombre), []).append(c)

    def match(self, nombre: str) -> MatchResult:
        exact = self._by_key.get(name_key(nombre), [])
        if len(exact) == 1:
            return MatchResult(exact[0].id, "exacto", tuple(exact))
        if len(exact) > 1:
            return MatchResult(None, "ambiguo", tuple(exact))
        tok = self._by_tokens.get(name_tokens(nombre), [])
        if len(tok) == 1:
            return MatchResult(tok[0].id, "tokens", tuple(tok))
        if len(tok) > 1:
            return MatchResult(None, "ambiguo", tuple(tok))
        return MatchResult(None, "sin_candidatos")
