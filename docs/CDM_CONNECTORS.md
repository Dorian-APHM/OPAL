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

## 4. Étape 3/4 — couche de dialecte (en cours)

Voir `backend/db/dialects/`. Principe : un `Dialect` par moteur fournit le driver,
la fabrique de curseur « rows as dict », le paramstyle et les fragments SQL non
portables (ilike/unaccent, interval, cast, extract, current_date, timeout…). Le
chemin PostgreSQL reste strictement identique à l'existant (mêmes pools psycopg2,
même SQL) pour garantir l'absence de régression de perf.

`CdmConfig.db_type` (nouveau, défaut `postgresql`) sélectionne le dialecte. La page
de configuration des connexions expose le choix du moteur.

## 5. Reste à faire (port analytique)

Le cœur analytique (`cohort/sql_builder.py`, `quality/*`, `incidence`, `estimation`)
génère du SQL PostgreSQL en clair. Sa migration vers les helpers de dialecte est le
gros du travail restant, à faire **module par module** avec validation sur vraie base
Oracle / SQL Server. Piste recommandée : réutiliser `SqlRender` (OHDSI) pour les
requêtes analytiques lourdes plutôt que réécrire une traduction maison.
