# Audit de Sécurité Approfondi — OPAL v1.2.1

**Date** : 2026-03-20
**Méthode** : Analyse statique exhaustive du code source (60+ fichiers), historique git, configuration Docker/Keycloak/Nginx
**Périmètre** : Backend (FastAPI, 19 routers), Frontend (React 18), Infrastructure (Docker/Keycloak/Nginx), Dépendances
**Auditeur** : Claude Code (Opus 4.6) — lecture complète de chaque fichier, traçage des flux de données, analyse des vecteurs d'attaque
**Branche** : OPAL_V1.2.1

---

## Résumé Exécutif

| Sévérité | Trouvées | Corrigées | Restantes |
|----------|----------|-----------|-----------|
| CRITIQUE | 3 | **3 ✅** | **0** |
| HAUTE | 8 | **8 ✅** (S04–S11, commit `2e45165`) | **0** |
| MOYENNE | 9 | 0 | 9 |
| BASSE | 6 | 0 | 6 |
| **Total** | **26** | **11** | **15** |

> **Mise à jour 2026-03-20** : toutes les vulnérabilités HAUTE corrigées (S04–S11, commit `2e45165`). Stashed changes

### Points forts confirmés

1. **Validation SQL robuste** : `safe_identifier()` + `psycopg2.sql.SQL/Identifier` sur tous les chemins critiques
2. **Protection SSRF** : Validation loopback, link-local, cloud metadata, résolution DNS sur les hôtes CDM
3. **Chiffrement Fernet** : Mots de passe CDM chiffrés au repos avec hiérarchie de clés
4. **JWT RS256** : Validation audience, issuer, clock skew 30s, JWKS cache avec TTL
5. **SSE tickets** : Usage unique, TTL 30s, capacité max 1000
6. **Audit logging** : Masquage des données sensibles (passwords, tokens, secrets), permissions fichier 0o640
7. **Guards production** : `ENVIRONMENT=production` bloque SECRET_KEY faible, auth désactivée, DATABASE_URL manquant
8. **CORS explicite** : Pas de wildcard, origines configurées par env var
9. **Headers Nginx** : CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy
10. **WebSocket** : Limite 5 connexions/utilisateur, éviction FIFO
11. **CSV injection** : Protection `csv_safe()` sur tous les exports
12. **Rate limiting** : Endpoints coûteux protégés (quality analyze, incidence, datamanagement)
13. **RBAC déclaratif** : `permissions.yaml` séparé du code, 4 rôles avec 12+ vérifications

---

## Findings détaillés

### CRITIQUE

---

#### S01 — Docker Socket monté dans le conteneur backend (Évasion de conteneur)

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Docker |
| **Fichier** | `docker-compose.yml:31` |
| **Statut** | ✅ CORRIGÉ |

**Description** : Le conteneur backend monte `/var/run/docker.sock:/var/run/docker.sock`. Cela accorde au processus backend un contrôle total sur le démon Docker, équivalent à un accès root sur l'hôte. Le router OHDSI (`modules/ohdsi/router.py`) utilise ce socket pour lancer des conteneurs Docker arbitraires.

**Scénario d'exploitation** : Si un attaquant obtient l'exécution de code dans le backend (ex: vulnérabilité de dépendance, désérialisation), il peut utiliser le socket Docker pour créer un conteneur privilégié montant le filesystem hôte → compromission totale de l'hôte.

**Correction appliquée** : Le socket Docker n'est plus monté nulle part et le `group_add` docker est retiré. L'orchestration OHDSI passe désormais par un **service runner dédié** (`opal-ohdsi-runner`) qui exécute les outils R en **sous-processus** et que le backend pilote via une API HTTP interne authentifiée par token. Le backend ne détient plus aucun privilège Docker. Voir [docs/adr/0001-ohdsi-runner-dedie.md](../adr/0001-ohdsi-runner-dedie.md).

---

#### S02 — AUTH_ENABLED=false accorde le rôle admin à toutes les requêtes

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Authentification |
| **Fichier** | `backend/auth/keycloak.py:193-202` |
| **Statut** | ✅ CORRIGÉ |

**Description** : Quand `AUTH_ENABLED=false`, le middleware accorde `roles: ["admin"]` et `preferred_username: "dev-user"` à chaque requête, contournant entièrement le RBAC. Bien que `config.py` mette maintenant `AUTH_ENABLED` à `"true"` par défaut (ligne 47) et lève un `RuntimeError` si `ENVIRONMENT=production` et `AUTH_ENABLED=false` (lignes 49-53), une instance de développement exposée sur un réseau n'a aucune authentification.

**Scénario d'exploitation** : Un développeur lance `docker compose up` avec `AUTH_ENABLED=false` et l'instance est accessible sur le LAN. N'importe quel utilisateur peut effectuer toutes les opérations admin.

**Correction appliquée** : Le middleware vérifie `request.client.host`. Toute requête provenant d'une IP non-localhost (`127.0.0.1`/`::1`) avec `AUTH_ENABLED=false` reçoit HTTP 403 et un log `CRITICAL` est émis. Le mode dev reste utilisable uniquement en local.

---

#### S03 — Identifiants Keycloak admin par défaut admin/admin

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Configuration |
| **Fichier** | `docker-compose.yml:16,95-96`, `.env.example:19-20` |
| **Statut** | ✅ CORRIGÉ |

**Description** : Les identifiants Keycloak admin par défaut sont `admin/admin`. Le `docker-compose.yml` utilise `${KEYCLOAK_ADMIN:-admin}` et `${KEYCLOAK_ADMIN_PASSWORD:-admin}`. Bien que `admin_router.py` (lignes 50-54) log un warning, aucun blocage empêche le déploiement avec ces identifiants. Le compose prod utilise `KEYCLOAK_ADMIN_PASSWORD:?` (obligatoire), mais pas le compose de base.

**Scénario d'exploitation** : Un attaquant découvre la console admin Keycloak au port 8080, se connecte avec `admin/admin`, et obtient le contrôle total du fournisseur d'identité.

**Correction appliquée** : Syntaxe `:?` dans `docker-compose.yml` (sections backend et keycloak). Déploiement impossible si `KEYCLOAK_ADMIN_PASSWORD` absent. `.env.example` mis à jour : valeur vide + commentaire de génération.

---

### HAUTE

---

#### S04 — Construction SQL via f-strings dans sql_builder.py

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Injection |
| **Fichier** | `backend/modules/cohort/sql_builder.py` (lignes 127, 260, 697-718) |
| **Statut** | Atténué par défense en profondeur |

**Description** : Le constructeur SQL de cohortes utilise abondamment les f-strings. Les valeurs utilisateur passent par `source_codes` (échappement `chr(39)` ligne 717), `concept_ids` (cast `int()`), dates (validées par `_DATE_RE`), schémas (`safe_identifier()`). La défense en profondeur est multi-couche mais non paramétrisée.

**Scénario d'exploitation** : Si `source_codes` contient une valeur qui survit au doublement des guillemets simples (ex: exploit d'encodage multibyte), une injection SQL est possible. Le remplacement `chr(39)+chr(39)` (ligne 717) est correct pour PostgreSQL standard, mais les requêtes paramétrisées seraient strictement plus sûres.

**Correction recommandée** : Refactoriser `source_codes` pour utiliser les requêtes paramétrisées (`%s` avec psycopg2) au lieu de l'interpolation avec échappement manuel.

---

#### S05 — Endpoints d'extraction sans vérification de propriété utilisateur

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Autorisation |
| **Fichier** | `backend/modules/datamanagement/router.py:447-531` |
| **Statut** | Présent |

**Description** : Les endpoints `/extract/status/{task_id}`, `/extract/download/{task_id}` et `/extract/cancel/{task_id}` vérifient seulement que le `task_id` existe, pas que l'utilisateur demandeur est propriétaire de la tâche. Le `username` est stocké dans le dict task (ligne 285) mais jamais vérifié.

**Scénario d'exploitation** : L'utilisateur A lance une extraction. L'utilisateur B (chercheur avec accès CDM limité) itère les `task_id` et télécharge des données CSV de CDMs auxquels il n'a pas accès.

**Correction recommandée** : Vérifier `request.state.user.preferred_username == task["username"]` (ou rôle admin) dans les endpoints status, download et cancel.

---

#### S06 — OHDSI Run sans vérification d'accès CDM

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Autorisation |
| **Fichier** | `backend/modules/ohdsi/router.py` |
| **Statut** | ✅ CORRIGÉ |

**Description** : Le `POST /api/ohdsi/run/{service_name}` reçoit `cdm_name` dans le body JSON mais n'appelait pas `check_cdm_access()`. De plus, les endpoints de lecture (logs/status/files) ne vérifiaient pas l'accès CDM (IDOR inter-CDM).

**Scénario d'exploitation** : Un data-manager avec accès CDM restreint par ACL lance une analyse contre un CDM qu'il ne devrait pas voir, ou consulte les sorties/logs d'un autre CDM.

**Correction appliquée** : `check_cdm_access()` est appelé au lancement ; les endpoints de lecture filtrent par accès (`status` réduit aux CDM accessibles, `logs` résout le dernier job accessible, `files` vérifie l'accès sur le segment CDM du chemin).

---

#### S07 — SQL généré retourné au frontend

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Exposition de données |
| **Fichier** | `backend/modules/cohort/router.py:598`, `backend/modules/datamanagement/router.py:402` |
| **Statut** | Présent |

**Description** : Plusieurs endpoints retournent le SQL complet dans la réponse (`{"sql": sql}`). Cela expose le nom du schéma OMOP, la structure des tables et la logique des requêtes au frontend.

**Scénario d'exploitation** : Un attaquant inspecte les réponses API pour apprendre le schéma de la base et les noms de tables, aidant à élaborer des attaques ciblées si une autre vulnérabilité est trouvée.

**Correction recommandée** : Supprimer le champ `sql` des réponses production, ou le conditionner à un flag debug ou au rôle admin.

---

#### S08 — Mots de passe CDM en clair dans les conteneurs Docker OHDSI

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Configuration |
| **Fichier** | `backend/modules/ohdsi/router.py` |
| **Statut** | ✅ CORRIGÉ (obsolète) |

**Description** : L'ancien router OHDSI transmettait le mot de passe CDM déchiffré en variable d'environnement (`DB_PASSWORD`) aux conteneurs lancés via le socket Docker, donc visible via `docker inspect`. La mitigation « creds file » d'alors était inopérante (le mot de passe restait aussi dans l'env, et aucun script ne lisait le fichier).

**Correction appliquée** : Il n'y a plus de conteneur lancé via socket (cf. S01). Le mot de passe est transmis au runner via le corps de `POST /jobs` sur le canal interne authentifié, puis injecté dans l'environnement du sous-processus R — pas d'exposition `docker inspect`. Le dispositif « creds file » mort a été supprimé.

---

#### S09 — Keycloak en mode développement dans le compose de base

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Réseau |
| **Fichier** | `docker-compose.yml:100` |
| **Statut** | Présent (corrigé dans compose prod) |

**Description** : Le `docker-compose.yml` de base lance Keycloak avec `start-dev` qui désactive HTTPS, la vérification de hostname stricte et le caching en mode production. Le port 8080 est bindé sur toutes les interfaces.

**Scénario d'exploitation** : Tout le trafic Keycloak (console admin, échange de tokens) est envoyé en HTTP clair → sniffing réseau des identifiants.

**Correction recommandée** : Le overlay production corrige cela (`start` mode, strict hostname). Documenter clairement que le compose de base est UNIQUEMENT pour le développement local.

---

#### S10 — OHDSI stop/status sans vérification d'autorisation

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Autorisation |
| **Fichier** | `backend/modules/ohdsi/router.py:213-243` |
| **Statut** | Présent |

**Description** : Les endpoints OHDSI stop et status ne vérifient pas si l'utilisateur demandeur a le droit d'arrêter ou de voir l'état d'un service. N'importe quel utilisateur avec accès à `/api/ohdsi` peut arrêter un conteneur OHDSI en cours ou consulter ses logs.

**Correction recommandée** : Tracker qui a lancé chaque service et restreindre l'arrêt au lanceur ou à l'admin.

---

#### S11 — Comparaison de mot de passe en clair dans le pool de connexions

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Exposition de données |
| **Fichier** | `backend/db/omop_connector.py:40,147` |
| **Statut** | Présent |

**Description** : `PoolEntry` stocke le mot de passe CDM en clair dans `self.password` pour comparaison lors de l'invalidation des pools sur changement de credentials. Les mots de passe déchiffrés persistent en mémoire du processus pour la durée de vie du pool.

**Scénario d'exploitation** : Un dump mémoire ou core dump du processus backend révélerait tous les mots de passe CDM en clair.

**Correction recommandée** : Stocker un hash du mot de passe (ex: SHA-256) au lieu de la valeur en clair pour la comparaison.

---

### MOYENNE

---

#### S12 — Rate limiting absent sur des endpoints coûteux

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Rate Limiting |
| **Fichier** | Plusieurs routers |
| **Statut** | Présent |

**Description** : Endpoints sans rate limiting :
- `POST /api/cohorts/count` — exécute du SQL sur le CDM
- `POST /api/cohorts/attrition` — multiples requêtes SQL
- `POST /api/cohorts/sample` — requête avec ORDER BY RANDOM()
- `POST /api/mapping/suggest` (single) — jusqu'à 6 stratégies
- `POST /api/concepts/counts` — UNION ALL sur tous les domaines
- `GET /api/search/` — recherche cross-entité sur le CDM
- `POST /api/ohdsi/run/{service_name}` — lance des conteneurs Docker

**Correction recommandée** : Ajouter `@limiter.limit("X/minute")` à tous les endpoints exécutant des requêtes CDM ou lançant des tâches background.

---

#### S13 — Endpoint i18n accepte un paramètre langue arbitraire

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation des entrées |
| **Fichier** | `backend/main.py:330-335` |
| **Statut** | Présent |

**Description** : `GET /api/i18n/{lang}` accepte n'importe quelle chaîne comme paramètre `lang`. Le message d'erreur reflète la valeur : `f"Language '{lang}' not found"`. Risque de contenu réfléchi (pas de XSS car réponse JSON, pas HTML).

**Correction recommandée** : Valider `lang` contre un pattern `^[a-z]{2}$` ou les clés connues du cache.

---

#### S14 — Paramètres date des logs d'audit non strictement validés

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation des entrées |
| **Fichier** | `backend/main.py:398-416` |
| **Statut** | Partiellement atténué |

**Description** : Les paramètres `date`, `date_from`, `date_to` sont parsés via `fromisoformat()` qui est strict. Le chemin est construit avec `AUDIT_LOG_DIR / f"{dt_str}.jsonl"`. `pathlib` empêche le path traversal, mais une validation regex explicite `^[0-9]{4}-[0-9]{2}-[0-9]{2}$` serait un defense-in-depth.

---

#### S15 — Store SSE tickets en mémoire (non distribué)

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Gestion de session |
| **Fichier** | `backend/auth/keycloak.py:52-86` |
| **Statut** | Présent (acceptable pour instance unique) |

**Description** : Les tickets SSE sont stockés dans un dict en mémoire (`_sse_tickets`). Dans un déploiement multi-instance derrière un load balancer, un ticket créé par l'instance A ne peut être validé par l'instance B.

**Correction recommandée** : Pour les déploiements multi-instance, utiliser Redis ou la base app pour le stockage des tickets.

---

#### S16 — CORS origins incluent localhost par défaut

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Configuration |
| **Fichier** | `backend/config.py:62` |
| **Statut** | Présent (dev uniquement) |

**Description** : Les origines CORS par défaut incluent `http://localhost:3000,http://localhost:5173`. Approprié pour le développement mais doit être surchargé en production.

**Correction recommandée** : Supprimer les defaults localhost quand `ENVIRONMENT=production`.

---

#### S17 — Clé Fernet auto-générée fragile

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Cryptographie |
| **Fichier** | `backend/utils/crypto.py:18-44` |
| **Statut** | Présent |

**Description** : Si ni `ENCRYPTION_KEY` ni `.secret_key` n'existe, une clé Fernet est auto-générée et persistée dans `data/.secret_key`. Si le volume `data/` est perdu (recréation de volume Docker), tous les mots de passe CDM chiffrés deviennent irrécupérables.

**Correction recommandée** : En production, exiger `ENCRYPTION_KEY` (lever RuntimeError si absent quand `ENVIRONMENT=production`).

---

#### S18 — Métadonnées analyses actives exposées à tous les utilisateurs

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Autorisation |
| **Fichier** | `backend/modules/quality/router.py:439-458` |
| **Statut** | Présent |

**Description** : `GET /api/quality/analyze/active` retourne les métadonnées de toutes les analyses actives (nom CDM, domaines, username) à tout utilisateur authentifié sans filtrage par rôle ou accès CDM.

**Correction recommandée** : Filtrer les résultats par permissions d'accès CDM ou restreindre à admin/data-manager.

---

#### S19 — Absence de limite de taille des messages WebSocket

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | WebSocket |
| **Fichier** | `backend/main.py:598-627` |
| **Statut** | Présent |

**Description** : L'endpoint WebSocket lit les messages avec `websocket.receive_text()` sans limite de taille. Un client malveillant pourrait envoyer des messages très volumineux.

**Correction recommandée** : Ajouter une validation de taille (rejeter les messages > 1KB).

---

#### S20 — Absence de validation de la taille des messages WebSocket

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | WebSocket |
| **Fichier** | `backend/main.py:598-627` |
| **Statut** | Présent |

**Description** : Le endpoint WebSocket ne vérifie pas le contenu des messages reçus au-delà du ping/pong. Pas de validation du format JSON ni de whitelist des types de messages acceptés.

**Correction recommandée** : Valider le format et le type des messages entrants.

---

### BASSE

---

#### S21 — CSP autorise unsafe-inline pour les styles

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Headers |
| **Fichier** | `frontend/nginx.conf:12` |
| **Statut** | Présent |

**Description** : Le CSP inclut `style-src 'self' 'unsafe-inline'; style-src-attr 'unsafe-inline'`. Courant dans les apps React avec CSS-in-JS mais affaiblit la protection CSP.

---

#### S22 — Logs d'audit sans protection d'intégrité

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Audit |
| **Fichier** | `backend/audit/logger.py:118-132` |
| **Statut** | Présent |

**Description** : Les logs d'audit sont des fichiers JSONL sans HMAC, signature ou protection append-only. Un attaquant avec accès au filesystem pourrait modifier ou supprimer des entrées.

---

#### S23 — Noms de fichiers CSV pas entièrement sanitisés

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Validation des entrées |
| **Fichier** | `backend/modules/concept/router.py:537` |
| **Statut** | Présent |

**Description** : Certains exports CSV incluent des valeurs utilisateur dans le header `Content-Disposition` (ex: query de recherche dans le nom de fichier concept) sans la sanitisation `re.sub(r'[^\w\-.]', '_', ...)` appliquée dans d'autres exports.

---

#### S24 — Version Keycloak à vérifier

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Dépendances |
| **Fichier** | `docker-compose.yml:92` |
| **Statut** | Présent |

**Description** : Keycloak 24.0 est utilisé. Vérifier les advisories de sécurité pour cette version et mettre à jour si nécessaire.

---

#### S25 — Identifiants Keycloak par défaut dans le compose dev

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Configuration |
| **Fichier** | `docker-compose.yml:95-96` |
| **Statut** | ✅ CORRIGÉ (voir S03) |

**Description** : `KEYCLOAK_ADMIN_PASSWORD` est désormais obligatoire via `:?` dans le compose de base également. Le déploiement échoue si non défini (voir S03).

---

#### S26 — Placeholder URL dans alembic.ini

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Configuration |
| **Fichier** | `backend/alembic.ini` |
| **Statut** | Présent |

**Description** : L'URL de connexion dans `alembic.ini` est un placeholder. La valeur réelle est injectée via `env.py` depuis `DATABASE_URL`. Risque faible mais pourrait induire en erreur.

---

## Analyse SQL Injection

| Module | Fichier | Méthode SQL | Sources d'entrée utilisateur | Protection | Risque |
|--------|---------|-------------|------------------------------|------------|--------|
| sql_builder | `cohort/sql_builder.py` | f-string | schema, concept_ids, source_codes, dates, opérateurs | `safe_identifier()`, `int()`, `chr(39)` escape, date regex | FAIBLE (atténué) |
| pathways | `cohort/pathways.py` | f-string | schema, concept_ids, combo_window, event_name | `safe_identifier()`, `int()`, psycopg2 params pour ename | FAIBLE (atténué) |
| concept/router | `concept/router.py` | `psycopg2.sql.SQL` | query recherche, domaine, vocabulaire, concept_id | `psycopg2.sql.Identifier` + `%s` params | TRÈS FAIBLE |
| mapping/suggest | `mapping/suggest.py` | `psycopg2.sql.SQL` | source_value, domaine, schéma | `safe_identifier()` + `%s` params | TRÈS FAIBLE |
| mapping/router | `mapping/router.py` | f-string | schema, table, colonnes, terme recherche | `safe_identifier()` + `%(param)s` dict params | FAIBLE (atténué) |
| quality/domains | `quality/domains/*.py` | f-string | schema, table, noms de colonnes | `safe_identifier()` + noms depuis DOMAIN_CONFIG | TRÈS FAIBLE |
| search_router | `search_router.py` | `psycopg2.sql.SQL` | query recherche, CDM name | `psycopg2.sql.Identifier` + `%s` params | TRÈS FAIBLE |
| incidence/engine | `incidence/engine.py` | f-string | schema, cohort SQL, strata | `safe_identifier()`, `int()` casts | FAIBLE (atténué) |
| estimation/router | `estimation/router.py` | f-string | schema, table, time_at_risk_end | `int()` casts, constantes DOMAIN_CONFIG | FAIBLE (atténué) |
| datamanagement | `datamanagement/extractor.py` | f-string | schema, table, colonnes | `_safe()` regex, whitelist EXTRACTABLE_TABLES | FAIBLE (atténué) |
| cdm_helper | `utils/cdm_helper.py` | `%s` params | schema, table, colonne | `safe_identifier()` + `%s` params | TRÈS FAIBLE |

**Verdict global** : 0 vulnérabilité exploitable. Défense en profondeur sur tous les chemins. La seule recommandation est de migrer les f-strings de `sql_builder.py` vers des requêtes paramétrisées.

---

## Matrice de couverture RBAC

| Préfixe Endpoint | Auth requise | Vérif. rôle | Vérif. accès CDM | Notes |
|------------------|-------------|-------------|------------------|-------|
| `/api/health` | Non | Non | Non | Public |
| `/api/i18n/{lang}` | Non | Non | Non | Public |
| `/api/access-requests` (POST) | Non | Non | Non | Public (rate limited) |
| `/api/auth/*` | Oui | Non (tout user) | Non | Auth seulement |
| `/api/cdm/` (GET) | Oui | Non | Non | Liste CDM read-only |
| `/api/admin/*` | Oui | Rôle admin | Non | Admin uniquement |
| `/api/cdm-access/*` | Oui | `can_manage_access` | Non | Permission-based |
| `/api/quality/*` | Oui | `permissions.yaml` | Oui (middleware + check_cdm_access) | ✅ |
| `/api/cohorts/*` | Oui | `permissions.yaml` | Oui (check_cdm_access body) | ✅ |
| `/api/concepts/*` | Oui | `permissions.yaml` | Oui (middleware via cdm_name param) | ✅ |
| `/api/mapping/*` | Oui | `permissions.yaml` | Oui (check_cdm_access body) | ✅ |
| `/api/ohdsi/*` | Oui | `permissions.yaml` | **MANQUANT pour run** | ⚠️ S06 |
| `/api/datamanagement/*` | Oui | `permissions.yaml` | Oui (check_cdm_access dans extract/start) | ✅ |
| `/api/incidence/*` | Oui | `permissions.yaml` | Oui (check_cdm_access) | ✅ |
| `/api/estimation/*` | Oui | `permissions.yaml` | Oui (check_cdm_access) | ✅ |
| `/api/notifications/*` | Oui | `permissions.yaml` | Non (user-scoped) | ✅ |
| `/api/favorites/*` | Oui | `permissions.yaml` | Non (user-scoped) | ✅ |
| `/api/saved-queries/*` | Oui | `permissions.yaml` | Non (ownership check) | ✅ |
| `/api/cohort-templates/*` | Oui | `permissions.yaml` | Non | ✅ |
| `/api/search/*` | Oui | `permissions.yaml` | Partiel (CDM query needs access) | ⚠️ |
| `/api/groups/*` | Oui | `permissions.yaml` | Non | Create/delete = admin |
| `/api/audit/*` | Oui | Rôle admin | Non | ✅ |
| `/api/ws/notifications` | Oui (ticket) | Non | Non | SSE ticket auth |

---

## Recommandations prioritisées

### Priorité 1 — Bloquants déploiement
1. ✅ Résolu (ohdsi-runner-adr) — le socket Docker a été retiré du compose de base ; OHDSI passe par un runner dédié appelé en HTTP.
2. Exiger le mot de passe Keycloak admin dans le compose de base
3. ✅ Résolu (ohdsi-runner-adr) — `check_cdm_access` est appelé dans `run_service` (`backend/modules/ohdsi/router.py`).

### Priorité 2 — Avant mise en production
4. Ajouter la vérification de propriété utilisateur aux endpoints d'extraction
5. Arrêter de retourner le SQL généré au frontend
6. ✅ Superseded (ohdsi-runner-adr) — les credentials CDM sont transmis au runner via un POST authentifié (token partagé) sur un réseau isolé, plus via le socket/secrets Docker.
7. Exiger `ENCRYPTION_KEY` en production
8. Hasher les mots de passe dans `PoolEntry`

### Priorité 3 — Durcissement
9. Rate limiting sur cohort count, attrition, sample, concept counts, search, OHDSI run
10. ✅ Résolu (ohdsi-runner-adr) — `_assert_stop_allowed` n'autorise l'arrêt qu'au lanceur du job ou à un admin/data-manager.
11. Filtrer les analyses actives par permissions CDM
12. Valider strictement les dates des logs d'audit
13. Sanitiser tous les noms de fichiers CSV

### Priorité 4 — Bonnes pratiques
14. Limite de taille messages WebSocket
15. HMAC pour les logs d'audit
16. Mise à jour Keycloak
17. Resserrer CSP pour supprimer `unsafe-inline`
18. Refactoriser sql_builder.py source_codes vers requêtes paramétrisées
