# Audit Fonctionnel Approfondi — OPAL v1.2.0

**Date** : 2026-03-18
**Périmètre** : 19 modules backend (200+ endpoints), 15 pages frontend, 48 fichiers de tests backend, 7 fichiers de tests frontend
**Méthodologie** : Lecture complète de chaque fichier source, traçage des flux de données API→DB→OMOP, analyse ligne par ligne de sql_builder.py (1152 lignes), pathways.py (347 lignes), suggest.py (845 lignes)
**Auditeur** : Claude Code — audit exhaustif basé sur le code source et l'historique des commits

---

## Résumé Exécutif

| Sévérité | Nombre |
|----------|--------|
| CRITIQUE | 4 |
| HAUTE | 9 |
| MOYENNE | 12 |
| BASSE | 8 |
| **Total** | **33** |

OPAL implémente un ensemble fonctionnel remarquablement complet pour une plateforme OMOP CDM : qualité Achilles-like (5 analyseurs de domaines), cohort builder avec SQL dynamique (1152 lignes, 10+ types de critères), mapping avec 5 stratégies, pathways ATLAS-style, incidence, estimation Kaplan-Meier, et data management. L'analyse en profondeur révèle cependant des bugs concrets dans le code, des incohérences API/frontend, et des lacunes fonctionnelles significatives.

---

## Constats Positifs

### Architecture
- **19 modules bien découplés** avec routers séparés, logique métier isolée
- **22 modèles** avec indexes composites pertinents (`cdm_name+domain+version`, `cohort_id+version`, `username+read`)
- **Système de permissions** piloté par `permissions.yaml` — 4 rôles : admin, data-manager, chercheur, medecin
- **Notifications temps réel** via WebSocket avec préférences par utilisateur
- **Versioning** des snapshots qualité et des versions de cohorte
- **Audit trail complet** avec logs JSONL rotatifs et rétention 30 jours

### Modules métier
- **Quality** : 5 analyseurs (Person, ObservationPeriod, Dashboard, Clinical×8, Conformity 20+ checks)
- **Cohort Builder** : Critères JSON → SQL avec relations temporelles d'Allen, same-visit, concept_ancestor, demographics, measurement ranges, occurrence frequency
- **Mapping** : 5 stratégies (exact, relationship, ingredient/DCI, fuzzy/trigram, contextual) + SapBERT pré-calculé
- **Pathways** : Algorithme ATLAS-style complet (target cohort → events → eras → sequencing → sunburst)
- **Incidence** : Taux d'incidence avec stratification âge/sexe
- **Estimation** : Kaplan-Meier avec test log-rank et IC Greenwood

### Tests
- **48 fichiers de tests backend** (~9250 lignes) couvrant tous les modules majeurs
- Tests avec SQLite in-memory via `conftest.py` — pas de dépendance externe
- Mocks OMOP via `omop_mock.py` pour les connecteurs

---

## CRITIQUE

### F1 — Critères JSON de cohorte : aucune validation de structure

**Fichier** : `backend/modules/cohort/router.py:49`

```python
class CohortCreateRequest(BaseModel):
    criteria: dict  # ← AUCUNE validation Pydantic !
```

Le champ `criteria` accepte n'importe quel dictionnaire. Le `sql_builder.py` fait du parsing interne avec `get()` et valeurs par défaut, mais aucun schéma ne valide la structure.

**Bugs concrets identifiés** :
- `concept_ids: "string"` au lieu de `[int]` → `int()` crashe avec ValueError non gérée
- `criteria: {}` (vide) → `build_cohort_sql` retourne SQL invalide
- Profondeur illimitée (10000 niveaux imbriqués) → stack overflow / OOM → **DoS**
- Liste de 1M+ concept_ids → construction SQL de plusieurs Mo → timeout DB

**Impact** : Erreurs 500 cryptiques, DoS possible, débogage impossible pour l'utilisateur.

**Remédiation** : Créer un modèle Pydantic récursif avec limites (max_depth=5, max_concepts=10000).

---

### F2 — Bugs dans le code SSE de quality/router.py

**Fichier** : `backend/modules/quality/router.py`

**Bug 1 — Ligne 377** : `queue.Queue.get(True, 2.0)` — signature incorrecte
```python
msg = progress_queue.get(True, 2.0)  # Devrait être get(block=True, timeout=2.0)
```
L'appel positional fonctionne en CPython mais est fragile. Plus important : si la queue est vide et le timeout expire, `queue.Empty` n'est pas capturé → crash du générateur SSE.

**Bug 2 — Ligne 420** : `conn.closed` n'existe pas sur psycopg2
```python
if not conn.closed:
    conn.cancel()  # conn.closed n'est pas un attribut standard
```
Devrait être `if conn and conn.status != psycopg2.extensions.STATUS_READY`.

**Impact** : Crash silencieux des analyses SSE en cours, annulation d'analyse non fonctionnelle.

---

### F3 — Couverture de tests frontend très faible (7 fichiers / 15 pages)

**Tests existants** : `client.test.ts`, `AnimatedList.test.tsx`, `SkeletonPatterns.test.tsx`, `ErrorState.test.tsx`, `Toast.test.tsx`, `Empty.test.tsx`, `useTheme.test.ts`

**Tests manquants critiques** :
- **0 test de page** (QualityPage, CohortPage, MappingPage, etc.)
- **0 test d'authentification** (KeycloakContext.tsx)
- **0 test WebSocket** (useNotificationWs.ts)
- **0 test du cohort builder** (QueryCanvas, CriteriaGroupEditor)
- **0 test de routage/protection** (ProtectedRoute)

**Impact** : Régressions frontend non détectées. Bug lors de refactoring silencieux.

---

### F4 — 3 domaines OMOP manquants dans DOMAIN_CONFIG

**Fichier** : `backend/config.py` — DOMAIN_CONFIG

**Domaines implémentés (8/11)** : Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death

**Domaines manquants** :
- ❌ `Specimen` — Échantillons biologiques
- ❌ `Note` / `Note_NLP` — Données textuelles (essentiel en milieu hospitalier français)
- ❌ `Payer_Plan_Period` — Couverture assurantielle

**Impact** : Impossible d'analyser la qualité, construire des cohortes, ou mapper ces domaines. Les requêtes échouent silencieusement quand un utilisateur sélectionne un domaine non supporté.

---

## HAUTE

### F5 — Gestion d'erreurs inconsistante entre modules

| Module | 404 pattern | Auth check | CDM access check |
|--------|-------------|------------|-----------------|
| `cohort/router.py` | `HTTPException(404)` | Middleware | `check_cdm_access()` |
| `mapping/router.py` | `HTTPException(404)` | Middleware | `check_cdm_access()` |
| `saved_queries_router.py` | `HTTPException(404)` | Owner check L.89 | **Non** |
| `favorites_router.py` | `HTTPException(404)` | Username filter | **Non** |
| `concept_set/router.py` | `JSONResponse(404)` | Middleware | **1 endpoint sur 7** |
| `incidence/router.py` | `HTTPException(404)` | Middleware | **2 endpoints sur 5** |
| `estimation/router.py` | `HTTPException(404)` | Middleware | **2 endpoints sur 5** |

15+ endpoints ne vérifient pas l'accès CDM (détail dans l'audit sécurité C3).

---

### F6 — Endpoint d'exécution de requêtes sauvegardées absent

**Fichier** : `backend/modules/saved_queries_router.py`

Le module permet de sauvegarder des requêtes SQL mais n'a PAS d'endpoint d'exécution. Les requêtes sauvegardées ne sont qu'un carnet de notes.

---

### F7 — Race condition dans l'annulation d'analyse qualité

**Fichier** : `backend/modules/quality/router.py:395-427`

L'annulation vérifie l'existence dans `_active_analyses` puis modifie `cancelled=True` dans deux sections `with _active_analyses_lock:` séparées. Entre les deux, le worker thread peut terminer et supprimer l'entrée → TOCTOU.

---

### F8 — Mapping `apply` : écriture CDM sans dry-run ni backup

**Fichier** : `backend/modules/mapping/router.py`

`POST /api/mapping/apply/{cdm_name}/{domain}` écrit dans `source_to_concept_map` du CDM externe — la SEULE opération d'écriture. Pas de mode `dry_run`, pas de backup automatique, pas de rollback sur erreur partielle.

---

### F9 — Pas de soft-delete pour les cohortes

**Fichier** : `backend/modules/cohort/router.py`

`DELETE /api/cohorts/{id}` supprime définitivement la cohorte, ses versions, caractérisations et pathways. Les analyses d'incidence/estimation référençant cette cohorte deviennent orphelines.

---

### F10 — Incidence/Estimation : pas de gestion d'erreur sur cohortes inexistantes

**Fichier** : `backend/modules/incidence/router.py`, `estimation/router.py`

Si une cohorte référencée est supprimée entre la création de l'analyse et son exécution → erreur 500 non gérée.

---

### F11 — Pas de validation des `concept_ids` dans pathways

**Fichier** : `backend/modules/cohort/pathways.py:119-143`

```python
ids_str = ",".join(str(int(cid)) for cid in concept_ids)
```
Liste vide → `IN ()` syntax error SQL. IDs négatifs acceptés silencieusement.

---

### F12 — Pas de cascade delete dans les modèles

**Fichier** : `backend/db/models.py`

- Suppression Cohort : CohortVersion, CohortShare, IncidenceAnalysis non cascadés → orphelins
- Suppression UserGroup : UserGroupMember orphelins
- Suppression CdmConfig : CdmAccess/CdmGroupAccess stale → rows fantômes

---

### F13 — `created_by` nullable sur Cohort sans NULL guards

**Fichier** : `backend/db/models.py:71`

`created_by` est nullable mais utilisé pour les vérifications de partage sans guard → cohorts orphelines possibles si créées avant que le champ soit obligatoire.

---

## MOYENNE

### F14 — API/Frontend : ohdsiApi.logsUrl est `async` sans opération async

**Fichier** : `frontend/src/api/client.ts:455-463` et `OhdsiPage.tsx:132`

```typescript
logsUrl: async (service: string, offset?: number): Promise<string> => {
  // Aucune opération async, juste construction d'URL
  return `/api/ohdsi/logs/${service}${qs}`;
}
```
Utilisé avec `await` inutilement. Code trompeur.

---

### F15 — QualityPage : progress bar non reset au cancel

**Fichier** : `frontend/src/pages/QualityPage.tsx:456-467`

Après annulation d'un batch, la barre de progression reste affichée avec les données stale. Le prochain lancement montre un état incohérent.

---

### F16 — Race condition dans useNotifDots

**Fichier** : `frontend/src/hooks/useNotifDots.ts:21-30`

Flag `fetchingRef` simple qui silencieusement drop les requêtes concurrentes de rafraîchissement de badges. Le dernier état peut être stale.

---

### F17 — ConceptSetPage/IncidencePage/EstimationPage : routes dupliquées

Ces pages sont BOTH :
- Embarquées comme tabs dans CohortPage
- Routes standalone dans App.tsx

Risque de state management dupliqué si ouvertes simultanément.

---

### F18 — i18n incomplète : LoginPage et OhdsiPage ont des strings français hardcodées

**Fichiers** : `frontend/src/pages/LoginPage.tsx`, `OhdsiPage.tsx`

Certaines chaînes sont en français directement dans le JSX au lieu d'utiliser les clés i18n.

---

### F19 — Quality : pas de pagination sur `list_snapshots`

**Fichier** : `backend/modules/quality/router.py:587-607`

Charge TOUS les snapshots avec leur colonne `results` (JSON volumineux) en mémoire.

---

### F20 — Concept Explorer : navigation hiérarchique limitée

**Fichier** : `backend/modules/concept/router.py`

Pas de navigation par vocabulaire, pas de filtrage par concept_class, pas d'affichage complet des relations concept_relationship.

---

### F21 — Cohort sharing : pas de notification de retrait de partage

L'utilisateur perd l'accès silencieusement quand un partage est retiré.

---

### F22 — Data Management : pas de preview avant extraction

Pas de preview (10 premières lignes) ni d'estimation du volume avant lancement.

---

### F23 — OHDSI : dépendance Docker-in-Docker non documentée pour l'utilisateur

Le prérequis du socket Docker n'est pas documenté dans le guide utilisateur.

---

### F24 — Groups : pas de hiérarchie ni de nested groups

Structure plate, insuffisante pour un hôpital avec services/pôles.

---

### F25 — Search : recherche globale ne couvre pas tous les types

Ne couvre pas : snapshots qualité, analyses incidence/estimation, décisions de mapping, groupes.

---

## BASSE

### F26 — `AccessRequest` : pas de notification email (uniquement in-app)
### F27 — Cohort templates : catégorisation par string libre, pas de système structuré
### F28 — Pas de versioning d'API (`/api/v1/`)
### F29 — OpenAPI : pas de descriptions détaillées ni exemples
### F30 — Pas de mode offline/dégradé côté frontend
### F31 — Pas de raccourcis clavier
### F32 — Pas de mécanisme d'export/import de définitions de cohortes
### F33 — Pas de backup/restore intégré

---

## Couverture de Tests — Analyse Détaillée

### Backend (48 fichiers, ~9250 lignes)

| Module | Fichiers de test | Couverture | Lacunes |
|--------|-----------------|-----------|---------|
| Quality (engine, domains, comparator, conformity, report) | 7 | Bonne | Pas de test de cancellation, SSE non testé |
| Cohort (builder, router, pathways, comparison, diff) | 6 | Bonne | Pas de test de critères malformés |
| Mapping (router, suggest) | 2 | Moyenne | Pas de test de batch suggest |
| Concept (router, cache) | 2 | Moyenne | Pas de test de hiérarchie |
| Notifications (endpoints, preferences, WS) | 4 | Bonne | — |
| Admin (API, role access, access requests) | 3 | Bonne | — |
| CDM (access, helper) | 2 | Moyenne | SSRF non testé |
| Saved queries, favorites, groups, templates | 4 | Moyenne | — |
| Incidence, estimation, datamanagement | 5 | Bonne | — |
| Search, audit, i18n, crypto | 4 | Bonne | — |
| SQL builder | 1 | Bonne | Pas de test temporal/occurrence |

**Lacunes critiques** :
- Pas de tests d'intégration end-to-end
- Pas de tests de performance/charge
- Pas de tests de concurrence (race conditions)
- Pas de tests des edge cases JSON malformés dans les critères de cohorte

### Frontend (7 fichiers, ~84 tests)

| Composant | Testé ? |
|-----------|---------|
| Composants UI (5 fichiers) | ✅ |
| Client API | ✅ |
| Hook thème | ✅ |
| Pages (15 pages) | ❌ |
| Auth context | ❌ |
| WebSocket hook | ❌ |
| Cohort components | ❌ |
| Quality components | ❌ |
| GlobalSearch | ❌ |
| Routing / ProtectedRoute | ❌ |

---

## Conformité OMOP CDM

### Tables supportées

| Table CDM | Qualité | Cohort | Mapping | Concept | Pathways |
|-----------|---------|--------|---------|---------|----------|
| person | ✅ | ✅ | — | — | — |
| observation_period | ✅ | ✅ | — | — | ✅ |
| visit_occurrence | ✅ | ✅ | ✅ | ✅ | ✅ |
| condition_occurrence | ✅ | ✅ | ✅ | ✅ | ✅ |
| drug_exposure | ✅ | ✅ | ✅ | ✅ | ✅ |
| measurement | ✅ | ✅ | ✅ | ✅ | ✅ |
| procedure_occurrence | ✅ | ✅ | ✅ | ✅ | ✅ |
| observation | ✅ | ✅ | ✅ | ✅ | — |
| device_exposure | ✅ | ✅ | ✅ | ✅ | ✅ |
| death | ✅ | ✅ | ✅ | ✅ | — |
| concept | — | ✅ | ✅ | ✅ | — |
| concept_ancestor | — | ✅ | — | ✅ | ✅ |
| concept_relationship | — | — | ✅ | ✅ | — |
| vocabulary | — | — | — | ✅ | — |
| source_to_concept_map | — | — | ✅ (write) | — | — |

### Tables non supportées (CDM v5.4)

- `specimen` — Échantillons biologiques
- `note` / `note_nlp` — Données textuelles
- `cost` — Données de coûts
- `payer_plan_period` — Couverture assurantielle
- `episode` / `episode_event` — Épisodes de soins (v5.4)

---

## Matrice de Remédiation

| ID | Effort | Impact | Priorité |
|----|--------|--------|----------|
| F1 | Moyen | Critique | Semaine 1 |
| F2 | Faible | Critique | Semaine 1 |
| F3 | Élevé | Critique | Sprint dédié |
| F4 | Moyen | Critique | Semaine 2 |
| F5 | Moyen | Haute | Semaine 2 |
| F6-F13 | Variable | Haute | Semaine 2-3 |
| F14-F25 | Variable | Moyenne | Semaine 3-4 |
| F26-F33 | Variable | Basse | Backlog |
