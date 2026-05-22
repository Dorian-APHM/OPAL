# OPAL — Document Méthodologique

Ce document décrit l'ensemble des méthodes, algorithmes et techniques analytiques implémentés dans OPAL. Il est destiné aux utilisateurs, évaluateurs et auditeurs souhaitant comprendre les fondements techniques de chaque fonctionnalité.

---

## Table des matières

1. [Analyse qualité des données](#1-analyse-qualité-des-données)
2. [Contrôles de conformité CDM](#2-contrôles-de-conformité-cdm)
3. [Construction de cohortes](#3-construction-de-cohortes)
4. [Caractérisation de cohortes (Table 1)](#4-caractérisation-de-cohortes-table-1)
5. [Comparaison de cohortes (SMD)](#5-comparaison-de-cohortes-smd)
6. [Suggestions de mapping](#6-suggestions-de-mapping)
7. [Extraction de données](#7-extraction-de-données)
8. [Sécurité et connexions](#8-sécurité-et-connexions)

---

## 1. Analyse qualité des données

L'analyse qualité s'inspire des métriques Achilles (OHDSI) et produit un profil complet de chaque domaine OMOP CDM.

### 1.1 Dashboard (vue transversale)

Pour chaque domaine clinique (Condition, Drug, Measurement, Procedure, Observation, Visit, Device, Death), une requête unique calcule :

| Métrique | Description | Méthode SQL |
|----------|-------------|-------------|
| `total_records` | Nombre total d'enregistrements | `COUNT(*)` |
| `distinct_persons` | Patients distincts | `COUNT(DISTINCT person_id)` |
| `pct_persons` | % de la population couverte | `distinct_persons / total_persons × 100` |
| `total_terms` | Termes sources distincts | `COUNT(DISTINCT source_value)` |
| `mapped_terms` | Termes mappés (concept_id ≠ 0) | `COUNT(DISTINCT CASE WHEN concept_id != 0 THEN source_value END)` |
| `pct_terms_mapped` | Taux de mapping (%) | `mapped_terms / total_terms × 100` |
| `sparkline` | Tendance mensuelle (12 mois) | `date_trunc('month', date_col)` + `COUNT(*)` |

### 1.2 Observation Period (6 sous-analyses)

Toutes les requêtes partagent un CTE commun `per` qui pré-calcule les dates min/max d'observation par patient :

```sql
per AS (
    SELECT person_id,
           MIN(observation_period_start_date) AS obs_start,
           MAX(observation_period_end_date) AS obs_end
    FROM observation_period
    GROUP BY person_id
)
```

#### 1.2.1 Âge à la première observation
- Histogramme de l'âge (entier, 0–120 ans)
- Reconstruction de la date de naissance : `MAKE_DATE(year_of_birth, COALESCE(month_of_birth, 7), COALESCE(day_of_birth, 1))`
- Fallback au 1er juillet si mois/jour absents

#### 1.2.2 Âge par genre (boxplot)
- Âge décimal : `(obs_start - birth_date) / 365.25`
- Quantiles : `PERCENTILE_CONT(0.1 / 0.25 / 0.5 / 0.75 / 0.9) WITHIN GROUP (ORDER BY age)`
- Stratifié par `gender_concept_id` avec résolution du nom via `concept`

#### 1.2.3 Durée d'observation (mois)
- Calcul : `DATE_PART('year', AGE(obs_end, obs_start)) × 12 + DATE_PART('month', AGE(...))`
- Plafonnement : valeurs > `cap_months` (défaut 120) regroupées dans un seul bucket
- Format histogramme : mois → nombre de patients

#### 1.2.4 Durée par genre (boxplot)
- Mêmes quantiles que 1.2.2, appliqués à la durée en mois
- Stratifié par genre

#### 1.2.5 Observation cumulative
- Fonction fenêtre cumulative (du plus long au plus court) :
  ```sql
  SUM(n) OVER (ORDER BY months DESC) AS n_ge
  ```
- Résultat : pour chaque seuil M, le % de patients avec ≥ M mois d'observation

#### 1.2.6 Observation continue par année
- `generate_series(min_year, max_year)` pour énumérer toutes les années
- Un patient est "continûment observé" une année Y si : `obs_start ≤ 1er janv Y` ET `obs_end ≥ 31 déc Y`

### 1.3 Domaines cliniques

Pour chaque domaine clinique (Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death, Specimen, Note, Payer_Plan_Period) :

| Analyse | Méthode |
|---------|---------|
| **Statistiques globales** | `COUNT(*)`, `COUNT(DISTINCT person_id)` |
| **Tendance mensuelle** | `date_trunc('month', date_col)` groupé par mois |
| **Distribution records/patient** | Sous-requête COUNT par patient → histogramme avec plafonnement |
| **Top N concepts** | GROUP BY concept_id, ORDER BY count DESC, LIMIT N |
| **Source values par concept** | Sous-requête `LATERAL` limitée à 10 source_values distincts par concept (évite les agrégations massives) |
| **Statistiques de mapping** | Scan unique : `COUNT(CASE WHEN concept_id != 0 ...)` pour termes et enregistrements |
| **Top termes non mappés** | `WHERE concept_id = 0 GROUP BY source_value ORDER BY count DESC LIMIT N` |

### 1.4 Démographie (Person)

- Distribution par genre, année de naissance, race, ethnicité
- Résolution des noms via LEFT JOIN sur la table `concept`
- Filtrage des années de naissance aberrantes (< 1850 ou > année courante)

---

## 2. Contrôles de conformité CDM

Score de conformité calculé sur ~24 vérifications réparties en 4 catégories.

### 2.1 Structure

| Vérification | Seuil |
|-------------|-------|
| Existence des 10 tables requises (person, observation_period, visit_occurrence, condition_occurrence, drug_exposure, measurement, procedure_occurrence, observation, concept, vocabulary) | Présente = pass, Absente = fail |

### 2.2 Complétude

| Vérification | Pass | Warning | Fail |
|-------------|------|---------|------|
| Patients sans observation_period | < 1% | 1–10% | ≥ 10% |
| Genre non mappé (concept_id = 0) | < 1% | 1–5% | ≥ 5% |
| Concepts non mappés (tables cliniques) | < 5% | 5–20% | ≥ 20% |

### 2.3 Conformance

| Vérification | Pass | Warning |
|-------------|------|---------|
| Patients avec observation_periods multiples | 0 | > 0 |
| Enregistrements référençant un visit_occurrence_id inexistant | 0 | < 100 → warning, ≥ 100 → fail |

### 2.4 Plausibilité

| Vérification | Pass | Warning/Fail |
|-------------|------|-------------|
| Années de naissance futures | 0 | > 0 → fail |
| Dates de fin d'observation futures | 0 | > 0 → warning |
| Dates cliniques futures | 0 | < 100 → warning, ≥ 100 → fail |

### 2.5 Score

```
Score = (nombre de checks "pass" / nombre total de checks) × 100
```

Les checks avec statut "warning" ne contribuent pas positivement au score.

### 2.6 Optimisation SQL

Les vérifications sont regroupées en requêtes uniques par table via la clause `COUNT(*) FILTER (WHERE ...)` de PostgreSQL, réduisant le nombre de scans.

---

## 3. Construction de cohortes

Le moteur de cohortes traduit une définition JSON en SQL PostgreSQL pur.

### 3.1 Structure des critères

```
Cohorte
├── Inclusion (groupe)
│   ├── Critères [...] avec opérateurs AND/OR entre eux
│   ├── Sous-groupes [...] récursifs
│   ├── sameVisit: true/false
│   └── Opérateur global: AND/OR
├── Exclusion (groupe, même structure)
└── Demographics (filtres âge/genre/race/ethnicité)
```

### 3.2 Traduction SQL

Chaque critère devient un CTE (Common Table Expression) produisant une liste de `person_id` :

```sql
WITH
cte_1 AS (SELECT person_id FROM condition_occurrence WHERE condition_concept_id IN (...)),
cte_2 AS (SELECT person_id FROM drug_exposure WHERE drug_concept_id IN (...)),
combined AS (
    SELECT person_id FROM cte_1
    INTERSECT              -- opérateur AND
    SELECT person_id FROM cte_2
)
SELECT DISTINCT person_id FROM combined
EXCEPT
SELECT person_id FROM exclusion_cte
```

### 3.3 Opérateurs logiques

| Opérateur | Niveau | Traduction SQL |
|-----------|--------|----------------|
| **AND** | entre critères | `INTERSECT` |
| **OR** | entre critères | `UNION` |
| **operatorWithNext** | par critère | Regroupe les critères OR consécutifs en UNION, puis INTERSECT entre groupes |
| **sameVisit** | groupe inclusion | JOIN sur `person_id AND visit_occurrence_id` au lieu de INTERSECT |

### 3.4 Filtres par critère

| Filtre | Description | SQL |
|--------|-------------|-----|
| **Concepts** | Liste de concept_ids standards | `concept_id IN (...)` |
| **Descendants** | Inclusion hiérarchique via concept_ancestor | `concept_id IN (SELECT descendant_concept_id FROM concept_ancestor WHERE ancestor_concept_id IN (...))` |
| **Source codes** | Codes sources directs | `source_value IN (...)` |
| **Valeurs** | Contrainte numérique (Measurement) | `value_as_number BETWEEN x AND y` |

### 3.5 Contraintes d'occurrence

| Type | Exemple | SQL |
|------|---------|-----|
| `at_least` | ≥ 3 occurrences | `HAVING COUNT(*) >= 3` |
| `exactly` | exactement 5 | `HAVING COUNT(*) = 5` |
| `at_most` | ≤ 2 | `HAVING COUNT(*) <= 2` |

**Occurrence fenêtrée** (ex: "≥ 3 fois en 30 jours") :

Utilise une fonction fenêtre glissante au lieu d'une sous-requête corrélée O(N²) :

```sql
SELECT person_id, event_date,
    COUNT(*) OVER (
        PARTITION BY person_id ORDER BY event_date
        RANGE BETWEEN CURRENT ROW AND INTERVAL '30 days' FOLLOWING
    ) AS cnt
FROM events
-- Puis : WHERE cnt >= 3
```

### 3.6 Contraintes temporelles

#### Fenêtre absolue
```json
{"type": "absolute_window", "date_from": "2020-01-01", "date_to": "2022-12-31"}
```
→ `WHERE event_date BETWEEN '2020-01-01' AND '2022-12-31'`

#### Relative à l'événement index
```json
{"type": "within_days", "relative_to": "index", "days_before": 30, "days_after": 365}
```
→ JOIN sur le CTE de l'événement index, restriction par intervalle de jours

#### Relative à un autre critère (algèbre d'Allen)

9 relations temporelles supportées entre intervalles d'événements :

| Relation | Signification |
|----------|--------------|
| `before` | A se termine avant le début de B |
| `after` | A commence après la fin de B |
| `overlaps` | A chevauche B (début A < fin B ET fin A > début B) |
| `contains` | A contient B (début A ≤ début B ET fin A ≥ fin B) |
| `during` | A est contenu dans B |
| `starts_before` | A commence avant B |
| `starts_after` | A commence après B |
| `ends_before` | A se termine avant B |
| `ends_after` | A se termine après B |

Les dates de fin sont spécifiques à chaque domaine (ex: `condition_end_date`, `drug_exposure_end_date`).

### 3.7 Attrition

Calcul pas à pas du nombre de patients restants après l'ajout de chaque critère :

1. Étape 0 : tous les patients de la table `person`
2. Pour chaque critère d'inclusion i : exécuter la cohorte avec les critères [1..i] → COUNT
3. Pour chaque critère d'exclusion j : exécuter avec inclusion complète + exclusions [1..j] → COUNT

Résultat : tableau d'attrition (label du critère, nombre de patients, delta).

### 3.8 Échantillonnage

- **Sample aléatoire** : `ORDER BY RANDOM() LIMIT N` avec données démographiques
- **Sample détaillé** : pour chaque patient, une sous-requête `LATERAL` récupère un enregistrement correspondant par critère (code source, concept, valeur)

---

## 4. Caractérisation de cohortes (Table 1)

Profil démographique et clinique complet de la cohorte.

### 4.1 Démographie

| Variable | Méthode |
|----------|---------|
| Âge | `EXTRACT(YEAR FROM CURRENT_DATE) - year_of_birth` → moyenne, écart-type, min, max, Q1, médiane, Q3 |
| Groupes d'âge | Buckets : 0–17, 18–29, 30–39, 40–49, 50–59, 60–69, 70–79, 80+ |
| Genre | Distribution par `gender_concept_id` |
| Race / Ethnicité | Distribution (si disponible dans le CDM) |

Quantiles calculés via `PERCENTILE_CONT() WITHIN GROUP`.

### 4.2 Prévalence par domaine

Pour chaque domaine clinique :
- % de la cohorte ayant au moins un enregistrement
- Top 25 concepts par nombre de patients (`n_persons`, `n_records`, `pct_persons`)

### 4.3 Statistiques de mesures

Pour les 25 mesures les plus fréquentes :
- Moyenne, écart-type, médiane, min, max de `value_as_number`
- Unité (via `MODE() WITHIN GROUP (ORDER BY unit_source_value)`)
- % de la cohorte concerné

### 4.4 Types de visites

Distribution des `visit_concept_id` (top 15) avec durée moyenne par type.

### 4.5 Mode visite (visit-level)

Quand la cohorte est construite avec `sameVisit=true` :
- Démographie : toujours au niveau patient
- Domaines cliniques : **restreints à la visite qualifiante** (JOIN sur `visit_occurrence_id`)

---

## 5. Comparaison de cohortes (SMD)

La différence standardisée des moyennes (Standardized Mean Difference) quantifie l'équilibre entre deux cohortes.

### 5.1 Formules

**Variables continues** (ex: âge moyen) :

```
SMD = (moyenne_A − moyenne_B) / √((σ_A² + σ_B²) / 2)
```

**Variables binaires** (ex: % femmes) :

```
SMD = (p_A − p_B) / √((p_A(1−p_A) + p_B(1−p_B)) / 2)
```

Où `p = proportion (0–1)`.

### 5.2 Variables comparées

| Catégorie | Variables |
|-----------|----------|
| Démographie | Âge (continu), genre (binaire par catégorie), race, ethnicité, groupes d'âge |
| Prévalence domaine | % avec données par domaine, % par concept (binaire) |
| Mesures | Moyenne/SD des mesures (continu), % concerné (binaire) |
| Visites | % par type de visite |
| Observation | Durée moyenne en jours |

### 5.3 Interprétation

| SMD | Interprétation |
|-----|---------------|
| < 0.1 | Différence négligeable |
| 0.1 – 0.2 | Petite différence |
| > 0.2 | Déséquilibre notable |

---

## 6. Suggestions de mapping

Le moteur de mapping propose des correspondances entre les termes sources (codes locaux) et les concepts standards OMOP, via 5 stratégies internes (+ SapBERT en pré-calcul externe) exécutées séquentiellement par ordre de confiance.

> **Note** : Le moteur détecte dynamiquement si la colonne `source_name` existe dans le CDM. Si absente, les stratégies basées sur le libellé (ingredient, fuzzy, keyword) sont limitées au `source_value`. Un tableau de `warnings` est retourné indiquant les limitations rencontrées.

### 6.1 SapBERT (pré-calculé, externe)

- **Source** : table `sapbert_mappings` dans la BDD applicative
- **Méthode** : embeddings de langage médical (modèle SapBERT) calculés hors-ligne
- **Principe** : similarité cosinus entre le vecteur du terme source et les vecteurs des concepts OMOP
- **Chargement** : résultats pré-calculés uploadés en CSV, récupérés à la demande par domaine et termes nécessaires
- **Confiance** : variable selon le score de similarité vectorielle

### 6.2 Exact Match (confiance 95%)

- **Méthode** : `concept_code = source_value`
- **Filtre** : `standard_concept = 'S'`, `invalid_reason IS NULL`
- **Priorisation** : concepts du même domaine en premier
- **Performance** : utilise l'index btree sur `concept_code`

### 6.3 Relationship Match (confiance 85%)

- **Méthode** : suit les relations `"Maps to"` dans `concept_relationship`
- **Flux** : `source_value` → match `concept_code` → traverse `concept_relationship` (relationship_id = 'Maps to') → concept standard cible
- **Usage typique** : codes non-standards (ICD-10, ICD-9) vers SNOMED

### 6.4 Ingredient / DCI Match (confiance 78–95%)

Stratégie spécialisée pour les **médicaments**, adaptée au contexte français.

#### Parsing du source_name français

Le parseur décompose un libellé comme `"HYDROXYZINE 25 MG CPR (ATARAX)"` en :

| Composant | Valeur extraite | Méthode |
|-----------|-----------------|---------|
| Principe actif (DCI) | `HYDROXYZINE` | Texte avant le dosage, nettoyé des formes galéniques |
| Dosage | `25 MG` | Regex : `(\d+[\.,]?\d*)\s*(MG|G|ML|MCG|µG|UI|...)` |
| Forme galénique | `Oral Tablet` | Détection de `CPR` → mapping vers RxNorm keywords |
| Marque | `ATARAX` | Extraction du contenu entre parenthèses |

#### Dictionnaire FR→EN (110+ DCI)

Exemples de corrections appliquées :

| Français | Anglais |
|----------|---------|
| PARACETAMOL | ACETAMINOPHEN |
| AMOXICILLINE | AMOXICILLIN |
| INSULINE GLARGINE | INSULIN GLARGINE |
| NORADRENALINE | NOREPINEPHRINE |
| SALBUTAMOL | ALBUTEROL |
| ACIDE ACETYLSALICYLIQUE | ASPIRIN |

Règle générique : les DCI en `-INE` perdent le `-E` final en anglais.

#### Formes galéniques FR → RxNorm

| Code FR | Keywords RxNorm |
|---------|----------------|
| CPR, COMP, ENROB | Oral Tablet |
| GEL, GELULE, CAPS | Oral Capsule |
| LP | Extended Release |
| INJ, AMP, PERF | Injectable, Injection |
| SERINGUE | Prefilled Syringe |
| STYLO | Pen Injector |
| POM, CREME | Topical, Ointment/Cream |
| PATCH | Transdermal |
| COLLYRE | Ophthalmic |
| SPRAY | Nasal Spray, Metered Dose Inhaler |
| SUPPO | Rectal Suppository |

#### Recherche dans le vocabulaire

1. Recherche `concept_name ILIKE '%ingredient_EN%dosage%'` (avec dosage)
2. Recherche `concept_name ILIKE '%ingredient_EN%'` (sans dosage)
3. Recherche dans `concept_synonym` (synonymes français/multilingues)
4. Priorisation par : domaine → marque → forme galénique → longueur du nom

#### Bonus de confiance

- Base : 78% (ingrédient seul) ou 85% (dosage + ingrédient)
- +5% si la marque correspond
- +5% si la forme galénique correspond
- Plafond : 95%

### 6.5 Fuzzy / Trigram (confiance ≤ 75%)

- **Méthode primaire** : extension PostgreSQL `pg_trgm`, opérateur `%%` et fonction `similarity()`
- **Score** : `similarity × 80`, plafonné à 75%
- **Fallback** : si `pg_trgm` non installé, recherche `ILIKE '%terme%'` sur `concept_name` + `concept_synonym` (confiance 50%)

### 6.6 Keyword Search (confiance 50–60%)

- **Extraction** : mots significatifs du `source_name` (≥ 4 caractères, hors stop-words anglais)
- **Stratégie A** (précise, 60%) : AND sur tous les keywords : `concept_name ILIKE '%kw1%' AND ILIKE '%kw2%'`
- **Stratégie B** (large, 50%) : keyword le plus long seul, si résultats insuffisants
- **Usage** : termes composés longs où le fuzzy échoue

### 6.7 Contextual Match (confiance 40%)

- **Méthode** : analyse des mappings existants dans `source_to_concept_map` pour des codes au préfixe similaire
- **Exemple** : si `I10.1` est mappé à "Essential hypertension", propose des concepts proches pour `I10.9`
- **Dernier recours** : confiance la plus faible

### 6.8 Logique d'orchestration

1. Les suggestions SapBERT sont ajoutées en premier (si elles existent dans la BDD applicative)
2. Les stratégies 1→5 (exact, relationship, ingredient, fuzzy+keyword, contextual) s'exécutent séquentiellement
3. **Court-circuit** : si les stratégies accumulées produisent ≥ `max_suggestions` résultats à ≥ 75% de confiance, les stratégies suivantes sont ignorées
4. Dédoublonnage par `concept_id` (un concept n'apparaît qu'une fois)
5. Tri final par confiance décroissante, retour des top N

### 6.9 Workflow per-user et validation par consensus

#### Principe

Le mapping dans OPAL suit un modèle de **double validation** : chaque utilisateur travaille indépendamment sur les suggestions, et un mapping n'est considéré valide que lorsque 2+ utilisateurs convergent sur la même correspondance.

#### Cycle de vie d'une décision

1. **Pending** : un seul utilisateur a approuvé le mapping (source_value → target_concept_id). Le terme reste visible dans les suggestions des autres utilisateurs.
2. **Consensus** : 2+ utilisateurs ont approuvé le même mapping. Le mapping est exportable via apply/STCM CSV.
3. **Conflit** : des utilisateurs ont mappé le même terme vers des cibles différentes. Un indicateur visuel (triangle jaune) signale le désaccord.
4. **Rejeté** : un utilisateur a rejeté un mapping. Le terme redevient disponible dans ses suggestions. Les décisions rejetées sont exclues du calcul de consensus/conflit.

#### Filtrage des suggestions

Seuls les termes `approved` ou `modified` par l'utilisateur courant sont exclus de ses suggestions. Les termes `rejected` restent disponibles pour permettre un re-mapping vers une autre cible.

#### Critère de consensus pour l'export

L'export STCM et la prévisualisation (preview) ne retournent que les mappings ayant :
- `action` IN (`approved`, `modified`)
- `target_concept_id` IS NOT NULL
- `COUNT(DISTINCT user) >= 2` pour le même couple (source_value, target_concept_id)

Un représentant unique (la décision la plus récente) est retourné par groupe consensus.

---

## 7. Extraction de données

### 7.1 Tables extractibles

10 tables OMOP standard, classées en deux catégories :

| Catégorie | Tables |
|-----------|--------|
| **Niveau patient** (pas de visite) | `person`, `death`, `observation_period` |
| **Niveau visite** (cliniques) | `visit_occurrence`, `condition_occurrence`, `drug_exposure`, `measurement`, `observation`, `procedure_occurrence`, `device_exposure` |

### 7.2 Construction du dataset

Le SQL d'extraction produit un dataset plat avec **une ligne par (patient, visite)**.

#### Étapes :

1. **CTE cohort** : résultat du SQL de cohorte (person_id, [visit_occurrence_id])
2. **CTE base** :
   - Mode `same_visit_only=true` : utilise les paires `(person_id, visit_occurrence_id)` de la cohorte
   - Mode `same_visit_only=false` : JOIN sur toutes les visites du patient via `visit_occurrence`
3. **Pré-agrégation des tables cliniques** : chaque table clinique est agrégée par `(person_id, visit_occurrence_id)` :
   - Colonnes → `STRING_AGG(DISTINCT valeur::text, ', ')` (valeurs distinctes concaténées)
   - Évite l'explosion cartésienne (3 conditions × 2 médicaments = 6 lignes → 1 seule ligne)
4. **Jointures finales** :
   - Tables patient/décès : LEFT JOIN sur `person_id`
   - Tables visite : LEFT JOIN sur `visit_occurrence_id`
   - Tables cliniques pré-agrégées : LEFT JOIN sur `(person_id, visit_occurrence_id)`

#### Nommage des colonnes

Format : `{table}__{colonne}` (ex: `condition_occurrence__condition_concept_id`, `person__gender_concept_id`)

### 7.3 Exécution

- **Background** : l'extraction tourne dans un thread séparé avec polling de progression
- **Named cursor** avec `itersize=2000` pour le streaming mémoire
- **3 étapes** : COUNT total → preview (N premières lignes) → CSV complet
- **Dates** : sérialisées en ISO 8601 (`isoformat()`)

---

## 8. Sécurité et connexions

### 8.1 Connexions CDM

- **Lecture seule** : toutes les requêtes vers les CDM externes sont en lecture seule (pas de CREATE, INSERT, UPDATE, DELETE)
- **Pool de connexions** : `ThreadedConnectionPool` psycopg2 par CDM (min=2, max=20)
- **Éviction** : pools inutilisés depuis 30 minutes automatiquement fermés
- **Invalidation** : pool fermé lors de la modification ou suppression d'un CDM

### 8.2 Protection SQL

- Tous les identifiants SQL (schéma, table, colonne) interpolés dans les requêtes sont validés par `safe_identifier()` (regex `^[A-Za-z_][A-Za-z0-9_]*$`)
- Les valeurs utilisateur passent par des paramètres préparés (`%s` / `%(name)s`)

### 8.3 Chiffrement

- Mots de passe CDM chiffrés au repos via Fernet (AES-128-CBC) avec la clé `SECRET_KEY`
- Rejet au démarrage si `SECRET_KEY` est absente ou trop faible

### 8.4 Authentification

- Keycloak (optionnel) : middleware valide le token Bearer via l'endpoint userinfo
- 4 rôles : `admin`, `omop-dim`, `chercheur`, `medecin`
- Contrôle d'accès par route selon le rôle

---

*Document généré pour OPAL v2.0.0 — Mars 2026*
