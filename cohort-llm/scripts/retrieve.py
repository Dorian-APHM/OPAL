"""
Retrieval over a per-CDM index built from OPAL's source_value_cache.

Pipeline per criterion label:
  1. LLM expansion (Qwen2.5) enriches the term (abbreviations, synonyms)
  2. bi-encoder (e5) similarity over the CDM index
  3. domain filter + concept-set grouping:
       - Condition : group by CIM10 3-char prefix (E11 + all E11x present in CDM)
       - Drug      : group by ATC (top-1 ATC = e.g. all metformin source_values)
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
        "Drug":        0.0,    # top-1 ATC only
        "Condition":   0.07,
        "Procedure":   0.06,
        "Measurement": 0.06,
    }

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
        if max_score < min_top_score:
            return []
        threshold = max_score - self.DOMAIN_GAP.get(domain, 0.010)

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
                    "score": score, "n_members": 1,
                    "members": [{"source_value": m["source_value"], "label": m["label"]}],
                })
            else:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                idxs = self.groups[key]
                members = [{
                    "source_value": self.meta[i]["source_value"],
                    "label": self.meta[i]["label"],
                } for i in idxs]
                results.append({
                    "domain": m["domain"], "kind": "group",
                    "group_key": key[1], "rep_label": m["label"],
                    "score": score, "n_members": len(members), "members": members,
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
]


def main() -> None:
    import sys
    cdm = sys.argv[1] if len(sys.argv) > 1 else "cdm_omop_20260314"
    print(f"Embeddings via opal-sapbert runner ({MODEL_NAME})...")
    client = EmbeddingClient()
    r = Retriever(cdm, client)
    print(f"Index {cdm}: {len(r.meta)} entries, domains={r.domains}\n")
    for label, dom in TESTS:
        exp = expand_label(label)
        groups = r.search_concept_set(exp, domain=dom)
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
