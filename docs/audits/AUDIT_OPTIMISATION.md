# Audit d'Optimisation & Performance Approfondi — OPAL v1.2.1

**Date** : 2026-03-20
**Périmètre** : Backend (FastAPI/psycopg2), Frontend (React 18/Vite), Infrastructure (Docker/PostgreSQL/Nginx)
**Méthodologie** : Lecture complète de chaque fichier SQL, analyse de chaque requête ligne par ligne, profilage statique des patterns mémoire/concurrence, audit du bundle frontend
**Auditeur** : Claude Code (Opus 4.6) — audit exhaustif basé sur le code source
**Branche** : OPAL_V1.2.1

---

## Résumé Exécutif

| Sévérité | Trouvées | Statut |
|----------|----------|--------|
| CRITIQUE | 5 | 0 corrigé, 5 présents |
| HAUTE | 8 | 0 corrigé, 8 présents |
| MOYENNE | 7 | 0 corrigé, 7 présents |
| BASSE | 5 | 0 corrigé, 5 présents |
| **Total** | **25** | **25 en attente** |

L'application est globalement bien conçue (connection pooling, GZip, lazy loading, cache i18n, thread pool borné). Les problèmes critiques concernent les requêtes SQL répétées inutilement (CTE observation_period exécuté 6 fois, source value search double-exécution), le chargement mémoire non borné (pathways fetchall), et l'absence de parallélisme dans le batch mapping.

---

## Findings détaillés

### CRITIQUE

---

#### O01 — Observation Period exécute le même CTE 6 fois

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/quality/domains/observation_period.py:56-261` |
| **Statut** | Présent |

**Description** : Le CTE `per` (GROUP BY complet sur `observation_period`) est embarqué textuellement dans 6 requêtes séparées. Chaque requête re-matérialise ce CTE from scratch. Sur un CDM avec des millions de périodes d'observation, chaque matérialisation est un full table scan + GROUP BY.

Le code commente "P13 fix: queries are grouped to share the same CTE per" mais l'implémentation exécute toujours 6 `cur.execute()` séparés. PostgreSQL ne peut pas partager les résultats CTE entre instructions distinctes.

**Impact estimé** : 6 full scans de la table `observation_period` au lieu de 1. Sur une table de 10M lignes : ~30s vs ~5s.

**Correction recommandée** : Utiliser une TABLE TEMPORAIRE :
```sql
CREATE TEMP TABLE _obs_per AS
SELECT person_id, MIN(observation_period_start_date) AS obs_start,
       MAX(observation_period_end_date) AS obs_end
FROM {schema}.observation_period GROUP BY person_id;
CREATE INDEX ON _obs_per(person_id);
```
Puis référencer `_obs_per` dans les 6 requêtes. Supprimer à la fin. Note : le code de pathways utilise déjà des tables temporaires.

---

#### O02 — Pathways `fetchall()` charge un result set non borné en mémoire

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Mémoire |
| **Fichier** | `backend/modules/cohort/pathways.py:244-256` |
| **Statut** | Présent |

**Description** : Après calcul des étapes de pathway, le code fait `rows = cur.fetchall()` sur une requête retournant une ligne par (person_id, step_rank). Pour une cohorte de 500K patients avec jusqu'à 5 étapes : 2.5M lignes chargées en mémoire Python comme dicts `RealDictCursor`.

**Impact estimé** :
- 10K patients × 3 étapes = 30K lignes × ~200B = **6 MB** ✅
- 100K patients × 5 étapes = 500K lignes × ~200B = **100 MB** ⚠️
- 500K patients × 5 étapes = 2.5M lignes × ~200B = **500 MB** ❌ (OOM avec limite conteneur 2G)

**Correction recommandée** : Utiliser un curseur server-side avec `cur.itersize = 5000` et construire `person_paths` incrémentalement :
```python
cur.itersize = 5000
cur.execute(...)
for r in cur:
    person_paths[r["person_id"]].append(r["step_label"])
```

---

#### O03 — Source value search exécute la requête complète 2 fois

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/concept/router.py:426-441` |
| **Statut** | Présent |

**Description** : L'endpoint `search_source_value` construit un UNION ALL sur toutes les tables de domaines, puis l'exécute DEUX FOIS : une fois wrappée dans `SELECT COUNT(*) FROM (...)` pour le total, et une fois avec `LIMIT/OFFSET` pour les données. Le UNION ALL est coûteux (ILIKE scans sur toutes les tables cliniques).

**Impact estimé** : Double le temps de requête. Si l'union prend 5s, l'endpoint prend 10s.

**Correction recommandée** : Utiliser le pattern `COUNT(*) OVER()` window function (déjà utilisé dans concept search à la ligne 131) :
```sql
SELECT *, COUNT(*) OVER() AS _total_count FROM (...union...) sub
ORDER BY n_records DESC LIMIT %s OFFSET %s
```

---

#### O04 — Batch mapping suggestions purement séquentielles

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Concurrence |
| **Fichier** | `backend/modules/mapping/suggest.py:103-125` |
| **Statut** | Présent |

**Description** : `suggest_batch` traite les termes un par un dans une boucle for sur une seule connexion. Chaque terme exécute jusqu'à 6 stratégies, chacune avec plusieurs requêtes SQL. Pour 200 termes avec 5+ requêtes chacun : 1000+ requêtes séquentielles.

Le commentaire "psycopg2 connections are not thread-safe" est correct, mais la solution n'est pas d'éviter le parallélisme — c'est d'utiliser plusieurs connexions du pool.

**Impact estimé** : 200 termes × ~200ms/terme = ~40s. Avec 4 connexions en parallèle : ~10s.

**Correction recommandée** : Découper le batch en chunks et traiter chaque chunk sur une connexion poolée séparée via le thread pool :
```python
from concurrent.futures import as_completed
from utils.thread_pool import executor

def _process_chunk(chunk, domain, omop_schema, ...):
    conn = get_omop_connection(...)
    try:
        return [suggest_mappings(conn, ...) for term in chunk]
    finally:
        conn.close()

chunks = [terms[i:i+50] for i in range(0, len(terms), 50)]
futures = [executor.submit(_process_chunk, chunk, ...) for chunk in chunks]
```

---

#### O05 — N+1 requêtes `information_schema.tables` dans le dashboard

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/quality/domains/dashboard.py:41-50` |
| **Statut** | Présent |

**Description** : Pour chacun des 11 domaines cliniques, l'analyse dashboard émet une requête individuelle `SELECT 1 FROM information_schema.tables` pour vérifier l'existence de la table. Soit 11 round-trips à la base de données.

**Impact estimé** : 11 × ~5-15ms = 55-165ms d'overhead par analyse dashboard.

**Correction recommandée** : Remplacer par une seule requête :
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = %s AND table_name = ANY(%s)
```

---

### HAUTE

---

#### O06 — Global search interroge TOUTES les tables de domaines avec ILIKE

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/search_router.py:111-162` |
| **Statut** | Présent |

**Description** : La recherche globale émet des requêtes ILIKE sur TOUTES les 11 tables cliniques (source_value, source_name). Les requêtes ILIKE ne peuvent pas utiliser les index B-tree standard et nécessitent des sequential scans.

**Impact estimé** : Sur un CDM avec 100M de records cliniques, chaque recherche pourrait prendre 10-30s.

**Correction recommandée** :
1. Ajouter des index GIN `pg_trgm` sur les colonnes source_value des domaines les plus utilisés
2. Limiter la recherche source_value à 3-4 domaines les plus pertinents plutôt que les 11
3. Ajouter un cache TTL court pour les résultats de recherche récents
4. Ajouter une longueur de query minimale (actuellement min_length=1 permet les recherches d'un caractère)

---

#### O07 — Export CSV quality charge tout en mémoire

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Mémoire |
| **Fichier** | `backend/modules/quality/router.py:666-735` |
| **Statut** | Présent |

**Description** : L'export CSV charge le blob JSON `AnalysisSnapshot.results` complet en mémoire, construit le CSV complet dans un `StringIO`, puis envoie via `StreamingResponse(iter([output.getvalue()]))`. Le "streaming" est faux — la réponse entière est matérialisée en mémoire avant l'envoi.

**Correction recommandée** : Utiliser un vrai générateur streaming comme dans l'export audit log (`main.py:548-592`).

---

#### O08 — Pool OMOP : dimensionnement linéaire avec le nombre de CDMs

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Connection Pooling |
| **Fichier** | `backend/config.py:65-67`, `backend/db/omop_connector.py:119` |
| **Statut** | Présent |

**Description** : Chaque CDM obtient son propre `ThreadedConnectionPool(minconn=2, maxconn=20)`. Avec 10 CDMs enregistrés : 20-200 connexions PostgreSQL minimum. Beaucoup de CDMs rarement utilisés maintiennent 2 connexions idle chacun.

**Impact estimé** : 10 CDMs × 2 min_conn = 20 connexions idle × ~10MB chacune = 200MB de mémoire PostgreSQL pour les connexions idle.

**Correction recommandée** : Réduire `OMOP_POOL_MIN_CONN` à 1. Réduire `OMOP_POOL_IDLE_TIMEOUT` de 1800s (30 min) à 300s (5 min) pour les CDMs rarement utilisés.

---

#### O09 — Cache `_column_exists_cache` non borné sans éviction

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Caching |
| **Fichier** | `backend/utils/cdm_helper.py:40-61` |
| **Statut** | Présent |

**Description** : `_column_exists_cache` est un dict simple sans limite de taille ni TTL d'éviction. La clé du cache inclut le DSN de connexion. Les entrées périmées persistent indéfiniment — si le schéma d'un CDM change, le cache n'est jamais invalidé.

**Correction recommandée** : Ajouter une taille max et un TTL, similaire au cache concept dans `concept/router.py` :
```python
_COLUMN_CACHE_MAX = 1000
_COLUMN_CACHE_TTL = 600  # 10 min
```

---

#### O10 — Source values pour un concept itère les 11 tables séquentiellement

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/concept/router.py:293-356` |
| **Statut** | Présent |

**Description** : `get_concept_source_values` boucle sur les 11 tables de domaines et émet une requête séparée par table. Chaque requête fait un GROUP BY sur source_value avec un WHERE sur concept_id.

**Impact estimé** : 11 × ~50-200ms = 550ms-2.2s par lookup concept.

**Correction recommandée** : Construire un seul UNION ALL comme dans l'endpoint counts (lignes 570-611).

---

#### O11 — SSE event generator bloque un thread asyncio

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Concurrence |
| **Fichier** | `backend/modules/quality/router.py:282-375` |
| **Statut** | Présent |

**Description** : Le générateur SSE utilise `run_in_executor` avec un `queue.get(timeout=2.0)` bloquant — cela occupe un thread du pool asyncio par défaut pendant toute la durée de l'analyse (potentiellement plusieurs minutes).

**Correction recommandée** : Utiliser `asyncio.Queue` au lieu de `queue.Queue`, ou augmenter la taille du `ThreadPoolExecutor` par défaut.

---

#### O12 — CodeMirror et dépendances lourdes non code-split

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Bundle Size |
| **Fichier** | `frontend/package.json`, `frontend/vite.config.ts` |
| **Statut** | Présent |

**Description** : La configuration de chunks manuels ne split que `vendor` (react/react-dom/react-router-dom), `recharts` et `framer`. Mais :
- CodeMirror suite (~6 packages, ~120KB gzippé) : utilisé uniquement sur CohortPage SQL editor
- keycloak-js (~35KB) : chargé globalement
- @headlessui/react (~15KB)
- i18next + react-i18next (~25KB)

**Impact estimé** : Bundle initial ~600-800KB gzippé au lieu de ~300KB atteignable.

**Correction recommandée** : Ajouter CodeMirror aux chunks manuels :
```js
manualChunks: {
  'vendor': ['react', 'react-dom', 'react-router-dom'],
  'recharts': ['recharts'],
  'framer': ['framer-motion'],
  'codemirror': ['@codemirror/view', '@codemirror/state', '@codemirror/lang-sql', ...],
}
```

---

#### O13 — Distribution records-per-person calcule les buckets en Python

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/quality/domains/clinical.py:56-83` |
| **Statut** | Présent |

**Description** : La distribution records-per-person récupère tous les comptages per-person puis catégorise en buckets côté Python. Cela transfere potentiellement des millions de lignes au serveur app.

**Correction recommandée** : Faire le bucketing dans SQL :
```sql
SELECT CASE WHEN cnt = 1 THEN '1' WHEN cnt BETWEEN 2 AND 5 THEN '2-5' ... END AS bucket, COUNT(*)
FROM (SELECT person_id, COUNT(*) AS cnt FROM ... GROUP BY person_id) sub
GROUP BY bucket
```

---

### MOYENNE

---

#### O14 — `ORDER BY RANDOM()` dans les requêtes sample

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Performance SQL |
| **Fichier** | `backend/modules/cohort/sql_builder.py:277,432` |
| **Statut** | Présent |

**Description** : `build_sample_sql` et `build_detailed_sample_sql` utilisent `ORDER BY RANDOM()` qui force PostgreSQL à générer une valeur aléatoire pour chaque ligne puis à toutes les trier. Pour les grandes cohortes (100K+), c'est très coûteux.

**Correction recommandée** : Utiliser `TABLESAMPLE SYSTEM(n)` pour un échantillonnage approximatif.

---

#### O15 — Écritures audit log synchrones dans le middleware hot path

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | I/O |
| **Fichier** | `backend/audit/logger.py:118-132,135-187` |
| **Statut** | Présent |

**Description** : `write_audit_log` effectue des `open()` + `f.write()` synchrones sur chaque requête HTTP matchée. Cela bloque l'event loop async pendant le I/O fichier.

**Impact estimé** : ~0.1-1ms par requête. Sous forte concurrence (100+ requêtes simultanées), cela s'accumule.

**Correction recommandée** : Écrire dans une queue en mémoire et flusher sur disque dans un thread background, ou utiliser `aiofiles`.

---

#### O16 — Cache concept utilise une éviction O(N)

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Caching |
| **Fichier** | `backend/modules/concept/router.py:46-52` |
| **Statut** | Présent |

**Description** : Quand le cache concept atteint 500 entrées, l'éviction trouve la plus ancienne via `min(_concept_cache, key=lambda k: _concept_cache[k][0])`. C'est O(N) par insertion à capacité.

**Correction recommandée** : Utiliser `collections.OrderedDict` avec `move_to_end` pour une sémantique LRU, ou `functools.lru_cache`.

---

#### O17 — Timeout Axios 30s trop court pour les opérations lourdes

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Réseau |
| **Fichier** | `frontend/src/api/client.ts:133` |
| **Statut** | Présent |

**Description** : `api.defaults.timeout = 30000` s'applique à TOUTES les requêtes, y compris les analyses quality batch, caractérisation et extraction. Ces opérations peuvent légitimement prendre 60-120s.

**Correction recommandée** : Utiliser des timeouts per-requête pour les endpoints long-running :
```typescript
characterize: (cdmName, criteria, ...) =>
  api.post('/cohorts/characterize', data, { timeout: 120000 }),
```

---

#### O18 — AnimatePresence avec popLayout sur les grandes listes

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Rendu Frontend |
| **Fichier** | `frontend/src/components/ui/AnimatedList.tsx:44-47` |
| **Statut** | Présent |

**Description** : `AnimatePresence` avec `popLayout` sur les listes de 50+ items cause du layout thrashing. Chaque ajout/suppression d'item déclenche un recalcul de layout pour tous les autres items.

**Correction recommandée** : Pour les listes >30 items, utiliser des animations CSS au lieu de Framer Motion, ou désactiver `popLayout`.

---

#### O19 — Healthcheck backend lent (démarrage Python)

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Docker |
| **Fichier** | `docker-compose.yml:43` |
| **Statut** | Présent |

**Description** : Le healthcheck utilise `python -c "import urllib..."` qui nécessite le démarrage complet de l'interpréteur Python (~200-500ms). Répété toutes les 30s.

**Correction recommandée** : Utiliser `curl -f http://localhost:8000/api/health` ou `wget -q --spider`.

---

#### O20 — `get_domain_config()` appelé 2 fois par domaine dans le dashboard

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Caching |
| **Fichier** | `backend/modules/quality/domains/dashboard.py:42,112` |
| **Statut** | Présent |

**Description** : `get_domain_config()` est appelé une première fois dans la boucle d'existence de table, puis à nouveau dans la boucle sparkline. Double travail.

**Correction recommandée** : Mettre en cache le résultat dans une variable locale au début de la fonction.

---

### BASSE

---

#### O21 — Chunks manuels Vite : CodeMirror et i18n non split

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Bundle Size |
| **Fichier** | `frontend/vite.config.ts:17-25` |
| **Statut** | Présent |

---

#### O22 — Cleanup in-memory tasks redondant avec TTL existant

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Mémoire |
| **Fichier** | `backend/main.py:130-165` |
| **Statut** | Présent |

**Description** : Le cleanup in-memory tourne toutes les 5 min mais les tâches ont déjà un TTL de 30 min. Pression GC redondante.

---

#### O23 — PageTransition crée un toggle de classe à chaque navigation

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Rendu Frontend |
| **Fichier** | `frontend/src/App.tsx:70-84` |
| **Statut** | Présent |

---

#### O24 — Pas de multi-stage build optimisé dans le Dockerfile backend

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Docker |
| **Fichier** | `backend/Dockerfile` |
| **Statut** | Présent |

---

#### O25 — Table UI : pagination limitée à 7 pages sans ellipsis

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Rendu Frontend |
| **Fichier** | `frontend/src/components/ui/Table.tsx:167` |
| **Statut** | Présent |

---

## Index PostgreSQL recommandés pour les CDMs OMOP

```sql
-- Recherche de concepts (mapping suggest, concept explorer, global search)
CREATE INDEX IF NOT EXISTS idx_concept_name_trgm ON {schema}.concept
  USING gin (concept_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_concept_code_btree ON {schema}.concept (concept_code)
  WHERE invalid_reason IS NULL;
CREATE INDEX IF NOT EXISTS idx_concept_standard ON {schema}.concept (standard_concept, domain_id)
  WHERE standard_concept = 'S' AND invalid_reason IS NULL;

-- Source value lookups (mapping, dashboard, global search)
CREATE INDEX IF NOT EXISTS idx_condition_source_value ON {schema}.condition_occurrence (condition_source_value);
CREATE INDEX IF NOT EXISTS idx_drug_source_value ON {schema}.drug_exposure (drug_source_value);
CREATE INDEX IF NOT EXISTS idx_measurement_source_value ON {schema}.measurement (measurement_source_value);
CREATE INDEX IF NOT EXISTS idx_observation_source_value ON {schema}.observation (observation_source_value);
CREATE INDEX IF NOT EXISTS idx_procedure_source_value ON {schema}.procedure_occurrence (procedure_source_value);

-- Concept ancestor (cohort builder, concept explorer)
CREATE INDEX IF NOT EXISTS idx_concept_ancestor_ancestor ON {schema}.concept_ancestor (ancestor_concept_id);
CREATE INDEX IF NOT EXISTS idx_concept_ancestor_descendant ON {schema}.concept_ancestor (descendant_concept_id);

-- Observation period (characterization, incidence, estimation)
CREATE INDEX IF NOT EXISTS idx_obs_period_person ON {schema}.observation_period (person_id);

-- Concept relationship (mapping suggest stratégie 2)
CREATE INDEX IF NOT EXISTS idx_concept_rel_id1_rel ON {schema}.concept_relationship (concept_id_1, relationship_id)
  WHERE invalid_reason IS NULL;
```

---

## Estimation mémoire pour les chemins critiques

| Chemin | 10K patients | 100K patients | 500K patients |
|--------|-------------|---------------|---------------|
| Quality (1 domaine) | ~15 MB | ~15 MB | ~15 MB |
| Quality (11 domaines) | ~15 MB | ~15 MB | ~15 MB |
| Pathways (`fetchall`) | **6 MB** ✅ | **100 MB** ⚠️ | **500 MB** ❌ |
| Characterization | ~12 MB | ~12 MB | ~12 MB |
| Data extraction | ~20 MB | ~20 MB | ~20 MB |
| Mapping batch (200 termes) | ~15 MB | ~15 MB | ~15 MB |

Le seul chemin avec risque OOM est **Pathways** (O02) pour les grandes cohortes.

---

## Analyse du bundle frontend

| Chunk | Modules | Taille gzippée estimée | Utilisé sur |
|-------|---------|------------------------|-------------|
| `vendor` (existant) | react, react-dom, react-router-dom | ~45 KB | Toutes les pages |
| `recharts` (existant) | recharts | ~65 KB | Quality, Incidence, Estimation |
| `framer` (existant) | framer-motion | ~35 KB | Animations globales |
| `codemirror` (**à ajouter**) | @codemirror/* (6 packages) | ~120 KB | CohortPage uniquement |
| `keycloak` (**à ajouter**) | keycloak-js | ~35 KB | Auth init |
| `i18n` (**à ajouter**) | i18next + react-i18next | ~25 KB | Déferrable |

**Points positifs existants** :
- ✅ Toutes les 12+ pages utilisent `React.lazy()` + `Suspense`
- ✅ `ErrorBoundary` wrape chaque page
- ✅ `PageSkeleton` fournit des loading states
- ✅ Nginx sert les assets statiques avec cache 365d + immutable
