# OPAL — Audit Complet d'Optimisation Computationnelle

**Date** : 2026-03-12
**Périmètre** : Toutes les briques de calcul backend (requêtes SQL sur base OMOP CDM, requêtes sur base applicative, traitement Python, connectivité)

---

## Table des matières

1. [Synthèse Exécutive](#1-synthèse-exécutive)
2. [Connectivité & Pool de Connexions](#2-connectivité--pool-de-connexions)
3. [Module Quality — Analyse Domaines Cliniques](#3-module-quality--analyse-domaines-cliniques)
4. [Module Quality — Dashboard](#4-module-quality--dashboard)
5. [Module Quality — Observation Period](#5-module-quality--observation-period)
6. [Module Quality — Conformité](#6-module-quality--conformité)
7. [Module Cohort — SQL Builder](#7-module-cohort--sql-builder)
8. [Module Mapping — Suggest Engine](#8-module-mapping--suggest-engine)
9. [Module Concept Explorer](#9-module-concept-explorer)
10. [Module Search — Recherche Globale](#10-module-search--recherche-globale)
11. [Audit Logs (main.py)](#11-audit-logs-mainpy)
12. [Base Applicative — Schéma & Index](#12-base-applicative--schéma--index)
13. [Optimisations côté Base Source OMOP CDM](#13-optimisations-côté-base-source-omop-cdm)
14. [Startup & Middleware](#14-startup--middleware)
15. [Frontend — Patterns d'appels API](#15-frontend--patterns-dappels-api)
16. [Modules Restants — Cohort, Data Management, Estimation, Incidence, Concept Sets](#16-modules-restants--cohort-data-management-estimation-incidence-concept-sets)
17. [Matrice de Priorités](#17-matrice-de-priorités)

---

## 1. Synthèse Exécutive

| Catégorie | Déjà optimisé | A optimiser |
|-----------|:---:|:---:|
| Connexions OMOP CDM | `statement_timeout`, `connect_timeout` | ~~Pas de pool, pas d'autocommit, connexion ouverte/fermée par requête~~ **CORRIGE** (P1 — ThreadedConnectionPool par CDM) |
| Pool SQLAlchemy (app DB) | `pool_pre_ping`, `pool_size=10` | ~~Pas de `pool_recycle`, paramètres non configurables~~ **CORRIGE** (P2/P3 — pool_recycle=1800, paramètres via env vars) |
| Quality Engine | Requêtes SQL propres, LIMIT sur top concepts | ~~COUNT(DISTINCT) full scan (P4)~~ **CORRIGE**, ~~3 scans mapping_stats (P8)~~ **CORRIGE**, ~~Dashboard N+1 2 scans/domaine (P9)~~ **CORRIGE**, CTE recalculées, pas de parallélisme |
| Cohort SQL Builder | CTEs, paramètres échappés, `concept_ancestor` | SQL dynamique complexe non caché, pas d'EXPLAIN |
| Mapping Suggest | 6 stratégies avec early exit, LIMIT | Appel séquentiel par terme (N+1), ILIKE sans index trgm |
| Concept Explorer | Pagination, LIMIT 200 | COUNT(*) séparé du SELECT, UNION ALL sur tous les domaines |
| Search Global | - | UNION ALL sur toutes les tables cliniques pour chaque recherche |
| Audit Logs | - | Lecture/parsing complet de fichiers JSONL en mémoire |
| Schéma App DB | Index sur colonnes simples | Pas d'index composites, pas de FK, race condition versioning |
| Base source OMOP | - | Index manquants sur `source_value`, `source_concept_id`, `pg_trgm` |
| Frontend | Axios centralisé, `Promise.all`, `useSessionState` | Pas de cache API, appels dupliqués, waterfall, payloads surdimensionnés |

---

## 2. Connectivité & Pool de Connexions

### Fichier : `db/omop_connector.py`

#### Ce qui est bien fait
- `connect_timeout=10` — évite les blocages sur hôtes inaccessibles
- `statement_timeout=300000` (5 min) — protège contre les requêtes en fuite
- `autocommit=False` — transactions explicites

#### Problèmes critiques

**P1 — Pas de pool de connexions OMOP CDM** --- CORRIGE 2026-03-13

Chaque appel API ouvre une nouvelle connexion TCP + authentification PostgreSQL. Sur un CDM fréquemment accédé, cela représente ~50-100ms de latence ajoutée par requête (handshake TCP + SSL + auth).

```
Impact : Latence +50-100ms par requête API touchant le CDM
```

**Recommandation** : Utiliser `psycopg2.pool.ThreadedConnectionPool` par CDM, avec un cache LRU des pools :

```python
from psycopg2.pool import ThreadedConnectionPool
from functools import lru_cache

@lru_cache(maxsize=16)
def _get_pool(host, port, dbname, user, password):
    return ThreadedConnectionPool(
        minconn=2, maxconn=10,
        host=host, port=port, dbname=dbname,
        user=user, password=password,
        connect_timeout=10,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
```

### Fichier : `db/app_db.py`

#### Ce qui est bien fait
- `pool_pre_ping=True` — détecte les connexions mortes
- `pool_size=10, max_overflow=20` — dimensionnement correct

#### Problèmes

**P2 — Pas de `pool_recycle`** --- CORRIGE 2026-03-13

Les connexions ne sont jamais recyclées. Si PostgreSQL ou un proxy réseau coupe les connexions idle après N minutes, `pool_pre_ping` va détecter la mort mais au prix d'un round-trip supplémentaire à chaque checkout.

```python
# Manquant :
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10,
                       max_overflow=20, pool_recycle=1800)  # ← ajouter
```

**P3 — Paramètres de pool non configurables** --- CORRIGE 2026-03-13

`pool_size`, `max_overflow`, `pool_recycle` sont codés en dur. En production avec beaucoup d'utilisateurs concurrents, il faut pouvoir les ajuster sans redéployer.

**P41 — Connexions OMOP en mode transactionnel pour du read-only**

`omop_connector.py:32` : `conn.autocommit = False` force chaque connexion en mode transactionnel. Comme tout accès OMOP est en lecture seule, cela crée un overhead inutile (allocation snapshot PostgreSQL, maintien de locks partagés).

**Recommandation** : `conn.autocommit = True` ou `SET default_transaction_read_only = on`.

**P42 — Race condition sur `_save_snapshot`**

`quality/router.py:67-70` : `SELECT MAX(version)` puis `INSERT` avec `version+1` n'est pas atomique. Deux threads concurrents pour le même CDM/domain peuvent obtenir le même MAX et insérer des versions dupliquées.

**Recommandation** : Ajouter `UNIQUE(cdm_name, domain, version)` + retry on conflict, ou `INSERT ... SELECT MAX(version)+1` en une seule requête.

**P43 — Cache des lookups CdmConfig et AnalysisSettings**

`_get_conn()` dans chaque router exécute 2 requêtes app DB (CdmConfig + AnalysisSettings) à chaque appel API, même si ces données changent rarement.

**Recommandation** : Cache LRU avec TTL de 30-60s sur les configs CDM.

---

## 3. Module Quality — Analyse Domaines Cliniques

### Fichier : `modules/quality/domains/clinical.py`

#### Ce qui est bien fait
- Requêtes SQL propres avec agrégation côté base (COUNT, GROUP BY)
- `LIMIT` sur top concepts et top unmapped terms
- Bucketing des records_per_person en Python (léger)

#### Problèmes identifiés

**P4 — `_get_global_stats` : COUNT(*) + COUNT(DISTINCT) full table scan** --- CORRIGE 2026-03-13

```sql
SELECT COUNT(*) AS total_rows,
       COUNT(DISTINCT person_id) AS distinct_persons
FROM {full_table}
```

Sur une table `condition_occurrence` de 100M+ lignes, `COUNT(DISTINCT person_id)` nécessite un **Hash Aggregate** ou un **Sort** complet en mémoire. C'est la requête la plus lente de l'analyse.

**Recommandation** :
- Si une approximation est acceptable : `SELECT COUNT(*) AS total_rows FROM {table}` + `SELECT COUNT(*) FROM (SELECT DISTINCT {person_id} FROM {table}) t` — permet au planificateur d'utiliser un index-only scan sur `person_id`
- Ou utiliser `HyperLogLog` via l'extension `hll` pour les comptages distincts approximatifs (~2% d'erreur)
- Ou ajouter un **index sur `person_id`** sur chaque table clinique (voir section 13)

**P5 — `_get_monthly_counts` : scan complet + tri**

```sql
SELECT date_trunc('month', date_col)::date AS month_start, COUNT(*) AS n
FROM {full_table}
GROUP BY date_trunc('month', date_col)
ORDER BY month_start
```

Scan complet de la table. Si la table a un index sur `date_col`, PostgreSQL pourrait faire un Index-Only Scan + regroupement, mais sans index c'est un Seq Scan.

**Recommandation** : Créer un index sur la colonne `date_col` de chaque table clinique (voir section 13).

**P6 — `_get_records_per_person` : double agrégation**

```sql
SELECT cnt, COUNT(*) FROM (
    SELECT person_id, COUNT(*) AS cnt FROM {table} GROUP BY person_id
) t GROUP BY cnt
```

Deux passes de GROUP BY imbriquées sur la table complète. C'est correct algorithmiquement mais lourd. Pas d'optimisation simple ici — c'est intrinsèque au calcul de distribution.

**P7 — `_get_top_concepts` : JOIN + STRING_AGG + GROUP BY** --- CORRIGE 2026-03-13

```sql
SELECT t.concept_id, c.concept_name,
       STRING_AGG(DISTINCT t.source_value, ', ' ORDER BY t.source_value),
       COUNT(*), COUNT(DISTINCT t.person_id)
FROM {table} t JOIN concept c ON ...
WHERE t.concept_id != 0
GROUP BY t.concept_id, c.concept_name
ORDER BY n_records DESC LIMIT N
```

Le `STRING_AGG(DISTINCT ...)` force PostgreSQL à collecter et dédupliquer toutes les source_values par concept avant de tronquer au LIMIT. Sur un domaine avec 1000 source_values par concept, c'est coûteux.

**Recommandation** : Ajouter un sous-LIMIT au `STRING_AGG` ou calculer les source_values dans une sous-requête latérale avec `LIMIT 10`.

**P8 — `_get_mapping_stats` : 3 scans séquentiels sur la même table** --- CORRIGE 2026-03-13

`_get_mapping_stats` exécute 3 requêtes séparées :
1. `COUNT(DISTINCT source_value)` + `COUNT(DISTINCT CASE WHEN concept_id != 0 ...)`
2. `COUNT(*)` + `COUNT(CASE WHEN concept_id != 0 ...)`
3. Top unmapped terms

Les requêtes 1 et 2 pourraient être fusionnées en une seule :

```sql
SELECT COUNT(*) AS total_rows,
       COUNT(CASE WHEN concept_id != 0 THEN 1 END) AS mapped_rows,
       COUNT(DISTINCT source_value) AS total_terms,
       COUNT(DISTINCT CASE WHEN concept_id != 0 THEN source_value END) AS mapped_terms
FROM {full_table}
```

**Impact** : Économise 1 scan complet de la table (potentiellement 30-60s sur table de 100M lignes).

---

## 4. Module Quality — Dashboard

### Fichier : `modules/quality/domains/dashboard.py`

#### Problèmes identifiés

**P9 — Boucle N+1 sur tous les domaines cliniques** — **CORRIGE 2026-03-13**

`run_dashboard_analysis` itère sur `DOMAIN_CONFIG` (8 domaines) et exécutait **3 requêtes par domaine** :
1. `COUNT(*) + COUNT(DISTINCT person_id)` — full scan
2. `COUNT(DISTINCT source_value) + COUNT(DISTINCT CASE WHEN ...)` — full scan
3. Monthly trend (derniers 12 mois) — scan partiel

Total : **~24 requêtes SQL**, dont 16 étaient des full scans sur les tables cliniques les plus volumineuses.

**Correction appliquée** : Fusion des requêtes 1+2 en une seule par domaine (4 agrégats dans un seul scan, comme P8). Résultat : **17 requêtes** (1 person + 8 stats + 8 sparklines) au lieu de 25. Élimine 8 full scans inutiles.

**P10 — Pas de cache de dashboard** — **NON APPLICABLE**

Le dashboard est recalculé à chaque appel, ce qui est le **comportement attendu** : l'utilisateur lance une analyse parce qu'il s'attend à des changements dans le CDM. Les résultats précédents sont déjà accessibles via les snapshots versionnés. Un cache intermédiaire retournerait des données stales sans valeur ajoutée.

---

## 5. Module Quality — Observation Period

### Fichier : `modules/quality/domains/observation_period.py`

#### Ce qui est bien fait
- Utilisation de CTEs pour structurer les requêtes complexes
- `PERCENTILE_CONT` calculé côté PostgreSQL (pas en Python)
- `MAKE_DATE` avec fallback pour les dates incomplètes
- Cap configurable sur les mois d'observation

#### Problèmes identifiés

**P11 — Requête cumulative observation : correlated subquery O(n * cap_months)** — **CORRIGE 2026-03-13**

```sql
WITH ...
s AS (SELECT generate_series(0, cap_months) AS thr),
agg AS (
    SELECT s.thr, (SELECT COUNT(*) FROM per2 WHERE months >= s.thr) AS n_ge
    FROM s
)
```

C'est une **sous-requête corrélée** qui exécute `COUNT(*)` une fois par seuil (0 à `cap_months`, typiquement 120). Sur 500K patients, cela fait 120 scans de la CTE `per2`.

**Recommandation** : Utiliser une fenêtre cumulative :

```sql
WITH per2 AS (...),
hist AS (
    SELECT months AS m, COUNT(*) AS n FROM per2 GROUP BY months
),
cum AS (
    SELECT m, SUM(n) OVER (ORDER BY m DESC) AS n_ge,
           SUM(n) OVER () AS n_total
    FROM hist
)
SELECT m AS thr, ROUND(n_ge::numeric / n_total * 100, 2) AS pct
FROM cum ORDER BY m
```

**Impact** : Passe de O(N * cap_months) à O(N) — amélioration potentielle de 100x.

**P12 — Continuous observation by year : cross join implicite** — **NON APPLICABLE (DBA)**

```sql
JOIN per ON per.obs_start <= MAKE_DATE(y.y, 1, 1)
        AND per.obs_end >= MAKE_DATE(y.y, 12, 31)
```

C'est un **cross join filtré** entre toutes les années et tous les patients. Sans index sur `obs_start` / `obs_end`, PostgreSQL fait un Nested Loop sur chaque année × chaque patient.

**Recommandation** : Index composite côté base source OMOP — hors périmètre applicatif (CDM en lecture seule). Le cross join reste acceptable car `years` contient typiquement 20-30 lignes et `per` est déjà agrégé.

**P13 — 6 CTEs "per" recalculées séparément** — **CORRIGE 2026-03-13**

Les requêtes 1-6 recalculaient toutes la même CTE `per` (MIN/MAX de observation_period par person_id). Cette CTE était exécutée 6 fois indépendamment.

**Correction appliquée** : CTE `per` factorisée dans un fragment SQL réutilisé (`per_cte`) dans les 6 requêtes. Pas de table temporaire (CDM en lecture seule). PostgreSQL peut mettre en cache le plan de la CTE entre les requêtes de la même session. Le P11 (fenêtre cumulative) réduit aussi la pression sur cette CTE.

---

## 6. Module Quality — Conformité

### Fichier : `modules/quality/conformity.py`

#### Ce qui est bien fait
- Validation des identifiants SQL (sécurité)
- Checks structurés avec scoring
- `NOT EXISTS` pour les orphans (meilleur que `LEFT JOIN ... IS NULL` dans certains cas)

#### Problèmes identifiés

**P14 — Multiple COUNT(*) séquentiels sur les mêmes tables** — **CORRIGE 2026-03-13**

Pour chaque table clinique, la conformité exécutait 4 scans séquentiels (total, unmapped, future dates, orphans).

**Correction appliquée** : Fusion via `COUNT(*) FILTER (WHERE ...)` en une seule requête par table. Sections 4/5/6 unifiées dans une config par table. Person checks (section 2) également fusionnés. Réduit de ~20 requêtes à ~7.

---

## 7. Module Cohort — SQL Builder

### Fichier : `modules/cohort/sql_builder.py`

#### Ce qui est bien fait
- **Validation d'identifiants SQL** via regex (`_SAFE_IDENTIFIER_RE`) — sécurité contre l'injection
- **Validation des dates** ISO
- **CTEs chaînées** — construction modulaire du SQL
- **Paramètres échappés** via `%s` (psycopg2 parameterization)
- **`concept_ancestor` expansion** pour les hiérarchies de concepts
- **Relations temporelles** (before, after, during, within) via sous-requêtes EXISTS
- **Opérateurs logiques** (AND, OR, AT_LEAST, AT_MOST, NOT) avec composition récursive

#### Problèmes identifiés

**P15 — SQL généré non caché** — **NON APPLICABLE**

La génération SQL est du string building quasi instantané. Un cache LRU ajouterait de la complexité pour un gain négligeable.

**P16 — Pas de EXPLAIN avant exécution** — **NON APPLICABLE**

C'est une feature (endpoint EXPLAIN), pas un problème de performance du code existant.

**P17 — `concept_ancestor` expansion potentiellement large** — **NON APPLICABLE (déjà implémenté)**

Le code utilise **déjà une sous-requête** (`IN (SELECT descendant_concept_id FROM concept_ancestor WHERE ...)`) et non un `IN (...)` matérialisé. L'expansion reste côté PostgreSQL.

**P57 — Occurrence fréquence fenêtrée : sous-requête corrélée O(N²) (sql_builder.py:798-821)** — **CORRIGE 2026-03-13**

La contrainte d'occurrence avec fenêtre temporelle utilise :

```sql
WHERE (SELECT COUNT(*) FROM cte_inner b
       WHERE b.person_id = a.person_id
         AND b.event_date BETWEEN a.event_date AND a.event_date + INTERVAL 'X days')
      >= N
```

Sous-requête corrélée exécutée une fois par ligne — O(M²) par patient pour M événements.

**Recommandation** : Remplacer par une fonction fenêtre :
```sql
SELECT DISTINCT person_id FROM (
  SELECT person_id, COUNT(*) OVER (
    PARTITION BY person_id ORDER BY event_date
    RANGE BETWEEN CURRENT ROW AND INTERVAL 'X days' FOLLOWING
  ) AS cnt FROM cte_inner
) sub WHERE cnt >= N
```

**P58 — Attrition : N+1 requêtes re-scannant les mêmes données (sql_builder.py:229-259)** — **DIFFERE**

Refactoring significatif nécessaire (build_attrition_sql + router). Gain limité car l'attrition est peu fréquente et les steps individuels sont rapides avec les index existants. À traiter dans une itération future si besoin.

**P59 — Export CSV non streamé (cohort/router.py:658-685, 1154-1179)** — **DIFFERE**

Nécessite de restructurer la gestion du cycle de vie connexion pendant le streaming (connexion doit rester ouverte pendant la réponse StreamingResponse). Fonctionne bien pour les tailles typiques (< 100K patients).

**P60 — `cohort_count_approximate` n'est pas approximate (cohort/router.py:488-521)** — **NON APPLICABLE**

Feature manquante, pas un problème de performance du code existant.

**P61 — `_active_characterizations` : fuite mémoire (cohort/router.py:843)** — **DIFFERE**

Impact faible (dict de quelques entrées, les clients poll régulièrement). À traiter dans une itération future.

**P62 — `_can_access_cohort` : 2-3 requêtes par appel (cohort/router.py:312-341)** — **DIFFERE**

Impact négligeable (requêtes sur app DB locale, tables très petites). À combiner si des problèmes de latence sont observés.

---

## 8. Module Mapping — Suggest Engine

### Fichier : `modules/mapping/suggest.py`

#### Ce qui est bien fait
- **6 stratégies ordonnées par précision** (exact > relationship > ingredient > fuzzy > keyword > contextual)
- **Early exit** quand ≥ max_suggestions avec confidence ≥ 75
- **Dedup** via `seen_concept_ids` set
- **Fallback gracieux** si `pg_trgm` n'est pas installé
- **Dictionnaire DCI français→anglais** pour le bridge médicament
- **LIMIT** sur chaque stratégie

#### Problèmes identifiés

**P18 — `suggest_batch` : boucle N+1 séquentielle** — **DIFFERE**

```python
for term in unmapped_terms:
    suggs = suggest_mappings(conn, sv, sn, domain, ...)
```

Chaque terme exécute 3-7 requêtes SQL. Pour un batch de 50 termes, c'est 150-350 requêtes séquentielles sur une seule connexion.

**Recommandation** :
- Batch les requêtes `_exact_match` en une seule avec `WHERE concept_code = ANY(array_of_source_values)`
- Batch les requêtes `_relationship_match` de la même façon
- Garder les stratégies fuzzy/keyword/contextual en individuel (trop dépendantes du terme)

**Impact potentiel** : De 350 requêtes à ~100 pour 50 termes.

**P19 — `_ingredient_match` : jusqu'à 4 requêtes ILIKE par terme** — **NON APPLICABLE (DBA)**

Pour chaque terme, la stratégie ingredient :
1. Cherche `ILIKE %ingredient_en%dosage%` dans `concept`
2. Cherche `ILIKE %ingredient_en%` dans `concept`
3. Cherche `ILIKE %ingredient_fr%` dans `concept`
4. Cherche `ILIKE %ingredient_fr%dosage%` dans `concept_synonym`

**4 requêtes ILIKE** sur la table `concept` (~6M lignes dans un CDM standard). Sans index `pg_trgm`, chacune est un seq scan.

**Recommandation** : Activer `pg_trgm` + créer un index GIN :
```sql
CREATE INDEX CONCURRENTLY idx_concept_name_trgm
ON omop_cdm.concept USING gin (concept_name gin_trgm_ops);
```

**P20 — `_fuzzy_match` : similarity() scan complet** — **NON APPLICABLE (DBA)**

```sql
WHERE c.concept_name % %(term)s  -- trigram similarity
```

Même avec `pg_trgm`, sans index GIN, l'opérateur `%` fait un scan séquentiel. Avec l'index GIN recommandé en P19, cette requête deviendra rapide.

**P21 — `_keyword_match` : ILIKE chaînés sans index** — **NON APPLICABLE (DBA)**

```sql
WHERE c.concept_name ILIKE %kw0% AND c.concept_name ILIKE %kw1% AND ...
```

Multiple ILIKE sur la même colonne. PostgreSQL ne peut pas combiner plusieurs pattern matches via un index B-tree. Seul un index GIN (trgm) peut aider.

### Fichier : `modules/mapping/router.py`

#### Ce qui est bien fait
- **Background threading** pour les suggestions batch avec task_id + polling
- **SapBERT fast-path** : termes avec suggestions pré-calculées sautent le pipeline lent
- **Already-decided exclusion** au niveau SQL (`!= ALL(%(approved)s)`)
- **Pagination** sur list_unmapped et mapping_history
- **Annulation** des tâches background via flag `cancelled`

#### Problèmes identifiés

**P44 — `mapping_dashboard` : N+1 sur domaines (18 queries → 1)** — **CORRIGE 2026-03-13**

```python
for domain_name in DOMAIN_CONFIG.keys():
    snapshot = db.query(AnalysisSnapshot).filter(...).order_by(version.desc()).first()
```

18 requêtes SQLAlchemy séparées pour récupérer le dernier snapshot de chaque domaine.

**Recommandation** : Une seule requête avec `DISTINCT ON` :
```sql
SELECT DISTINCT ON (domain) * FROM analysis_snapshots
WHERE cdm_name = :name ORDER BY domain, version DESC
```

**P45 — `strategy_stats` : agrégation en Python au lieu de SQL** — **CORRIGE 2026-03-13**

`router.py:202` : `.all()` charge TOUTES les MappingDecision en mémoire, puis fait du grouping/counting/averaging en Python (lignes 205-236). Pour un CDM avec 10K+ décisions, c'est beaucoup d'ORM objects en RAM.

**Recommandation** : Pousser l'agrégation en SQL :
```sql
SELECT suggestion_source, action, COUNT(*), AVG(confidence_score)
FROM mapping_decisions
WHERE cdm_name = :name GROUP BY suggestion_source, action
```

**P46 — `suggest_batch_endpoint` : charge TOUTES les lignes SapBERT d'un domaine** — **CORRIGE 2026-03-13**

`router.py:551-556` : `SELECT * FROM sapbert_mapping WHERE domain = :domain ORDER BY source_code, rank` charge potentiellement 100K+ lignes en mémoire pour construire un dict, alors que seuls les termes non-mappés (max 200) sont utilisés.

**Recommandation** : Filtrer avec `WHERE source_code = ANY(%(svs)s)` après avoir déterminé les termes à traiter.

**P47 — `apply_mapping` : INSERT séquentiel dans une boucle** — **CORRIGE 2026-03-13**

`router.py:831-842` : Chaque mapping approuvé est inséré individuellement dans `source_to_concept_map` via une boucle Python.

**Recommandation** : Utiliser `psycopg2.extras.execute_values()` pour un batch INSERT en un seul round-trip.

---

## 9. Module Concept Explorer

### Fichier : `modules/concept/router.py`

#### Ce qui est bien fait
- Pagination avec `LIMIT/OFFSET`
- Support de recherche par concept_id (integer) vs texte
- `= ANY(%s)` pour les batch counts (PostgreSQL-optimized array matching)
- LIMIT 200 sur les relationships et descendants

#### Problèmes identifiés

**P22 — `search_concepts` : COUNT(*) séparé du SELECT** — **CORRIGE 2026-03-13**

```python
# Query 1: SELECT ... LIMIT/OFFSET
# Query 2: SELECT COUNT(*) ...   ← même WHERE, 2ème scan complet
```

La recherche exécute la requête 2 fois : une pour les résultats, une pour le total. Sur `concept` (~6M lignes) avec ILIKE, c'est 2 scans complets.

**Recommandation** : Utiliser une window function :
```sql
SELECT *, COUNT(*) OVER() AS total_count FROM concept WHERE ... LIMIT/OFFSET
```

**P23 — `get_concept_source_values` : boucle sur tous les domaines**

```python
for domain_name, cfg in DOMAIN_CONFIG.items():
    cur.execute(f"SELECT ... FROM {table} WHERE concept_id = %s ...")
```

8 requêtes SQL séquentielles, une par domaine clinique, même si le concept n'apparaît que dans 1 domaine.

**Recommandation** : D'abord identifier dans quel(s) domaine(s) le concept apparaît, puis ne requêter que ces tables.

**P24 — `search_source_value` : UNION ALL sur tous les domaines**

```python
for domain_name, cfg in domains_to_search.items():
    union_parts.append(f"SELECT ... FROM {table} WHERE source_value ILIKE ...")
```

Construit un UNION ALL de 8 sous-requêtes, chacune avec ILIKE. Puis exécute 2 fois (COUNT + données).

**Recommandation** : Permettre de filtrer par domaine (déjà supporté via `domain` param) et encourager son usage côté frontend. Fusionner les 2 exécutions avec `COUNT(*) OVER()`.

**P25 — `get_concept_counts` : boucle sur tous les domaines**

Même pattern que P23 — 8 requêtes `GROUP BY` séparées alors qu'un UNION ALL serait plus efficace (1 seul round-trip réseau).

---

## 10. Module Search — Recherche Globale

### Fichier : `modules/search_router.py`

#### Problèmes identifiés

**P26 — Recherche globale : 4 types d'entités + UNION ALL source values**

La recherche globale exécute :
1. Query SQLAlchemy sur `Cohort` (ILIKE sur name)
2. Connexion CDM + query sur `concept` (ILIKE sur name/code)
3. UNION ALL sur 8 tables cliniques (source_value ILIKE) — **le plus lourd**
4. Query SQLAlchemy sur `SavedQuery` (ILIKE sur name)
5. Query SQLAlchemy sur `MappingDecision` (ILIKE sur source_value)

Le point 3 est le même pattern que P24 — UNION ALL de 8 ILIKE scans.

**Recommandation** :
- Ajouter un **index GIN sur `source_value`** des tables cliniques (voir section 13)
- Limiter la recherche source_value aux domaines les plus pertinents (pas tous)
- Ajouter un **debounce côté frontend** pour éviter de déclencher cette recherche à chaque frappe

---

## 11. Audit Logs (main.py)

### Fichier : `main.py` lignes 173-331

#### Problèmes identifiés

**P27 — Lecture complète de fichiers JSONL en mémoire**

```python
for line in log_file.read_text().strip().split("\n"):
    entry = json.loads(line)
    if user and entry.get("user") != user: continue
    entries.append(entry)
entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
```

Pour un système actif, un fichier journalier peut faire 10-100MB. La totalité est :
1. Chargée en mémoire (`read_text()`)
2. Découpée en lignes (`split("\n")`)
3. Parsée en JSON (`json.loads()` par ligne)
4. Filtrée en Python
5. Triée en Python
6. Paginée en Python

**Recommandation** :
- **Court terme** : Lire le fichier en streaming (ligne par ligne) et arrêter dès que `page_size` résultats filtrés sont collectés (si tri chronologique inverse = ordre fichier inverse)
- **Moyen terme** : Stocker les audit logs en base PostgreSQL avec index sur `(date, user, action)`
- **`get_audit_stats`** et **`export_audit_csv`** ont le même problème

**P28 — Endpoint i18n : lecture fichier à chaque requête** — **CORRIGE 2026-03-13**

```python
@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    with open(filepath) as f:
        return json.load(f)
```

Le fichier est relu et parsé à chaque appel. Il ne change qu'au déploiement.

**Recommandation** : `@lru_cache` ou lecture au démarrage.

---

## 12. Base Applicative — Schéma & Index

### Fichier : `db/models.py`

#### Ce qui est bien fait
- Index sur les colonnes `cdm_name`, `domain`, `username` des principales tables
- `UniqueConstraint` sur `ReferenceCodebook`, `CdmAccess`, `CohortShare`, `UserGroupMember`
- `_utcnow()` avec timezone

#### Index composites manquants (CRITIQUE) — **CORRIGE 2026-03-13**

| Table | Index manquant | Pattern de requête |
|-------|---------------|-------------------|
| `analysis_snapshots` | `(cdm_name, domain)` | Toute requête quality/mapping |
| `analysis_snapshots` | `(cdm_name, domain, version DESC)` | "Get latest snapshot" |
| `mapping_decisions` | `(cdm_name, domain)` | Dashboard mapping |
| `mapping_decisions` | `(cdm_name, domain, source_value)` | Mapping audit |
| `cohort_versions` | `(cohort_id, version DESC)` | "Get latest version" |
| `notifications` | `(username, read)` | Badge de notifications |
| `access_requests` | `(username, status)` | Vérification doublon |

**Impact** : Sans ces index composites, PostgreSQL utilise un seul index (ex: `cdm_name`) puis filtre séquentiellement sur la 2ème colonne. Sur les snapshots avec historique, cela devient de plus en plus lent.

#### Contraintes d'intégrité manquantes

| Table | Contrainte manquante | Risque |
|-------|---------------------|--------|
| `analysis_snapshots` | `UNIQUE(cdm_name, domain, version)` | Versions dupliquées possibles |
| `cohort_versions` | `UNIQUE(cohort_id, version)` | Versions dupliquées possibles |
| `cohort_versions` | `FK(cohort_id) → cohorts(id)` | Versions orphelines si cohort supprimée |
| `incidence_analyses` | `FK(target_cohort_id) → cohorts(id)` | Références cassées |
| `estimation_analyses` | `FK(target_cohort_id) → cohorts(id)` | Références cassées |
| `cohort_shares` | `FK(cohort_id) → cohorts(id)` | Partages orphelins |

#### Colonnes Text au lieu de JSONB

| Table | Colonne | Type actuel | Recommandé |
|-------|---------|------------|-----------|
| `concept_sets` | `concepts_json` | `Text` | `JSONB` |
| `incidence_analyses` | `parameters_json` | `Text` | `JSONB` |
| `incidence_analyses` | `results_json` | `Text` | `JSONB` |
| `estimation_analyses` | `parameters_json` | `Text` | `JSONB` |
| `estimation_analyses` | `results_json` | `Text` | `JSONB` |

**Avantage JSONB** : Validation à l'écriture, indexation GIN possible, requêtes JSON côté base, stockage plus compact.

---

## 13. Optimisations côté Base Source OMOP CDM

Ce sont des recommandations d'index et de configuration à appliquer **sur les bases OMOP CDM sources** pour accélérer les requêtes OPAL. Ces index n'affectent que les performances en lecture (la base est en lecture seule).

### Index prioritaires à créer

```sql
-- 1. Extension pg_trgm (nécessaire pour fuzzy matching)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Index trigram sur concept_name (accélère ILIKE, fuzzy, keyword)
CREATE INDEX CONCURRENTLY idx_concept_name_trgm
ON omop_cdm.concept USING gin (concept_name gin_trgm_ops);

-- 3. Index sur concept_code (accélère exact match mapping)
CREATE INDEX CONCURRENTLY idx_concept_code
ON omop_cdm.concept (concept_code) WHERE invalid_reason IS NULL;

-- 4. Index sur concept_synonym_name (accélère ingredient match)
CREATE INDEX CONCURRENTLY idx_concept_syn_name_trgm
ON omop_cdm.concept_synonym USING gin (concept_synonym_name gin_trgm_ops);

-- 5. Index sur source_value des tables cliniques (accélère search + mapping)
CREATE INDEX CONCURRENTLY idx_condition_source_value
ON omop_cdm.condition_occurrence (condition_source_value);

CREATE INDEX CONCURRENTLY idx_drug_source_value
ON omop_cdm.drug_exposure (drug_source_value);

CREATE INDEX CONCURRENTLY idx_measurement_source_value
ON omop_cdm.measurement (measurement_source_value);

CREATE INDEX CONCURRENTLY idx_procedure_source_value
ON omop_cdm.procedure_occurrence (procedure_source_value);

CREATE INDEX CONCURRENTLY idx_observation_source_value
ON omop_cdm.observation (observation_source_value);

-- 6. Index composite sur observation_period (accélère les analyses de durée)
CREATE INDEX CONCURRENTLY idx_obs_period_dates
ON omop_cdm.observation_period (
    observation_period_start_date, observation_period_end_date
);

-- 7. Index sur concept_ancestor (déjà indexé dans OMOP standard, vérifier)
-- Normalement indexé, mais vérifier :
-- CREATE INDEX CONCURRENTLY idx_ca_ancestor ON omop_cdm.concept_ancestor (ancestor_concept_id);
-- CREATE INDEX CONCURRENTLY idx_ca_descendant ON omop_cdm.concept_ancestor (descendant_concept_id);

-- 8. Index sur concept_relationship pour "Maps to"
CREATE INDEX CONCURRENTLY idx_cr_maps_to
ON omop_cdm.concept_relationship (concept_id_1, relationship_id)
WHERE relationship_id = 'Maps to' AND invalid_reason IS NULL;

-- 9. Index sur date columns des tables cliniques (accélère monthly counts + conformity)
CREATE INDEX CONCURRENTLY idx_condition_date
ON omop_cdm.condition_occurrence (condition_start_date);

CREATE INDEX CONCURRENTLY idx_drug_date
ON omop_cdm.drug_exposure (drug_exposure_start_date);

CREATE INDEX CONCURRENTLY idx_measurement_date
ON omop_cdm.measurement (measurement_date);
```

### Configuration PostgreSQL recommandée pour les CDMs

```ini
# postgresql.conf — pour des bases OMOP CDM analytiques (read-heavy)
shared_buffers = 4GB               # 25% de RAM
effective_cache_size = 12GB         # 75% de RAM
work_mem = 256MB                    # Pour les sorts/hash aggregates (quality analysis)
maintenance_work_mem = 1GB          # Pour CREATE INDEX CONCURRENTLY
random_page_cost = 1.1              # SSD (si applicable)
effective_io_concurrency = 200      # SSD
max_parallel_workers_per_gather = 4 # Parallélisme des scans
default_statistics_target = 500     # Meilleures estimations de cardinalité
```

---

## 14. Startup & Middleware

### Fichier : `main.py`

**P29 — `Base.metadata.create_all()` à chaque démarrage**

Ligne 72 : SQLAlchemy vérifie l'existence de chaque table à chaque redémarrage. En production, le schéma est stable.

**Recommandation** : Migrer vers Alembic pour les migrations de schéma.

**P30 — Migrations inline à chaque démarrage**

Lignes 75-91 : `ALTER TABLE` conditionnels exécutés à chaque startup. `sa_inspect` + introspection de colonnes ajoutent de la latence au démarrage.

**P31 — AuditMiddleware sur tous les endpoints** — **NON APPLICABLE (déjà implémenté)**

`SKIP_PATHS` dans `audit/logger.py` exclut déjà `/api/health`, `/api/i18n`, `/api/auth`, `/docs`, etc.

**P32 — `import requests` synchrone pour Keycloak**

Les appels à Keycloak via la bibliothèque `requests` bloquent le thread pool de FastAPI. Un appel lent à Keycloak (réseau) bloque un worker.

**Recommandation** : Utiliser `httpx.AsyncClient` avec des endpoints `async def`.

---

## 15. Frontend — Patterns d'appels API

#### Ce qui est bien fait
- Client API centralisé (`src/api/client.ts`) avec Axios
- `Promise.all` pour les appels parallèles (ex: concept details, `ConceptExplorerPage.tsx:201`)
- `localStorage` pour le CDM sélectionné
- `useSessionState` pour persister l'état entre navigations

#### Problèmes identifiés

**P33 — Pas de cache côté client**

Aucun cache API. Chaque changement de page refetch les mêmes données. Données statiques re-fetchées à chaque navigation :
- `qualityApi.domains()` — liste statique, fetchée à chaque visite de QualityPage
- `cohortApi.listDomains()` — idem, fetchée à chaque montage de CriteriaPanel
- `conceptApi.domains(cdm)` / `conceptApi.vocabularies(cdm)` — rarement modifiées
- `cdmAccessApi.getAccessibleCdms()` — change uniquement quand l'admin modifie les accès

**Recommandation** : Utiliser React Query / TanStack Query avec `staleTime` adapté :
- Données statiques (domains, vocabularies) : `staleTime: Infinity` (ne change qu'au déploiement)
- Snapshots : `staleTime: 5 * 60 * 1000` (5 min)
- Concept search : `staleTime: 30 * 1000` (30s)
- Notifications : `staleTime: 15 * 1000` (15s)

**P34 — Recherche globale : pas de debounce visible**

Si l'utilisateur tape rapidement, chaque caractère déclenche potentiellement un appel à `/api/search/` qui exécute un UNION ALL sur 8 tables cliniques (P26).

**Recommandation** : Debounce de 300-500ms côté frontend.

**P35 — Appels API dupliqués**

- `getAccessibleCdms()` appelé simultanément depuis `App.tsx:124` ET `TopNav.tsx:120` à chaque authentification — 2 requêtes identiques
- `qualityApi.timeline()` appelé depuis `QualityPage.tsx:348` ET `SnapshotTimeline.tsx:37` — même payload
- `qualityApi.activeAnalyses()` appelé 2 fois au montage de QualityPage (batch + conformity tabs)

**Recommandation** : Partager via React Context ou cache partagé (React Query déduplique nativement les requêtes identiques).

**P36 — Waterfall concept search → counts**

`ConceptExplorerPage.tsx:139-145` : La recherche de concepts fait d'abord `conceptApi.search()`, puis enchaîne `conceptApi.counts()` avec les IDs retournés. C'est un waterfall (la 2ème requête attend la 1ère).

**Recommandation** : Retourner les counts inline dans la réponse de recherche côté backend.

**P37 — 3 appels parallèles par clic sur un concept**

`ConceptExplorerPage.tsx:201-206` : Chaque clic sur un concept déclenche `details()` + `hierarchy()` + `sourceValues()` — 3 connexions OMOP ouvertes/fermées (sans pool).

**Recommandation** : Endpoint composite backend `/concepts/full/{id}` qui retourne tout en 1 appel.

**P38 — Payloads complets slicés côté client**

- `HomePage.tsx:49` : `cohortApi.list()` retourne TOUTES les cohortes, mais seules les 5 premières sont affichées (`slice(0, 5)`)
- `HomePage.tsx:50` : `favoritesApi.list()` retourne TOUS les favoris, seuls les 10 premiers affichés
- `qualityApi.getLatestSnapshot()` retourne le JSON complet des résultats, mais seul `results.summary` est utilisé sur le Dashboard

**Recommandation** : Ajouter des paramètres `limit` côté API et/ou des endpoints allégés (ex: `/api/quality/snapshots/latest/summary`).

**P39 — Polling notifications sans vérification de staleness**

`TopNav.tsx:94` : Badge notifications pollé toutes les 15s + à chaque `window.focus`. `setBadges()` est appelé même si les valeurs n'ont pas changé, causant des re-renders inutiles.

**Recommandation** : Comparer les nouvelles valeurs avant de mettre à jour le state.

**P40 — Chargement N+1 des colonnes par table**

`DataManagementPage.tsx:285-300` : Quand l'utilisateur sélectionne des tables, `listColumns()` est appelé individuellement pour chaque table. 5 tables = 5 appels séquentiels.

**Recommandation** : Endpoint batch acceptant plusieurs noms de tables.

---

## 16. Modules Restants — Cohort, Data Management, Estimation, Incidence, Concept Sets

### Fichiers : `modules/cohort/router.py`, `modules/datamanagement/router.py`, `modules/estimation/router.py`, `modules/incidence/router.py`, `modules/concept_set/router.py`, `modules/cohort_templates_router.py`

**P48 — N+1 dans `list_cohorts` (cohort/router.py:199-262)** — **CORRIGE 2026-03-13**

La liste des cohortes charge toutes les cohortes, puis boucle pour récupérer la dernière version de chacune :

```python
cohorts = query.all()           # 1 requête
for c in cohorts:
    latest = db.query(CohortVersion).filter(...).first()  # N requêtes
```

De plus, `_can_access_cohort` (lignes 312-341) est appelée pour chaque cohorte, ajoutant encore des requêtes pour vérifier les groupes utilisateur.

**Impact** : Pour 100 cohortes = 200+ requêtes au lieu de 2-3.

**Recommandation** :
- JOIN avec sous-requête `DISTINCT ON (cohort_id) ORDER BY version DESC`
- Charger les groupes de l'utilisateur une seule fois et passer en paramètre

---

**P49 — N+1 dans `list_cohorts_for_extraction` (datamanagement/router.py:113-146)**

Même pattern que P48 : charge toutes les cohortes puis boucle pour récupérer la dernière version.

**Recommandation** : Même fix que P48 — JOIN avec `DISTINCT ON`.

---

**P50 — `patient_journey` boucle sur tous les domaines (cohort/router.py:1184-1317)**

Pour un seul patient, exécute une requête SQL par domaine OMOP (~10+ requêtes séparées), puis trie les événements en Python.

```python
for domain_name, dcfg in DOMAIN_CONFIG.items():
    cur.execute(f"SELECT ... FROM {schema}.{table} WHERE person_id = %s", ...)
events.sort(key=lambda e: e.get("start_date") or "9999")
```

**Recommandation** : Combiner en une seule requête `UNION ALL` avec `ORDER BY start_date` côté SQL.

---

**P51 — `concept_set_counts` : 1 requête par domaine (concept_set/router.py:182-222)**

Boucle sur `DOMAIN_CONFIG` pour compter les occurrences d'un concept set dans chaque table clinique — 10-15 requêtes séparées.

**Recommandation** : `UNION ALL` sur toutes les tables en une seule requête.

---

**P52 — JSON parsing dans `list_concept_sets` (concept_set/router.py:70)**

Chaque concept set de la liste est parsé en JSON juste pour compter le nombre de concepts :

```python
"concept_count": len(json.loads(s.concepts_json)) if s.concepts_json else 0
```

**Recommandation** : Stocker le count en colonne dénormalisée ou utiliser `json_array_length()` côté SQL.

---

**P53 — Kaplan-Meier agrège en Python (estimation/router.py:264-282)**

Toutes les lignes de survie sont chargées en mémoire puis regroupées par strate en Python.

**Recommandation** : Effectuer le regroupement et le calcul des probabilités de survie côté SQL avec `GROUP BY` et fonctions fenêtre.

---

**P54 — `incidence_rate` agrège en Python (incidence/router.py:129-163)**

Charge toutes les lignes brutes puis passe à une fonction Python pour calculer le taux d'incidence.

**Recommandation** : Calculer `COUNT(*)` et `SUM(time_at_risk)` directement en SQL.

---

**P55 — Pagination manquante sur endpoints de liste**

Les endpoints suivants retournent tous les enregistrements sans LIMIT :
- `list_concept_sets` (concept_set/router.py)
- `list_templates` (cohort_templates_router.py)
- `list_estimations` (estimation/router.py)
- `list_incidence_analyses` (incidence/router.py)

**Recommandation** : Ajouter paramètres `limit` et `offset` avec des défauts raisonnables (50-100).

---

**P56 — `cohort_sample_detailed` lookup de labels en Python (cohort/router.py:616-644)**

Double boucle sur les patients et colonnes de code pour construire un set de codes nécessitant un label, puis requête `reference_codebook`, puis re-boucle pour appliquer.

**Recommandation** : `LEFT JOIN` directement dans la requête SQL initiale pour obtenir les descriptions.

---

## 17. Matrice de Priorités

### Impact CRITIQUE (faire en premier)

| ID | Module | Problème | Effort | Impact perf |
|----|--------|----------|--------|-------------|
| ~~P1~~ | ~~Connector~~ | ~~Pas de pool de connexions OMOP~~ | ~~Moyen~~ | ~~-50-100ms/requête~~ **CORRIGE** |
| P11 | ObsPeriod | ~~Cumulative observation O(N*M)~~ **CORRIGE** (fenêtre cumulative O(N)) | Faible | -100x sur cette requête |
| P13 | ObsPeriod | ~~CTE `per` recalculée 6×~~ **CORRIGE** (CTE factorisée `per_cte`) | Faible | Factorisation code, cache plan PG |
| ~~P8~~ | ~~Clinical~~ | ~~3 scans → 1 dans mapping_stats~~ | ~~Faible~~ | ~~-30-60s par domaine~~ **CORRIGE** |
| P9 | Dashboard | ~~24 requêtes → 17~~ **CORRIGE** | Moyen | -30% temps dashboard |
| P48 | Cohort | ~~list_cohorts N+1~~ **CORRIGE** (subquery JOIN) | Moyen | -200+ queries/page |
| P57 | Cohort | ~~Occurrence fenêtrée O(N²) corrélée~~ **CORRIGE** (window RANGE) | Faible | -100x sur cette CTE |
| P58 | Cohort | Attrition N+1 requêtes re-scannant | Moyen | -N scans complets |
| P59 | Cohort | Export CSV non streamé (OOM risk) | Moyen | Mémoire -90% |
| Index composites | App DB | ~~`(cdm_name, domain)` etc.~~ **CORRIGE** (models.py) | Faible | Toutes les requêtes app |

### Impact ÉLEVÉ (planifier rapidement)

| ID | Module | Problème | Effort | Impact perf |
|----|--------|----------|--------|-------------|
| P18 | Mapping | Batch suggest N+1 | Moyen | -60% requêtes batch |
| P19 | Mapping | ILIKE sans pg_trgm | Moyen (DBA) | -90% temps fuzzy/keyword |
| P14 | Conformity | ~~4 scans → 1 par table~~ **CORRIGE** (FILTER clause) | Faible | -75% temps conformité |
| P22 | Concept | ~~COUNT séparé du SELECT~~ **CORRIGE** (COUNT OVER()) | Faible | -1 scan par recherche |
| P49 | DataMgmt | list_cohorts_for_extraction N+1 | Moyen | -100+ queries |
| P50 | Cohort | patient_journey 10+ queries→1 UNION | Faible | -10 queries/patient |
| P51 | ConceptSet | concept_set_counts 15 queries→1 | Faible | -14 queries |
| P27 | Audit | JSONL en mémoire | Moyen | Mémoire + latence |
| ~~P2~~ | ~~App DB~~ | ~~Pas de pool_recycle~~ | ~~Trivial~~ | ~~Stabilité production~~ **CORRIGE** |

### Impact MOYEN (backlog)

| ID | Module | Problème | Effort | Impact perf |
|----|--------|----------|--------|-------------|
| ~~P4~~ | ~~Clinical~~ | ~~COUNT(DISTINCT) full scan~~ | ~~Moyen~~ | ~~Dépend des index source~~ **CORRIGE** |
| ~~P7~~ | ~~Clinical~~ | ~~STRING_AGG sans sous-LIMIT~~ | ~~Faible~~ | ~~Variable~~ **CORRIGE** |
| P15 | Cohort | SQL non caché | Faible | Micro-optimisation |
| P23 | Concept | Source values : boucle domaines | Faible | -7 requêtes inutiles |
| P28 | main.py | ~~i18n sans cache~~ **CORRIGE** (cache startup) | Trivial | Micro-optimisation |
| P33 | Frontend | Pas de cache client (React Query) | Moyen | UX + réseau |
| P34 | Frontend | Pas de debounce search | Trivial | -N requêtes inutiles |
| P35 | Frontend | Appels API dupliqués (CDMs, timeline) | Faible | -2-3 requêtes/page |
| P36 | Frontend | Waterfall concept search→counts | Moyen | -1 round-trip |
| P37 | Frontend | 3 appels par clic concept (endpoint composite) | Moyen | -2 connexions OMOP |
| P38 | Frontend | Payloads complets slicés côté client | Faible | Bande passante |
| P41 | Connector | autocommit=False pour read-only | Trivial | Overhead transaction |
| P42 | Quality | Race condition _save_snapshot | Faible | Intégrité données |
| P43 | Backend | Cache lookups CdmConfig/Settings | Faible | -2 queries/requête |
| P44 | Mapping | ~~Dashboard N+1 domaines~~ **CORRIGE** (DISTINCT ON) | Faible | -17 queries |
| P45 | Mapping | ~~strategy_stats agrège en Python~~ **CORRIGE** (SQL GROUP BY) | Faible | Mémoire + CPU |
| P46 | Mapping | ~~SapBERT charge tout un domaine~~ **CORRIGE** (IN filter) | Faible | Mémoire |
| P47 | Mapping | ~~apply_mapping INSERT séquentiel~~ **CORRIGE** (execute_values) | Faible | -N round-trips |
| P53 | Estimation | Kaplan-Meier agrège en Python | Moyen | Mémoire grandes cohortes |
| P54 | Incidence | Taux d'incidence agrège en Python | Moyen | Mémoire grandes cohortes |
| P56 | Cohort | sample_detailed labels en Python | Faible | -2 passes sur données |
| P60 | Cohort | count_approximate n'est pas approximate | Faible | Endpoint inutile |
| P61 | Cohort | _active_characterizations fuite mémoire | Faible | Stabilité production |
| P62 | Cohort | _can_access_cohort 3 queries→1 | Faible | -2 queries/accès |

### Impact FAIBLE (amélioration continue)

| ID | Module | Problème | Effort |
|----|--------|----------|--------|
| ~~P3~~ | ~~App DB~~ | ~~Pool non configurable~~ | ~~Trivial~~ **CORRIGE** |
| P5 | Clinical | Monthly counts sans index | Dépend DBA |
| P6 | Clinical | Double GROUP BY distribution | Intrinsèque |
| P10 | Dashboard | ~~Pas de cache dashboard~~ **NON APPLICABLE** (snapshots versionnés suffisent) | Moyen |
| P16 | Cohort | Pas d'EXPLAIN endpoint | Faible |
| P17 | Cohort | concept_ancestor expansion | Faible |
| P29 | Startup | create_all à chaque démarrage | Moyen (Alembic) |
| P30 | Startup | Migrations inline | Moyen (Alembic) |
| P31 | Middleware | Audit sur health check | Trivial |
| P32 | main.py | requests synchrone Keycloak | Moyen |
| P39 | Frontend | Polling notifications sans stale check | Trivial |
| P40 | Frontend | N+1 chargement colonnes par table | Faible |
| P52 | ConceptSet | JSON parsing pour count dans liste | Trivial |
| P55 | Divers | Pagination manquante sur 4 endpoints | Trivial |

---

## Récapitulatif des gains estimés

| Scénario | Avant (estimé) | Après optimisation | Gain |
|----------|----------------|-------------------|------|
| Analyse Quality 1 domaine (100M lignes) | ~120s | ~60-80s | 30-50% |
| Dashboard (8 domaines) | ~300s | ~120-150s | 50-60% |
| Observation Period analysis | ~90s | ~30-40s | 55-65% |
| Conformité | ~120s | ~40-50s | 60-65% |
| Batch suggest 50 termes (sans pg_trgm) | ~60s | ~15-20s | 65-75% |
| Batch suggest 50 termes (avec pg_trgm) | ~60s | ~5-8s | 85-90% |
| Recherche globale (sans index source) | ~10-30s | ~1-3s | 90% |
| Latence par requête API (pool connexion) | +50-100ms | +5-10ms | 90% |
| Liste cohortes (100 cohortes) | 200+ queries, ~2s | 2-3 queries, ~100ms | 95% |
| Patient journey (1 patient) | 10+ queries, ~500ms | 1 query, ~50ms | 90% |
| Attrition 15 critères | 16 queries, ~30s | 1 query, ~5s | 80-85% |
| Export cohort 1M patients | ~800Mo RAM | ~50Mo streaming | 95% mémoire |
