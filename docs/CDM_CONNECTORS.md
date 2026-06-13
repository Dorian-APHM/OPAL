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
Exécute le **vrai SQL** des endpoints contre un PostgreSQL OMOP réel (seed
`tests/fixtures/omop_mini_seed.sql`), activé par `OPAL_ITEST_OMOP_HOST`. C'est la
preuve de non-régression : on lance la suite **avant et après** chaque port et on
exige le même résultat. (Hôte = IP non-loopback car l'API bloque loopback/SSRF.)
C'est le garde-fou à réutiliser pour porter les modules restants.

## 5. État du port par module

**FAIT et validé sur vrai PostgreSQL (aucune régression PG)** : `concept/router.py`,
`source_value_cache.py`, `search_router.py`, `mapping/suggest.py`, `mapping/router.py`
(y compris le chemin d'écriture *apply*), `atc_labels.py`, `concept_set/router.py`,
`sapbert_build.py`, `datamanagement/{router,extractor}.py`, `cohort/sql_builder.py`
(clé de voûte cohortes/incidence/estimation/extraction), `cohort/router.py`,
`incidence/engine.py`, `estimation/router.py`, `quality/conformity.py`,
`quality/domains/person.py`, `quality/domains/dashboard.py`.

**RESTE — constructions « dures » (le 20 % structurel annoncé)**, à finir avec un
helper dédié + validation sur vraie base :

| Fichier | Construction non triviale | Piste |
|---|---|---|
| `quality/domains/clinical.py` | `LATERAL` join, `STRING_AGG(DISTINCT … ORDER BY)` | LATERAL→`CROSS APPLY` (MSSQL) ; STRING_AGG→`LISTAGG` (Oracle). Le reste (global/monthly/mapping stats) est fragment-level, trivial. |
| `quality/domains/observation_period.py` | `generate_series(années)`, `AGE()`, `DATE_PART('month', AGE())` | helpers `generate_series` (CTE récursive non-PG), `age_years`, `months_between` |
| `cohort/pathways.py` | tables temporaires (`CREATE TABLE _pw_*`), `ANALYZE`, `CREATE INDEX` anonyme, `INTERVAL` | couche DDL temp-tables par moteur (`SELECT … INTO` MSSQL, `GLOBAL TEMPORARY` Oracle) |
| `cohort/characterization.py` | idem (temp tables, `SAVEPOINT`, `PERCENTILE_CONT`) | idem ; `SAVEPOINT`/`PERCENTILE_CONT` sont déjà portables |

Tous les **helpers de dialecte** nécessaires existent déjà (`date_add/sub`,
`interval_literal`, `date_trunc`, `extract`, `cast`, `least/greatest`,
`count_filter/sum_filter`, `percentile_cont`, `in_list/not_in_list`, `length`,
`list_tables/list_columns`, `stream_cursor`, `execute` avec paramstyle %s/:name/?).
Le port restant est mécanique sauf les 4 constructions ci-dessus (LATERAL,
STRING_AGG, generate_series, temp-tables) qui demandent un helper par moteur.

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
