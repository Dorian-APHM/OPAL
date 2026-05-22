"""Helpers for case- and accent-insensitive text search.

`unaccent(col) ILIKE unaccent(pattern)` is the standard PostgreSQL idiom for
matching "Meta" against "Méta" and vice versa. This module exposes:

- `unaccent_lower(s)` — Python-side normalization (strip diacritics + lowercase),
  used to normalize the search pattern when needed and as the SQLite fallback.
- `iaccent_ilike(col, pattern)` — SQLAlchemy ORM expression that produces
  `unaccent(col) ILIKE unaccent(pattern)` against PostgreSQL, falling back to
  plain `.ilike()` on SQLite (the conftest registers a SQLite UDF so that
  `unaccent(x)` returns the python-normalized string).
"""
from __future__ import annotations

import unicodedata

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement


def unaccent_lower(s: str) -> str:
    """Strip diacritics and lowercase. Used as the SQLite UDF body and to
    normalize patterns on the Python side when raw SQL is built dynamically.
    """
    if s is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def iaccent_ilike(col: ColumnElement, pattern: str):
    """Return a SQLAlchemy boolean expression equivalent to
    `unaccent(col) ILIKE unaccent(pattern)` — case- and accent-insensitive.

    Works on both PostgreSQL (real `unaccent` extension) and SQLite (UDF
    registered in conftest). On SQLite, `unaccent` is lowercase already, so
    ILIKE / LIKE semantics converge.
    """
    return func.unaccent(col).ilike(func.unaccent(pattern))
