# OPAL — OMOP Platform for Analytics & Lineage

Plateforme web de qualite des donnees, construction de cohortes, mapping de vocabulaires et exploration de concepts pour les bases de donnees [OMOP CDM](https://ohdsi.github.io/CommonDataModel/).

---

## Table des matieres

1. [Apercu](#apercu)
2. [Architecture](#architecture)
3. [Demarrage rapide](#demarrage-rapide)
4. [Configuration](#configuration)
5. [Modules fonctionnels](#modules-fonctionnels)
   - [Gestion des CDM](#1-gestion-des-cdm)
   - [Analyse Qualite](#2-analyse-qualite)
   - [Constructeur de Cohortes](#3-constructeur-de-cohortes)
   - [Workflow de Mapping](#4-workflow-de-mapping)
   - [Explorateur de Concepts](#5-explorateur-de-concepts)
   - [Outils OHDSI](#6-outils-ohdsi)
   - [Parametres](#7-parametres)
   - [Audit et Administration](#8-audit-et-administration)
   - [Modules complementaires](#9-modules-complementaires)
6. [Securite et Authentification](#securite-et-authentification)
7. [Internationalisation](#internationalisation)
8. [Developpement](#developpement)
9. [Stack technique](#stack-technique)
10. [Documentation](#documentation)

---

## Apercu

OPAL est une application web autonome qui se connecte a vos bases OMOP CDM existantes pour :

- **Analyser la qualite** des donnees selon 11 domaines (Person, Condition, Drug, Measurement, etc.)
- **Construire des cohortes** de patients via un query builder visuel avec caracterisation Table 1
- **Mapper les vocabulaires** source vers les concepts standard OMOP (6 strategies de suggestion)
- **Explorer les concepts** OMOP avec hierarchie, relations et codes source
- **Executer des outils OHDSI** (Achilles, DQD, CDM Onboarding) avec logs en temps reel
- **Comparer des CDM** et detecter les regressions entre versions
- **Administrer les utilisateurs** via Keycloak avec controle d'acces par role

OPAL fonctionne en **lecture seule** sur vos CDM. La seule ecriture possible (optionnelle, opt-in) concerne la table `source_to_concept_map` lors de l'application des mappings valides.

---

## Architecture

![Architecture OPAL](docs/images/architecture.svg)

| Service | Role | Image |
|---------|------|-------|
| **opal-frontend** | SPA React servie par Nginx, proxy API | `node:20-alpine` → `nginx:alpine` |
| **opal-backend** | API REST FastAPI, moteur d'analyse | `python:3.12-slim` |
| **opal-db** | Base applicative (configs, snapshots, cohortes, decisions) | `postgres:16-alpine` |
| **opal-keycloak** | Authentification OIDC, gestion des roles | `keycloak:24.0` |

Les 4 services communiquent via le reseau Docker interne `opal-network`. Ports exposes : **3000** (frontend), **8080** (Keycloak).

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

# Lancer tous les services
docker compose up -d
```

L'application est accessible sur **http://localhost:3000**.
Keycloak est accessible sur **http://localhost:8080** (admin/admin par defaut).

### Premiers pas

1. Se connecter via Keycloak (ou acceder directement si `AUTH_ENABLED=false`)
2. Acceder a la page **Gestion des CDM** (`/cdm`)
3. Renseigner les coordonnees de connexion PostgreSQL de votre base OMOP
4. Tester la connexion
5. Enregistrer le CDM
6. Selectionner le CDM dans le menu lateral
7. Lancer une analyse qualite, construire une cohorte, explorer les mappings ou les concepts

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
| `KEYCLOAK_URL` | `http://opal-keycloak:8080` | URL interne du serveur Keycloak |
| `KEYCLOAK_REALM` | `opal` | Realm Keycloak |
| `KEYCLOAK_CLIENT_ID` | `opal-frontend` | Client ID Keycloak |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Origines CORS autorisees |
| `OMOP_POOL_MIN_CONN` | `2` | Connexions idle maintenues par pool CDM |
| `OMOP_POOL_MAX_CONN` | `20` | Max connexions simultanees par CDM |
| `OMOP_POOL_IDLE_TIMEOUT` | `1800` | Eviction des pools inactifs (secondes) |
| `APP_DB_POOL_SIZE` | `10` | Taille du pool SQLAlchemy (base app) |
| `APP_DB_MAX_OVERFLOW` | `20` | Connexions supplementaires sous charge |
| `APP_DB_POOL_RECYCLE` | `1800` | Recyclage des connexions app (secondes) |

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

**Route** : `/cdm` | **API** : `/api/cdm/` | **Roles** : admin, data-manager

Enregistrez et gerez les connexions aux bases OMOP CDM externes.

- Formulaire de connexion (hote, port, base, utilisateur, mot de passe, schema OMOP)
- Test de connexion avant enregistrement (affiche le nombre de patients)
- Chiffrement Fernet des mots de passe (AES-128-CBC + HMAC)
- Liste des CDM enregistres avec test de connectivite et suppression
- Configuration du schema OMOP par CDM

> **Note** : `GET /api/cdm/` est accessible a tout utilisateur authentifie (necessaire pour le selecteur CDM du menu lateral).

---

### 2. Analyse Qualite

**Route** : `/quality` | **API** : `/api/quality/` | **Roles** : admin, data-manager, chercheur

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

#### Fonctionnalites transversales

- **Analyse par lot** : lancer tous les domaines en une fois avec progression temps reel (SSE streaming)
- **Historique des snapshots** : chaque analyse cree une nouvelle version, consultable et comparable
- **Export CSV** : chaque tableau de resultats est exportable en CSV
- **Mode comparaison** : comparer deux CDM sur un meme domaine, avec detection d'alertes
- **Rapports** : generation de rapports HTML et PDF (unitaire ou comparaison), bilingue (FR/EN)
- **Timeline** : visualisation de l'historique des analyses

#### Comparateur

Compare deux snapshots et detecte les ecarts significatifs :

- Calcul du % de variation pour chaque metrique
- **Warning** si ecart > seuil (defaut 5%)
- **Critical** si ecart > 2x le seuil (defaut 10%)
- Metriques comparees : total_persons, total_records, pct_terms_mapped, pct_rows_mapped

---

### 3. Constructeur de Cohortes

**Route** : `/cohorts` | **API** : `/api/cohorts/` | **Roles** : admin, data-manager, chercheur, medecin

Query builder visuel pour definir, executer et exporter des cohortes de patients OMOP.

#### Interface en 3 panneaux

| Panneau | Role |
|---------|------|
| **Gauche** — Criteres | Recherche de concepts OMOP, blocs domaine cliquables, filtre par vocabulaire |
| **Centre** — Canvas | Construction visuelle de la requete, caracterisation Table 1, comparaison, editeur SQL |
| **Droite** — Resultats | Comptage, attrition, echantillon, preview SQL, export |

#### Onglets du panneau central

| Onglet | Description |
|--------|-------------|
| **Query Builder** | Construction visuelle des criteres d'inclusion/exclusion avec logique AND/OR |
| **Table 1** | Caracterisation : demographie, prevalence par domaine, mesures, types de visite |
| **Comparer** | Comparaison de deux cohortes avec calcul SMD (Standardized Mean Difference) |
| **SQL Editor** | Execution de requetes SQL en lecture seule avec export CSV |

#### Criteres supportes

**Domaines** : Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death

| Type | Options |
|------|---------|
| **Concepts** | Liste de concept_id + option "inclure descendants" via `concept_ancestor` |
| **Codes source** | Codes source directs (ex: `E11.9`, `FGLF671`) |
| **Temporel** | `any_time`, `absolute_window` (dates fixes), `within_days` (N jours relatifs) |
| **Frequence** | `any`, `at_least N`, `exactly N`, `at_most N` (+ fenetre glissante optionnelle) |
| **Valeur** | Operateurs numeriques (`>`, `<`, `>=`, `<=`, `=`, `between`), unite |
| **Demographie** | Age (min/max), genre, race, ethnicite |

#### Execution

| Action | Description |
|--------|-------------|
| **Compter** | `COUNT(DISTINCT person_id)` sur le SQL genere |
| **Approximation** | Comptage rapide via `TABLESAMPLE` |
| **Attrition** | Comptage incremental a chaque etape (critere par critere) |
| **Echantillon** | 10 patients aleatoires avec demographie |
| **Echantillon detaille** | Patients avec codes cliniques |
| **Parcours patient** | Timeline des evenements cliniques d'un patient |
| **Export CSV** | Liste des patient_id avec demographie |
| **Export SQL** | Requete SQL generee |

#### Versioning

- Chaque sauvegarde avec modification des criteres cree une **nouvelle version**
- Historique complet des versions consultable
- Comptage patient stocke apres execution

---

### 4. Workflow de Mapping

**Route** : `/mapping` | **API** : `/api/mapping/` | **Roles** : admin, data-manager, medecin

Workflow complet de mapping des codes source vers les concepts standard OMOP.

#### 4 onglets

**Dashboard** — Vue d'ensemble :
- Taux de mapping termes et lignes par domaine (barres)
- Volume non mappe par domaine
- Evolution du mapping a travers les versions de snapshots (courbe)
- Performance des strategies de suggestion (taux d'approbation/modification/rejet)

**Exploration des non mappes** — Liste paginee :
- Filtrage par domaine et recherche textuelle
- Statistiques par terme : nombre de records, nombre de personnes
- Export CSV

**Suggestions** — Moteur de suggestion a 6 strategies :

| Strategie | Confiance | Methode |
|-----------|-----------|---------|
| **SapBERT** | Variable | Embeddings semantiques pre-calcules (instantane) |
| **Exact match** | 95% | `concept_code = source_value` avec `standard_concept = 'S'` |
| **Relationships** | 85% | Via `concept_relationship` (`Maps to`) |
| **Keyword** | ≤80% | Recherche progressive par mots-cles AND |
| **Fuzzy** | ≤75% | Similarite trigramme PostgreSQL (`pg_trgm`) ou fallback ILIKE |
| **Contextual** | 40% | Analyse des prefixes dans `source_to_concept_map` existant |

- Suggestion unitaire ou par lot (top N termes non mappes)
- Configuration des strategies activees par domaine
- Approbation en lot par seuil de confiance (≥80%, ≥90%)

**Historique** — Audit complet :
- Historique pagine avec filtres (domaine, action)
- Rollback de decisions individuelles
- Export CSV de l'historique
- Application des mappings : preview d'impact → export STCM CSV ou ecriture CDM (opt-in)

#### Reference et SapBERT

- **Codebooks de reference** : upload de CSV (CCAM, CIM-10…) pour enrichir les descriptions
- **Mappings SapBERT** : upload de resultats pre-calcules pour suggestions instantanees

---

### 5. Explorateur de Concepts

**Route** : `/concepts` | **API** : `/api/concepts/` | **Roles** : admin, data-manager, chercheur, medecin

Navigation et exploration du vocabulaire OMOP.

#### Deux modes de recherche

**Par concept** :
- Recherche par nom, code ou ID
- Filtres : domaine, vocabulaire, concepts standard uniquement
- Affichage : ID, nom, code, domaine, vocabulaire, classe, flag standard
- Compteurs lazy-load (records/personnes) par concept

**Par code source** :
- Recherche dans les tables cliniques par `source_value` et `source_name`
- Visualisation du concept mappe (si existant)
- Export CSV des resultats

#### Panneau de detail

- **Info** : metadonnees completes du concept (synonymes inclus)
- **Relations** : concepts lies avec type de relation (Maps to, Is a, etc.)
- **Hierarchie** : ancetres et descendants via `concept_ancestor` avec niveaux de separation
- **Codes source** : tous les codes source mappes vers ce concept (avec compteurs)

---

### 6. Outils OHDSI

**Route** : `/ohdsi` | **API** : `/api/ohdsi/` | **Roles** : admin, data-manager

Lancement et supervision de conteneurs Docker OHDSI.

| Service | Description |
|---------|-------------|
| **Achilles** | Characterization des donnees |
| **Achilles Export** | Export des resultats Achilles |
| **DQD** | Data Quality Dashboard |
| **CDM Onboarding** | Rapport d'embarquement CDM |

- Configuration : schema resultats, schema vocabulaire, version CDM
- Logs en temps reel via SSE avec auto-reconnexion
- Navigateur de fichiers de sortie avec telechargement
- Statuts : idle, running, done, error

---

### 7. Parametres

**Route** : `/settings` | **API** : `/api/cdm/{name}/settings` | **Roles** : admin, data-manager

Configuration des parametres d'analyse pour chaque CDM :

- Schema OMOP (`omop_cdm` par defaut)
- Nombre de termes non mappes affiches (1–500)
- Nombre de top concepts affiches (1–500)
- Seuil records/personne (10–1000)
- Cap duree d'observation en mois (12–600)
- Seuil d'alerte comparaison en % (0.1–50)

---

### 8. Audit et Administration

#### Journal d'audit

**Route** : `/audit` | **API** : `/api/audit/` | **Roles** : admin

Suivi de toutes les actions utilisateur :
- Filtres : plage de dates, utilisateur, type d'action
- Statistiques : total evenements, utilisateurs actifs, actions par type
- Codes HTTP colores (2xx vert, 4xx orange, 5xx rouge)
- Export CSV

#### Gestion des utilisateurs

**Route** : `/users` | **API** : `/api/admin/` | **Roles** : admin

- Liste des utilisateurs Keycloak avec leurs roles
- Attribution/retrait de roles via l'interface
- Activation/desactivation de comptes
- File d'attente des demandes d'acces avec approbation/rejet
- Creation automatique du compte Keycloak a l'approbation (mot de passe temporaire)

#### Demandes d'acces

**Route** : `/login` (onglet Sign Up) | **API** : `POST /api/access-requests` | **Public**

Formulaire d'inscription en libre-service :
- Champs : nom d'utilisateur, email, prenom, nom, role souhaite
- L'administrateur valide la demande et un compte est cree automatiquement

---

### 9. Modules complementaires

Les modules suivants completent les fonctionnalites principales :

| Module | Route | API | Description |
|--------|-------|-----|-------------|
| **Accueil** | `/` | — | Tableau de bord personnel : notifications, cohortes recentes, actions rapides |
| **Gestion de donnees** | `/data-management` | `/api/datamanagement/` | Monitoring ETL, extraction de donnees, suivi des chargements |
| **Concept Sets** | `/concept-sets` | `/api/concept-sets/` | CRUD de jeux de concepts reutilisables |
| **Incidence** | `/incidence` | `/api/incidence/` | Analyse de taux d'incidence sur cohortes |
| **Estimation** | `/estimation` | `/api/estimation/` | Estimation d'effets populationnels |
| **Controle d'acces CDM** | — | `/api/cdm-access/` | Gestion des permissions utilisateur/groupe par CDM |
| **Notifications** | — | `/api/notifications/` | Notifications in-app (demandes, partages, alertes) |
| **Favoris** | — | `/api/favorites/` | Marquer cohortes, concepts, requetes comme favoris |
| **Requetes sauvegardees** | — | `/api/saved-queries/` | Persistance des requetes SQL personnalisees |
| **Templates de cohortes** | — | `/api/cohort-templates/` | Modeles de criteres de cohortes reutilisables |
| **Partage de cohortes** | — | `/api/cohorts/` | Partage de cohortes entre utilisateurs |
| **Recherche globale** | — | `/api/search/` | Recherche transversale (cohortes, concepts, requetes) |
| **Groupes** | — | `/api/groups/` | Gestion de groupes d'utilisateurs |

---

## Securite et Authentification

### Chiffrement des mots de passe CDM

- **Algorithme** : Fernet (AES-128-CBC + HMAC-SHA256)
- **Cle** : generee au premier demarrage, stockee dans `/app/data/.secret_key` (permissions `0600`)
- **Volume** : le repertoire `data/` est monte via un volume Docker nomme (`opal_data`)

### Authentification Keycloak (OIDC)

- **Protocole** : OpenID Connect avec PKCE (S256)
- **Activation** : `AUTH_ENABLED=true` dans le backend
- **Validation** : JWT valide localement via JWKS (pas de dependance au hostname de l'issuer)
- **Refresh** : token renouvele automatiquement toutes les 30 secondes
- **Desactive par defaut** : tous les utilisateurs sont traites comme admin

### Controle d'acces par role (RBAC)

| Role | Pages accessibles | Description |
|------|-------------------|-------------|
| `admin` | Toutes | Acces complet + administration + audit |
| `data-manager` | Toutes | Data steward, acces complet sans audit |
| `chercheur` | Quality, Cohorts, Concepts | Recherche et analyse |
| `medecin` | Mapping, Cohorts, Concepts | Mapping et analyse |

Le controle s'applique a deux niveaux :
- **Backend** : middleware intercepte chaque requete et verifie le role
- **Frontend** : les elements de menu sont filtres selon le role

### Audit

- Toutes les requetes API sont tracees (utilisateur, methode, chemin, statut, duree)
- Logs stockes par jour, consultables et exportables via l'interface admin

### Recommandations production

| Point | Recommandation |
|-------|----------------|
| `SECRET_KEY` | Generer une cle forte : `openssl rand -hex 32` |
| PostgreSQL opal-db | Changer le mot de passe par defaut (`opal`) |
| HTTPS | Placer un reverse proxy TLS (Traefik, Caddy) devant le port 3000 |
| Authentification | Activer Keycloak (`AUTH_ENABLED=true`) |
| Reseau | Ne pas exposer les ports 8000 et 5432 en production |
| Keycloak | Changer le mot de passe admin par defaut |

---

## Internationalisation

OPAL est disponible en **francais** et **anglais**.

- Changement de langue via le bouton dans le menu lateral
- Persistance du choix dans `localStorage`
- Backend : fichiers JSON `backend/i18n/en.json` et `backend/i18n/fr.json`
- Frontend : i18next + react-i18next, fichiers `frontend/src/i18n/en.json` et `frontend/src/i18n/fr.json`
- Rapports qualite generables dans les deux langues

---

## Developpement

### Structure du projet

```
opal/
├── docker-compose.yml        # Orchestration des services
├── README.md                 # Documentation generale
├── CLAUDE.md                 # Instructions pour Claude Code
├── .env.example              # Template de configuration
│
├── docs/
│   ├── API.md                # Reference API complete (71+ endpoints)
│   ├── TECHNICAL.md          # Documentation technique
│   └── USER_GUIDE.md         # Guide utilisateur
│
├── backend/
│   ├── Dockerfile            # Python 3.12-slim + uvicorn
│   ├── requirements.txt      # Dependances Python
│   ├── main.py               # Point d'entree FastAPI + endpoints systeme (18 routers)
│   ├── config.py             # Variables d'environnement et constantes
│   ├── auth/
│   │   ├── keycloak.py       # Middleware OIDC + RBAC
│   │   └── permissions.py    # Permissions YAML loader
│   ├── permissions.yaml      # Matrice RBAC declarative
│   ├── audit/
│   │   └── logger.py         # Middleware d'audit (trace toutes les requetes)
│   ├── db/
│   │   ├── app_db.py         # Engine SQLAlchemy (base OPAL)
│   │   ├── models.py         # 21 modeles SQLAlchemy
│   │   └── omop_connector.py # Connexion dynamique aux CDM (psycopg2)
│   ├── utils/
│   │   ├── crypto.py         # Chiffrement Fernet
│   │   └── notifications.py  # Systeme de notifications
│   ├── modules/
│   │   ├── cdm_router.py          # CRUD des connexions CDM
│   │   ├── cdm_access_router.py   # Controle d'acces par CDM
│   │   ├── quality/
│   │   │   ├── router.py          # Endpoints analyse qualite + rapports
│   │   │   ├── engine.py          # Orchestration d'analyse
│   │   │   ├── comparator.py      # Comparaison de snapshots
│   │   │   ├── conformity.py      # Conformite des donnees
│   │   │   └── domains/           # SQL par domaine
│   │   │       ├── dashboard.py
│   │   │       ├── person.py
│   │   │       ├── observation_period.py
│   │   │       └── clinical.py
│   │   ├── cohort/
│   │   │   ├── router.py          # CRUD, execution, caracterisation, SQL
│   │   │   ├── sql_builder.py     # JSON -> SQL
│   │   │   ├── characterization.py # Table 1
│   │   │   └── comparison.py      # Comparaison de cohortes (SMD)
│   │   ├── mapping/
│   │   │   ├── router.py          # Workflow de mapping + reference + SapBERT
│   │   │   └── suggest.py         # Moteur de suggestion (6 strategies)
│   │   ├── concept/
│   │   │   └── router.py          # Recherche, hierarchie, codes source
│   │   ├── concept_set/
│   │   │   └── router.py          # Concept sets CRUD
│   │   ├── ohdsi/
│   │   │   └── router.py          # Orchestration Docker OHDSI
│   │   ├── incidence/
│   │   │   └── router.py          # Taux d'incidence
│   │   ├── estimation/
│   │   │   └── router.py          # Estimation populationnelle
│   │   ├── datamanagement/
│   │   │   ├── router.py          # Gestion de donnees / ETL
│   │   │   └── extractor.py       # Extraction de donnees
│   │   ├── notifications_router.py    # Notifications utilisateur
│   │   ├── favorites_router.py        # Favoris utilisateur
│   │   ├── saved_queries_router.py    # Requetes sauvegardees
│   │   ├── cohort_templates_router.py # Templates de cohortes
│   │   ├── cohort_sharing_router.py   # Partage de cohortes
│   │   ├── search_router.py          # Recherche globale
│   │   └── groups_router.py          # Groupes utilisateurs
│   ├── i18n/
│   │   ├── en.json           # Traductions anglais
│   │   └── fr.json           # Traductions francais
│   └── tests/                # 22 fichiers de tests
│       ├── conftest.py       # Fixtures SQLite in-memory
│       ├── test_api.py
│       ├── test_engine.py
│       ├── test_comparator.py
│       ├── test_crypto.py
│       ├── test_cohort_api.py
│       ├── test_mapping_api.py
│       ├── test_suggest.py
│       ├── test_sql_builder.py
│       ├── test_cohort_comparison.py
│       ├── test_cohort_diff.py
│       ├── test_cohort_sharing.py
│       ├── test_cohort_templates.py
│       ├── test_admin_api.py
│       ├── test_audit_api.py
│       ├── test_access_requests.py
│       ├── test_cdm_access.py
│       ├── test_conformity.py
│       ├── test_favorites.py
│       ├── test_groups.py
│       ├── test_notifications.py
│       ├── test_saved_queries.py
│       └── test_search.py
│
├── frontend/
│   ├── Dockerfile            # Node 20 build + Nginx runtime
│   ├── nginx.conf            # SPA routing + proxy API
│   ├── package.json          # Dependances React
│   ├── vite.config.ts        # Build Vite + proxy dev
│   ├── tsconfig.json         # TypeScript strict
│   └── src/
│       ├── main.tsx          # Point d'entree React
│       ├── App.tsx           # Routing et layout (16 pages)
│       ├── opal-theme.css    # Theme Neumorphic Emerald Night
│       ├── auth/
│       │   └── KeycloakContext.tsx  # Contexte auth + RBAC frontend
│       ├── api/
│       │   └── client.ts     # Client Axios (100+ endpoints)
│       ├── types/
│       │   └── index.ts      # Interfaces TypeScript
│       ├── hooks/
│       │   ├── useNotifDots.ts    # Pastilles de notification
│       │   ├── useSessionState.ts # Etat session en memoire
│       │   └── useIsMobile.ts     # Detection mobile
│       ├── i18n/
│       │   ├── index.ts      # Configuration i18next
│       │   ├── en.json       # Traductions anglais
│       │   └── fr.json       # Traductions francais
│       ├── pages/            # 16 pages
│       │   ├── HomePage.tsx
│       │   ├── QualityPage.tsx
│       │   ├── CohortPage.tsx
│       │   ├── DataManagementPage.tsx
│       │   ├── MappingPage.tsx
│       │   ├── ConceptExplorerPage.tsx
│       │   ├── CdmManagementPage.tsx
│       │   ├── SettingsPage.tsx
│       │   ├── OhdsiPage.tsx
│       │   ├── IncidencePage.tsx
│       │   ├── EstimationPage.tsx
│       │   ├── ConceptSetPage.tsx
│       │   ├── AuditPage.tsx
│       │   ├── UserManagementPage.tsx
│       │   ├── LoginPage.tsx
│       │   └── LandingPage.tsx
│       └── components/
│           ├── layout/
│           │   ├── Sidebar.tsx    # Navigation + CDM selector
│           │   └── TopNav.tsx     # Barre superieure + recherche globale
│           ├── ui/                # Composants Neumorphic custom
│           │   ├── Card.tsx
│           │   ├── Checkbox.tsx
│           │   ├── Select.tsx
│           │   └── Tabs.tsx
│           ├── GlobalSearch.tsx   # Recherche globale
│           ├── SqlEditor.tsx      # Editeur SQL (CodeMirror)
│           ├── quality/
│           │   ├── AnalysisResults.tsx
│           │   ├── ComparisonView.tsx
│           │   ├── DomainSelector.tsx
│           │   └── SnapshotTimeline.tsx
│           └── cohort/
│               ├── CriteriaPanel.tsx
│               ├── CriteriaGroupEditor.tsx
│               ├── QueryCanvas.tsx
│               ├── ResultsPanel.tsx
│               ├── CharacterizationPanel.tsx
│               ├── CohortComparisonPanel.tsx
│               └── PatientJourney.tsx
│
├── keycloak/
│   ├── opal-realm.json       # Configuration du realm OPAL
│   └── themes/opal/          # Theme personnalise Keycloak
│
└── scripts/
    ├── sapbert_mapping.py    # Generation des embeddings SapBERT
    ├── scrape_athena_ccam.py # Scraping vocabulaire CCAM depuis Athena
    ├── reload_codebooks.sh   # Chargement des codebooks de reference
    └── setup_keycloak.sh     # Configuration LDAP Keycloak
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

Les tests utilisent une base SQLite en memoire et mockent les connexions OMOP. Aucune base externe requise.

---

## Stack technique

### Backend

| Technologie | Role |
|-------------|------|
| Python 3.12 | Runtime |
| FastAPI | Framework API REST |
| Uvicorn | Serveur ASGI |
| SQLAlchemy 2.x | ORM (base applicative) |
| psycopg2 | Driver PostgreSQL (CDM externes, lecture seule) |
| Pydantic 2.x | Validation des donnees |
| cryptography | Chiffrement Fernet |
| PyJWT | Validation JWT (Keycloak) |

### Frontend

| Technologie | Role |
|-------------|------|
| React 18 | Framework UI |
| TypeScript 5 | Typage statique |
| Vite 5 | Build et dev server |
| Composants Neumorphic custom | Design system (Card, Select, Tabs, Checkbox…) |
| Lucide React | Icones |
| Recharts | Graphiques (barres, courbes, camemberts, aires) |
| CodeMirror 6 | Editeur SQL |
| Axios | Client HTTP |
| i18next | Internationalisation |
| React Router 6 | Routing SPA |
| keycloak-js | Client OpenID Connect |

### Infrastructure

| Technologie | Role |
|-------------|------|
| PostgreSQL 16 | Base applicative |
| Nginx Alpine | Serveur web + reverse proxy |
| Keycloak 24 | Authentification OIDC + gestion des roles |
| Docker Compose | Orchestration |

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/API.md](docs/API.md) | Reference API complete (71+ endpoints) |
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Documentation technique (architecture, modeles, securite) |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Guide utilisateur complet |

---

## Licence

Projet interne AP-HM.
