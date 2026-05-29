"""
Person domain analysis — ported from achilles_like/analysis.py.
"""
import logging
from psycopg2 import sql as psysql
from psycopg2.extras import DictCursor

from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)


def run_person_analysis(conn, omop_schema: str = "omop_cdm") -> dict:
    """
    Person domain analyses:
    - Total persons count
    - Gender distribution
    - Birth year distribution
    """
    person_schema = omop_schema.schema_for("person") if hasattr(omop_schema, "schema_for") else safe_identifier(omop_schema)
    concept_schema = omop_schema.schema_for("concept") if hasattr(omop_schema, "schema_for") else safe_identifier(omop_schema)
    _sp = psysql.Identifier(safe_identifier(person_schema))
    _sv = psysql.Identifier(safe_identifier(concept_schema))
    _person = psysql.Identifier("person")
    _concept = psysql.Identifier("concept")

    res = {
        "domain": "Person",
        "table": f"{person_schema}.person",
        "achilles_like": {},
        "mapping": {},
    }

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # Total persons
        cur.execute(psysql.SQL("SELECT COUNT(*) AS n FROM {}.{}").format(_sp, _person))
        total_persons = int(cur.fetchone()["n"] or 0)

        # Gender distribution
        cur.execute(psysql.SQL("""
            SELECT
                p.gender_concept_id,
                COALESCE(c.concept_name, 'UNKNOWN') AS concept_name,
                COUNT(*) AS n
            FROM {pschema}.{person} p
            LEFT JOIN {vschema}.{concept} c ON p.gender_concept_id = c.concept_id
            GROUP BY p.gender_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
            ORDER BY n DESC
        """).format(pschema=_sp, vschema=_sv, person=_person, concept=_concept))
        genders, gender_names, gender_counts = [], [], []
        for r in cur.fetchall():
            genders.append(int(r["gender_concept_id"]) if r["gender_concept_id"] is not None else None)
            gender_names.append(r["concept_name"])
            gender_counts.append(int(r["n"]))

        # Birth year distribution
        cur.execute(psysql.SQL("""
            SELECT year_of_birth::int AS year_of_birth, COUNT(*) AS n
            FROM {pschema}.{person}
            WHERE year_of_birth IS NOT NULL
              AND year_of_birth BETWEEN 1850 AND EXTRACT(YEAR FROM CURRENT_DATE)
            GROUP BY year_of_birth
            ORDER BY year_of_birth
        """).format(pschema=_sp, person=_person))
        years, year_counts = [], []
        for r in cur.fetchall():
            years.append(int(r["year_of_birth"]))
            year_counts.append(int(r["n"]))

        # Race distribution (if available)
        race_ids, race_names, race_counts = [], [], []
        try:
            cur.execute(psysql.SQL("""
                SELECT
                    p.race_concept_id,
                    COALESCE(c.concept_name, 'UNKNOWN') AS concept_name,
                    COUNT(*) AS n
                FROM {pschema}.{person} p
                LEFT JOIN {vschema}.{concept} c ON p.race_concept_id = c.concept_id
                GROUP BY p.race_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
                ORDER BY n DESC
            """).format(pschema=_sp, vschema=_sv, person=_person, concept=_concept))
            for r in cur.fetchall():
                race_ids.append(int(r["race_concept_id"]) if r["race_concept_id"] is not None else None)
                race_names.append(r["concept_name"])
                race_counts.append(int(r["n"]))
        except Exception:
            logger.warning("Failed to fetch race distribution", exc_info=True)
            conn.rollback()

        # Ethnicity distribution (if available)
        eth_ids, eth_names, eth_counts = [], [], []
        try:
            cur.execute(psysql.SQL("""
                SELECT
                    p.ethnicity_concept_id,
                    COALESCE(c.concept_name, 'UNKNOWN') AS concept_name,
                    COUNT(*) AS n
                FROM {pschema}.{person} p
                LEFT JOIN {vschema}.{concept} c ON p.ethnicity_concept_id = c.concept_id
                GROUP BY p.ethnicity_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
                ORDER BY n DESC
            """).format(pschema=_sp, vschema=_sv, person=_person, concept=_concept))
            for r in cur.fetchall():
                eth_ids.append(int(r["ethnicity_concept_id"]) if r["ethnicity_concept_id"] is not None else None)
                eth_names.append(r["concept_name"])
                eth_counts.append(int(r["n"]))
        except Exception:
            logger.warning("Failed to fetch ethnicity distribution", exc_info=True)
            conn.rollback()

    res["achilles_like"]["person_summary"] = {
        "total_persons": total_persons,
        "gender_distribution": {
            "gender_concept_id": genders,
            "gender_name": gender_names,
            "count": gender_counts,
        },
        "birth_year_distribution": {
            "year_of_birth": years,
            "count": year_counts,
        },
        "race_distribution": {
            "race_concept_id": race_ids,
            "race_name": race_names,
            "count": race_counts,
        },
        "ethnicity_distribution": {
            "ethnicity_concept_id": eth_ids,
            "ethnicity_name": eth_names,
            "count": eth_counts,
        },
    }
    return res
