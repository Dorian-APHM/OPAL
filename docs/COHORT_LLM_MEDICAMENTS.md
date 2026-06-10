# Cohort-LLM — Recherche par médicament (Drug)

Comment l'assistant IA de cohortes résout un terme médicament (molécule, nom
commercial **ou classe thérapeutique**) en **codes OMOP réels** de ton CDM.

> Voir aussi [COHORT_LLM.md](COHORT_LLM.md) pour l'architecture générale (modes,
> déploiement, sécurité). Cette fiche détaille uniquement le domaine **Drug**.

---

## 1. Principe

Un terme médicament, c'est presque toujours un **groupement**, pas un seul code.
« anti-inflammatoire » = toute la famille des AINS ; « doliprane » = toutes les
présentations de paracétamol. La résolution suit donc le **même modèle que la
CIM10** : on renvoie **plusieurs groupes** (la famille), jamais le seul meilleur.

L'astuce centrale : on **n'essaie pas** de faire matcher le mot « anti-inflammatoire »
contre un libellé de classe (SapBERT en est incapable, cf. §6). On le **convertit en
noms de molécules** via le LLM, et SapBERT matche les **noms de molécules** — c'est
sa force.

```
"anti-inflammatoire"
   │  (1) LLM : terme → molécules
   ▼
[ibuprofène, kétoprofène, diclofénac, naproxène, célécoxib, …]
   │  (2) SapBERT : chaque molécule → ses produits du CDM (max par produit)
   ▼
produits au-dessus du plancher 0.70
   │  (3) groupement par code ATC (source_atc)
   ▼
M01AE (67)  M01AB (27)  M01AH (13)  …   ← la famille AINS, en plusieurs groupes
   │  (4) titre = nom de classe ATC
   ▼
"Propionic acid derivatives"  "Acetic acid derivatives"  "Coxibs"
```

---

## 2. Le flux `/draft` de bout en bout

```
Navigateur
  │  prompt FR ("patients sous anti-inflammatoires")
  ▼
Backend  /api/cohort-llm/draft        (auth Keycloak, check_cdm_access)
  │  relais ; en on-premise injecte {base_url, model, api_key} du LLM
  ▼
opal-llm /draft
  ├─ extract.py  : prompt → {demographics, criteria[]}   (LLM)
  └─ pour chaque critère Drug :
       ├─ expand_drug_terms()      : terme → liste de DCI  (LLM)
       ├─ search_concept_set()     : [label, *molécules] → SapBERT (/encode)
       │     · max par produit · plancher 0.70 · groupement ATC · titre de classe
       └─ crit["concept_sets"] = groupes
  ▼
Backend (relais) → Navigateur → UI (cases à cocher, membres dépliables)
```

| Étape | Code | Rôle |
|---|---|---|
| Relais | [backend/modules/cohort_llm_router.py](../backend/modules/cohort_llm_router.py) | Auth, injection LLM, forward HTTP |
| Extraction | [cohort-llm/scripts/extract.py](../cohort-llm/scripts/extract.py) | Prompt FR → critères structurés |
| Expansion + matching | [cohort-llm/scripts/retrieve.py](../cohort-llm/scripts/retrieve.py) | `expand_drug_terms`, `search_concept_set` |
| Construction de l'index | [cohort-llm/scripts/index_builder.py](../cohort-llm/scripts/index_builder.py) | `clean_drug_label`, embeddings, `load_atc_labels` |
| Affichage | [frontend/src/components/cohort/CriterionReviewCard.tsx](../frontend/src/components/cohort/CriterionReviewCard.tsx) | Groupes cochables |

---

## 3. Expansion : terme → molécules (DCI)

`expand_drug_terms(label, llm)` demande au LLM une **liste de DCI représentatives**.
Le LLM sait parfaitement faire « classe → molécules » (bien mieux que « terme → code
ATC », qu'un petit modèle hallucine).

| Terme saisi | Expansion (molécules) |
|---|---|
| anti-inflammatoire | ibuprofène, kétoprofène, diclofénac, naproxène, célécoxib, indométacine… |
| antibiotique | amoxicilline, ceftriaxone, ciprofloxacine, azithromycine, vancomycine… |
| antidiabétique oral | metformine, gliclazide, glimépiride, sitagliptine, répaglinide… |
| metformine (molécule) | metformine |
| doliprane (marque) | paracétamol |

La requête finale envoyée au retriever est `[label, *molécules]` : le **libellé brut
ET chaque molécule**, chacun comme **item de requête séparé**.

---

## 4. Matching + groupement (`search_concept_set`)

1. **Encodage** : tous les items de requête sont encodés par **opal-sapbert** (`/encode`,
   vecteurs L2-normalisés). Chaque produit du CDM reçoit son **meilleur score (max)**
   parmi toutes les requêtes — chaque molécule « tire » ses propres produits.
2. **Plancher absolu** : on garde les produits dont le score ≥ **`DRUG_MIN_SCORE = 0.70`**.
   Si le meilleur produit est sous 0.70 → aucun match.
3. **Groupement ATC** : les survivants sont regroupés par **code ATC** (`source_atc`).
   Un groupe = **tous les `source_value` du CDM partageant cet ATC** (pas seulement
   les produits matchés — toute la famille au même code).
4. **Titre** : chaque groupe est titré par le **nom de sa classe ATC** (table
   `atc_labels`), avec repli sur le libellé d'un membre si le code n'est pas nommé.

> **Pourquoi un plancher absolu et pas un écart relatif** (comme la CIM10) ? Une fois
> les libellés nettoyés (§5), un bon match score 0.73–1.0. Si une molécule matche à
> 1.0, un écart relatif (ex. −0.10) remonterait le plancher à 0.90 et **couperait le
> reste de la famille**. Le plancher absolu garde toute la famille et coupe le bruit
> de sous-mots (ex. « metformine » ~ « methadone » à 0.66).

---

## 5. L'index RAG et le nettoyage des libellés

L'index est construit **par CDM** depuis le `source_value_cache` (app DB) par
`index_builder.py`, embeddings via opal-sapbert, stockés en fichiers
(`embeddings.npy` + `metadata.jsonl`) dans le volume `opal_llm_index`.

**Nettoyage des libellés Drug** (`clean_drug_label`) : les libellés du CDM
(`MOLÉCULE DOSE FORME (MARQUE)`) noient le nom de molécule. On retire
**dosage / unités / forme galénique**, on **garde molécule + marque**. Seul le texte
**embeddé** est nettoyé ; le **libellé original reste affiché**.

| Libellé CDM | Texte embeddé |
|---|---|
| `METFORMINE 500 MG CPR (GLUCOPHAGE)` | `metformine glucophage` |
| `DOLIPRANE 1G CPR` | `doliprane` |
| `VANCOMYCINE 1 G PDR INJ` | `vancomycine` |

Impact mesuré (cosinus SapBERT, requête « metformine ») :

| Texte embeddé | Score |
|---|---|
| `METFORMINE 500 MG CPR (GLUCOPHAGE)` (brut) | **0.44** ❌ (< 0.70 → aucun match) |
| `metformine glucophage` (nettoyé) | **0.62–0.92** ✅ |

On garde molécule **et** marque parce que les deux sont cherchés : « metformine »
(DCI) **et** « glucophage » (marque) doivent matcher.

> Changer `clean_drug_label` **nécessite de reconstruire l'index** (re-embedding).
> Changer `DRUG_MIN_SCORE` ou l'expansion ne le nécessite pas.

---

## 6. Les noms de classe ATC (titres de groupe)

Un groupe est titré par sa **classe ATC**, pas par un médicament membre (qui prêtait
à confusion : « WARFARINE… » comme titre de toute la classe des AVK).

- Table app DB **`atc_labels`** `(cdm_name, atc_code, label)` — **affichage uniquement**.
- Moissonnée par le backend ([atc_labels.py](../backend/modules/concept/atc_labels.py))
  depuis le `concept` ATC de ton CDM, après la construction du cache Drug.
- Lue par le retriever (`load_atc_labels`) ; lookup **scopé au domaine Drug** pour
  éviter qu'un préfixe CIM10 3-car (ex. `C01`) hérite d'un nom ATC homonyme.
- **Noms en anglais** (c'est ce que contient le vocabulaire ATC du CDM) : « Vitamin K
  antagonists », « Biguanides », « Fluoroquinolones »… Une traduction FR (par le LLM,
  une fois) est possible — c'est de l'affichage, sans impact sur le matching.

> ⚠️ Ne pas confondre `atc_labels` (titres, affichage) avec l'ancienne approche
> « nœuds de classe ATC embeddés » qui a été **rejetée** : embedder les libellés de
> classe pour le *matching* échouait (SapBERT alignant des synonymes d'entités, pas
> des périphrases de classe — « anti-inflammatoire »→« Antiinfectives »,
> « anticoagulant »→« hémostatiques », l'opposé clinique).

---

## 7. Paramètres

| Paramètre | Lieu | Défaut | Effet |
|---|---|---|---|
| `DRUG_MIN_SCORE` | `retrieve.py` (classe `Retriever`) | `0.70` | Plancher de score d'un groupe. ↑ = moins de bruit, risque de couper des familles ; ↓ = plus de rappel, plus de bruit de bord. |
| `clean_drug_label` | `index_builder.py` | — | Règles de nettoyage (dosage/forme/unités). Modif ⇒ **rebuild d'index**. |
| Prompt d'expansion | `DRUG_EXPAND_SYSTEM` dans `retrieve.py` | — | Nombre/qualité des molécules proposées (6–12). |

---

## 8. Exemples (testés sur `cdm_omop_20260314`)

| Requête | Groupes ATC renvoyés | Codes |
|---|---|---|
| metformine | A10BA « Biguanides » | 19 |
| glucophage (marque) | A10BA « Biguanides » | 19 |
| doliprane (marque) | N02BE « Anilides » | 83 |
| antidiabétique oral | A10BB, A10BX, A10BD, A10BK, A10BA | 105 |
| anti-inflammatoire | M01AE, M01AB, M01AH (+ bruit de bord ~0.71) | ~107 |
| antibiotique | J01CA, J01DD, J01FA, J01MA, J01XA, J01AA… | ~312 |
| anticoagulant | B01AA « Vitamin K antagonists », B01AF, B01AB | 93 |

---

## 9. Limites connues

- **Bruit de bord** : des groupes proches du plancher (~0.71) peuvent apparaître (ex.
  anesthésiques locaux sous « anti-inflammatoire »). L'UI montre une liste cochable —
  l'utilisateur décoche. Calibrable via `DRUG_MIN_SCORE`.
- **Dépend du LLM** pour l'expansion : si le LLM est indisponible, `expand_drug_terms`
  retombe sur `[label]` seul (une classe ne se résout alors plus en famille).
- **Dépend de `source_atc`** : le groupement utilise la colonne (non standard)
  `drug_source_atc` du CDM. Un produit sans ATC ne se regroupe pas (singleton).
- **Largeur du groupe = granularité ATC stockée** : groupement par `source_atc` exact ;
  la finesse dépend du niveau ATC présent dans le CDM.
- **Noms de classe en anglais** (cf. §6).
- **Requête DCI sur libellé marque-seul** : un produit étiqueté seulement par sa marque
  (sans la DCI) ne matche pas bien une requête DCI, et inversement — d'où le choix de
  garder molécule + marque à l'embedding.
