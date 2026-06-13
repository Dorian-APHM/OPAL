# Connecteurs CDM multi-moteurs (PostgreSQL / Oracle / SQL Server)

> Statut : **en cours**. PostgreSQL est le moteur historique et reste la
> référence (aucune régression de perf tolérée). Oracle et SQL Server sont
> ajoutés derrière une couche de dialecte. Les implémentations Oracle/MSSQL
> sont *best-effort* tant qu'elles n'ont pas été validées sur une vraie base.

## 1. Architecture des connexions au CDM externe

OPAL se connecte **en lecture seule** aux bases OMOP CDM externes. Toute la
mécanique passe par trois couches :

| Couche | Fichier | Rôle |
|---|---|---|
| Pool de connexions | `backend/db/omop_connector.py` | Un pool par CDM, wrapper `PooledConnection`, éviction idle, invalidation |
| Helper centralisé | `backend/utils/cdm_helper.py` | `get_cdm_connection()` : lookup + déchiffrement + connexion + `SchemaMap` |
| Modèle de config | `backend/db/models.py` (`CdmConfig`) | host/port/dbname/user/password chiffré/schema + **`db_type`** |

Le point d'entrée unique pour toute requête CDM est `get_cdm_connection(db, cdm_name)`
(ou `get_omop_connection(...)` directement dans quelques routers historiques).

## 2. Inventaire : tout ce qui appelle le CDM externe

Recensement exhaustif des fichiers ouvrant une connexion CDM (`get_cdm_connection` /
`get_omop_connection` / `_get_conn`) et du travail de portage qu'ils impliquent.

### 2.1 Points d'ouverture de connexion

| Fichier | Endpoint(s) | SQL exécuté sur le CDM |
|---|---|---|
| `modules/concept/router.py` | `/search`, `/details`, `/hierarchy`, `/domains`, `/vocabularies`, `/source-values`, `/counts`, ATC | Vocabulaire (`concept`, `concept_relationship`, `concept_ancestor`, `concept_synonym`) + comptages cliniques |
| `modules/mapping/router.py` | `/concept-lookup`, suggestions, apply | Vocabulaire + `source_to_concept_map` (seule écriture autorisée) |
| `modules/mapping/suggest.py` | (appelé par router) | `concept`, `concept_synonym`, `concept_relationship` |
| `modules/cohort/router.py` | génération/exécution de cohortes, `/concept-search` | Tables cliniques + vocabulaire |
| `modules/cohort/sql_builder.py` | (génère le SQL des cohortes) | **Le plus lourd** : critères → SQL |
| `modules/cohort/pathways.py` | pathways | `unnest(ARRAY[...])`, fenêtres temporelles |
| `modules/cohort/characterization.py` | caractérisation | `PERCENTILE_CONT ... WITHIN GROUP`, casts |
| `modules/quality/router.py` + `engine.py` | analyses qualité | `information_schema`, agrégats |
| `modules/quality/conformity.py` | conformité | `FILTER (WHERE ...)`, `CURRENT_DATE + INTERVAL` |
| `modules/quality/domains/*.py` | dashboards par domaine | `date_trunc`, `AGE`, `DATE_PART`, `MAKE_DATE`, `generate_series` |
| `modules/incidence/router.py` + `engine.py` | taux d'incidence | `INTERVAL`, fenêtres |
| `modules/estimation/router.py` | estimation | `EXTRACT`, casts, `INTERVAL` |
| `modules/datamanagement/router.py` + `extractor.py` | monitoring ETL, export | `information_schema`, `DictCursor` |
| `modules/concept_set/router.py` | résolution de concept sets | vocabulaire |
| `modules/search_router.py` | recherche globale | `concept` + tables sources |
| `modules/sapbert_router.py` | build SapBERT | lecture vocabulaire/sources |
| `modules/concept/source_value_cache.py` | **build du cache** | `SELECT DISTINCT ... GROUP BY` (à porter en priorité) |

### 2.2 Surface de couplage PostgreSQL (à traduire par dialecte)

- **Drivers / curseurs** : `psycopg2`, `DictCursor`/`RealDictCursor` — 19 fichiers.
- **`psycopg2.sql`** (`Identifier`/`SQL`) — ~120 appels, 8 fichiers.
- **`ILIKE` + `unaccent()`** : recherche de **vocabulaire** (concept/synonymes) dans
  `concept/router.py`, `mapping/suggest.py`, `mapping/router.py`, `cohort/router.py`,
  `search_router.py`. *(La recherche de **source values** ne tape plus le CDM : elle est
  100 % cache → voir §3.)*
- **Casts `::type`**, **`ARRAY[...]`/`unnest`**, **`INTERVAL`**, **`EXTRACT`/`AGE`/`DATE_PART`/
  `date_trunc`/`MAKE_DATE`/`generate_series`**, **`PERCENTILE_CONT ... WITHIN GROUP`**,
  **`FILTER (WHERE ...)`**, **`information_schema`**, **`SET statement_timeout`** (GUC).

## 3. Étape 1 — cache de valeurs source obligatoire (FAIT)

Les endpoints de recherche/exploration de **valeurs source** sont désormais servis
**exclusivement** par le cache pré-calculé `SourceValueCache` (base OPAL, toujours
PostgreSQL, recherche via `utils/text_search.iaccent_ilike` déjà compatible multi-moteur).

Le **fallback CDM direct** (qui utilisait `unaccent/ILIKE` PostgreSQL) a été **supprimé** de :

- `concept/router.py` : `/search-source-value`, `/search-source-value/fast`, `/search-source-value/export`
- `mapping/router.py` : `/unmapped/{cdm}/{domain}`

Quand le cache n'est pas construit, ces endpoints renvoient **HTTP 409**
(`{"code": "source_value_cache_missing", ...}`) via `cdm_helper.raise_source_value_cache_missing()`.
Le front doit proposer la construction du cache plutôt que d'afficher une liste vide.

> Conséquence multi-moteur : pour un CDM non-PostgreSQL, seule la **construction du
> cache** (`source_value_cache.py`, un `SELECT DISTINCT ... GROUP BY`) doit savoir lire
> le CDM. Toute la recherche de valeurs source retombe sur la base OPAL.

## 4. Couche de dialecte (FAIT — infrastructure)

Voir `backend/db/dialects/`. Un `Dialect` par moteur fournit :

- **connexion** : `connect()`, `dict_cursor()` (psycopg2 `RealDictCursor` pour PG ;
  `DictRowCursor` proxy pour Oracle/MSSQL), `set_statement_timeout()`, `reset_session()`.
- **métadonnées / streaming** : `table_exists()`, `column_exists()`,
  `disable_statement_timeout()`, `stream_cursor()` (curseur serveur nommé pour PG,
  curseur batché pour les autres).
- **exécution / paramstyle** : `execute(cursor, sql, params)` écrit le SQL en `%s`
  (style psycopg2) et le traduit vers `:1` (Oracle) ou `?` (ODBC) — voir
  `translate_pyformat()`. `quote_ident()` (`"x"` PG/Oracle, `[x]` MSSQL).
- **fragments SQL** (point d'extension du port analytique) : `ilike`, `unaccent`,
  `cast`, `current_date`, `interval_days`, `extract_year`, `limit_offset`.

Le chemin **PostgreSQL est strictement identique à l'existant** (mêmes pools psycopg2,
même SQL, `execute()` est un passthrough) → aucune régression de perf.

`CdmConfig.db_type` (défaut `postgresql`, migration `c9d0e1f2a3b4` qui *backfill* les
CDM existants en `postgresql`) sélectionne le dialecte. La page de config expose le
choix du moteur (`GET /api/cdm/engines`). Drivers : `oracledb` (thin), `pyodbc`
(import paresseux ; `unixodbc` dans l'image, `msodbcsql18` à ajouter pour MSSQL).

### Verticale source-value / mapping — FAIT, agnostique
Le **builder du cache** (`source_value_cache.py`) passe par le dialecte
(metadata + timeout + streaming). Comme la recherche de valeurs source est 100 %
cache (§3), **un CDM non-PG est pleinement utilisable** pour la recherche de codes
sources et l'explorateur de mapping dès que le cache est construit.

### Explorateur de concepts (`concept/router.py`) — FAIT, agnostique
Tous les endpoints de lecture du vocabulaire sont portés sur le dialecte (plus
aucun `psycopg2.sql` ni `RealDictCursor` dans le module) : `/search`, `/domains`,
`/vocabularies`, `/details`, `/hierarchy`, `/source-values/{id}`, `/counts`,
`/counts/source`, et le worker de build du cache. Helpers utilisés : `_tbl()`
(table qualifiée), `dialect.ilike/cast/limit_offset/in_list/quote_ident/execute`.

### Harnais d'intégration sur vraie base — `tests/test_integration_omop.py`
Exécute le **vrai SQL** des endpoints contre un OMOP réel, activé par
`OPAL_ITEST_OMOP_HOST` (+ `OPAL_ITEST_OMOP_DBTYPE`, défaut `postgresql`). Seeds :
`tests/fixtures/omop_mini_seed.sql` (PostgreSQL) et
`tests/fixtures/omop_mini_seed_oracle.sql` (Oracle). C'est la preuve de
non-régression : on lance la suite **avant et après** chaque port et on exige le
même résultat. (Hôte = IP non-loopback car l'API bloque loopback/SSRF.)
C'est le garde-fou à réutiliser pour porter les modules restants.

### Validation Oracle des endpoints portés — FAIT (vrai Oracle Free 23)
Le harnais a été exécuté sur **Oracle** (`db_type=oracle`, image
`container-registry.oracle.com/database/free`) : les 17 tests passent, comme sur
PostgreSQL (qui reste à 17/17 + suite unitaire verte). En plus du case-folding des
identifiants déjà géré par `quote_ident` (non quoté → Oracle remonte en majuscules),
trois écarts de portabilité, invisibles tant qu'on n'exécutait que sur PG, ont dû
être corrigés :

1. **Casse des colonnes en sortie** — `DictRowCursor` normalise les clés en
   minuscules (Oracle remonte les noms de colonnes en majuscules), pour que les
   lecteurs gardent l'accès `row["concept_id"]` comme avec `RealDictCursor`.
2. **Alias en underscore** — `concept/router.py` n'utilise plus l'alias
   `_total_count` (un identifiant Oracle ne peut commencer par `_` sans guillemets ;
   `ORA-00911`).
3. **Détection de colonnes optionnelles** — `cdm_helper._column_exists()` passe par
   `conn.dialect.column_exists()` (catalogue `ALL_TAB_COLUMNS` sur Oracle) au lieu
   d'une requête `information_schema … LIMIT 1` propre à PostgreSQL.

## 5. État du port par module — TERMINÉ ✅

**100 % du SQL touchant le CDM passe désormais par le `Dialect`.** Vérification :
`grep -r 'psycopg2.sql | cursor_factory | RealDictCursor' modules/` → **aucune occurrence**.
Chaque module a été **validé bout-en-bout sur un vrai PostgreSQL** (aucune régression PG) :

`concept/router.py`, `source_value_cache.py`, `search_router.py`, `mapping/suggest.py`,
`mapping/router.py` (+ chemin d'écriture *apply*), `atc_labels.py`, `concept_set/router.py`,
`sapbert_build.py`, `datamanagement/{router,extractor}.py`, `cohort/sql_builder.py`
(clé de voûte), `cohort/router.py`, `cohort/pathways.py`, `cohort/characterization.py`,
`incidence/engine.py`, `estimation/router.py`, `quality/conformity.py`,
`quality/domains/{person,dashboard,clinical,observation_period}.py`.

Les constructions « dures » ont chacune leur helper de dialecte (PG natif ;
Oracle/SQL Server *best-effort*, à valider sur vraie instance) :

| Construction | PostgreSQL | Oracle / SQL Server |
|---|---|---|
| `generate_series` | `generate_series` | CTE récursive (`int_series_cte`) |
| `AGE()` / mois | `AGE` + `DATE_PART` | `MONTHS_BETWEEN` / `DATEDIFF` |
| `MAKE_DATE` | `MAKE_DATE` | `TO_DATE` / `DATEFROMPARTS` |
| tables temp | `CREATE TEMP TABLE` | table régulière / `SELECT … INTO` |
| `= ANY` / `!= ALL` | array bind | `IN (...)` / `NOT IN (...)` |
| `INTERVAL N days` | `INTERVAL` | `(d±N)` / `DATEADD` |
| `FILTER (WHERE)` | `FILTER` | `SUM(CASE WHEN …)` |
| `ILIKE`/`unaccent` | natif | `LOWER() LIKE LOWER()` |
| paramstyle | `%s` / `%(n)s` | `:1` / `:name` / `?` (traduit) |
| `LATERAL`, `STRING_AGG`, `MODE`, `SAVEPOINT` | natif | best-effort (CROSS APPLY / LISTAGG / SAVE TRAN) — documenté |

**Ce qu'il reste = validation Oracle/SQL Server sur une vraie instance** (le SQL
est généré ; il « suffit » de l'exécuter). Voir §6 : brancher le harnais avec
`OPAL_ITEST_OMOP_DBTYPE=oracle|sqlserver`.

### Validation exhaustive sur vraies bases PG + Oracle — `tests/test_integration_omop_full.py`

Harnais couvrant **les 45 endpoints qui exécutent du SQL sur le CDM** (sync via
HTTP ; async/workers — quality analyze/conformity, characterization,
suggest-batch, cache build, extract — appelés directement contre une vraie
connexion). Lancé sur un vrai PostgreSQL 16 **et** un vrai Oracle Free 23 :

- **PostgreSQL : toute la surface passe** (35 tests + 2 *xfail* = bugs
  pré-existants ci-dessous). C'est la preuve de non-régression sur 100 % des
  endpoints CDM (et non plus le seul sous-ensemble de `test_integration_omop.py`).
- **Oracle : 23/35 passent ; 12 restent en échec** — ce sont exactement les
  « constructions dures » du tableau ci-dessus, *non encore finalisées* :
  - `cohort/sql_builder.py` (clé de voûte → count, count/approx, sample,
    sample/detailed, export, incidence, estimation, extract) : l'expansion de
    concepts `unnest(ARRAY[...])` et les alias `FROM (...) AS x` → **ORA-00907**.
  - `quality/domains/clinical.py` : `GROUP BY` non positionnel / `LATERAL` /
    `STRING_AGG` → **ORA-03162**.
  - `cohort/characterization.py` : tables temporaires nommées `_xxx` → **ORA-00911**.

  Ces 12 endpoints sont marqués `xfail` *uniquement sur Oracle* dans le harnais :
  la suite reste verte sur les deux moteurs et chaque lacune est tracée (un
  *xpass* signalera quand le port est terminé). Le constat corrige le « TERMINÉ ✅ »
  ci-dessus : 100 % du SQL **passe par le dialecte**, mais Oracle n'est pas encore
  100 % **exécutable** pour ces constructions.

### Bugs PRÉ-EXISTANTS découverts (identiques sur `main`, indépendants du moteur)

Non causés par le port (vérifiés à l'identique sur `main`), mais ce sont des
« surprises » potentielles sur un vrai CDM :

1. **Domaine `Note` (quality)** — `quality/domains/clinical.py` lit
   `cfg["source_value"]` sans garde, or `DOMAIN_CONFIG["Note"]` n'a pas de
   `source_value` → `ValueError`. Crashe sur tout CDM (PG comme Oracle).
2. **Fuite read-only de pool (PG)** — `/cohorts/sql/execute` met la connexion
   psycopg2 en `set_session(readonly=True)` ; `close()` ne réinitialise que
   `statement_timeout`, pas le flag read-only → le consommateur suivant du pool
   (ex. characterization avec ses tables temp) hérite du read-only.
3. **`concept-sets/{id}/resolve` et `/counts`** — font `json.loads(concepts_json)`
   puis itèrent comme une liste, alors que le format stocké est
   `{"concepts":[...], "source_codes":[...]}` (ils n'utilisent pas le helper
   `_parse_payload`) → `TypeError`.

## 6. Harnais de validation

Un vrai PostgreSQL + un mini-OMOP (`backend/tests/fixtures/omop_mini_seed.sql`)
permettent de rejouer le SQL réel des endpoints (`tests/test_integration_omop.py`,
gate `OPAL_ITEST_OMOP_HOST`). Méthode appliquée à chaque module : lancer la suite
**avant** le port (référence PG), porter, relancer → résultat identique. Pour
valider Oracle/SQL Server, brancher le harnais sur une vraie instance (même schéma
OMOP) ; le SQL est généré, il « suffit » de l'exécuter.

⚠️ **Garde-fou régression** : les tests de ces modules sont *mock-based* (curseur
factice renvoyant des données canned) et **ne valident pas le texte SQL**. Réécrire
leurs requêtes ne peut donc PAS être prouvé sans régression sans une vraie instance
PostgreSQL (et Oracle/SQL Server pour le best-effort). Ce port doit se faire
**module par module, chaque module validé sur de vraies bases** avant merge.

Mécanique cible par requête : remplacer la composition `psycopg2.sql.Identifier/SQL`
par des f-strings utilisant `dialect.quote_ident(safe_identifier(x))` pour les
identifiants et `dialect.ilike(...)` / fragments pour le SQL non portable, garder les
paramètres en `%s` et exécuter via `dialect.execute(cur, sql, params)`.

Piste recommandée pour les requêtes analytiques lourdes (cohortes, qualité) :
réutiliser **`SqlRender` (OHDSI)** plutôt qu'une traduction maison.
