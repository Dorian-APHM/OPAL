# PLAN QUICK WINS R3 — Troisieme passe

> R1 (25) + R2 (20) = 45/80 items corriges.
> R3 cible les items restants faisables rapidement.
> Items lourds (Alembic, refactor main.py, frontend a11y, CI securite) restent en backlog.

---

## BATCH 9 — P1 Securite restante (4 items)

| # | Item | Ref Audit | Fichier | Effort | Fix |
|---|------|-----------|---------|--------|-----|
| 46 | SQL injection clinical.py → psycopg2.sql | 1.3 | `quality/domains/clinical.py` | ~40 lignes | Migrer 5 fonctions de f-string+safe_identifier vers `psycopg2.sql.SQL`/`Identifier` |
| 47 | SQL injection conformity.py → psycopg2.sql | 1.4 | `quality/conformity.py` | ~40 lignes | Migrer 5 blocs vers `psycopg2.sql.SQL`/`Identifier` |
| 48 | SSRF re-verification DNS | 1.10 | `db/omop_connector.py` | ~15 lignes | Valider IP resolue dans `get_omop_connection()` |
| 49 | SSE tickets periodic cleanup | 1.9 | `auth/keycloak.py` | ~10 lignes | Integrer nettoyage dans evictor thread |

## BATCH 10 — P1/P2 Performance (5 items)

| # | Item | Ref Audit | Fichier | Effort | Fix |
|---|------|-----------|---------|--------|-----|
| 50 | Concept counts UNION ALL | 2.6 | `concept/router.py` | ~20 lignes | UNION ALL unique au lieu de N requetes |
| 51 | observation_period CTE combine | 8.6 | `observation_period.py` | ~25 lignes | Regrouper 6→2-3 requetes |
| 52 | bulk_decision upsert | 8.7 | `mapping/router.py` | ~15 lignes | `INSERT ON CONFLICT DO UPDATE` |
| 53 | Concept cache LRU | 2.8 | `concept/router.py` | ~15 lignes | `functools.lru_cache` sur `/details` et `/hierarchy` |
| 54 | Batch suggest parallelisation | 2.7 | `mapping/suggest.py` | ~15 lignes | `ThreadPoolExecutor` pour batch |

## BATCH 11 — P2 Architecture (4 items)

| # | Item | Ref Audit | Fichier | Effort | Fix |
|---|------|-----------|---------|--------|-----|
| 55 | Extract `get_cdm_connection()` | 3.2 | Nouveau `utils/cdm_helper.py` | ~30 lignes + refactor 5 routers | Centraliser logique CDM |
| 56 | CDM access check sur endpoints | 4.7+4.8 | 4 routers | ~4 lignes/router | `check_cdm_access(cdm_name, request, db)` |
| 57 | Refactor main.py — extraire admin routes | 3.4 | `main.py` → `admin_router.py` | ~50 lignes refactor | Deplacer endpoints admin Keycloak |
| 58 | ForeignKeys dans models.py | 8.0.3 | `db/models.py` | ~15 lignes | Ajouter FK + `ondelete="CASCADE"` |

## BATCH 12 — P2/P3 Tests + divers (5 items)

| # | Item | Ref Audit | Fichier | Effort | Fix |
|---|------|-----------|---------|--------|-----|
| 59 | Tests IDOR | 5.1 | `tests/test_role_access.py` | ~40 lignes | Tests user B ne peut pas modifier/supprimer resources user A |
| 60 | Tests incidence/estimation | 5.2 | Nouveaux fichiers test | ~60 lignes | Tests unitaires fonctions de calcul |
| 61 | Traductions i18n hardcoded | 4.6 | 3 routers + `fr.json` | ~20 lignes | Extraire strings FR hardcodees vers i18n |
| 62 | Logs structures JSON | 6.5 | `main.py` | ~10 lignes | `python-json-logger` ou dict formatter |
| 63 | .env.example verification | 6.4 | `.env.example` | ~5 lignes | Verifier completude avec nouvelles vars |

---

## CE QUI RESTE EN BACKLOG FINAL (12 items)

**Architecture lourde :**
- Alembic migration initiale (necessite planification schema complet)
- Imports inline refactoring

**Frontend :**
- Accessibilite a11y (audit systematique avec axe-core)
- Sunburst clavier navigation
- Types `any` excessifs
- Lazy loading pages (React.lazy)
- State management global (Zustand/Context)

**DevOps :**
- CI securite (bandit, trivy)
- Backup automatise

**Tests :**
- Tests suggest.py strategies individuelles
- Tests frontend composants
- Tests de charge

---

## RESUME R3

| Batch | Items | Impact | Effort total |
|-------|-------|--------|-------------|
| 9 — P1 Securite | 4 | Haut | ~105 lignes |
| 10 — P1/P2 Perf | 5 | Haut | ~90 lignes |
| 11 — P2 Archi | 4 | Moyen-Haut | ~100 lignes |
| 12 — P2/P3 Tests+divers | 5 | Moyen | ~135 lignes |
| **Total R3** | **18** | | **~430 lignes** |

Apres R1 (25) + R2 (20) + R3 (18) = **63/80 items corriges**. Reste 12 en backlog final (frontend, DevOps, refactoring lourd).
