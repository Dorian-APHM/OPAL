# PLAN QUICK WINS — Corrections simples a fort impact

> Critere : < 15 lignes de code chacun, impact securite ou fiabilite eleve
> Estimation : ~25 corrections faisables en un seul pass

---

## BATCH 1 — P0 Securite (4 items, bloquants)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 1 | Path traversal OHDSI | `ohdsi/router.py` | 3 lignes | `.resolve()` + startswith check |
| 2 | SQL injection search_router | `search_router.py` | ~20 lignes | `safe_identifier()` + `psycopg2.sql` |
| 3 | SQL injection concept_set | `concept_set/router.py` | ~10 lignes | `ANY(%s)` au lieu de f-string |
| 4 | SQL injection suggest.py schema | `suggest.py` | ~30 lignes | `psycopg2.sql.Identifier` sur schema (7 queries) |

## BATCH 2 — P1 IDOR (5 items, tous identiques)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 5 | IDOR notifications read | `notifications_router.py:132` | 2 lignes | Filtre `username == current_user` |
| 6 | IDOR notifications create | `notifications_router.py:179` | 1 ligne | Restreindre au role admin |
| 7 | IDOR saved queries | `saved_queries_router.py:76,91` | 4 lignes | Check `created_by == current_user` |
| 8 | IDOR cohort delete | `cohort/router.py` | 3 lignes | `_can_access_cohort` sur DELETE |
| 9 | IDOR concept sets | `concept_set/router.py:115-139` | 4 lignes | Check `created_by` |
| 10 | IDOR cohort templates | `cohort_templates_router.py:256` | 3 lignes | Check `created_by` |

## BATCH 3 — P1 Infra & perf (5 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 11 | Thread safety task dicts | 4 fichiers | 8 lignes/fichier | Ajouter `threading.Lock()` |
| 12 | Rate limiting endpoints lourds | 6 endpoints | 1 ligne/endpoint | `@limiter.limit("3/minute")` |
| 13 | SSE tickets cap | `keycloak.py` | 5 lignes | `if len > MAX: reject` |
| 14 | N+1 groups | `groups_router.py` | 8 lignes | JOIN + GROUP BY |
| 15 | Healthchecks Docker | `docker-compose.yml` + `main.py` | 10 lignes | `/api/health` + compose healthcheck |

## BATCH 4 — P2 One-liners (10 items)

| # | Item | Fichier | Effort | Fix |
|---|------|---------|--------|-----|
| 16 | page_size non borne | `main.py:268` | 1 ligne | `Query(ge=1, le=500)` |
| 17 | Content-Disposition injection | `quality/router.py` | 1 ligne | `re.sub(r'[^\w\-.]', '_', name)` |
| 18 | ILIKE wildcard escape | `search_router.py` | 2 lignes | Escape `%` et `_` |
| 19 | Cohort delete orphan shares | `cohort/router.py` | 1 ligne | Delete CohortShares avant cohort |
| 20 | GZip middleware | `main.py` | 1 ligne | `GZipMiddleware` |
| 21 | datetime.utcnow() | 4 fichiers | find/replace | `datetime.now(timezone.utc)` |
| 22 | CSV formula injection | helper + 4 fichiers | 10 lignes | Prefixer `=+\-@` avec `'` |
| 23 | N+1 datamanagement | `datamanagement/router.py` | 8 lignes | Subquery comme cohort |
| 24 | Nginx security headers | `nginx.conf` | 5 lignes | Repeter headers dans location |
| 25 | DELETE incidence/estimation | 2 routers | 15 lignes | Copier pattern existant |

---

## CE QU'ON NE FAIT PAS (backlog)

Ces items sont soit trop lourds, soit a faible impact immediat :

- **Alembic migration initiale** — necessite planification schema complet
- **Refactoring main.py** — gros refactor, pas de bug
- **suggest.py parallelisation** — optimisation, pas bloquant
- **Tests IDOR / incidence / estimation / frontend** — important mais pas un quick fix
- **CI securite (bandit, trivy)** — config DevOps, pas du code
- **Frontend (a11y, lazy loading, state management, types)** — gros chantiers UI
- **ForeignKeys dans models.py** — necessite migration + tests
- **DNS rebinding SSRF** — edge case, protection existante suffisante
- **Keycloak issuer validation** — risque theorique faible
- **Audit logger donnees sensibles** — P2, filtrage a definir
- **Logs structures JSON** — changement infra
- **Backup automatise** — ops, pas du code
- **Traductions i18n** — beaucoup de strings, effort moyen

---

## RESUME

| Batch | Items | Impact | Effort total estime |
|-------|-------|--------|-------------------|
| 1 — P0 Securite | 4 | Critique | ~60 lignes |
| 2 — P1 IDOR | 6 | Haut | ~20 lignes |
| 3 — P1 Infra | 5 | Haut | ~50 lignes |
| 4 — P2 One-liners | 10 | Moyen-Haut | ~40 lignes |
| **Total** | **25** | | **~170 lignes** |

25 corrections, ~170 lignes de code. Le reste (55 items) va en backlog.
