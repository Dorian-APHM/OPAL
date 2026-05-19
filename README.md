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
   - [Notifications temps reel](#10-notifications-temps-reel)
   - [Pathways Analysis](#11-pathways-analysis)
   - [Theme clair](#12-theme-clair)
6. [Securite et Authentification](#securite-et-authentification)
7. [Internationalisation](#internationalisation)
8. [Developpement](#developpement)
9. [Stack technique](#stack-technique)
10. [Documentation](#documentation)

---

## Apercu

OPAL est une application web autonome qui se connecte a vos bases OMOP CDM existantes pour :

- **Analyser la qualite** des donnees selon 14 domaines (Person, Condition, Drug, Measurement, Specimen, Note, etc.)
- **Construire des cohortes** de patients via un query builder visuel avec caracterisation Table 1
- **Mapper les vocabulaires** source vers les concepts standard OMOP (6 strategies de suggestion)
- **Explorer les concepts** OMOP avec hierarchie, relations et codes source
- **Executer des outils OHDSI** (Achilles, DQD, CDM Onboarding) avec logs en temps reel
- **Comparer des CDM** et detecter les regressions entre versions
- **Administrer les utilisateurs** via Keycloak avec controle d'acces par role
- **Recevoir des notifications temps reel** via WebSocket (zero polling)
- **Analyser les parcours de soins** (Pathways Analysis) a la maniere d'ATLAS
- **Basculer entre theme sombre et clair** (palette Creme Sauge)

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

Les 4 services communiquent via le reseau Docker interne `opal-network`. Ports exposes : **3000** (frontend), **8000** (API backend), **8080** (Keycloak).

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

# Definir le mot de passe PostgreSQL (obligatoire)
export POSTGRES_PASSWORD=yourpassword

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
6. Selectionner le CDM dans la barre de navigation superieure (TopNav)
7. **Charger les referentiels de reference** (voir [Bootstrap des referentiels](#bootstrap-des-referentiels) ci-dessous)
8. Lancer une analyse qualite, construire une cohorte, explorer les mappings ou les concepts

### Bootstrap des referentiels

Pour que la recherche par mot-cle en francais fonctionne dans **Concept Explorer** (mode Source value), il faut charger les codebooks FR **avant** de peupler la SourceValueCache. Les labels FR ecrasent les `source_name` du CDM lors de la population — c'est ce qui permet de trouver "tumeur", "diabete", etc.

Trois references actives :

| Fichier (dans le repo) | Cible | Domaine | Usage |
|---|---|---|---|
| `scripts/ccam_fr.csv` | `reference_codebooks` | Procedure | Labels FR CCAM (recherche par mot-cle + mapping) |
| `scripts/cim10_fr.csv` | `reference_codebooks` | Condition | Labels FR CIM-10 (recherche par mot-cle + mapping) |
| `data/sapbert_results.csv` | `sapbert_mappings` | Procedure | Top-5 suggestions SapBERT pre-calculees (mapping auto) |

Le script [scripts/reload_codebooks.sh](scripts/reload_codebooks.sh) fait toute la sequence :

```bash
# Bootstrap codebooks + SapBERT (apres au moins un CDM enregistre)
./scripts/reload_codebooks.sh

# Bootstrap + rebuild de la SourceValueCache pour un CDM specifique
./scripts/reload_codebooks.sh --cdm <nom_cdm>

# Avec auth Keycloak active
AUTH_TOKEN=<token_bearer> ./scripts/reload_codebooks.sh --cdm <nom_cdm>
```

**Ordre critique** : `reload_codebooks.sh` charge les codebooks puis declenche le rebuild du cache. Si tu charges les codebooks **apres** avoir peuple le cache, il faut re-lancer la population (les labels FR ne sont appliques qu'au moment de la population). Le populate est asynchrone (background worker) — poll l'etat :

```bash
curl --noproxy '*' "http://localhost:8000/api/concepts/source-value-cache/status?cdm_name=<nom_cdm>"
```

Chaque domaine est commite independamment : tu peux tester Procedure des qu'il est `done`, meme si Condition est encore `running`.

**Equivalent UI** : page Mapping → "Charger un referentiel" pour les CSV ; page Settings ou Concept Explorer → bouton "Populate source value cache". Resultat identique.

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
| `AUTH_ENABLED` | `true` | Activer l'authentification Keycloak OIDC |
| `KEYCLOAK_URL` | `http://keycloak:8080` | URL interne du serveur Keycloak |
| `KEYCLOAK_REALM` | `opal` | Realm Keycloak |
| `KEYCLOAK_CLIENT_ID` | `opal-frontend` | Client ID Keycloak |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Origines CORS autorisees |
| `OMOP_POOL_MIN_CONN` | `2` | Connexions idle maintenues par pool CDM |
| `OMOP_POOL_MAX_CONN` | `20` | Max connexions simultanees par CDM |
| `OMOP_POOL_IDLE_TIMEOUT` | `1800` | Eviction des pools inactifs (secondes) |
| `APP_DB_POOL_SIZE` | `10` | Taille du pool SQLAlchemy (base app) |
| `APP_DB_MAX_OVERFLOW` | `20` | Connexions supplementaires sous charge |
| `APP_DB_POOL_RECYCLE` | `1800` | Recyclage des connexions app (secondes) |
| `ENVIRONMENT` | `development` | Mode d'execution (`development` ou `production`) |
| `OMOP_STATEMENT_TIMEOUT_MS` | `300000` | Timeout requetes OMOP en millisecondes |
| `MAX_WORKER_THREADS` | `16` | Threads max pour taches background |
| `KEYCLOAK_ISSUER_URL` | *(vide)* | URL issuer Keycloak (si different de `KEYCLOAK_URL`) |

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

> **Note** : `GET /api/cdm/` est accessible a tout utilisateur authentifie (necessaire pour le selecteur CDM de la barre de navigation superieure).

---

### 2. Analyse Qualite

**Route** : `/quality` | **API** : `/api/quality/` | **Roles** : admin, data-manager, chercheur

Moteur d'analyse des donnees type Achilles, execute des requetes SQL sur votre CDM et stocke les resultats sous forme de snapshots versiones.

#### Domaines disponibles (14)

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
| **Specimen** | `specimen` | Idem |
| **Note** | `note` | Idem |
| **Payer_Plan_Period** | `payer_plan_period` | Idem |

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

#### Installation des images OHDSI

Les 4 outils sont construits depuis [ohdsi-tools/](ohdsi-tools/) (Dockerfile + scripts R + packages OHDSI vendores + driver JDBC PostgreSQL). Le repertoire est autonome : aucun telechargement externe au build.

```bash
# Sans proxy
docker compose -f ohdsi-tools/docker-compose.yml build

# Derriere proxy APHM (cntlm sur localhost:3128)
docker compose -f ohdsi-tools/docker-compose.yml build \
  --build-arg HTTP_PROXY=http://localhost:3128 \
  --build-arg HTTPS_PROXY=http://localhost:3128 \
  --build-arg PROXY_CA_HOST=127.0.0.1 \
  --build-arg PROXY_CA_PORT=3128
```

Les images sont nommees `ohdsi-docker-{achilles,achilles-export,dqd,cdmonboarding}` (prefixe par defaut `OHDSI_IMAGE_PREFIX=ohdsi-docker`). Les conteneurs sont lances a la demande par le backend via le socket Docker — voir [ohdsi-tools/README.md](ohdsi-tools/README.md).

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
| **Notifications** | — | `/api/notifications/`, `/api/ws/notifications` | Notifications temps reel via WebSocket |
| **Favoris** | — | `/api/favorites/` | Marquer cohortes, concepts, requetes comme favoris |
| **Requetes sauvegardees** | — | `/api/saved-queries/` | Persistance des requetes SQL personnalisees |
| **Templates de cohortes** | — | `/api/cohort-templates/` | Modeles de criteres de cohortes reutilisables |
| **Partage de cohortes** | — | `/api/cohorts/` | Partage de cohortes entre utilisateurs |
| **Recherche globale** | — | `/api/search/` | Recherche transversale (cohortes, concepts, requetes) |
| **Groupes** | — | `/api/groups/` | Gestion de groupes d'utilisateurs |

---

### 10. Notifications temps reel

**API** : `/api/ws/notifications` (WebSocket) + `/api/notifications/` (REST) | **Roles** : tous

Systeme de notifications entierement temps reel via WebSocket, sans aucun polling.

#### Architecture

```
Client (navigateur)  ──WebSocket──►  Backend (FastAPI)
                                        │
                         ┌──────────────┤
                         ▼              ▼
                    WebSocket       Insert DB
                    Manager         (Notification)
                         │
                         ▼
                   Broadcast vers
                   les connexions
                   de l'utilisateur
```

#### Fonctionnalites

- **Connexion WebSocket authentifiee** via ticket SSE a usage unique (TTL 30s)
- **11 types de notification** : `access_granted`, `access_revoked`, `cdm_created`, `cdm_updated`, `cdm_deleted`, `mapping_applied`, `cohort_deleted`, `cohort_updated`, `group_removed`, `cohort_shared`, `access_request`
- **Declencheurs automatiques** dans tous les modules (CDM, cohortes, mapping, groupes, acces)
- **NotificationCenter** : drawer avec historique complet, filtres, actions en lot
- **Preferences** : mute par type de notification (`GET/POST /api/notifications/preferences`)
- **Nettoyage automatique** : purge des notifications lues > 30 jours
- **Reconnexion automatique** avec backoff exponentiel cote client

---

### 11. Pathways Analysis

**Route** : `/cohorts` (onglet Pathways) | **API** : `/api/cohorts/pathways` | **Roles** : admin, data-manager, chercheur, medecin

Analyse de parcours de soins ("treatment pathways") basee sur la methodologie OHDSI ATLAS.

#### Principe

1. Definir des **event cohorts** (groupes de concepts representant un traitement ou une condition)
2. OPAL collecte les evenements cliniques des patients de la cohorte cible
3. Les evenements sont collapses en **eras** (periodes contigues)
4. Les **sequences** de traitements sont aggregees et visualisees en **sunburst**

#### Parametres

| Parametre | Defaut | Description |
|-----------|--------|-------------|
| `max_depth` | 5 | Profondeur max des parcours (1-10) |
| `min_cell_count` | 5 | Seuil minimum de patients par chemin |
| `combo_window` | 0 | Jours pour fusionner les eras chevauchantes |

#### Interface

- **Event Cohort Builder** : recherche de concepts OMOP, nommage, toggle descendants
- **Sunburst SVG interactif** : arcs concentriques, tooltips, legende couleurs
- **Table des top pathways** : sequences classees par frequence
- **Export CSV** des resultats

---

### 12. Theme clair

OPAL propose un **mode sombre** (defaut) et un **mode clair** (palette Creme Sauge).

#### Activation

- Bouton soleil/lune dans la barre superieure (TopNav)
- Persistance du choix dans `localStorage`
- Transition fluide (0.4s) entre les themes

#### Palette Creme Sauge (mode clair)

| Element | Couleur |
|---------|---------|
| Arriere-plan | `#EDE7D9` (creme chaud) |
| Surfaces | `#E0D9C8` (creme fonce) |
| Accent | `#8FAE6B` (vert sauge) |
| Texte | `#2D3B1E` (vert fonce) |

Toutes les surfaces sont creme — aucun blanc pur. Les ombres neumorphiques sont adaptees au mode clair.

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
- **Active par defaut** : `AUTH_ENABLED=true` — desactiver explicitement avec `AUTH_ENABLED=false` en developpement uniquement

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
- Masquage automatique des parametres sensibles (password, token, ticket)
- Fichiers de logs crees avec permissions `0o640`

### Securite renforcee (v1.2.1)

| Protection | Detail |
|-----------|--------|
| **SQL injection** | Migration complete vers `psycopg2.sql.SQL` + `sql.Identifier` |
| **Path traversal** | Validation `resolve()` + `startswith()` dans le file browser OHDSI |
| **SSRF** | Rejet des hosts CDM locaux, metadata cloud, IPs privees |
| **Rate limiting** | `slowapi` sur endpoints sensibles (inscription, tickets, compute) |
| **IDOR** | Verification d'ownership sur toutes les ressources utilisateur |
| **CSP** | `Content-Security-Policy`, `Strict-Transport-Security`, `Permissions-Policy` |
| **Thread safety** | `threading.Lock` sur tous les dicts de taches partages |
| **GZip** | Compression automatique des reponses (seuil 1000 bytes) |
| **Production guards** | `SECRET_KEY` faible ou `AUTH_ENABLED=false` en prod → crash immediat |

### Recommandations production

| Point | Recommandation |
|-------|----------------|
| `SECRET_KEY` | Generer une cle forte : `openssl rand -hex 32` |
| PostgreSQL opal-db | Changer le mot de passe par defaut (`opal`) |
| HTTPS | Placer un reverse proxy TLS (Traefik, Caddy) devant le port 3000 |
| Authentification | Activer Keycloak (`AUTH_ENABLED=true`) |
| Reseau | Ne pas exposer les ports 8000 et 5432 en production |
| Keycloak | Changer le mot de passe admin par defaut |
| Docker | Utiliser `docker-compose.prod.yml` pour le deploiement production |

### Nouveautes v1.2.1

| Fonctionnalite | Detail |
|----------------|--------|
| **Detection de colonnes optionnelles** | `cdm_helper.py` detecte si `source_name` existe dans la table OMOP avant de l'inclure dans les requetes |
| **Avertissements de mapping** | Les suggestions affichent des warnings (`source_name_missing`, `no_reference_codebook`, etc.) pour guider l'utilisateur |
| **Rate limiting** | `slowapi` applique sur les endpoints couteux (inscription, tickets SSE, compute) |
| **Pool de threads borne** | `MAX_WORKER_THREADS` (defaut 16) limite la concurrence des taches background |
| **Nettoyage des taches en memoire** | Daemon automatique purge les taches terminees pour eviter les fuites memoire |
| **3 nouveaux domaines** | Specimen, Note et Payer_Plan_Period ajoutes a `DOMAIN_CONFIG` |

---

## Internationalisation

OPAL est disponible en **francais** et **anglais**.

- Changement de langue via le bouton dans la barre de navigation superieure (TopNav)
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
├── CHANGELOG.md             # Historique des changements v1.2.1
│
├── docs/
│   ├── API.md                # Reference API complete (80+ endpoints)
│   ├── TECHNICAL.md          # Documentation technique
│   ├── USER_GUIDE.md         # Guide utilisateur
│   ├── METHODOLOGIE.md       # Methodologie des analyses
│   └── WEBSOCKET_NOTIFICATIONS.md  # Documentation WebSocket
│
├── backend/
│   ├── Dockerfile            # Python 3.12-slim + uvicorn
│   ├── requirements.txt      # Dependances Python
│   ├── main.py               # Point d'entree FastAPI + endpoints systeme (19 routers)
│   ├── config.py             # Variables d'environnement et constantes
│   ├── alembic/              # Migrations de schema (Alembic)
│   ├── auth/
│   │   ├── keycloak.py       # Middleware ASGI OIDC + RBAC
│   │   └── permissions.py    # Permissions YAML loader
│   ├── permissions.yaml      # Matrice RBAC declarative
│   ├── audit/
│   │   └── logger.py         # Middleware d'audit (trace toutes les requetes)
│   ├── db/
│   │   ├── app_db.py         # Engine SQLAlchemy (base OPAL)
│   │   ├── models.py         # 22 modeles SQLAlchemy
│   │   └── omop_connector.py # Connexion dynamique aux CDM (psycopg2)
│   ├── utils/
│   │   ├── crypto.py         # Chiffrement Fernet
│   │   ├── notifications.py  # Systeme de notifications
│   │   ├── ws_manager.py     # WebSocket connection manager
│   │   ├── cdm_helper.py     # Helper centralise connexion CDM
│   │   ├── sql_safety.py     # Validation identifiants SQL
│   │   ├── csv_safety.py     # Protection injection CSV
│   │   ├── rate_limit.py     # Decorateur rate limiting
│   │   └── thread_pool.py    # Pool de threads borne (MAX_WORKER_THREADS)
│   ├── modules/
│   │   ├── cdm_router.py          # CRUD des connexions CDM
│   │   ├── cdm_access_router.py   # Controle d'acces par CDM
│   │   ├── quality/
│   │   │   ├── router.py          # Endpoints analyse qualite + rapports
│   │   │   ├── engine.py          # Orchestration d'analyse
│   │   │   ├── comparator.py      # Comparaison de snapshots
│   │   │   ├── conformity.py      # Conformite des donnees
│   │   │   ├── report_builder.py  # Generation de rapports HTML/PDF
│   │   │   └── domains/           # SQL par domaine
│   │   │       ├── dashboard.py
│   │   │       ├── person.py
│   │   │       ├── observation_period.py
│   │   │       └── clinical.py
│   │   ├── admin_router.py        # Administration utilisateurs (extrait de main.py)
│   │   ├── cohort/
│   │   │   ├── router.py          # CRUD, execution, caracterisation, SQL
│   │   │   ├── sql_builder.py     # JSON -> SQL
│   │   │   ├── pathways.py        # Pathways Analysis (parcours de soins)
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
│   └── tests/                # 51 fichiers de tests (601+ tests)
│       ├── conftest.py       # Fixtures SQLite in-memory
│       ├── omop_mock.py      # Mock reutilisable psycopg2
│       ├── README.md         # Documentation architecture de test
│       └── test_*.py         # 49 fichiers de tests (csv_safety, thread_pool, rate_limit, sql_safety, ohdsi_router, etc.)
│
├── frontend/
│   ├── Dockerfile            # Node 20 build + Nginx runtime
│   ├── nginx.conf            # SPA routing + proxy API
│   ├── package.json          # Dependances React
│   ├── vite.config.ts        # Build Vite + proxy dev
│   ├── tsconfig.json         # TypeScript strict
│   └── src/
│       ├── main.tsx          # Point d'entree React
│       ├── App.tsx           # Routing et layout (12 pages routees + 3 non routees)
│       ├── opal-theme.css    # Theme Neumorphic (dark + light Creme Sauge)
│       ├── auth/
│       │   └── KeycloakContext.tsx  # Contexte auth + RBAC frontend
│       ├── api/
│       │   └── client.ts     # Client Axios (100+ endpoints)
│       ├── types/
│       │   └── index.ts      # Interfaces TypeScript
│       ├── theme/
│       │   └── tokens.ts     # Design tokens (couleurs, ombres, dark/light)
│       ├── hooks/
│       │   ├── useNotifDots.ts      # Pastilles de notification (WebSocket)
│       │   ├── useNotificationWs.ts # Hook WebSocket notifications
│       │   ├── useTheme.ts          # Toggle dark/light avec persistance
│       │   ├── useSessionState.ts   # Etat session en memoire
│       │   └── useIsMobile.ts       # Detection mobile
│       ├── i18n/
│       │   ├── index.ts      # Configuration i18next
│       │   ├── en.json       # Traductions anglais
│       │   └── fr.json       # Traductions francais
│       ├── pages/            # 15 fichiers (12 pages routees, 3 non routees : Incidence, Estimation, ConceptSet)
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
│       │   └── LoginPage.tsx
│       └── components/
│           ├── layout/
│           │   ├── Sidebar.tsx    # Navigation + CDM selector
│           │   └── TopNav.tsx     # Barre superieure + recherche + theme + notifs
│           ├── NotificationCenter.tsx  # Drawer notifications temps reel
│           ├── ui/                # Composants Neumorphic custom
│           │   ├── Card.tsx
│           │   ├── Checkbox.tsx
│           │   ├── Select.tsx
│           │   ├── Tabs.tsx
│           │   ├── AnimatedList.tsx     # Animations (FadeIn, ScaleIn, CountUp)
│           │   ├── SkeletonPatterns.tsx # Skeleton loaders contextuels
│           │   ├── ErrorState.tsx       # Etats d'erreur riches
│           │   ├── Empty.tsx            # Etats vides (11 variantes)
│           │   └── Toast.tsx            # Toasts animes
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
│               ├── PathwaysPanel.tsx    # Sunburst parcours de soins
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
    └── setup_keycloak.example.sh  # Modele de configuration LDAP Keycloak
                                    # (copier en setup_keycloak.sh et adapter — voir l'en-tete du script)
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
| slowapi | Rate limiting |
| Alembic | Migrations de schema |

### Frontend

| Technologie | Role |
|-------------|------|
| React 18 | Framework UI |
| TypeScript 5 | Typage statique |
| Vite 5 | Build et dev server |
| Composants Neumorphic custom | Design system (Card, Select, Tabs, Checkbox…) |
| Framer Motion | Micro-animations (listes, transitions, compteurs) |
| Lucide React | Icones |
| Recharts | Graphiques (barres, courbes, camemberts, aires) |
| CodeMirror 6 | Editeur SQL |
| Axios | Client HTTP |
| i18next | Internationalisation |
| React Router 6 | Routing SPA |
| keycloak-js | Client OpenID Connect |
| Vitest + Testing Library | Tests unitaires et composants |

### Infrastructure

| Technologie | Role |
|-------------|------|
| PostgreSQL 16 | Base applicative |
| Nginx Alpine | Serveur web + reverse proxy |
| Keycloak 24 | Authentification OIDC + gestion des roles |
| Docker Compose | Orchestration |

---

### Tests

```bash
# Backend (601 tests)
cd opal/backend
pip install -r requirements-dev.txt
pytest tests/ -v

# Frontend (84 tests)
cd opal/frontend
npm install
npx vitest run
```

Les tests backend utilisent une base SQLite en memoire et un mock psycopg2 (`omop_mock.py`). Aucune base externe requise.

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/API.md](docs/API.md) | Reference API complete (80+ endpoints) |
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Documentation technique (architecture, modeles, securite) |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Guide utilisateur complet |
| [docs/METHODOLOGIE.md](docs/METHODOLOGIE.md) | Methodologie des analyses (qualite, cohortes, mapping) |
| [docs/WEBSOCKET_NOTIFICATIONS.md](docs/WEBSOCKET_NOTIFICATIONS.md) | Architecture WebSocket notifications |
| [CHANGELOG.md](CHANGELOG.md) | Historique detaille des changements v1.2.1 |

---

## Licence

Projet interne AP-HM.
