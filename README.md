# OPAL — OMOP Platform for Analytics & Lineage

Plateforme web de qualité des données, construction de cohortes et mapping de vocabulaires pour les bases de données [OMOP CDM](https://ohdsi.github.io/CommonDataModel/).

---

## Table des matières

1. [Apercu](#apercu)
2. [Architecture](#architecture)
3. [Demarrage rapide](#demarrage-rapide)
4. [Configuration](#configuration)
5. [Modules fonctionnels](#modules-fonctionnels)
   - [Gestion des CDM](#1-gestion-des-cdm)
   - [Analyse Qualite](#2-analyse-qualite)
   - [Constructeur de Cohortes](#3-constructeur-de-cohortes)
   - [Workflow de Mapping](#4-workflow-de-mapping)
   - [Parametres](#5-parametres)
6. [API Reference](#api-reference)
7. [Modele de donnees](#modele-de-donnees)
8. [Securite](#securite)
9. [Internationalisation](#internationalisation)
10. [Developpement](#developpement)
11. [Stack technique](#stack-technique)

---

## Apercu

OPAL est une application web autonome qui se connecte a vos bases OMOP CDM existantes pour :

- **Analyser la qualite** des donnees selon 11 domaines (Person, Condition, Drug, Measurement, etc.)
- **Construire des cohortes** de patients via un query builder visuel
- **Mapper les vocabulaires** source vers les concepts standard OMOP
- **Comparer des CDM** et detecter les regressions entre versions

OPAL fonctionne en **lecture seule** sur vos CDM. La seule ecriture possible (optionnelle, opt-in) concerne la table `source_to_concept_map` lors de l'application des mappings valides.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    docker compose up                         │
│                                                              │
│  ┌────────────────┐         ┌────────────────┐              │
│  │  opal-frontend │  /api/  │  opal-backend  │              │
│  │  React + Nginx │────────>│  FastAPI        │              │
│  │  :3000 -> :80  │         │  :8000          │              │
│  └────────────────┘         └───────┬────────┘              │
│                                     │                        │
│                              ┌──────┴───────┐               │
│                              │   opal-db     │               │
│                              │  PostgreSQL 16│               │
│                              │  :5432        │               │
│                              └──────────────┘               │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                         │
                         │ psycopg2 (lecture seule*)
                         ▼
                ┌──────────────────┐
                │  CDM OMOP        │
                │  (bases externes)│
                │  PostgreSQL      │
                └──────────────────┘
```

| Service | Role | Image |
|---------|------|-------|
| **opal-frontend** | SPA React servie par Nginx, proxy API | `node:20-alpine` → `nginx:alpine` |
| **opal-backend** | API REST FastAPI, moteur d'analyse | `python:3.12-slim` |
| **opal-db** | Base applicative (configs, snapshots, cohortes, decisions) | `postgres:16-alpine` |

Les 3 services communiquent via le reseau Docker interne `opal-network`. Seuls les ports **3000** (frontend) et **8000** (backend, pour debug) sont exposes.

---

## Demarrage rapide

### Prerequis

- Docker et Docker Compose
- Acces reseau vers vos bases PostgreSQL OMOP CDM

### Lancement

```bash
cd opal/

# Generer une cle secrete pour le chiffrement des mots de passe
export SECRET_KEY=$(openssl rand -hex 32)

# Lancer les 3 services
docker compose up -d
```

L'application est accessible sur **http://localhost:3000**.

### Premiers pas

1. Acceder a la page **Gestion des CDM** (`/cdm`)
2. Renseigner les coordonnees de connexion PostgreSQL de votre base OMOP
3. Tester la connexion
4. Enregistrer le CDM
5. Selectionner le CDM dans le menu lateral
6. Lancer une analyse qualite, construire une cohorte, ou explorer les mappings

### Arret

```bash
docker compose down          # Arret (donnees preservees)
docker compose down -v       # Arret + suppression des volumes (reset complet)
```

---

## Configuration

### Variables d'environnement

| Variable | Defaut | Description |
|----------|--------|-------------|
| `DATABASE_URL` | `postgresql://opal:opal@opal-db:5432/opal` | Connexion a la base applicative OPAL |
| `SECRET_KEY` | `change-me-in-production` | Cle pour le chiffrement Fernet des mots de passe CDM |
| `AUTH_ENABLED` | `false` | Activer l'authentification Keycloak OIDC |
| `KEYCLOAK_URL` | `http://keycloak:8080` | URL du serveur Keycloak |
| `KEYCLOAK_REALM` | `opal` | Realm Keycloak |
| `KEYCLOAK_CLIENT_ID` | `opal-frontend` | Client ID Keycloak |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Origines CORS autorisees |

### Parametres d'analyse (par CDM)

Ces parametres sont configurables dans l'interface (page Parametres) pour chaque CDM :

| Parametre | Defaut | Description |
|-----------|--------|-------------|
| `omop_schema` | `omop_cdm` | Schema PostgreSQL contenant les tables OMOP |
| `top_unmapped_terms` | `50` | Nombre de termes non mappes affiches |
| `top_concepts` | `50` | Nombre de top concepts affiches |
| `max_records_per_person` | `100` | Seuil pour la distribution records/personne |
| `max_observation_months` | `120` | Cap pour l'analyse de duree d'observation |
| `comparison_alert_threshold` | `5.0` | Seuil (%) de declenchement des alertes de comparaison |

---

## Modules fonctionnels

### 1. Gestion des CDM

**Route** : `/cdm`

Enregistrez et gerez les connexions aux bases OMOP CDM externes.

**Fonctionnalites** :
- Formulaire de connexion (hote, port, base, utilisateur, mot de passe, schema OMOP)
- Test de connexion avant enregistrement
- Chiffrement Fernet des mots de passe (AES-128-CBC + HMAC)
- Liste des CDM enregistres avec suppression
- Test de connectivite des CDM existants

**Securite** : Les mots de passe ne sont jamais stockes en clair. Ils sont chiffres via Fernet (bibliotheque `cryptography`) avec une cle generee au premier demarrage et stockee avec les permissions `0600`.

---

### 2. Analyse Qualite

**Route** : `/quality`

Moteur d'analyse des donnees type Achilles, execute des requetes SQL sur votre CDM et stocke les resultats sous forme de snapshots versiones.

#### Domaines disponibles (11)

| Domaine | Table OMOP | Analyses |
|---------|------------|----------|
| **Dashboard** | Toutes | Vue agregee : total personnes, records par domaine, taux de mapping |
| **Person** | `person` | Distribution genre, annee de naissance, race, ethnicite |
| **ObservationPeriod** | `observation_period` | Age a la 1ere observation, duree d'observation, observation cumulative et continue |
| **Condition** | `condition_occurrence` | Stats globales, evolution mensuelle, records/personne, top concepts, mapping |
| **Drug** | `drug_exposure` | Idem |
| **Measurement** | `measurement` | Idem |
| **Observation** | `observation` | Idem |
| **Procedure** | `procedure_occurrence` | Idem |
| **Visit** | `visit_occurrence` | Idem |
| **Device** | `device_exposure` | Idem |
| **Death** | `death` | Idem |

#### Analyses par domaine clinique

Pour chaque domaine clinique (Condition, Drug, etc.), l'analyse produit :

1. **Statistiques globales** : total lignes, personnes distinctes, moyenne par personne
2. **Evolution mensuelle** : nombre de records par mois (graphique en courbe)
3. **Distribution records/personne** : combien de patients ont 1, 2, 3… N records
4. **Top N concepts** : concepts les plus frequents (nombre de records et personnes)
5. **Qualite du mapping** :
   - Niveau terme : termes source distincts mappes vs non mappes
   - Niveau ligne : lignes mappees vs non mappees
   - Top termes non mappes classes par frequence

#### Analyse Person

- Distribution par genre (camembert)
- Distribution par annee de naissance (barres)
- Distribution par race (camembert)
- Distribution par ethnicite (camembert)

#### Analyse ObservationPeriod

- Age a la premiere observation (histogramme)
- Age par genre (quantiles p10, p25, mediane, p75, p90)
- Duree d'observation en mois (histogramme)
- Duree par genre (quantiles)
- Observation cumulative (% de personnes avec >= X mois)
- Observation continue par annee calendaire

#### Fonctionnalites transversales

- **Analyse par lot** : lancer tous les domaines en une fois avec barre de progression (SSE streaming)
- **Historique des snapshots** : chaque analyse cree une nouvelle version, consultable et comparable
- **Export CSV** : chaque tableau de resultats est exportable en CSV
- **Mode comparaison** : comparer deux CDM sur un meme domaine, avec detection d'alertes

#### Comparateur

Compare deux snapshots et detecte les ecarts significatifs :

- Calcul du % de variation pour chaque metrique
- **Warning** si ecart > seuil (defaut 5%)
- **Critical** si ecart > 2x le seuil (defaut 10%)
- Metriques comparees : total_persons, total_records, pct_terms_mapped, pct_rows_mapped

---

### 3. Constructeur de Cohortes

**Route** : `/cohorts`

Query builder visuel pour definir, executer et exporter des cohortes de patients OMOP.

#### Interface en 3 panneaux

| Panneau | Role |
|---------|------|
| **Gauche** — Criteres | Recherche de concepts OMOP, blocs domaine cliquables, filtre par vocabulaire |
| **Centre** — Canvas | Construction visuelle de la requete (inclusion/exclusion, demographie) |
| **Droite** — Resultats | Comptage, attrition, echantillon, export |

#### Criteres supportes

**Domaines** : Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death

**Operateurs d'ensemble** :
- Inclusion : AND / OR entre criteres
- Exclusion : EXCEPT (retire les patients du resultat)

**Contraintes par critere** :

| Type | Options |
|------|---------|
| **Concepts** | Liste de concept_id + option "inclure descendants" via `concept_ancestor` |
| **Temporel** | `any_time` (aucune restriction), `absolute_window` (dates fixes), `within_days` (N jours relatifs) |
| **Frequence** | `any`, `at_least N`, `exactly N`, `at_most N` (+ fenetre glissante optionnelle) |
| **Valeur** | Operateurs numeriques (`>`, `<`, `>=`, `<=`, `=`, `between`), concept de valeur, unite |
| **Demographie** | Age (min/max), genre, race, ethnicite |

#### Generation SQL

Les criteres JSON sont traduits en requetes SQL avec CTEs :
- Chaque critere produit un CTE retournant des `person_id`
- Les CTEs sont combines par `INTERSECT` (AND), `UNION` (OR), `EXCEPT` (exclusion)
- Les contraintes demographiques filtrent via la table `person`

#### Execution

| Action | Description |
|--------|-------------|
| **Compter** | `COUNT(DISTINCT person_id)` sur le SQL genere |
| **Approximation** | Comptage rapide via `TABLESAMPLE` |
| **Attrition** | Comptage incremental a chaque etape (critere par critere) |
| **Echantillon** | 10 patients aleatoires avec demographie |
| **Export CSV** | Liste des patient_id |
| **Export SQL** | Requete SQL generee |

#### Versioning

- Chaque sauvegarde avec modification des criteres cree une **nouvelle version**
- Historique complet des versions consultable
- Comptage patient stocke apres execution

---

### 4. Workflow de Mapping

**Route** : `/mapping`

Workflow complet de mapping des codes source vers les concepts standard OMOP, en 5 etapes.

#### Etape 1 — Dashboard

Vue d'ensemble des taux de mapping par domaine :
- Taux de mapping termes et lignes (barres)
- Volume non mappe par domaine
- Evolution du mapping a travers les versions de snapshots (courbe)
- Nombre de decisions prises

#### Etape 2 — Exploration des non mappes

Liste paginee des termes source non mappes (`concept_id = 0`) :
- Filtrage par recherche (ILIKE sur source_value et source_name)
- Pagination (jusqu'a 500 par page)
- Statistiques par terme : nombre de records, nombre de personnes
- Export CSV de tous les termes non mappes

#### Etape 3 — Suggestions automatiques

Moteur de suggestion a 4 strategies, executees en cascade :

| Strategie | Confiance | Methode |
|-----------|-----------|---------|
| **Exact match** | 95% | `concept_code = source_value` avec `standard_concept = 'S'` |
| **Relationships** | 85% | Via `concept_relationship` (`Maps to`) |
| **Fuzzy** | ≤75% | Similarite trigramme PostgreSQL (`pg_trgm`) ou fallback ILIKE |
| **Contextual** | 40% | Analyse des prefixes dans `source_to_concept_map` existant |

- Suggestion unitaire ou par lot (top N termes non mappes)
- Chaque suggestion affiche : concept cible, vocabulaire, score de confiance, source de suggestion

#### Etape 4 — Validation

Workflow de decision pour chaque terme :

| Action | Description |
|--------|-------------|
| **Approuver** | Accepter la suggestion proposee |
| **Modifier** | Choisir un concept cible different |
| **Rejeter** | Marquer comme "pas de mapping" |
| **Approuver en lot** | Approuver tous les termes au-dessus d'un seuil de confiance (80% ou 90%) |

#### Etape 5 — Application

Generation des lignes `source_to_concept_map` a partir des decisions approuvees :

- **Preview** : visualiser l'impact (lignes et personnes affectees) avant d'appliquer
- **Export STCM** : telecharger les mappings au format CSV `source_to_concept_map`
- **Ecriture CDM** (optionnelle) : INSERT/UPSERT dans la table `source_to_concept_map` du CDM
  - Upsert : `ON CONFLICT DO UPDATE` — jamais de suppression
  - Transactionnel avec rollback en cas d'erreur

#### Historique et audit

- Historique pagine de toutes les decisions (filtre par domaine, action)
- **Rollback** : annuler une decision specifique
- Export complet de l'historique en CSV
- Champs traces : source_value, action, concept cible, confiance, source de suggestion, utilisateur, date

---

### 5. Parametres

**Route** : `/settings`

Configuration des parametres d'analyse pour chaque CDM :

- Schema OMOP (`omop_cdm` par defaut)
- Nombre de termes non mappes affiches (1–500)
- Nombre de top concepts affiches (1–500)
- Seuil records/personne (10–1000)
- Cap duree d'observation en mois (12–600)
- Seuil d'alerte comparaison en % (0.1–50)

---

## API Reference

### CDM Management — `/api/cdm`

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/cdm/` | Lister les CDM enregistres |
| `POST` | `/api/cdm/` | Enregistrer un CDM |
| `POST` | `/api/cdm/test` | Tester une connexion (sans sauvegarde) |
| `POST` | `/api/cdm/{name}/test` | Tester un CDM enregistre |
| `PUT` | `/api/cdm/{name}` | Modifier un CDM |
| `DELETE` | `/api/cdm/{name}` | Supprimer un CDM |
| `GET` | `/api/cdm/{name}/settings` | Obtenir les parametres d'analyse |
| `PUT` | `/api/cdm/{name}/settings` | Modifier les parametres d'analyse |

### Quality Analysis — `/api/quality`

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/quality/domains` | Lister les domaines disponibles |
| `POST` | `/api/quality/analyze` | Analyser un domaine |
| `POST` | `/api/quality/analyze/batch` | Analyser plusieurs domaines |
| `POST` | `/api/quality/analyze/batch/stream` | Analyse par lot avec progression SSE |
| `GET` | `/api/quality/snapshots/{cdm}/{domain}` | Lister les snapshots |
| `GET` | `/api/quality/snapshots/{cdm}/{domain}/latest` | Dernier snapshot |
| `GET` | `/api/quality/snapshots/by-id/{id}` | Snapshot par ID |
| `GET` | `/api/quality/export/{snapshot_id}/{table_type}` | Export CSV d'un tableau |
| `POST` | `/api/quality/compare` | Comparer deux CDM/snapshots |

**Types de tableaux exportables** : `top_concepts`, `top_unmapped`, `domain_stats`, `mapping_stats`, `gender`, `birth_year`, `age_by_gender`, `duration_by_gender`

### Cohort Builder — `/api/cohorts`

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/cohorts/concepts/search` | Rechercher des concepts OMOP |
| `GET` | `/api/cohorts/concepts/vocabularies` | Lister les vocabulaires |
| `GET` | `/api/cohorts/domains` | Lister les domaines |
| `GET` | `/api/cohorts/` | Lister les cohortes |
| `POST` | `/api/cohorts/` | Creer une cohorte |
| `GET` | `/api/cohorts/{id}` | Detail d'une cohorte |
| `PUT` | `/api/cohorts/{id}` | Modifier une cohorte |
| `DELETE` | `/api/cohorts/{id}` | Supprimer une cohorte |
| `POST` | `/api/cohorts/count` | Compter les patients |
| `POST` | `/api/cohorts/count/approximate` | Comptage approximatif |
| `POST` | `/api/cohorts/attrition` | Diagramme d'attrition |
| `POST` | `/api/cohorts/sample` | Echantillon de patients |
| `POST` | `/api/cohorts/{id}/execute` | Executer et stocker le comptage |
| `GET` | `/api/cohorts/{id}/export` | Exporter (CSV ou SQL) |

### Mapping Workflow — `/api/mapping`

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/mapping/dashboard/{cdm}` | Taux de mapping par domaine |
| `GET` | `/api/mapping/dashboard/{cdm}/evolution` | Evolution du mapping |
| `GET` | `/api/mapping/unmapped/{cdm}/{domain}` | Termes non mappes (pagine) |
| `GET` | `/api/mapping/unmapped/{cdm}/{domain}/export` | Export CSV des non mappes |
| `POST` | `/api/mapping/suggest` | Suggestion unitaire |
| `POST` | `/api/mapping/suggest/batch` | Suggestions par lot |
| `POST` | `/api/mapping/decide` | Enregistrer une decision |
| `POST` | `/api/mapping/decide/bulk` | Decisions en lot |
| `POST` | `/api/mapping/apply` | Appliquer les mappings |
| `POST` | `/api/mapping/apply/preview` | Preview de l'application |
| `GET` | `/api/mapping/apply/export/{cdm}/{domain}` | Export STCM CSV |
| `GET` | `/api/mapping/history/{cdm}` | Historique des decisions |
| `POST` | `/api/mapping/history/{id}/rollback` | Rollback d'une decision |
| `GET` | `/api/mapping/history/{cdm}/export` | Export historique CSV |

### Autres

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/` | Racine |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/i18n/{lang}` | Traductions (`en` ou `fr`) |

---

## Modele de donnees

### Base applicative OPAL (`opal-db`)

```
┌──────────────────┐     ┌─────────────────────┐
│   cdm_configs    │     │ analysis_snapshots   │
├──────────────────┤     ├─────────────────────┤
│ id (PK)          │     │ id (PK)             │
│ name (unique)    │     │ cdm_name (idx)      │
│ db_host          │     │ domain (idx)        │
│ db_port          │     │ version             │
│ db_name          │     │ results (JSON)      │
│ db_user          │     │ created_at          │
│ db_password_enc  │     └─────────────────────┘
│ omop_schema      │
│ created_at       │     ┌─────────────────────┐
│ updated_at       │     │ analysis_settings   │
└──────────────────┘     ├─────────────────────┤
                         │ id (PK)             │
┌──────────────────┐     │ cdm_name (unique)   │
│    cohorts       │     │ omop_schema         │
├──────────────────┤     │ top_unmapped_terms  │
│ id (PK)          │     │ top_concepts        │
│ cdm_name (idx)   │     │ max_records_pp      │
│ name             │     │ max_obs_months      │
│ description      │     │ alert_threshold     │
│ created_at       │     └─────────────────────┘
│ updated_at       │
└────────┬─────────┘     ┌─────────────────────┐
         │               │ mapping_decisions   │
         │ 1:N           ├─────────────────────┤
         ▼               │ id (PK)             │
┌──────────────────┐     │ cdm_name (idx)      │
│ cohort_versions  │     │ domain (idx)        │
├──────────────────┤     │ source_value        │
│ id (PK)          │     │ source_name         │
│ cohort_id (FK)   │     │ action              │
│ version          │     │ target_concept_id   │
│ criteria_json    │     │ target_concept_name │
│ generated_sql    │     │ target_vocab_id     │
│ patient_count    │     │ previous_concept_id │
│ created_at       │     │ suggestion_source   │
└──────────────────┘     │ confidence_score    │
                         │ user                │
                         │ created_at          │
                         └─────────────────────┘
```

### Initialisation

Les tables sont creees automatiquement au demarrage du backend via `Base.metadata.create_all()`. Pas de systeme de migrations — les tables sont idempotentes.

---

## Securite

### Chiffrement des mots de passe CDM

- **Algorithme** : Fernet (AES-128-CBC + HMAC-SHA256)
- **Cle** : generee au premier demarrage, stockee dans `/app/data/.secret_key` (permissions `0600`)
- **Volume** : le repertoire `data/` est monte via un volume Docker nomme (`opal_data`) pour persister la cle

### Authentification (optionnelle)

- **Protocole** : OpenID Connect via Keycloak
- **Activation** : `AUTH_ENABLED=true`
- **Middleware** : valide le token Bearer via l'endpoint userinfo de Keycloak
- **Desactive par defaut** : tous les utilisateurs sont traites comme admin

### Acces aux CDM

- OPAL se connecte aux CDM avec les identifiants fournis par l'utilisateur
- Les connexions sont ouvertes a la demande et fermees apres chaque requete
- Aucune connexion persistante aux CDM externes

### Recommandations pour la production

| Point | Recommandation |
|-------|----------------|
| `SECRET_KEY` | Generer une cle forte : `openssl rand -hex 32` |
| PostgreSQL opal-db | Changer le mot de passe par defaut (`opal`) |
| HTTPS | Placer un reverse proxy TLS (Traefik, Caddy) devant le port 3000 |
| Authentification | Activer Keycloak (`AUTH_ENABLED=true`) |
| Reseau | Ne pas exposer le port 8000 en production |

---

## Internationalisation

OPAL est disponible en **francais** et **anglais**.

- Changement de langue via le bouton dans le menu lateral
- Persistance du choix dans `localStorage`
- Bibliotheque : i18next + react-i18next
- Fichiers de traduction : `frontend/src/i18n/en.json` et `frontend/src/i18n/fr.json`

---

## Developpement

### Structure du projet

```
opal/
├── docker-compose.yml        # Orchestration des 3 services
├── README.md                 # Cette documentation
│
├── backend/
│   ├── Dockerfile            # Python 3.12-slim + uvicorn
│   ├── requirements.txt      # 8 dependances Python
│   ├── main.py               # Point d'entree FastAPI
│   ├── config.py             # Variables d'environnement et constantes
│   ├── auth/
│   │   └── keycloak.py       # Middleware OIDC optionnel
│   ├── db/
│   │   ├── app_db.py         # Engine SQLAlchemy (base OPAL)
│   │   ├── models.py         # 6 modeles SQLAlchemy
│   │   └── omop_connector.py # Connexion dynamique aux CDM
│   ├── utils/
│   │   └── crypto.py         # Chiffrement Fernet
│   ├── modules/
│   │   ├── cdm_router.py     # CRUD des connexions CDM
│   │   ├── quality/
│   │   │   ├── router.py     # Endpoints analyse qualite
│   │   │   ├── engine.py     # Orchestration d'analyse
│   │   │   ├── comparator.py # Comparaison de snapshots
│   │   │   └── domains/      # SQL par domaine
│   │   │       ├── dashboard.py
│   │   │       ├── person.py
│   │   │       ├── observation_period.py
│   │   │       └── clinical.py
│   │   ├── cohort/
│   │   │   ├── router.py     # CRUD et execution de cohortes
│   │   │   └── sql_builder.py # JSON -> SQL
│   │   └── mapping/
│   │       ├── router.py     # Workflow de mapping
│   │       └── suggest.py    # Moteur de suggestion (4 strategies)
│   └── tests/                # Tests unitaires et d'integration
│       ├── test_api.py
│       ├── test_engine.py
│       ├── test_comparator.py
│       ├── test_crypto.py
│       ├── test_cohort_api.py
│       └── test_mapping_api.py
│
└── frontend/
    ├── Dockerfile            # Node 20 build + Nginx runtime
    ├── nginx.conf            # SPA routing + proxy API
    ├── package.json          # Dependances React
    ├── vite.config.ts        # Build Vite + proxy dev
    ├── tsconfig.json         # TypeScript strict
    └── src/
        ├── main.tsx          # Point d'entree React
        ├── App.tsx           # Routing et layout
        ├── api/
        │   └── client.ts     # Client Axios (45+ endpoints)
        ├── types/
        │   └── index.ts      # Interfaces TypeScript
        ├── i18n/
        │   ├── index.ts      # Configuration i18next
        │   ├── en.json       # Traductions anglais
        │   └── fr.json       # Traductions francais
        ├── pages/
        │   ├── QualityPage.tsx
        │   ├── CohortPage.tsx
        │   ├── MappingPage.tsx
        │   ├── CdmManagementPage.tsx
        │   └── SettingsPage.tsx
        └── components/
            ├── layout/
            │   └── Sidebar.tsx
            ├── quality/
            │   ├── AnalysisResults.tsx
            │   ├── ComparisonView.tsx
            │   └── DomainSelector.tsx
            └── cohort/
                ├── CriteriaPanel.tsx
                ├── QueryCanvas.tsx
                └── ResultsPanel.tsx
```

### Developpement local (sans Docker)

**Backend** :

```bash
cd opal/backend
pip install -r requirements.txt
export DATABASE_URL=postgresql://opal:opal@localhost:5432/opal
uvicorn main:app --reload --port 8000
```

**Frontend** :

```bash
cd opal/frontend
npm install
npm run dev    # http://localhost:5173, proxy API vers :8000
```

### Tests

```bash
cd opal/backend
pip install pytest
pytest tests/ -v
```

Les tests utilisent une base SQLite en memoire et mockent les connexions OMOP.

---

## Stack technique

### Backend

| Technologie | Version | Role |
|-------------|---------|------|
| Python | 3.12 | Runtime |
| FastAPI | ≥0.110 | Framework API REST |
| Uvicorn | ≥0.27 | Serveur ASGI |
| SQLAlchemy | ≥2.0 | ORM (base applicative) |
| psycopg2 | ≥2.9 | Driver PostgreSQL (CDM externes) |
| Pydantic | ≥2.0 | Validation des donnees |
| cryptography | ≥42.0 | Chiffrement Fernet |
| httpx | ≥0.27 | Client HTTP (Keycloak) |

### Frontend

| Technologie | Version | Role |
|-------------|---------|------|
| React | 18.3 | Framework UI |
| TypeScript | 5.3 | Typage statique |
| Vite | 5.1 | Build et dev server |
| Ant Design | 5.15 | Composants UI |
| Recharts | 2.12 | Graphiques (barres, courbes, camemberts, aires) |
| Axios | 1.6 | Client HTTP |
| i18next | 23.10 | Internationalisation |
| React Router | 6.22 | Routing SPA |

### Infrastructure

| Technologie | Version | Role |
|-------------|---------|------|
| PostgreSQL | 16 (Alpine) | Base applicative |
| Nginx | Alpine | Serveur web + reverse proxy |
| Docker Compose | 3.8 | Orchestration |

---

## Licence

Projet interne AP-HM.
