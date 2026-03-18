# OPAL — Suivi de Remediation Audit de Securite

**Date de debut** : 2026-03-13
**Document source** : `AUDIT_SECURITE_CONFORMITE.md`

---

## Constats corriges

| ID | Constat | Severite | Statut | Fichiers modifies |
|---|---|---|---|---|
| C-AUTH-01 | Validation JWT incomplete (iss/aud) | CRITIQUE | CORRIGE | `auth/keycloak.py` |
| C-AUTH-02 | Identifiants Keycloak par defaut | CRITIQUE | CORRIGE | `docker-compose.yml`, `.env.example` |
| C-AUTH-03 | Mode sans authentification | MAJEUR | CORRIGE | `config.py` (blocage en prod si AUTH_ENABLED=false) |
| C-AUTH-04 | Token JWT dans l'URL | MAJEUR | CORRIGE | `auth/keycloak.py` (log warning + deprecation) |
| C-AUTH-05 | MDP temporaire = username | MAJEUR | CORRIGE | `main.py` (`secrets.token_urlsafe(16)`) |
| C-AUTH-06 | Endpoints admin sans role check | CRITIQUE | CORRIGE | `main.py`, `groups_router.py`, `cdm_access_router.py` |
| C-AUTH-07 | IDOR sur mise a jour cohortes | MAJEUR | CORRIGE | `cohort/router.py` (ajout `_can_access_cohort()` sur PUT) |
| C-AUTH-08 | SSRF via db_host CDM | MAJEUR | CORRIGE | `cdm_router.py` (validation hostname, rejet loopback/link-local/metadata) |
| C-CRYPTO-01 | Cle Fernet en 0o644 | CRITIQUE | CORRIGE | `utils/crypto.py` (change en 0o600) |
| C-CRYPTO-02 | SECRET_KEY par defaut | CRITIQUE | CORRIGE | `config.py` (blocage en prod), `docker-compose.yml` (`${SECRET_KEY:?...}`) |
| C-CRYPTO-03 | MDP PostgreSQL en clair | MAJEUR | CORRIGE | `docker-compose.yml` (externalise via `${POSTGRES_PASSWORD:?...}`) |
| C-CRYPTO-04 | Pas de TLS inter-services | MAJEUR | PARTIEL | `db/omop_connector.py` (ajout param sslmode pour CDM externes) |
| C-DB-01 | Injection SQL via identifiants | CRITIQUE | CORRIGE | `utils/sql_safety.py` (nouveau), `concept/router.py`, `quality/domains/clinical.py`, `mapping/router.py`, `mapping/suggest.py`, `cohort/sql_builder.py` |
| C-DB-02 | Validation non uniforme | MAJEUR | CORRIGE | Centralise via `utils/sql_safety.py` (resolu par C-DB-01) |
| C-DB-04 | Messages d'erreur verbeux | MODERE | CORRIGE | `concept/router.py`, `quality/router.py`, `mapping/router.py`, `cohort/router.py`, `datamanagement/router.py`, `cohort/characterization.py` |
| C-DB-05 | Pas de connection pooling | MODERE | DEJA CORRIGE | `db/omop_connector.py` (ThreadedConnectionPool existait deja) |

---

## Constats restants

| ID | Constat | Severite | Type |
|---|---|---|---|
| C-DB-03 | Connexions CDM sans TLS | MAJEUR | Infrastructure (sslmode ajoute, config a activer) |
| C-API-01 | CORS trop permissif | MODERE | Configuration |
| C-API-02 | Pas de rate limiting | MAJEUR | Code + Infrastructure |
| C-API-03 | Headers securite manquants (CSP) | MODERE | Infrastructure (Nginx) |
| C-API-04 | Path traversal possible (i18n) | MODERE | Code |
| C-API-05 | Pas de protection CSRF | MODERE | Code |
| C-API-06 | Swagger expose en production | MINEUR | Configuration |
| C-INFRA-01 | Docker socket monte | CRITIQUE | Infrastructure |
| C-INFRA-02 | Keycloak en mode dev/root | CRITIQUE | Infrastructure |
| C-INFRA-03 | Dependances non epinglees | MODERE | Infrastructure |
| C-INFRA-04 | Pas de segmentation reseau | MODERE | Infrastructure |
| C-INFRA-05 | Port PostgreSQL expose | MODERE | Infrastructure |
| C-INFRA-06 | Pas de scan de vulnerabilites | MODERE | CI/CD |
| C-RGPD-01 | Base legale non documentee | MAJEUR | Documentation |
| C-RGPD-02 | AIPD absente | MAJEUR | Documentation |
| C-RGPD-03 | Droits des personnes non impl. | MAJEUR | Code + Processus |
| C-RGPD-04 | Registre des traitements absent | MAJEUR | Documentation |
| C-RGPD-05 | Pas de consentement/information | MAJEUR | Code + Documentation |
| C-RGPD-06 | Pseudonymisation absente | MAJEUR | Code |
| C-RGPD-07 | Durees de conservation non def. | MODERE | Configuration |
| C-RGPD-10 | Exports patient-level sans anonymisation | MAJEUR | Code |
| C-RGPD-11 | Pas de finalite documentee | MAJEUR | Documentation |
| C-RGPD-08 | DPO non designe | MODERE | Organisationnel |
| C-RGPD-09 | Procedure violation absente | MODERE | Documentation |
| C-HDS-01 | Certification HDS non verifiee | MAJEUR | Organisationnel |
| C-HDS-02 | PCA/PRA absent | MAJEUR | Documentation |
| C-HDS-03 | Chiffrement au repos partiel | MODERE | Infrastructure |
| C-LOG-01 | Logs sans integrite crypto | MODERE | Code |
| C-LOG-02 | Consultations non tracees | MAJEUR | Code |
| C-LOG-03 | Retention logs insuffisante | MODERE | Configuration |
| C-LOG-04 | Pas de centralisation logs | MODERE | Infrastructure |
| C-LOG-05 | Pas d'alerting securite | MODERE | Infrastructure |

---

## Tests

- **315 tests backend** : tous passent (0 echecs)
- Tests RBAC specifiques : `tests/test_role_access.py` (27 tests)
- Tests audit : `tests/test_audit_api.py` (13 tests)
- Tests admin : `tests/test_admin_api.py` (14 tests)
- Tests access requests : `tests/test_access_requests.py` (18 tests)

---

## Fichiers crees

| Fichier | Description |
|---|---|
| `backend/utils/sql_safety.py` | Validation centralisee des identifiants SQL |
| `backend/tests/test_role_access.py` | Tests RBAC defense-in-depth |

## Infrastructure de tests amelioree

- `conftest.py` : SQLite in-memory avec `StaticPool` (plus de fichier `.db`)
- `conftest.py` : Support `X-Test-Roles` / `X-Test-Username` pour simuler les roles
- `app_db.py` : Parametres pool conditionnels (SQLite vs PostgreSQL)
