# PLAN QUICK WINS R2 — Deuxieme passe

> 25/80 items corriges dans R1. Reste 55 items.
> Meme critere : faisable rapidement, fort impact.

---

## BATCH 5 — P1 Securite restante (4 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 26 | SQL injection clinical.py | `quality/domains/clinical.py` | ~30 lignes | Migrer 5 fonctions vers `psycopg2.sql` |
| 27 | SQL injection conformity.py | `quality/conformity.py` | ~30 lignes | Migrer 5 blocs vers `psycopg2.sql` |
| 28 | Missing auth cancel_analysis | `quality/router.py` | 5 lignes | Stocker username, verifier a l'annulation |
| 29 | OHDSI network_mode="host" | `ohdsi/router.py` | 3 lignes | Remplacer par reseau dedie |

## BATCH 6 — P1 Performance (5 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 30 | Pagination cohort_sharing | `cohort_sharing_router.py` | 10 lignes | Ajouter limit/offset |
| 31 | Pagination 4 endpoints listing | `mapping,saved_queries,favorites,cdm_access` | 5 lignes/endpoint | Ajouter limit/offset |
| 32 | Extractions CSV en memoire | `datamanagement/router.py` | 20 lignes | Ecrire dans fichier temp |
| 33 | Audit logs en memoire | `main.py` | 15 lignes | `itertools.islice` + line counting |
| 34 | Dashboard N queries sequentielles | `quality/domains/dashboard.py` | 20 lignes | UNION ALL unique |

## BATCH 7 — P1/P2 Architecture + Fonctionnel (5 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 35 | Extract `get_cdm_connection()` | Nouveau `utils/cdm_helper.py` | 30 lignes + refactor 5 routers | Centraliser logique CDM |
| 36 | Pydantic models admin | `main.py` | 20 lignes | `AssignRoleRequest`, etc. |
| 37 | OHDSI RunRequest schema regex | `ohdsi/router.py` | 2 lignes | `pattern=r"^[A-Za-z_]..."` |
| 38 | list_groups role restriction | `groups_router.py` | 5 lignes | Cacher membres si non-admin |
| 39 | Keycloak issuer validation | `auth/keycloak.py` | 3 lignes | Ajouter `issuer=` dans jwt.decode |

## BATCH 8 — P2/P3 One-liners restants (6 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 40 | Audit logger filtre sensible | `audit/logger.py` | 10 lignes | Masquer password/token/ticket |
| 41 | Task dicts TTL + cap | 4 fichiers | 15 lignes/fichier | Cleanup thread + max 100 |
| 42 | Double scan COUNT OVER() | `concept/router.py` | 5 lignes | `COUNT(*) OVER()` |
| 43 | Audit log file permissions | `audit/logger.py` | 3 lignes | `os.chmod(path, 0o640)` |
| 44 | Docker DB bind localhost | `docker-compose.yml` | 1 ligne | `127.0.0.1:5434:5432` |
| 45 | LandingPage dead code | `LandingPage.tsx` | Supprimer | Delete fichier |

---

## CE QUI RESTE EN BACKLOG (35 items)

**Architecture lourde :**
- Alembic migration initiale
- Refactoring main.py en routers
- ForeignKeys dans models.py
- Inconsistance schemas OMOP (resolu par cdm_helper)
- Imports inline

**Performance moyenne :**
- CSV streaming exports (architecture change)
- Concept counts UNION ALL
- Concept cache LRU
- observation_period CTE combine
- Batch suggestion parallelisation
- bulk_decision upsert
- Keycloak async handlers

**Tests :**
- Tests IDOR
- Tests incidence/estimation
- Tests suggest.py strategies
- Tests frontend composants
- Tests sql_builder cas limites
- Tests de charge

**DevOps :**
- CI securite (bandit, trivy)
- .env.example a jour
- Logs structures JSON
- Backup automatise

**Frontend :**
- Accessibilite a11y
- Sunburst clavier
- Types `any` excessifs
- Lazy loading pages
- State management global

**Fonctionnel :**
- Traductions i18n
- CDM access check sur endpoints
- Pool evictor encapsulation

---

## RESUME R2

| Batch | Items | Impact | Effort total |
|-------|-------|--------|-------------|
| 5 — P1 Securite | 4 | Haut | ~70 lignes |
| 6 — P1 Perf | 5 | Haut | ~55 lignes |
| 7 — P1/P2 Archi | 5 | Moyen-Haut | ~60 lignes |
| 8 — P2/P3 Divers | 6 | Moyen | ~50 lignes |
| **Total R2** | **20** | | **~235 lignes** |

Apres R1 (25) + R2 (20) = **45/80 items corriges**. Reste 35 en backlog (tests, frontend, DevOps, refactoring lourd).
