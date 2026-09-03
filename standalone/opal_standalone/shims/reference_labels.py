"""Standalone replacement for ``backend/utils/reference_labels.py``.

Reference codebooks (ICD/ATC label files uploaded by an administrator) live in
the application database, which the standalone apps do not have. Source-value
enrichment therefore becomes a no-op: labels already present in the CDM are
untouched, and nothing is added.
"""
from __future__ import annotations

from typing import Sequence


def get_reference_label_map(_db, _domain: str, _codes: Sequence[str]) -> dict[str, str]:
    """No codebooks without an application database."""
    return {}


def enrich_source_names(_db, _domain: str, _items, *_args, **_kwargs) -> None:
    """No-op enrichment (kept for signature compatibility with the server)."""
    return None
