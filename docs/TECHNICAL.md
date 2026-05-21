# OPAL — Documentation Technique

Ce document decrit l'architecture interne, les choix de conception, le modele de donnees et les mecanismes de securite d'OPAL.

---

## Table des matieres

1. [Vue d'ensemble de l'architecture](#1-vue-densemble-de-larchitecture)
2. [Backend — FastAPI](#2-backend--fastapi)
3. [Frontend — React](#3-frontend--react)
4. [Modele de donnees](#4-modele-de-donnees)
5. [Securite](#5-securite)
6. [Connexion aux CDM externes](#6-connexion-aux-cdm-externes)
7. [Moteur d'analyse qualite](#7-moteur-danalyse-qualite)
8. [Generateur SQL de cohortes](#8-generateur-sql-de-cohortes)
9. [Moteur de suggestions de mapping](#9-moteur-de-suggestions-de-mapping)
10. [Integration OHDSI](#10-integration-ohdsi)
11. [Notifications temps reel (WebSocket)](#11-notifications-temps-reel-websocket)
12. [Pathways Analysis](#12-pathways-analysis)
13. [Theme et UI](#13-theme-et-ui)
14. [Audit et tracabilite](#14-audit-et-tracabilite)
15. [Infrastructure Docker](#15-infrastructure-docker)
16. [Tests](#16-tests)
17. [Deploiement en production](#17-deploiement-en-production)

---

## 1. Vue d'ensemble de l'architecture

### Topologie des services

![Architecture OPAL](images/architecture.svg)

### Principes architecturaux

- **Separation stricte** : la base applicative (`opal-db`) et les CDM externes sont deux mondes distincts
- **Lecture seule** : les CDM sont accedes en lecture seule via `psycopg2` brut (pas d'ORM)
- **Pool de connexions** : chaque CDM dispose d'un `ThreadedConnectionPool` psycopg2 (min=2, max=20 par defaut, configurable via env vars)
- **Versioning** : snapshots d'analyse et versions de cohortes sont immuables
- **Chiffrement** : mots de passe CDM chiffres Fernet au repos

---

## 2. Backend — FastAPI

### Point d'entree (`main.py`)

Le fichier `main.py` configure l'application FastAPI :

1. Creation de la base de donnees (tables via `Base.metadata.create_all()`)
2. Enregistrement du middleware CORS
3. Enregistrement conditionnel du middleware Keycloak (`AUTH_ENABLED`)
4. Enregistrement du middleware d'audit
5. Inclusion des 19 routers de modules
6. Endpoints systeme directs (health, i18n, auth)
7. GZip middleware (compression > 1000 bytes)

### Organisation des modules

```
backend/
├── main.py                    # App FastAPI + endpoints systeme (19 routers)
├── config.py                  # Configuration (env vars + DOMAIN_CONFIG)
├── alembic/                   # Migrations de schema (Alembic)
│   └── versions/              # Fichiers de migration
├── auth/
│   ├── keycloak.py            # Middleware ASGI OIDC + RBAC
│   └── permissions.py         # Permissions YAML loader
├── permissions.yaml           # Matrice RBAC declarative
├── audit/
│   └── logger.py              # Middleware d'audit (masquage params sensibles)
├── db/
│   ├── app_db.py              # SQLAlchemy engine + session factory
│   ├── models.py              # 22 modeles ORM (+ NotificationPreference)
│   └── omop_connector.py      # Pool de connexions psycopg2 aux CDM
├── utils/
│   ├── crypto.py              # Chiffrement/dechiffrement Fernet
│   ├── notifications.py       # Systeme de notifications (DB + WebSocket push)
│   ├── ws_manager.py          # WebSocket connection manager
│   ├── cdm_helper.py          # Helper centralise connexion CDM
│   ├── sql_safety.py          # Validation identifiants SQL (safe_identifier)
│   ├── csv_safety.py          # Protection injection formules CSV
│   └── rate_limit.py          # Decorateur rate limiting
├── modules/
│   ├── admin_router.py        # /api/admin/ (extrait de main.py)
│   ├── cdm_router.py          # /api/cdm/
│   ├── cdm_access_router.py   # /api/cdm-access/
│   ├── quality/
│   │   ├── router.py          # /api/quality/
│   │   ├── engine.py          # Orchestration des analyses
│   │   ├── comparator.py      # Comparaison inter-CDM
│   │   ├── report_builder.py  # Generation rapports HTML/PDF
│   │   ├── conformity.py      # Conformite des donnees
│   │   └── domains/           # SQL par domaine
│   ├── cohort/
│   │   ├── router.py          # /api/cohorts/
│   │   ├── sql_builder.py     # JSON criteres -> SQL
│   │   ├── pathways.py        # Pathways Analysis (parcours de soins)
│   │   ├── characterization.py # Table 1
│   │   └── comparison.py      # Comparaison SMD
│   ├── mapping/
│   │   ├── router.py          # /api/mapping/
│   │   └── suggest.py         # 6 strategies de suggestion
│   ├── concept/
│   │   └── router.py          # /api/concepts/
│   ├── concept_set/
│   │   └── router.py          # /api/concept-sets/
│   ├── ohdsi/
│   │   └── router.py          # /api/ohdsi/
│   ├── incidence/
│   │   └── router.py          # /api/incidence/
│   ├── estimation/
│   │   └── router.py          # /api/estimation/
│   ├── datamanagement/
│   │   ├── router.py          # /api/datamanagement/
│   │   └── extractor.py       # Extraction de donnees
│   ├── notifications_router.py    # /api/notifications/ + /api/ws/notifications
│   ├── favorites_router.py        # /api/favorites/
│   ├── saved_queries_router.py    # /api/saved-queries/
│   ├── cohort_templates_router.py # /api/cohort-templates/
│   ├── cohort_sharing_router.py   # /api/cohorts/ (partage)
│   ├── search_router.py          # /api/search/
│   └── groups_router.py          # /api/groups/
├── i18n/
│   ├── en.json                # Traductions EN (cache au demarrage)
│   └── fr.json                # Traductions FR (cache au demarrage)
└── tests/                     # 51 fichiers de tests (601 tests)
```

### Configuration (`config.py`)

Toute la configuration provient de variables d'environnement avec des valeurs par defaut :

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://opal:opal@opal-db:5432/opal")
SECRET_KEY = os.getenv("SECRET_KEY", "")          # REQUIRED — generate with: openssl rand -hex 32
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")  # "development" ou "production"
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "...")    # Internal Docker URL (backend → Keycloak)
KEYCLOAK_ISSUER_URL = os.getenv("KEYCLOAK_ISSUER_URL", KEYCLOAK_URL)  # Public URL (browser → Keycloak)
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "opal-frontend")
OMOP_STATEMENT_TIMEOUT_MS = int(os.getenv("OMOP_STATEMENT_TIMEOUT_MS", "300000"))  # 5 min
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", "16"))
```

> **Note** : `KEYCLOAK_ISSUER_URL` doit correspondre a l'URL par laquelle les navigateurs accedent a Keycloak (ex: `http://myserver:8080`). Elle sert a verifier le champ `iss` des tokens JWT. `KEYCLOAK_URL` est l'URL interne Docker utilisee par le backend.

Le dictionnaire `DOMAIN_CONFIG` mappe chaque domaine OMOP a sa table et ses colonnes :

```python
DOMAIN_CONFIG = {
    "Condition": {
        "table": "condition_occurrence",
        "concept_id": "condition_concept_id",
        "source_value": "condition_source_value",
        "date_col": "condition_start_date",
    },
    # ... 11 domaines cliniques :
    # Condition, Drug, Measurement, Observation, Procedure,
    # Visit, Device, Death, Specimen, Note, Payer_Plan_Period
}
```

### Couche base de donnees

#### Base applicative (`db/app_db.py`)

- SQLAlchemy 2.x avec sessions synchrones
- Engine cree au demarrage, sessions via `SessionLocal()`
- Dependency injection FastAPI via `get_db()` (yield pattern)
- Tables creees automatiquement au boot (`create_all()`)

#### Connecteur OMOP (`db/omop_connector.py`)

- Connexions `psycopg2` pures (pas d'ORM)
- **Pool de connexions** par CDM (`ThreadedConnectionPool`, min=2, max=20)
- Pool identifie par `host:port/dbname@user`, cree a la premiere requete
- `conn.close()` remet la connexion au pool (wrapper `PooledConnection` transparent)
- `rollback()` automatique au retour au pool pour nettoyer l'etat de session
- Pool invalide automatiquement si le mot de passe CDM change
- Eviction des pools inactifs >30min (thread daemon)
- Fermeture propre de tous les pools au shutdown FastAPI
- `test_omop_connection()` reste en connexion directe (pas de pool)

```python
# Le wrapper PooledConnection est transparent pour les routers :
conn = get_omop_connection(host, port, dbname, user, password)
try:
    cur = conn.cursor()
    cur.execute("SELECT ...")
finally:
    conn.close()  # remet au pool au lieu de fermer
```

Configuration via variables d'environnement :

| Variable | Defaut | Description |
|----------|--------|-------------|
| `OMOP_POOL_MIN_CONN` | `2` | Connexions idle maintenues par CDM |
| `OMOP_POOL_MAX_CONN` | `20` | Maximum de connexions simultanees par CDM |
| `OMOP_POOL_IDLE_TIMEOUT` | `1800` | Secondes avant eviction d'un pool inactif |
| `OMOP_STATEMENT_TIMEOUT_MS` | `300000` | Timeout par requete SQL en millisecondes (5 min) |

#### Helper CDM centralise (`utils/cdm_helper.py`)

Module utilitaire qui evite de dupliquer la logique connexion CDM dans 5+ routers :

- **`get_cdm_connection(db, cdm_name)`** : lookup du CDM en base, dechiffrement du mot de passe, checkout d'une connexion poolee, resolution du schema (via `AnalysisSettings` ou fallback `DEFAULT_OMOP_SCHEMA`). Retourne `(connection, validated_schema)`. Leve `HTTPException 404` si CDM introuvable.
- **`get_domain_config(conn, schema, domain)`** : retourne la configuration `DOMAIN_CONFIG` pour un domaine en verifiant a l'execution que les colonnes optionnelles (ex: `source_name` = `drug_source_name`, `measurement_source_name`) existent reellement dans le CDM. Si une colonne optionnelle est absente, elle est retiree du dictionnaire retourne. Utilise un cache `(dsn, schema, table, column)` pour eviter les requetes `information_schema` repetees.
- **`check_cdm_access(request, cdm_name)`** : verifie que l'utilisateur courant a acces au CDM. Utile pour les endpoints POST qui recoivent `cdm_name` dans le body JSON (invisible au middleware Keycloak). Ne fait rien si `AUTH_ENABLED=false`. Leve `HTTPException 403` si acces refuse.

---

## 3. Frontend — React

### Stack technique

| Bibliotheque | Role |
|--------------|------|
| React 18 | UI framework (hooks, context) |
| TypeScript 5 | Typage statique |
| Vite 5 | Build / dev server (HMR) |
| Tailwind CSS 4 | Utilitaires CSS (via `@tailwindcss/vite`) |
| Composants Neumorphic custom | Design system (Card, Select, Tabs, Checkbox) |
| Framer Motion | Micro-animations (listes, transitions, compteurs) |
| Lucide React | Icones |
| CodeMirror 6 | Editeur SQL |
| Recharts | Visualisations (Bar, Line, Pie, Area) |
| Axios | Client HTTP |
| React Router 6 | Routing SPA |
| i18next | Internationalisation (FR/EN) |
| keycloak-js | Client OIDC |
| Vitest + Testing Library | Tests unitaires et composants (84 tests) |

### Architecture

```
src/
├── main.tsx                   # Point d'entree React
├── App.tsx                    # Router + Layout + Theme
├── auth/
│   └── KeycloakContext.tsx    # Provider auth (OIDC + RBAC)
├── api/
│   └── client.ts             # Client Axios organise par module
├── types/
│   └── index.ts              # Interfaces TypeScript partagees
├── hooks/                     # Hooks custom
│   ├── useNotifDots.ts        # Pastilles notification (WebSocket)
│   ├── useNotificationWs.ts   # Hook WebSocket notifications
│   ├── useTheme.ts            # Toggle dark/light + persistance
│   ├── useSessionState.ts     # Etat session en memoire
│   └── useIsMobile.ts         # Detection mobile
├── theme/
│   └── tokens.ts              # Design tokens (couleurs, ombres, dark/light)
├── i18n/                      # Traductions
├── pages/                     # 12 pages routees (+ 3 fichiers non routes)
└── components/                # Composants reutilisables
    ├── layout/                # TopNav, Sidebar
    ├── NotificationCenter.tsx # Drawer notifications temps reel
    ├── ui/                    # Composants Neumorphic + animations + skeletons
    ├── quality/               # Composants analyse qualite
    └── cohort/                # Composants cohorte (+ PathwaysPanel.tsx)
```

### Client API (`api/client.ts`)

Le client Axios est organise en objets par module :

```typescript
export const qualityApi = {
  getDomains: () => axios.get('/api/quality/domains'),
  analyze: (data) => axios.post('/api/quality/analyze', data),
  // ...
};
```

Un intercepteur injecte automatiquement le Bearer token Keycloak sur chaque requete.

Pour les endpoints SSE et les telechargements, des helpers `authFetch()` et `getAuthToken()` sont fournis.

### Contexte d'authentification (`auth/KeycloakContext.tsx`)

Le `AuthProvider` encapsule toute l'application et fournit :

- `authenticated` : etat de connexion
- `username`, `roles` : informations utilisateur
- `hasPageAccess(path)` : verification RBAC cote frontend
- `login()`, `logout()` : redirections Keycloak

La matrice des permissions frontend est synchronisee avec le backend :

```typescript
const ROLE_PAGE_ACCESS: Record<OpalRole, string[] | null> = {
  admin: null,           // toutes les pages
  'data-manager': null,
  chercheur: ['/quality', '/cohorts', '/concepts'],
  medecin: ['/mapping', '/cohorts', '/concepts'],
};
```

### Theme et style

- Design system **Neumorphic** entierement custom (pas de framework UI externe)
- Composants UI dans `components/ui/` : Card, Select, Tabs, Checkbox avec effets neumorphiques
- Theme CSS dans `opal-theme.css` (couleur primaire : `#2bc459`)
- **Deux modes** : sombre (Emerald Night, defaut) et clair (Creme Sauge `#EDE7D9`)
- Toggle dans TopNav avec persistance `localStorage`, transition fluide 0.4s
- Anti-flash : script dans `index.html` applique le theme avant le premier paint
- Design responsive (sidebar collapsible, drawers mobiles)
- **Micro-animations** : AnimatedList, FadeIn, ScaleIn, CountUp (Framer Motion)
- **Skeleton loaders** contextuels : CardSkeleton, TableSkeleton, DashboardSkeleton
- **Etats d'erreur riches** : 5 variantes avec detection automatique
- **Etats vides** : 11 variantes predefinies avec animations
- **Toast** : animations spring, countdown progress bar

---

## 4. Modele de donnees

### Schema de la base applicative

```
┌──────────────────────┐     ┌─────────────────────────┐
│   cdm_configs        │     │ analysis_snapshots       │
├──────────────────────┤     ├─────────────────────────┤
│ id         PK serial │     │ id         PK serial     │
│ name       unique     │     │ cdm_name   idx           │
│ db_host    varchar    │     │ domain     idx           │
│ db_port    int        │     │ version    int           │
│ db_name    varchar    │     │ results    JSON          │
│ db_user    varchar    │     │ created_at timestamp     │
│ db_password_enc text  │     └─────────────────────────┘
│ omop_schema varchar   │
│ created_at timestamp  │     ┌─────────────────────────┐
│ updated_at timestamp  │     │ analysis_settings       │
└──────────────────────┘     ├─────────────────────────┤
                              │ id         PK serial     │
┌──────────────────────┐     │ cdm_name   unique        │
│    cohorts           │     │ omop_schema varchar      │
├──────────────────────┤     │ top_unmapped_terms int   │
│ id         PK serial │     │ top_concepts int         │
│ cdm_name   idx       │     │ max_records_per_person   │
│ name       varchar   │     │ max_observation_months   │
│ description text     │     │ comparison_alert_thresh  │
│ created_by varchar   │     └─────────────────────────┘
│ shared_with_all int  │
│ created_at timestamp │
│ updated_at timestamp │
└────────┬─────────────┘     ┌─────────────────────────┐
         │                    │ mapping_decisions       │
         │ 1:N                ├─────────────────────────┤
         ▼                    │ id         PK serial     │
┌──────────────────────┐     │ cdm_name   idx           │
│ cohort_versions      │     │ domain     idx           │
├──────────────────────┤     │ source_value varchar     │
│ id         PK serial │     │ source_name varchar      │
│ cohort_id  FK        │     │ action     varchar       │
│ version    int       │     │ target_concept_id int    │
│ criteria_json JSON   │     │ target_concept_name      │
│ generated_sql text   │     │ target_vocabulary_id     │
│ patient_count int    │     │ previous_concept_id int  │
│ characterization JSON│     │ suggestion_source        │
│ characterized_at     │     │ confidence_score float   │
│ created_at timestamp │     │ user       varchar       │
└──────────────────────┘     │ reason     text          │
                              │ created_at timestamp     │
┌──────────────────────┐     └─────────────────────────┘
│ reference_codebooks  │
├──────────────────────┤     ┌─────────────────────────┐
│ id         PK serial │     │ sapbert_mappings        │
│ name       varchar   │     ├─────────────────────────┤
│ domain     varchar   │     │ id         PK serial     │
│ code       varchar   │     │ domain     varchar       │
│ description text     │     │ source_code varchar      │
│ uploaded_at timestamp│     │ source_name varchar      │
└──────────────────────┘     │ rank       int           │
                              │ target_concept_id int    │
                              │ target_concept_code      │
                              │ target_concept_name      │
                              │ target_vocabulary_id     │
                              │ similarity float         │
                              │ uploaded_at timestamp    │
                              └─────────────────────────┘

┌──────────────────────┐     ┌───────────────────────────┐
│   concept_sets       │     │ incidence_analyses         │
├──────────────────────┤     ├───────────────────────────┤
│ id         PK serial │     │ id              PK serial  │
│ cdm_name   idx       │     │ cdm_name        idx        │
│ name       varchar   │     │ name            varchar    │
│ domain     varchar   │     │ target_cohort_id int       │
│ description text     │     │ outcome_cohort_id int      │
│ concepts_json text   │     │ parameters_json text       │
│ created_by varchar   │     │ results_json    text       │
│ created_at timestamp │     │ created_at      timestamp  │
└──────────────────────┘     └───────────────────────────┘

┌───────────────────────────┐     ┌─────────────────────────┐
│ estimation_analyses       │     │ cdm_access               │
├───────────────────────────┤     ├─────────────────────────┤
│ id              PK serial │     │ id         PK serial     │
│ cdm_name        idx       │     │ cdm_name   idx           │
│ name            varchar   │     │ username   idx           │
│ analysis_type   varchar   │     │ granted_by varchar       │
│ target_cohort_id int      │     │ created_at timestamp     │
│ outcome_cohort_id int     │     └─────────────────────────┘
│ parameters_json text      │
│ results_json    text      │
│ created_at      timestamp │
└───────────────────────────┘

┌──────────────────────┐     ┌─────────────────────────┐
│ cdm_group_access     │     │ user_favorites           │
├──────────────────────┤     ├─────────────────────────┤
│ id         PK serial │     │ id         PK serial     │
│ cdm_name   idx       │     │ username   idx           │
│ group_name idx       │     │ item_type  varchar       │
│ granted_by varchar   │     │ item_id    varchar       │
│ created_at timestamp │     │ item_label varchar       │
└──────────────────────┘     │ item_meta  JSON          │
                              │ created_at timestamp     │
                              └─────────────────────────┘

                              ┌─────────────────────────┐
                              │ saved_queries            │
┌──────────────────────┐     ├─────────────────────────┤
│ notifications        │     │ id         PK serial     │
├──────────────────────┤     │ cdm_name   idx           │
│ id         PK serial │     │ name       varchar       │
│ username   idx       │     │ sql        text          │
│ type       varchar   │     │ description text         │
│ title      varchar   │     │ created_by varchar       │
│ message    text      │     │ created_at timestamp     │
│ link       varchar   │     │ updated_at timestamp     │
│ item_id    varchar   │     └─────────────────────────┘
│ read       boolean   │
│ target_role varchar  │     ┌─────────────────────────┐
│ created_at timestamp │     │ cohort_templates         │
└──────────────────────┘     ├─────────────────────────┤
                              │ id         PK serial     │
┌──────────────────────┐     │ name       varchar       │
│ cohort_shares        │     │ category   varchar       │
├──────────────────────┤     │ description text         │
│ id         PK serial │     │ criteria_json JSON       │
│ cohort_id  FK        │     │ author     varchar       │
│ share_type varchar   │     │ created_at timestamp     │
│ share_target varchar │     └─────────────────────────┘
│ shared_by  varchar   │
│ created_at timestamp │     ┌─────────────────────────┐
└──────────────────────┘     │ user_groups              │
                              ├─────────────────────────┤
                              │ id         PK serial     │
┌──────────────────────┐     │ name       unique        │
│ user_group_members   │     │ description text         │
├──────────────────────┤     │ created_by varchar       │
│ id         PK serial │     │ created_at timestamp     │
│ group_name varchar   │     └─────────────────────────┘
│ username   varchar   │
│ added_by   varchar   │     ┌─────────────────────────┐
│ created_at timestamp │     │ access_requests          │
└──────────────────────┘     ├─────────────────────────┤
                              │ id         PK serial     │
                              │ username   varchar       │
                              │ email      varchar       │
                              │ first_name varchar       │
                              │ last_name  varchar       │
                              │ requested_role varchar   │
                              │ status     varchar       │
                              │ reviewed_by varchar      │
                              │ reviewed_at timestamp    │
                              │ created_at timestamp     │
                              └─────────────────────────┘
```

### Index composites et contraintes

| Table | Index / Contrainte | Colonnes |
|-------|-------------------|----------|
| `analysis_snapshots` | Index composite | `(cdm_name, domain)` |
| `analysis_snapshots` | Index composite | `(cdm_name, domain, version)` |
| `analysis_snapshots` | UniqueConstraint | `(cdm_name, domain, version)` |
| `cohort_versions` | Index composite | `(cohort_id, version)` |
| `cohort_versions` | UniqueConstraint | `(cohort_id, version)` |
| `mapping_decisions` | Index composite | `(cdm_name, domain)` |
| `mapping_decisions` | Index composite | `(cdm_name, domain, source_value)` |
| `notifications` | Index composite | `(username, read)` |

```
┌──────────────────────────┐
│ notification_preferences │
├──────────────────────────┤
│ id         PK serial     │
│ username   idx           │
│ notif_type varchar       │
│ enabled    boolean       │
│ updated_at timestamp     │
└──────────────────────────┘
```

### Conventions

- Migrations gerees via **Alembic** (migration initiale : 22 tables + index)
- Les resultats d'analyse sont stockes en JSON dans `analysis_snapshots.results`
- Les criteres de cohorte sont stockes en JSON dans `cohort_versions.criteria_json`
- Index composites sur les colonnes frequemment filtrees ensemble (voir tableau ci-dessus)
- Contrainte d'unicite sur `cdm_configs.name` et `analysis_settings.cdm_name`

### Tables OMOP accedees (lecture seule)

| Table | Usage |
|-------|-------|
| `person` | Demographie, comptages |
| `observation_period` | Periodes d'observation |
| `condition_occurrence` | Diagnostics |
| `drug_exposure` | Medicaments |
| `measurement` | Mesures biologiques |
| `observation` | Observations |
| `procedure_occurrence` | Actes medicaux |
| `visit_occurrence` | Visites/sejours |
| `device_exposure` | Dispositifs medicaux |
| `death` | Deces |
| `concept` | Vocabulaire OMOP |
| `concept_relationship` | Relations entre concepts |
| `concept_ancestor` | Hierarchie des concepts |
| `concept_synonym` | Synonymes |
| `vocabulary` | Vocabulaires |
| `source_to_concept_map` | Mappings source (lecture + ecriture optionnelle) |

---

## 5. Securite

### Chiffrement des mots de passe CDM

**Algorithme** : Fernet (symmetric, AES-128-CBC + HMAC-SHA256)

**Flux** :
1. Au premier demarrage, si `/app/data/.secret_key` n'existe pas, une cle Fernet est generee
2. Le fichier est cree avec les permissions `0600` (owner read/write uniquement)
3. La variable `SECRET_KEY` peut aussi etre fournie via l'environnement
4. A chaque enregistrement de CDM, le mot de passe est chiffre avant stockage
5. A chaque connexion CDM, le mot de passe est dechiffre en memoire

```python
# crypto.py
from cryptography.fernet import Fernet

def encrypt_password(password: str) -> str:
    f = Fernet(get_key())
    return f.encrypt(password.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    f = Fernet(get_key())
    return f.decrypt(encrypted.encode()).decode()
```

### Mode d'authentification

Le comportement depend des variables `ENVIRONMENT` et `AUTH_ENABLED` :

| `ENVIRONMENT` | `AUTH_ENABLED` | Comportement |
|---|---|---|
| `development` | `false` | Acces total sans login (warning en log a chaque requete, username = `dev-user`) |
| `development` | `true` | Authentification Keycloak normale |
| `production` | `true` | Authentification Keycloak normale |
| `production` | `false` | **Refus de demarrer** (RuntimeError) |

> En production, il est impossible de desactiver l'authentification. Le backend refuse de demarrer si `AUTH_ENABLED=false` et `ENVIRONMENT=production`.

### Authentification Keycloak

**Protocole** : OpenID Connect avec PKCE (S256)

**Architecture** :
- Le frontend utilise `keycloak-js` pour le flux OIDC
- Le backend valide les JWT localement via JWKS (pas d'appel reseau a chaque requete)

**Validation du token** :
```python
expected_issuer = f"{KEYCLOAK_ISSUER_URL}/realms/{KEYCLOAK_REALM}"
payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    audience=KEYCLOAK_CLIENT_ID,       # verify aud = "opal-frontend"
    issuer=expected_issuer,            # verify iss = public Keycloak URL
    options={
        "verify_iss": True,
        "verify_exp": True,
        "verify_aud": True,
    },
)
```

> Le mismatch Docker/browser pour l'issuer est resolu par `KEYCLOAK_ISSUER_URL` (URL publique) distincte de `KEYCLOAK_URL` (URL interne Docker). L'audience est injectee dans les tokens via un `oidc-audience-mapper` configure dans le client Keycloak.

### Tickets SSE (connexions EventSource)

L'API `EventSource` du navigateur ne supporte pas les headers custom (`Authorization`). Pour les endpoints SSE (ex: logs OHDSI en streaming), un systeme de **tickets a usage unique** est utilise :

1. Le frontend appelle `POST /api/auth/sse-ticket` (authentifie via Bearer token)
2. Le backend genere un ticket UUID valide **30 secondes**, stocke en memoire
3. Le frontend ouvre `new EventSource('/api/ohdsi/logs/service?ticket=<ticket>')`
4. Le middleware consomme le ticket (usage unique) et restaure l'identite utilisateur
5. Toute reutilisation du meme ticket retourne 401

> Ce mecanisme evite de transmettre le JWT dans l'URL, ou il serait visible dans les logs serveur, l'historique navigateur et les headers Referer.

### RBAC (Role-Based Access Control)

Le middleware intercepte chaque requete et applique la logique suivante :

1. **Public paths** (`/api/health`, `/api/i18n`, `/api/access-requests`, `/docs`) : pas de verification
2. **Auth-only paths** (`/api/auth`) : token valide suffit, pas de verification de role
3. **Read paths** (`GET /api/cdm/`) : tout utilisateur authentifie
4. **Role-restricted paths** : verification via `ROLE_ROUTE_ACCESS`

```python
ROLE_ROUTE_ACCESS = {
    "admin": None,       # None = acces a tout
    "data-manager": None,
    "chercheur": ["/api/quality", "/api/cohorts", "/api/concepts", "/api/i18n", "/api/health"],
    "medecin": ["/api/mapping", "/api/cohorts", "/api/concepts", "/api/i18n", "/api/health"],
}
```

### Mots de passe temporaires (creation d'utilisateurs)

Lorsqu'un administrateur cree un utilisateur (approbation de demande d'acces ou ajout direct), le backend genere un **mot de passe aleatoire** de 22 caracteres (`secrets.token_urlsafe(16)`) :

- Le mot de passe est marque `"temporary": true` dans Keycloak → l'utilisateur devra le changer a sa premiere connexion
- Le mot de passe aleatoire est retourne **une seule fois** dans la reponse API (`temporary_password`) pour que l'admin puisse le communiquer a l'utilisateur
- En mode LDAP (`KEYCLOAK_LDAP_ENABLED=true`), aucun mot de passe n'est genere car l'authentification est deleguee au LDAP

> **Securite** : les mots de passe temporaires ne sont jamais derives du nom d'utilisateur ni d'informations previsibles.

### Defense en profondeur (endpoint-level role checks)

En plus du middleware qui filtre les routes via `permissions.yaml`, chaque endpoint sensible verifie les roles au niveau du code (defense en profondeur) :

| Endpoints | Verification | Roles autorises |
|---|---|---|
| `/api/admin/*` (users, roles, access-requests) | `_require_admin()` | admin uniquement |
| `/api/audit/*` (logs, stats, export) | `_require_admin()` | admin uniquement |
| `/api/cdm-access/grant`, `/revoke`, `/grant-group`, `/revoke-group` | `_require_manage_access()` | roles avec `can_manage_access: true` (admin, data-manager) |
| `/api/cdm-access/cdm/{name}` (clear all) | `_require_clear_all()` | roles avec `can_clear_all_grants: true` (admin) |
| `/api/groups` (POST, PUT, DELETE, members) | `require_roles("admin", "data-manager")` | admin, data-manager |
| `/api/groups` (GET) | aucune restriction | tous les utilisateurs authentifies |

> Meme si le middleware est contourne ou mal configure, les endpoints refusent les appels non autorises avec une **403 Forbidden**.

### Protection contre les injections SQL

- Toutes les requetes SQL vers les CDM utilisent `psycopg2.sql.SQL` + `sql.Identifier` pour les identifiants (schema, table, colonne) — plus aucune f-string SQL
- Les parametres de valeur utilisent des placeholders `%s` avec binding psycopg2
- `safe_identifier()` (`utils/sql_safety.py`) valide les identifiants contre `^[A-Za-z_][A-Za-z0-9_]*$` avec une limite de 63 caracteres (limite PostgreSQL) en defense supplementaire
- L'editeur SQL du constructeur de cohortes n'accepte que `SELECT`, `WITH` et `EXPLAIN`
- Les noms de schema et tables sont valides contre `DOMAIN_CONFIG`
- Protection ILIKE : les wildcards (`%`, `_`) dans les recherches sont echappes

### Protection SSRF

- Les hosts CDM sont valides lors de l'enregistrement : rejet de localhost, IPs privees/link-local/multicast, metadata cloud (`169.254.169.254`, `metadata.google.internal`)
- Resolution DNS des hostnames avec verification de l'IP resolue

### Protection IDOR

- Verification d'ownership sur toutes les ressources utilisateur (notifications, saved queries, concept sets, cohort templates, cohorts)
- Les non-admin ne voient que leurs propres groupes

### Rate limiting

`slowapi` avec limites par endpoint (desactive en mode test `TESTING=1`) :

| Endpoint | Limite | Module |
|----------|--------|--------|
| `POST /api/quality/analyze` | 3/min | quality/router |
| `POST /api/quality/analyze-batch-stream` | 2/min | quality/router |
| `POST /api/quality/conformity` | 3/min | quality/router |
| `POST /api/cdm/test-connection` | 5/min | cdm_router |
| `POST /api/cdm/{name}/test` | 5/min | cdm_router |
| `POST /api/cohorts/execute-sql` | 10/min | cohort/router |
| `POST /api/cohorts/characterize` | 3/min | cohort/router |
| `POST /api/cohorts/pathways` | 3/min | cohort/router |
| `POST /api/mapping/suggest-batch` | 3/min | mapping/router |
| `POST /api/incidence/compute` | 3/min | incidence/router |
| `POST /api/estimation/kaplan-meier` | 3/min | estimation/router |
| `POST /api/datamanagement/extract` | 3/min | datamanagement/router |
| `POST /api/access-requests` | 5/min | admin_router |
| `POST /api/auth/sse-ticket` | 10/min | main |

---

## 6. Connexion aux CDM externes

### Architecture de connexion

```
Requete API
    │
    ▼
Router (FastAPI)
    │
    ├── Recupere CdmConfig depuis opal-db (SQLAlchemy)
    │
    ├── Dechiffre le mot de passe (Fernet)
    │
    ├── Checkout connexion depuis le pool CDM
    │   - Pool cree a la 1ere requete (ThreadedConnectionPool)
    │   - connect_timeout=10, statement_timeout=5min
    │   - rollback() au checkout pour etat propre
    │
    ├── Execute la requete SQL
    │
    └── conn.close() → retour au pool (pas de fermeture reelle)
```

### Caracteristiques

- **Pool de connexions par CDM** : `ThreadedConnectionPool` (min=2, max=20, configurable)
- **Wrapper transparent** : `PooledConnection` intercepte `close()` pour faire un `putconn()`
- **Invalidation** : pool ferme et recree si mot de passe CDM change ou CDM supprime
- **Eviction** : pools inactifs >30min fermes automatiquement (thread daemon)
- **Lecture seule** : transactions read-only sauf pour l'ecriture STCM
- **Timeout** : 10 secondes de connexion, 5 minutes par requete
- **Isolation** : chaque CDM a ses propres identifiants et son propre pool

### Ecriture dans le CDM (opt-in)

La seule ecriture autorisee concerne `source_to_concept_map` lors de l'application des mappings :

```sql
INSERT INTO {schema}.source_to_concept_map
  (source_code, source_concept_id, source_vocabulary_id, ...)
VALUES (%s, %s, %s, ...)
ON CONFLICT (source_code, source_vocabulary_id, target_concept_id)
DO UPDATE SET ...
```

L'operation est transactionnelle avec rollback automatique en cas d'erreur.

---

## 7. Moteur d'analyse qualite

### Architecture

```
POST /api/quality/analyze
    │
    ▼
router.py ──> engine.py ──> domains/{domain}.py
                                │
                                ├── dashboard.py   (requetes agregees multi-tables)
                                ├── person.py      (demographie)
                                ├── observation_period.py  (periodes d'observation)
                                └── clinical.py    (domaines cliniques generiques)
```

### Flux d'analyse

1. Le router recoit le CDM et le domaine
2. `engine.py` orchestre l'execution des requetes SQL
3. Le module domaine genere les requetes SQL adaptees
4. Les resultats sont structures en JSON et sauvegardes comme snapshot versionne
5. Le versioning est automatique : `MAX(version) + 1` pour le couple `(cdm_name, domain)`

### Optimisations SQL

- **Dashboard** : stats de base + mapping fusionnees en 1 seule requete par domaine (4 agregats dans un seul scan)
- **Domaines cliniques** : `COUNT(*)` et `COUNT(DISTINCT)` separes en 2 requetes pour profiter des index-only scans ; `STRING_AGG` des source_values limitee a 10 via `LATERAL` subquery ; stats mapping (terms + rows) calculees en 1 seul scan avec 4 agregats conditionnels
- **Observation Period** : CTE `per` (MIN/MAX dates par patient) factorisee en fragment SQL reutilise dans les 6 analyses ; observation cumulative calculee via fenetre `SUM() OVER (ORDER BY m DESC)` au lieu d'une sous-requete correlee O(N * cap_months)
- **Conformite** : checks par table clinique fusionnes en 1 requete avec `COUNT(*) FILTER (WHERE ...)` au lieu de 4 scans separes

### Metriques par domaine clinique

Chaque domaine clinique produit :

| Metrique | SQL | Description |
|----------|-----|-------------|
| `global.total_rows` | `COUNT(*)` | Nombre total de lignes |
| `global.distinct_persons` | `COUNT(DISTINCT person_id)` | Personnes distinctes |
| `global.avg_per_person` | `AVG(count)` | Moyenne lignes/personne |
| `monthly_trend` | `GROUP BY DATE_TRUNC('month', date_col)` | Evolution mensuelle |
| `records_per_person` | Distribution de `COUNT(*) GROUP BY person_id` | Histogramme |
| `top_concepts` | `GROUP BY concept_id ORDER BY COUNT(*) DESC` | Top N concepts |
| `mapping.terms` | `COUNT(DISTINCT source_value) WHERE concept_id = 0` | Termes non mappes |
| `mapping.rows` | `COUNT(*) WHERE concept_id = 0` | Lignes non mappees |

### Comparateur (`comparator.py`)

Compare deux snapshots et genere des alertes :

```python
def compare(results_a, results_b, threshold=5.0):
    diffs = []
    for metric in ["total_records", "pct_terms_mapped", ...]:
        val_a = extract(results_a, metric)
        val_b = extract(results_b, metric)
        pct = ((val_b - val_a) / val_a) * 100
        severity = "critical" if abs(pct) > threshold * 2 else "warning" if abs(pct) > threshold else None
        diffs.append({"metric": metric, "diff_pct": pct, "severity": severity})
    return diffs
```

### Rapports

Les rapports HTML/PDF sont generes cote backend :
- Template HTML inline avec CSS et graphiques
- Conversion PDF via `weasyprint` ou similaire
- Bilingue (FR/EN) avec les traductions i18n

---

## 8. Generateur SQL de cohortes

### Architecture (`sql_builder.py`)

Le generateur traduit une structure JSON de criteres en requete SQL avec CTEs.

### Structure d'entree

```json
{
  "inclusion": {
    "criteria": [
      {
        "id": "c1",
        "domain": "Condition",
        "concepts": [{"concept_id": 201826}],
        "include_descendants": true,
        "temporal": {"type": "any_time"},
        "occurrence": {"type": "at_least", "count": 2},
        "operatorWithNext": "AND"
      }
    ]
  },
  "exclusion": { "criteria": [...] },
  "demographics": {
    "age": {"min": 18, "max": 65},
    "gender": ["FEMALE"]
  }
}
```

### Logique de generation

1. **Chaque critere** genere un CTE retournant des `person_id` :

```sql
cte_c1 AS (
  SELECT DISTINCT co.person_id
  FROM {schema}.condition_occurrence co
  JOIN {schema}.concept_ancestor ca
    ON co.condition_concept_id = ca.descendant_concept_id
  WHERE ca.ancestor_concept_id IN (201826)
  GROUP BY co.person_id
  HAVING COUNT(*) >= 2
)
```

2. **Combinaison** : les criteres consecutifs en `OR` sont groupes en `UNION`, les groupes `AND` sont combines par `INTERSECT`

3. **Exclusion** : les criteres d'exclusion sont combines puis soustraits via `EXCEPT`

4. **Demographie** : filtre via `JOIN person` (age calcule, genre, race, ethnicite)

5. **Contraintes temporelles** :
   - `any_time` : pas de filtre date
   - `absolute_window` : `date_col BETWEEN start AND end`
   - `within_days` : `date_col >= CURRENT_DATE - N`

6. **Contraintes de valeur** (Measurement) :
   - `value_as_number > 140` ou `BETWEEN 90 AND 140`

### Sortie

La requete finale est un `SELECT DISTINCT person_id FROM ...` combinant tous les CTEs.

### Optimisations

- **Occurrence fenêtree** : la contrainte `N events within X days` utilise une window function `COUNT(*) OVER (PARTITION BY person_id ORDER BY event_date RANGE BETWEEN CURRENT ROW AND INTERVAL 'X days' FOLLOWING)` au lieu d'une sous-requete correlee O(N²)
- **Liste des cohortes** : les dernieres versions sont chargees en 1 seule requete (subquery JOIN sur `MAX(version)`) au lieu de N+1

---

## 9. Moteur de suggestions de mapping

### Architecture (`suggest.py`)

Le moteur execute les strategies SapBERT (pre-calcule) puis 5 strategies SQL en cascade et retourne les meilleures suggestions classees par confiance.

### Strategies

#### 1. SapBERT (pre-calcule)

```python
# Lookup instantane dans sapbert_mappings
results = db.query(SapbertMapping).filter_by(
    domain=domain, source_code=source_value
).order_by(SapbertMapping.rank).limit(5)
```

- Score de confiance = `similarity * 100`
- Ignore les strategies SQL si SapBERT a des resultats

#### 2. Exact Match

```sql
SELECT * FROM {schema}.concept
WHERE (concept_code = %s OR LOWER(concept_name) = LOWER(%s))
  AND standard_concept = 'S'
  AND domain_id = %s
```

- Confiance : 95%

#### 3. Relationship-based

```sql
SELECT c2.* FROM {schema}.concept c1
JOIN {schema}.concept_relationship cr ON c1.concept_id = cr.concept_id_1
JOIN {schema}.concept c2 ON cr.concept_id_2 = c2.concept_id
WHERE c1.concept_code = %s
  AND cr.relationship_id = 'Maps to'
  AND c2.standard_concept = 'S'
```

- Confiance : 85%

#### 4. Ingredient / DCI Match (pont francais→anglais)

Extrait le principe actif (DCI/INN) du `source_name` francais (ex: `"HYDROXYZINE 25 MG CPR (ATARAX)"` → ingredient `HYDROXYZINE`, dosage `25 MG`, forme `CPR`) puis recherche dans `concept_name` et `concept_synonym` :

- Correction DCI francais→anglais via dictionnaire (`IBUPROFENE` → `IBUPROFEN`, `AMOXICILLINE` → `AMOXICILLIN`, etc.) + regle generique (`-INE` → `-IN`)
- Extraction du dosage et de la forme galenique (CPR→Oral Tablet, INJ→Injectable, etc.) pour prioriser la bonne formulation
- Recherche en cascade : ingredient + dosage, puis ingredient seul, puis synonymes
- Confiance : 70-80%

#### 5. Fuzzy (trigrammes) + Keyword (recherche progressive)

**Fuzzy** :
```sql
-- Utilise pg_trgm si disponible
SELECT *, similarity(concept_name, %s) AS sim
FROM {schema}.concept
WHERE concept_name % %s
  AND standard_concept = 'S'
ORDER BY sim DESC
LIMIT 5
```

- Confiance : `similarity * 75`
- Fallback sur `ILIKE '%term%'` si `pg_trgm` n'est pas installe

**Keyword** :
```sql
-- Essaie d'abord tous les mots, puis retire un mot a chaque iteration
SELECT * FROM {schema}.concept
WHERE concept_name ILIKE ALL(ARRAY['%mot1%', '%mot2%', '%mot3%'])
  AND standard_concept = 'S'
  AND domain_id = %s
```

- Confiance : decroissante (80% → 60%)

#### 6. Contextual

Analyse les mappings existants dans `source_to_concept_map` pour trouver des patterns :

```sql
SELECT target_concept_id, COUNT(*) as freq
FROM {schema}.source_to_concept_map
WHERE source_vocabulary_id = %s
  AND source_code LIKE %s  -- prefixe commun
GROUP BY target_concept_id
ORDER BY freq DESC
```

- Confiance : 40%

### Reference codebooks

Les codebooks de reference enrichissent les descriptions des codes source. Lors d'une suggestion, si un codebook est charge pour le domaine, la description du code est ajoutee au `source_name` pour ameliorer la pertinence des recherches fuzzy et keyword.

### Workflow per-user et consensus

#### Decisions individuelles

Chaque decision de mapping est attribuee a l'utilisateur authentifie (`_get_username(request)` leve une erreur 401 si le username n'est pas resolu). Le filtre des suggestions n'exclut que les termes approuves/modifies par l'utilisateur courant — les decisions des autres utilisateurs n'impactent pas ses suggestions. Les termes rejetes restent disponibles pour re-mapping.

#### Consensus (2+ utilisateurs)

Un mapping n'est exportable que lorsqu'il atteint le consensus :

```python
def _get_consensus_decisions(db, cdm_name, domain):
    # Trouve les paires (source_value, target_concept_id) avec 2+ users distincts
    consensus_pairs = (
        db.query(MappingDecision.source_value, MappingDecision.target_concept_id)
        .filter(action IN ["approved", "modified"], target_concept_id IS NOT NULL)
        .group_by(source_value, target_concept_id)
        .having(count(distinct(user)) >= 2)
    )
    # Retourne un representant par groupe consensus
```

Les endpoints `apply`, `apply/preview` et `apply/export` utilisent cette fonction.

#### Actions sur l'historique

| Endpoint | Effet | Permission |
|----------|-------|------------|
| `POST /history/{id}/withdraw` | Supprime la decision (pas de trace) | Proprietaire ou admin |
| `POST /history/{id}/reject` | Change `action` en "rejected" (en place) | Proprietaire ou admin |
| `POST /history/{id}/rollback` | Cree une entree `rolled_back` + supprime l'original | Proprietaire ou admin |

#### Vue groupee (frontend)

L'historique regroupe les decisions par `(source_value, domain, target_concept_id, action)` :
- Meme mapping par 2 users → une seule ligne avec `users: ["jdupont", "medecin"]`
- Un `userIdMap` (user → decision_id) permet le withdraw du bon ID
- Statut : `consensus` (2+ users, meme cible), `conflict` (cibles differentes), `single` (1 user)
- Les decisions `rejected` sont exclues du calcul consensus/conflit

### Optimisations

- **Dashboard mapping** : dernier snapshot par domaine charge en 1 requete (`DISTINCT ON`) au lieu de N+1
- **Strategy stats** : agregation (approval rate, avg confidence) poussee en SQL (`GROUP BY`, `CASE`, `AVG`) au lieu de charger tous les objets ORM en memoire
- **SapBERT batch** : charge uniquement les mappings des termes a traiter (`IN (source_codes)`) au lieu de tout le domaine (~100K+ lignes)
- **Apply mapping** : batch INSERT via `execute_values()` en 1 round-trip au lieu de N inserts sequentiels

---

## 10. Integration OHDSI

### Architecture

OPAL utilise le Docker socket pour lancer des conteneurs OHDSI a la demande.

```
POST /api/ohdsi/run/achilles
    │
    ▼
router.py
    │
    ├── Recupere les parametres CDM (host, port, credentials)
    │
    ├── Construit la commande docker run
    │   - Image: ohdsi-docker-achilles
    │   - Env vars: CDM_CONNECTION_STRING, RESULTS_SCHEMA, ...
    │   - Volume: output/ monte pour les resultats
    │
    ├── Lance le conteneur en arriere-plan
    │
    └── Stocke le PID/container_id pour le suivi
```

### Logs en temps reel

Les logs sont streames via SSE (Server-Sent Events) :

1. Un thread lit `docker logs --follow` du conteneur
2. Les nouvelles lignes sont accumulees dans un buffer
3. L'endpoint SSE envoie les lignes depuis un offset
4. Le frontend auto-reconnecte avec le dernier offset en cas de deconnexion

### Fichiers de sortie

Les resultats OHDSI sont ecrits dans un volume monte. Le navigateur de fichiers permet :
- Lister les dossiers et fichiers
- Telecharger des fichiers individuels
- Naviguer via des breadcrumbs

---

## 11. Notifications temps reel (WebSocket)

### Architecture

```
Client (navigateur)
    │
    ├── useNotificationWs hook
    │   ├── Demande ticket SSE (POST /api/auth/sse-ticket)
    │   ├── Ouvre WebSocket (GET /api/ws/notifications?ticket=xxx)
    │   ├── Reconnexion auto avec backoff exponentiel
    │   └── Dispatch evenement 'opal:notification' au DOM
    │
    ▼
Backend (FastAPI)
    │
    ├── WebSocket endpoint (main.py)
    │   ├── Valide le ticket SSE (usage unique, TTL 30s)
    │   ├── Enregistre la connexion dans WebSocketManager
    │   └── Boucle de reception (keepalive)
    │
    ├── WebSocketManager (utils/ws_manager.py)
    │   ├── Connexions par utilisateur (dict[str, list[WebSocket]])
    │   ├── Connexions par role (dict[str, list[WebSocket]])
    │   ├── send_to_user(username, data) → broadcast personnel
    │   ├── send_to_role(role, data) → broadcast par role
    │   └── Gestion propre des deconnexions
    │
    └── notify() helper (utils/notifications.py)
        ├── Insert en DB (Notification model)
        ├── Verifie les preferences (NotificationPreference)
        └── Push WebSocket instantane via WebSocketManager
```

### Types de notification

| Type | Declencheur | Destinataire |
|------|------------|--------------|
| `cohort_shared` | Partage de cohorte | Utilisateur cible |
| `access_request` | Demande d'acces | Admins (par role) |
| `access_granted` | Attribution d'acces CDM | Utilisateur cible |
| `access_revoked` | Revocation d'acces CDM | Utilisateur cible |
| `cdm_created` | Creation CDM | Admins + data-managers |
| `cdm_updated` | Modification CDM | Admins + data-managers |
| `cdm_deleted` | Suppression CDM | Admins + data-managers |
| `mapping_applied` | Application mapping | Admins + data-managers |
| `cohort_deleted` | Suppression cohorte | Utilisateurs partages |
| `cohort_updated` | Modification cohorte | Utilisateurs partages |
| `group_removed` | Retrait d'un groupe | Membre retire |

### Preferences

Les utilisateurs peuvent muter des types de notification specifiques via `POST /api/notifications/preferences`. Le helper `notify()` verifie les preferences avant d'envoyer.

### Nettoyage

Un thread daemon purge les notifications lues datant de plus de 30 jours.

### Configuration Nginx

```nginx
location /api/ws/ {
    proxy_pass http://opal-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
```

---

## 12. Pathways Analysis

### Methodologie

Basee sur l'approche OHDSI ATLAS (Hripcsak et al. 2016) : analyse des sequences de traitements des patients d'une cohorte.

### Architecture (`modules/cohort/pathways.py`)

```
POST /api/cohorts/pathways
    │
    ├── 1. Materialiser la cohorte cible (table temp _pw_target)
    │      └── Reutilise build_cohort_sql() du sql_builder
    │
    ├── 2. Collecter les evenements par event cohort
    │      ├── Requete les tables OMOP (drug_exposure, condition_occurrence, etc.)
    │      ├── Support include_descendants via concept_ancestor
    │      └── Extraction (person_id, start_date, end_date, event_name)
    │
    ├── 3. Collapse en eras
    │      └── Fusion des intervalles chevauchants d'un meme evenement
    │         (fenetre configurable : combo_window jours)
    │
    ├── 4. Construction des sequences
    │      ├── Ordonnancement des eras par date de debut
    │      └── Troncature a max_depth etapes
    │
    ├── 5. Aggregation
    │      ├── Comptage des sequences identiques
    │      └── Calcul des pourcentages
    │
    └── 6. Construction de l'arbre sunburst
           ├── Structure hierarchique {name, value, children}
           ├── Elagage automatique (min_cell_count)
           └── Attribution de couleurs par evenement
```

### Execution asynchrone

L'analyse s'execute en tache de fond (FastAPI `BackgroundTasks`) avec progression reportee via un dict en memoire `_pathways_tasks`.

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/api/cohorts/pathways` | POST | Lance l'analyse |
| `/api/cohorts/pathways/status/{task_id}` | GET | Polling statut + resultats |
| `/api/cohorts/pathways/cancel/{task_id}` | POST | Annulation |

---

## 13. Theme et UI

### Systeme de themes

OPAL propose deux themes selectionables via le hook `useTheme` :

| Theme | Palette | Fond | Accent |
|-------|---------|------|--------|
| **Dark** (Emerald Night) | Vert emeraude | `#1a1a2e` | `#2bc459` |
| **Light** (Creme Sauge) | Creme/sauge | `#EDE7D9` | `#8FAE6B` |

Le theme est gere par :
- Variables CSS `[data-theme="light"]` dans `opal-theme.css`
- Hook `useTheme` avec persistance `localStorage`
- Script anti-flash dans `index.html`
- Transition CSS 0.4s via classe `.opal-theme-transitioning`
- `tokens.ts` : exports `lightColors` et `lightShadows`

### Composants d'animation

| Composant | Description | Dependance |
|-----------|-------------|------------|
| `AnimatedList` | Listes avec apparition stagger | Framer Motion |
| `FadeIn` | Fondu d'entree pour sections | Framer Motion |
| `ScaleIn` | Pop-in pour cartes | Framer Motion |
| `CountUp` | Animation de compteur numerique | Framer Motion |

### Skeleton loaders

| Composant | Usage |
|-----------|-------|
| `CardSkeleton` | Cartes en chargement |
| `StatSkeleton` | Statistiques en chargement |
| `TableSkeleton` | Tableaux en chargement |
| `DashboardSkeleton` | Dashboard complet |
| `ListSkeleton` | Listes en chargement |

### Etats d'erreur (`ErrorState.tsx`)

5 variantes avec detection automatique via `detectErrorVariant()` :
- `network` : erreur reseau
- `server` : erreur serveur (5xx)
- `forbidden` : acces refuse (403)
- `not-found` : ressource introuvable (404)
- `generic` : erreur generique

### CSS micro-interactions

| Classe | Effet |
|--------|-------|
| `.opal-pressable` | Scale au clic |
| `.bell-ring` | Animation de cloche |
| `.shimmer` | Effet de brillance |
| `.skeleton-wave` | Onde de chargement |
| `.success-flash` | Flash de succes |
| `.number-pop` | Pop de nombre |

---

## 14. Audit et tracabilite

### Middleware d'audit (`audit/logger.py`)

Chaque requete API est tracee dans un fichier de log JSON par jour :

```json
{
  "timestamp": "2026-03-06T10:30:00.123",
  "user": "chercheur1",
  "method": "POST",
  "path": "/api/quality/analyze",
  "status": 200,
  "duration_ms": 1250,
  "ip": "172.18.0.1"
}
```

### Stockage

- Un fichier par jour : `logs/audit_2026-03-06.jsonl`
- Format JSONL (une ligne JSON par entree)
- Lecture paginee et filtree via l'API `/api/audit/logs`

### Mapping decisions audit trail

Les decisions de mapping incluent un audit trail complet dans la table `mapping_decisions` :
- Utilisateur qui a pris la decision
- Action (approved/modified/rejected/rolled_back)
- Concept precedent (pour les modifications)
- Source de la suggestion et score de confiance
- Raison textuelle optionnelle
- Horodatage

---

## 15. Infrastructure Docker

### docker-compose.yml

**4 services** :

| Service | Image | Ports | Volumes |
|---------|-------|-------|---------|
| `opal-frontend` | `node:20-alpine` → `nginx:alpine` | 3000:80 | - |
| `opal-backend` | `python:3.12-slim` | 8000:8000 | `opal_data`, Docker socket, logs |
| `opal-db` | `postgres:16-alpine` | 5434:5432 | `opal_pgdata` |
| `opal-keycloak` | `keycloak:24.0` | 8080:8080 | `opal_keycloak_data`, realm config |

### Reseau

Tous les services partagent le reseau Docker `opal-network`. Les noms de service servent de DNS interne (`opal-db`, `opal-keycloak`, etc.).

### Volumes

| Volume | Persistance | Contenu |
|--------|-------------|---------|
| `opal_pgdata` | Donnees PostgreSQL | Tables OPAL |
| `opal_data` | Cle de chiffrement | `.secret_key` |
| `opal_keycloak_data` | Donnees Keycloak | Utilisateurs, sessions |

### docker-compose.prod.yml (production)

Le fichier `docker-compose.prod.yml` ajoute les durcissements suivants :
- Keycloak en mode production (`start` au lieu de `start-dev`)
- PostgreSQL pour persistence Keycloak (remplace H2 en memoire)
- Socket Docker retire
- Ports bindes sur localhost uniquement
- Variables d'environnement requises (`:?`)
- Limites de ressources (CPU/RAM)

### Health checks

Le backend expose `GET /api/health` utilise comme health check Docker.

---

## 16. Tests

### Configuration de test (`conftest.py`)

Les tests utilisent SQLite en memoire, sans base PostgreSQL externe :

```python
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
Base.metadata.create_all(bind=engine)

# Override FastAPI dependency
app.dependency_overrides[get_db] = override_get_db
```

### Infrastructure de test

- **`omop_mock.py`** : Mock reutilisable de connexion psycopg2 avec sequences de reponses pre-configurees (dict→fetchone, list→fetchall, Exception→erreur)
- **`README.md`** : Documentation complete de l'architecture de test

### Couverture de tests (51 fichiers, 601 tests backend + 84 frontend)

#### Tests existants (v1.0)

| Fichier | Couverture |
|---------|-----------|
| `test_api.py` | CDM CRUD, quality endpoints |
| `test_engine.py` | Moteur d'analyse (mocks psycopg2) |
| `test_comparator.py` | Logique de comparaison |
| `test_crypto.py` | Chiffrement/dechiffrement + DecryptionError |
| `test_cohort_api.py` | Cohort CRUD, SQL generation |
| `test_mapping_api.py` | Mapping workflow, decisions |
| `test_suggest.py` | Strategies de suggestion |
| `test_sql_builder.py` | Generation SQL cohortes |
| `test_cohort_comparison.py` | Comparaison de cohortes (SMD) |
| `test_cohort_diff.py` | Diff de criteres |
| `test_cohort_sharing.py` | Partage de cohortes |
| `test_cohort_templates.py` | Templates de cohortes |
| `test_admin_api.py` | Admin endpoints |
| `test_audit_api.py` | Audit endpoints |
| `test_access_requests.py` | Demandes d'acces |
| `test_cdm_access.py` | Controle d'acces CDM |
| `test_conformity.py` | Conformite des donnees |
| `test_favorites.py` | Favoris |
| `test_groups.py` | Groupes utilisateurs |
| `test_notifications.py` | Notifications (enrichi +400 lignes) |
| `test_saved_queries.py` | Requetes sauvegardees |
| `test_search.py` | Recherche globale |

#### Nouveaux tests (v1.1)

| Fichier | Couverture |
|---------|-----------|
| `test_dashboard_domain.py` | Dashboard UNION ALL, sparklines, error recovery |
| `test_person_domain.py` | Demographics, colonnes manquantes, NULLs |
| `test_observation_period_domain.py` | 6 sous-analyses, cap mois, donnees vides |
| `test_clinical_domain.py` | 5 helpers + orchestrateur tous domaines |
| `test_report_builder.py` | Rapports HTML, comparaison, SVG |
| `test_extractor.py` | SQL builder, identifiants, CTE, bucketing |
| `test_cdm_helper.py` | Lookup CDM, auth, schema override |
| `test_pathways.py` | Validation API pathways |
| `test_pathways_analysis.py` | Sunburst builder, pruning, chemins profonds |
| `test_concept_router.py` | Recherche, details, hierarchie |
| `test_concept_set_api.py` | CRUD, ownership, filtres |
| `test_concept_cache.py` | TTL, eviction, invalidation cache |
| `test_estimation_router.py` | CRUD estimation |
| `test_incidence_router.py` | CRUD incidence |
| `test_incidence_engine.py` | compute_incidence, aggregate, poisson_ci |
| `test_survival.py` | compute_km, median_survival, log_rank_test |
| `test_datamanagement_router.py` | Tables, colonnes, statut taches |
| `test_role_access.py` | RBAC defense en profondeur + IDOR |
| `test_i18n.py` | Parite cles EN/FR, endpoint |
| `test_ws_manager.py` | WebSocket manager : connect, broadcast |
| `test_ws_endpoint.py` | Endpoint WS : auth, messages |
| `test_ws_nginx.py` | Config nginx WebSocket |
| `test_notification_preferences.py` | Preferences par type |
| `test_pagination_gaps.py` | Pagination limit/offset |
| `test_thread_pool.py` | Pool de connexions OMOP, eviction, invalidation |
| `test_csv_safety.py` | Protection injection formules CSV |
| `test_ohdsi_router.py` | Endpoints OHDSI, orchestration Docker |
| `test_rate_limit.py` | Rate limiting par endpoint |
| `test_sql_safety.py` | Validation safe_identifier, longueur max |

#### Tests frontend (6 fichiers, 84 tests)

| Fichier | Couverture |
|---------|-----------|
| `AnimatedList.test.tsx` | FadeIn, ScaleIn, CountUp |
| `SkeletonPatterns.test.tsx` | Card, Stat, Table, Dashboard, List |
| `Empty.test.tsx` | 11 variantes, overrides |
| `ErrorState.test.tsx` | 5 variantes, detection automatique |
| `Toast.test.tsx` | 4 types, auto-dismiss, a11y |
| `useTheme.test.ts` | Toggle, persistance, transition |

### Execution

```bash
# Backend (601 tests)
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v                          # Tous les tests
pytest tests/test_api.py -v               # Un fichier specifique
pytest tests/test_api.py::test_function -v  # Un test specifique

# Frontend (84 tests)
cd frontend
npx vitest run
```

---

## 17. Deploiement en production

### Installation pas-a-pas

#### 1. Preparer la configuration

```bash
cd /chemin/vers/opal
cp .env.example .env
```

Editer `.env` avec les valeurs de production :

```bash
# OBLIGATOIRE — securite
ENVIRONMENT=production
SECRET_KEY=$(openssl rand -hex 32)     # cle de chiffrement des mots de passe CDM
KEYCLOAK_ADMIN=opal-admin              # compte admin de la console Keycloak
KEYCLOAK_ADMIN_PASSWORD=MotDePasse!Fort123   # mot de passe fort, PAS admin/admin
POSTGRES_PASSWORD=MotDePassePostgres   # mot de passe de la base applicative

# OBLIGATOIRE — authentification
AUTH_ENABLED=true                      # obligatoire en production (le backend refuse de demarrer sinon)
KEYCLOAK_ISSUER_URL=http://monserveur:8080   # URL publique de Keycloak (vue par les navigateurs)

# OBLIGATOIRE — reseau
CORS_ORIGINS=http://monserveur:3000    # URL(s) d'acces a OPAL, separees par des virgules
```

> **ENVIRONMENT=production** active les controles de securite au demarrage :
> - `AUTH_ENABLED` doit etre `true` (sinon le backend refuse de demarrer)
> - Les warnings de securite sont logges si des valeurs par defaut sont detectees

> **KEYCLOAK_ISSUER_URL** doit correspondre exactement a l'URL que les navigateurs utilisent pour acceder a Keycloak. Elle sert a verifier le champ `iss` des tokens JWT. Si elle ne matche pas, tous les utilisateurs seront rejetes en 401.

> **SECRET_KEY** chiffre les mots de passe CDM en base. Si vous la perdez ou la changez, il faudra re-saisir tous les mots de passe CDM dans OPAL.

#### 2. Lancer les services

```bash
docker compose up -d
```

Au premier demarrage :
- Keycloak importe automatiquement le realm `opal` (roles, client, mappers)
- Un utilisateur OPAL `admin` est cree avec un mot de passe temporaire `admin`
- La base applicative est creee automatiquement

#### 3. Premier login

1. Ouvrir `http://monserveur:3000` → redirection vers Keycloak
2. Se connecter avec `admin` / `admin`
3. Keycloak demande de changer le mot de passe (car `temporary: true`)
4. Choisir un mot de passe fort → acces a OPAL

#### 4. Configurer Keycloak (console admin)

Acceder a `http://monserveur:8080` avec les credentials definis dans `.env` (`KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`).

Depuis la console :
- Configurer le LDAP si necessaire (synchronisation des comptes hospitaliers)
- Creer des utilisateurs supplementaires avec les roles OPAL (`admin`, `data-manager`, `chercheur`, `medecin`)
- Ajuster la politique de mots de passe (Realm settings → Authentication → Password policy)

### Checklist de securite

- [ ] `ENVIRONMENT=production`
- [ ] `AUTH_ENABLED=true`
- [ ] `SECRET_KEY` genere avec `openssl rand -hex 32`
- [ ] `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` changes (pas `admin/admin`)
- [ ] `KEYCLOAK_ISSUER_URL` pointe vers l'URL publique de Keycloak
- [ ] `POSTGRES_PASSWORD` change (pas `opal`)
- [ ] `CORS_ORIGINS` restreint aux URLs de production
- [ ] Reverse proxy TLS configure (Traefik, Caddy, Nginx)
- [ ] Ports internes non exposes (8000, 5432, 5434)
- [ ] Volumes montes sur du stockage persistant
- [ ] Sauvegardes regulieres de `opal-db` configurees
- [ ] Rotation des logs d'audit configuree

### Architecture production recommandee

```
Internet
    │
    ▼
Reverse Proxy (TLS)
    │
    ├── /           → opal-frontend:80
    ├── /api/       → opal-backend:8000
    └── /auth/      → opal-keycloak:8080
```

### Sauvegarde

Les donnees critiques a sauvegarder :
- **opal-db** : `pg_dump` regulier (contient configs, snapshots, decisions)
- **opal_data** : fichier `.secret_key` (necessaire pour dechiffrer les mots de passe)
- **Keycloak** : export du realm ou backup de la base Keycloak

### Dimensionnement

| Composant | Minimum | Recommande |
|-----------|---------|------------|
| CPU | 2 cores | 4 cores |
| RAM | 4 Go | 8 Go |
| Disque | 10 Go | 50 Go (logs + snapshots) |

Les requetes d'analyse qualite peuvent etre lourdes sur de gros CDM (>1M patients). Le timeout par defaut de 10s pour la connexion CDM peut necessiter un ajustement.
