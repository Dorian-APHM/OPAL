"""
Retrieval over a per-CDM index built from OPAL's source_value_cache.

Pipeline per criterion label:
  1. LLM expansion (Qwen2.5) enriches the term (abbreviations, synonyms)
  2. bi-encoder (e5) similarity over the CDM index
  3. domain filter + concept-set grouping:
       - Condition : group by CIM10 3-char prefix (E11 + all E11x present in CDM)
       - Drug      : group by ATC, returning the therapeutic family as SEVERAL
                     groups within a score gap (like Condition) — not just the best
                     one. Class queries ("anti-inflammatoire") work via the LLM
                     expansion, which turns them into representative molecules
                     (ibuprofène, kétoprofène…) that SapBERT matches well; the ATC
                     grouping then rolls them up into the family (all M01A*).
       - Procedure / Measurement : singleton per source_value
  Returns the FULL concept-set (all matching codes), never a single top-1.

Metadata schema (from index_builder): {domain, source_value, source_atc, label, n_records}
"""
from collections import defaultdict

import numpy as np

import index_builder
from embed_client import EmbeddingClient
from llm import LLMClient, embedded_client

MODEL_NAME = index_builder.MODEL_NAME
OVERFETCH = 100


# ──────────────────────────────────────────────────────────────────────
# LLM expansion

EXPAND_SYSTEM = """Tu es un médecin expert en terminologie médicale française. Pour chaque terme médical, tu produis une reformulation enrichie en UNE LIGNE courte (5-10 mots).

RÈGLES STRICTES :
- Le terme original DOIT être réécrit en TOUT premier, complet, tel quel
- Si c'est une abréviation : ajouter la forme développée
- Ajouter 1-2 synonymes cliniques fréquents en français
- Privilégier la forme LA PLUS FRÉQUENTE en pratique
- INTERDIT : ajouter pulmonaire/rénal/secondaire si le terme est primaire/essentiel
- INTERDIT : ajouter des comorbidités (HTA, diabète, etc.) si pas dans le terme
- INTERDIT : tout caractère non latin (pas de chinois, japonais...)
- Pas de phrase complète, juste des mots-clés français séparés par des espaces

Exemples :
Terme: AVC
Réponse: AVC accident vasculaire cérébral infarctus cérébral attaque cérébrale

Terme: DT2
Réponse: DT2 diabète sucré de type 2 diabète non insulinodépendant

Terme: HTA
Réponse: HTA hypertension artérielle essentielle primitive

Terme: metformine
Réponse: metformine biguanide antidiabétique oral

Terme: glycémie à jeun
Réponse: glycémie à jeun glucose sanguin matinal hyperglycémie"""


def expand_label(label: str, llm: LLMClient | None = None) -> str:
    client = llm or embedded_client()
    txt = client.complete(EXPAND_SYSTEM, f"Terme: {label}\nRéponse:",
                          max_tokens=60, timeout=60).strip().split("\n")[0].strip()
    if txt.lower().startswith("réponse:"):
        txt = txt[8:].strip()
    return txt or label


# Drug terms are resolved to representative molecules (DCI): SapBERT matches molecule
# NAMES well (its strength), whereas it fails on therapeutic-class labels. A class
# term thus becomes a handful of molecules whose products the ATC grouping rolls up
# into the full family. The LLM reliably knows class -> molecules (far more than ATC
# codes). Each returned molecule is fed to the retriever as a separate query item.
DRUG_EXPAND_SYSTEM = """Tu es pharmacologue clinicien. On te donne un terme de prescription : une molécule (DCI), un nom commercial, ou une classe thérapeutique. Tu réponds UNIQUEMENT par une liste de DCI (noms de molécules) en français, séparées par des virgules, sur UNE seule ligne.

RÈGLES STRICTES :
- Classe thérapeutique -> 6 à 12 DCI les plus représentatives de la classe.
- Molécule (DCI) -> la molécule elle-même (et ses synonymes DCI éventuels).
- Nom commercial -> la/les DCI correspondantes.
- UNIQUEMENT des noms de molécules (DCI) : jamais de nom de classe, jamais de phrase, pas de dosage ni de forme.
- Pas de caractère non latin.

Exemples :
Terme: anti-inflammatoire
Réponse: ibuprofène, kétoprofène, diclofénac, naproxène, célécoxib, indométacine, piroxicam, acide méfénamique
Terme: antibiotique
Réponse: amoxicilline, ceftriaxone, ciprofloxacine, azithromycine, gentamicine, vancomycine, métronidazole, pipéracilline
Terme: antidiabétique oral
Réponse: metformine, gliclazide, glimépiride, sitagliptine, répaglinide, empagliflozine, dapagliflozine
Terme: anticoagulant
Réponse: énoxaparine, héparine, warfarine, fluindione, apixaban, rivaroxaban, dabigatran
Terme: metformine
Réponse: metformine
Terme: doliprane
Réponse: paracétamol"""


def expand_drug_terms(label: str, llm: LLMClient | None = None, max_terms: int = 12) -> list[str]:
    """Drug term (molecule / brand / therapeutic class) -> representative DCI list.

    Lets a class query resolve to molecules SapBERT can match; the ATC grouping then
    returns the whole family. Falls back to [label] if the LLM is unavailable/empty.
    """
    client = llm or embedded_client()
    try:
        txt = client.complete(DRUG_EXPAND_SYSTEM, f"Terme: {label}\nRéponse:",
                              max_tokens=80, timeout=60).strip().split("\n")[0].strip()
    except Exception:
        return [label]
    if txt.lower().startswith("réponse:"):
        txt = txt[8:].strip()
    parts = [p.strip() for p in txt.replace(";", ",").split(",")]
    seen, out = set(), []
    for p in parts:
        if len(p) < 3:
            continue
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out[:max_terms] or [label]


# ──────────────────────────────────────────────────────────────────────
# Grouping helpers

def cim10_prefix(code: str) -> str:
    return code[:3] if len(code) > 3 else code


# ──────────────────────────────────────────────────────────────────────
# Retriever (per CDM)

class Retriever:
    # Per-domain absolute score gap (vs top-1) for accepting additional groups.
    # Calibrated for SapBERT (XLM-R CLS cosine): correct-match scores sit LOWER and
    # more spread out than e5's (~0.55-0.80 for a good hit vs e5's 0.80+), so both the
    # gaps and min_top_score are looser than the original e5 values. First pass —
    # refine against more queries if precision/recall needs it.
    DOMAIN_GAP = {
        "Condition":   0.07,
        "Procedure":   0.06,
        "Measurement": 0.06,
    }

    # Drug uses an ABSOLUTE score floor instead of a relative gap. A drug query is a
    # GROUPING (the family, not one code), so we keep EVERY ATC group whose best
    # member clears this floor. A relative gap fails here: with cleaned molecule
    # labels (dose/form stripped) a good hit scores ~0.73-1.0, so one exact molecule
    # match (1.0) would raise a relative bar and drop the rest of the family; mean-
    # while subword look-alikes (metformine~methadone ~0.66) need a hard cutoff. The
    # molecule expansion (service.py) sends each molecule as its own query item, so a
    # group is kept iff some molecule matches its products well. Calibratable.
    DRUG_MIN_SCORE = 0.70

    def __init__(self, cdm_name: str, client: EmbeddingClient, conn=None):
        self.cdm_name = cdm_name
        self.client = client
        self.emb, self.meta = index_builder.load_or_build(cdm_name, client, conn=conn)
        self.domains = sorted({m["domain"] for m in self.meta})
        self.mask = {
            d: np.array([m["domain"] == d for m in self.meta]) for d in self.domains
        }
        # group_key -> list of indices
        self.groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, m in enumerate(self.meta):
            k = self._group_key_for(i)
            if k is not None:
                self.groups[k].append(i)

        # ATC code -> class name, to title Drug groups with their class (e.g. B01AA ->
        # "VITAMIN K ANTAGONISTS") instead of a member's product label. Display only;
        # empty/missing falls back to the representative member label.
        self.atc_labels = index_builder.load_atc_labels(cdm_name)

    def _group_key_for(self, idx: int) -> tuple[str, str] | None:
        m = self.meta[idx]
        if m["domain"] == "Condition":
            return ("Condition", cim10_prefix(m["source_value"]))
        if m["domain"] == "Drug" and m.get("source_atc"):
            return ("Drug", m["source_atc"])
        return None  # Procedure / Measurement : singleton

    def encode_query(self, text: str) -> np.ndarray:
        # Runner returns L2-normalized vectors; no e5-style "query:" prefix for SapBERT.
        return self.client.encode([text]).astype("float32")[0]

    def search_concept_set(self, text: str | list[str], domain: str | None = None,
                           overfetch: int = OVERFETCH,
                           min_top_score: float = 0.55) -> list[dict]:
        # Accept several query forms (e.g. raw label + LLM expansion) and keep the best
        # (max) similarity per concept: the raw mention wins where the expansion dilutes
        # ("cancer de la prostate" -> C61, not the in-situ D07), the expansion wins where
        # it resolves an abbreviation ("AVC" -> I64). Runner returns normalized vectors.
        queries = [text] if isinstance(text, str) else [q for q in text if q]
        qembs = self.client.encode(queries).astype("float32")   # (n_q, dim), normalized
        sims = (self.emb @ qembs.T).max(axis=1)                  # best score per concept
        if domain in self.mask:
            sims = np.where(self.mask[domain], sims, -np.inf)
        if not np.isfinite(sims).any():
            return []

        top_idx = np.argpartition(-sims, min(overfetch, len(sims) - 1))[:overfetch]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        top_idx = [int(i) for i in top_idx if np.isfinite(sims[i])]
        if not top_idx:
            return []

        max_score = float(sims[top_idx[0]])
        if domain == "Drug":
            # Absolute floor: keep the whole therapeutic family, drop subword noise.
            threshold = self.DRUG_MIN_SCORE
            if max_score < threshold:
                return []
        else:
            if max_score < min_top_score:
                return []
            threshold = max_score - self.DOMAIN_GAP.get(domain, 0.010)

        # Products that matched the query themselves (score >= threshold), as opposed
        # to ATC siblings pulled in by group expansion. The UI's "exact molecule" mode
        # (solution A: name match, no ATC expansion) keeps only these.
        passed: set[int] = {i for i in top_idx if float(sims[i]) >= threshold}

        seen_keys: set[tuple[str, str]] = set()
        seen_singletons: set[int] = set()
        results: list[dict] = []
        for idx in top_idx:
            score = float(sims[idx])
            if score < threshold:
                break
            m = self.meta[idx]
            key = self._group_key_for(idx)
            if key is None:
                if idx in seen_singletons:
                    continue
                seen_singletons.add(idx)
                results.append({
                    "domain": m["domain"], "kind": "singleton",
                    "group_key": m["source_value"], "rep_label": m["label"],
                    "score": score, "n_members": 1, "n_matched": 1,
                    "members": [{"source_value": m["source_value"], "label": m["label"],
                                 "matched": True}],
                })
            else:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                idxs = self.groups[key]
                # matched = the product matched the query by name (vs ATC sibling pulled
                # in by expansion). "Exact molecule" mode keeps only matched members.
                members = [{
                    "source_value": self.meta[i]["source_value"],
                    "label": self.meta[i]["label"],
                    "matched": i in passed,
                } for i in idxs]
                # Title Drug groups with their ATC class name when known; keep the
                # representative member label otherwise. Scoped to Drug so a 3-char
                # CIM10 prefix can't collide with a homonymous 3-char ATC code.
                rep_label = m["label"]
                if key[0] == "Drug":
                    rep_label = self.atc_labels.get(key[1]) or m["label"]
                results.append({
                    "domain": m["domain"], "kind": "group",
                    "group_key": key[1], "rep_label": rep_label,
                    "score": score, "n_members": len(members),
                    "n_matched": sum(1 for mem in members if mem["matched"]),
                    "members": members,
                })
        return results


# ──────────────────────────────────────────────────────────────────────
# CLI test

_SHORT = {"Condition": "COND", "Procedure": "PROC", "Drug": "DRUG", "Measurement": "MEAS"}

TESTS = [
    ("diabète de type 2", "Condition"),
    ("metformine", "Drug"),
    ("insulinothérapie", "Drug"),
    ("hypertension artérielle", "Condition"),
    ("insuffisance rénale chronique stade 3", "Condition"),
    ("AVC", "Condition"),
    ("glycémie à jeun", "Measurement"),
    ("radiographie du thorax", "Procedure"),
    ("doliprane", "Drug"),
    ("anti-inflammatoire", "Drug"),       # class query -> AINS family (M01A*)
    ("antibiotique", "Drug"),             # class query -> J01 family
    ("antidiabétique oral", "Drug"),      # class query -> A10B family
]


def main() -> None:
    import sys
    cdm = sys.argv[1] if len(sys.argv) > 1 else "cdm_omop_20260314"
    print(f"Embeddings via opal-sapbert runner ({MODEL_NAME})...")
    client = EmbeddingClient()
    r = Retriever(cdm, client)
    print(f"Index {cdm}: {len(r.meta)} entries, domains={r.domains}\n")
    for label, dom in TESTS:
        if dom == "Drug":
            mols = expand_drug_terms(label)
            queries, exp = [label, *mols], ", ".join(mols)
        else:
            exp = expand_label(label)
            queries = [label, exp]
        groups = r.search_concept_set(queries, domain=dom)
        total = sum(g["n_members"] for g in groups)
        print(f"\n{'='*90}\n  '{label}' [{dom}]  → {len(groups)} groupe(s), {total} code(s)")
        print(f"  expansion: {exp}\n{'='*90}")
        for g in groups[:4]:
            print(f"  ▸ [{g['score']:.3f}] {_SHORT.get(g['domain'],g['domain'])} "
                  f"{g['group_key']:10s} ({g['n_members']}) {g['rep_label'][:60]}")
            for mem in g["members"][:4]:
                print(f"      - {mem['source_value']:10s} {mem['label'][:64]}")
            if g["n_members"] > 4:
                print(f"      … +{g['n_members']-4}")


if __name__ == "__main__":
    main()
