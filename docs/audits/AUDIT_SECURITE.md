# Audit de Sécurité — OPAL v1.2.0

**Date** : 2026-03-18
**Périmètre** : Backend (FastAPI), Frontend (React), Infrastructure (Docker Compose, Keycloak)
**Méthodologie** : Revue statique de code, analyse architecturale, vérification OWASP Top 10

---

## Résumé Exécutif

| Sévérité | Nombre |
|----------|--------|
| CRITIQUE | 3 |
| HAUTE | 7 |
| MOYENNE | 8 |
| BASSE | 6 |
| **Total** | **24** |

L'application présente une architecture de sécurité globalement solide (JWT local, RBAC via permissions.yaml, chiffrement Fernet, `psycopg2.sql` pour les requêtes critiques). Toutefois, plusieurs failles significatives demeurent, principalement autour de la construction SQL dans le module pathways, du stockage de tickets SSE non thread-safe, et de l'absence de protection CSRF.

---

## Constats Positifs

- Validation JWT locale avec JWKS et vérification issuer/audience/expiration (`auth/keycloak.py:268-279`)
- RBAC piloté par `permissions.yaml` avec contrôle d'accès par CDM au niveau middleware
- Chiffrement Fernet des mots de passe CDM (`utils/crypto.py`)
- `safe_identifier()` en defense-in-depth pour les identifiants SQL (`utils/sql_safety.py`)
- Protection CSV contre l'injection de formules (`utils/csv_safety.py`)
- Rate limiting sur les endpoints sensibles (SSE tickets : 10/min)
- Masquage des paramètres sensibles dans les logs d'audit (`audit/logger.py:177-183`)
- GZip activé, health checks configurés, CORS paramétrable
- `SECRET_KEY` obligatoire en production avec RuntimeError (`config.py:26-31`)
- `AUTH_ENABLED=false` interdit en production (`config.py:41-45`)
- `PKCE S256` activé côté frontend (`KeycloakContext.tsx:113`)
- Pool de connexions OMOP avec éviction des pools inactifs, rollback systématique

---

## CRITIQUE

### C1 — Injection SQL via f-string dans le module Pathways

**Fichier** : `backend/modules/cohort/pathways.py:94-167`

Le module Pathways utilise des f-strings pour interpoler `omop_schema` et des noms de colonnes/tables provenant de `DOMAIN_CONFIG` dans des requêtes SQL brutes :

```python
# Ligne 94-102
cur.execute(f"""
    CREATE TEMP TABLE _pw_target AS
    SELECT DISTINCT p.person_id,
           op.observation_period_start_date AS cohort_start,
           op.observation_period_end_date   AS cohort_end
    FROM ({cohort_sql}) p
    JOIN {omop_schema}.observation_period op
      ON p.person_id = op.person_id
""")

# Ligne 156-167
cur.execute(f"""
    INSERT INTO _pw_events (...)
    SELECT ... FROM _pw_target tgt
    JOIN {omop_schema}.{table} t ON ...
    WHERE {concept_filter}
""", {"ename": name})
```

Bien que `omop_schema` soit validé par `safe_identifier()` (ligne 79) et que `table`/`cid_col`/`date_col` proviennent de `DOMAIN_CONFIG` (statique), le code mélange des valeurs utilisateur (`cohort_sql`, `concept_filter`) avec des f-strings. `combo_window` (ligne 190) est injecté via `f"INTERVAL '{int(combo_window)} days'"` — le `int()` protège contre l'injection, mais le pattern reste fragile.

**Risque** : Si un futur développeur ajoute un champ dynamique sans validation, l'injection est immédiate. Le `cohort_sql` intègre du SQL construit par `sql_builder.py` qui lui-même utilise des f-strings validées — la chaîne de confiance est longue et difficile à auditer.

**Remédiation** : Migrer vers `psycopg2.sql.SQL` + `sql.Identifier` pour TOUS les identifiants interpolés, comme le fait déjà `conformity.py:76-97`.

**Note complémentaire** : Ce pattern f-string est aussi présent dans :
- `quality/domains/person.py:17-29` — `f"SELECT COUNT(*) AS n FROM {person_table}"`
- `quality/domains/dashboard.py:22-32` — `f"SELECT COUNT(*) AS total FROM {person_table}"`
- `quality/domains/observation_period.py` — multiples f-strings
- `cohort/characterization.py:66-545` — ~15 occurrences de f-strings SQL
- `estimation/router.py:97-99` — construction SQL avec f-strings

Seuls `conformity.py` et `clinical.py` utilisent correctement `psysql.SQL()` + `psysql.Identifier()`. Ceci contredit l'assertion dans CLAUDE.md : *"All SQL identifiers use psycopg2.sql.SQL + sql.Identifier — no f-string SQL anywhere."*

---

### C2 — Stockage de tickets SSE sans synchronisation thread-safe

**Fichier** : `backend/auth/keycloak.py:50-83`

Le dictionnaire `_sse_tickets` est un `dict` Python standard partagé entre les threads de l'application (FastAPI + uvicorn workers) sans aucun verrou :

```python
_sse_tickets: dict[str, tuple[dict, float]] = {}  # Ligne 53

def create_sse_ticket(user_info: dict) -> str:
    global _sse_tickets
    now = time.time()
    expired = [k for k, (_, exp) in _sse_tickets.items() if exp < now]  # Itération sans lock
    for k in expired:
        del _sse_tickets[k]
    if len(_sse_tickets) >= _MAX_SSE_TICKETS:  # Check-then-act sans atomicité
        raise HTTPException(status_code=429, detail="Too many active tickets")
    ticket_id = uuid.uuid4().hex
    _sse_tickets[ticket_id] = (user_info, now + _SSE_TICKET_TTL)
    return ticket_id
```

**Risque** :
- **Race condition** : deux requêtes concurrentes peuvent dépasser `_MAX_SSE_TICKETS`
- **RuntimeError** : itération sur `_sse_tickets.items()` pendant qu'un autre thread modifie le dict (Python 3.x peut lever `RuntimeError: dictionary changed size during iteration`)
- **Fuite mémoire** : si le cleanup échoue (exception), les tickets expirés s'accumulent

**Remédiation** :
```python
import threading
_sse_lock = threading.Lock()

def create_sse_ticket(user_info: dict) -> str:
    with _sse_lock:
        # cleanup + check + insert atomiques
```

---

### C3 — Credentials Keycloak par défaut non bloquées

**Fichier** : `docker-compose.yml:15-16` et `docker-compose.yml:95-96`

```yaml
KEYCLOAK_ADMIN=${KEYCLOAK_ADMIN:-admin}
KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD:-admin}
```

Les credentials par défaut `admin/admin` sont utilisées si aucune variable n'est définie. Contrairement à `SECRET_KEY` et `POSTGRES_PASSWORD` qui utilisent la syntaxe `${VAR:?error}` (obligatoire), les credentials Keycloak utilisent `${VAR:-default}` (optionnel avec fallback).

**Risque** : En production, si l'opérateur oublie de définir ces variables, Keycloak est accessible avec `admin/admin`, permettant la création d'utilisateurs admin arbitraires, la modification des rôles, et l'accès complet à l'application.

**Remédiation** : Utiliser `${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD must be set}` dans `docker-compose.yml`, cohérent avec les autres secrets.

---

## HAUTE

### H1 — Absence de protection CSRF

**Fichier** : `backend/main.py:164-170`

L'application utilise CORS + Bearer tokens JWT. Les requêtes API sont protégées par le header `Authorization`, mais les cookies `SameSite` ne sont pas configurés par le backend, et il n'y a pas de token CSRF double-submit.

**Risque** : Dans un scénario où le token JWT est stocké dans un cookie (possible selon la configuration Keycloak), un site malveillant pourrait déclencher des requêtes cross-origin avec les cookies attachés. Actuellement, le token est dans `localStorage` (via `keycloak-js`), ce qui atténue le risque mais n'est pas garanti sur toutes les configurations.

**Remédiation** : Ajouter un middleware CSRF pour les mutations (POST/PUT/DELETE) ou s'assurer contractuellement que le token n'est jamais dans un cookie.

---

### H2 — Saved Queries : aucune validation du SQL stocké

**Fichier** : `backend/modules/saved_queries_router.py:18-23`

```python
class SaveQueryRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=500)
    sql: str = Field(..., min_length=1)  # Aucune validation ni max_length
    description: str = ""
```

Le SQL est stocké tel quel sans aucune restriction de longueur ni analyse syntaxique. La sauvegarde elle-même n'est pas dangereuse (CRUD pur), mais si ces requêtes sont exécutées ultérieurement via un endpoint d'exécution, elles pourraient contenir du DDL/DML dangereux.

**Risque** : Stockage de payloads SQL arbitrairement volumineux (DoS storage), potentiel XSS si le SQL est affiché sans échappement côté frontend. Si un endpoint d'exécution est ajouté ultérieurement, le SQL stocké sera exécuté tel quel.

**Remédiation** : Ajouter `max_length=50000` au champ `sql`. Si un endpoint d'exécution existe, le wrapper dans un `SET statement_timeout` + rôle read-only.

---

### H3 — IDOR sur les cohortes : pas de vérification d'accès CDM

**Fichier** : `backend/modules/cohort/router.py`

Les endpoints cohort (`GET /{cohort_id}`, `PUT /{cohort_id}`, `DELETE /{cohort_id}`) ne vérifient pas si l'utilisateur a accès au CDM associé à la cohorte. Le middleware Keycloak extrait `cdm_name` des query params ou de patterns de path, mais les routes cohort utilisent des IDs numériques :

```
GET /api/cohorts/42  → pas de cdm_name dans le path → pas de check CDM
```

Le middleware (`keycloak.py:86-106`) ne peut pas extraire `cdm_name` d'un path comme `/api/cohorts/42`, donc le check CDM est court-circuité.

**Risque** : Un utilisateur authentifié peut lire/modifier/supprimer les cohortes de CDMs auxquels il n'a pas accès, en connaissant l'ID numérique.

**Remédiation** : Dans le router cohort, après avoir récupéré la cohorte en base, vérifier que l'utilisateur a accès à `cohort.cdm_name` via la logique de `_check_cdm_access`.

---

### H4 — Keycloak en mode `start-dev` sans HTTPS

**Fichier** : `docker-compose.yml:98-100`

```yaml
- KC_HOSTNAME_STRICT=false
- KC_HOSTNAME_STRICT_HTTPS=false
- KC_HTTP_ENABLED=true
command: start-dev --import-realm
```

Keycloak est démarré en mode développement (`start-dev`) avec HTTP activé et la vérification HTTPS désactivée. Les tokens JWT et credentials transitent en clair sur le réseau.

**Risque** : Man-in-the-middle sur le réseau Docker, interception de tokens. En production, les utilisateurs envoient leurs credentials Keycloak en HTTP.

**Remédiation** : Fournir un `docker-compose.prod.yml` avec `start --optimized`, certificats TLS, et `KC_HOSTNAME_STRICT_HTTPS=true`.

---

### H5 — WebSocket : pas de limite de connexions par utilisateur

**Fichier** : `backend/utils/ws_manager.py:26-31`

```python
async def connect(self, websocket: WebSocket, username: str, roles: list[str] | None = None):
    await websocket.accept()
    self._connections[username].add(websocket)  # Aucune limite
```

Un utilisateur peut ouvrir un nombre illimité de connexions WebSocket (un onglet = une connexion).

**Risque** : Un utilisateur malveillant peut ouvrir des milliers de WebSockets, épuisant la mémoire et les file descriptors du serveur.

**Remédiation** : Ajouter une limite (ex: 10 connexions par utilisateur). Fermer la plus ancienne connexion si la limite est atteinte.

---

### H6 — Communication backend→Keycloak en HTTP interne

**Fichier** : `backend/modules/admin_router.py` (utilise `KEYCLOAK_URL=http://opal-keycloak:8080`)

Les appels API admin vers Keycloak (création d'utilisateurs, attribution de rôles) transitent en HTTP sur le réseau Docker interne. Bien que ce réseau soit isolé, dans un déploiement multi-hôte (Swarm, K8s), le trafic peut traverser des réseaux non chiffrés.

**Remédiation** : Supporter TLS interne ou utiliser un service mesh.

---

### H7 — `_check_cdm_access` crée une session DB non gérée par le cycle de requête

**Fichier** : `backend/auth/keycloak.py:123-152`

```python
def _check_cdm_access(cdm_name: str, user_info: dict) -> bool:
    db = SessionLocal()  # Session créée manuellement
    try:
        # queries...
        return ...
    finally:
        db.close()
```

Cette session est créée en dehors du système de dépendances FastAPI. En cas d'exception non capturée entre `SessionLocal()` et `db.close()`, la session fuit.

**Remédiation** : Utiliser un context manager ou intégrer dans le système `Depends(get_db)`.

---

## MOYENNE

### M1 — Absence de headers de sécurité sur les réponses API

**Fichier** : `backend/main.py`

Le backend ne retourne pas de headers de sécurité :
- Pas de `X-Content-Type-Options: nosniff`
- Pas de `X-Frame-Options: DENY`
- Pas de `Strict-Transport-Security`
- Pas de `Referrer-Policy`

Le frontend Nginx les ajoute probablement, mais les appels API directs (mobile, scripts) ne les reçoivent pas.

**Remédiation** : Ajouter un middleware FastAPI pour les headers de sécurité.

---

### M2 — Rate limiting incomplet

**Fichier** : `backend/main.py:282` — Seul l'endpoint SSE ticket a un rate limit explicite (`10/minute`).

Les endpoints coûteux (analyse qualité, count de cohorte, suggestions de mapping, recherche de concepts) n'ont pas de rate limiting.

**Risque** : DoS applicatif — un utilisateur peut lancer des dizaines d'analyses qualité simultanées.

**Remédiation** : Appliquer des limites sur `/api/quality/analyze` (2/min), `/api/cohorts/count` (10/min), `/api/mapping/suggest` (5/min).

---

### M3 — `safe_identifier` n'a pas de limite de longueur

**Fichier** : `backend/utils/sql_safety.py:16-28`

```python
def safe_identifier(name: str) -> str:
    if not isinstance(name, str) or not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name  # Pas de vérification de longueur
```

PostgreSQL limite les identifiants à 63 caractères. Un identifiant de 10000 caractères passerait la validation.

**Remédiation** : Ajouter `if len(name) > 63: raise ValueError(...)`.

---

### M4 — Log d'audit exclut les opérations admin sensibles

**Fichier** : `backend/audit/logger.py:103`

```python
SKIP_PATHS = {"/api/health", "/api/i18n", "/api/auth", ...}
```

Le préfixe `/api/auth` est exclu, ce qui masque les créations de tickets SSE (`/api/auth/sse-ticket`). De plus, les opérations admin (`POST /api/admin/users`, `DELETE /api/admin/users`) ne sont pas dans `ACTION_MAP` et ne reçoivent qu'un label générique.

**Remédiation** : Retirer `/api/auth` des SKIP_PATHS (ou ne skipper que `/api/auth/me`). Ajouter les actions admin dans `ACTION_MAP`.

---

### M5 — Notification `create` accessible aux data-managers sans restriction de cible

**Fichier** : `backend/modules/notifications_router.py:189-216`

```python
@router.post("/create")
def create_notification(req: CreateNotificationRequest, ...):
    if not any(r in ("admin", "data-manager") for r in user_roles):
        raise HTTPException(403, ...)
    notif = Notification(username=req.username, ...)
```

Un data-manager peut créer une notification pour N'IMPORTE QUEL utilisateur, potentiellement avec un contenu trompeur (phishing interne, faux liens).

**Remédiation** : Restreindre la création de notifications aux admins, ou valider que le data-manager ne peut notifier que les utilisateurs de ses CDMs.

---

### M6 — Docker socket monté dans le container backend

**Fichier** : `docker-compose.yml:31`

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Le socket Docker est monté pour permettre l'orchestration OHDSI. Cela donne au container backend un accès root effectif sur l'hôte Docker.

**Risque** : Si le backend est compromis, l'attaquant peut créer des containers privilégiés, accéder au filesystem hôte, et escalader vers root.

**Remédiation** : Utiliser un proxy Docker avec ACL (ex: Tecnativa/docker-socket-proxy) au lieu du socket brut.

---

### M7 — Keycloak URL hardcodée côté frontend

**Fichier** : `frontend/src/auth/KeycloakContext.tsx:44-47`

```typescript
function getKeycloakUrl(): string {
  const hostname = window.location.hostname;
  return `http://${hostname}:8080`;
}
```

Le port 8080 et le protocole HTTP sont hardcodés. En production avec un reverse proxy ou un port différent, l'authentification échouera.

**Remédiation** : Charger l'URL Keycloak depuis une variable d'environnement Vite (`import.meta.env.VITE_KEYCLOAK_URL`) ou depuis le backend via `/api/config`.

---

### M8 — Pas de validation de l'audience dans les tickets SSE

**Fichier** : `backend/auth/keycloak.py:56-72`

Le ticket SSE contient le `user_info` complet (incluant rôles, username, etc.) mais n'est pas lié à l'IP source ni au User-Agent. Un ticket intercepté peut être utilisé depuis n'importe quel client.

**Remédiation** : Ajouter l'IP source et un hash du User-Agent au ticket, vérifier à la consommation.

---

## BASSE

### B1 — CORS inclut localhost par défaut

**Fichier** : `backend/config.py:54`

```python
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
```

En l'absence de variable d'environnement, les origines localhost sont autorisées. En production, si `CORS_ORIGINS` n'est pas défini, n'importe quelle page sur localhost peut faire des requêtes cross-origin.

---

### B2 — Pas de rotation de clé de chiffrement

**Fichier** : `backend/utils/crypto.py`

Tous les mots de passe sont chiffrés avec la même clé Fernet. Aucun mécanisme de rotation n'existe. Si la clé est compromise, tous les mots de passe le sont.

---

### B3 — Token refresh ne distingue pas erreur réseau vs auth

**Fichier** : `frontend/src/auth/KeycloakContext.tsx:140-143`

```typescript
.catch(() => {
    console.warn('Token refresh failed, logging out');
    keycloak.logout();
});
```

Une erreur réseau temporaire provoque un logout. L'utilisateur perd son travail en cours.

---

### B4 — `AuditMiddleware` hérite de `BaseHTTPMiddleware`

**Fichier** : `backend/audit/logger.py:135`

`BaseHTTPMiddleware` bufferise les réponses, ce qui peut interférer avec le streaming SSE. Le middleware Keycloak utilise correctement un ASGI pur, mais l'audit utilise `BaseHTTPMiddleware`.

---

### B5 — Fichier de clé : race condition théorique

**Fichier** : `backend/utils/crypto.py:31-44`

Le check `SECRET_KEY_FILE.exists()` suivi de `open()` présente une TOCTOU théorique. En pratique, l'impact est faible car le fichier est créé une seule fois au premier démarrage.

---

### B6 — Pas de `Content-Security-Policy` sur les réponses API

Les réponses JSON ne bénéficient pas d'un CSP, bien que l'impact soit faible sur des réponses non-HTML.

---

## Matrice de Remédiation

| ID | Effort | Impact | Priorité |
|----|--------|--------|----------|
| C1 | Moyen | Critique | Semaine 1 |
| C2 | Faible | Critique | Semaine 1 |
| C3 | Trivial | Critique | Semaine 1 |
| H1 | Moyen | Haut | Semaine 2 |
| H2 | Faible | Haut | Semaine 2 |
| H3 | Faible | Haut | Semaine 1 |
| H4 | Moyen | Haut | Semaine 2 |
| H5 | Faible | Haut | Semaine 1 |
| H6 | Moyen | Haut | Semaine 3 |
| H7 | Faible | Moyen | Semaine 2 |
| M1-M8 | Variable | Moyen | Semaine 2-3 |
| B1-B6 | Faible | Bas | Semaine 4+ |
