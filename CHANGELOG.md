# CHANGELOG — OPAL

---

## v3.3.0 (2026-05-29)

> **Tag** : `v3.3.0`
> **Base** : `v3.2.0` (`e969579`)

### Fonctionnalites

- **Schemas OMOP par categorie** (`backend/utils/cdm_helper.py`, `backend/config.py`, `frontend/src/components/SchemaCategoriesEditor.tsx`) : un CDM peut desormais lire chaque categorie de tables OMOP (clinical, vocabulary, derived, metadata…) depuis un schema PostgreSQL different. Nouveau helper `SchemaMap`/`build_schema_map(cdm, settings)` (sous-classe `str`, retombe sur `omop_schema` sans override → 100% retrocompatible), colonnes `schema_categories` JSON nullable sur `cdm_configs` et `analysis_settings`, editeur dedie dans Gestion CDM / Reglages. Tous les domaines Quality, `conformity.py` et OHDSI resolvent le schema par categorie. (`2cbfa28`, `60a236f`, merge `8486b22`)
- **Runner OHDSI dedie — suppression du socket Docker** (`ohdsi-tools/runner/`, `backend/modules/ohdsi/router.py`, `docker-compose.yml`) : l'orchestration OHDSI par montage du socket Docker est remplacee par un service `opal-ohdsi-runner` (FastAPI) qui execute les outils R (Achilles, DQD, CDM Onboarding, Achilles Export) en **sous-processus**, pilote par le backend via une API HTTP interne authentifiee par token. Le backend ne detient plus aucun privilege Docker. **Opt-in** : `OHDSI_MODE=off` par defaut (onglet masque), `OHDSI_MODE=on` + profil compose `ohdsi` pour activer. Voir [ADR 0001](docs/adr/0001-ohdsi-runner-dedie.md). (`7f71eb8`, `eebafee`, merge `591d8bd`)
- **Export CSV de l'historique de mapping** (`backend/modules/mapping/router.py`, `frontend/src/pages/MappingPage.tsx`) : `GET /api/mapping/history/{cdm_name}/export` + bouton « Export CSV » dans la vue historique (respecte les filtres domaine/action/utilisateur). (`4062a91`, merge `bf4412f`)

### Securite

- **S01 (CRITIQUE) corrige** : le socket Docker (`/var/run/docker.sock`) et le `group_add` docker sont retires du backend. Une compromission du backend ne donne plus un acces root-hote. (`591d8bd`)
- **Annulation OHDSI robuste** : `cancel` envoie `SIGTERM` puis **escalade en `SIGKILL`** apres 10s au groupe de process (R + JVM enfants) si l'outil ignore le signal. (`591d8bd`)

### Migrations

- Alembic `f6a7b8c9d0e1` : ajout des colonnes `schema_categories` JSON **nullable** sur `cdm_configs` et `analysis_settings`. Additif et non destructif ; auto-ALTER idempotent au demarrage pour les bases existantes.

### Corrections

- **OHDSI respecte l'override de schema des AnalysisSettings** (`build_schema_map(cdm, settings)`) au lieu du schema d'enregistrement brut — remarque revue Codex. (`591d8bd`)
- **`OHDSI_RUNNER_TOKEN` ne casse plus les commandes compose hors profil** : passage de `${VAR:?}` (obligatoire, interpole pour TOUTE commande meme hors profil) a `${VAR:-}`. L'obligation est appliquee au runtime (runner + garde production). (`4d4d468`)
- **Tests perimes corriges** : `test_extractor.py` (import `_agg_expr` supprime) et le test de timeout frontend — la suite repasse au vert. (`4062a91`)

### Notes de deploiement

- OHDSI est desormais **opt-in et desactive par defaut**. Pour l'activer : `OHDSI_MODE=on` + `OHDSI_RUNNER_TOKEN` (`openssl rand -hex 32`) dans `.env`, puis `docker compose --profile ohdsi up -d --build`. Voir [.env.example](.env.example) et README §6.

---

## v3.2.0 (2026-05-28)

> **Tag** : `v3.2.0` → commit `e969579`
> **Base** : `v3.1.0`

### Fonctionnalites

- **Restructuration de la page Cohort (V2)** (`frontend/src/pages/CohortPage.tsx`) : onglets Builder / Analyse, navigation au survol, layout adapte au viewport, tiroir « Results » repliable, barre superieure sur une seule ligne. (`6bb6d23`, `4a4087e`, `077d439`)

### Securite / Authentification

- **Keycloak** : changement de mot de passe force a la premiere connexion de l'admin ; le mot de passe admin par defaut respecte la policy du realm. (`466341a`, `e969579`)

### Documentation

- Bascule de l'installation vers le workflow `.env` ; `.env.example` synchronise avec `docker-compose.yml`. (`708dc70`, `97c7fbd`)

---

## v3.1.0 (2026-05-23)

> **Tag** : `v3.1.0` → commit `d1470ea`
> **Base** : `v3.0.0`

### Fonctionnalites

- **Multi-select Mapping Manual** (`frontend/src/pages/MappingPage.tsx`) : selection de plusieurs codes source via cases a cocher pour les mapper vers le meme `target_concept_id` en une seule action. La selection persiste entre les pages, l'approbation itere `mappingApi.decide` via `Promise.allSettled` (succes partiels toleres). Le panneau Step 2 s'adapte : 1 selectionne → vue detaillee + suggestions ; N>1 → liste compacte + lookup manuel uniquement. (`bc38045`)
- **Recherche case+accent insensible partout** (`backend/utils/text_search.py`) : nouveau helper `iaccent_ilike()` produisant `unaccent(col) ILIKE unaccent(pattern)`. Applique a toutes les recherches par mot-cle (concept names, source values, cohortes, mapping decisions, suggestions). "Meta" et "Meta" renvoient desormais les memes resultats. Extension PostgreSQL `unaccent` requise sur l'app DB (migration Alembic `e5f6a7b8c9d0`) et sur chaque CDM (action admin manuelle). UDF Python enregistree sur SQLite pour les tests. (`6c8b19f`)
- **Pagination des resultats Manual Mapping** (`frontend/src/pages/MappingPage.tsx`) : ajout de pagination sur la recherche de codes source (page size 50) — auparavant limite a 20 resultats sans pagination. (`2cca594`)
- **Badges "pending" dans Concept Explorer + Mapping** (`backend/modules/concept/router.py`, `backend/modules/mapping/router.py`) : les valeurs source ayant une decision approved/modified dans OPAL mais pas encore appliquee au CDM sont signalees avec un badge orange et un surlignage de ligne `bg-orange-500/8`. Evite de re-mapper des codes deja decides. (`f835d84`, `4d8dd07`)
- **Tooltip "Reason" viewport-aware dans Mapping History** (`frontend/src/pages/MappingPage.tsx`) : le tooltip detecte l'espace disponible au-dessus/en-dessous de la ligne et bascule pour ne plus etre tronque par le bas de l'ecran. (`f835d84`)

### Securite

- **`cryptography` 46.0.5 → 46.0.7** (`backend/requirements.txt`) : corrige le buffer overflow avec buffers non-contigus (Moderate) et l'enforcement incomplet des contraintes DNS sur les peer names (Low). (`d1470ea`)
- **`python-multipart` 0.0.22 → 0.0.27** (`backend/requirements.txt`) : corrige le DoS via headers multipart non bornes (**High**) et le DoS via large preamble/epilogue (Moderate). (`d1470ea`)

### Migrations

- Migration Alembic `e5f6a7b8c9d0` : `CREATE EXTENSION IF NOT EXISTS unaccent` sur l'app DB (no-op sur SQLite tests).

---

## v1.2.1 (2026-03-20)

> **Branche** : `OPAL_V1.2.1`
> **Base** : `OPAL_V1.2.0`
> **Periode** : 18–20 mars 2026

### Securite

- **S04** (`sql_builder.py`) : Remplacement de l'echappement manuel des `source_codes` par l'adapteur psycopg2 (`psycopg2.extensions.adapt`) — meme mecanisme que les requetes parametrees `%s`. (`2e45165`)
- **S05** (`datamanagement/router.py`) : Verification de propriete sur `/extract/status`, `/extract/download`, `/extract/cancel` — seul le lanceur ou un admin/data-manager y a acces. (`2e45165`)
- **S06** (`ohdsi/router.py`) : `check_cdm_access()` ajoute au debut de `run_service`. (`2e45165`)
- **S07** (`cohort/router.py`, `datamanagement/router.py`) : Champ `sql` supprime des reponses `/cohorts/count` et des resultats d'extraction. (`2e45165`)
- **S08** (`ohdsi/router.py`) : Mot de passe CDM ecrit dans un fichier temporaire (chmod 0600) monte en lecture seule dans le conteneur OHDSI, supprime apres demarrage. `DB_PASSWORD` n'apparait plus dans `docker inspect`. (`2e45165`)
- **S09** (`docker-compose.yml`) : Port Keycloak lie a `127.0.0.1:8080`. Warning developpement ajoute. (`2e45165`)
- **S10** (`ohdsi/router.py`) : `launched_by` enregistre dans `_tasks`. Arret via `/stop/{service}` restreint au lanceur ou admin. (`2e45165`)
- **S11** (`db/omop_connector.py`) : `PoolEntry` stocke uniquement un hash SHA-256 du mot de passe (plus de plaintext). (`2e45165`)
- **AUTH_ENABLED defaut `true`** : le mode non-authentifie n'est plus le defaut. Un `RuntimeError` est leve en production si `AUTH_ENABLED=false` (`config.py`, `9aa1d2f`)
- **Rate limiting** : ajout de limites sur les endpoints couteux — quality analyze (3/min), batch stream (2/min), CDM test (5/min), cohorts execute (10/min), mapping suggest batch (3/min), incidence (3/min), estimation (3/min), characterize (3/min), pathways (3/min), conformity (3/min) (`9aa1d2f`)

### Fonctionnalites

- **F02** (`config.py`) : Correction du domaine Note — `note_source_value` et `note_source_concept_id` ne sont pas des colonnes OMOP CDM v5.4 standard. Mis à `None`, gérés gracieusement par `cdm_helper.py`.
- **F03** (`db/models.py`, `alembic/versions/`) : Ajout de `ForeignKey("cohorts.id", ondelete="CASCADE")` sur `CohortVersion.cohort_id` et `CohortShare.cohort_id`. Migration Alembic `b1c2d3e4f5a6` ajoutée.
- **F04** (`frontend/src/api/client.ts`) : Ajout de `delete` dans `incidenceApi` et `estimationApi` pour aligner le frontend sur les endpoints `DELETE /api/incidence/{id}` et `DELETE /api/estimation/{id}` du backend.
- **F05** (`backend/i18n/`, `frontend/src/i18n/`) : Ajout des traductions manquantes pour les domaines `Specimen`, `Note` et `Payer_Plan_Period` dans les 4 fichiers i18n (EN/FR).
- **F08** (`modules/cdm_router.py`) : Nettoyage des `UserFavorite` référençant un CDM supprimé lors du cascade delete.
- **F10** (`modules/concept_set/router.py`) : Bypass admin ajouté aux endpoints `update` et `delete` des concept sets — les admins peuvent gérer les concept sets de tous les utilisateurs.
- **Colonnes optionnelles** : detection dynamique des colonnes `source_name` dans le CDM via `cdm_helper.get_domain_config()`. Les domaines dont le CDM ne contient pas certaines colonnes optionnelles fonctionnent gracieusement (`0288819`, `3180cfb`)
- **Warnings mapping** : le moteur de suggestions retourne un tableau `warnings` indiquant les limitations rencontrees (`source_name_missing`, `no_reference_codebook`, `no_sapbert_embeddings`, `source_names_empty`) (`1d006e1`, `3712ecd`)
- **Mapping UX** : meilleurs etats vides, error toasts, warnings affiches dans l'interface (`3712ecd`, `874a92d`)

### Optimisation

- **N+1 query fix** : optimisation des requetes quality engine pour eviter les requetes N+1 (`9aa1d2f`)
- **Thread pool borne** : `MAX_WORKER_THREADS` (defaut 16) remplace les threads non-bornes (`0d45e01`)
- **Nettoyage in-memory** : daemon de nettoyage des taches perimees toutes les 5 min (`0d45e01`)

### UX / Style

- **Login page** : fond avec grille de points, formulaire simplifie (matricule + role uniquement), espacement ameliore (`2d0859d`, `874a92d`)
- **TopNav** : affichage logo uniquement (pas le nom complet) (`874a92d`)
- **Listes** : espacement ameliore dans les listes de mapping et suggestions (`2d0859d`)

### Tests

- **+27 tests** : `test_csv_safety.py`, `test_thread_pool.py` couvrant les lacunes identifiees (`0fdde24`)
- **Nouveaux fichiers** : `test_ohdsi_router.py`, `test_rate_limit.py`, `test_sql_safety.py`

### Audits

- **3 audits exhaustifs** remplaces : securite (26 findings), optimisation (25 findings), fonctionnel (28 findings) — tous mis a jour pour v1.2.1 (`docs/audits/`)
- Resolution des findings CRITIQUE et HAUTE des audits precedents (`9534240`, `605961f`, `0d45e01`)

### Documentation

- **Mise a jour complete** : README, API.md, TECHNICAL.md, USER_GUIDE.md, METHODOLOGIE.md, WEBSOCKET_NOTIFICATIONS.md alignes avec le code actuel
- 29 endpoints manquants ajoutes a API.md
- 13 schemas de modeles corriges dans TECHNICAL.md
- Navigation sidebar → TopNav refletee dans toute la doc

### Commits

| Hash | Description |
|------|-------------|
| `9aa1d2f` | fix(security): AUTH_ENABLED default true, rate limiting, N+1 query optimization |
| `874a92d` | style: login page polish, TopNav logo only, mapping warnings UX |
| `2d0859d` | style: polish Login page, improve list spacing |
| `3180cfb` | Merge branch 'backend-optional-columns' into OPAL_V1.2.1 |
| `1d006e1` | feat: add warnings to mapping suggestion responses |
| `3712ecd` | feat: mapping suggestion warnings, better empty states, error toasts |
| `0288819` | fix: optional source_name columns and dynamic domain detection |
| `0fdde24` | test: add 27 tests for csv_safety and thread_pool |
| `0d45e01` | fix: resolve MOYENNE audit findings |
| `605961f` | fix: resolve HAUTE audit findings |

---

## v1.2.0 (2026-03-18)

> **Branche** : `OPAL_V1.2.0`
> **Base** : `OPAL_V1.1.0`
> **Periode** : 18 mars 2026

### Audits et corrections

- 3 audits approfondis (securite, optimisation, fonctionnel) avec 98 findings au total
- Resolution de tous les findings P0/CRITIQUE (SQL injection f-string, SSE race condition, CSV en RAM, 3 domaines OMOP manquants)
- Resolution des findings HAUTE (rate limiting, cascade deletes, JWT clock skew, JWKS TTL)
- Resolution des findings MOYENNE (CSV injection, safe_identifier longueur, Keycloak password policy)
- 27 tests supplementaires pour les lacunes identifiees

---

## v1.1.0 (2026-03-18)

> **Branche** : `claude/ws-notifications-tests-bZV25`
> **Base** : `OPAL_V1.0.1` (v1.0.1 — securite + optimisations SQL)
> **Periode** : 15–18 mars 2026 (3 sessions de travail)
> **Bilan** : 128 fichiers modifies, ~18 200 lignes ajoutees, ~2 000 supprimees
> **Tests** : 601 backend + 84 frontend = **685 tests** (zero failure)

---

## Table des matieres

1. [Nouveautes fonctionnelles](#1-nouveautes-fonctionnelles)
   - [Notifications temps reel (WebSocket)](#11-notifications-temps-reel-websocket)
   - [Pathways Analysis (parcours de soins)](#12-pathways-analysis-parcours-de-soins)
   - [Theme clair Creme Sauge](#13-theme-clair-creme-sauge)
   - [Micro-animations et UX avancee](#14-micro-animations-et-ux-avancee)
2. [Securite](#2-securite)
3. [Performance](#3-performance)
4. [Architecture](#4-architecture)
5. [Tests](#5-tests)
6. [Infrastructure et DevOps](#6-infrastructure-et-devops)
7. [Commits detailles](#7-commits-detailles)
8. [Fichiers crees et modifies](#8-fichiers-crees-et-modifies)

---

## 1. Nouveautes fonctionnelles

### 1.1 Notifications temps reel (WebSocket)

**Commits** : `7d78c53`, `2e185b6`, `080dadc`

Remplacement complet du systeme de notifications par polling par un systeme **temps reel pur via WebSocket**.

#### Backend

- **Endpoint WebSocket** : `GET /api/ws/notifications`
  - Authentification via ticket SSE a usage unique (TTL 30s)
  - Suivi des connexions par utilisateur et par role
  - Reconnexion automatique avec backoff exponentiel
- **WebSocket Manager** (`utils/ws_manager.py`) :
  - Broadcast par utilisateur ou par role
  - Gestion propre des deconnexions
  - Thread-safe avec verrous
- **`notify()` enrichi** (`utils/notifications.py`) :
  - Insertion DB + push WebSocket instantane
  - 9 nouveaux types de notification : `access_granted`, `access_revoked`, `cdm_created`, `cdm_updated`, `cdm_deleted`, `mapping_applied`, `cohort_deleted`, `cohort_updated`, `group_removed`
- **Declencheurs** ajoutes dans tous les modules :
  - `cdm_router` : creation/modification/suppression CDM
  - `cdm_access_router` : attribution/revocation acces utilisateur et groupe
  - `cohort/router` : suppression cohorte (notifie les utilisateurs partages)
  - `cohort_sharing_router` : annulation de partage
  - `groups_router` : suppression groupe, retrait de membre
  - `mapping/router` : decision de mapping, application de mapping
- **Preferences de notification** :
  - Nouveau modele `NotificationPreference`
  - `GET/POST /api/notifications/preferences`
  - Mute par type de notification
- **Nettoyage automatique** : thread daemon qui purge les notifications lues > 30 jours
- **Endpoints DELETE** : suppression individuelle et en lot

#### Frontend

- **`useNotificationWs` hook** : connexion WebSocket au montage, reconnexion auto, dispatch d'evenements `opal:notification`
- **`NotificationCenter` drawer** : historique complet avec :
  - Filtre tout/non lu
  - Marquer lu (individuel/tous)
  - Supprimer (individuel/tous lus)
  - Navigation vers la page liee au clic
  - Affichage relatif du temps, icones et couleurs par type
- **TopNav** : cloche avec badge compteur non lus
- **Zero polling** : WebSocket gere 100% de la livraison temps reel

#### Nginx

- Bloc `location /api/ws/` avec headers `Upgrade`/`Connection` pour WebSocket
- Timeout 24h pour les connexions WebSocket longue duree
- CSP mis a jour : `ws:` et `wss:` dans `connect-src`

---

### 1.2 Pathways Analysis (parcours de soins)

**Commit** : `8da9ed0`

Feature complete d'analyse de parcours de soins ("treatment pathways") basee sur la methodologie OHDSI ATLAS (Hripcsak et al. 2016).

#### Backend — `modules/cohort/pathways.py` (346 lignes)

- **Materialisation** de la cohorte cible via `build_cohort_sql()` dans une table temporaire
- **Collecte d'evenements** : pour chaque "event cohort" (concepts definis), requete les tables OMOP correspondantes avec support `include_descendants` via `concept_ancestor`
- **Collapse d'eras** : fusion des intervalles temporels chevauchants en eras contigues (fenetre configurable)
- **Construction de sequences** : ordonnancement par date, troncature a `max_depth` etapes
- **Arbre sunburst** : construction hierarchique `{name, value, children}` avec elagage automatique (`min_cell_count`)

| Parametre | Defaut | Description |
|-----------|--------|-------------|
| `max_depth` | 5 | Profondeur max des parcours (1-10) |
| `min_cell_count` | 5 | Seuil minimum de patients par chemin |
| `combo_window` | 0 | Jours pour fusionner les eras chevauchantes |

#### Endpoints

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/api/cohorts/pathways` | POST | Lance l'analyse en tache de fond |
| `/api/cohorts/pathways/status/{task_id}` | GET | Polling du statut + resultats |
| `/api/cohorts/pathways/cancel/{task_id}` | POST | Annulation d'une analyse en cours |

#### Frontend — `PathwaysPanel.tsx` (826 lignes)

- **Event Cohort Builder** : recherche de concepts, nommage, toggle descendants
- **Sunburst SVG custom** : arcs concentriques sans dependance D3, tooltips au survol
- **Legende couleurs** + sequences selectionnees
- **Table des top pathways** : compte et pourcentage
- **Barre de progression** + **Export CSV** + **Panneau settings**

---

### 1.3 Theme clair Creme Sauge

**Commits** : `08e5b7b`, `cb1265a`, `e0f747b`, `ae11f5e`, `806fda8`

Implementation d'un mode clair complet sur l'ensemble de l'application.

#### Palette

| Token | Couleur | Usage |
|-------|---------|-------|
| `--bg-base` | `#EDE7D9` | Arriere-plan principal |
| `--bg-surface` | `#E0D9C8` | Surfaces, cartes |
| `--bg-shadow` | `#CFC8B6` | Ombres neumorphiques |
| `--accent` | `#8FAE6B` | Accent sauge (boutons, badges) |
| `--text` | `#2D3B1E` | Texte principal |

#### Implementation

- **CSS** : variables `[data-theme="light"]` dans `opal-theme.css` et `landing.css` — toutes les surfaces sont creme, zero blanc
- **Ombres neumorphiques** : surcharges completes pour le mode clair (glows, focus rings, scrollbar, tags)
- **`useTheme` hook** : toggle dark/light avec persistance `localStorage`
- **TopNav** : bouton soleil/lune entre le selecteur de langue et la cloche
- **Anti-flash** : script dans `index.html` qui lit `localStorage` avant le premier paint
- **`tokens.ts`** : export `lightColors` et `lightShadows`
- **`Card.tsx`** : refactore avec classe CSS `.opal-card-shadow` theme-aware

---

### 1.4 Micro-animations et UX avancee

**Commits** : `942353f`, `c14c08a`

#### Nouveaux composants d'animation (`AnimatedList.tsx`)

| Composant | Description |
|-----------|-------------|
| `AnimatedList` | Listes avec apparition en cascade (stagger) via Framer Motion |
| `FadeIn` | Fondu d'entree pour les sections |
| `ScaleIn` | Pop-in pour les cartes et elements isoles |
| `CountUp` | Animation de compteur numerique |

#### Skeleton loaders (`SkeletonPatterns.tsx`)

| Composant | Usage |
|-----------|-------|
| `CardSkeleton` | Placeholder de carte |
| `StatSkeleton` | Placeholder de statistique |
| `TableSkeleton` | Placeholder de tableau |
| `DashboardSkeleton` | Placeholder de dashboard complet |
| `ListSkeleton` | Placeholder de liste |
| `InlineSkeleton` | Placeholder inline |

#### Etats d'erreur riches (`ErrorState.tsx`)

- 5 variantes : `network`, `server`, `forbidden`, `not-found`, `generic`
- Detection automatique du type d'erreur (`detectErrorVariant()`)
- Icones animees, boutons retry/home, mode compact
- Integre dans `ErrorBoundary` et `ForbiddenPage`

#### Etats vides enrichis (`Empty.tsx`)

- 11 variantes predefinies : `no-cdm`, `no-cohorts`, `no-notifications`, `no-data`, etc.
- Animation flottante de l'icone, anneau lumineux subtil

#### Toast ameliore (`Toast.tsx`)

- Animations spring physics (apparition/disparition)
- Spin-in de l'icone, barre de progression countdown
- Support success/error/info/warning

#### CSS micro-interactions (`opal-theme.css`)

- `.opal-pressable` : scale au clic
- `bell-ring` : animation de cloche
- `shimmer` / `skeleton-wave` : effets de chargement
- `success-flash` / `number-pop` : feedback visuel
- Transition de theme fluide (0.4s) via classe `opal-theme-transitioning`

---

## 2. Securite

### Audit complet et remediation

3 rounds d'audit ont identifie **80 findings** au total. **62 items corriges** (P0 a P2).

### P0 — Critique (7/7 corriges)

| Correction | Fichiers | Detail |
|-----------|----------|--------|
| **Injection SQL** | `concept/router.py`, `search_router.py`, `concept_set/router.py`, `suggest.py`, `clinical.py`, `conformity.py` | Migration systematique des f-strings vers `psycopg2.sql.SQL` + `sql.Identifier`. Nouveau module `utils/sql_safety.py` avec `safe_identifier()` |
| **Path traversal** | `ohdsi/router.py` | Validation `resolve()` + `startswith()` dans le navigateur de fichiers OHDSI |
| **SSRF** | `cdm_router.py` | Validation des hosts CDM : rejet localhost, metadata cloud, IPs privees, link-local |
| **Rate limiting** | `main.py`, `utils/rate_limit.py` | `slowapi` sur endpoints sensibles (inscription, tickets SSE, compute) |
| **CDM access checks** | `cohort/router.py`, `concept/router.py`, `concept_set/router.py` | `check_cdm_access()` sur 12 endpoints POST non proteges |
| **S01 — Docker socket** (C3) | `docker-compose.yml` | Suppression du mount `/var/run/docker.sock` dans le fichier de base. Commentaire detaille sur le proxy Docker (Tecnativa `docker-socket-proxy`) pour l'integration OHDSI. |
| **S02 — AUTH_ENABLED=false non-localhost** (C6) | `backend/auth/keycloak.py` | Rejet HTTP 403 + log CRITICAL si une requete non-localhost arrive avec `AUTH_ENABLED=false`. Le mode dev reste fonctionnel uniquement depuis 127.0.0.1/::1. |
| **S03 — Keycloak credentials par defaut** (C7) | `docker-compose.yml`, `.env.example` | `KEYCLOAK_ADMIN_PASSWORD` desormais obligatoire (syntaxe `:?`). Le deploiement echoue avec message explicite si la variable n'est pas definie. La valeur par defaut `admin` est supprimee. |

### P1 — Eleve

| Correction | Detail |
|-----------|--------|
| **IDOR** (6 items) | Verification d'ownership sur notifications, saved queries, concept sets, cohort templates, cohort delete |
| **Admin RBAC** | `_require_admin()` sur 12 endpoints admin/audit |
| **Mots de passe temporaires** | `secrets.token_urlsafe(16)` au lieu du username |
| **Keycloak credentials** | Plus de fallback `admin/admin`, warning si detecte |
| **CORS restrictif** | Methodes et headers explicites au lieu de `*` |
| **Masquage erreurs** | Messages generiques, plus de stack traces/SQL dans les reponses HTTP |
| **CSP** | `Content-Security-Policy`, `Strict-Transport-Security`, `Permissions-Policy` |
| **Production guards** | `SECRET_KEY` faible + `AUTH_ENABLED=false` en prod → crash immediat |
| **Thread safety** | `threading.Lock` sur tous les dicts de taches partages |
| **Credentials hardening** | Permissions fichier cle `0o600`, `ENCRYPTION_KEY` env var, `DecryptionError` explicite |
| **Audit logs** | Masquage params sensibles (password, token, ticket), permissions `0o640` |

### P2 — Modere

| Correction | Detail |
|-----------|--------|
| Bound `page_size` audit (1-500) | Previent les DoS via pagination |
| Sanitize `Content-Disposition` | Noms de fichiers securises |
| Escape ILIKE wildcards | Protection contre les patterns malveillants |
| CSV formula injection | Helper `csv_safe()` pour les exports |
| `datetime.now(timezone.utc)` | Remplacement de `utcnow()` deprece |
| Security headers nginx | Headers de securite sur les assets statiques |
| OHDSI network dedie | Conteneurs Docker sur reseau isole au lieu de host |
| Dependances pinnees | Versions exactes dans `requirements.txt` |

### Production hardening (`docker-compose.prod.yml`)

- Keycloak en mode production (`start` au lieu de `start-dev`)
- PostgreSQL pour persistence Keycloak (remplace H2)
- Socket Docker retire
- Ports bindes sur localhost
- Variables d'environnement requises

---

## 3. Performance

### Optimisations SQL

| Optimisation | Fichier | Impact |
|-------------|---------|--------|
| **N+1 cohortes** | `cohort/router.py` | Subquery + JOIN au lieu de N requetes individuelles → O(1) |
| **N+1 mapping dashboard** | `mapping/router.py` | `DISTINCT ON (domain)` en une requete |
| **N+1 groupes** | `groups_router.py` | JOIN + GROUP BY au lieu de boucle |
| **N+1 data management** | `datamanagement/router.py` | Batch query au lieu de boucle |
| **Strategy stats** | `mapping/router.py` | Aggregation SQL (`CASE` + `COUNT`/`AVG`) au lieu de Python |
| **COUNT(*) OVER()** | `concept/router.py` | Elimination de la requete COUNT separee |
| **CTE attrition** | `cohort/router.py` | CTE unique au lieu de N requetes sequentielles |
| **Conformite mergee** | `conformity.py` | `COUNT(*) FILTER (WHERE ...)` : 3→1 requete |
| **Dashboard UNION ALL** | `dashboard.py` | Stats domaines fusionnees en une requete |
| **Bulk mapping** | `mapping/router.py` | `IN` clause + `bulk_save_objects` au lieu de boucle |
| **Concept counts** | `concept/router.py` | `UNION ALL` au lieu de N requetes par domaine |

### Caches

| Cache | TTL | Taille max | Usage |
|-------|-----|-----------|-------|
| **Concept details** | 5 min | 500 entrees | Details et hierarchie par CDM+concept_id |
| **i18n** | Infini | 2 entrees | Traductions chargees au demarrage |

### Pagination

Ajout `limit/offset` sur : `saved_queries`, `favorites`, `cdm_access`, `mapping/reference`, `mapping/sapbert`, `admin_cohorts_by_user`.

### Index composites

| Table | Index | Colonnes |
|-------|-------|----------|
| `analysis_snapshots` | `ix_snapshots_cdm_domain` | `(cdm_name, domain)` |
| `analysis_snapshots` | `ix_snapshots_cdm_domain_version` | `(cdm_name, domain, version)` |
| `cohort_versions` | `ix_cohort_versions_cohort_version` | `(cohort_id, version)` |
| `mapping_decisions` | `ix_mapping_decisions_cdm_domain` | `(cdm_name, domain)` |
| `mapping_decisions` | `ix_mapping_decisions_cdm_domain_sv` | `(cdm_name, domain, source_value)` |
| `notifications` | `ix_notifications_user_read` | `(username, read)` |

---

## 4. Architecture

### Refactoring majeurs

| Changement | Detail |
|-----------|--------|
| **Admin router extrait** | `main.py` → `modules/admin_router.py` (~500 lignes deplacees) |
| **CDM helper centralise** | `utils/cdm_helper.py` : `get_cdm_connection()` avec `safe_identifier` |
| **Keycloak middleware ASGI** | Reecrit en ASGI pur (plus de `BaseHTTPMiddleware` qui bufferise le streaming) |
| **SSE tickets** | Tickets a usage unique (TTL 30s) au lieu de JWT dans les query params |
| **Token refresh queue** | Intercepteur Axios : une seule requete de refresh, les autres attendent |
| **GZip middleware** | Compression automatique (seuil 1000 bytes) |
| **Cascade delete CDM** | Suppression de toutes les entites liees lors de la suppression d'un CDM |
| **Alembic migrations** | Migration initiale avec 22 tables et tous les index |

### Nouveaux modules

| Module | Lignes | Role |
|--------|--------|------|
| `utils/ws_manager.py` | 129 | WebSocket connection manager |
| `utils/cdm_helper.py` | 67 | Helper centralise connexion CDM |
| `utils/csv_safety.py` | 9 | Protection injection formules CSV |
| `utils/rate_limit.py` | 14 | Decorateur rate limiting |
| `modules/admin_router.py` | 506 | Routes admin (extrait de main.py) |
| `modules/cohort/pathways.py` | 346 | Moteur pathways analysis |
| `docker-compose.prod.yml` | 67 | Compose production durci |

---

## 5. Tests

### Statistiques

| Metrique | Avant (v1.0.1) | Apres (v1.1.0) | Delta |
|----------|----------------|-----------------|-------|
| **Tests backend** | 315 | 601 | +286 (+91%) |
| **Tests frontend** | 10 | 94 | +84 |
| **Total** | 325 | **685** | **+360 (+111%)** |
| **Fichiers de tests backend** | 22 | 38 | +16 |
| **Fichiers de tests frontend** | 1 | 7 | +6 |
| **Coverage estimee** | ~60% | ~75%+ | +15pp |

### Infrastructure de test

- **`omop_mock.py`** : mock reutilisable de connexion psycopg2 avec sequences de reponses pre-configurees
- **`README.md`** : documentation complete de l'architecture de test

### Nouveaux fichiers de tests backend (16)

| Fichier | Tests | Couverture |
|---------|-------|------------|
| `test_dashboard_domain.py` | Stats UNION ALL, sparklines, error recovery |
| `test_person_domain.py` | Demographics, colonnes manquantes, NULLs |
| `test_observation_period_domain.py` | 6 sous-analyses, cap mois, donnees vides |
| `test_clinical_domain.py` | 5 helpers + orchestrateur tous domaines |
| `test_report_builder.py` | Rapports HTML, comparaison, SVG |
| `test_extractor.py` | SQL builder, identifiants, CTE, bucketing |
| `test_cdm_helper.py` | Lookup CDM, auth, schema override |
| `test_pathways_analysis.py` | Sunburst builder, pruning, chemins profonds |
| `test_concept_set_api.py` | CRUD complet, ownership, filtres |
| `test_estimation_router.py` | CRUD estimation |
| `test_incidence_router.py` | CRUD incidence |
| `test_datamanagement_router.py` | Tables, colonnes, statut taches |
| `test_concept_router.py` | Recherche, details, hierarchie, domaines |
| `test_incidence_engine.py` | compute_incidence, aggregate, poisson_ci |
| `test_survival.py` | compute_km, median_survival, log_rank_test |
| `test_role_access.py` | Tests IDOR : saved queries, cohorts, notifications, concept sets |
| `test_i18n.py` | Parite cles EN/FR, endpoint |
| `test_ws_manager.py` | WebSocket manager : connect, disconnect, broadcast |
| `test_ws_endpoint.py` | Endpoint WS : auth, messages, reconnexion |
| `test_ws_nginx.py` | Config nginx WebSocket |
| `test_notification_preferences.py` | Preferences par type, mute/unmute |
| `test_notifications.py` (enrichi) | +400 lignes : delete, bulk, preferences |
| `test_pagination_gaps.py` | Pagination limit/offset sur tous les endpoints |
| `test_concept_cache.py` | TTL, eviction, invalidation cache |
| `test_pathways.py` | Validation API, sunburst, pruning, collapse eras |

### Nouveaux fichiers de tests frontend (6)

| Fichier | Tests | Couverture |
|---------|-------|------------|
| `AnimatedList.test.tsx` | FadeIn, ScaleIn, CountUp : rendu, props, className |
| `SkeletonPatterns.test.tsx` | Card, Stat, Table, Dashboard, List, Inline : structure |
| `Empty.test.tsx` | 11 variantes, overrides titre/description/icone, children |
| `ErrorState.test.tsx` | 5 variantes, detectErrorVariant(), retry/home |
| `Toast.test.tsx` | success/error/info/warning, auto-dismiss, close, a11y |
| `useTheme.test.ts` | Toggle dark/light, persistance localStorage, classe transition |

---

## 6. Infrastructure et DevOps

### GitHub Actions CI (`.github/workflows/ci.yml`)

4 jobs paralleles :

| Job | Actions |
|-----|---------|
| `backend-tests` | Python 3.12, pip install, pytest + coverage, Codecov upload |
| `frontend-build` | Node 20, npm ci, npm run build |
| `frontend-tests` | Node 20, npm ci, vitest run |
| `docker-build` | docker compose build (smoke test) |

### Docker Compose durci

| Changement | Detail |
|-----------|--------|
| Credentials parametrises | `POSTGRES_PASSWORD`, `SECRET_KEY` requis (`:?`) |
| Resource limits | Backend 2G/2CPU, Frontend 512M, DB 1G, Keycloak 1G |
| Port DB localhost | `127.0.0.1:${DB_EXTERNAL_PORT:-5434}:5432` |
| Healthcheck Keycloak | TCP health check |
| Hostnames parametrises | `EXTERNAL_HOSTNAME` pour CORS et Keycloak |

### Nginx

| Ajout | Detail |
|-------|--------|
| WebSocket proxy | `/api/ws/` avec headers `Upgrade`, timeout 24h |
| SSE proxy | `/api/ohdsi/logs/` avec `proxy_buffering off` |
| Security headers | CSP, HSTS, Permissions-Policy sur tous les assets |

### Dependances ajoutees

**Backend** :
- `slowapi` — rate limiting
- `alembic` — migrations de schema

**Frontend** :
- `framer-motion` — animations
- `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom` — tests

### Variables d'environnement ajoutees

| Variable | Defaut | Description |
|----------|--------|-------------|
| `ENVIRONMENT` | `development` | Active les guards en production |
| `ENCRYPTION_KEY` | — | Cle Fernet base64 (prioritaire sur fichier) |
| `TESTING` | — | Desactive le rate limiter en mode test |
| `EXTERNAL_HOSTNAME` | `localhost` | Hostname externe (CORS, Keycloak) |
| `DB_EXTERNAL_PORT` | `5434` | Port externe PostgreSQL |

---

## 7. Commits detailles

### Session 1 — 15 mars 2026

| Hash | Description |
|------|-------------|
| `883ad1b` | Plan d'amelioration : audit complet (securite, perfs, archi, tests, DevOps) |
| `8da9ed0` | Pathways Analysis : feature complete ATLAS-style |
| `d6ec563` | Implementation P0/P1 : securite + optimisations + pool connexions + Alembic |
| `55299f4` | Fix rate limiter : suppression default_limits, fix SAWarning |
| `0dcfdec` | CHANGELOG session 1 |

### Session 2 — 15-16 mars 2026

| Hash | Description |
|------|-------------|
| `41a7128` | Audit V2 : 54 findings |
| `e8207eb` | Audit V2 : +11 findings (65 total) |
| `0b6df86` | Audit supplementaire round 2 |
| `704a46c` | Audit V2 : +10 findings + path traversal critique (75 total) |
| `05a7f75` | Audit V2 final : 80 findings |
| `fca2476` | Plan quick wins (25 items) + rapport audit R2 |
| `8bb8299` | **25 quick wins appliques** (P0/P1/P2) — 327 tests |
| `3ea0750` | Plan quick wins R2 (20 items) |
| `f1d768a` | **16 quick wins R2 appliques** — 327 tests |
| `a7491de` | **Quick wins R3** : securite, perfs, archi, tests |
| `5d45352` | Rapport de verification R2 |
| `6cdb46c` | .gitignore : .coverage et htmlcov/ |
| `145f56f` | **114 nouveaux tests** — 477 total, coverage 60→75%+ |
| `d316cda` | Rapport de verification R3 |
| `8771fd9` | **Gaps R2/R3** : pagination, cache, admin refactor, SSE cleanup |

### Session 3 — 16-18 mars 2026

| Hash | Description |
|------|-------------|
| `7d78c53` | **Notifications temps reel** : WebSocket endpoint, manager, preferences |
| `2e185b6` | **Zero polling** : suppression complete du polling, pur WebSocket |
| `080dadc` | **Nginx WebSocket** : proxy + CSP |
| `7a51939` | 71 tests : WebSocket, notifications, cache, pagination |
| `8ea5889` | Documentation WebSocket + tests supplementaires |
| `08e5b7b` | Mockup theme clair : 3 palettes |
| `cb1265a` | Rebuild mockup avec layout TopNav |
| `e0f747b` | **Theme Creme Sauge** : implementation complete |
| `ae11f5e` | Mockup palette finale + comparaison dark/light |
| `806fda8` | Ajustement surfaces creme (plus foncees pour mobile) |
| `1145ce0` | **Hardening securite** : access checks, pinning deps, Alembic migration, prod compose |
| `942353f` | **Micro-animations** : AnimatedList, skeletons, ErrorState, Empty, Toast, transitions |
| `c14c08a` | **84 tests frontend** : tous les nouveaux composants UI |

---

## 8. Fichiers crees et modifies

### Nouveaux fichiers (50+)

#### Backend — Modules
| Fichier | Lignes | Role |
|---------|--------|------|
| `modules/admin_router.py` | 506 | Routes admin (extrait de main.py) |
| `modules/cohort/pathways.py` | 346 | Moteur pathways analysis |
| `utils/ws_manager.py` | 129 | WebSocket connection manager |
| `utils/cdm_helper.py` | 67 | Helper centralise connexion CDM |
| `utils/csv_safety.py` | 9 | Protection injection CSV |
| `utils/rate_limit.py` | 14 | Decorateur rate limiting |
| `utils/sql_safety.py` | 28 | Validation identifiants SQL |

#### Backend — Tests (16 nouveaux fichiers)
| Fichier | Lignes |
|---------|--------|
| `tests/omop_mock.py` | 106 |
| `tests/test_dashboard_domain.py` | 131 |
| `tests/test_person_domain.py` | 120 |
| `tests/test_observation_period_domain.py` | 114 |
| `tests/test_clinical_domain.py` | 236 |
| `tests/test_report_builder.py` | 211 |
| `tests/test_extractor.py` | 204 |
| `tests/test_cdm_helper.py` | 114 |
| `tests/test_pathways_analysis.py` | 91 |
| `tests/test_concept_set_api.py` | 139 |
| `tests/test_estimation_router.py` | 88 |
| `tests/test_incidence_router.py` | 84 |
| `tests/test_datamanagement_router.py` | 109 |
| `tests/test_concept_router.py` | 161 |
| `tests/test_incidence_engine.py` | 111 |
| `tests/test_survival.py` | 118 |
| `tests/test_role_access.py` | 116 |
| `tests/test_i18n.py` | 65 |
| `tests/test_ws_manager.py` | 342 |
| `tests/test_ws_endpoint.py` | 373 |
| `tests/test_ws_nginx.py` | 207 |
| `tests/test_notification_preferences.py` | 163 |
| `tests/test_pagination_gaps.py` | 152 |
| `tests/test_concept_cache.py` | 124 |
| `tests/test_pathways.py` | 199 |
| `tests/README.md` | 184 |

#### Backend — Infrastructure
| Fichier | Lignes |
|---------|--------|
| `alembic.ini` | 149 |
| `alembic/env.py` | 61 |
| `alembic/script.py.mako` | 28 |
| `alembic/versions/26a4acfe5afa_initial_schema.py` | 375 |
| `requirements-dev.txt` | 4 |

#### Frontend — Composants
| Fichier | Lignes |
|---------|--------|
| `components/NotificationCenter.tsx` | 274 |
| `components/cohort/PathwaysPanel.tsx` | 826 |
| `components/ui/AnimatedList.tsx` | 146 |
| `components/ui/ErrorState.tsx` | 149 |
| `components/ui/SkeletonPatterns.tsx` | 108 |
| `hooks/useNotificationWs.ts` | 113 |
| `hooks/useTheme.ts` | 51 |
| `theme/tokens.ts` | 52 |

#### Frontend — Tests
| Fichier | Lignes |
|---------|--------|
| `components/ui/AnimatedList.test.tsx` | 68 |
| `components/ui/Empty.test.tsx` | 99 |
| `components/ui/ErrorState.test.tsx` | 127 |
| `components/ui/SkeletonPatterns.test.tsx` | 104 |
| `components/ui/Toast.test.tsx` | 144 |
| `hooks/useTheme.test.ts` | 66 |

#### Infrastructure
| Fichier | Lignes |
|---------|--------|
| `.github/workflows/ci.yml` | 66 |
| `docker-compose.prod.yml` | 67 |

### Fichiers supprimes

| Fichier | Raison |
|---------|--------|
| `frontend/src/pages/LandingPage.tsx` | Page inutilisee (524 lignes) |
