# OPAL standalone — briques autonomes en Streamlit

> Chaque brique fonctionnelle d'OPAL, exécutable seule, en Python pur : pas de
> Docker, pas de base applicative, pas de Keycloak, pas de gestion
> d'utilisateurs. Un seul fichier de configuration décrit la connexion OMOP,
> ouverte en lecture seule — PostgreSQL, Oracle ou SQL Server.

- **Code** : [`standalone/`](../standalone)
- **Démarrage rapide** : [`standalone/README.md`](../standalone/README.md)
- **Décision d'architecture** : [ADR 0002](adr/0002-standalone-streamlit.md)

---

## Sommaire

1. [À qui ça s'adresse](#1-à-qui-ça-sadresse)
2. [Installation](#2-installation)
3. [Configuration — référence complète](#3-configuration--référence-complète)
4. [Moteurs de base de données](#4-moteurs-de-base-de-données)
5. [Lancer les briques](#5-lancer-les-briques)
6. [Guide des briques](#6-guide-des-briques)
7. [Données locales](#7-données-locales)
8. [Sécurité](#8-sécurité)
9. [Architecture](#9-architecture)
10. [Développer une brique](#10-développer-une-brique)
11. [Tests](#11-tests)
12. [Dépannage](#12-dépannage)
13. [Différences avec l'application complète](#13-différences-avec-lapplication-complète)
14. [FAQ](#14-faq)

---

## 1. À qui ça s'adresse

Le standalone répond à un besoin précis : **analyser un CDM OMOP depuis un poste
de travail, sans rien déployer**. Un data manager, un épidémiologiste ou un
prestataire qui veut une analyse qualité ou une cohorte sur une base OMOP
n'installe pas Docker, PostgreSQL applicatif et Keycloak pour cela.

| Utilisez le standalone si… | Utilisez l'application complète si… |
|---|---|
| vous êtes seul (ou quelques personnes) sur un poste ou un serveur d'analyse | plusieurs utilisateurs partagent la plateforme |
| vous voulez démarrer en 2 minutes, sans droits d'administration | vous avez besoin de comptes, rôles et traçabilité |
| vous explorez / auditez un CDM ponctuellement | vous industrialisez le suivi qualité dans la durée |
| vous n'avez pas de Docker sur la machine | vous voulez partage de cohortes, notifications, audit, OHDSI, assistant IA |

Les deux cohabitent : **les analyses sont les mêmes** (même code, mêmes
requêtes), seule l'enveloppe change.

---

## 2. Installation

### Prérequis

- **Python 3.11 ou plus** (le fichier de configuration est lu avec `tomllib`).
- Un accès réseau en lecture à une base OMOP CDM.
- Une copie du dépôt : les briques importent les moteurs d'analyse de
  `backend/modules/`. Aucune installation du backend n'est nécessaire, seule sa
  présence sur le disque.

### Étapes

```bash
git clone https://github.com/DorianGrousset/OPAL.git
cd OPAL

python -m venv .venv && source .venv/bin/activate    # recommandé
pip install -r standalone/requirements.txt

cp standalone/config.example.toml standalone/config.toml
$EDITOR standalone/config.toml                        # renseignez la connexion OMOP

python standalone/run.py --check                      # vérification de l'install
streamlit run standalone/apps/quality.py              # la brique Qualité, seule
```

`--check` valide la configuration, la présence du pilote, l'accès au CDM et le
fichier de données local, puis sort avec le code 1 si une base est
inaccessible :

```
Configuration   : /opt/OPAL/standalone/config.toml

Base « omop » : postgresql — opal_readonly@db.chu:5432/omop
  Schéma        : omop_cdm
  Pilote        : OK
  Connexion     : OK — PostgreSQL, 39 tables dans « omop_cdm », 812 344 patients

Stockage local  : /opt/OPAL/standalone/data/opal-standalone.db (148 ko)
Résultat        : tout est prêt.
```

### Dépendances

| Paquet | Rôle | Obligatoire |
|---|---|---|
| `streamlit` | interface | oui |
| `pandas` | tableaux et graphiques | oui |
| `psycopg2-binary` | moteur de référence PostgreSQL | oui |
| `plotly` | sunburst des parcours de soins | recommandé (dégradé sans) |
| `oracledb` | CDM Oracle | seulement si `db_type = "oracle"` |
| `pyodbc` | CDM SQL Server | seulement si `db_type = "sqlserver"` |

Ni FastAPI, ni SQLAlchemy, ni cryptography, ni les services compagnons
(Keycloak, SapBERT, OHDSI, LLM) ne sont installés.

---

## 3. Configuration — référence complète

Un seul fichier, `standalone/config.toml`, modelé sur
[`config.example.toml`](../standalone/config.example.toml). Ordre de recherche :

1. le chemin passé à `run.py --config` ;
2. la variable d'environnement `OPAL_STANDALONE_CONFIG` ;
3. `standalone/config.toml`.

### `[omop]` — la connexion (obligatoire)

| Clé | Défaut | Description |
|---|---|---|
| `name` | `"omop"` | nom affiché dans l'interface et clé des données locales |
| `db_type` | `"postgresql"` | moteur : `postgresql`, `oracle` ou `sqlserver` |
| `host` | — | **obligatoire** |
| `port` | selon moteur | 5432 / 1521 / 1433 |
| `database` | — | **obligatoire** — sous Oracle, le *service name* |
| `user` | — | **obligatoire** — idéalement un compte en lecture seule |
| `password` | `""` | laissez vide et exportez `OPAL_OMOP_PASSWORD` |
| `schema` | `"omop_cdm"` | schéma par défaut des tables OMOP |
| `statement_timeout_ms` | `1800000` | garde-fou par requête (30 min) |
| `read_only` | `true` | force la session en lecture seule quand le moteur le permet |

### `[omop.schema_categories]` — un schéma par catégorie (facultatif)

Les déploiements réels rangent parfois le vocabulaire dans un schéma partagé.
Les catégories suivent le CDM v5.4 : `clinical`, `health_system`,
`health_economics`, `derived`, `metadata`, `vocabulary`. Toute catégorie non
renseignée retombe sur `schema`.

```toml
[omop.schema_categories]
vocabulary = "omop_vocabulary"
```

### `[[cdm]]` — bases supplémentaires (facultatif)

Chaque section `[[cdm]]` accepte les mêmes clés que `[omop]`, moteur compris :
une même installation peut donc pointer un PostgreSQL et un Oracle. Un sélecteur
apparaît alors dans la barre latérale, ce qui permet notamment de **comparer
deux CDM** dans la brique Qualité.

```toml
[[cdm]]
name = "omop-2023"
db_type = "oracle"
host = "oracle.chu"
port = 1521
database = "OMOPSVC"
user = "opal_ro"
schema = "omop_cdm"
```

### `[analysis]` — paramètres des analyses qualité

| Clé | Défaut | Effet |
|---|---|---|
| `top_unmapped_terms` | `50` | nombre de termes non mappés remontés par domaine |
| `top_concepts` | `50` | nombre de concepts les plus fréquents par domaine |
| `max_records_per_person` | `100` | plafond de l'histogramme enregistrements/patient |
| `max_observation_months` | `120` | plafond de la durée d'observation (mois) |
| `comparison_alert_threshold` | `5.0` | écart (%) déclenchant une alerte de comparaison |

### `[storage]` et `[ui]`

| Clé | Défaut | Effet |
|---|---|---|
| `storage.path` | `standalone/data` | dossier du fichier SQLite (chemin relatif = relatif au fichier de config) |
| `ui.lang` | `"fr"` | langue des rapports HTML (`fr` ou `en`) |

### Variables d'environnement

| Variable | Effet |
|---|---|
| `OPAL_STANDALONE_CONFIG` | chemin du fichier de configuration |
| `OPAL_OMOP_PASSWORD` | mot de passe (recommandé plutôt que le fichier) |
| `OPAL_OMOP_DB_TYPE` / `_HOST` / `_PORT` / `_DATABASE` / `_USER` / `_SCHEMA` | surchargent la **première** base déclarée |
| `OPAL_BACKEND_DIR` | emplacement du dossier `backend/` si le dépôt est éclaté |

Une erreur de configuration n'est jamais silencieuse : moteur inconnu, clé
obligatoire manquante ou nom de base dupliqué arrêtent le démarrage avec un
message explicite, et l'interface affiche la marche à suivre.

---

## 4. Moteurs de base de données

| Moteur | `db_type` | Port | Pilote | Statut |
|---|---|---|---|---|
| PostgreSQL | `postgresql` | 5432 | inclus | moteur de référence, validé de bout en bout |
| Oracle | `oracle` | 1521 | `pip install oracledb` | best-effort (SQL généré et testé, validation sur instance réelle faite côté serveur) |
| SQL Server | `sqlserver` | 1433 | `pip install pyodbc` + pilote ODBC système | best-effort |

Tout le SQL — celui des moteurs d'analyse réutilisés comme celui propre au
standalone — passe par la couche de dialectes du dépôt
([`backend/db/dialects/`](../backend/db/dialects), voir
[CDM_CONNECTORS.md](CDM_CONNECTORS.md)) : quoting des identifiants, pagination
(`LIMIT` / `FETCH NEXT`), placeholders (`%s` traduits en `:1` / `?`), casts,
arithmétique de dates, recherche insensible à la casse
(`ILIKE` / `LOWER() LIKE LOWER()`), listes d'identifiants (tableau lié sur
PostgreSQL, `IN (…)` découpé en tranches sous la limite Oracle de 1000).

**Spécificités Oracle** : `database` est le *service name* ; les identifiants ne
sont pas quotés, donc un schéma écrit `omop_cdm` dans la configuration résout
l'objet `OMOP_CDM` créé par les DDL OHDSI ; le pilote `oracledb` fonctionne en
mode *thin* (aucun client Oracle à installer).

**Spécificité SQL Server** : `pyodbc` nécessite un pilote ODBC système
(`msodbcsql18`), et le moteur n'a pas de session en lecture seule — utilisez un
compte en lecture seule.

---

## 5. Lancer les briques

Chaque brique est une application Streamlit indépendante :

```bash
streamlit run standalone/apps/quality.py
streamlit run standalone/apps/cohort.py
streamlit run standalone/apps/concepts.py
# … concept_sets, mapping, incidence, estimation, datamanagement, lineage
streamlit run standalone/apps/opal.py          # les neuf briques dans une app
```

Le lanceur `run.py` fait la même chose, avec quelques raccourcis :

```bash
python standalone/run.py --list                 # lister les briques
python standalone/run.py                        # toutes les briques (apps/opal.py)
python standalone/run.py quality                # une brique
python standalone/run.py quality --port 8502    # sur un autre port
python standalone/run.py cohort --config /chemin/config.toml
python standalone/run.py --check                # diagnostic, sans interface
```

Plusieurs briques peuvent tourner **en parallèle** sur des ports différents ;
elles partagent le même fichier de données local (SQLite gère les accès
concurrents en mode WAL).

**Exposer l'application** : Streamlit écoute par défaut sur `localhost`. Il n'y
a **aucune authentification** — ne l'exposez pas telle quelle sur un réseau
ouvert. Sur un serveur d'analyse, passez par un tunnel SSH
(`ssh -L 8501:localhost:8501 serveur`) ou un reverse-proxy qui porte
l'authentification.

---

## 6. Guide des briques

### 6.1 Qualité — `apps/quality.py`

Analyses Achilles-like par domaine, versionnées.

| Onglet | Contenu |
|---|---|
| **Analyse** | sélection des domaines présents dans le CDM, exécution avec barre de progression, puis affichage : Dashboard (volumétrie et % de termes mappés par domaine), Person (genre, années de naissance, race, ethnicité), ObservationPeriod (âge à la première observation, durées, observation cumulée, quantiles par genre), domaines cliniques (volumétrie mensuelle, enregistrements par patient, top concepts, statistiques de mapping, termes non mappés) |
| **Conformité** | contrôles structurels du CDM avec score /100, filtrables par statut, versionnés comme un snapshot `Conformity` |
| **Historique** | tous les snapshots, consultation, export JSON, exports CSV (top concepts, termes non mappés, statistiques par domaine, âge/durée par genre), suppression |
| **Comparaison** | deux snapshots du même domaine (deux dates, ou deux bases), écarts et alertes au-delà du seuil, rapport HTML de comparaison |
| **Rapport** | rapport HTML autoportant à partir des derniers snapshots des domaines choisis |

> Chaque exécution crée une **nouvelle version** de snapshot : relancer une
> analyse n'écrase rien, c'est ce qui permet le suivi dans le temps.

### 6.2 Cohortes — `apps/cohort.py`

| Onglet | Contenu |
|---|---|
| **Définition** | démographie (genre, âge, âge à la date index), critères d'inclusion et d'exclusion (domaine, concepts, codes source, descendants, occurrence, fenêtre de dates, valeur pour les mesures), option « même séjour », import depuis un concept set, édition JSON avancée, SQL généré, enregistrement local |
| **Effectifs & attrition** | comptage des patients, puis effectif après ajout de chaque critère (tableau + graphique + export CSV) |
| **Échantillon** | échantillon détaillé avec les codes ayant déclenché chaque critère ; export complet de la cohorte |
| **Caractérisation** | Table 1 : démographie, prévalence par domaine, mesures, types de séjour, périodes d'observation |
| **Parcours** | parcours de soins façon ATLAS : cohorte cible + évènements, tableau des parcours et diagramme sunburst |
| **Comparaison** | deux cohortes caractérisées, différences standardisées (SMD > 0,1 = déséquilibre) |
| **SQL** | console en lecture seule (`SELECT` / `WITH` / `EXPLAIN`), pré-remplie avec le SQL de la cohorte courante |

> Caractérisation et parcours créent des **tables de travail de session** dans le
> CDM (comme l'application complète) puis les suppriment. Leur connexion est donc
> ouverte sans le verrou lecture seule ; elles n'écrivent jamais dans les tables
> du CDM.

### 6.3 Explorateur de concepts — `apps/concepts.py`

Recherche par nom, code ou `concept_id`, filtres domaine / vocabulaire /
standards, pagination, export CSV. Le détail d'un concept donne ses relations,
ses ancêtres et descendants (`concept_ancestor`) et les **valeurs source** des
tables cliniques qui pointent vers lui.

### 6.4 Concept sets — `apps/concept_sets.py`

Ensembles réutilisables de concepts OMOP **et/ou** de codes source. Résolution
avec descendants, volumétrie par domaine, import/export JSON (les exports de
l'application complète sont acceptés, ancien format liste compris). Un concept
set alimente directement le constructeur de cohortes.

### 6.5 Mapping — `apps/mapping.py`

| Onglet | Contenu |
|---|---|
| **Couverture** | % de termes et de lignes mappés par domaine |
| **Atelier** | termes source non mappés (filtrables), suggestions par les trois stratégies déterministes (code exact, relation « Maps to », ingrédient/forme galénique), acceptation ou rejet, suggestions en lot avec acceptation automatique au-dessus d'un seuil de confiance |
| **Décisions** | décisions enregistrées localement, export CSV et export au format `source_to_concept_map` |

> Les décisions ne sont **jamais écrites dans le CDM** : le standalone produit un
> fichier `source_to_concept_map` que votre équipe ETL applique elle-même.
> Les suggestions SapBERT (service GPU) sont hors périmètre.

### 6.6 Incidence — `apps/incidence.py`

Taux d'incidence et proportion à partir de deux cohortes enregistrées (cible et
évènement) : période à risque, fenêtre d'exclusion antérieure, stratification
(genre, tranche d'âge, année), intervalle de confiance de Poisson, SQL exécuté
visible, enregistrement et historique.

### 6.7 Estimation — `apps/estimation.py`

Courbes de Kaplan-Meier entre une cohorte cible et une cohorte évènement :
unité de temps, limitation de la période à risque, stratification, survie
médiane, test du log-rank, table de survie exportable.

### 6.8 Data management — `apps/datamanagement.py`

Extraction des données brutes d'une cohorte : choix des tables et des colonnes,
aperçu du schéma relationnel (clés et relations OMOP), extraction en flux et
téléchargement d'un **ZIP d'un CSV par table**.

### 6.9 Lineage ETL — `apps/lineage.py`

Documentation ETL HTML transformée en graphe de lignage : graphe interactif
(centrable sur une table), tables, relations, chaînes de remontée vers chaque
table OMOP, export JSON/CSV.

---

## 7. Données locales

Tout ce que vous produisez est conservé dans **un fichier SQLite**
(`standalone/data/opal-standalone.db` par défaut) :

| Table | Contenu |
|---|---|
| `snapshots` | analyses qualité et conformité, versionnées par CDM et domaine |
| `cohorts` | définitions de cohortes + dernière caractérisation / parcours |
| `concept_sets` | concepts et codes source |
| `mapping_decisions` | décisions de mapping (une par valeur source et domaine) |
| `analyses` | analyses d'incidence et d'estimation enregistrées |
| `lineage` | graphe de lignage par CDM |

Aucune colonne de propriétaire : il n'y a pas d'utilisateurs.

- **Sauvegarder / déplacer** : copiez le fichier `.db` (fermez les applications
  d'abord, ou copiez aussi les fichiers `-wal` / `-shm`).
- **Remettre à zéro** : supprimez le fichier, il est recréé au démarrage.
- **Partager** : pointez `storage.path` vers un dossier partagé — SQLite
  supporte plusieurs lecteurs, mais évitez les écritures simultanées intensives.

---

## 8. Sécurité

- **Lecture seule** : la session est forcée en lecture seule quand le moteur le
  permet (`default_transaction_read_only` sur PostgreSQL, appliqué en autocommit
  pour survivre à un rollback ; `SET TRANSACTION READ ONLY` sur Oracle ; SQL
  Server n'a pas d'équivalent). Exception assumée : caractérisation et parcours,
  qui créent des tables de session (§6.2). **Utilisez de toute façon un compte de
  base en lecture seule** : c'est la seule garantie valable sur les trois moteurs.
- **Timeout** : chaque requête est bornée par `statement_timeout_ms`.
- **Injection SQL** : tout identifiant passe par `safe_identifier()` puis le
  quoting du dialecte ; les valeurs sont toujours liées en paramètres.
- **Console SQL** : `SELECT` / `WITH` / `EXPLAIN` uniquement, mots-clés
  d'écriture refusés, nombre de lignes plafonné.
- **Exports CSV** : protection contre l'injection de formules (`=`, `+`, `-`,
  `@` préfixés).
- **Secrets** : `standalone/config.toml` est ignoré par git. Préférez
  `OPAL_OMOP_PASSWORD` au mot de passe en clair ; sinon `chmod 600`.
- **Pas d'authentification** : voir l'avertissement d'exposition réseau au §5.

---

## 9. Architecture

```
standalone/
├── apps/                 un script Streamlit par brique (+ opal.py, le hub)
├── opal_standalone/
│   ├── bootstrap.py      met backend/ sur sys.path et installe les shims
│   ├── shims/            remplacements des 3 modules liés au serveur
│   ├── config.py         lecture et validation de config.toml
│   ├── omop.py           connexions CDM par dialecte (conn.dialect)
│   ├── glue.py           SQL de niveau routeur, routé par dialecte
│   ├── store.py          persistance SQLite
│   ├── diagnostics.py    self-check (run.py --check)
│   ├── ui.py             barre latérale et helpers Streamlit partagés
│   └── views/            une vue par brique
├── tests/                pytest, sans base de données
├── config.example.toml
├── requirements.txt
└── run.py                lanceur + diagnostic
```

### Le principe : réutiliser, ne pas forker

```
apps/quality.py
   └── opal_standalone.views.quality
          ├── opal_standalone.omop      → connexion (porte .dialect)
          ├── opal_standalone.store     → SQLite
          └── backend/modules/quality/  → LE MOTEUR D'ANALYSE, tel quel
                     ├── config, utils.sql_safety, db.dialects   (réels)
                     └── utils.cdm_helper, utils.reference_labels,
                         db.app_db                               (shims)
```

Les moteurs d'analyse de `backend/modules/**` sont volontairement purs : ils
n'importent ni FastAPI ni SQLAlchemy. Trois modules qu'ils touchent sont, eux,
liés au déploiement serveur ; `bootstrap.py` les remplace au moment de l'import :

| Module backend | Remplacement standalone |
|---|---|
| `utils.cdm_helper` | `SchemaMap` (avec le dialecte attaché), détection des colonnes optionnelles via le catalogue du moteur, pas de base applicative ni de FastAPI |
| `utils.reference_labels` | enrichissement des libellés désactivé (les référentiels vivent dans la base applicative) |
| `db.app_db` | session inerte : la persistance passe par SQLite |

Ce que le standalone réimplémente, c'est uniquement la **glue de niveau
routeur** (`glue.py`) : SQL de cohorte datée, SQL Kaplan-Meier, requêtes
vocabulaire, termes non mappés, garde SQL lecture seule, validation des
critères. Le reste — analyses qualité, conformité, constructeur de cohortes,
caractérisation, parcours, incidence, survie, extraction, suggestions de
mapping, parsing du lignage — est **le code du serveur, exécuté tel quel**.

### Invariants à respecter

1. Un moteur de `backend/modules/**` ne doit **jamais** importer FastAPI ou
   SQLAlchemy au niveau module (`tests/test_bootstrap.py` le vérifie).
2. Toute connexion remise à un moteur doit porter `.dialect` ; tout `SchemaMap`
   doit porter `_dialect`.
3. Aucun SQL PostgreSQL-only dans `opal_standalone/` : pas de `psycopg2.sql`,
   `RealDictCursor`, `ILIKE`, `information_schema`, `::cast`
   (`tests/test_engines_multi_dialect.py` le vérifie).
4. `glue.py` doit rester aligné sur les routeurs qu'il reproduit : si un routeur
   change sa logique, la glue suit.

---

## 10. Développer une brique

1. **La vue** : `opal_standalone/views/<brique>.py` exposant `TITLE`, `ICON`,
   `SUBTITLE` et `render(config, cdm, store)`.
2. **Le point d'entrée** : `apps/<brique>.py`, huit lignes qui ajoutent
   `standalone/` au `sys.path`, appellent `ui.page_setup`, `ui.sidebar` puis
   `view.render`.
3. **Le lanceur** : ajoutez la brique au dictionnaire `BRICKS` de `run.py` et à
   `ui.BRICKS` (barre latérale et hub).
4. **Le SQL** : réutilisez un moteur de `backend/modules/**` si possible ; sinon
   écrivez-le dans `glue.py`, en `%s` et via le dialecte.
5. **Les tests** : la vue est automatiquement couverte par `tests/test_apps.py`
   (rendu sur les trois moteurs) dès que le point d'entrée existe ; ajoutez les
   tests de logique dans `tests/test_views.py` ou un fichier dédié.

---

## 11. Tests

```bash
pip install pytest
python -m pytest standalone/tests -q      # 106 tests, aucune base requise
```

| Fichier | Vérifie |
|---|---|
| `test_bootstrap.py` | le pont vers les moteurs, les shims, l'absence de FastAPI/SQLAlchemy |
| `test_config.py` | lecture, validation, moteurs, ports par défaut, surcharges d'environnement |
| `test_store.py` | versionnement des snapshots, CRUD cohortes / concept sets / décisions |
| `test_glue.py` | SQL de cohorte datée, garde SQL lecture seule, validation des critères |
| `test_engines_end_to_end.py` | un moteur d'analyse exécuté sur une connexion simulée |
| `test_engines_multi_dialect.py` | SQL par moteur (pagination, placeholders, dates, listes IN), verrou de session, absence de SQL PostgreSQL-only |
| `test_views.py` | exports CSV, helpers de critères, graphe de lignage |
| `test_apps.py` | chaque application se rend, sur PostgreSQL, Oracle et SQL Server |
| `test_app_flows.py` | aller-retour analyse → snapshot → affichage, comptage de cohorte, formulaire de critères |
| `test_diagnostics.py` | le self-check `run.py --check` |

---

## 12. Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| « Configuration OPAL standalone introuvable » | pas de `config.toml` | `cp standalone/config.example.toml standalone/config.toml` |
| « unsupported db_type » au démarrage | faute de frappe sur `db_type` | valeurs acceptées : `postgresql`, `oracle`, `sqlserver` |
| « Le pilote du moteur `oracle` est absent » | `oracledb` non installé | `pip install oracledb` |
| `ORA-00942: table or view does not exist` | schéma inexistant ou droits manquants | vérifiez `schema` (Oracle résout `omop_cdm` → `OMOP_CDM`) et les droits du compte |
| Connexion refusée / timeout | réseau, port, service name | `python standalone/run.py --check` donne le message exact du pilote |
| « cannot execute CREATE TABLE in a read-only transaction » | compte sans droit de table temporaire | seuls Caractérisation et Parcours en ont besoin ; accordez `TEMP` ou renoncez à ces deux onglets |
| Une analyse tourne très longtemps | volumétrie du CDM | augmentez `statement_timeout_ms`, réduisez `top_concepts` / `top_unmapped_terms` |
| Rapport HTML vide | aucun snapshot pour les domaines choisis | lancez d'abord l'analyse dans l'onglet Analyse |
| Les modifications de `config.toml` ne sont pas prises en compte | configuration mise en cache par Streamlit | bouton « Recharger la configuration » dans la barre latérale |
| `OPAL backend not found` | dépôt éclaté ou dossier `backend/` déplacé | `export OPAL_BACKEND_DIR=/chemin/vers/backend` |

---

## 13. Différences avec l'application complète

| | Application complète | Standalone |
|---|---|---|
| Déploiement | Docker Compose (4 services) | `pip install` + `streamlit run` |
| Interface | React + FastAPI | Streamlit |
| Base applicative | PostgreSQL | SQLite local |
| Authentification | Keycloak, rôles, accès par CDM | aucune |
| Analyses | moteurs `backend/modules/**` | **les mêmes** |
| Moteurs CDM | PostgreSQL / Oracle / SQL Server | idem |
| Valeurs source | cache pré-calculé en base applicative | lues en direct dans le CDM |
| Libellés de référentiels | référentiels importés (CCAM…) | non disponibles |
| Suggestions de mapping | 3 stratégies + SapBERT | les 3 stratégies déterministes |
| Écriture `source_to_concept_map` | possible depuis l'application | export CSV uniquement |
| Hors périmètre | — | partage, groupes, notifications, favoris, audit, outils OHDSI, assistant IA |

---

## 14. FAQ

**Le standalone duplique-t-il le code du serveur ?**
Non. Il importe les mêmes moteurs d'analyse ; seule la glue de niveau routeur
(~500 lignes) est réimplémentée. Une correction dans un moteur bénéficie
immédiatement aux deux.

**Puis-je supprimer le dossier `backend/` ?**
Non : c'est lui qui contient les analyses. En revanche vous pouvez le déplacer
et pointer `OPAL_BACKEND_DIR` dessus.

**Les données du CDM sortent-elles de ma machine ?**
Non. Aucune brique n'émet de requête réseau en dehors de la connexion à votre
CDM. Les exports sont des téléchargements navigateur.

**Puis-je récupérer ensuite mes cohortes dans l'application complète ?**
Les définitions de cohortes et les concept sets sont du JSON au même format ;
l'export JSON d'une brique se réimporte donc dans l'application (concept sets)
ou se recolle dans l'éditeur avancé (cohortes).

**Plusieurs personnes peuvent-elles utiliser la même instance ?**
Techniquement oui (Streamlit sert plusieurs sessions), mais il n'y a ni comptes
ni cloisonnement : tout le monde voit et modifie les mêmes données locales. À
plusieurs, déployez l'application complète.

**Comment mettre à jour ?**
`git pull` puis `pip install -r standalone/requirements.txt`. Le fichier SQLite
et `config.toml` ne sont pas touchés (ils sont ignorés par git).
