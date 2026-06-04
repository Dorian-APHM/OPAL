"""
Reference label enrichment — fills empty source_name from ReferenceCodebook.

Codebook selection is **name-agnostic**: production codebooks are not necessarily
named with an "_FR" suffix, so for a given domain we pick the codebook with the
MOST codes as the primary source of labels and fall back to the other codebooks
of the same domain for codes the primary doesn't cover.

Usage:
    from utils.reference_labels import enrich_source_names, get_reference_label_map

    # Bulk: enrich a list of dicts that have "source_value" and "source_name"
    enrich_source_names(db, "Procedure", rows)

    # Map: get {code: label} for a set of codes
    ref_map = get_reference_label_map(db, "Condition", ["A011", "I10"])
"""
import logging
from typing import Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import ReferenceCodebook

logger = logging.getLogger(__name__)


def get_reference_label_map(db: Session, domain: str, codes: Sequence[str]) -> dict[str, str]:
    """Return {code: description} for the given codes from the domain's codebooks.

    Selection is by **code count, not by name**: the codebook with the most codes
    for the domain is primary; any other codebook of the same domain is a fallback
    for codes the primary doesn't have (or has with an empty label). This works in
    production where codebooks may carry arbitrary names (no "_FR" convention).
    """
    if not codes:
        return {}

    unique_codes = list(set(codes))

    # Priority order for this domain: richest codebook (most codes) first.
    counts = (
        db.query(ReferenceCodebook.name, func.count(ReferenceCodebook.id))
        .filter(ReferenceCodebook.domain == domain)
        .group_by(ReferenceCodebook.name)
        .order_by(func.count(ReferenceCodebook.id).desc())
        .all()
    )
    if not counts:
        return {}
    rank = {name: i for i, (name, _n) in enumerate(counts)}  # 0 = richest = highest priority

    result: dict[str, str] = {}
    best_rank: dict[str, int] = {}
    batch_size = 1000
    for i in range(0, len(unique_codes), batch_size):
        batch = unique_codes[i : i + batch_size]
        rows = (
            db.query(ReferenceCodebook.code, ReferenceCodebook.description, ReferenceCodebook.name)
            .filter(
                ReferenceCodebook.domain == domain,
                ReferenceCodebook.code.in_(batch),
            )
            .all()
        )
        for code, desc, name in rows:
            if not (desc or "").strip():
                continue  # empty label — let a lower-priority codebook fill it
            r = rank.get(name, len(rank))
            if code not in best_rank or r < best_rank[code]:
                best_rank[code] = r
                result[code] = desc

    return result


def enrich_source_names(
    db: Session,
    domain: str,
    rows: list[dict],
    source_value_key: str = "source_value",
    source_name_key: str = "source_name",
) -> None:
    """Enrich rows in-place: set source_name from the domain's reference codebooks.

    When a reference codebook exists for the domain, its label (from the richest
    codebook, with fallback to the others) takes priority over whatever the CDM
    provides (which may be empty or in another language).
    """
    codes_to_lookup = [
        r[source_value_key]
        for r in rows
        if r.get(source_value_key)
    ]
    if not codes_to_lookup:
        return

    ref_map = get_reference_label_map(db, domain, codes_to_lookup)
    if not ref_map:
        return

    for r in rows:
        if r.get(source_value_key):
            label = ref_map.get(r[source_value_key])
            if label:
                r[source_name_key] = label
