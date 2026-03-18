# Audit Fonctionnel — OPAL v1.2.0

**Date** : 2026-03-18
**Périmètre** : 19 modules backend, 15 pages frontend, 48 fichiers de tests backend, 7 fichiers de tests frontend
**Méthodologie** : Revue de code, analyse de couverture, vérification de complétude OMOP CDM, cohérence API/UI

---

## Résumé Exécutif

| Sévérité | Nombre |
|----------|--------|
| CRITIQUE | 2 |
| HAUTE | 7 |
| MOYENNE | 10 |
| BASSE | 7 |
| **Total** | **26** |

OPAL implémente un ensemble fonctionnel remarquablement complet pour une plateforme OMOP CDM : qualité avec Achilles-like, cohort builder avec SQL dynamique, mapping avec 6 stratégies, pathways ATLAS-style, incidence, estimation Kaplan-Meier, et data management. La couverture de tests backend est solide (48 fichiers, ~9250 lignes). Les problèmes principaux concernent la couverture de tests frontend, des lacunes de validation sur les critères JSON cohort, et des incohérences entre certains contrats API.

---

## Constats Positifs

### Architecture
- **19 modules bien découplés** avec routers séparés, logique métier isolée
- **22 modèles** avec indexes composites pertinents et contraintes d'unicité
- **Système de permissions** piloté par `permissions.yaml` — source unique de vérité
- **4 rôles** bien définis : admin, data-manager, chercheur, medecin
- **Notifications temps réel** via WebSocket avec préférences par utilisateur
- **Versioning** des snapshots qualité et des versions de cohorte
- **Audit trail complet** avec logs JSONL rotatifs et rétention configurable

### Modules métier
- **Quality** : Analyse Person, ObservationPeriod, Dashboard, et 8 domaines cliniques avec conformité CDM structurelle
- **Cohort Builder** : Critères JSON → SQL avec relations temporelles d'Allen, same-visit linking, concept_ancestor expansion
- **Mapping** : 6 stratégies de suggestion (SapBERT, exact, relationship, keyword, fuzzy, contextual) avec workflow de validation
- **Pathways** : Algorithme ATLAS-style avec sunburst tree pour la visualisation
- **Incidence** : Calcul de taux d'incidence avec stratification âge/sexe et intervalles de confiance
- **Estimation** : Kaplan-Meier pur Python avec test log-rank et Greenwood CI
- **Data Management** : Extraction de données avec sélection de tables/colonnes et progress polling

### Tests
- **48 fichiers de tests backend** (~9250 lignes) couvrant tous les modules majeurs
- Tests avec SQLite in-memory via `conftest.py` — pas de dépendance externe
- Mocks OMOP via `omop_mock.py` pour les tests de connecteurs
- Tests WebSocket (`test_ws_endpoint.py`, `test_ws_manager.py`, `test_ws_nginx.py`)

### Frontend
- **15 pages** avec lazy loading complet
- Design system neumorphique cohérent avec 20+ composants UI
- Error Boundary global avec composant ErrorState riche
- PageSkeleton pour les états de chargement
- 11 variantes d'Empty states
- Auth context avec PKCE S256 et token refresh automatique

---

## CRITIQUE

### F1 — Critères JSON de cohorte : validation insuffisante côté backend

**Fichier** : `backend/modules/cohort/router.py:49` et `backend/modules/cohort/sql_builder.py`

```python
class CohortCreateRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    criteria: dict  # ← Aucune validation de structure !
```

Le champ `criteria` accepte n'importe quel dictionnaire JSON. Le `sql_builder.py` fait du parsing interne avec des `get()` et des valeurs par défaut, mais il n'y a pas de validation Pydantic des critères avant la construction SQL.

**Risque** :
- Un JSON malformé peut provoquer des `KeyError` non capturés dans `sql_builder.py`
- Des types inattendus (ex: `concept_ids: "string"` au lieu de `[int]`) peuvent produire du SQL invalide
- L'absence de validation rend le débogage difficile pour les utilisateurs

**Impact** : Erreurs 500 cryptiques au lieu de 422 avec message clair.

**Remédiation** : Créer un modèle Pydantic récursif pour les critères :
```python
class CriterionItem(BaseModel):
    domain: str
    concept_ids: list[int] = []
    include_descendants: bool = False
    # ... autres champs attendus

class CohortCriteria(BaseModel):
    inclusion: list[CriterionGroup]
    exclusion: list[CriterionGroup] = []
```

---

### F2 — Couverture de tests frontend très faible

**Fichiers** : `frontend/src/` — 7 fichiers de tests uniquement

Tests existants :
- `client.test.ts` — Client API
- `AnimatedList.test.tsx`, `SkeletonPatterns.test.tsx`, `ErrorState.test.tsx`, `Toast.test.tsx`, `Empty.test.tsx` — Composants UI
- `useTheme.test.ts` — Hook thème

Tests manquants critiques :
- **Aucun test de pages** (`QualityPage`, `CohortPage`, `MappingPage`, etc.)
- **Aucun test du contexte d'authentification** (`KeycloakContext.tsx`)
- **Aucun test du WebSocket** (`useNotificationWs.ts`)
- **Aucun test du composant cohort** (`QueryCanvas`, `CriteriaGroupEditor`, etc.)
- **Aucun test de GlobalSearch**
- **Aucun test de routage et protection des routes**

**Impact** : Les régressions frontend ne sont pas détectées. Les 84 tests mentionnés dans CLAUDE.md contrastent avec les 7 fichiers réels — possible inflation du count.

**Remédiation** : Prioriser les tests sur :
1. `KeycloakContext.tsx` — authentification
2. `CohortPage` / `QueryCanvas` — logique complexe de construction de critères
3. `QualityPage` — affichage des résultats d'analyse
4. Routage / protection des pages par permissions

---

## HAUTE

### F3 — Pas de validation des `concept_ids` dans pathways

**Fichier** : `backend/modules/cohort/pathways.py:119-143`

```python
for ec in event_cohorts:
    concept_ids = ec.get("concept_ids", [])
    # ...
    ids_str = ",".join(str(int(cid)) for cid in concept_ids)
```

Les `concept_ids` sont extraits directement du JSON utilisateur sans validation Pydantic. Le `int()` protège contre l'injection SQL, mais une liste vide ou des IDs négatifs ne sont pas rejetés.

**Impact** : `IN ()` (liste vide) provoque une erreur SQL syntax. Des IDs négatifs ne correspondent à rien mais consomment du temps de requête.

**Remédiation** : Valider avec `concept_ids: list[int] = Field(min_items=1)` dans un modèle Pydantic.

---

### F4 — Gestion d'erreurs inconsistante entre modules

Comparaison des patterns d'erreur :

| Module | 404 pattern | Auth check | CDM access check |
|--------|-------------|------------|-----------------|
| `cohort/router.py` | `raise HTTPException(404)` | Via middleware | `check_cdm_access()` helper |
| `mapping/router.py` | `raise HTTPException(404)` | Via middleware | `check_cdm_access()` helper |
| `saved_queries_router.py` | `raise HTTPException(404)` | Owner check (ligne 89) | Non |
| `favorites_router.py` | `raise HTTPException(404)` | Via username | Non |
| `concept_set/router.py` | `raise HTTPException(404)` | Via middleware | Non |
| `notifications_router.py` | `raise HTTPException(404)` | Via user filter | N/A |

Les modules secondaires (`saved_queries`, `favorites`, `concept_set`) n'ont pas de vérification explicite d'accès CDM. Un utilisateur peut lire les favoris ou concept sets d'un CDM auquel il n'a pas accès.

**Remédiation** : Standardiser avec `check_cdm_access()` dans tous les modules qui manipulent des données liées à un CDM.

---

### F5 — Endpoint d'exécution de requêtes SQL sauvegardées absent

**Fichier** : `backend/modules/saved_queries_router.py`

Le module `saved_queries` permet de sauvegarder des requêtes SQL mais n'a PAS d'endpoint d'exécution. Le frontend `SqlEditor.tsx` envoie les requêtes directement au CDM via un endpoint séparé.

**Impact** : Les requêtes sauvegardées ne sont qu'un carnet de notes. Aucune fonctionnalité d'exécution depuis la liste des requêtes, pas de partage ni de résultats historiques.

**Remédiation** : Considérer un endpoint `POST /api/saved-queries/{id}/execute` avec les protections adéquates (read-only, statement_timeout, résultats paginés).

---

### F6 — Incidence/Estimation : pas de gestion d'erreur sur cohortes inexistantes

**Fichier** : `backend/modules/incidence/router.py` et `backend/modules/estimation/router.py`

L'exécution d'une analyse d'incidence ou estimation référence des `cohort_id` (target + outcome). Si une cohorte est supprimée entre la création de l'analyse et son exécution, le code lèvera une erreur non gérée.

**Impact** : Erreur 500 au lieu d'un message clair "Cohorte cible introuvable".

**Remédiation** : Vérifier l'existence des cohortes avant l'exécution et retourner un 404 descriptif.

---

### F7 — Mapping `apply` : écriture sur CDM externe sans confirmation forte

**Fichier** : `backend/modules/mapping/router.py`

L'endpoint `POST /api/mapping/apply/{cdm_name}/{domain}` écrit dans la table `source_to_concept_map` du CDM externe. C'est la SEULE opération d'écriture sur les CDMs externes (sinon read-only).

**Impact** : Une erreur dans les mappings appliqués peut corrompre la table `source_to_concept_map`. Il n'y a pas de mécanisme de rollback automatique ni de dry-run.

**Remédiation** :
- Ajouter un mode `dry_run=true` qui retourne le SQL sans l'exécuter
- Créer un backup de la table avant l'apply (`CREATE TABLE ... AS SELECT * FROM ...`)
- Ajouter une confirmation explicite côté API (token de confirmation)

---

### F8 — Race condition dans l'annulation d'analyse qualité

**Fichier** : `backend/modules/quality/router.py:395-427`

L'annulation d'une analyse vérifie l'existence de l'entrée dans `_active_analyses` puis modifie `cancelled=True` dans deux sections `with _active_analyses_lock:` séparées. Entre ces deux sections, le worker thread peut terminer et supprimer l'entrée, créant une race condition TOCTOU.

**Impact** : L'annulation peut échouer silencieusement ou lever une KeyError.

**Remédiation** : Regrouper check + modification dans une seule section verrouillée.

---

### F9 — Pas de soft-delete pour les cohortes

**Fichier** : `backend/modules/cohort/router.py`

La suppression d'une cohorte (`DELETE /api/cohorts/{id}`) est définitive. Les versions, caractérisations, et pathways associées sont perdues. Si des analyses d'incidence/estimation référencent cette cohorte, elles deviennent orphelines.

**Impact** : Perte de données irréversible. Les analyses référençant la cohorte deviennent incohérentes.

**Remédiation** : Ajouter un champ `deleted_at` pour soft-delete, avec purge après 30 jours. Ou ajouter une vérification de dépendances avant suppression.

---

## MOYENNE

### F10 — i18n incomplète : seuls `en.json` et `fr.json`

**Fichier** : `backend/i18n/`

L'application ne supporte que l'anglais et le français. Pour une application médicale internationale, c'est insuffisant.

**Impact** : Utilisateurs non francophones/anglophones doivent utiliser l'interface en anglais.

---

### F11 — Keycloak `start-dev` avec import de realm : pas de migration automatique

**Fichier** : `docker-compose.yml:100`

`--import-realm` importe le realm depuis un fichier JSON au démarrage, mais uniquement si le realm n'existe pas déjà. Les modifications ultérieures du fichier `opal-realm.json` ne sont pas appliquées.

**Impact** : Les mises à jour de configuration (nouveaux rôles, scopes, clients) nécessitent une suppression manuelle du realm.

---

### F12 — Concept Explorer : pas de navigation hiérarchique complète

**Fichier** : `backend/modules/concept/router.py`

Le module concept fournit la recherche et la hiérarchie parent/enfant, mais ne supporte pas :
- Navigation par vocabulaire (lister tous les vocabs, puis drill-down)
- Filtrage par classe de concept
- Affichage des relations (`concept_relationship` complet)

**Impact** : Expérience de navigation limitée comparée à ATLAS Vocabulary Search.

---

### F13 — Quality analysis : pas d'annulation côté utilisateur

**Fichier** : `backend/modules/quality/router.py`

L'analyse qualité SSE n'a pas de mécanisme d'annulation. Si un utilisateur lance une analyse puis navigue ailleurs, l'analyse continue en arrière-plan sans possibilité d'arrêt.

**Impact** : Gaspillage de ressources. Un utilisateur peut lancer accidentellement 10 analyses coûteuses.

---

### F14 — Cohort sharing : pas de notification de retrait de partage

**Fichier** : `backend/modules/cohort_sharing_router.py`

Quand un partage de cohorte est retiré (`DELETE /api/cohorts/{id}/shares`), l'utilisateur cible n'est pas notifié. Il perd silencieusement l'accès.

**Impact** : Confusion utilisateur — la cohorte disparaît sans explication.

---

### F15 — Data Management : pas de preview avant extraction

**Fichier** : `backend/modules/datamanagement/router.py`

L'extraction de données lance directement le traitement complet. Il n'y a pas de preview (ex: 10 premières lignes) ni d'estimation du volume de données.

**Impact** : L'utilisateur ne sait pas ce qu'il va obtenir avant de lancer une extraction potentiellement volumineuse.

---

### F16 — OHDSI : dépendance à Docker-in-Docker non documentée

**Fichier** : `backend/modules/ohdsi/router.py`

L'intégration OHDSI requiert le socket Docker monté dans le container. Cette dépendance n'est pas documentée dans le guide utilisateur et peut surprendre les opérateurs.

---

### F17 — Groups : pas de hiérarchie ni de nested groups

**Fichier** : `backend/modules/groups_router.py`

Les groupes sont plats — pas de sous-groupes ni de hiérarchie organisationnelle. Pour un hôpital avec des services/pôles, la structure est trop limitée.

---

### F18 — Search : recherche globale ne couvre pas tous les types

**Fichier** : `backend/modules/search_router.py`

La recherche globale couvre cohortes, concept sets, et requêtes sauvegardées, mais pas :
- Snapshots d'analyse qualité
- Analyses d'incidence/estimation
- Décisions de mapping
- Groupes d'utilisateurs

---

### F19 — Pas de système d'export/import de cohortes

Il n'y a pas de fonctionnalité pour exporter une définition de cohorte (JSON) et l'importer dans une autre instance OPAL ou un autre CDM.

---

## BASSE

### F20 — `AccessRequest` : pas de notification par email

**Fichier** : `backend/modules/admin_router.py`

Les demandes d'accès génèrent une notification in-app pour les admins, mais pas d'email. Si aucun admin n'est connecté, la demande peut rester en attente indéfiniment.

---

### F21 — Cohort templates : pas de catégorisation hiérarchique

**Fichier** : `backend/modules/cohort_templates_router.py`

Les templates ont un champ `category` (String) mais pas de système de catégories structuré. Impossible de filtrer par spécialité médicale de manière fiable.

---

### F22 — Pas de versioning d'API

L'API n'utilise pas de préfixe de version (`/api/v1/`). Les changements breaking nécessiteront une migration coordonnée frontend/backend.

---

### F23 — Pas de documentation OpenAPI enrichie

**Fichier** : `backend/main.py:34-38`

FastAPI génère l'OpenAPI automatiquement, mais les endpoints manquent de :
- Descriptions détaillées des paramètres
- Exemples de requêtes/réponses
- Codes d'erreur documentés

---

### F24 — Pas de mode offline/dégradé côté frontend

Si le backend est indisponible, le frontend affiche des erreurs génériques. Pas de mode offline avec cache local des dernières données consultées.

---

### F25 — Frontend : pas de raccourcis clavier

Pour un outil analytique utilisé quotidiennement, l'absence de raccourcis clavier (navigation, recherche rapide, actions fréquentes) est un manque d'ergonomie.

---

### F26 — Pas de mécanisme de backup/restore intégré

Pas de commande ou endpoint pour sauvegarder/restaurer la base applicative (cohortes, mappings, snapshots). La sauvegarde dépend entièrement de l'opérateur.

---

## Couverture de Tests — Analyse Détaillée

### Backend (48 fichiers, ~9250 lignes)

| Module | Fichiers de test | Couverture |
|--------|-----------------|-----------|
| Quality (engine, domains, comparator, conformity, report) | 7 | Bonne |
| Cohort (builder, router, pathways, comparison, diff) | 6 | Bonne |
| Mapping (router, suggest) | 2 | Moyenne |
| Concept (router, cache) | 2 | Moyenne |
| Notifications (endpoints, preferences, WS) | 4 | Bonne |
| Admin (API, role access, access requests) | 3 | Bonne |
| CDM (access, helper) | 2 | Moyenne |
| Saved queries, favorites, groups, templates | 4 | Moyenne |
| Incidence, estimation, datamanagement | 5 | Bonne |
| Search, audit, i18n, crypto | 4 | Bonne |
| SQL builder | 1 | Bonne |

**Lacunes identifiées** :
- Pas de test d'intégration end-to-end (API → DB → OMOP mock)
- Pas de tests de performance/charge
- Pas de tests de concurrence (race conditions)

### Frontend (7 fichiers, ~84 tests estimés)

| Composant | Testé ? |
|-----------|---------|
| Composants UI (5 fichiers) | Oui |
| Client API | Oui |
| Hook thème | Oui |
| Pages (15 pages) | Non |
| Auth context | Non |
| WebSocket hook | Non |
| Cohort components | Non |
| Quality components | Non |
| GlobalSearch | Non |
| Routing | Non |

---

## Conformité OMOP CDM

### Tables supportées

| Table CDM | Qualité | Cohort | Mapping | Concept | Pathways |
|-----------|---------|--------|---------|---------|----------|
| person | OK | OK | — | — | — |
| observation_period | OK | OK | — | — | OK |
| visit_occurrence | OK | OK | OK | OK | OK |
| condition_occurrence | OK | OK | OK | OK | OK |
| drug_exposure | OK | OK | OK | OK | OK |
| measurement | OK | OK | OK | OK | OK |
| procedure_occurrence | OK | OK | OK | OK | OK |
| observation | OK | OK | OK | OK | — |
| device_exposure | OK | OK | OK | OK | OK |
| death | OK | OK | OK | OK | — |
| concept | — | OK | OK | OK | — |
| concept_ancestor | — | OK | — | OK | OK |
| concept_relationship | — | — | OK | OK | — |
| vocabulary | — | — | — | OK | — |
| source_to_concept_map | — | — | OK (write) | — | — |

### Tables non supportées (CDM v5.4)

- `note` / `note_nlp` — Données textuelles
- `specimen` — Échantillons biologiques
- `cost` — Données de coûts
- `payer_plan_period` — Couverture assurantielle
- `episode` / `episode_event` — Épisodes de soins (v5.4)
- `survey_conduct` — Questionnaires
- `fact_relationship` — Relations inter-tables

**Impact** : Pour un usage hospitalier français, les tables `note` et `cost` seraient nécessaires. Les `episode` tables (CDM v5.4) ne sont pas encore supportées.

---

## Matrice de Remédiation

| ID | Effort | Impact | Priorité |
|----|--------|--------|----------|
| F1 | Moyen | Critique | Semaine 1 |
| F2 | Élevé | Critique | Sprint dédié |
| F3 | Faible | Haute | Semaine 1 |
| F4 | Moyen | Haute | Semaine 2 |
| F5 | Moyen | Haute | Semaine 3 |
| F6 | Faible | Haute | Semaine 1 |
| F7 | Moyen | Haute | Semaine 2 |
| F8 | Faible | Haute | Semaine 1 |
| F9 | Faible | Haute | Semaine 2 |
| F10-F19 | Variable | Moyenne | Semaine 3-4 |
| F20-F26 | Variable | Basse | Backlog |
