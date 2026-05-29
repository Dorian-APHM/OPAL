"""
extract.py — Prompt FR brut → JSON cohorte structuré.

Compatible avec le schéma temporal d'OPAL `cohort/sql_builder.py` :
  - absolute_window      (date_from, date_to)
  - within_days          (days_before/after, relative_to=index)
  - relative_to_criterion (reference_criterion_id, relation, days_before/after)

Le retour de extract_cohort() est ensuite consommé en aval :
  - pour chaque criterion.label → on lance le RAG (retrieve.py) pour résoudre
    en codes (CIM10/CCAM/ATC/source_value Measurement)
  - le bloc temporal / value / demographics est directement utilisable par
    OPAL sql_builder une fois les codes injectés.
"""
import json
from datetime import date

from llm import LLMClient, embedded_client

TODAY_ISO = date.today().isoformat()  # injected into the prompt for "il y a X mois"


EXTRACT_SYSTEM = f"""Tu es un assistant d'extraction de cohorte médicale OMOP.
À partir d'une requête en langage naturel d'un médecin français, tu extrais les critères
en un objet JSON structuré.

Date du jour : {TODAY_ISO}

SCHÉMA OBLIGATOIRE :
{{
  "demographics": {{
    "age_min": int | null,
    "age_max": int | null,
    "sex": "M" | "F" | null
  }},
  "criteria": [
    {{
      "id": "crit1",
      "domain": "Condition" | "Drug" | "Procedure" | "Measurement" | "Visit",
      "label": "terme tel que mentionné par le médecin (FR brut)",
      "negation": false,
      "operator_with_next": "AND" | "OR",
      "temporal": null,
      "value": null
    }}
  ]
}}

Le champ "temporal" prend l'une des formes suivantes (ou null) :
  - {{"type": "absolute_window", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}}
    (l'un ou l'autre peut manquer pour signifier "depuis" ou "jusqu'à")
  - {{"type": "within_days", "relative_to": "index", "days_before": int, "days_after": int}}
    (pour "il y a X mois", "dans les X jours", etc. — relatif à l'entrée dans la cohorte)
  - {{"type": "relative_to_criterion", "reference_criterion_id": "crit1",
      "relation": "before" | "during" | "after" | "overlaps",
      "days_before": int, "days_after": int}}
    (pour "X dans les Y jours suivant Z")

Le champ "value" est uniquement pour Measurement :
  {{"operator": ">" | "<" | ">=" | "<=" | "=" | "between",
    "value": float, "value_high": float | null, "unit": "string"}}

RÈGLES :
1. label = exactement ce que le médecin a tapé, sans normalisation médicale, sans code
2. Choix du domain :
   - Condition = pathologies CIM10 (diabète, HTA, IDM, AVC, cancer…)
   - Drug = médicaments (metformine, insuline, doliprane…)
   - Procedure = actes chirurgicaux ou techniques CCAM (exérèse, pose de prothèse…)
   - Measurement = analyses biologiques (glycémie, créatinine, HbA1c…)
   - Visit = hospitalisation en tant que telle (sans pathologie particulière)
3. negation = true pour "sans X", "absence de X", "non X", "pas de X"
4. operator_with_next : opérateur logique entre ce critère et le suivant ; AND par défaut
5. Conversions temporelles :
   - "entre 2020 et 2022" → absolute_window {{date_from: "2020-01-01", date_to: "2022-12-31"}}
   - "depuis janvier 2023" → absolute_window {{date_from: "2023-01-01"}}
   - "avant 2021" → absolute_window {{date_to: "2020-12-31"}}
   - "il y a moins de 6 mois" → within_days {{days_before: 180, relative_to: "index"}}
   - "dans la dernière année" → within_days {{days_before: 365, relative_to: "index"}}
   - "30 jours après X" → relative_to_criterion {{reference_criterion_id: "<id de X>", relation: "after", days_after: 30}}
6. Convertir mois→jours en utilisant 30 jours/mois pour within_days
7. Pas mentionné → null ou absent
8. Tu réponds UNIQUEMENT en JSON valide, sans préambule, sans markdown."""


def extract_cohort(prompt: str, llm: LLMClient | None = None) -> dict:
    """Send the prompt to the LLM (OpenAI-compatible) and parse its JSON response.

    `llm` is supplied per request by the service (embedded local model, or the
    institution's on-premise endpoint). Falls back to the embedded client for CLI use.
    """
    client = llm or embedded_client()
    return client.complete_json(EXTRACT_SYSTEM, prompt, max_tokens=800)


# ──────────────────────────────────────────────────────────────────────
# Test suite — focus on temporal handling

TESTS = [
    # Baseline (no temporal)
    "Patients diabétiques de type 2 sous metformine, hommes de 25 à 40 ans",

    # absolute_window
    "Patients diabétiques hospitalisés entre 2020 et 2022",
    "Patients sous metformine depuis janvier 2023",
    "AVC diagnostiqués avant 2021",

    # within_days (relative to index)
    "Patients ayant fait un infarctus du myocarde il y a moins de 6 mois",
    "Patients hospitalisés pour AVC dans la dernière année",

    # relative_to_criterion
    "Patients ayant fait un AVC dans les 30 jours suivant un IDM",

    # Measurement with value
    "Diabétiques de type 2 avec glycémie à jeun supérieure à 1.26 g/L",
    "Hémoglobine glyquée supérieure ou égale à 7%",

    # Negation
    "Patients DT2 sans insulinothérapie",

    # Mixed logic
    "Femmes 50-70 ans sous metformine ou insuline et ayant fait un AVC",
]


def main() -> None:
    for p in TESTS:
        print(f"\n{'='*92}\n  {p}\n{'='*92}")
        try:
            out = extract_cohort(p)
            print(json.dumps(out, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
