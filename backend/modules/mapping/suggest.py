"""
Mapping suggestion engine.

Proposes concept mappings for unmapped source values using 5 strategies
(in priority order):
1. Exact match: source_value == concept_code in target vocabulary
2. Concept relationships: "Maps to" relationships in concept_relationship
3. Ingredient match: extract active ingredient from source_name (DCI/INN) and
   search concept_name + concept_synonym (handles French→English CDMs)
4. Fuzzy matching: trigram / similarity between source_value and concept_name
5. Contextual: patterns from already-mapped terms in the same vocabulary
"""
import logging
import re

from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)


def suggest_mappings(
    conn,
    source_value: str,
    source_name: str | None,
    domain: str,
    omop_schema: str = "omop_cdm",
    max_suggestions: int = 5,
    enable_exact: bool = True,
    enable_relationship: bool = True,
    enable_ingredient: bool = True,
) -> list[dict]:
    """
    Generate mapping suggestions for a single source term.
    Returns a list of suggestions sorted by confidence score (desc).

    Deterministic SQL strategies, each independently toggleable:
      - exact:        concept_code == source_value (btree index, conf 95)
      - relationship: OMOP "Maps to" (conf 85)
      - ingredient:   French DCI / galenic-form drug matching (conf 78-95) — only
                      yields results for drug-like names (the Drug domain)
    SapBERT suggestions are pre-computed and merged separately by the caller.
    """
    # Every suggestion query hits vocabulary tables (concept,
    # concept_relationship, concept_synonym) — resolve to the vocabulary schema.
    if hasattr(omop_schema, "schema_for"):
        omop_schema = omop_schema.schema_for("concept")
    omop_schema = safe_identifier(omop_schema)
    suggestions = []
    seen_concept_ids = set()

    def _add(results: list[dict]):
        for s in results:
            if s["concept_id"] not in seen_concept_ids:
                suggestions.append(s)
                seen_concept_ids.add(s["concept_id"])

    dialect = conn.dialect
    with dialect.dict_cursor(conn) as cur:
        if enable_exact:
            _add(_exact_match(dialect, cur, source_value, domain, omop_schema))
        if enable_relationship and source_name:
            _add(_relationship_match(dialect, cur, source_value, domain, omop_schema))
        if enable_ingredient and source_name:
            _add(_ingredient_match(dialect, cur, source_name, domain, omop_schema))

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return suggestions[:max_suggestions]


def suggest_batch(
    conn,
    unmapped_terms: list[dict],
    domain: str,
    omop_schema: str = "omop_cdm",
    max_per_term: int = 5,
    enable_exact: bool = True,
    enable_relationship: bool = True,
    enable_ingredient: bool = True,
) -> list[dict]:
    """
    Generate suggestions for a batch of unmapped terms.
    Each term dict should have 'source_value' and optionally 'source_name'.
    Returns list of {source_value, source_name, suggestions: [...]}.
    """
    # NOTE: Sequential processing — psycopg2 connections are not thread-safe.
    # Parallelization would require a connection per thread from the pool.
    results = []
    for term in unmapped_terms:
        sv = term.get("source_value", "")
        sn = term.get("source_name", "")
        try:
            suggs = suggest_mappings(
                conn, sv, sn, domain, omop_schema, max_per_term,
                enable_exact=enable_exact,
                enable_relationship=enable_relationship,
                enable_ingredient=enable_ingredient,
            )
        except Exception as e:
            logger.warning("Suggestion failed for %s: %s", sv, e)
            conn.rollback()
            suggs = []
        results.append({
            "source_value": sv,
            "source_name": sn,
            "suggestions": suggs,
        })
    return results


# ──── Strategy 1: Exact Match ────

def _exact_match(dialect, cur, source_value: str, domain: str, schema: str) -> list[dict]:
    """Find concepts where concept_code exactly matches source_value."""
    concept = f"{dialect.quote_ident(schema)}.{dialect.quote_ident('concept')}"
    try:
        dialect.execute(cur, f"""
            SELECT c.concept_id, c.concept_name, c.concept_code,
                   c.vocabulary_id, c.domain_id, c.standard_concept
            FROM {concept} c
            WHERE c.concept_code = %(sv)s
              AND c.invalid_reason IS NULL
              AND c.standard_concept = 'S'
            ORDER BY
              CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
              c.concept_name
            {dialect.limit_offset('5', '0')}
        """, {"sv": source_value, "domain": domain})
        rows = cur.fetchall()
        return [
            {
                "concept_id": r["concept_id"],
                "concept_name": r["concept_name"],
                "concept_code": r["concept_code"],
                "vocabulary_id": r["vocabulary_id"],
                "domain_id": r["domain_id"],
                "standard_concept": r["standard_concept"],
                "confidence": 95,
                "source": "exact",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Exact match error: %s", e)
        cur.connection.rollback()
        return []


# ──── Strategy 2: Concept Relationships ────

def _relationship_match(dialect, cur, source_value: str, domain: str, schema: str) -> list[dict]:
    """Find 'Maps to' relationships from source concept codes."""
    sch = dialect.quote_ident(schema)
    concept = f"{sch}.{dialect.quote_ident('concept')}"
    concept_relationship = f"{sch}.{dialect.quote_ident('concept_relationship')}"
    try:
        dialect.execute(cur, f"""
            SELECT DISTINCT
                c2.concept_id, c2.concept_name, c2.concept_code,
                c2.vocabulary_id, c2.domain_id, c2.standard_concept,
                CASE WHEN c2.domain_id = %(domain)s THEN 0 ELSE 1 END AS domain_rank
            FROM {concept} c1
            JOIN {concept_relationship} cr
              ON c1.concept_id = cr.concept_id_1
              AND cr.relationship_id = 'Maps to'
              AND cr.invalid_reason IS NULL
            JOIN {concept} c2
              ON cr.concept_id_2 = c2.concept_id
              AND c2.standard_concept = 'S'
              AND c2.invalid_reason IS NULL
            WHERE c1.concept_code = %(sv)s
            ORDER BY domain_rank
            {dialect.limit_offset('5', '0')}
        """, {"sv": source_value, "domain": domain})
        rows = cur.fetchall()
        return [
            {
                "concept_id": r["concept_id"],
                "concept_name": r["concept_name"],
                "concept_code": r["concept_code"],
                "vocabulary_id": r["vocabulary_id"],
                "domain_id": r["domain_id"],
                "standard_concept": r["standard_concept"],
                "confidence": 85,
                "source": "relationship",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Relationship match error: %s", e)
        cur.connection.rollback()
        return []


# ──── Strategy 3: Ingredient / DCI Match ────

# Common French→English DCI/INN spelling differences
_DCI_CORRECTIONS = {
    "IBUPROFENE": "IBUPROFEN",
    "PARACETAMOL": "ACETAMINOPHEN",
    "AMOXICILLINE": "AMOXICILLIN",
    "AMPICILLINE": "AMPICILLIN",
    "CEFOTAXIME": "CEFOTAXIME",
    "CIPROFLOXACINE": "CIPROFLOXACIN",
    "CLINDAMYCINE": "CLINDAMYCIN",
    "DOXYCYCLINE": "DOXYCYCLINE",
    "ERYTHROMYCINE": "ERYTHROMYCIN",
    "GENTAMICINE": "GENTAMICIN",
    "LEVOFLOXACINE": "LEVOFLOXACIN",
    "METRONIDAZOLE": "METRONIDAZOLE",
    "OXACILLINE": "OXACILLIN",
    "PENICILLINE": "PENICILLIN",
    "PIPERACILLINE": "PIPERACILLIN",
    "RIFAMPICINE": "RIFAMPIN",
    "VANCOMYCINE": "VANCOMYCIN",
    "AMLODIPINE": "AMLODIPINE",
    "ATORVASTATINE": "ATORVASTATIN",
    "FLUVASTATINE": "FLUVASTATIN",
    "PRAVASTATINE": "PRAVASTATIN",
    "ROSUVASTATINE": "ROSUVASTATIN",
    "SIMVASTATINE": "SIMVASTATIN",
    "LOSARTAN": "LOSARTAN",
    "VALSARTAN": "VALSARTAN",
    "IRBESARTAN": "IRBESARTAN",
    "CLOPIDOGREL": "CLOPIDOGREL",
    "FLUOXETINE": "FLUOXETINE",
    "PAROXETINE": "PAROXETINE",
    "SERTRALINE": "SERTRALINE",
    "ESCITALOPRAM": "ESCITALOPRAM",
    "ALPRAZOLAM": "ALPRAZOLAM",
    "DIAZEPAM": "DIAZEPAM",
    "LORAZEPAM": "LORAZEPAM",
    "TRAMADOL": "TRAMADOL",
    "MORPHINE": "MORPHINE",
    "CODEINE": "CODEINE",
    "INSULINE": "INSULIN",
    "METFORMINE": "METFORMIN",
    "OMEPRAZOLE": "OMEPRAZOLE",
    "ESOMEPRAZOLE": "ESOMEPRAZOLE",
    "PANTOPRAZOLE": "PANTOPRAZOLE",
    "LANSOPRAZOLE": "LANSOPRAZOLE",
    "PREDNISOLONE": "PREDNISOLONE",
    "PREDNISONE": "PREDNISONE",
    "METHYLPREDNISOLONE": "METHYLPREDNISOLONE",
    "DEXAMETHASONE": "DEXAMETHASONE",
    "ENOXAPARINE": "ENOXAPARIN",
    "HEPARINE": "HEPARIN",
    "WARFARINE": "WARFARIN",
    "FUROSEMIDE": "FUROSEMIDE",
    "SPIRONOLACTONE": "SPIRONOLACTONE",
    "DIGOXINE": "DIGOXIN",
    "AMIODARONE": "AMIODARONE",
    "DOPAMINE": "DOPAMINE",
    "DOBUTAMINE": "DOBUTAMINE",
    "NORADRENALINE": "NOREPINEPHRINE",
    "ADRENALINE": "EPINEPHRINE",
    "ATROPINE": "ATROPINE",
    "MIDAZOLAM": "MIDAZOLAM",
    "PROPOFOL": "PROPOFOL",
    "KETAMINE": "KETAMINE",
    "LIDOCAINE": "LIDOCAINE",
    "BUPIVACAINE": "BUPIVACAINE",
    "SALBUTAMOL": "ALBUTEROL",
    "IPRATROPIUM": "IPRATROPIUM",
    "FLUTICASONE": "FLUTICASONE",
    "BUDESONIDE": "BUDESONIDE",
    "CETIRIZINE": "CETIRIZINE",
    "DESLORATADINE": "DESLORATADINE",
    "LORATADINE": "LORATADINE",
    "ACIDE ACETYLSALICYLIQUE": "ASPIRIN",
    "ASPIRINE": "ASPIRIN",
    "TAMSULOSINE": "TAMSULOSIN",
    "INSULINE ASPARTE": "INSULIN ASPART",
    "INSULINE GLARGINE": "INSULIN GLARGINE",
    "INSULINE LISPRO": "INSULIN LISPRO",
    "INSULINE DETEMIR": "INSULIN DETEMIR",
    "INSULINE DEGLUDEC": "INSULIN DEGLUDEC",
    "INSULINE HUMAINE": "INSULIN HUMAN",
    "ALLOPURINOL": "ALLOPURINOL",
    "COLCHICINE": "COLCHICINE",
    "GABAPENTINE": "GABAPENTIN",
    "PREGABALINE": "PREGABALIN",
    "LAMOTRIGINE": "LAMOTRIGINE",
    "LEVETIRACETAM": "LEVETIRACETAM",
    "CARBAMAZEPINE": "CARBAMAZEPINE",
    "VALPROATE": "VALPROATE",
    "CLOZAPINE": "CLOZAPINE",
    "OLANZAPINE": "OLANZAPINE",
    "QUETIAPINE": "QUETIAPINE",
    "RISPERIDONE": "RISPERIDONE",
    "ARIPIPRAZOLE": "ARIPIPRAZOLE",
    "LITHIUM": "LITHIUM",
    "METHOTREXATE": "METHOTREXATE",
    "CICLOSPORINE": "CYCLOSPORINE",
    "TACROLIMUS": "TACROLIMUS",
    "AZATHIOPRINE": "AZATHIOPRINE",
    "RITUXIMAB": "RITUXIMAB",
    "ADALIMUMAB": "ADALIMUMAB",
    "INFLIXIMAB": "INFLIXIMAB",
    "OXYCODONE": "OXYCODONE",
    "FENTANYL": "FENTANYL",
    "NALOXONE": "NALOXONE",
    "RACECADOTRIL": "RACECADOTRIL",
    "LOPERAMIDE": "LOPERAMIDE",
    "URAPIDIL": "URAPIDIL",
    "NICARDIPINE": "NICARDIPINE",
}



# French galenic forms to strip from source_name
_GALENIC_FORMS = re.compile(
    r'\b(CPR|COMP|GEL|GELULE|CAPS|INJ|AMP|SACHET|SOL|SUSP|SIROP|SIR|'
    r'POM|CREME|CR|SUPPO|PATCH|COLLYRE|SPRAY|PDR|POUDRE|GRAN|'
    r'FL|FLACON|BUV|BUVABL|IV|IM|SC|PO|LP|LM|EFF|SEC|ORAL|'
    r'ENROB|PERF|SERINGUE|STYLO|SAF|VERSABLE|IRRIGATION)\b',
    re.IGNORECASE,
)

# Mapping from French galenic form → English RxNorm form keywords
# Used to prioritize matching concepts (ORDER BY, not filter)
_FORM_HINTS: dict[str, list[str]] = {
    # Oral solid
    "CPR":      ["Oral Tablet"],
    "COMP":     ["Oral Tablet"],
    "ENROB":    ["Oral Tablet"],
    "EFF":      ["Effervescent Tablet"],
    "GEL":      ["Oral Capsule"],
    "GELULE":   ["Oral Capsule"],
    "CAPS":     ["Oral Capsule"],
    "LP":       ["Extended Release"],
    # Oral liquid
    "SIROP":    ["Oral Solution"],
    "SIR":      ["Oral Solution"],
    "BUV":      ["Oral Solution"],
    "BUVABL":   ["Oral Solution"],
    "SACHET":   ["Oral Powder", "Oral Granules"],
    # Injectable
    "INJ":      ["Injectable", "Injection"],
    "AMP":      ["Injectable", "Injection"],
    "PERF":     ["Injection", "Intravenous"],
    "SERINGUE": ["Prefilled Syringe", "Injectable"],
    "STYLO":    ["Pen Injector", "Injectable"],
    "IV":       ["Intravenous", "Injection"],
    "IM":       ["Injection", "Injectable"],
    "SC":       ["Injection", "Injectable"],
    "SAF":      ["Injection", "Injectable"],
    # Topical
    "POM":      ["Topical", "Ointment"],
    "CREME":    ["Topical", "Cream"],
    "CR":       ["Topical", "Cream"],
    "PATCH":    ["Transdermal"],
    # Other
    "COLLYRE":  ["Ophthalmic"],
    "SPRAY":    ["Nasal Spray", "Metered Dose Inhaler"],
    "SUPPO":    ["Rectal Suppository"],
    "PDR":      ["Powder"],
    "POUDRE":   ["Powder"],
}

# Pattern to detect dosage: number + unit (with optional space)
_DOSAGE_PATTERN = re.compile(
    r'(\d+[\.,]?\d*)\s*(MG/ML|MG|G/L|G|ML|MCG|µG|UI/ML|UI|U/ML|%)\b',
    re.IGNORECASE,
)


def _extract_ingredient_dosage_form(
    source_name: str,
) -> tuple[str, str | None, list[str], str | None]:
    """
    Extract ingredient, dosage, galenic form hints, and brand name from a
    French drug source_name like "HYDROXYZINE 25 MG CPR (ATARAX)".
    Returns (ingredient, dosage_str or None, form_keywords list, brand or None).
    """
    name = source_name.strip().upper()

    # Extract brand name from parentheses before removing it
    brand = None
    brand_match = re.search(r'\(([^)]+)\)', name)
    if brand_match:
        brand = brand_match.group(1).strip()
    name = re.sub(r'\([^)]*\)', '', name).strip()

    # Detect galenic form BEFORE stripping
    form_keywords: list[str] = []
    for match in _GALENIC_FORMS.finditer(name):
        form_code = match.group(1).upper()
        if form_code in _FORM_HINTS:
            for kw in _FORM_HINTS[form_code]:
                if kw not in form_keywords:
                    form_keywords.append(kw)

    # Find dosage
    dose_match = _DOSAGE_PATTERN.search(name)
    dosage = None
    if dose_match:
        val = dose_match.group(1).replace(',', '.')
        unit = dose_match.group(2).upper()
        dosage = f"{val} {unit}"
        # Keep only text before the dosage as ingredient
        name = name[:dose_match.start()].strip()

    # Always remove galenic forms from ingredient name
    name = _GALENIC_FORMS.sub('', name).strip()
    # Clean up residual separators
    name = re.sub(r'\s+', ' ', name).strip().rstrip('/')
    return name, dosage, form_keywords, brand


def _form_order_clause(dialect, form_keywords: list[str], alias: str = "c") -> str:
    """Build a CASE WHEN clause to prioritize concepts matching the galenic form."""
    if not form_keywords:
        return "0+0"
    conditions = " OR ".join(
        dialect.ilike(f"{alias}.concept_name", f"%({_form_param(i)})s")
        for i in range(len(form_keywords))
    )
    return f"CASE WHEN {conditions} THEN 0 ELSE 1 END"


def _form_param(i: int) -> str:
    return f"_form_{i}"


def _form_params(form_keywords: list[str]) -> dict:
    """Build parameter dict for form keyword placeholders (with ILIKE wildcards)."""
    return {_form_param(i): f"%{kw}%" for i, kw in enumerate(form_keywords)}


def _form_matches(concept_name: str, form_keywords: list[str]) -> bool:
    """Check if a concept_name matches any of the form keywords."""
    cn = concept_name.upper()
    return any(kw.upper() in cn for kw in form_keywords)


def _ingredient_match(
    dialect, cur, source_name: str, domain: str, schema: str
) -> list[dict]:
    """
    Extract the active ingredient (DCI/INN) from a French source_name and
    search in concept_name and concept_synonym. Uses galenic form hints
    (CPR→Oral Tablet, INJ→Injectable) to prioritize the right formulation.
    """
    ingredient, dosage, form_keywords, brand = _extract_ingredient_dosage_form(source_name)
    if not ingredient or len(ingredient) < 3:
        return []

    # Apply DCI French→English correction if available
    ingredient_en = _DCI_CORRECTIONS.get(ingredient, None)
    if not ingredient_en:
        # Generic rule: French DCI ending in -INE often drops the E in English
        if ingredient.endswith("INE") and len(ingredient) > 5:
            ingredient_en = ingredient[:-1]
        else:
            ingredient_en = ingredient

    form_order = _form_order_clause(dialect, form_keywords)
    fparams = _form_params(form_keywords)

    # Brand name ordering: concepts with [BrandName] ranked higher
    if brand:
        brand_order = f"CASE WHEN {dialect.ilike('c.concept_name', '%(brand_pat)s')} THEN 0 ELSE 1 END"
        fparams["brand_pat"] = f"%{brand}%"
    else:
        brand_order = "0+0"

    results = []
    try:
        # Try both French and English names
        ingredients_to_try = [ingredient_en]
        if ingredient_en != ingredient:
            ingredients_to_try.append(ingredient)

        # Build search terms: ingredient+dosage first, then ingredient only
        # For injectables, dosage format differs (20 MG/2 ML → 10 MG/ML),
        # so we search ingredient+form first (no dosage) to get the right form
        is_injectable = any(
            kw.upper() in ("INJECTABLE", "INJECTION", "INTRAVENOUS",
                           "PREFILLED SYRINGE", "PEN INJECTOR")
            for kw in form_keywords
        )

        search_terms = []
        for ingr_name in ingredients_to_try:
            if dosage and not is_injectable:
                # Oral forms: dosage in name matches directly
                search_terms.append((f"%{ingr_name}%{dosage}%", True))
            # Always add ingredient-only search
            search_terms.append((f"%{ingr_name}%", False))

        seen = {r["concept_id"] for r in results}
        for search_term, has_dosage in search_terms:
            if len(results) >= 5:
                break

            concept_tbl = f"{dialect.quote_ident(schema)}.{dialect.quote_ident('concept')}"
            # brand_order and form_order are code-generated SQL fragments (not user input)
            ingredient_sql = f"""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.vocabulary_id, c.domain_id, c.standard_concept
                FROM {concept_tbl} c
                WHERE {dialect.ilike('c.concept_name', '%(term)s')}
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                ORDER BY
                  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
                  {brand_order}, {form_order}, {dialect.length('c.concept_name')}
                {dialect.limit_offset('5', '0')}
            """
            dialect.execute(cur, ingredient_sql, {"term": search_term, "domain": domain, **fparams})
            rows = cur.fetchall()
            for r in rows:
                if r["concept_id"] not in seen:
                    # Base confidence: dosage match > form-only match
                    base_conf = 85 if has_dosage else 78
                    if brand and brand.upper() in r["concept_name"].upper():
                        base_conf = min(base_conf + 5, 95)
                    if form_keywords and _form_matches(r["concept_name"], form_keywords):
                        base_conf = min(base_conf + 5, 95)
                    results.append({
                        "concept_id": r["concept_id"],
                        "concept_name": r["concept_name"],
                        "concept_code": r["concept_code"],
                        "vocabulary_id": r["vocabulary_id"],
                        "domain_id": r["domain_id"],
                        "standard_concept": r["standard_concept"],
                        "confidence": base_conf,
                        "source": "ingredient",
                    })
                    seen.add(r["concept_id"])

        # Also search concept_synonym (use original French ingredient for synonyms)
        if len(results) < 5:
            syn_term = f"%{ingredient}%" if not dosage else f"%{ingredient}%{dosage}%"
            sch = dialect.quote_ident(schema)
            syn_tbl = f"{sch}.{dialect.quote_ident('concept_synonym')}"
            concept_tbl = f"{sch}.{dialect.quote_ident('concept')}"
            dialect.execute(cur, f"""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.vocabulary_id, c.domain_id, c.standard_concept
                FROM {syn_tbl} cs
                JOIN {concept_tbl} c ON cs.concept_id = c.concept_id
                WHERE {dialect.ilike('cs.concept_synonym_name', '%(term)s')}
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                GROUP BY c.concept_id, c.concept_name, c.concept_code,
                         c.vocabulary_id, c.domain_id, c.standard_concept
                ORDER BY
                  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
                  {dialect.length('c.concept_name')}
                {dialect.limit_offset('5', '0')}
            """, {"term": syn_term, "domain": domain})
            rows = cur.fetchall()
            seen = {r["concept_id"] for r in results}
            for r in rows:
                if r["concept_id"] not in seen:
                    results.append({
                        "concept_id": r["concept_id"],
                        "concept_name": r["concept_name"],
                        "concept_code": r["concept_code"],
                        "vocabulary_id": r["vocabulary_id"],
                        "domain_id": r["domain_id"],
                        "standard_concept": r["standard_concept"],
                        "confidence": 78,
                        "source": "synonym",
                    })

    except Exception as e:
        logger.warning("Ingredient match error: %s", e)
        cur.connection.rollback()

    return results
