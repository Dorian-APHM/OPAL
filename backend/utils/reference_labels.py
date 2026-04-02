"""
Reference label enrichment — fills empty source_name from ReferenceCodebook (CCAM_FR, CIM10_FR, etc.).

Usage:
    from utils.reference_labels import enrich_source_names, get_reference_label_map

    # Bulk: enrich a list of dicts that have "source_value" and "source_name"
    enrich_source_names(db, "Procedure", rows)

    # Map: get {code: label} for a set of codes
    ref_map = get_reference_label_map(db, "Condition", ["A011", "I10"])
"""
import logging
from typing import Sequence

from sqlalchemy.orm import Session

from db.models import ReferenceCodebook

logger = logging.getLogger(__name__)

# Domain → codebook name suffix pattern (matched by domain column)
# We don't hardcode names — we match by domain so any codebook registered
# for a domain will be used (CCAM_FR for Procedure, CIM10_FR for Condition, etc.)


def get_reference_label_map(db: Session, domain: str, codes: Sequence[str]) -> dict[str, str]:
    """Return {code: description} for the given codes from reference codebooks matching the domain.

    If multiple codebooks exist for a domain (e.g. CCAM_FR and CCAM_EN),
    ALL are queried — the first match wins (ordered by id, so oldest upload first).
    For the enrichment use-case, the FR codebooks should be the ones with matching domain.
    """
    if not codes:
        return {}

    # Deduplicate
    unique_codes = list(set(codes))

    # Query in batches of 1000 to avoid oversized IN clauses
    # Prioritize _FR codebooks — they are the authoritative labels for display.
    # EN codebooks (e.g. CCAM_EN) are only used by the mapping module directly.
    result: dict[str, str] = {}
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
        # FR codebooks first, then others as fallback
        fr_rows = [(code, desc) for code, desc, name in rows if name.endswith("_FR")]
        other_rows = [(code, desc) for code, desc, name in rows if not name.endswith("_FR")]
        for code, desc in fr_rows:
            result[code] = desc
        for code, desc in other_rows:
            if code not in result:
                result[code] = desc

    return result


def enrich_source_names(
    db: Session,
    domain: str,
    rows: list[dict],
    source_value_key: str = "source_value",
    source_name_key: str = "source_name",
) -> None:
    """Enrich rows in-place: set source_name from FR reference codebooks.

    When a FR reference codebook exists for the domain, its labels take
    priority over whatever the CDM provides (which may be EN or empty).
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
