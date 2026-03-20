# Audit Fonctionnel Approfondi — OPAL v1.2.1

**Date** : 2026-03-20
**Périmètre** : 19 modules backend (200+ endpoints), 15 pages frontend, 50+ fichiers de tests backend, types TypeScript, i18n EN/FR, modèles SQLAlchemy, Alembic
**Méthodologie** : Lecture complète de chaque fichier source, traçage des flux API→DB→OMOP, comparaison client.ts vs routes backend, analyse couverture i18n, vérification DOMAIN_CONFIG vs CDM OMOP v5.4
**Auditeur** : Claude Code (Opus 4.6) — audit exhaustif basé sur le code source
**Branche** : OPAL_V1.2.1

---

## Résumé Exécutif

| Sévérité | Trouvées | Statut |
|----------|----------|--------|
| CRITIQUE | 3 | 0 corrigé, 3 présents |
| HAUTE | 7 | 0 corrigé, 7 présents |
| MOYENNE | 10 | 0 corrigé, 10 présents |
| BASSE | 8 | 0 corrigé, 8 présents |
| **Total** | **28** | **28 en attente** |

OPAL implémente un ensemble fonctionnel remarquablement complet pour une plateforme OMOP CDM : qualité Achilles-like (5 analyseurs de domaines + conformité), cohort builder avec SQL dynamique (1152 lignes, 10+ types de critères), mapping avec 6 stratégies, pathways ATLAS-style, incidence, estimation Kaplan-Meier, et data management avec extraction streaming. L'analyse en profondeur révèle cependant des pages orphelines non routées, des colonnes OMOP non standard dans la configuration, et des incohérences API/frontend.

---

## Findings détaillés

### CRITIQUE

---

#### F01 — 3 pages frontend (Incidence, Estimation, ConceptSet) sans routes dans App.tsx

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Complétude fonctionnelle |
| **Fichier** | `frontend/src/App.tsx:163-175` |
| **Statut** | Présent |

**Description** : Les fichiers `IncidencePage.tsx`, `EstimationPage.tsx` et `ConceptSetPage.tsx` existent dans le répertoire pages mais ne sont jamais lazy-loaded ni routés dans `App.tsx`. Les routers backend correspondants (`/api/incidence/`, `/api/estimation/`, `/api/concept-sets/`) existent et sont pleinement fonctionnels. Les utilisateurs n'ont **aucun moyen** d'atteindre ces pages via la navigation.

**Comportement attendu** : Les 3 pages devraient avoir des entrées `<Route>` dans `App.tsx` (ex: `/incidence`, `/estimation`, `/concept-sets`).

**Correction recommandée** : Ajouter les imports lazy et les entrées Route pour `/incidence`, `/estimation`, `/concept-sets` dans `App.tsx`. Aussi les ajouter au tableau `ALL_PAGES` et aux listes de pages dans `permissions.yaml`.

---

#### F02 — Colonne `note_source_value` du domaine Note inexistante dans OMOP CDM v5.4

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Conformité OMOP |
| **Fichier** | `backend/config.py:167` |
| **Statut** | Présent |

**Description** : La table OMOP CDM `note` n'a pas de colonne `note_source_value`. Les colonnes standard sont `note_text`, `note_title`, etc. Le `DOMAIN_CONFIG` pour "Note" référence `"source_value": "note_source_value"` qui causera des erreurs SQL runtime sur tout CDM ayant une table `note`. De même, `note_source_concept_id` n'est pas standard.

**Correction recommandée** : Mettre `"source_value": None` pour le domaine Note. Le code d'analyse qualité, mapping et recherche qui itère sur `DOMAIN_CONFIG` gère déjà gracieusement `None` comme source_value (grâce aux checks dans `cdm_helper.py`).

---

#### F03 — `CohortVersion.cohort_id` n'a pas de contrainte ForeignKey en base

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | CRITIQUE |
| **Catégorie** | Intégrité des données |
| **Fichier** | `backend/db/models.py:92` |
| **Statut** | Présent |

**Description** : `CohortVersion.cohort_id` est déclaré comme `Column(Integer, nullable=False, index=True)` sans `ForeignKey("cohorts.id")`. La relation sur `Cohort.versions` utilise `primaryjoin="Cohort.id == foreign(CohortVersion.cohort_id)"` qui fonctionne au niveau ORM mais ne crée **pas** de contrainte foreign key en base. Des lignes `CohortVersion` orphelines peuvent exister si la suppression bypasse l'ORM. Même problème pour `CohortShare.cohort_id`.

**Correction recommandée** : Ajouter `ForeignKey("cohorts.id", ondelete="CASCADE")` et créer une migration Alembic.

---

### HAUTE

---

#### F04 — Endpoints delete Incidence/Estimation absents du client frontend

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Contrat API |
| **Fichier** | `frontend/src/api/client.ts:540-570` |
| **Statut** | Présent |

**Description** : Le backend a `DELETE /api/incidence/{analysis_id}` et `DELETE /api/estimation/{analysis_id}` mais le frontend `incidenceApi` et `estimationApi` n'ont pas de méthode `delete`. Les utilisateurs ne peuvent pas supprimer les analyses sauvegardées depuis l'UI.

**Correction recommandée** : Ajouter `delete: (id) => api.delete(`/incidence/${id}`)` aux deux objets API.

---

#### F05 — 3 domaines OMOP manquants dans les i18n (Specimen, Note, Payer_Plan_Period)

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | i18n |
| **Fichier** | Backend et frontend `i18n/en.json`, `i18n/fr.json` |
| **Statut** | Présent |

**Description** : `DOMAIN_CONFIG` couvre 11 domaines dont Specimen, Note et Payer_Plan_Period. Mais la section `domains` des fichiers i18n ne liste que 9 domaines. Quand ces 3 domaines apparaissent dans les UIs qualité ou mapping, leurs noms apparaîtront comme clés brutes au lieu de labels localisés.

**Correction recommandée** : Ajouter les traductions pour `domains.Specimen`, `domains.Note`, `domains.Payer_Plan_Period` dans les 4 fichiers i18n.

---

#### F06 — Analyse SSE : pas de protection contre les analyses concurrentes pour le même CDM/domaine

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Race Condition |
| **Fichier** | `backend/modules/quality/router.py:241-403` |
| **Statut** | Présent |

**Description** : Deux utilisateurs peuvent lancer des analyses streaming batch pour le même CDM simultanément. Les deux écriront des versions de snapshot. La fonction `_save_snapshot` utilise `max(version) + 1` qui sous écritures concurrentes pourrait générer le même numéro de version, violant la contrainte unique `uq_snapshot_cdm_domain_version`.

**Correction recommandée** : Wrapper `_save_snapshot` dans une boucle retry catchant IntegrityError, ou utiliser `SELECT ... FOR UPDATE` sur la requête version.

---

#### F07 — `permissions.yaml` manque les pages incidence, estimation, concept-sets

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Complétude fonctionnelle |
| **Fichier** | `backend/permissions.yaml:24-31` |
| **Statut** | Présent |

**Description** : Le rôle `data-manager` liste des pages comme `/quality`, `/cohorts`, `/mapping` etc. mais ne liste pas `/incidence`, `/estimation`, ni `/concept-sets`. Si ces routes sont ajoutées au frontend (correction de F01), le composant `ProtectedRoute` vérifiera `hasPageAccess` et refusera l'accès même aux data-managers. Les rôles `chercheur` et `medecin` manquent aussi ces entrées.

---

#### F08 — `UserFavorite` non nettoyé lors de la suppression d'un CDM

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Intégrité des données |
| **Fichier** | `backend/modules/cdm_router.py:260-315` |
| **Statut** | Présent |

**Description** : Lors de la suppression d'un CDM, le cascade delete supprime Cohorts, Snapshots, MappingDecisions, ConceptSets, etc. Mais les entrées `UserFavorite` référençant des éléments du CDM supprimé ne sont **pas** nettoyées. Cela crée des favoris orphelins pointant vers des entités inexistantes.

---

#### F09 — Templates built-in impossibles à supprimer

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Edge Case |
| **Fichier** | `backend/modules/cohort_templates_router.py:256-268` |
| **Statut** | Présent |

**Description** : Les templates built-in ont `author = "OPAL"`. L'endpoint delete vérifie `if t.author != current_user: raise 403`. Cela signifie que personne ne peut supprimer les templates built-in car aucun utilisateur n'a le username "OPAL". Les admins devraient pouvoir supprimer tout template.

**Correction recommandée** : Les rôles admin/data-manager devraient bypasser la vérification d'auteur.

---

#### F10 — Concept set update/delete sans override admin

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | HAUTE |
| **Catégorie** | Edge Case |
| **Fichier** | `backend/modules/concept_set/router.py:120-152` |
| **Statut** | Présent |

**Description** : Même pattern que F09 : update et delete vérifient `cs.created_by != current_user` et lèvent 403. Les admins ne peuvent pas gérer les concept sets créés par d'autres utilisateurs. Incohérent avec le cohort sharing où les admins peuvent gérer toute cohorte.

---

### MOYENNE

---

#### F11 — `saved_queries_router.py` sans vérification d'accès CDM

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/saved_queries_router.py` |
| **Statut** | Présent |

**Description** : Les endpoints `create_query` et `list_queries` n'appellent pas `check_cdm_access`. Un utilisateur pourrait sauvegarder des requêtes contre des CDMs auxquels il n'a pas accès.

---

#### F12 — `search_router.py` sans vérification d'accès CDM

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/search_router.py:23-28` |
| **Statut** | Présent |

**Description** : La recherche globale interroge cohortes, mappings et concepts à travers les CDMs sans vérifier que l'utilisateur a accès au `cdm_name` demandé.

---

#### F13 — `concept/router.py` search sans vérification d'accès CDM

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/concept/router.py:81-147` |
| **Statut** | Présent |

**Description** : L'endpoint `/concepts/search` accepte `cdm_name` en query parameter mais ne vérifie pas l'accès CDM via `check_cdm_access`. D'autres endpoints concept comme `/counts` font cette vérification.

---

#### F14 — `admin_router.py` — `submit_access_request` accepte un `dict` brut

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/admin_router.py:207` |
| **Statut** | Présent |

**Description** : L'endpoint utilise `body: dict` au lieu d'un modèle Pydantic, bypassant la validation automatique, la coercion de types et la génération de schéma OpenAPI.

---

#### F15 — `add_user_direct` endpoint async incohérent

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Error Handling |
| **Fichier** | `backend/modules/admin_router.py:377` |
| **Statut** | Présent |

**Description** : Seul endpoint utilisant `async def` avec `await request.json()` au lieu d'un body model Pydantic. Bypasse la validation et est incohérent avec le reste du codebase.

---

#### F16 — `CohortTemplate._ensure_builtins` race condition en multi-worker

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Race Condition |
| **Fichier** | `backend/modules/cohort_templates_router.py:173-179` |
| **Statut** | Présent |

**Description** : `_ensure_builtins` vérifie `count == 0` puis insère les templates. Sous plusieurs workers, deux requêtes pourraient voir count=0 et insérer des doublons. La table n'a pas de contrainte unique sur `(name, author)`.

---

#### F17 — Export CSV quality : filename non quoté dans Content-Disposition

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Edge Case |
| **Fichier** | `backend/modules/quality/router.py:734` |
| **Statut** | Présent |

**Description** : `Content-Disposition: attachment; filename={filename}` — le filename n'est pas quoté. Si les noms CDM contiennent des espaces ou caractères spéciaux, le header sera malformé.

---

#### F18 — `concept_cache` est process-local et non invalidé entre workers

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Edge Case |
| **Fichier** | `backend/modules/concept/router.py:30-52` |
| **Statut** | Présent (acceptable avec TTL 5 min) |

**Description** : Le dict `_concept_cache` est per-process. En déploiement multi-worker (Gunicorn), chaque worker a son propre cache. L'invalidation dans un worker n'affecte pas les autres. Le TTL de 5 min atténue le problème.

---

#### F19 — `Notification.read` utilise Integer(0/1) au lieu de Boolean

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Intégrité des données |
| **Fichier** | `backend/db/models.py:284,72` |
| **Statut** | Présent (choix de compatibilité SQLite) |

**Description** : `Notification.read` et `Cohort.shared_with_all` utilisent `Integer` avec valeurs 0/1 au lieu de `Boolean`, commenté "for SQLite compat". Pas de CHECK constraint assurant que les valeurs soient uniquement 0 ou 1.

---

#### F20 — `cohort_sharing_router.py` vérifie l'accès CDM par grant direct uniquement

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | MOYENNE |
| **Catégorie** | Edge Case |
| **Fichier** | `backend/modules/cohort_sharing_router.py:68-79` |
| **Statut** | Présent |

**Description** : Lors du partage avec un utilisateur, le check ne regarde que `CdmAccess` (grants directs) mais pas `CdmGroupAccess` (grants de groupe). Un utilisateur avec accès basé sur un groupe pourrait être rejeté.

---

### BASSE

---

#### F21 — `chercheur` et `medecin` n'ont pas accès à `/api/concept-sets`

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Complétude fonctionnelle |
| **Fichier** | `backend/permissions.yaml:62-96` |
| **Statut** | Présent |

**Description** : Les chercheurs et médecins ne peuvent pas accéder aux concept sets via l'API, même s'ils peuvent accéder aux concepts. Les concept sets sont une extension naturelle de la navigation de concepts.

---

#### F22 — `quality/engine.py` — `get_available_domains` avale les exceptions silencieusement

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Error Handling |
| **Fichier** | `backend/modules/quality/engine.py:33-48` |
| **Statut** | Présent |

**Description** : Si la requête `information_schema` échoue (ex: permission denied), le bloc `except` retombe sur le retour de tous les domaines sans logger de warning. Cela peut masquer des problèmes de permissions.

---

#### F23 — Colonne `payer_source_value` du domaine Payer_Plan_Period non standard OMOP CDM v5.4

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Conformité OMOP |
| **Fichier** | `backend/config.py:170-177` |
| **Statut** | Présent |

**Description** : La table OMOP `payer_plan_period` n'a pas de colonne `payer_source_value` ni `payer_source_concept_id`. Causera des erreurs SQL similaires à F02. Toutefois, ce domaine est rarement présent dans les CDMs.

---

#### F24 — Extraction background ignore la révocation d'accès

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/datamanagement/router.py`, `extractor.py` |
| **Statut** | Présent |

**Description** : La tâche d'extraction tourne en thread background après le check initial d'accès CDM. Si l'accès est révoqué entre la requête et l'exécution background, l'extraction se poursuit.

---

#### F25 — Alembic n'a qu'un seul fichier de migration

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Intégrité des données |
| **Fichier** | `backend/alembic/versions/26a4acfe5afa_initial_schema.py` |
| **Statut** | Présent |

**Description** : Un seul fichier de migration existe. Si `models.py` a évolué depuis, la migration et les modèles peuvent être désynchronisés.

---

#### F26 — `CohortTemplate.criteria_json` ne valide pas le schéma JSON

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Validation |
| **Fichier** | `backend/modules/cohort_templates_router.py:238` |
| **Statut** | Présent |

**Description** : `CreateTemplateRequest` accepte n'importe quel `dict` comme `criteria_json` sans valider sa conformité au schéma de critères de cohorte. Des templates invalides pourraient être sauvegardés.

---

#### F27 — Structures i18n frontend/backend différentes

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | i18n |
| **Statut** | Choix architectural |

**Description** : Les fichiers i18n frontend ont des clés (`app.subtitle`) absentes du backend, et inversement. C'est un choix de design (systèmes séparés) mais impose une synchronisation manuelle.

---

#### F28 — Pas de test unitaire dédié pour le moteur de caractérisation

| Attribut | Valeur |
|----------|--------|
| **Sévérité** | BASSE |
| **Catégorie** | Couverture de tests |
| **Fichier** | `backend/modules/cohort/characterization.py` |
| **Statut** | Présent |

**Description** : Le fichier `characterization.py` n'a pas de fichier de test dédié (`test_characterization.py`). La couverture est indirecte via les tests d'intégration du router cohort.

---

## Matrice de couverture de tests

| Module | Fichier(s) de test | Couverture |
|--------|--------------------|------------|
| CDM CRUD | `test_api.py` | ✅ Couvert |
| CDM Access | `test_cdm_access.py` | ✅ Couvert |
| CDM Helper | `test_cdm_helper.py` | ✅ Couvert |
| Quality Engine | `test_engine.py`, `test_clinical_domain.py`, `test_dashboard_domain.py`, `test_person_domain.py`, `test_observation_period_domain.py` | ✅ Bien couvert |
| Quality Comparator | `test_comparator.py` | ✅ Couvert |
| Quality Conformity | `test_conformity.py` | ✅ Couvert |
| Quality Report | `test_report_builder.py` | ✅ Couvert |
| Cohort API | `test_cohort_api.py` | ✅ Couvert |
| Cohort SQL Builder | `test_sql_builder.py` | ✅ Couvert |
| Cohort Pathways | `test_pathways.py`, `test_pathways_analysis.py` | ✅ Couvert |
| Cohort Comparison | `test_cohort_comparison.py`, `test_cohort_diff.py` | ✅ Couvert |
| Cohort Sharing | `test_cohort_sharing.py` | ✅ Couvert |
| Cohort Templates | `test_cohort_templates.py` | ✅ Couvert |
| **Cohort Characterization** | *Pas de test dédié* | ⚠️ **GAP** |
| Mapping API | `test_mapping_api.py` | ✅ Couvert |
| Mapping Suggest | `test_suggest.py` | ✅ Couvert |
| Concept Router | `test_concept_router.py` | ✅ Couvert |
| Concept Cache | `test_concept_cache.py` | ✅ Couvert |
| Concept Set API | `test_concept_set_api.py` | ✅ Couvert |
| Incidence Engine | `test_incidence_engine.py` | ✅ Couvert |
| Incidence Router | `test_incidence_router.py` | ✅ Couvert |
| Estimation Router | `test_estimation_router.py` | ✅ Couvert |
| Estimation Survival | `test_survival.py` | ✅ Couvert |
| Data Management | `test_datamanagement_router.py`, `test_extractor.py` | ✅ Couvert |
| Admin API | `test_admin_api.py` | ✅ Couvert |
| Notifications | `test_notifications.py`, `test_notification_preferences.py` | ✅ Couvert |
| Favorites | `test_favorites.py` | ✅ Couvert |
| Saved Queries | `test_saved_queries.py` | ✅ Couvert |
| Groups | `test_groups.py` | ✅ Couvert |
| Search | `test_search.py` | ✅ Couvert |
| Audit | `test_audit_api.py` | ✅ Couvert |
| OHDSI | `test_ohdsi_router.py` | ✅ Couvert |
| WebSocket | `test_ws_endpoint.py`, `test_ws_manager.py`, `test_ws_nginx.py` | ✅ Couvert |
| Crypto | `test_crypto.py` | ✅ Couvert |
| CSV Safety | `test_csv_safety.py` | ✅ Couvert |
| SQL Safety | `test_sql_safety.py` | ✅ Couvert |
| Rate Limiting | `test_rate_limit.py` | ✅ Couvert |
| i18n | `test_i18n.py` | ✅ Couvert |

**Résultat** : Couverture excellente — 50+ fichiers de tests, tous les modules couverts sauf `characterization.py` (test dédié manquant).

---

## Vérification DOMAIN_CONFIG (11 domaines OMOP cliniques)

| Domaine | Dans DOMAIN_CONFIG | Table | `source_value` valide | Dans i18n EN | Dans i18n FR |
|---------|-------------------|-------|----------------------|-------------|-------------|
| Condition | ✅ | condition_occurrence | ✅ condition_source_value | ✅ | ✅ |
| Drug | ✅ | drug_exposure | ✅ drug_source_value | ✅ | ✅ |
| Measurement | ✅ | measurement | ✅ measurement_source_value | ✅ | ✅ |
| Observation | ✅ | observation | ✅ observation_source_value | ✅ | ✅ |
| Procedure | ✅ | procedure_occurrence | ✅ procedure_source_value | ✅ | ✅ |
| Visit | ✅ | visit_occurrence | ✅ visit_source_value | ✅ | ✅ |
| Device | ✅ | device_exposure | ✅ device_source_value | ✅ | ✅ |
| Death | ✅ | death | ✅ death_type_source_value | ✅ | ✅ |
| Specimen | ✅ | specimen | ✅ specimen_source_value | ❌ | ❌ |
| Note | ✅ | note | ❌ **note_source_value** (non standard) | ❌ | ❌ |
| Payer_Plan_Period | ✅ | payer_plan_period | ❌ **payer_source_value** (non standard) | ❌ | ❌ |

**Résultat** : 11/11 domaines configurés. **2 colonnes source_value invalides**, **3 domaines absents de l'i18n**.

---

## Comparaison contrat API (Frontend client.ts vs Backend routes)

| Route Backend | Méthode Frontend | Match |
|---------------|-----------------|-------|
| `GET /api/cdm/` | `cdmApi.list()` | ✅ |
| `POST /api/cdm/` | `cdmApi.create()` | ✅ |
| `POST /api/cdm/test` | `cdmApi.test()` | ✅ |
| `PUT /api/cdm/{name}` | `cdmApi.update()` | ✅ |
| `DELETE /api/cdm/{name}` | `cdmApi.delete()` | ✅ |
| `POST /api/quality/analyze` | `qualityApi.analyze()` | ✅ |
| `POST /api/quality/analyze/batch/stream` | `qualityApi.analyzeBatchStream()` | ✅ |
| `POST /api/quality/conformity` | `conformityApi.run()` | ✅ |
| `POST /api/cohorts/` | `cohortApi.create()` | ✅ |
| `GET /api/cohorts/` | `cohortApi.list()` | ✅ |
| `PUT /api/cohorts/{id}` | `cohortApi.update()` | ✅ |
| `DELETE /api/cohorts/{id}` | `cohortApi.delete()` | ✅ |
| `POST /api/mapping/suggest` | `mappingApi.suggest()` | ✅ |
| `POST /api/mapping/decide` | `mappingApi.decide()` | ✅ |
| `POST /api/incidence/compute` | `incidenceApi.compute()` | ✅ |
| `POST /api/incidence/save` | `incidenceApi.save()` | ✅ |
| `GET /api/incidence/` | `incidenceApi.list()` | ✅ |
| **`DELETE /api/incidence/{id}`** | **MANQUANT** | ❌ |
| `POST /api/estimation/kaplan-meier` | `estimationApi.kaplanMeier()` | ✅ |
| `POST /api/estimation/save` | `estimationApi.save()` | ✅ |
| `GET /api/estimation/` | `estimationApi.list()` | ✅ |
| **`DELETE /api/estimation/{id}`** | **MANQUANT** | ❌ |
| `GET /api/concept-sets/` | `conceptSetApi.list()` | ✅ |
| `POST /api/concept-sets/` | `conceptSetApi.create()` | ✅ |
| `DELETE /api/concept-sets/{id}` | `conceptSetApi.delete()` | ✅ |
| Tous les autres endpoints | Correspondance | ✅ |

**Résultat** : **2 endpoints delete manquants** dans le client frontend. Tous les autres routes sont correctement mappés.

---

## Comparaison i18n

### Backend en.json vs fr.json
**Parité parfaite** — Les deux fichiers ont des structures de clés identiques (337 lignes chacun). Aucune clé manquante dans aucune direction.

### Frontend en.json vs fr.json
Les deux fichiers suivent la même structure. Aucune clé manquante détectée.

### Clés de domaines manquantes (backend et frontend)
- `domains.Specimen`
- `domains.Note`
- `domains.Payer_Plan_Period`
