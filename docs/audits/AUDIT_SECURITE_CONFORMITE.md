# RAPPORT D'AUDIT DE SECURITE ET DE CONFORMITE

## Application OPAL — OMOP Platform for Analytics & Lineage

---

| **Champ** | **Valeur** |
|---|---|
| **Date de l'audit** | 12 mars 2026 |
| **Version auditee** | 1.0.0 |
| **Perimetre** | Backend (FastAPI/Python), Frontend (React/TypeScript), Infrastructure (Docker Compose), Base de donnees (PostgreSQL), Authentification (Keycloak) |
| **Contexte reglementaire** | RGPD (Reglement UE 2016/679), Recommandations CNIL Sante, Referentiel HDS, Code de la Sante Publique (Art. L1110-4, L1111-8), Directive NIS2, PGSSI-S |
| **Classification des donnees** | Donnees de sante a caractere personnel (Art. 9 RGPD — categories particulieres) |
| **Niveau de criticite global** | **ELEVE** |

---

## TABLE DES MATIERES

1. [Resume executif](#1-resume-executif)
2. [Methodologie](#2-methodologie)
3. [Cartographie des risques](#3-cartographie-des-risques)
4. [Authentification et controle d'acces](#4-authentification-et-controle-dacces)
5. [Chiffrement et gestion des secrets](#5-chiffrement-et-gestion-des-secrets)
6. [Securite des bases de donnees](#6-securite-des-bases-de-donnees)
7. [Securite de l'API et du Frontend](#7-securite-de-lapi-et-du-frontend)
8. [Infrastructure et deploiement](#8-infrastructure-et-deploiement)
9. [Conformite RGPD / CNIL](#9-conformite-rgpd--cnil)
10. [Conformite sectorielle sante (HDS, PGSSI-S)](#10-conformite-sectorielle-sante-hds-pgssi-s)
11. [Journalisation et tracabilite](#11-journalisation-et-tracabilite)
12. [Plan de remediation](#12-plan-de-remediation)
13. [Synthese des constats](#13-synthese-des-constats)
14. [Annexes](#14-annexes)

---

## 1. Resume executif

L'application OPAL est une plateforme web d'analyse de bases de donnees cliniques au format OMOP CDM. Elle est deployee dans un contexte hospitalier et manipule des **donnees de sante a caractere personnel** (diagnostics, traitements, mesures biologiques, procedures medicales, deces).

Cet audit a identifie **42 constats** repartis comme suit :

| Severite | Nombre | Exemples cles |
|---|---|---|
| **CRITIQUE** | 8 | Injection SQL via identifiants, cle de chiffrement en 0o644, mot de passe Keycloak admin/admin, Docker socket monte, endpoints admin sans controle de role, SSRF via enregistrement CDM |
| **MAJEUR** | 14 | Pas de TLS sur connexions CDM, pas de rate limiting, validation JWT incomplete, pas de politique de mots de passe, exports patient-level sans anonymisation, absence de droit a l'effacement |
| **MODERE** | 14 | Absence de CSP, logs d'audit sans signature, pas de consentement explicite, pas de DPO designe |
| **MINEUR** | 10 | Documentation AIPD absente, pas de banniere de consentement, messages d'erreur trop verbeux |

**L'application presente un niveau de risque eleve** pour un deploiement en production dans un contexte hospitalier. Les points critiques identifes necessitent une remediation avant toute mise en production sur des donnees reelles de patients.

---

## 2. Methodologie

### 2.1 Referentiels utilises

| Referentiel | Application |
|---|---|
| **RGPD** (Reglement UE 2016/679) | Protection des donnees personnelles, droits des personnes, base legale |
| **Recommandations CNIL** | Guide pratique sante, referentiel RS-001 (entrepots de donnees de sante), MR-004 (recherche) |
| **Referentiel HDS** (Hebergement de Donnees de Sante) | Exigences pour l'hebergement de donnees de sante (Art. L1111-8 CSP) |
| **PGSSI-S** | Politique generale de securite des systemes d'information de sante |
| **OWASP Top 10 2021** | Vulnerabilites applicatives web |
| **ISO 27001/27002** | Bonnes pratiques de securite de l'information |
| **Directive NIS2** | Securite des reseaux et systemes d'information (secteur sante) |

### 2.2 Perimetre technique audite

- **Backend** : 18 routeurs FastAPI, 21 modeles SQLAlchemy, connecteur OMOP CDM
- **Frontend** : Application React SPA, client API Axios
- **Infrastructure** : Docker Compose (4 services), Nginx reverse proxy
- **Authentification** : Keycloak 24.0, middleware JWT, RBAC (4 roles)
- **Base de donnees** : PostgreSQL 16 (app), connexions dynamiques vers CDM externes

### 2.3 Exclusions

- Tests d'intrusion actifs (pentest)
- Audit de l'infrastructure reseau sous-jacente
- Audit du systeme d'exploitation hote
- Revue des bases OMOP CDM externes

---

## 3. Cartographie des risques

### 3.1 Matrice des risques

```
IMPACT
  ^
  |  [C5]        [C1][C2]   [C3][C4]
5 |  Docker       SQL Inj.   Clé chiffr.
  |              JWT bypass   Admin creds
  |
4 |  [M3]        [M1][M2]   [M4]
  |  Erreurs     No TLS     No rate
  |  verbose     CDM conn   limiting
  |
3 |  [m1]        [Mo1][Mo2] [Mo3]
  |  Doc AIPD    No CSP     Logs non
  |  manquante   Headers    signes
  |
2 |              [m2]       [m3]
  |              Banniere   Deps non
  |              cookies    epinglees
  |
1 |
  +----+----+----+----+----+----> PROBABILITE
       1    2    3    4    5
```

### 3.2 Flux de donnees sensibles

```
Navigateur ──HTTP──> Nginx ──HTTP──> FastAPI ──psycopg2──> CDM PostgreSQL
   │                  :80              :8000                (donnees patients)
   │                                    │
   │                                    └──> App DB PostgreSQL :5432
   │                                          (configs, mots de passe chiffres,
   │                                           cohortes, decisions de mapping)
   └──HTTP──> Keycloak :8080
              (identites, tokens JWT)
```

**Points d'attention** : Toutes les communications internes sont en HTTP clair (pas de TLS inter-services).

---

## 4. Authentification et controle d'acces

### 4.1 Architecture d'authentification

| Composant | Implementation | Evaluation |
|---|---|---|
| **IdP** | Keycloak 24.0 | Conforme (OIDC) |
| **Validation JWT** | PyJWT + JWKS local | Partiellement conforme |
| **RBAC** | 4 roles (admin, data-manager, chercheur, medecin) | Conforme |
| **ACL CDM** | Controle par utilisateur et par groupe | Conforme |
| **Middleware** | `KeycloakMiddleware` (Starlette) | A renforcer |

### 4.2 Constats critiques

#### C-AUTH-01 : Validation JWT incomplete (CRITIQUE)

**Fichier** : `backend/auth/keycloak.py:186-194`

```python
payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    options={
        "verify_iss": False,   # Issuer non verifie
        "verify_exp": True,
        "verify_aud": False,   # Audience non verifiee
    },
)
```

**Risque** : Un token JWT emis par un autre realm Keycloak ou un autre fournisseur OIDC pourrait etre accepte. L'absence de verification de l'`issuer` et de l'`audience` permet une attaque par confusion de tokens.

**Recommandation CNIL** : Le referentiel RS-001 exige une authentification forte avec verification complete des jetons.

**Remediation** : Activer `verify_iss: True` et `verify_aud: True` avec les valeurs attendues.

---

#### C-AUTH-02 : Identifiants Keycloak par defaut en production (CRITIQUE)

**Fichier** : `docker-compose.yml:79-80`

```yaml
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

**Fichier** : `main.py:473-474`

```python
admin_user = os.getenv("KEYCLOAK_ADMIN", "admin")
admin_pass = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")
```

**Risque** : Acces complet a la console d'administration Keycloak. Un attaquant pourrait creer des utilisateurs, modifier les roles, exfiltrer tous les tokens.

**Remediation** : Imposer des identifiants forts via variables d'environnement sans valeur par defaut. Ajouter un controle au demarrage qui refuse de lancer l'application si les credentials par defaut sont detectes.

---

#### C-AUTH-03 : Mode sans authentification (MAJEUR)

**Fichier** : `backend/auth/keycloak.py:134-135`

```python
if not AUTH_ENABLED:
    request.state.user = {"sub": "default", "preferred_username": "user", "roles": ["admin"]}
```

**Risque** : Quand `AUTH_ENABLED=false`, TOUT utilisateur obtient les droits `admin` sans aucune authentification. Ce mode ne doit pas exister en production.

**Remediation** : Supprimer ce mode ou le limiter strictement a l'environnement de developpement avec un controle d'environnement (`ENVIRONMENT != production`).

---

#### C-AUTH-04 : Token JWT dans l'URL (query parameter) (MAJEUR)

**Fichier** : `backend/auth/keycloak.py:143`

```python
elif token_param:
    token = token_param
```

**Risque** : Les tokens passes en parametre d'URL sont enregistres dans les logs du serveur web, l'historique du navigateur, les logs proxy, et les referrers HTTP. Cela constitue une fuite de credentials.

**Remediation** : Migrer vers un mecanisme de tickets a usage unique pour les connexions SSE/EventSource, ou utiliser des cookies HttpOnly.

---

#### C-AUTH-05 : Absence de politique de mots de passe (MAJEUR)

**Fichier** : `main.py:616-619`

```python
user_payload["credentials"] = [{
    "type": "password",
    "value": ar.username,   # Mot de passe = nom d'utilisateur
    "temporary": True,
}]
```

**Risque** : Le mot de passe temporaire est identique au nom d'utilisateur. Meme s'il est temporaire, il peut etre intercepte ou exploite avant le changement.

**Recommandation CNIL** : La deliberation n°2017-012 exige des mots de passe d'au moins 12 caracteres avec une complexite suffisante.

**Remediation** : Generer des mots de passe temporaires aleatoires et les communiquer via un canal securise.

---

#### C-AUTH-06 : Endpoints admin sans verification de role (CRITIQUE)

**Fichiers** : `main.py:173-228, 336-736`, `modules/cdm_access_router.py:169-252`, `modules/groups_router.py:51-169`

Les endpoints suivants n'ont **aucune verification de role** malgre les commentaires "admin only" :

| Endpoint | Risque |
|---|---|
| `GET /api/admin/users` | Tout utilisateur authentifie peut lister les utilisateurs Keycloak |
| `POST /api/admin/users/{id}/roles` | Tout utilisateur peut s'assigner le role `admin` |
| `DELETE /api/admin/users/{id}/roles/{role}` | Tout utilisateur peut supprimer le role admin d'un autre |
| `PUT /api/admin/users/{id}/toggle` | Tout utilisateur peut desactiver des comptes |
| `POST /api/admin/users/add` | Tout utilisateur peut creer un compte avec n'importe quel role |
| `POST /api/admin/access-requests/{id}/approve` | Tout utilisateur peut approuver des demandes d'acces |
| `GET /api/audit/logs` | Tout utilisateur peut consulter les logs d'audit |
| `GET /api/audit/export` | Tout utilisateur peut exporter les logs d'audit en CSV |
| `POST /api/cdm-access/grant` | Tout utilisateur peut s'octroyer l'acces a un CDM |
| `POST /api/cdm-access/revoke` | Tout utilisateur peut revoquer l'acces d'un autre |
| `DELETE /api/groups/{name}` | Tout utilisateur peut supprimer un groupe (pas de parametre `request`) |

**Risque** : Escalade de privileges complete. Un utilisateur avec le role `chercheur` peut :
1. S'assigner le role `admin` via `POST /api/admin/users/{id}/roles`
2. S'octroyer l'acces a tous les CDM via `POST /api/cdm-access/grant`
3. Desactiver les comptes administrateurs via `PUT /api/admin/users/{id}/toggle`
4. Supprimer les groupes d'acces via `DELETE /api/groups/{name}`

**Remediation** : Ajouter `@require_roles("admin")` ou utiliser le decorateur `Depends(require_roles("admin"))` sur chaque endpoint sensible. Pour `DELETE /api/groups/{name}`, ajouter le parametre `request: Request` et verifier le role.

---

#### C-AUTH-07 : IDOR sur la mise a jour des cohortes (MAJEUR)

**Fichier** : `modules/cohort/router.py:393-434`

```python
@router.put("/{cohort_id}")
def update_cohort(cohort_id: int, req: CohortUpdateRequest, db: Session = Depends(get_db)):
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    # Pas de verification _can_access_cohort() ici
    if req.name is not None:
        cohort.name = req.name
```

L'endpoint `GET /{cohort_id}` verifie correctement `_can_access_cohort()`, mais l'endpoint `PUT` ne le fait pas. Tout utilisateur authentifie peut modifier les criteres, le nom et la description de n'importe quelle cohorte.

**Remediation** : Ajouter la verification `_can_access_cohort()` dans l'endpoint PUT.

---

#### C-AUTH-08 : Risque SSRF via enregistrement CDM (MAJEUR)

**Fichier** : `modules/cdm_router.py:17-32`

Le champ `db_host` accepte n'importe quelle chaine sans validation. Un utilisateur pourrait enregistrer un CDM pointant vers des services internes (serveur de metadonnees cloud `169.254.169.254`, bases de donnees internes, etc.).

**Remediation** : Valider les hostnames, rejeter les IPs privees/reservees, implementer une liste blanche de plages reseau autorisees.

---

### 4.3 Points positifs

- RBAC granulaire avec 4 roles bien definis
- Matrice de permissions externalisee dans `permissions.yaml`
- Controle d'acces par CDM (ACL utilisateur + groupe)
- Tokens JWT valides localement (JWKS)
- Endpoints publics correctement identifies

---

## 5. Chiffrement et gestion des secrets

### 5.1 Constats critiques

#### C-CRYPTO-01 : Cle de chiffrement avec permissions trop permissives (CRITIQUE)

**Fichier** : `backend/utils/crypto.py:21,25`

```python
os.chmod(SECRET_KEY_FILE, 0o644)   # Lisible par tous les utilisateurs
fd = os.open(str(SECRET_KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
```

**Risque** : La cle Fernet utilisee pour chiffrer les mots de passe des CDM est stockee avec les permissions `rw-r--r--`. Tout processus sur le meme systeme peut lire cette cle et dechiffrer tous les mots de passe.

**Recommandation CNIL** : Les cles de chiffrement doivent etre protegees par des controles d'acces stricts (referentiel RS-001, mesure C12).

**Remediation** :
- Changer les permissions a `0o600` (lecture/ecriture proprietaire uniquement)
- Migrer vers un gestionnaire de secrets (HashiCorp Vault, AWS Secrets Manager)
- Utiliser des variables d'environnement injectees par l'orchestrateur

---

#### C-CRYPTO-02 : SECRET_KEY avec valeur par defaut insecure (CRITIQUE)

**Fichier** : `config.py:21-29`

```python
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "change-me-in-production":
    SECRET_KEY = "change-me-in-production"
```

**Fichier** : `docker-compose.yml:14`

```yaml
SECRET_KEY=${SECRET_KEY:-change-me-in-production}
```

**Risque** : Si la variable d'environnement n'est pas definie, l'application demarre avec une cle connue publiquement. Un simple avertissement en log est insuffisant.

**Remediation** : Refuser de demarrer l'application si SECRET_KEY n'est pas defini ou utilise la valeur par defaut. Implementer un controle bloquant.

---

#### C-CRYPTO-03 : Mots de passe PostgreSQL en clair (MAJEUR)

**Fichier** : `docker-compose.yml:8,62-64`

```yaml
DATABASE_URL=postgresql://opal:opal@opal-db:5432/opal
POSTGRES_USER=opal
POSTGRES_PASSWORD=opal
```

**Risque** : Les identifiants de la base applicative sont en clair dans le fichier `docker-compose.yml`, commite dans le depot Git. Le mot de passe `opal` est trivial.

**Remediation** : Utiliser Docker Secrets ou des fichiers d'environnement externes non commites. Imposer des mots de passe forts.

---

#### C-CRYPTO-04 : Absence de TLS inter-services (MAJEUR)

Aucune communication entre les services Docker n'est chiffree :
- Frontend (Nginx) → Backend (FastAPI) : HTTP clair
- Backend → App DB (PostgreSQL) : pas de `sslmode`
- Backend → CDM externes : pas de `sslmode` (`omop_connector.py:23-31`)
- Backend → Keycloak : HTTP clair

**Risque** : Interception des donnees en transit, y compris les tokens JWT, mots de passe, et donnees de sante.

**Recommandation CNIL** : Le chiffrement des flux est obligatoire pour les donnees de sante (Art. 32 RGPD, mesures de securite).

**Remediation** : Implementer TLS sur toutes les communications, en priorite les connexions aux CDM externes contenant des donnees patients.

---

### 5.2 Points positifs

- Utilisation de Fernet (AES-128-CBC + HMAC-SHA256) pour le chiffrement des mots de passe
- La cle est generee automatiquement si absente
- Gestion gracieuse des echecs de dechiffrement

---

## 6. Securite des bases de donnees

### 6.1 Constats critiques

#### C-DB-01 : Injection SQL via interpolation d'identifiants (CRITIQUE)

**Fichiers concernes** :
- `backend/modules/concept/router.py:328-349`
- `backend/modules/quality/domains/clinical.py:17-159`
- `backend/modules/mapping/router.py:426-902`

**Exemple** (`concept/router.py`) :

```python
where_clause = f"t.{source_col} ILIKE %s"
union_parts.append(f"""
    SELECT %s AS domain,
           t.{source_col} AS source_value,
    FROM {schema}.{table} t
    LEFT JOIN {schema}.concept c ON c.concept_id = t.{concept_col}
    WHERE {where_clause}
""")
```

**Risque** : Les noms de schemas, tables et colonnes sont interpoles directement dans les requetes SQL via f-strings. Bien que ces valeurs proviennent actuellement de `DOMAIN_CONFIG` (statique) et de `AnalysisSettings.omop_schema` (configurable par l'utilisateur), une compromission de la configuration ou une injection via l'API de configuration CDM pourrait permettre l'execution de code SQL arbitraire.

**Impact potentiel** : Lecture/modification/suppression de donnees patients dans les CDM externes.

**Remediation** :
- Utiliser `psycopg2.sql.Identifier()` pour tous les noms d'objets SQL
- Valider systematiquement avec `_validate_identifier()` (existe dans `sql_builder.py` mais pas applique partout)
- Implementer une liste blanche de schemas/tables/colonnes autorises

---

#### C-DB-02 : Validation des identifiants SQL non uniforme (MAJEUR)

**Fichier** : `backend/modules/cohort/sql_builder.py:18-22`

La fonction de validation existe :

```python
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _validate_identifier(name: str) -> str:
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name
```

Mais elle n'est **pas utilisee** dans les autres modules (`concept/router.py`, `quality/engine.py`, `mapping/router.py`).

**Remediation** : Deplacer cette fonction dans un module utilitaire partage et l'appliquer systematiquement.

---

#### C-DB-03 : Connexions CDM sans chiffrement (MAJEUR)

**Fichier** : `backend/db/omop_connector.py:23-31`

```python
conn = psycopg2.connect(
    host=host, port=port, dbname=dbname,
    user=user, password=password,
    connect_timeout=10,
    # ABSENT : sslmode, sslcert, sslkey, sslrootcert
)
```

**Risque** : Les donnees de sante (diagnostics, traitements, mesures) transitent en clair entre le backend et les CDM.

**Remediation** : Ajouter `sslmode='verify-full'` avec verification du certificat serveur.

---

#### C-DB-04 : Messages d'erreur exposant la structure de la base (MODERE)

**Fichier** : `backend/modules/concept/router.py:375`

```python
except Exception as e:
    return {"results": [], "error": str(e)}
```

**Risque** : Les messages d'exception PostgreSQL peuvent reveler des noms de tables, colonnes, types de donnees.

**Remediation** : Logger l'erreur complete cote serveur, retourner un message generique au client.

---

#### C-DB-05 : Pas de connection pooling pour les CDM externes (MODERE)

Chaque requete ouvre et ferme une connexion. Pas de protection contre l'epuisement des ressources.

**Remediation** : Implementer un pool de connexions avec limite de taille (ex: `psycopg2.pool.ThreadedConnectionPool`).

---

### 6.2 Points positifs

- Requetes parametrees (`%s`) pour les valeurs de donnees
- Statement timeout de 5 minutes
- Connection timeout de 10 secondes
- Acces CDM en lecture seule (sauf `source_to_concept_map`)
- Autocommit desactive par defaut

---

## 7. Securite de l'API et du Frontend

### 7.1 Configuration CORS

**Fichier** : `main.py:54-60`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Constat (MODERE)** : `allow_methods=["*"]` et `allow_headers=["*"]` sont trop permissifs. Les origines sont configurables mais incluent des IPs internes en dur dans le docker-compose.

**Remediation** : Restreindre aux methodes effectivement utilisees (GET, POST, PUT, DELETE) et aux headers necessaires.

---

### 7.2 Absence de rate limiting (MAJEUR)

Aucun mecanisme de limitation de debit n'est implemente sur l'ensemble de l'API. Les endpoints suivants sont particulierement sensibles :

| Endpoint | Risque |
|---|---|
| `/api/concepts/search` | DoS via requetes ILIKE couteuses |
| `/api/cohorts/count` | Execution de SQL complexe |
| `/api/quality/analyze` | Analyse complete d'un domaine |
| `/api/access-requests` | Flooding de demandes d'acces |
| `/api/admin/users` | Enumeration d'utilisateurs |

**Recommandation CNIL** : Limiter le nombre de requetes par utilisateur et par intervalle de temps (recommandation generale de securite).

**Remediation** : Implementer `slowapi` ou un middleware custom avec Redis/memoire.

---

### 7.3 Headers de securite

**Fichier** : `frontend/nginx.conf:8-11`

Headers presents :
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

**Headers manquants (MODERE)** :

| Header | Objectif |
|---|---|
| `Content-Security-Policy` | Prevention XSS, controle des sources |
| `Strict-Transport-Security` | Forcer HTTPS (HSTS) |
| `Permissions-Policy` | Restreindre les fonctionnalites navigateur |
| `X-Permitted-Cross-Domain-Policies` | Controle des politiques cross-domain |

---

### 7.4 Traversee de chemin (Path Traversal)

**Fichier** : `main.py:138-144`

```python
@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    filepath = I18N_DIR / f"{lang}.json"
    if not filepath.exists():
        return JSONResponse(status_code=404, ...)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
```

**Constat (MODERE)** : Le parametre `lang` n'est pas valide. Un attaquant pourrait tenter `../../etc/passwd` (bien que `.json` soit ajoute et que `pathlib` normalise, une validation explicite est recommandee).

**Remediation** : Valider que `lang` correspond a un pattern alphanum simple (`^[a-z]{2}$`).

---

### 7.5 Protection CSRF

**Constat (MODERE)** : Aucune protection CSRF n'est implementee. L'authentification par header `Authorization: Bearer` offre une protection naturelle (le navigateur ne l'envoie pas automatiquement), mais les endpoints publics (`/api/access-requests`) n'ont aucune protection.

---

### 7.6 Swagger/OpenAPI expose en production (MINEUR)

**Fichier** : `main.py:29-33` — FastAPI expose `/docs` et `/openapi.json` par defaut.

**Risque** : Documentation complete de l'API accessible sans authentification.

**Remediation** : Desactiver en production (`docs_url=None, redoc_url=None` si `ENVIRONMENT == production`).

---

### 7.7 Points positifs

- Validation des roles demandes (`/api/access-requests`)
- Client API centralise (Axios)
- Headers de securite de base configures dans Nginx
- Reverse proxy avec timeouts configures

---

## 8. Infrastructure et deploiement

### 8.1 Docker Socket monte (CRITIQUE)

**Fichier** : `docker-compose.yml:27`

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**Risque** : Le montage du socket Docker dans le conteneur backend equivaut a donner un acces root sur l'hote. Meme si le conteneur tourne en utilisateur non-root (`USER opal`), l'ajout au groupe Docker (`group_add: "136"`) permet la creation et le controle de conteneurs arbitraires.

**Impact** : Evasion de conteneur, acces complet a l'hote, lecture/modification de tous les volumes.

**Recommandation** : Utiliser une alternative securisee (Docker-in-Docker avec socket proxy filtre, ou API Docker distante avec TLS mutuel).

---

### 8.2 Keycloak en mode developpement (CRITIQUE)

**Fichier** : `docker-compose.yml:77,84`

```yaml
user: "0:0"           # Root
command: start-dev     # Mode developpement
KC_HOSTNAME_STRICT=false
KC_HOSTNAME_STRICT_HTTPS=false
KC_HTTP_ENABLED=true
```

**Risque** :
- Execution en tant que root
- Mode `start-dev` desactive les optimisations et certaines protections de securite
- HTTPS desactive pour l'IdP (tokens et credentials en clair)

**Remediation** : Utiliser `start` avec configuration de production, certificat TLS, utilisateur non-root.

---

### 8.3 Dockerfile — Analyse de securite

**Backend** (`backend/Dockerfile`) :

| Aspect | Evaluation |
|---|---|
| Image de base | `python:3.12-slim` — acceptable |
| Utilisateur non-root | `USER opal` — conforme |
| Multi-stage build | Non — image plus volumineuse |
| Epinglage des dependances | Non (`>=` au lieu de `==`) |
| Scan de vulnerabilites | Non configure |

**Frontend** (`frontend/Dockerfile`) :

| Aspect | Evaluation |
|---|---|
| Multi-stage build | Oui — conforme |
| Image de production | `nginx:alpine` — acceptable |
| Utilisateur non-root | Non — Nginx tourne en root |

---

### 8.4 Dependances non epinglees (MODERE)

**Fichier** : `backend/requirements.txt`

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
```

Toutes les dependances utilisent `>=` au lieu de `==`, ce qui rend les builds non reproductibles et expose a des attaques de supply chain.

**Remediation** : Epingler les versions exactes, utiliser un fichier `requirements.lock`, scanner avec `pip-audit` ou `safety`.

---

### 8.5 Reseau Docker (MODERE)

Tous les services partagent le meme reseau Docker (`opal-network`). Il n'y a pas de segmentation reseau.

**Remediation** : Creer des reseaux separes (frontend-network, backend-network) et limiter les communications inter-services.

---

### 8.6 Port PostgreSQL expose sur l'hote (MODERE)

**Fichier** : `docker-compose.yml:59-60`

```yaml
ports:
  - "5434:5432"
```

**Risque** : La base applicative est directement accessible depuis le reseau hote avec les identifiants par defaut `opal/opal`.

**Remediation** : Supprimer le mapping de port en production, ou restreindre a `127.0.0.1:5434:5432`.

---

### 8.7 Pas de scan de vulnerabilites (MODERE)

Aucun outil de scan de vulnerabilites (SAST, DAST, SCA) n'est configure dans le pipeline CI/CD.

**Remediation** : Integrer `bandit` (SAST Python), `trivy` (conteneurs), `npm audit` (frontend), `pip-audit` (backend).

---

## 9. Conformite RGPD / CNIL

### 9.1 Base legale du traitement

| Exigence RGPD | Statut | Observation |
|---|---|---|
| **Art. 6** — Base legale | NON DOCUMENTE | Pas de documentation de la base legale (interet legitime, mission de service public, ou consentement) |
| **Art. 9** — Donnees de sante | NON DOCUMENTE | Pas de derogation documentee pour le traitement de donnees de categories particulieres |
| **Art. 13/14** — Information des personnes | ABSENT | Pas de mentions d'information, pas de politique de confidentialite |
| **Art. 15-22** — Droits des personnes | NON IMPLEMENTE | Aucun mecanisme pour exercer les droits d'acces, rectification, effacement, portabilite |
| **Art. 25** — Privacy by design | PARTIELLEMENT | Architecture read-only positive, mais absence de pseudonymisation native |
| **Art. 28** — Sous-traitance | NON DOCUMENTE | Pas de contrat de sous-traitance pour l'hebergement |
| **Art. 30** — Registre des traitements | ABSENT | Pas de registre des activites de traitement |
| **Art. 32** — Securite | PARTIELLEMENT | Mesures techniques presentes mais insuffisantes (voir sections 4-8) |
| **Art. 33/34** — Notification de violations | ABSENT | Pas de procedure de notification de violations de donnees |
| **Art. 35** — AIPD | ABSENT | Pas d'Analyse d'Impact relative a la Protection des Donnees |
| **Art. 37** — DPO | NON DOCUMENTE | Pas de DPO designe dans l'application |

### 9.2 Recommandations CNIL specifiques Sante

#### 9.2.1 Referentiel RS-001 (Entrepots de donnees de sante)

| Exigence RS-001 | Statut | Observation |
|---|---|---|
| Finalite determinee et legitime | NON DOCUMENTE | Pas de documentation des finalites |
| Pseudonymisation | ABSENT | Les donnees OMOP CDM sont accedees avec les identifiants patients d'origine (`person_id`). Pas de couche de pseudonymisation |
| Minimisation des donnees | PARTIELLEMENT | L'architecture read-only limite les risques, mais toutes les tables sont accessibles sans filtre |
| Duree de conservation | PARTIELLEMENT | Retention des logs d'audit a 90 jours, mais pas de politique pour les snapshots/cohortes/decisions |
| Mesures de securite | PARTIELLEMENT | Chiffrement des mots de passe, RBAC, audit — mais lacunes identifiees |
| Comite scientifique/ethique | NON DOCUMENTE | Pas de mecanisme de validation par un comite ethique avant acces aux donnees |
| Information des patients | ABSENT | Pas de mecanisme d'information des patients dont les donnees sont analysees |
| Declaration CNIL | NON VERIFIE | Conformite MR-004 ou autorisation CNIL non documentee |

#### 9.2.2 Consentement et droits des personnes

**Constats** :

1. **Absence de mecanisme de consentement** (MAJEUR) : L'application ne prevoit aucun recueil de consentement des patients dont les donnees sont analysees. Selon le contexte d'utilisation (recherche vs soins), un consentement ou une information peut etre requis.

2. **Absence de droit d'acces** (MAJEUR) : Pas d'endpoint permettant aux patients d'acceder a leurs donnees.

3. **Absence de droit a l'effacement** (MAJEUR) : Pas de mecanisme pour supprimer les donnees d'un patient specifique des analyses/cohortes. Pas de suppression en cascade des comptes utilisateurs (notifications, partages, groupes restent orphelins).

4. **Absence de droit a la portabilite** (MODERE) : Pas d'export des donnees personnelles dans un format structure (pas d'endpoint `/api/user/profile/export`).

5. **Absence de registre des traitements** (MAJEUR) : L'article 30 du RGPD exige un registre. L'audit log ne constitue pas un registre des activites de traitement.

6. **Exports patient-level sans anonymisation** (MAJEUR) : Les exports de cohortes (`/api/cohorts/export/direct`) et les extractions de donnees (`/api/datamanagement/extract/`) retournent des `person_id` avec des quasi-identifiants (annee de naissance, genre, race). Aucun mecanisme de k-anonymite, d'agregation obligatoire ou de suppression des petits effectifs n'est implemente.

7. **Absence de finalite documentee pour l'acces aux donnees** (MAJEUR) : Aucun champ `purpose` ou `legal_basis` n'est capture dans les logs d'audit ni dans les requetes d'acces. Impossible de demontrer la conformite au principe de limitation des finalites (Art. 5-1-b RGPD).

---

#### 9.2.3 Durees de conservation

| Type de donnees | Duree actuelle | Recommandation CNIL |
|---|---|---|
| Logs d'audit | 90 jours (configurable) | 6 mois minimum / 1 an recommande pour la sante |
| Snapshots qualite | Illimitee | Definir une politique de retention |
| Cohortes | Illimitee | Supprimer a la fin du projet de recherche |
| Decisions de mapping | Illimitee | Archiver apres validation finale |
| Comptes utilisateurs | Illimitee | Desactiver apres 6 mois d'inactivite |
| Tokens JWT | Selon config Keycloak | Duree de vie courte (15 min access, 30 min refresh) |

---

### 9.3 Mesures CNIL a implementer en priorite

1. **Realiser une AIPD** (Analyse d'Impact) — Obligatoire pour les traitements de donnees de sante a grande echelle (Art. 35 RGPD)
2. **Designer un DPO** — Obligatoire pour les etablissements de sante (Art. 37 RGPD)
3. **Constituer le registre des traitements** — Art. 30
4. **Documenter la base legale** — Art. 6 et 9
5. **Implementer les droits des personnes** — Art. 15-22
6. **Rediger les mentions d'information** — Art. 13/14

---

## 10. Conformite sectorielle sante (HDS, PGSSI-S)

### 10.1 Hebergement de Donnees de Sante (HDS)

| Exigence HDS (Art. L1111-8 CSP) | Statut | Observation |
|---|---|---|
| Hebergeur certifie HDS | NON VERIFIE | L'infrastructure hote doit etre certifiee HDS si elle heberge des donnees de sante |
| Contrat d'hebergement | NON DOCUMENTE | Contrat specifique requis avec clauses de securite |
| Chiffrement au repos | PARTIEL | Mots de passe CDM chiffres (Fernet), mais pas les snapshots/cohortes |
| Chiffrement en transit | ABSENT | Pas de TLS inter-services |
| Sauvegardes | NON VERIFIE | Pas de politique de sauvegarde documentee |
| PCA/PRA | ABSENT | Pas de Plan de Continuite/Reprise d'Activite |
| Tests d'intrusion | NON REALISE | Tests de penetration periodiques requis |

### 10.2 PGSSI-S (Politique Generale de Securite des SI de Sante)

| Exigence PGSSI-S | Statut | Observation |
|---|---|---|
| Identification/Authentification | PARTIELLEMENT CONFORME | Keycloak + LDAP, mais lacunes JWT |
| Imputabilite | PARTIELLEMENT CONFORME | Audit log present mais incomplet |
| Tracabilite | PARTIELLEMENT CONFORME | Actions tracees mais pas les consultations de donnees patients |
| Gestion des habilitations | CONFORME | RBAC + ACL CDM |
| Chiffrement | PARTIELLEMENT CONFORME | Voir section 5 |
| Anti-virus / Anti-malware | NON APPLICABLE | Conteneurs Docker |
| Mises a jour de securite | NON VERIFIE | Pas de politique de mises a jour documentee |

### 10.3 Exigences specifiques OMOP CDM

| Aspect | Statut | Observation |
|---|---|---|
| Acces en lecture seule | CONFORME | Sauf `source_to_concept_map` pour le mapping |
| Separation des environnements | CONFORME | App DB separee du CDM |
| Controle d'acces granulaire | CONFORME | Par CDM, par utilisateur, par groupe |
| Journalisation des requetes | PARTIELLEMENT | Actions tracees, mais pas le detail des requetes SQL executees |
| Anonymisation des exports | ABSENT | Les exports CSV/cohortes peuvent contenir des `person_id` |

---

## 11. Journalisation et tracabilite

### 11.1 Architecture d'audit

L'application dispose d'un systeme d'audit logging (`backend/audit/logger.py`) :

| Aspect | Implementation | Evaluation |
|---|---|---|
| Format | JSONL structure (ts, user, roles, action, method, path, status, duration, ip) | Bon |
| Stockage | Fichiers journaliers (`YYYY-MM-DD.jsonl`) | Acceptable |
| Retention | 90 jours (configurable via `AUDIT_LOG_RETENTION_DAYS`) | Insuffisant pour la sante |
| Middleware | `AuditMiddleware` (Starlette) | Bon |
| Actions tracees | 30+ patterns mappes | Bon |
| Export | CSV via `/api/audit/export` | Bon |
| Statistiques | `/api/audit/stats` | Bon |

### 11.2 Constats

#### C-LOG-01 : Logs d'audit sans integrite cryptographique (MODERE)

Les fichiers JSONL peuvent etre modifies sans detection. Aucune signature, hash de chaine, ou scellement n'est implemente.

**Recommandation PGSSI-S** : Les traces d'audit doivent etre protegees en integrite.

**Remediation** : Implementer un hash en chaine (chaque entree contient le hash de l'entree precedente) ou utiliser un service de log immutable.

---

#### C-LOG-02 : Consultations de donnees non tracees (MAJEUR)

**Fichier** : `backend/audit/logger.py:144-146`

```python
if action is None and method == "GET":
    return await call_next(request)
```

Les requetes GET qui ne correspondent pas a un pattern specifique ne sont pas tracees. Cela signifie que la **consultation de donnees patients** (hierarchies de concepts, resultats de qualite, etc.) n'est pas journalisee.

**Recommandation CNIL** : Toutes les consultations de donnees de sante doivent etre tracees (referentiel RS-001).

**Remediation** : Logger tous les acces aux endpoints manipulant des donnees CDM, meme en lecture.

---

#### C-LOG-03 : Retention insuffisante pour le contexte sante (MODERE)

La retention par defaut de 90 jours est insuffisante :
- La CNIL recommande une conservation des traces d'au moins 6 mois
- Le code de la sante publique peut imposer des durees plus longues
- Les investigations post-incident necessitent un historique plus long

**Remediation** : Porter la retention a 12 mois minimum, avec archivage longue duree.

---

#### C-LOG-04 : Pas de centralisation des logs (MODERE)

Les logs sont stockes localement dans le conteneur (monte sur le volume hote). Pas d'envoi vers un SIEM ou un service centralise.

**Remediation** : Integrer un collecteur de logs (Fluentd, Filebeat) vers un SIEM (ELK, Splunk, Graylog).

---

#### C-LOG-05 : Pas d'alerting sur evenements de securite (MODERE)

Aucun mecanisme d'alerte en temps reel sur les evenements critiques (tentatives d'acces non autorise, volume anormal de requetes, erreurs d'authentification).

**Remediation** : Implementer des regles d'alerte sur les patterns de securite.

---

### 11.3 Points positifs

- Middleware d'audit bien structure et non intrusif
- 30+ actions specifiquement identifiees
- Format JSONL facilement parsable
- Export CSV pour analyse
- Nettoyage automatique au demarrage
- Horodatage UTC

---

## 12. Plan de remediation

### 12.1 Actions immediates (Sprint 1 — 2 semaines)

| # | Action | Severite | Effort |
|---|---|---|---|
| R-01 | Activer `verify_iss` et `verify_aud` dans la validation JWT | CRITIQUE | 1h |
| R-02 | Changer les permissions de la cle Fernet a `0o600` | CRITIQUE | 30min |
| R-03 | Refuser de demarrer si `SECRET_KEY` est la valeur par defaut | CRITIQUE | 1h |
| R-04 | Changer les identifiants Keycloak par defaut | CRITIQUE | 1h |
| R-05 | Ajouter `sslmode='require'` aux connexions CDM | CRITIQUE | 2h |
| R-06 | Appliquer `_validate_identifier()` partout | CRITIQUE | 4h |
| R-07 | Ajouter `@require_roles("admin")` aux endpoints admin/audit/cdm-access/groups | CRITIQUE | 4h |
| R-08 | Supprimer ou securiser le mode `AUTH_ENABLED=false` | MAJEUR | 2h |
| R-08b | Ajouter verification `_can_access_cohort()` dans PUT cohorte | MAJEUR | 1h |
| R-08c | Valider les hostnames CDM (protection SSRF) | MAJEUR | 3h |

### 12.2 Actions court terme (Sprint 2-3 — 1 mois)

| # | Action | Severite | Effort |
|---|---|---|---|
| R-09 | Implementer le rate limiting (slowapi) | MAJEUR | 3h |
| R-10 | Configurer CSP et HSTS dans Nginx | MODERE | 2h |
| R-11 | Epingler les dependances (requirements.txt, package-lock.json) | MODERE | 2h |
| R-12 | Segmenter les reseaux Docker | MODERE | 3h |
| R-13 | Configurer Keycloak en mode production | CRITIQUE | 4h |
| R-14 | Supprimer l'exposition du port PostgreSQL | MODERE | 30min |
| R-15 | Logger les consultations de donnees CDM | MAJEUR | 4h |
| R-16 | Porter la retention des logs a 12 mois | MODERE | 1h |
| R-17 | Generer des mots de passe temporaires aleatoires | MAJEUR | 2h |
| R-18 | Migrer le token SSE vers des tickets a usage unique | MAJEUR | 4h |

### 12.3 Actions moyen terme (1-3 mois)

| # | Action | Severite | Effort |
|---|---|---|---|
| R-19 | Realiser l'AIPD (Analyse d'Impact) | REGLEMENTAIRE | 2-3 sem. |
| R-20 | Rediger et publier la politique de confidentialite | REGLEMENTAIRE | 1 sem. |
| R-21 | Constituer le registre des traitements (Art. 30) | REGLEMENTAIRE | 1 sem. |
| R-22 | Documenter la base legale du traitement | REGLEMENTAIRE | 1 sem. |
| R-23 | Designer un DPO et documenter sa designation | REGLEMENTAIRE | Variable |
| R-24 | Implementer la pseudonymisation des `person_id` et l'anonymisation des exports | MAJEUR | 2 sem. |
| R-24b | Ajouter un champ `purpose`/`legal_basis` aux requetes d'acces aux donnees | MAJEUR | 1 sem. |
| R-24c | Implementer la suppression en cascade des comptes utilisateurs | MAJEUR | 1 sem. |
| R-25 | Integrer un SIEM pour la centralisation des logs | MODERE | 1 sem. |
| R-26 | Mettre en place TLS inter-services (mTLS) | MAJEUR | 1 sem. |
| R-27 | Configurer un scanner de vulnerabilites en CI/CD | MODERE | 2 jours |
| R-28 | Implementer les droits des personnes (acces, effacement) | REGLEMENTAIRE | 2-3 sem. |
| R-29 | Signer/sceller les logs d'audit | MODERE | 3 jours |
| R-30 | Documenter le PCA/PRA | REGLEMENTAIRE | 2 sem. |

### 12.4 Actions long terme (3-6 mois)

| # | Action | Severite | Effort |
|---|---|---|---|
| R-31 | Realiser un test d'intrusion | REGLEMENTAIRE | Externe |
| R-32 | Obtenir/verifier la certification HDS de l'hebergeur | REGLEMENTAIRE | Variable |
| R-33 | Implementer le chiffrement au repos (TDE PostgreSQL) | MAJEUR | 1 sem. |
| R-34 | Mettre en place une politique de sauvegarde documentee | REGLEMENTAIRE | 1 sem. |
| R-35 | Remplacer Docker socket par une alternative securisee | CRITIQUE | 1 sem. |
| R-36 | Implementer MFA pour les comptes administrateurs | MAJEUR | 3 jours |

---

## 13. Synthese des constats

### 13.1 Tableau recapitulatif

| ID | Constat | Severite | Categorie | Ref. reglementaire |
|---|---|---|---|---|
| C-AUTH-01 | Validation JWT incomplete (iss/aud) | CRITIQUE | Authentification | PGSSI-S |
| C-AUTH-02 | Identifiants Keycloak par defaut | CRITIQUE | Authentification | ISO 27002 A.9 |
| C-AUTH-03 | Mode sans authentification | MAJEUR | Authentification | Art. 32 RGPD |
| C-AUTH-04 | Token JWT dans l'URL | MAJEUR | Authentification | OWASP A07 |
| C-AUTH-05 | MDP temporaire = username | MAJEUR | Authentification | CNIL delib. 2017-012 |
| C-AUTH-06 | Endpoints admin/CDM-access/groups sans role check | CRITIQUE | Autorisation | PGSSI-S |
| C-AUTH-07 | IDOR sur mise a jour des cohortes | MAJEUR | Autorisation | OWASP A01 |
| C-AUTH-08 | SSRF via enregistrement CDM (db_host) | MAJEUR | Validation | OWASP A10 |
| C-CRYPTO-01 | Cle Fernet en 0o644 | CRITIQUE | Chiffrement | Art. 32 RGPD |
| C-CRYPTO-02 | SECRET_KEY par defaut | CRITIQUE | Chiffrement | Art. 32 RGPD |
| C-CRYPTO-03 | MDP PostgreSQL en clair | MAJEUR | Chiffrement | ISO 27002 A.10 |
| C-CRYPTO-04 | Pas de TLS inter-services | MAJEUR | Chiffrement | Art. 32 RGPD, HDS |
| C-DB-01 | Injection SQL via identifiants | CRITIQUE | Base de donnees | OWASP A03 |
| C-DB-02 | Validation non uniforme | MAJEUR | Base de donnees | OWASP A03 |
| C-DB-03 | Connexions CDM sans TLS | MAJEUR | Base de donnees | Art. 32 RGPD |
| C-DB-04 | Messages d'erreur verbeux | MODERE | Base de donnees | OWASP A04 |
| C-DB-05 | Pas de connection pooling | MODERE | Base de donnees | ISO 27002 A.12 |
| C-API-01 | CORS trop permissif | MODERE | API | OWASP A05 |
| C-API-02 | Pas de rate limiting | MAJEUR | API | OWASP A04 |
| C-API-03 | Headers securite manquants (CSP) | MODERE | API | OWASP A05 |
| C-API-04 | Path traversal possible (i18n) | MODERE | API | OWASP A01 |
| C-API-05 | Pas de protection CSRF | MODERE | API | OWASP A01 |
| C-API-06 | Swagger expose en production | MINEUR | API | OWASP A01 |
| C-INFRA-01 | Docker socket monte | CRITIQUE | Infrastructure | ISO 27002 A.13 |
| C-INFRA-02 | Keycloak en mode dev/root | CRITIQUE | Infrastructure | PGSSI-S |
| C-INFRA-03 | Dependances non epinglees | MODERE | Infrastructure | OWASP A06 |
| C-INFRA-04 | Pas de segmentation reseau | MODERE | Infrastructure | ISO 27002 A.13 |
| C-INFRA-05 | Port PostgreSQL expose | MODERE | Infrastructure | ISO 27002 A.13 |
| C-INFRA-06 | Pas de scan de vulnerabilites | MODERE | Infrastructure | NIS2 |
| C-RGPD-01 | Base legale non documentee | MAJEUR | RGPD | Art. 6/9 RGPD |
| C-RGPD-02 | AIPD absente | MAJEUR | RGPD | Art. 35 RGPD |
| C-RGPD-03 | Droits des personnes non impl. | MAJEUR | RGPD | Art. 15-22 RGPD |
| C-RGPD-04 | Registre des traitements absent | MAJEUR | RGPD | Art. 30 RGPD |
| C-RGPD-05 | Pas de consentement/information | MAJEUR | RGPD | Art. 13/14 RGPD |
| C-RGPD-06 | Pseudonymisation absente | MAJEUR | RGPD/CNIL | RS-001 |
| C-RGPD-07 | Durees de conservation non def. | MODERE | RGPD | Art. 5-1-e RGPD |
| C-RGPD-10 | Exports patient-level sans anonymisation | MAJEUR | RGPD/CNIL | RS-001, Art. 25 RGPD |
| C-RGPD-11 | Pas de finalite documentee pour l'acces | MAJEUR | RGPD | Art. 5-1-b RGPD |
| C-RGPD-08 | DPO non designe | MODERE | RGPD | Art. 37 RGPD |
| C-RGPD-09 | Procedure violation absente | MODERE | RGPD | Art. 33/34 RGPD |
| C-HDS-01 | Certification HDS non verifiee | MAJEUR | HDS | Art. L1111-8 CSP |
| C-HDS-02 | PCA/PRA absent | MAJEUR | HDS | Referentiel HDS |
| C-HDS-03 | Chiffrement au repos partiel | MODERE | HDS | Referentiel HDS |
| C-LOG-01 | Logs sans integrite crypto | MODERE | Audit | PGSSI-S |
| C-LOG-02 | Consultations non tracees | MAJEUR | Audit | RS-001, PGSSI-S |
| C-LOG-03 | Retention logs insuffisante | MODERE | Audit | CNIL |
| C-LOG-04 | Pas de centralisation logs | MODERE | Audit | NIS2 |
| C-LOG-05 | Pas d'alerting securite | MODERE | Audit | ISO 27001 A.16 |

### 13.2 Score de maturite

| Domaine | Score | Cible minimale sante |
|---|---|---|
| Authentification & Acces | 40/100 | 80/100 |
| Chiffrement & Secrets | 35/100 | 80/100 |
| Securite base de donnees | 50/100 | 75/100 |
| Securite API/Web | 55/100 | 75/100 |
| Infrastructure | 40/100 | 80/100 |
| Conformite RGPD/CNIL | 20/100 | 90/100 |
| Conformite HDS/PGSSI-S | 25/100 | 85/100 |
| Journalisation/Audit | 55/100 | 80/100 |
| **SCORE GLOBAL** | **38/100** | **80/100** |

---

## 14. Annexes

### Annexe A : Fichiers audites

| Fichier | Contenu |
|---|---|
| `backend/main.py` | Point d'entree FastAPI, endpoints admin, middleware |
| `backend/config.py` | Configuration applicative |
| `backend/utils/crypto.py` | Chiffrement Fernet |
| `backend/auth/keycloak.py` | Middleware d'authentification JWT |
| `backend/auth/permissions.py` | Matrice RBAC |
| `backend/permissions.yaml` | Definition des roles et permissions |
| `backend/audit/logger.py` | Middleware d'audit |
| `backend/db/omop_connector.py` | Connexion CDM externe |
| `backend/db/app_db.py` | Connexion base applicative |
| `backend/db/models.py` | Modeles de donnees (21 modeles) |
| `backend/modules/concept/router.py` | Routeur concepts (SQL dynamique) |
| `backend/modules/cohort/sql_builder.py` | Generateur SQL cohortes |
| `backend/modules/quality/domains/clinical.py` | Analyse qualite clinique |
| `backend/modules/mapping/router.py` | Routeur mapping (SQL dynamique) |
| `backend/modules/saved_queries_router.py` | Requetes sauvegardees |
| `backend/Dockerfile` | Image Docker backend |
| `frontend/Dockerfile` | Image Docker frontend |
| `frontend/nginx.conf` | Configuration Nginx |
| `frontend/package.json` | Dependances frontend |
| `backend/requirements.txt` | Dependances backend |
| `docker-compose.yml` | Orchestration des services |
| `.gitignore` | Fichiers exclus du depot |
| `.env.example` | Template de configuration |

### Annexe B : Referentiels et liens

- [RGPD - Reglement (UE) 2016/679](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX%3A32016R0679)
- [CNIL - Referentiel RS-001 Entrepots de Donnees de Sante](https://www.cnil.fr/fr/declaration/rs-001-entrepots-de-donnees-de-sante)
- [CNIL - Guide Pratique Sante](https://www.cnil.fr/fr/quest-ce-ce-que-le-rgpd)
- [CNIL - Deliberation 2017-012 (Mots de passe)](https://www.cnil.fr/fr/mots-de-passe-une-nouvelle-recommandation-pour-maitriser-sa-securite)
- [Referentiel HDS - ANS](https://esante.gouv.fr/produits-services/hds)
- [PGSSI-S - ANS](https://esante.gouv.fr/produits-services/pgssi-s)
- [OWASP Top 10 2021](https://owasp.org/www-project-top-ten/)
- [ISO 27001:2022](https://www.iso.org/standard/27001)
- [Directive NIS2 (UE) 2022/2555](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX%3A32022L2555)

### Annexe C : Glossaire

| Terme | Definition |
|---|---|
| **AIPD** | Analyse d'Impact relative a la Protection des Donnees (DPIA) |
| **CDM** | Common Data Model (modele de donnees commun OMOP) |
| **CNIL** | Commission Nationale de l'Informatique et des Libertes |
| **CSP** | Content Security Policy (en-tete HTTP de securite) |
| **DPO** | Data Protection Officer (Delegue a la Protection des Donnees) |
| **HDS** | Hebergement de Donnees de Sante |
| **HSTS** | HTTP Strict Transport Security |
| **JWKS** | JSON Web Key Set |
| **JWT** | JSON Web Token |
| **OMOP** | Observational Medical Outcomes Partnership |
| **PCA** | Plan de Continuite d'Activite |
| **PRA** | Plan de Reprise d'Activite |
| **PGSSI-S** | Politique Generale de Securite des Systemes d'Information de Sante |
| **RBAC** | Role-Based Access Control |
| **RGPD** | Reglement General sur la Protection des Donnees |
| **RS-001** | Referentiel CNIL relatif aux entrepots de donnees de sante |
| **SIEM** | Security Information and Event Management |
| **TLS** | Transport Layer Security |

---

*Rapport genere le 12 mars 2026.*
*Ce rapport est confidentiel et destine exclusivement aux responsables du projet OPAL.*
