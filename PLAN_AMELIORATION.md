# PLAN D'AMELIORATION OPAL — Audit complet

> Date : 2026-03-13
> Scope : Securite, Performance, Architecture, Frontend, Tests, DevOps, Nouvelles fonctionnalites

---

## TABLE DES MATIERES

1. [SECURITE — Critique](#1-securite--critique)
2. [PERFORMANCE & OPTIMISATION — Backend](#2-performance--optimisation--backend)
3. [PERFORMANCE & OPTIMISATION — Frontend](#3-performance--optimisation--frontend)
4. [ARCHITECTURE & QUALITE DE CODE](#4-architecture--qualite-de-code)
5. [TESTS & COUVERTURE](#5-tests--couverture)
6. [DEVOPS & INFRASTRUCTURE](#6-devops--infrastructure)
7. [ACCESSIBILITE (a11y)](#7-accessibilite-a11y)
8. [NOUVELLES FONCTIONNALITES](#8-nouvelles-fonctionnalites)

Chaque section contient : le probleme, les fichiers concernes (file:line), la solution proposee, et la priorite (P0=critique, P1=haute, P2=moyenne, P3=basse).

---

## 1. SECURITE — Critique

### 1.1 [P0] Injection SQL via f-string UNION dans concept/router.py

**Probleme :** Les requetes UNION sont assemblees par f-string avec du contenu derive de l'utilisateur.
**Fichiers :**
- `backend/modules/concept/router.py:361` — `f"SELECT COUNT(*) AS cnt FROM ({full_query}) sub"`
- `backend/modules/concept/router.py:443` — `f"SELECT * FROM ({full_query}) sub ORDER BY ..."`
- `backend/modules/concept/router.py:500-502` — Interpolation de colonnes/tables

**Solution :**
- Remplacer les f-strings par des requetes parametrees ou `sql.SQL` de psycopg2
- Valider chaque partie du UNION avec `safe_identifier()` avant assemblage
- Ajouter des tests unitaires specifiques pour les injections SQL sur ces endpoints

---

### 1.2 [P0] Absence totale de rate limiting

**Probleme :** Aucun middleware de rate limiting. Tous les endpoints sont vulnérables au brute-force et au DoS.
**Fichiers :** `backend/main.py` (aucun middleware rate-limit)

**Solution :**
- Installer `slowapi` (basé sur `limits`)
- Configurer des limites globales (ex: 100 req/min/IP) et par endpoint :
  - `/api/access-requests` : 5 req/min (anti-spam)
  - `/api/auth/sse-ticket` : 10 req/min/user
  - `/api/quality/analyze` : 3 req/min/user (operations longues)
  - `/api/mapping/suggest` : 10 req/min/user
  - Exports CSV : 5 req/min/user
- Ajouter les headers `X-RateLimit-*` dans les réponses

---

### 1.3 [P0] XSS via i18next `escapeValue: false`

**Probleme :** L'echappement HTML est desactive dans i18next. Si une clé de traduction contient du HTML malveillant, il sera rendu.
**Fichier :** `frontend/src/i18n/index.ts:14` — `escapeValue: false`

**Solution :**
- Remettre `escapeValue: true` (defaut)
- Pour les rares cas necessitant du HTML, utiliser `<Trans>` component avec des composants React
- Auditer `i18n/fr.json` et `i18n/en.json` pour tout contenu HTML existant

---

### 1.4 [P1] Absence de CSP (Content Security Policy)

**Probleme :** Aucun header CSP configure ni dans Vite ni dans nginx (seuls X-Frame-Options et X-XSS-Protection sont presents).
**Fichiers :**
- `frontend/nginx.conf:8-11` — Headers existants mais pas de CSP
- `frontend/vite.config.ts` — Aucune config headers

**Solution :**
- Ajouter dans `nginx.conf` :
  ```
  add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self';" always;
  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
  ```
- Adapter le CSP selon les CDN utilises (Recharts, etc.)
- Tester avec le report-uri en mode report-only d'abord

---

### 1.5 [P1] Token refresh et retry manquants dans le client API

**Probleme :** L'intercepteur axios ne retente pas les requetes apres un 401. Le token refresh se fait en background (30s) mais les requetes echouees sont perdues.
**Fichier :** `frontend/src/api/client.ts:59-80`

**Solution :**
- Implementer un intercepteur de reponse qui :
  1. Detecte le 401
  2. Rafraichit le token via Keycloak
  3. Rejouent la requete originale
- Ajouter une file d'attente pour eviter les refresh multiples simultanes
- Configurer un `timeout` axios global (ex: 30s par defaut, 300s pour les exports)

---

### 1.6 [P1] Gestion des clés de chiffrement

**Probleme :** La cle Fernet est stockee en fichier local (`/app/data/.secret_key`) sans rotation possible. L'echec de dechiffrement retourne une chaine vide silencieusement.
**Fichiers :**
- `backend/utils/crypto.py:10` — Stockage fichier
- `backend/utils/crypto.py:43-57` — Echec silencieux

**Solution :**
- Phase 1 : Faire lever une exception explicite si le dechiffrement echoue (forcer la re-saisie du mot de passe CDM)
- Phase 2 : Supporter une source externe de cle (variable d'env `ENCRYPTION_KEY`, ou integration Vault/KMS)
- Phase 3 : Mecanisme de rotation de cle (re-chiffrer tous les mots de passe avec la nouvelle cle)

---

### 1.7 [P1] Keycloak tourne en root

**Probleme :** Le conteneur Keycloak est configure avec `user: "0:0"` (root).
**Fichier :** `docker-compose.yml:81`

**Solution :**
- Supprimer `user: "0:0"`
- Utiliser l'image Keycloak avec l'utilisateur par defaut (1000:1000)
- Ajuster les permissions des volumes montes en consequence

---

### 1.8 [P1] CORS trop permissif

**Probleme :** `allow_methods=["*"]` et `allow_headers=["*"]` combines avec `allow_credentials=True`.
**Fichier :** `backend/main.py:90-96`

**Solution :**
- Restreindre `allow_methods` a `["GET", "POST", "PUT", "DELETE", "OPTIONS"]`
- Restreindre `allow_headers` a `["Authorization", "Content-Type", "Accept", "Accept-Language"]`
- Valider que `CORS_ORIGINS` ne contient jamais `*` quand `allow_credentials=True`

---

### 1.9 [P2] Tickets SSE sans limite par utilisateur

**Probleme :** Pas de limite sur le nombre de tickets SSE crees par utilisateur. Accumulation en memoire sans nettoyage proactif.
**Fichier :** `backend/auth/keycloak.py:50-76`

**Solution :**
- Limiter a 5 tickets actifs par utilisateur
- Ajouter un nettoyage periodique des tickets expires (tache background toutes les 60s)
- Ajouter un TTL maximal et un compteur par IP

---

### 1.10 [P2] Credentials par defaut Keycloak non bloquees en production

**Probleme :** Les identifiants `admin/admin` generent un WARNING mais ne bloquent pas le demarrage.
**Fichier :** `backend/main.py:544-548`

**Solution :**
- Si `AUTH_ENABLED=true` et credentials = default, refuser le demarrage avec un message explicite
- Ajouter un flag `ALLOW_DEFAULT_CREDENTIALS=true` pour le developpement uniquement

---

## 2. PERFORMANCE & OPTIMISATION — Backend

### 2.1 [P1] Handler manquant pour ConnectionError (pool epuise)

**Probleme :** Quand le pool OMOP est epuise, `ConnectionError` est levee mais non capturee par un exception handler — retourne 500 au lieu de 503.
**Fichiers :**
- `backend/db/omop_connector.py:163-170` — Leve ConnectionError
- `backend/main.py:72-86` — Handlers existants (manque ConnectionError)

**Solution :**
```python
@app.exception_handler(ConnectionError)
async def connection_error_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})
```

---

### 2.2 [P1] Requetes N+1 dans cohort sharing et access control

**Probleme :** Chargement de toutes les entites en memoire puis filtrage Python au lieu de filtrage SQL.
**Fichiers :**
- `backend/modules/cohort_sharing_router.py:211` — `db.query(CohortShare).all()` sans WHERE
- `backend/modules/cdm_access_router.py:93-95` — `.all()` puis filtrage Python
- `backend/modules/cohort/router.py:217-233` — Boucle sur les groupes utilisateur

**Solution :**
- Remplacer `.all()` + filtre Python par des `.filter()` SQL
- Pour les groupes utilisateur : une seule requete avec `IN` clause ou sous-requete
- Ajouter des index composes manquants (voir 2.4)

---

### 2.3 [P1] Attrition de cohorte en O(n) requetes

**Probleme :** L'analyse d'attrition execute une requete separee par etape.
**Fichier :** `backend/modules/cohort/router.py:540-589`

**Solution :**
- Utiliser un CTE (Common Table Expression) avec UNION ALL pour calculer toutes les etapes en une seule requete
- Alternative : pipeline CTEs enchainées avec comptages intermediaires

---

### 2.4 [P2] Index composites manquants

**Probleme :** Plusieurs patterns de requetes frequentes n'ont pas d'index adequats.
**Fichier :** `backend/db/models.py`

**Ajouts proposes :**
```python
# CdmAccess — requete frequente par (cdm_name, username)
Index('ix_cdm_access_cdm_user', 'cdm_name', 'username')

# Cohort — filtrage par (cdm_name, created_by)
Index('ix_cohort_cdm_creator', 'cdm_name', 'created_by')

# SavedQuery — tri par date de creation
Index('ix_saved_query_cdm_created', 'cdm_name', 'created_at')

# Notification — requete par (username, item_id)
Index('ix_notification_user_item', 'username', 'item_id')
```

---

### 2.5 [P2] Pagination manquante sur plusieurs endpoints

**Probleme :** Plusieurs endpoints retournent `.all()` sans limite.
**Fichiers :**
- `backend/modules/cdm_router.py:124` — Liste tous les CDMs
- `backend/modules/cohort_templates_router.py` — Tous les templates
- `backend/modules/groups_router.py` — Tous les groupes
- `backend/modules/saved_queries_router.py` — Toutes les requetes sauvees
- `backend/modules/favorites_router.py` — Tous les favoris

**Solution :**
- Ajouter `skip: int = 0, limit: int = 100` sur tous ces endpoints
- Retourner un objet `{ items: [...], total: int }` pour permettre la pagination frontend

---

### 2.6 [P2] Appels HTTP Keycloak synchrones bloquants

**Probleme :** Les appels a l'API Keycloak utilisent `requests.get()` synchrone, bloquant le thread FastAPI.
**Fichier :** `backend/main.py:417-440` et `main.py:532-565`

**Solution :**
- Remplacer `requests` par `httpx.AsyncClient` pour les appels Keycloak
- Cacher le token admin Keycloak avec un TTL (ex: 5 min) au lieu de le re-fetcher a chaque appel
- Utiliser `async def` pour les endpoints concernes

---

### 2.7 [P2] Lecture synchrone des logs d'audit en memoire

**Probleme :** Les fichiers JSONL d'audit sont lus entierement en memoire pour filtrage.
**Fichier :** `backend/main.py:264-322`

**Solution :**
- Implementer une lecture en streaming ligne par ligne avec filtres appliques a la volee
- Ajouter une limite de date obligatoire (ex: max 7 jours par requete)
- Alternative : stocker les logs d'audit dans la base PostgreSQL pour permettre des requetes SQL efficaces

---

### 2.8 [P3] Validation de configuration manquante

**Probleme :** Pas de validation que `OMOP_POOL_MIN_CONN <= OMOP_POOL_MAX_CONN`, pas de validation des CORS_ORIGINS comme URLs valides.
**Fichier :** `backend/config.py`

**Solution :**
- Ajouter des assertions au demarrage de l'application
- Utiliser pydantic `BaseSettings` au lieu de `os.getenv` brut pour la validation automatique

---

## 3. PERFORMANCE & OPTIMISATION — Frontend

### 3.1 [P1] Polling a la place de WebSocket

**Probleme :** L'analyse qualite utilise un polling a 2s au lieu de WebSocket/SSE.
**Fichiers :**
- `frontend/src/pages/QualityPage.tsx:129` — Intervalle 2s
- `frontend/src/pages/MappingPage.tsx` — Polling similaire

**Solution :**
- Utiliser les SSE (deja partiellement implementes) de facon systematique pour toutes les operations longues
- Fallback sur polling uniquement si SSE echoue
- Augmenter l'intervalle de polling fallback a 5-10s

---

### 3.2 [P2] Fichiers pages trop volumineux

**Probleme :** Des fichiers monolithiques difficiles a maintenir.
**Fichiers :**
- `frontend/src/pages/MappingPage.tsx` — 59.9 KB
- `frontend/src/pages/CohortPage.tsx` — 1015 lignes
- `frontend/src/pages/QualityPage.tsx` — 800 lignes

**Solution :**
- Extraire en sous-composants :
  - `MappingPage` → `MappingDashboard`, `MappingTable`, `MappingSuggestionPanel`, `MappingBatchActions`
  - `CohortPage` → `CriteriaPanel`, `QueryCanvas`, `ResultsPanel`, `AttritionChart`
  - `QualityPage` → `QualityDashboard`, `QualityDomainView`, `QualityComparison`

---

### 3.3 [P2] Absence de memoisation

**Probleme :** Les composants enfants re-render a chaque changement du parent. Aucun `React.memo()` utilise.
**Fichiers :** Pages QualityPage, CohortPage, MappingPage

**Solution :**
- Wrapper les sous-composants couteux avec `React.memo()`
- Utiliser `useMemo()` pour les calculs derives (ex: filtrage, tri)
- Utiliser `useCallback()` pour les handlers passes en props
- Remplacer `rowKey={() => JSON.stringify(r).slice(0, 100)}` par `rowKey={(r) => r.person_id}` (`CohortPage.tsx:485,929`)

---

### 3.4 [P2] Gestion d'etat par prop drilling

**Probleme :** `useSessionState()` custom utilise une Map en memoire (perdue au refresh). Prop drilling sur 3-4 niveaux.
**Fichier :** `frontend/src/hooks/useSessionState.ts`

**Solution :**
- Migrer vers Zustand (leger, ~1KB) pour l'etat global partage :
  - Store `cdmStore` : CDM selectionne, settings
  - Store `qualityStore` : resultats d'analyse, domaine selectionne
  - Store `cohortStore` : criteres, resultats
- Persister les stores critiques dans `sessionStorage` via le middleware Zustand `persist`

---

### 3.5 [P3] Types `any` repandus

**Probleme :** Utilisation de `any` dans les types TypeScript, annulant les benefices du typage.
**Fichier :** `frontend/src/types/index.ts:335, 339, 340, 343, 347, 360, 400, 401, 505, 509`

**Solution :**
- Remplacer chaque `any` par le type concret ou `unknown`
- Ajouter la regle ESLint `@typescript-eslint/no-explicit-any` en warning puis error

---

### 3.6 [P3] Catch vides dans les pages

**Probleme :** Nombreux `.catch(() => {})` qui avalent les erreurs silencieusement.
**Fichiers :**
- `QualityPage.tsx:72, 99, 132, 218, 350`
- `CohortPage.tsx:88, 104`
- `MappingPage.tsx:1452`

**Solution :**
- Remplacer par `.catch((err) => console.error(err))` au minimum
- Mieux : afficher un toast d'erreur ou un composant d'erreur inline
- Creer un hook `useApiCall()` qui gere loading/error/data de facon standard

---

## 4. ARCHITECTURE & QUALITE DE CODE

### 4.1 [P1] Pas de systeme de migrations de base de donnees

**Probleme :** Aucun Alembic ou systeme de migration. Les changements de schema necessitent une recreation manuelle.

**Solution :**
- Installer Alembic : `pip install alembic`
- Initialiser : `alembic init alembic`
- Generer la migration initiale depuis les modeles existants
- Documenter le workflow de migration dans CLAUDE.md
- Structure cible :
  ```
  backend/
    alembic/
      versions/
        001_initial_schema.py
      env.py
    alembic.ini
  ```

---

### 4.2 [P1] Pas de suppression en cascade pour les CDMs

**Probleme :** Supprimer un CDM ne supprime pas les snapshots, cohortes, accès associes. Donnees orphelines possibles.
**Fichiers :**
- `backend/modules/cdm_router.py` — Endpoint DELETE
- `backend/db/models.py` — Relations sans `cascade="all, delete-orphan"`

**Solution :**
- Ajouter `cascade="all, delete-orphan"` sur les relations ou
- Implementer une suppression explicite transactionnelle dans le endpoint DELETE :
  1. Supprimer CdmAccess, CdmGroupAccess
  2. Supprimer AnalysisSnapshot, AnalysisSettings
  3. Supprimer Cohorts et CohortVersions
  4. Supprimer MappingDecisions
  5. Supprimer le CdmConfig
  6. Invalider le pool de connexion

---

### 4.3 [P2] Pas de gestion de conflits de concurrence

**Probleme :** Deux utilisateurs modifiant la meme cohorte ou les memes mapping decisions peuvent s'ecraser mutuellement.

**Solution :**
- Implementer l'optimistic locking avec un champ `version` (compteur) sur :
  - `Cohort`
  - `MappingDecision`
- Le client envoie la version qu'il a lue ; le serveur rejette si elle a change (HTTP 409 Conflict)

---

### 4.4 [P2] Configuration via os.getenv brut

**Probleme :** `config.py` utilise `os.getenv()` sans validation de type ni de valeur.
**Fichier :** `backend/config.py`

**Solution :**
- Migrer vers `pydantic.BaseSettings` :
  ```python
  class Settings(BaseSettings):
      DATABASE_URL: str
      SECRET_KEY: str = Field(min_length=32)
      AUTH_ENABLED: bool = True
      CORS_ORIGINS: list[str] = ["http://localhost:3000"]
      OMOP_POOL_MIN_CONN: int = Field(default=2, ge=1)
      OMOP_POOL_MAX_CONN: int = Field(default=20, ge=2)
      # ...
      class Config:
          env_file = ".env"
  ```

---

### 4.5 [P3] Variables d'environnement non documentees

**Probleme :** `APP_DB_POOL_SIZE`, `APP_DB_MAX_OVERFLOW`, `APP_DB_POOL_RECYCLE`, `OMOP_POOL_*` ne sont pas dans `.env.example`.
**Fichier :** `.env.example`

**Solution :**
- Ajouter toutes les variables manquantes avec leurs valeurs par defaut et un commentaire explicatif

---

## 5. TESTS & COUVERTURE

### 5.1 [P0] Aucun test frontend

**Probleme :** Zero fichier de test cote frontend. Aucun framework de test installe.

**Solution :**
- Installer Vitest + React Testing Library :
  ```bash
  npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
  ```
- Tests prioritaires a ecrire :
  1. `client.test.ts` — Intercepteurs axios, gestion d'erreur, token refresh
  2. `App.test.tsx` — Routing, lazy loading, error boundary
  3. Tests pour chaque page critique : QualityPage, CohortPage, MappingPage
  4. Tests des hooks custom (`useSessionState`, `useAuth`)

---

### 5.2 [P1] pytest absent de requirements.txt

**Probleme :** `pytest` n'est pas liste comme dependance alors que 25 fichiers de test existent.
**Fichier :** `backend/requirements.txt`

**Solution :**
- Creer un `requirements-dev.txt` :
  ```
  -r requirements.txt
  pytest>=8.0.0
  pytest-cov>=4.1.0
  pytest-asyncio>=0.23.0
  httpx>=0.27.0  # pour TestClient async
  ```
- Ajouter la config pytest dans `pyproject.toml` :
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  addopts = "--cov=. --cov-report=html --cov-report=term-missing"
  ```

---

### 5.3 [P1] Pas de CI/CD

**Probleme :** Aucun pipeline d'integration continue. Les tests et builds sont manuels.

**Solution :**
- Creer `.github/workflows/ci.yml` :
  ```yaml
  name: CI
  on: [push, pull_request]
  jobs:
    backend-tests:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.12' }
        - run: pip install -r backend/requirements-dev.txt
        - run: cd backend && pytest tests/ -v --cov --cov-report=xml
        - uses: codecov/codecov-action@v4

    frontend-build:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-node@v4
          with: { node-version: '20' }
        - run: cd frontend && npm ci && npm run build

    frontend-tests:
      runs-on: ubuntu-latest
      steps:
        - run: cd frontend && npm ci && npx vitest run

    docker-build:
      runs-on: ubuntu-latest
      steps:
        - run: docker compose build
  ```

---

### 5.4 [P2] Couverture de tests insuffisante

**Probleme :** Pas de coverage reporting. Certaines zones critiques peu testees.

**Solution :**
- Cible de couverture : 80% backend, 60% frontend
- Zones a couvrir en priorite :
  - `utils/crypto.py` — Chiffrement/dechiffrement, rotation de cle
  - `db/omop_connector.py` — Pool exhaustion, connection recovery, eviction
  - `modules/quality/engine.py` — Tous les types d'analyse
  - `modules/cohort/sql_builder.py` — Cas limites SQL (deja bien teste)
  - `auth/keycloak.py` — SSE tickets, role resolution, CDM access checks

---

### 5.5 [P3] Tests end-to-end absents

**Probleme :** Aucun test e2e (Playwright/Cypress).

**Solution :**
- Installer Playwright :
  ```bash
  npm install -D @playwright/test
  npx playwright install
  ```
- Scenarios prioritaires :
  1. Login → selection CDM → lancement analyse qualite
  2. Creation de cohorte → ajout criteres → execution
  3. Workflow mapping complet (dashboard → suggestions → decision)
  4. CRUD CDM (ajout, test connexion, modification, suppression)

---

## 6. DEVOPS & INFRASTRUCTURE

### 6.1 [P1] Hostnames et IPs en dur dans docker-compose.yml

**Probleme :** `antodeep002`, `10.64.48.194` codes en dur.
**Fichier :** `docker-compose.yml:12, 19`

**Solution :**
- Externaliser dans `.env` :
  ```env
  EXTERNAL_HOSTNAME=localhost
  KEYCLOAK_ISSUER_URL=http://opal-keycloak:8080/realms/opal
  CORS_ORIGINS=http://${EXTERNAL_HOSTNAME}:3000
  ```
- Utiliser les noms de service Docker (`opal-keycloak`) pour la communication inter-conteneurs

---

### 6.2 [P1] Pas de limites de ressources Docker

**Probleme :** Aucun service n'a de limite memoire ou CPU.
**Fichier :** `docker-compose.yml`

**Solution :**
```yaml
services:
  opal-backend:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
  opal-frontend:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
  opal-db:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
  opal-keycloak:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
```

---

### 6.3 [P2] Port de la base de donnees expose

**Probleme :** `opal-db` expose le port 5434 sur l'hote, inutile en production.
**Fichier :** `docker-compose.yml`

**Solution :**
- Utiliser un profil Docker Compose pour separer dev et prod :
  ```yaml
  opal-db:
    ports:
      - "${DB_EXTERNAL_PORT:-}:5432"  # Vide en prod = pas expose
  ```
- Ou utiliser `docker-compose.override.yml` pour le dev uniquement

---

### 6.4 [P2] Pas de Makefile ni scripts d'automatisation

**Probleme :** Toutes les operations sont manuelles.

**Solution :**
- Creer un `Makefile` :
  ```makefile
  .PHONY: dev test build deploy

  dev:             ## Lance l'environnement de dev
  	docker compose up -d

  test-backend:    ## Lance les tests backend
  	cd backend && pytest tests/ -v --cov

  test-frontend:   ## Lance les tests frontend
  	cd frontend && npx vitest run

  test: test-backend test-frontend

  build:           ## Build les images Docker
  	docker compose build

  lint:            ## Lint backend + frontend
  	cd backend && ruff check .
  	cd frontend && npx eslint src/

  migrate:         ## Applique les migrations
  	cd backend && alembic upgrade head

  migrate-create:  ## Cree une nouvelle migration
  	cd backend && alembic revision --autogenerate -m "$(msg)"
  ```

---

### 6.5 [P2] Pas de health check pour Keycloak

**Probleme :** Le service Keycloak n'a aucun health check dans docker-compose.yml.
**Fichier :** `docker-compose.yml`

**Solution :**
```yaml
opal-keycloak:
  healthcheck:
    test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080 && echo -e 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\n\r\n' >&3 && cat <&3 | grep -q '200'"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 60s
```

---

### 6.6 [P2] Pas de pre-commit hooks

**Solution :**
- Installer pre-commit :
  ```yaml
  # .pre-commit-config.yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.3.0
      hooks:
        - id: ruff
          args: [--fix]
    - repo: https://github.com/pre-commit/pre-commit-hooks
      hooks:
        - id: check-added-large-files
        - id: detect-private-key
        - id: check-merge-conflict
    - repo: https://github.com/Yelp/detect-secrets
      hooks:
        - id: detect-secrets
  ```

---

### 6.7 [P3] Versions de dependances non pinnees (backend)

**Probleme :** `requirements.txt` utilise `>=` pour toutes les dependances.
**Fichier :** `backend/requirements.txt`

**Solution :**
- Utiliser `pip-compile` (pip-tools) pour generer un `requirements.txt` avec des versions exactes
- Garder `requirements.in` avec les contraintes flexibles
- Automatiser la mise a jour avec Dependabot ou Renovate

---

## 7. ACCESSIBILITE (a11y)

### 7.1 [P1] Aucun attribut ARIA dans les composants UI

**Probleme :** Aucun `aria-label`, `aria-describedby`, `role` dans la librairie de composants custom.

**Solution :**
- Ajouter sur tous les composants interactifs :
  - `Button` : `aria-label` pour les boutons icon-only
  - `Input` : `aria-required`, `aria-invalid`, label associe obligatoire
  - `Select/Dropdown` : `role="listbox"`, `aria-expanded`
  - `Modal/Drawer` : `role="dialog"`, `aria-modal="true"`, focus trap
  - `Table` : `aria-label`, `aria-sort` pour les colonnes triables
  - `Spinner/Loading` : `aria-live="polite"`, `role="status"`
  - `Toast/Alert` : `role="alert"`, `aria-live="assertive"`

---

### 7.2 [P2] Navigation clavier incomplete

**Probleme :** Pas de gestion du focus dans les modals, pas de skip-to-content link.

**Solution :**
- Ajouter un lien "Skip to content" en haut de page
- Implementer le focus trap dans les modals/drawers
- Assurer la navigation Tab dans les dropdowns et menus
- Tester avec le lecteur d'ecran (NVDA/VoiceOver)

---

### 7.3 [P2] Indicateurs bases uniquement sur la couleur

**Probleme :** Les scores qualite et les statuts de mapping utilisent uniquement la couleur.
**Fichiers :** `QualityPage.tsx:250-251`, composants de mapping

**Solution :**
- Ajouter des icones ou des labels textuels en plus de la couleur :
  - Score bon : couleur verte + icone check + texte "Bon"
  - Score warning : couleur orange + icone warning + texte "Attention"
  - Score critique : couleur rouge + icone X + texte "Critique"

---

## 8. NOUVELLES FONCTIONNALITES

### 8.1 [P2] Monitoring et observabilite

**Description :** Ajouter un endpoint `/metrics` Prometheus et des dashboards Grafana.

**Implementation :**
- Backend : `prometheus-fastapi-instrumentator` pour les metriques HTTP automatiques
- Metriques custom : pool connections actives, duree des analyses, taille des exports
- Docker : ajouter un service `prometheus` + `grafana` en option
- Alertes : pool epuise, latence P99 > 5s, taux d'erreur > 5%

---

### 8.2 [P2] Systeme de notifications temps reel

**Description :** Remplacer le polling des notifications par du WebSocket/SSE.

**Implementation :**
- Backend : endpoint SSE `/api/notifications/stream` (l'infrastructure SSE existe deja)
- Events : analyse terminee, nouvelle cohorte partagee, mapping applique, access request approuvee
- Frontend : hook `useNotificationStream()` qui ecoute les SSE et met a jour le badge

---

### 8.3 [P2] Export et import de configurations

**Description :** Permettre l'export/import de cohortes, mappings et analyses entre instances OPAL.

**Implementation :**
- Format JSON standardise avec versioning de schema
- Endpoints : `GET /api/export/{type}/{id}`, `POST /api/import/{type}`
- Types exportables : cohortes (criteres JSON), mapping decisions, concept sets, templates
- Validation de compatibilite a l'import (version du schema, domaines disponibles)

---

### 8.4 [P3] Mode hors-ligne / cache local

**Description :** Permettre la consultation des resultats d'analyse sans connexion au serveur.

**Implementation :**
- Service Worker pour mettre en cache les reponses API des analyses deja consultees
- IndexedDB pour les resultats d'analyse qualite et les definitions de cohortes
- Indicateur visuel "mode hors-ligne" dans la barre de navigation

---

### 8.5 [P3] Tableau de bord administrateur

**Description :** Vue d'ensemble pour les admins : utilisation, connexions actives, pools, logs.

**Implementation :**
- Page `AdminDashboardPage` avec :
  - Nombre de CDMs connectes et statut des pools
  - Utilisateurs actifs (derniere activite)
  - Metriques d'utilisation par module (qualite, cohortes, mapping)
  - Graphique de latence et d'erreurs (si Prometheus disponible)
  - Acces rapide aux logs d'audit filtres

---

## RESUME PAR PRIORITE

| Priorite | Categorie | Nombre d'items |
|----------|-----------|----------------|
| **P0 — Critique** | Securite, Tests | 4 |
| **P1 — Haute** | Securite, Performance, Architecture, DevOps, a11y | 14 |
| **P2 — Moyenne** | Performance, Frontend, Architecture, DevOps, a11y, Features | 17 |
| **P3 — Basse** | Code quality, Docs, Features | 7 |

### Ordre d'execution recommande

**Phase 1 — Securite critique (1-2 semaines)**
1. Fix SQL injection (1.1)
2. Rate limiting (1.2)
3. Fix XSS i18n (1.3)
4. CSP headers (1.4)
5. Token refresh (1.5)

**Phase 2 — Fondations (2-3 semaines)**
6. Alembic migrations (4.1)
7. CI/CD pipeline (5.3)
8. pytest dans requirements (5.2)
9. Handler ConnectionError (2.1)
10. Fix N+1 queries (2.2)
11. Keycloak non-root (1.7)

**Phase 3 — Qualite & Performance (2-3 semaines)**
12. Tests frontend (5.1)
13. Refactoring pages volumineuses (3.2)
14. Pagination endpoints (2.5)
15. Index composites (2.4)
16. Accessibilite ARIA (7.1)
17. Makefile (6.4)

**Phase 4 — Ameliorations (continu)**
18. Monitoring Prometheus (8.1)
19. Notifications temps reel (8.2)
20. State management Zustand (3.4)
21. Export/import configs (8.3)
22. Tests e2e (5.5)
23. Pre-commit hooks (6.6)

---

*Ce plan est base sur un audit complet du code source au 2026-03-13.*
