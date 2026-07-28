from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NormalizationConfigError(ValueError):
    """Raised when alias or generic-term config is invalid."""


@dataclass(frozen=True)
class AliasIndex:
    alias_to_canonical: dict[str, str]

    def resolve(self, value: str) -> str:
        key = normalized_match_key(value)
        return self.alias_to_canonical.get(key, key)


@dataclass(frozen=True)
class GenericTermIndex:
    terms: frozenset[str]

    def contains(self, value: str) -> bool:
        return normalized_match_key(value) in self.terms


def normalized_match_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = _strip_edge_symbols(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()


def resolve_candidate_key(value: str, aliases: AliasIndex | None = None) -> str:
    key = normalized_match_key(value)
    if not key:
        return key
    if aliases is None:
        return key
    return aliases.alias_to_canonical.get(key, key)


def load_alias_index(path: Path) -> AliasIndex:
    payload = _load_json_object(path)
    entries = payload.get("aliases")
    if not isinstance(entries, list):
        raise NormalizationConfigError("aliases config must contain an aliases list")

    alias_to_canonical: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NormalizationConfigError("alias entries must be objects")
        canonical = entry.get("canonical")
        aliases = entry.get("aliases", [])
        if not isinstance(canonical, str) or not canonical.strip():
            raise NormalizationConfigError("alias canonical must be a non-empty string")
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            raise NormalizationConfigError("alias aliases must be a string list")

        canonical_key = normalized_match_key(canonical)
        _put_alias(alias_to_canonical, canonical_key, canonical_key)
        for alias in aliases:
            alias_key = normalized_match_key(alias)
            if alias_key:
                _put_alias(alias_to_canonical, alias_key, canonical_key)
    return AliasIndex(alias_to_canonical=alias_to_canonical)


def load_generic_term_index(path: Path) -> GenericTermIndex:
    payload = _load_json_object(path)
    terms = payload.get("generic_terms")
    if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
        raise NormalizationConfigError(
            "generic_terms config must contain a string list"
        )
    return GenericTermIndex(
        terms=frozenset(
            normalized_match_key(term)
            for term in terms
            if normalized_match_key(term)
        )
    )


def _strip_edge_symbols(value: str) -> str:
    chars = list(value.strip())
    while chars and _is_edge_symbol(chars[0]):
        chars.pop(0)
    while chars and _is_edge_symbol(chars[-1]):
        chars.pop()
    return "".join(chars)


def _is_edge_symbol(value: str) -> bool:
    category = unicodedata.category(value)
    return category[0] in {"P", "S"}


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise NormalizationConfigError(f"config must be a JSON object: {path}")
    return payload


def _put_alias(
    alias_to_canonical: dict[str, str],
    alias_key: str,
    canonical_key: str,
) -> None:
    existing = alias_to_canonical.get(alias_key)
    if existing is not None and existing != canonical_key:
        raise NormalizationConfigError(
            f"alias maps to multiple canonical terms: {alias_key}"
        )
    alias_to_canonical[alias_key] = canonical_key
