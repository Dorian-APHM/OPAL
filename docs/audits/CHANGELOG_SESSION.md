# CHANGELOG — Session de travail du 15 mars 2026

> **Branche** : `claude/count-code-lines-03FQD`
> **Base** : `master` (v1.0.1)
> **Commits** : 4 commits, ~2600 lignes ajoutees, ~800 lignes supprimees sur 45 fichiers backend + 7 fichiers frontend
> **Tests** : 327 tests passent (100% green)

---

## Vue d'ensemble

Cette session a couvert 4 axes principaux :

1. **Plan d'amelioration complet** — Audit exhaustif de la codebase (securite, perfs, archi, tests, DevOps)
2. **Pathways Analysis** — Nouvelle fonctionnalite ATLAS-style dans l'onglet Cohort
3. **Implementation P0/P1** — Corrections critiques de securite + optimisations performances
4. **Fix rate limiter** — Correction des effets de bord du rate limiting sur la suite de tests

---

## Commit 1 : Plan d'amelioration (`883ad1b`)

### Quoi
Fichier `PLAN_AMELIORATION.md` : audit complet de la codebase couvrant securite, performance, architecture, tests et DevOps. Chaque item identifie le probleme, les fichiers concernes (file:line), la solution proposee et la priorite (P0 a P3).

### Pourquoi
Avant de modifier quoi que ce soit, il fallait un inventaire structure de toutes les dettes techniques et failles. Ce document sert de reference pour prioriser et tracer les corrections.

### Fichiers
- `PLAN_AMELIORATION.md` (nouveau)

---

## Commit 2 : Pathways Analysis (`8da9ed0`)

### Quoi
Feature complete d'analyse de parcours de soins ("treatment pathways") basee sur la methodologie OHDSI ATLAS (Hripcsak et al. 2016).

### Pourquoi
C'est une fonctionnalite phare d'ATLAS qui manquait a OPAL. Elle permet de visualiser les sequences de traitements des patients d'une cohorte sous forme de sunburst interactif.

### Backend — `backend/modules/cohort/pathways.py` (nouveau, 346 lignes)

**Moteur de calcul :**
- **Materialisation** de la cohorte cible via `build_cohort_sql()` dans une table temporaire `_pw_target`
- **Collecte d'evenements** : pour chaque "event cohort" (ensemble de concepts definis par l'utilisateur), requete les tables OMOP correspondantes (drug_exposure, condition_occurrence, etc.)
  - Support `include_descendants` via jointure `concept_ancestor`
  - Extraction des paires `(person_id, start_date, end_date, event_name)`
- **Collapse d'eras** : fusionne les intervalles temporels chevauchants d'un meme evenement en eras contigues (avec fenetre de fusion configurable `combo_window`)
- **Construction de sequences** : pour chaque patient, ordonne les eras par date de debut et tronque a `max_depth` etapes
- **Aggregation** : compte les sequences identiques, calcule les pourcentages
- **Arbre sunburst** : construit un arbre hierarchique `{name, value, children}` pour la visualisation
  - Elagage automatique (`min_cell_count`) pour respecter les contraintes de cellules minimum
  - Attribution de couleurs par evenement

**Parametres configurables :**
| Parametre | Default | Description |
|-----------|---------|-------------|
| `max_depth` | 5 | Profondeur max des parcours (1-10) |
| `min_cell_count` | 5 | Seuil minimum de patients par chemin |
| `combo_window` | 0 | Jours pour fusionner les eras chevauchantes |

### Backend — `backend/modules/cohort/router.py` (3 nouveaux endpoints)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/api/cohorts/pathways` | POST | Lance l'analyse en tache de fond (BackgroundTasks) |
| `/api/cohorts/pathways/status/{task_id}` | GET | Polling du statut + resultats |
| `/api/cohorts/pathways/cancel/{task_id}` | POST | Annulation d'une analyse en cours |

**Pattern identique** a celui de la characterization existante : dict en memoire `_pathways_tasks`, progression reportee via callback.

### Frontend — `frontend/src/components/cohort/PathwaysPanel.tsx` (nouveau, 826 lignes)

Composant React complet avec :
- **Event Cohort Builder** : recherche de concepts OMOP, nommage des evenements, toggle descendants
- **Sunburst SVG custom** : graphique en arcs concentriques sans dependance D3, tooltips au survol
- **Legende couleurs** + affichage des sequences selectionnees
- **Table des top pathways** : compte et pourcentage
- **Barre de progression** pendant l'analyse
- **Export CSV** des resultats
- **Panneau settings** (max depth, min cell count, combo window)

### Frontend — Autres fichiers modifies

| Fichier | Modification |
|---------|-------------|
| `frontend/src/pages/CohortPage.tsx` | Nouvel onglet "Pathways" entre Compare et SQL |
| `frontend/src/types/index.ts` | Nouveaux types : `PathwaysResult`, `PathwaysSunburstNode`, `PathwaysEventCohort` |
| `frontend/src/api/client.ts` | 3 fonctions API : `pathways()`, `pathwaysStatus()`, `pathwaysCancel()` |

### Tests — `backend/tests/test_pathways.py` (nouveau, 199 lignes, 11 tests)

| Test | Ce qu'il verifie |
|------|-----------------|
| `test_pathways_missing_criteria` | Rejet si criteres manquants (422) |
| `test_pathways_missing_event_cohorts` | Rejet si event cohorts manquantes (422) |
| `test_pathways_empty_event_cohorts` | Rejet si liste event cohorts vide (422) |
| `test_pathways_invalid_max_depth_*` (x2) | Validation des bornes max_depth (1-10) |
| `test_pathways_status_not_found` | 404 pour task_id inexistant |
| `test_pathways_cancel_not_found` | 404 pour annulation task_id inexistant |
| `test_build_sunburst_tree` | Construction correcte de l'arbre hierarchique |
| `test_build_sunburst_tree_pruning` | Elagage des branches sous le seuil min_cell_count |
| `test_collapse_eras_*` (x2) | Fusion correcte des intervalles temporels |

---

## Commit 3 : Implementation P0/P1 (`d6ec563`)

Ce commit est le plus massif. Il implemente toutes les corrections prioritaires identifiees dans `PLAN_AMELIORATION.md`.

---

### 3.1 SECURITE

#### 3.1.1 [P0] Injection SQL — `backend/modules/concept/router.py`

**Probleme** : Toutes les requetes SQL utilisaient des f-strings pour interpoler le schema et les noms de tables. Un schema malveillant pouvait injecter du SQL arbitraire.

**Solution** :
- Remplacement systematique de tous les f-strings SQL par `psycopg2.sql.SQL` + `sql.Identifier`
- Nouvelle fonction helper `_ident(name)` qui wrap `safe_identifier()` + `psycopg2.sql.Identifier()`
- Le schema est valide via `safe_identifier()` des son obtention dans `_get_conn()`

**Exemple avant/apres** :
```python
# AVANT (vulnerable)
cur.execute(f"SELECT * FROM {schema}.concept WHERE concept_id = %s", [id])

# APRES (securise)
query = psysql.SQL("SELECT * FROM {schema}.concept WHERE concept_id = %s").format(
    schema=_ident(schema)
)
cur.execute(query, [id])
```

**Fichiers modifies** : `backend/modules/concept/router.py` (147 lignes changees — toutes les requetes SQL du fichier)

#### 3.1.2 [P0] Nouveau module `backend/utils/sql_safety.py` (28 lignes)

```python
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def safe_identifier(name: str) -> str:
    """Valide un identifiant SQL (schema/table/colonne).
    Leve ValueError si caracteres non autorises."""
```

**Pourquoi** : Defense en profondeur. Meme les valeurs provenant de `DOMAIN_CONFIG` (statique) ou de champs Pydantic sont validees avant interpolation SQL.

**Utilise par** : `concept/router.py`, `mapping/router.py`, `cohort/pathways.py`, `quality/domains/clinical.py`, `quality/domains/observation_period.py`, `quality/domains/dashboard.py`

#### 3.1.3 [P0] Rate Limiting — `backend/main.py`

**Probleme** : Aucun rate limiting. Tous les endpoints etaient vulnerables au brute-force et DoS.

**Solution** : Installation de `slowapi` avec des limites par endpoint :

| Endpoint | Limite | Raison |
|----------|--------|--------|
| `/api/access-requests` | 5/min | Anti-spam inscription |
| `/api/auth/sse-ticket` | 10/min | Limite creation de tickets SSE |

Le limiter est **desactive en mode test** via `os.getenv("TESTING")` pour ne pas casser la suite de tests.

**Dependance ajoutee** : `slowapi` dans `requirements.txt`

#### 3.1.4 [P0] SSRF Prevention — `backend/modules/cdm_router.py`

**Probleme** : L'utilisateur pouvait enregistrer un CDM pointant vers `localhost`, `169.254.169.254` (metadata cloud), ou d'autres adresses internes.

**Solution** : Nouvelle fonction `_validate_db_host()` (50 lignes) :
- Rejette les hostnames dangereux (`localhost`, `metadata.google.internal`)
- Valide le format hostname (RFC 1123)
- Parse les IP et rejette loopback, link-local, multicast, metadata cloud
- Resout les hostnames et verifie l'IP resolue
- Validateur Pydantic sur `CdmCreateRequest.db_host` et `CdmTestRequest.db_host`

#### 3.1.5 [P1] Hardening des credentials

**Fichier** : `backend/utils/crypto.py`

| Changement | Avant | Apres |
|-----------|-------|-------|
| Permissions fichier cle | `0o644` | `0o600` (lecture owner seul) |
| Source de la cle | Fichier seul | `ENCRYPTION_KEY` env var (prioritaire) puis fichier |
| Echec decryption | Retourne `""` silencieusement | Leve `DecryptionError` explicite |
| Logging | `warning` | `error` |

**Nouvelle classe** : `DecryptionError(Exception)` — permet un traitement specifique dans le handler d'exception global.

#### 3.1.6 [P1] Admin endpoints — Protection par role

**Probleme** : Les endpoints admin (`/api/audit/*`, `/api/admin/*`) n'avaient pas de verification de role au niveau du code. Seul le middleware de routing filtrait, sans defense en profondeur.

**Solution** : Nouvelle fonction `_require_admin(request)` utilisee comme `Depends()` :

```python
def _require_admin(request: Request):
    user = getattr(request.state, "user", {})
    if "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403, detail="Forbidden: admin role required")
```

**Endpoints proteges** (10 au total) :
- `GET /api/audit/logs`
- `GET /api/audit/stats`
- `GET /api/audit/dates`
- `GET /api/audit/export`
- `GET /api/admin/users`
- `POST /api/admin/users/{id}/roles`
- `DELETE /api/admin/users/{id}/roles/{role}`
- `PUT /api/admin/users/{id}/toggle`
- `GET /api/admin/access-requests`
- `POST /api/admin/access-requests/{id}/approve`
- `POST /api/admin/access-requests/{id}/reject`
- `POST /api/admin/users/add`

**Tests** : `backend/tests/test_role_access.py` (153 lignes) — 10+ tests verifiant que chaque role non-admin recoit un 403.

#### 3.1.7 [P1] Mots de passe temporaires securises

**Probleme** : Les mots de passe temporaires lors de la creation d'utilisateurs Keycloak etaient le username lui-meme.

**Solution** : Remplacement par `secrets.token_urlsafe(16)` — genere un mot de passe temporaire cryptographiquement aleatoire de 22 caracteres.

**Fichiers** : `backend/main.py` (approve_access_request, add_user_direct)

#### 3.1.8 [P1] Keycloak admin credentials

**Avant** : Default a `admin/admin` silencieusement.
**Apres** :
- Default a `""` (pas de fallback dangereux)
- Log `WARNING` si les credentials sont `admin/admin`
- Return `None` si credentials vides (pas de tentative de connexion)

#### 3.1.9 [P1] CORS restrictif

```python
# AVANT
allow_methods=["*"],
allow_headers=["*"],

# APRES
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
```

#### 3.1.10 [P1] Production guards — `backend/config.py`

- `ENVIRONMENT=production` + `SECRET_KEY` vide/default → **crash immediat** (`RuntimeError`)
- `ENVIRONMENT=production` + `AUTH_ENABLED=false` → **crash immediat** (`RuntimeError`)
- Nouvelle variable `ENVIRONMENT` (default: `development`)

#### 3.1.11 [P1] Content Security Policy — `frontend/nginx.conf`

```nginx
Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none';
  base-uri 'self'; form-action 'self';"
Strict-Transport-Security "max-age=31536000; includeSubDomains"
Permissions-Policy "camera=(), microphone=(), geolocation=()"
```

#### 3.1.12 [P1] Masquage des erreurs internes

**Probleme** : Les messages d'erreur HTTP exposaient des details internes (stack traces, noms de tables, SQL).

**Solution** : Remplacement systematique dans tous les routers :
```python
# AVANT
raise HTTPException(status_code=500, detail=f"Cohort count error: {e}")

# APRES
logger.exception("Cohort count failed")
raise HTTPException(status_code=500, detail="An internal error occurred during cohort count")
```

**Fichiers modifies** : `cohort/router.py`, `concept/router.py`, `mapping/router.py`

---

### 3.2 PERFORMANCE

#### 3.2.1 Connection Pool OMOP — `backend/db/omop_connector.py` (reecrit, +224 lignes)

**Probleme** : Chaque requete OMOP ouvrait une connexion TCP complete (handshake ~50-100ms) puis la fermait.

**Solution** : Pool de connexions par CDM avec `ThreadedConnectionPool` de psycopg2.

**Architecture** :
```
_pools: dict[str, PoolEntry]     # Cle = "host:port/dbname@user"
  └── PoolEntry
        ├── pool: ThreadedConnectionPool  (min=2, max=20)
        ├── password: str
        └── last_used: float (monotonic)
```

**`PooledConnection`** (proxy transparent) :
- `close()` → retourne la connexion au pool (+ rollback pour nettoyer la session)
- `__getattr__` → forward transparent vers la vraie connexion psycopg2
- `__enter__`/`__exit__` → context manager
- `__del__` → filet de securite si le GC collecte sans close()
- Si la connexion est cassee → `putconn(close=True)` pour la detruire

**Lifecycle** :
- **Creation** : lazy, au premier `get_omop_connection()` pour un CDM donne
- **Eviction** : thread daemon `pool-evictor` toutes les 5 min, supprime les pools idle > 30min
- **Invalidation** : `invalidate_pool(key)` appele lors du update/delete d'un CDM
- **Shutdown** : `close_all_pools()` au shutdown FastAPI

**Variables d'environnement** :
| Variable | Default | Description |
|----------|---------|-------------|
| `OMOP_POOL_MIN_CONN` | 2 | Connexions minimum par pool |
| `OMOP_POOL_MAX_CONN` | 20 | Connexions maximum par pool |
| `OMOP_POOL_IDLE_TIMEOUT` | 1800 | Secondes avant eviction (30 min) |

#### 3.2.2 N+1 Query — Liste des cohortes — `backend/modules/cohort/router.py`

**Probleme** : Pour N cohortes, N requetes individuelles pour obtenir la derniere version.

**Solution** : Une seule requete avec subquery + join :
```python
max_ver_sq = db.query(CohortVersion.cohort_id, func.max(CohortVersion.version))
    .filter(CohortVersion.cohort_id.in_(cohort_ids))
    .group_by(CohortVersion.cohort_id).subquery()

latest_rows = db.query(CohortVersion)
    .join(max_ver_sq, and_(
        CohortVersion.cohort_id == max_ver_sq.c.cohort_id,
        CohortVersion.version == max_ver_sq.c.max_ver,
    )).all()
```

**Impact** : O(1) requete au lieu de O(N).

#### 3.2.3 N+1 Query — Mapping dashboard — `backend/modules/mapping/router.py`

**Probleme** : Boucle `for domain in DOMAIN_CONFIG` avec une requete par domaine pour obtenir le dernier snapshot.

**Solution** : `DISTINCT ON (domain)` en une seule requete :
```python
db.query(AnalysisSnapshot)
    .filter(cdm_name=..., domain.in_(DOMAIN_CONFIG.keys()))
    .order_by(AnalysisSnapshot.domain, AnalysisSnapshot.version.desc())
    .distinct(AnalysisSnapshot.domain)
    .all()
```

#### 3.2.4 Aggregation SQL — Strategy stats — `backend/modules/mapping/router.py`

**Probleme** : Chargement de toutes les `MappingDecision` en memoire Python pour faire des groupby manuels.

**Solution** : Pushdown vers SQL avec `case()` et `func.count()`/`func.avg()` :
```python
db.query(
    MappingDecision.suggestion_source,
    func.count(MappingDecision.id).label("total"),
    func.count(case((MappingDecision.action == "approved", 1))).label("approved"),
    func.avg(MappingDecision.confidence_score).label("avg_confidence"),
    ...
).group_by(MappingDecision.suggestion_source)
```

#### 3.2.5 COUNT(*) OVER() — Recherche concepts — `backend/modules/concept/router.py`

**Probleme** : Deux requetes separees (SELECT + COUNT) sur la meme table avec les memes filtres.

**Solution** : `COUNT(*) OVER() AS _total_count` dans la requete principale — un seul scan.

#### 3.2.6 CTE Attrition — `backend/modules/cohort/router.py`

**Probleme** : N requetes sequentielles pour N etapes d'attrition.

**Solution** : Construction d'un CTE unique :
```sql
WITH step_0 AS (...), step_1 AS (...), step_2 AS (...)
SELECT (SELECT * FROM step_0), (SELECT * FROM step_1), (SELECT * FROM step_2)
```
Avec fallback vers les requetes individuelles si le CTE echoue.

#### 3.2.7 Merge de requetes conformite — `backend/modules/quality/conformity.py`

**Probleme** : 3 requetes separees sur la table `person` (total, unmapped_gender, future_births).

**Solution** : Une seule requete avec `COUNT(*) FILTER (WHERE ...)` :
```sql
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE gender_concept_id = 0 OR gender_concept_id IS NULL) AS unmapped_gender,
    COUNT(*) FILTER (WHERE year_of_birth > EXTRACT(YEAR FROM CURRENT_DATE)) AS future_births
FROM {schema}.person
```

Idem pour `observation_period` : merge de 2 requetes en 1.

#### 3.2.8 Index composites — `backend/db/models.py`

| Table | Index | Colonnes |
|-------|-------|----------|
| `analysis_snapshots` | `ix_snapshots_cdm_domain` | `(cdm_name, domain)` |
| `analysis_snapshots` | `ix_snapshots_cdm_domain_version` | `(cdm_name, domain, version)` |
| `cohort_versions` | `ix_cohort_versions_cohort_version` | `(cohort_id, version)` |
| `mapping_decisions` | `ix_mapping_decisions_cdm_domain` | `(cdm_name, domain)` |
| `mapping_decisions` | `ix_mapping_decisions_cdm_domain_sv` | `(cdm_name, domain, source_value)` |
| `notifications` | `ix_notifications_user_read` | `(username, read)` |

+ Contraintes `UniqueConstraint` correspondantes.

#### 3.2.9 Cache i18n — `backend/main.py`

**Avant** : Lecture du fichier JSON a chaque requete `/api/i18n/{lang}`.
**Apres** : Chargement au demarrage dans `_i18n_cache: dict[str, dict]`, lookup O(1).

---

### 3.3 ARCHITECTURE

#### 3.3.1 Keycloak Middleware ASGI pur — `backend/auth/keycloak.py`

**Probleme** : `BaseHTTPMiddleware` de Starlette bufferise les reponses, ce qui cassait le streaming SSE (Server-Sent Events) sur les endpoints de logs OHDSI.

**Solution** : Reecrit en middleware ASGI natif :
```python
class KeycloakMiddleware:
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # ... validation du token ...
        await self.app(scope, receive, send)  # forward direct, pas de buffering
```

#### 3.3.2 SSE Tickets — `backend/auth/keycloak.py`

**Probleme** : Le token JWT etait passe en query parameter `?token=xxx` pour les connexions EventSource (SSE). Ce token apparaissait dans les logs serveur et l'historique navigateur.

**Solution** : Systeme de tickets a usage unique :
1. Le client appelle `POST /api/auth/sse-ticket` (authentifie) → recoit un ticket UUID
2. Le client se connecte en SSE avec `?ticket=xxx`
3. Le middleware consomme le ticket (one-time-use, TTL 30s)
4. Plus de token JWT dans les URLs

#### 3.3.3 Token Refresh Queue — `frontend/src/api/client.ts`

**Probleme** : Si le token JWT expirait, toutes les requetes en parallele recevaient un 401 et chacune tentait un refresh.

**Solution** : Intercepteur Axios avec queue de requetes :
- La premiere requete 401 lance le refresh
- Les requetes suivantes attendent dans une queue
- Quand le refresh reussit, toutes les requetes en queue sont relancees

#### 3.3.4 Cascade Delete CDM — `backend/modules/cdm_router.py`

Quand un CDM est supprime, suppression en cascade de :
- `AnalysisSnapshot`
- `AnalysisSettings`
- `CohortVersion` (via Cohort)
- `Cohort`
- `MappingDecision`
- `CdmAccess`
- `CdmAccessRequest`
- Pool de connexions OMOP (`invalidate_pool`)

#### 3.3.5 Alembic — Migrations de schema

Nouveaux fichiers :
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/README`

Permet de gerer les migrations de schema de la base interne de maniere versionnee au lieu de `Base.metadata.create_all()`.

---

### 3.4 DEVOPS & INFRASTRUCTURE

#### 3.4.1 GitHub Actions CI — `.github/workflows/ci.yml` (66 lignes)

4 jobs paralleles :
| Job | Actions |
|-----|---------|
| `backend-tests` | Python 3.12, pip install, pytest avec coverage, upload Codecov |
| `frontend-build` | Node 20, npm ci, npm run build |
| `frontend-tests` | Node 20, npm ci, vitest run |
| `docker-build` | docker compose build (smoke test) |

#### 3.4.2 Docker Compose durci — `docker-compose.yml`

| Changement | Detail |
|-----------|--------|
| Credentials parametrises | `POSTGRES_PASSWORD`, `SECRET_KEY` requis (`:?`) |
| Resource limits | Backend 2G/2CPU, Frontend 512M/0.5CPU, DB 1G/1CPU, Keycloak 1G/1CPU |
| Keycloak non-root | Suppression de `user: "0:0"` |
| Healthcheck Keycloak | Ajout d'un healthcheck TCP |
| Hostnames parametrises | `EXTERNAL_HOSTNAME` pour CORS et Keycloak issuer |
| Port DB configurable | `DB_EXTERNAL_PORT` (default 5434) |

#### 3.4.3 Nginx SSE — `frontend/nginx.conf`

Nouveau bloc `location /api/ohdsi/logs/` avec `proxy_buffering off` pour que les evenements SSE soient transmis en temps reel au lieu d'etre bufferises par nginx.

---

### 3.5 TESTS

#### 3.5.1 Refonte `conftest.py`

| Avant | Apres |
|-------|-------|
| SQLite fichier (`test_opal.db`) | SQLite in-memory (`sqlite://`) |
| Pool standard | `StaticPool` (meme DB pour tous les threads) |
| Roles fixes | Headers `X-Test-Roles` et `X-Test-Username` configurables |
| Variable `TESTING` absente | `os.environ["TESTING"] = "1"` |

#### 3.5.2 Nouveaux fichiers de tests

| Fichier | Tests | Ce qu'il couvre |
|---------|-------|----------------|
| `test_pathways.py` | 11 | Validation API, sunburst builder, pruning, collapse eras |
| `test_role_access.py` | 10+ | Defense en profondeur RBAC (403 pour non-admin) |

#### 3.5.3 Tests modifies (adaptation au nouveau conftest)

| Fichier | Nature des changements |
|---------|----------------------|
| `test_admin_api.py` | Adaptation aux headers de role |
| `test_audit_api.py` | Idem |
| `test_access_requests.py` | Idem |
| `test_cdm_access.py` | Fix subquery SAWarning |
| `test_conformity.py` | Adaptation aux requetes conformite mergees |
| `test_crypto.py` | Test de `DecryptionError` au lieu de retour silencieux |
| `test_api.py` | Adaptation mineure |
| `test_cohort_api.py` | Adaptation mineure |
| `test_mapping_api.py` | Adaptation mineure |

#### 3.5.4 Tests frontend — `frontend/src/api/client.test.ts` (67 lignes, 10 tests)

| Test | Verification |
|------|-------------|
| `exports api as default` | Client Axios configure |
| `sets token getter` | `setTokenGetter()` fonctionne |
| `has request timeout` | Timeout 30s configure |
| `has interceptors` | Intercepteurs request/response presents |
| `exports cdmApi` | Module CDM avec `list`, `create`, `delete` |
| `exports qualityApi` | Module qualite avec `analyze` |
| `exports cohortApi` | Module cohorte avec `list`, `create` |
| `exports mappingApi` | Module mapping |
| `exports conceptApi` | Module concepts |

**Dependances ajoutees** : `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` dans `frontend/package.json`

---

## Commit 4 : Fix rate limiter (`55299f4`)

### Quoi
Correction de deux problemes introduits par le commit P0/P1.

### 4.1 Suppression de `default_limits` sur le Limiter

**Probleme** : Le `Limiter` avait un `default_limits=["100/minute"]` qui s'appliquait a TOUS les endpoints, y compris ceux des tests. Meme avec `TESTING=1`, certains tests echouaient.

**Solution** : Suppression du `default_limits`. Les limites explicites sur les endpoints sensibles (`5/minute`, `10/minute`) suffisent.

**Fichier** : `backend/main.py` (1 ligne supprimee)

### 4.2 Fix SAWarning `scalar_subquery()`

**Probleme** : SQLAlchemy emettait un `SAWarning: implicitly coercing SELECT object to scalar subquery` dans `cdm_access_router.py`.

**Solution** : Utilisation de `.scalar_subquery()` explicite au lieu de `.in_()` avec un raw query.

**Fichier** : `backend/modules/cdm_access_router.py` (8 lignes changees)

---

## Dependances ajoutees

### Backend (`requirements.txt`)
| Package | Version | Raison |
|---------|---------|--------|
| `slowapi` | (latest) | Rate limiting |
| `alembic` | (latest) | Migrations de schema |

### Backend (`requirements-dev.txt`) — nouveau fichier
| Package | Raison |
|---------|--------|
| `pytest` | Tests |
| `httpx` | TestClient async |
| `pytest-cov` | Coverage |
| `ruff` | Linting |

### Frontend (`package.json`)
| Package | Raison |
|---------|--------|
| `vitest` | Test runner |
| `@testing-library/react` | Tests composants React |
| `@testing-library/jest-dom` | Matchers DOM |
| `jsdom` | Environnement DOM pour tests |

---

## Variables d'environnement ajoutees

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development` ou `production` — active les guards |
| `ENCRYPTION_KEY` | (none) | Cle Fernet base64 (prioritaire sur fichier) |
| `TESTING` | (none) | `1` ou `true` desactive le rate limiter |
| `OMOP_POOL_MIN_CONN` | `2` | Connexions minimum par pool CDM |
| `OMOP_POOL_MAX_CONN` | `20` | Connexions maximum par pool CDM |
| `OMOP_POOL_IDLE_TIMEOUT` | `1800` | Secondes avant eviction pool idle |
| `APP_DB_POOL_SIZE` | `10` | Taille du pool SQLAlchemy interne |
| `APP_DB_MAX_OVERFLOW` | `20` | Overflow max SQLAlchemy |
| `APP_DB_POOL_RECYCLE` | `1800` | Recyclage connexions SQLAlchemy |
| `KEYCLOAK_ISSUER_URL` | (= `KEYCLOAK_URL`) | URL publique de Keycloak (browsers) |
| `EXTERNAL_HOSTNAME` | `localhost` | Hostname externe (CORS, Keycloak) |
| `DB_EXTERNAL_PORT` | `5434` | Port externe PostgreSQL |

---

## Resume des fichiers touches

### Nouveaux fichiers (8)
| Fichier | Lignes | Role |
|---------|--------|------|
| `backend/modules/cohort/pathways.py` | 346 | Moteur d'analyse de parcours |
| `backend/utils/sql_safety.py` | 28 | Validation identifiants SQL |
| `backend/tests/test_pathways.py` | 199 | Tests pathways |
| `backend/tests/test_role_access.py` | 153 | Tests RBAC defense en profondeur |
| `backend/requirements-dev.txt` | 4 | Dependances de dev |
| `backend/alembic.ini` | 149 | Configuration Alembic |
| `backend/alembic/env.py` | 61 | Script migration Alembic |
| `.github/workflows/ci.yml` | 66 | Pipeline CI GitHub Actions |
| `frontend/src/api/client.test.ts` | 67 | Tests du client API |
| `frontend/src/components/cohort/PathwaysPanel.tsx` | 826 | UI pathways sunburst |

### Fichiers modifies (35+)
Backend : `main.py`, `config.py`, `auth/keycloak.py`, `db/app_db.py`, `db/models.py`, `db/omop_connector.py`, `utils/crypto.py`, `modules/concept/router.py`, `modules/cohort/router.py`, `modules/mapping/router.py`, `modules/cdm_router.py`, `modules/cdm_access_router.py`, `modules/quality/conformity.py`, `modules/quality/domains/clinical.py`, `modules/quality/domains/dashboard.py`, `modules/quality/domains/observation_period.py`, `modules/quality/router.py`, `modules/groups_router.py`, `modules/datamanagement/router.py`, `modules/mapping/suggest.py`, `modules/cohort/sql_builder.py`, `modules/cohort/characterization.py`, 10 fichiers de tests

Frontend : `src/api/client.ts`, `src/pages/CohortPage.tsx`, `src/types/index.ts`, `package.json`

Infra : `docker-compose.yml`, `frontend/nginx.conf`, `.github/workflows/ci.yml`
