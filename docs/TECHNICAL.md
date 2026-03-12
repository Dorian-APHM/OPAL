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
11. [Audit et tracabilite](#11-audit-et-tracabilite)
12. [Infrastructure Docker](#12-infrastructure-docker)
13. [Tests](#13-tests)
14. [Deploiement en production](#14-deploiement-en-production)

---

## 1. Vue d'ensemble de l'architecture

### Topologie des services

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Docker Compose                               │
│                                                                       │
│  ┌─────────────────┐          ┌─────────────────┐                    │
│  │  opal-frontend   │  /api/  │  opal-backend    │                    │
│  │  Nginx + React   │────────>│  FastAPI/Uvicorn  │                    │
│  │  :3000           │         │  :8000            │                    │
│  └─────────────────┘         └────┬──────┬───────┘                    │
│                                   │      │                             │
│                    ┌──────────────┘      └──────────────┐             │
│                    │                                     │             │
│             ┌──────┴──────┐                      ┌──────┴──────┐     │
│             │  opal-db     │                      │opal-keycloak│     │
│             │ PostgreSQL 16│                      │ Keycloak 24 │     │
│             │ :5432        │                      │ :8080       │     │
│             └─────────────┘                      └─────────────┘     │
│                                                                       │
│              Docker Socket ──> OHDSI Containers (on-demand)           │
└──────────────────────────────────────────────────────────────────────┘
                    │
                    │ psycopg2 (lecture seule)
                    ▼
           ┌──────────────────┐
           │  CDM OMOP        │
           │  PostgreSQL      │
           │  (N bases)       │
           └──────────────────┘
```

### Principes architecturaux

- **Separation stricte** : la base applicative (`opal-db`) et les CDM externes sont deux mondes distincts
- **Lecture seule** : les CDM sont accedes en lecture seule via `psycopg2` brut (pas d'ORM)
- **Stateless** : chaque requete ouvre et ferme sa propre connexion CDM (pas de pool)
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
5. Inclusion des 18 routers de modules
6. Endpoints systeme directs (health, i18n, auth, audit, admin, access-requests)

### Organisation des modules

```
backend/
├── main.py                    # App FastAPI + endpoints systeme (18 routers)
├── config.py                  # Configuration (env vars + DOMAIN_CONFIG)
├── auth/
│   ├── keycloak.py            # Middleware OIDC + RBAC
│   └── permissions.py         # Permissions YAML loader
├── permissions.yaml           # Matrice RBAC declarative
├── audit/
│   └── logger.py              # Middleware d'audit (trace requetes)
├── db/
│   ├── app_db.py              # SQLAlchemy engine + session factory
│   ├── models.py              # 21 modeles ORM
│   └── omop_connector.py      # Connexions psycopg2 aux CDM
├── utils/
│   ├── crypto.py              # Chiffrement/dechiffrement Fernet
│   └── notifications.py       # Systeme de notifications
├── modules/
│   ├── cdm_router.py          # /api/cdm/
│   ├── cdm_access_router.py   # /api/cdm-access/
│   ├── quality/
│   │   ├── router.py          # /api/quality/
│   │   ├── engine.py          # Orchestration des analyses
│   │   ├── comparator.py      # Comparaison inter-CDM
│   │   ├── conformity.py      # Conformite des donnees
│   │   └── domains/           # SQL par domaine
│   ├── cohort/
│   │   ├── router.py          # /api/cohorts/
│   │   ├── sql_builder.py     # JSON criteres -> SQL
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
│   ├── notifications_router.py    # /api/notifications/
│   ├── favorites_router.py        # /api/favorites/
│   ├── saved_queries_router.py    # /api/saved-queries/
│   ├── cohort_templates_router.py # /api/cohort-templates/
│   ├── cohort_sharing_router.py   # /api/cohorts/ (partage)
│   ├── search_router.py          # /api/search/
│   └── groups_router.py          # /api/groups/
├── i18n/
│   ├── en.json                # Traductions EN
│   └── fr.json                # Traductions FR
└── tests/                     # 22 fichiers de tests
```

### Configuration (`config.py`)

Toute la configuration provient de variables d'environnement avec des valeurs par defaut :

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://opal:opal@opal-db:5432/opal")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
```

Le dictionnaire `DOMAIN_CONFIG` mappe chaque domaine OMOP a sa table et ses colonnes :

```python
DOMAIN_CONFIG = {
    "Condition": {
        "table": "condition_occurrence",
        "concept_id_col": "condition_concept_id",
        "source_value_col": "condition_source_value",
        "source_name_col": None,
        "date_col": "condition_start_date",
    },
    # ... 7 autres domaines
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
- Ouverture a la demande par requete
- Mot de passe dechiffre a chaque connexion
- Pattern context manager pour garantir la fermeture
- `RealDictCursor` pour des resultats en dictionnaires

```python
def get_cdm_connection(cdm_name: str, db: Session):
    config = db.query(CdmConfig).filter_by(name=cdm_name).first()
    password = decrypt_password(config.db_password_enc)
    conn = psycopg2.connect(
        host=config.db_host, port=config.db_port,
        dbname=config.db_name, user=config.db_user,
        password=password, connect_timeout=10
    )
    conn.set_session(readonly=True)
    return conn
```

---

## 3. Frontend — React

### Stack technique

| Bibliotheque | Role |
|--------------|------|
| React 18 | UI framework (hooks, context) |
| TypeScript 5 | Typage statique |
| Vite 5 | Build / dev server (HMR) |
| Composants Neumorphic custom | Design system (Card, Select, Tabs, Checkbox) |
| Lucide React | Icones |
| CodeMirror 6 | Editeur SQL |
| Recharts | Visualisations (Bar, Line, Pie, Area) |
| Axios | Client HTTP |
| React Router 6 | Routing SPA |
| i18next | Internationalisation (FR/EN) |
| keycloak-js | Client OIDC |

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
├── hooks/                     # Hooks custom (useNotifDots, useSessionState, useIsMobile)
├── i18n/                      # Traductions
├── pages/                     # 16 pages
└── components/                # Composants reutilisables (layout, ui, quality, cohort)
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

- Design system **Neumorphic Emerald Night** entierement custom (pas de framework UI externe)
- Composants UI dans `components/ui/` : Card, Select, Tabs, Checkbox avec effets neumorphiques
- Theme CSS dans `opal-theme.css` (couleur primaire : `#2bc459`, fond sombre)
- Mode sombre natif avec persistance `localStorage`
- Design responsive (sidebar collapsible, drawers mobiles)

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
│ created_at timestamp │     └─────────────────────────┘
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

┌──────────────────────┐     ┌─────────────────────────┐
│   concept_sets       │     │ incidence_analyses       │
├──────────────────────┤     ├─────────────────────────┤
│ id         PK serial │     │ id         PK serial     │
│ cdm_name   idx       │     │ cdm_name   idx           │
│ name       varchar   │     │ name       varchar       │
│ description text     │     │ config_json JSON         │
│ concept_ids JSON     │     │ results_json JSON        │
│ created_by varchar   │     │ created_by varchar       │
│ created_at timestamp │     │ created_at timestamp     │
└──────────────────────┘     └─────────────────────────┘

┌──────────────────────┐     ┌─────────────────────────┐
│ estimation_analyses  │     │ cdm_access               │
├──────────────────────┤     ├─────────────────────────┤
│ id         PK serial │     │ id         PK serial     │
│ cdm_name   idx       │     │ cdm_name   idx           │
│ name       varchar   │     │ username   idx           │
│ config_json JSON     │     │ can_read   boolean       │
│ results_json JSON    │     │ can_write  boolean       │
│ created_by varchar   │     │ granted_by varchar       │
│ created_at timestamp │     │ created_at timestamp     │
└──────────────────────┘     └─────────────────────────┘

┌──────────────────────┐     ┌─────────────────────────┐
│ cdm_group_access     │     │ user_favorites           │
├──────────────────────┤     ├─────────────────────────┤
│ id         PK serial │     │ id         PK serial     │
│ cdm_name   idx       │     │ username   idx           │
│ group_name idx       │     │ item_type  varchar       │
│ can_read   boolean   │     │ item_id    varchar       │
│ can_write  boolean   │     │ created_at timestamp     │
│ granted_by varchar   │     └─────────────────────────┘
│ created_at timestamp │
└──────────────────────┘     ┌─────────────────────────┐
                              │ saved_queries            │
┌──────────────────────┐     ├─────────────────────────┤
│ notifications        │     │ id         PK serial     │
├──────────────────────┤     │ cdm_name   idx           │
│ id         PK serial │     │ name       varchar       │
│ username   idx       │     │ sql_text   text          │
│ type       varchar   │     │ created_by varchar       │
│ title      varchar   │     │ created_at timestamp     │
│ message    text      │     └─────────────────────────┘
│ link       varchar   │
│ read       boolean   │     ┌─────────────────────────┐
│ created_at timestamp │     │ cohort_templates         │
└──────────────────────┘     ├─────────────────────────┤
                              │ id         PK serial     │
┌──────────────────────┐     │ name       varchar       │
│ cohort_shares        │     │ description text         │
├──────────────────────┤     │ criteria_json JSON       │
│ id         PK serial │     │ created_by varchar       │
│ cohort_id  FK        │     │ created_at timestamp     │
│ shared_by  varchar   │     └─────────────────────────┘
│ shared_with varchar  │
│ permission varchar   │     ┌─────────────────────────┐
│ created_at timestamp │     │ user_groups              │
└──────────────────────┘     ├─────────────────────────┤
                              │ id         PK serial     │
┌──────────────────────┐     │ name       unique        │
│ user_group_members   │     │ description text         │
├──────────────────────┤     │ created_by varchar       │
│ id         PK serial │     │ created_at timestamp     │
│ group_id   FK        │     └─────────────────────────┘
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

### Conventions

- Pas de systeme de migrations : `create_all()` est idempotent
- Les resultats d'analyse sont stockes en JSON dans `analysis_snapshots.results`
- Les criteres de cohorte sont stockes en JSON dans `cohort_versions.criteria_json`
- Index sur `(cdm_name, domain)` pour les snapshots et decisions de mapping
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

### Authentification Keycloak

**Protocole** : OpenID Connect avec PKCE (S256)

**Architecture** :
- Le frontend utilise `keycloak-js` pour le flux OIDC
- Le backend valide les JWT localement via JWKS (pas d'appel reseau a chaque requete)
- La validation JWKS evite le probleme de mismatch d'issuer (Docker hostname vs browser hostname)

**Validation du token** :
```python
payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    options={
        "verify_iss": False,   # evite le mismatch Docker/browser
        "verify_exp": True,
        "verify_aud": False,
    },
)
```

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

### Protection contre les injections

- Toutes les requetes SQL vers les CDM utilisent des parametres lies (`%s` avec psycopg2)
- L'editeur SQL du constructeur de cohortes n'accepte que `SELECT`, `WITH` et `EXPLAIN`
- Les noms de schema et tables sont valides contre `DOMAIN_CONFIG`

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
    ├── Ouvre connexion psycopg2
    │   - connect_timeout=10
    │   - readonly=True
    │   - RealDictCursor
    │
    ├── Execute la requete SQL
    │
    └── Ferme la connexion
```

### Caracteristiques

- **Pas de pool de connexions** : chaque requete ouvre et ferme sa connexion
- **Lecture seule** : `conn.set_session(readonly=True)` sauf pour l'ecriture STCM
- **Timeout** : 10 secondes de connexion
- **Isolation** : chaque CDM a ses propres identifiants stockes

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

---

## 9. Moteur de suggestions de mapping

### Architecture (`suggest.py`)

Le moteur execute 6 strategies en cascade et retourne les meilleures suggestions classees par confiance.

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

#### 4. Keyword (recherche progressive)

```sql
-- Essaie d'abord tous les mots, puis retire un mot a chaque iteration
SELECT * FROM {schema}.concept
WHERE concept_name ILIKE ALL(ARRAY['%mot1%', '%mot2%', '%mot3%'])
  AND standard_concept = 'S'
  AND domain_id = %s
```

- Confiance : decroissante (80% → 60%)

#### 5. Fuzzy (trigrammes)

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

## 11. Audit et tracabilite

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

## 12. Infrastructure Docker

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

### Health checks

Le backend expose `GET /api/health` utilise comme health check Docker.

---

## 13. Tests

### Configuration de test (`conftest.py`)

Les tests utilisent SQLite en memoire, sans base PostgreSQL externe :

```python
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
Base.metadata.create_all(bind=engine)

# Override FastAPI dependency
app.dependency_overrides[get_db] = override_get_db
```

### Couverture de tests (22 fichiers)

| Fichier | Couverture |
|---------|-----------|
| `test_api.py` | CDM CRUD, quality endpoints |
| `test_engine.py` | Moteur d'analyse (mocks psycopg2) |
| `test_comparator.py` | Logique de comparaison |
| `test_crypto.py` | Chiffrement/dechiffrement |
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
| `test_notifications.py` | Notifications |
| `test_saved_queries.py` | Requetes sauvegardees |
| `test_search.py` | Recherche globale |

### Execution

```bash
cd backend
pytest tests/ -v              # Tous les tests
pytest tests/test_api.py -v   # Un fichier specifique
pytest tests/test_api.py::test_function -v  # Un test specifique
```

---

## 14. Deploiement en production

### Checklist

- [ ] Generer un `SECRET_KEY` fort : `openssl rand -hex 32`
- [ ] Changer le mot de passe PostgreSQL par defaut
- [ ] Activer Keycloak : `AUTH_ENABLED=true`
- [ ] Changer le mot de passe admin Keycloak
- [ ] Configurer un reverse proxy TLS (Traefik, Caddy, Nginx)
- [ ] Ne pas exposer les ports 8000, 5432, 5434
- [ ] Configurer `CORS_ORIGINS` pour le domaine de production
- [ ] Monter les volumes sur du stockage persistant
- [ ] Configurer des sauvegardes regulieres de `opal-db`
- [ ] Configurer la rotation des logs d'audit

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
