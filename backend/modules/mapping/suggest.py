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

from psycopg2 import sql as psysql
from psycopg2.extras import DictCursor

from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)


def suggest_mappings(
    conn,
    source_value: str,
    source_name: str | None,
    domain: str,
    omop_schema: str = "omop_cdm",
    max_suggestions: int = 5,
    enable_fuzzy: bool = True,
    enable_keyword: bool = True,
    enable_contextual: bool = True,
) -> list[dict]:
    """
    Generate mapping suggestions for a single source term.
    Returns a list of suggestions sorted by confidence score (desc).

    Strategies 1-3 (exact, relationship, ingredient) always run (fast).
    Strategies 4-5 (fuzzy, keyword, contextual) can be toggled via flags.
    """
    omop_schema = safe_identifier(omop_schema)
    suggestions = []
    seen_concept_ids = set()

    def _add(results: list[dict]):
        for s in results:
            if s["concept_id"] not in seen_concept_ids:
                suggestions.append(s)
                seen_concept_ids.add(s["concept_id"])

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # Strategy 1: Exact match on concept_code (fast — uses btree index)
        _add(_exact_match(cur, source_value, domain, omop_schema))

        # Strategy 2: Concept relationships ("Maps to")
        if source_name:
            _add(_relationship_match(cur, source_value, domain, omop_schema))

        # Strategy 3: Ingredient / DCI match (French→English bridge)
        if source_name:
            _add(_ingredient_match(cur, source_name, domain, omop_schema))

        # Early exit: if we already have enough high-confidence results, skip slow strategies
        high_conf = [s for s in suggestions if s["confidence"] >= 75]
        if len(high_conf) >= max_suggestions:
            suggestions.sort(key=lambda x: x["confidence"], reverse=True)
            return suggestions[:max_suggestions]

        # Strategy 4: Fuzzy matching (trigram similarity)
        if enable_fuzzy:
            search_term = source_name or source_value
            _add(_fuzzy_match(cur, search_term, domain, omop_schema, max_suggestions * 2))

        # Strategy 4b: Keyword search
        if enable_keyword and source_name and len(suggestions) < max_suggestions:
            _add(_keyword_match(cur, source_name, domain, omop_schema, max_suggestions * 2))

        # Strategy 5: Contextual (from already-mapped terms in same vocab)
        if enable_contextual and len(suggestions) < max_suggestions:
            _add(_contextual_match(cur, source_value, domain, omop_schema))

    # Sort by confidence desc, return top N
    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return suggestions[:max_suggestions]


def suggest_batch(
    conn,
    unmapped_terms: list[dict],
    domain: str,
    omop_schema: str = "omop_cdm",
    max_per_term: int = 5,
    enable_fuzzy: bool = True,
    enable_keyword: bool = True,
    enable_contextual: bool = True,
) -> list[dict]:
    """
    Generate suggestions for a batch of unmapped terms.
    Each term dict should have 'source_value' and optionally 'source_name'.
    Returns list of {source_value, source_name, suggestions: [...]}.
    """
    results = []
    for term in unmapped_terms:
        sv = term.get("source_value", "")
        sn = term.get("source_name", "")
        try:
            suggs = suggest_mappings(
                conn, sv, sn, domain, omop_schema, max_per_term,
                enable_fuzzy=enable_fuzzy,
                enable_keyword=enable_keyword,
                enable_contextual=enable_contextual,
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

def _exact_match(cur, source_value: str, domain: str, schema: str) -> list[dict]:
    """Find concepts where concept_code exactly matches source_value."""
    try:
        cur.execute(psysql.SQL("""
            SELECT c.concept_id, c.concept_name, c.concept_code,
                   c.vocabulary_id, c.domain_id, c.standard_concept
            FROM {}.{} c
            WHERE c.concept_code = %(sv)s
              AND c.invalid_reason IS NULL
              AND c.standard_concept = 'S'
            ORDER BY
              CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
              c.concept_name
            LIMIT 5
        """).format(psysql.Identifier(schema), psysql.Identifier('concept')), {"sv": source_value, "domain": domain})
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

def _relationship_match(cur, source_value: str, domain: str, schema: str) -> list[dict]:
    """Find 'Maps to' relationships from source concept codes."""
    try:
        cur.execute(psysql.SQL("""
            SELECT DISTINCT
                c2.concept_id, c2.concept_name, c2.concept_code,
                c2.vocabulary_id, c2.domain_id, c2.standard_concept,
                CASE WHEN c2.domain_id = %(domain)s THEN 0 ELSE 1 END AS domain_rank
            FROM {schema}.{concept} c1
            JOIN {schema}.{concept_relationship} cr
              ON c1.concept_id = cr.concept_id_1
              AND cr.relationship_id = 'Maps to'
              AND cr.invalid_reason IS NULL
            JOIN {schema}.{concept2} c2
              ON cr.concept_id_2 = c2.concept_id
              AND c2.standard_concept = 'S'
              AND c2.invalid_reason IS NULL
            WHERE c1.concept_code = %(sv)s
            ORDER BY domain_rank
            LIMIT 5
        """).format(
            schema=psysql.Identifier(schema),
            concept=psysql.Identifier('concept'),
            concept_relationship=psysql.Identifier('concept_relationship'),
            concept2=psysql.Identifier('concept'),
        ), {"sv": source_value, "domain": domain})
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


def _form_order_clause(form_keywords: list[str], alias: str = "c") -> str:
    """Build a CASE WHEN clause to prioritize concepts matching the galenic form."""
    if not form_keywords:
        return "0+0"
    conditions = " OR ".join(
        f"{alias}.concept_name ILIKE %({_form_param(i)})s"
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
    cur, source_name: str, domain: str, schema: str
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

    form_order = _form_order_clause(form_keywords)
    fparams = _form_params(form_keywords)

    # Brand name ordering: concepts with [BrandName] ranked higher
    if brand:
        brand_order = "CASE WHEN c.concept_name ILIKE %(brand_pat)s THEN 0 ELSE 1 END"
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

            ingredient_sql = psysql.SQL("""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.vocabulary_id, c.domain_id, c.standard_concept
                FROM {schema}.{table} c
                WHERE c.concept_name ILIKE %(term)s
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                ORDER BY
                  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
            """).format(schema=psysql.Identifier(schema), table=psysql.Identifier('concept'))
            # brand_order and form_order are code-generated SQL fragments (not user input)
            order_tail = psysql.SQL("  {brand_order}, {form_order}, LENGTH(c.concept_name) LIMIT 5").format(
                brand_order=psysql.SQL(brand_order),
                form_order=psysql.SQL(form_order),
            )
            cur.execute(ingredient_sql + order_tail, {"term": search_term, "domain": domain, **fparams})
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
            cur.execute(psysql.SQL("""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.vocabulary_id, c.domain_id, c.standard_concept
                FROM {schema}.{syn_table} cs
                JOIN {schema}.{concept} c ON cs.concept_id = c.concept_id
                WHERE cs.concept_synonym_name ILIKE %(term)s
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                GROUP BY c.concept_id, c.concept_name, c.concept_code,
                         c.vocabulary_id, c.domain_id, c.standard_concept
                ORDER BY
                  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
                  LENGTH(c.concept_name)
                LIMIT 5
            """).format(
                schema=psysql.Identifier(schema),
                syn_table=psysql.Identifier('concept_synonym'),
                concept=psysql.Identifier('concept'),
            ), {"term": syn_term, "domain": domain})
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


# ──── Strategy 4: Fuzzy Matching ────

def _fuzzy_match(
    cur, search_term: str, domain: str, schema: str, limit: int = 10
) -> list[dict]:
    """
    Fuzzy match using ILIKE and trigram similarity.
    Falls back to ILIKE if pg_trgm is not available.
    """
    results = []

    # Try trigram similarity first
    try:
        cur.execute(psysql.SQL("""
            SELECT c.concept_id, c.concept_name, c.concept_code,
                   c.vocabulary_id, c.domain_id, c.standard_concept,
                   similarity(c.concept_name, %(term)s) AS sim
            FROM {}.{} c
            WHERE c.concept_name %% %(term)s
              AND c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
            ORDER BY sim DESC,
              CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END
            LIMIT %(lim)s
        """).format(psysql.Identifier(schema), psysql.Identifier('concept')), {"term": search_term, "domain": domain, "lim": limit})
        rows = cur.fetchall()
        for r in rows:
            sim = float(r["sim"]) if r["sim"] else 0
            results.append({
                "concept_id": r["concept_id"],
                "concept_name": r["concept_name"],
                "concept_code": r["concept_code"],
                "vocabulary_id": r["vocabulary_id"],
                "domain_id": r["domain_id"],
                "standard_concept": r["standard_concept"],
                "confidence": min(int(sim * 80), 75),  # Cap at 75% for fuzzy
                "source": "fuzzy",
            })
        return results
    except Exception:
        # pg_trgm not available — fall back to ILIKE on concept + synonym
        try:
            cur.connection.rollback()
            cur.execute(psysql.SQL("""
                SELECT concept_id, concept_name, concept_code,
                       vocabulary_id, domain_id, standard_concept
                FROM (
                    SELECT c.concept_id, c.concept_name, c.concept_code,
                           c.vocabulary_id, c.domain_id, c.standard_concept
                    FROM {schema}.{concept} c
                    WHERE c.concept_name ILIKE %(term)s
                      AND c.standard_concept = 'S'
                      AND c.invalid_reason IS NULL
                    UNION
                    SELECT c.concept_id, c.concept_name, c.concept_code,
                           c.vocabulary_id, c.domain_id, c.standard_concept
                    FROM {schema}.{syn_table} cs
                    JOIN {schema}.{concept2} c ON cs.concept_id = c.concept_id
                    WHERE cs.concept_synonym_name ILIKE %(term)s
                      AND c.standard_concept = 'S'
                      AND c.invalid_reason IS NULL
                ) sub
                ORDER BY LENGTH(concept_name),
                  CASE WHEN domain_id = %(domain)s THEN 0 ELSE 1 END
                LIMIT %(lim)s
            """).format(
                schema=psysql.Identifier(schema),
                concept=psysql.Identifier('concept'),
                syn_table=psysql.Identifier('concept_synonym'),
                concept2=psysql.Identifier('concept'),
            ), {"term": f"%{search_term}%", "domain": domain, "lim": limit})
            rows = cur.fetchall()
            for r in rows:
                results.append({
                    "concept_id": r["concept_id"],
                    "concept_name": r["concept_name"],
                    "concept_code": r["concept_code"],
                    "vocabulary_id": r["vocabulary_id"],
                    "domain_id": r["domain_id"],
                    "standard_concept": r["standard_concept"],
                    "confidence": 50,
                    "source": "fuzzy",
                })
            return results
        except Exception as e:
            logger.warning("Fuzzy match error: %s", e)
            return []


# ──── Strategy 4b: Keyword Search ────

_STOP_WORDS = {
    "the", "of", "a", "an", "and", "or", "by", "for", "in", "on", "at",
    "to", "with", "without", "from", "per", "via", "using", "not", "non",
    "less", "more", "than", "other", "each", "that", "this", "which",
}


def _extract_keywords(text: str, min_len: int = 4) -> list[str]:
    """Extract significant words from a description, filtering stop words."""
    words = re.findall(r'[a-zA-Z]+', text.lower())
    return [w for w in words if len(w) >= min_len and w not in _STOP_WORDS][:5]


def _keyword_match(
    cur, search_term: str, domain: str, schema: str, limit: int = 10
) -> list[dict]:
    """
    Search concepts by significant keywords from the description.
    Uses ILIKE with AND logic on top keywords for better recall than trigram.
    """
    keywords = _extract_keywords(search_term)
    if not keywords:
        return []

    results = []
    try:
        # Strategy A: AND all keywords (precise)
        if len(keywords) >= 2:
            where_parts = []
            params = {"domain": domain, "lim": limit}
            for i, kw in enumerate(keywords[:4]):
                pname = f"kw{i}"
                where_parts.append(f"c.concept_name ILIKE %({pname})s")
                params[pname] = f"%{kw}%"

            where_sql = psysql.SQL(' AND ').join(psysql.SQL(wp) for wp in where_parts)
            kw_query = psysql.SQL(
                "SELECT c.concept_id, c.concept_name, c.concept_code,"
                "       c.vocabulary_id, c.domain_id, c.standard_concept"
                " FROM {schema}.{table} c"
                " WHERE "
            ).format(schema=psysql.Identifier(schema), table=psysql.Identifier('concept')) + where_sql + psysql.SQL(
                "  AND c.standard_concept = 'S'"
                "  AND c.invalid_reason IS NULL"
                " ORDER BY"
                "  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,"
                "  LENGTH(c.concept_name)"
                " LIMIT %(lim)s"
            )
            cur.execute(kw_query, params)
            rows = cur.fetchall()
            seen = set()
            for r in rows:
                if r["concept_id"] not in seen:
                    results.append({
                        "concept_id": r["concept_id"],
                        "concept_name": r["concept_name"],
                        "concept_code": r["concept_code"],
                        "vocabulary_id": r["vocabulary_id"],
                        "domain_id": r["domain_id"],
                        "standard_concept": r["standard_concept"],
                        "confidence": 60,
                        "source": "keyword",
                    })
                    seen.add(r["concept_id"])

        # Strategy B: first keyword only (broader) if not enough results
        if len(results) < 3 and keywords:
            main_kw = max(keywords, key=len)  # longest keyword = most specific
            params2 = {"kw": f"%{main_kw}%", "domain": domain, "lim": limit}
            cur.execute(psysql.SQL("""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.vocabulary_id, c.domain_id, c.standard_concept
                FROM {schema}.{table} c
                WHERE c.concept_name ILIKE %(kw)s
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                ORDER BY
                  CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END,
                  LENGTH(c.concept_name)
                LIMIT %(lim)s
            """).format(schema=psysql.Identifier(schema), table=psysql.Identifier('concept')), params2)
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
                        "confidence": 50,
                        "source": "keyword",
                    })
                    seen.add(r["concept_id"])

    except Exception as e:
        logger.warning("Keyword match error: %s", e)
        try:
            cur.connection.rollback()
        except Exception:
            pass

    return results


# ──── Strategy 5: Contextual ────

def _contextual_match(cur, source_value: str, domain: str, schema: str) -> list[dict]:
    """
    Look at how similar source_values in the same vocabulary are mapped
    via source_to_concept_map, and suggest similar target concepts.
    """
    try:
        # Get the vocabulary prefix (e.g., first part of source_value before any separator)
        prefix = source_value.split(".")[0].split("-")[0].split("_")[0][:5]
        if len(prefix) < 2:
            return []

        cur.execute(psysql.SQL("""
            SELECT
                c.concept_id, c.concept_name, c.concept_code,
                c.vocabulary_id, c.domain_id, c.standard_concept,
                CASE WHEN c.domain_id = %(domain)s THEN 0 ELSE 1 END AS domain_rank
            FROM {schema}.{stcm} stcm
            JOIN {schema}.{concept} c ON stcm.target_concept_id = c.concept_id
            WHERE stcm.source_code LIKE %(prefix)s
              AND c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
              AND stcm.target_concept_id != 0
            GROUP BY c.concept_id, c.concept_name, c.concept_code,
                     c.vocabulary_id, c.domain_id, c.standard_concept
            ORDER BY domain_rank
            LIMIT 5
        """).format(
            schema=psysql.Identifier(schema),
            stcm=psysql.Identifier('source_to_concept_map'),
            concept=psysql.Identifier('concept'),
        ), {"prefix": f"{prefix}%", "domain": domain})
        rows = cur.fetchall()
        return [
            {
                "concept_id": r["concept_id"],
                "concept_name": r["concept_name"],
                "concept_code": r["concept_code"],
                "vocabulary_id": r["vocabulary_id"],
                "domain_id": r["domain_id"],
                "standard_concept": r["standard_concept"],
                "confidence": 40,
                "source": "contextual",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Contextual match error: %s", e)
        cur.connection.rollback()
        return []
