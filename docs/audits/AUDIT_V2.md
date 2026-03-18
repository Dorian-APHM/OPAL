# AUDIT V2 — Post-remediation complet

> **Date** : 2026-03-15
> **Branche** : `claude/count-code-lines-03FQD`
> **Scope** : Securite, Performance, Architecture, Fonctionnalites, Tests, DevOps
> **Base** : Codebase apres application de tous les P0/P1 du PLAN_AMELIORATION.md

Chaque item est classe :
- **P0** = Critique (bloquant production)
- **P1** = Haute (a traiter avant release)
- **P2** = Moyenne (sprint suivant)
- **P3** = Basse (backlog)

Les items marques **(V2)** existaient deja dans le PLAN_AMELIORATION.md initial mais n'ont pas ete corriges ou necessitent un second passage.

---

## TABLE DES MATIERES

1. [SECURITE](#1-securite)
2. [PERFORMANCE & OPTIMISATION](#2-performance--optimisation)
3. [ARCHITECTURE & QUALITE DE CODE](#3-architecture--qualite-de-code)
4. [FONCTIONNALITES & LOGIQUE METIER](#4-fonctionnalites--logique-metier)
5. [TESTS & COUVERTURE](#5-tests--couverture)
6. [DEVOPS & INFRASTRUCTURE](#6-devops--infrastructure)
7. [FRONTEND](#7-frontend)

---

## 1. SECURITE

### 1.1 [P0] Path Traversal dans `ohdsi/router.py` — lecture de fichiers arbitraires

**Fichiers** : `backend/modules/ohdsi/router.py:284-295`

```python
@router.get("/files/{path:path}")
def list_or_download_files(path: str = ""):
    output_dir = Path(OHDSI_OUTPUT_DIR)
    target = output_dir / path if path else output_dir
    if target.is_file():
        return FileResponse(str(target), filename=target.name)
```

**Probleme** : Le parametre `path` n'est pas valide contre le directory traversal. `GET /api/ohdsi/files/../../etc/passwd` permet de lire n'importe quel fichier du serveur. `Path("/data/ohdsi") / "../../etc/passwd"` resout vers `/etc/passwd`.

**Solution** :
```python
target = (output_dir / path).resolve()
if not str(target).startswith(str(output_dir.resolve())):
    raise HTTPException(status_code=403, detail="Access denied")
```

---

### 1.2a [P0] SQL injection restante dans `suggest.py` via f-string sur schema

**Fichiers** :
- `backend/modules/mapping/suggest.py:130` — `f"SELECT ... FROM {schema}.concept c ..."`
- `backend/modules/mapping/suggest.py:167-184` — idem strategy 2
- `backend/modules/mapping/suggest.py:507-519` — strategy 3
- `backend/modules/mapping/suggest.py:595-606` — strategy 4 fuzzy
- `backend/modules/mapping/suggest.py:625-648` — strategy 4 fallback
- `backend/modules/mapping/suggest.py:703-714` — strategy 4b keyword
- `backend/modules/mapping/suggest.py:786-801` — strategy 5 contextual

**Probleme** : `safe_identifier()` est bien appele en ligne 41, mais le schema valide est ensuite interpole via f-string (`f"FROM {schema}.concept"`). Bien que `safe_identifier` empeche les caracteres speciaux, l'injection via un identifiant syntaxiquement valide mais semantiquement dangereux (ex: un schema existant contenant des vues malveillantes) n'est pas bloquee. Le pattern correct est `psycopg2.sql.Identifier` comme dans `concept/router.py`.

**Solution** : Migrer toutes les requetes de `suggest.py` vers `psycopg2.sql.SQL` + `sql.Identifier`, identique au refactoring fait dans `concept/router.py`.

---

### 1.2 [P0] SQL injection dans `search_router.py` — f-string UNION complet

**Fichiers** :
- `backend/modules/search_router.py:79-98` — Requete concept directe avec `f"FROM {schema}.concept"`
- `backend/modules/search_router.py:114-142` — UNION ALL sur toutes les tables OMOP via f-string

**Probleme** : Le schema et les noms de colonnes/tables sont interpoles via f-string sans `safe_identifier()` ni `psycopg2.sql.Identifier`. Le schema provient de la config utilisateur.

**Solution** : Appliquer `safe_identifier()` sur schema + migrer vers `psycopg2.sql.SQL`/`sql.Identifier`.

---

### 1.3 [P1] SQL injection dans `clinical.py` — f-string sur identifiants pre-valides

**Fichiers** :
- `backend/modules/quality/domains/clinical.py:22-28` — `_get_global_stats()` : `f"SELECT COUNT(*) FROM {full_table}"`
- `backend/modules/quality/domains/clinical.py:39-46` — `_get_monthly_counts()`
- `backend/modules/quality/domains/clinical.py:56-63` — `_get_records_per_person()`
- `backend/modules/quality/domains/clinical.py:90-119` — `_get_top_concepts()`
- `backend/modules/quality/domains/clinical.py:138-178` — `_get_mapping_stats()`

**Probleme** : Les identifiants passent par `safe_identifier()` (ligne 214-221) ce qui empeche l'injection classique, mais l'interpolation reste via f-string. Defense en profondeur insuffisante.

**Solution** : Migrer vers `psycopg2.sql.SQL` + `sql.Identifier` pour la couche de defense complete. Priorite basse car `safe_identifier` protege deja, mais non conforme au pattern securise etabli dans `concept/router.py`.

---

### 1.4 [P1] SQL injection dans `conformity.py` — f-string sur schema valide

**Fichiers** :
- `backend/modules/quality/conformity.py:74-80` — `f"FROM {schema}.person"`
- `backend/modules/quality/conformity.py:88-93` — join person/observation_period
- `backend/modules/quality/conformity.py:131-139` — observation_period
- `backend/modules/quality/conformity.py:200-218` — boucle sur tables cliniques
- `backend/modules/quality/conformity.py:279-282` — visit_occurrence

**Probleme** : Meme pattern que 1.3 — `_safe()` valide mais f-string interpole.

**Solution** : Migrer vers `psycopg2.sql`.

---

### 1.5 [P1] IDOR — Notifications lisibles/modifiables par n'importe quel utilisateur

**Fichiers** :
- `backend/modules/notifications_router.py:132` — `mark_as_read()` n'a pas de filtre utilisateur
- `backend/modules/notifications_router.py:179-192` — `create_notification()` pas de controle d'acces

**Probleme** : `mark_as_read(notification_id)` ne verifie pas que la notification appartient a l'utilisateur courant. N'importe quel utilisateur authentifie peut marquer la notification d'un autre comme lue. `create_notification()` est accessible sans restriction de role — n'importe qui peut creer des notifications pour un autre utilisateur.

**Solution** :
- `mark_as_read` : ajouter filtre `Notification.username == current_user`
- `create_notification` : restreindre aux roles admin/system ou supprimer l'endpoint public

---

### 1.6 [P1] IDOR — Saved queries modifiables/supprimables par n'importe qui

**Fichiers** :
- `backend/modules/saved_queries_router.py:76` — `update_query()` pas de filtre owner
- `backend/modules/saved_queries_router.py:91` — `delete_query()` pas de filtre owner

**Probleme** : Un utilisateur peut modifier ou supprimer les requetes sauvegardees par un autre utilisateur. Pas de verification `SavedQuery.created_by == current_user`.

**Solution** : Ajouter un controle d'ownership sur update et delete.

---

### 1.7 [P1] IDOR — Cohort delete accessible sans verification de propriete

**Fichiers** :
- `backend/modules/cohort/router.py` — endpoint DELETE `/{cohort_id}`

**Probleme** : Le DELETE ne verifie pas si l'utilisateur est proprietaire ou admin. Seul le PUT a ete corrige avec `_can_access_cohort`.

**Solution** : Appliquer la meme logique `_can_access_cohort` ou `_require_owner_or_admin` sur le DELETE.

---

### 1.8 [P1] IDOR — Concept sets modifiables/supprimables par n'importe qui

**Fichiers** :
- `backend/modules/concept_set/router.py:115-139`

**Probleme** : `update_concept_set()` et `delete_concept_set()` n'ont pas de verification de propriete. N'importe quel utilisateur peut modifier/supprimer les concept sets d'un autre.

**Solution** : Ajouter verification `cs.created_by == current_user` ou role admin.

---

### 1.9 [P1] IDOR — Cohort templates supprimables par n'importe qui

**Fichiers** : `backend/modules/cohort_templates_router.py:256-264`

**Probleme** : `delete_template()` ne verifie ni la propriete ni le role. N'importe qui peut supprimer un template partage.

**Solution** : Ajouter check ownership ou `require_roles("admin", "data-manager")`.

---

### 1.10 [P1] Missing auth sur annulation d'analyse

**Fichiers** : `backend/modules/quality/router.py:359-368`

**Probleme** : `cancel_analysis(analysis_id)` ne verifie pas que l'utilisateur est celui qui a lance l'analyse. N'importe qui peut annuler l'analyse d'un autre en connaissant/devinant l'UUID.

**Solution** : Stocker le username dans `_active_analyses[id]` et verifier a l'annulation.

---

### 1.11 [P1] Conteneurs OHDSI en `network_mode="host"`

**Fichiers** : `backend/modules/ohdsi/router.py:126`

**Probleme** : Les conteneurs Docker OHDSI partagent le namespace reseau de l'hote, leur permettant d'acceder a tous les services internes (base app, Keycloak admin, etc.).

**Solution** : Utiliser un reseau Docker dedie (`network_mode="opal_internal"`).

---

### 1.12 [P1] (V2) Rate limiting insuffisant sur endpoints couteux

**Fichiers** : `backend/main.py`, `backend/modules/quality/router.py`, `backend/modules/cohort/router.py`

**Probleme** : Le rate limiting n'est applique que sur 2 endpoints (`/api/access-requests`, `/api/auth/sse-ticket`). Les endpoints de calcul intensif ne sont pas limites :
- `POST /api/quality/analyze` — lance une analyse complete
- `POST /api/cohorts/characterize` — characterization lourde
- `POST /api/cohorts/pathways` — analyse pathways
- `POST /api/incidence/run` — calcul incidence
- `POST /api/estimation/run` — survival analysis
- `POST /api/mapping/suggest-batch-async` — batch suggestion

**Solution** : Ajouter `@limiter.limit("3/minute")` sur ces endpoints.

---

### 1.9 [P1] SSE tickets non limites en memoire

**Fichiers** : `backend/auth/keycloak.py:49-66`

**Probleme** : `_sse_tickets` est un dict en memoire sans limite de taille. Un attaquant peut generer des milliers de tickets (rate limit 10/min, mais accumulation sur des heures). Le nettoyage se fait uniquement a la creation de nouveaux tickets.

**Solution** : Ajouter un cap (`MAX_SSE_TICKETS = 1000`), rejeter les nouveaux tickets au-dela. Ajouter un nettoyage periodique dans le evictor thread.

---

### 1.10 [P2] SSRF — resolution DNS avant connexion mais pas de re-verification (V2)

**Fichiers** : `backend/modules/cdm_router.py:54-66`

**Probleme** : Le hostname est valide a la creation du CDM, mais la resolution DNS peut changer (DNS rebinding). Lors des connexions suivantes, le hostname resolve peut pointer vers une adresse interne.

**Solution** : Valider l'IP resolue aussi dans `get_omop_connection()`, ou passer l'IP directement au pool apres resolution.

---

### 1.11 [P2] `_pathways_tasks` et `_active_suggestions` sans limite de taille

**Fichiers** :
- `backend/modules/cohort/router.py` — `_pathways_tasks: dict`
- `backend/modules/cohort/router.py` — `_characterization_tasks: dict`
- `backend/modules/mapping/router.py:31` — `_active_suggestions: dict`

**Probleme** : Ces dicts en memoire grandissent sans limite. Les taches terminees ne sont jamais supprimees. Fuite memoire lente.

**Solution** : Ajouter un TTL (ex: 1h apres completion) et un cap (ex: 100 taches max). Supprimer automatiquement les plus anciennes.

---

### 1.12 [P2] Absence de validation `KEYCLOAK_ISSUER_URL` dans token validation

**Fichiers** : `backend/auth/keycloak.py` — `_validate_token()`

**Probleme** : Le token JWT est valide avec le JWKS endpoint mais la claim `iss` (issuer) du token n'est pas explicitement comparee a `KEYCLOAK_ISSUER_URL`. Un token emis par un autre realm Keycloak pourrait etre accepte si les cles JWKS sont identiques.

**Solution** : Ajouter `issuer=KEYCLOAK_ISSUER_URL + "/realms/" + KEYCLOAK_REALM` dans l'appel `jwt.decode()`.

---

### 1.13 [P2] Export CSV sans sanitization — injection de formules

**Fichiers** :
- `backend/modules/concept/router.py:477-494` — export source value search CSV
- `backend/modules/mapping/router.py` — tous les exports CSV
- `backend/modules/quality/router.py` — export quality CSV
- `backend/main.py` — export audit CSV

**Probleme** : Les valeurs ecrites dans les CSV (source_value, concept_name, etc.) ne sont pas sanitisees. Si une valeur commence par `=`, `+`, `-`, `@`, un tableur comme Excel executera la formule (CSV injection / formula injection).

**Solution** : Prefixer les valeurs dangereuses avec un apostrophe (`'`) ou un tab dans les exports CSV :
```python
def _csv_safe(val):
    s = str(val) if val is not None else ""
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + s
    return s
```

---

### 1.18 [P2] `page_size` non borne sur endpoint audit logs

**Fichiers** : `backend/main.py:268`

**Probleme** : `page_size: int = 50` sans limite superieure. `page_size=999999999` force le serveur a charger et serialiser une reponse JSON enorme.

**Solution** : `page_size: int = Query(default=50, ge=1, le=500)`.

---

### 1.19 [P2] Content-Disposition header injection

**Fichiers** : `backend/modules/quality/router.py:590,776,813`

**Probleme** : Les noms de CDM sont interpoles dans le header `Content-Disposition` sans sanitization. Un CDM name contenant des newlines ou guillemets peut injecter des headers HTTP.

**Solution** : `safe_name = re.sub(r'[^\w\-.]', '_', cdm_name)`.

---

### 1.20 [P2] ILIKE sans echappement des wildcards

**Fichiers** : `backend/modules/search_router.py:48,161,178`

**Probleme** : Les termes de recherche sont interpoles dans `ILIKE` sans echapper `%` et `_`. Une recherche pour `%` retourne tout.

**Solution** : `escaped = search_term.replace('%', '\\%').replace('_', '\\_')`.

---

### 1.21 [P2] Audit logger enregistre des donnees sensibles dans les query params

**Fichiers** : `backend/audit/logger.py`

**Probleme** : Les query parameters sont logges tel quel, pouvant inclure des mots de passe (test connexion), tokens, ou donnees PHI.

**Solution** : Filtrer les parametres sensibles avant logging (`password`, `token`, `ticket`).

---

### 1.22 [P3] Permissions de fichier trop ouvertes pour audit logs

**Fichiers** : `backend/audit/logger.py`

**Probleme** : Les fichiers de log audit sont ecrits avec les permissions par defaut (probablement `0o644`). En production, ils peuvent contenir des informations sensibles (usernames, IP, actions).

**Solution** : Ecrire avec `0o640` (owner read/write, group read).

---

### 1.23 [P3] Docker Compose expose la DB sur l'hote

**Fichiers** : `docker-compose.yml`

**Probleme** : Le port PostgreSQL (`5434:5432`) est bind sur `0.0.0.0` par defaut, exposant la base a tout le reseau.

**Solution** : Binder sur `127.0.0.1:5434:5432` ou supprimer le port mapping en production.

---

## 2. PERFORMANCE & OPTIMISATION

### 2.1 [P1] N+1 dans `groups_router.py:list_groups()`

**Fichiers** : `backend/modules/groups_router.py:40-41`

```python
for g in groups:
    count = db.query(UserGroupMember).filter(UserGroupMember.group_name == g.name).count()
```

**Probleme** : Pour N groupes, N requetes COUNT individuelles.

**Solution** : Une seule requete avec `func.count()` + `outerjoin` + `group_by` :
```python
db.query(UserGroup, func.count(UserGroupMember.id))
  .outerjoin(UserGroupMember, UserGroupMember.group_name == UserGroup.name)
  .group_by(UserGroup.id)
  .order_by(UserGroup.name).all()
```

---

### 2.2 [P1] N+1 dans `cohort_sharing_router.py:admin_cohorts_by_user()` (V2)

**Fichiers** : `backend/modules/cohort_sharing_router.py:176-178`

```python
cohorts = db.query(Cohort).order_by(...).all()  # toutes les cohortes
shares = db.query(CohortShare).all()            # tous les partages
```

**Probleme** : Charge toutes les cohortes ET tous les partages en memoire sans filtre ni pagination. Sur une instance avec des milliers de cohortes, c'est tres couteux.

**Solution** : Ajouter pagination. Ou aggreger en SQL avec `GROUP BY created_by`.

---

### 2.3 [P1] Absence de pagination sur plusieurs endpoints de listing

**Fichiers** :
- `backend/modules/mapping/router.py` — `mapping_history()` charge toutes les decisions
- `backend/modules/saved_queries_router.py:41` — `list_queries()` sans LIMIT
- `backend/modules/favorites_router.py:38` — `list_favorites()` sans LIMIT
- `backend/modules/cdm_access_router.py:126` — `list_access()` sans LIMIT
- `backend/modules/cohort_sharing_router.py:176` — charge tout

**Probleme** : Ces endpoints retournent tous les resultats sans pagination. Sur des bases avec beaucoup de donnees, reponses lentes et consommation memoire elevee.

**Solution** : Ajouter `limit` (default 100) et `offset` en query params, comme deja fait dans `concept/router.py`.

---

### 2.4 [P2] Double scan dans `search-source-value` — COUNT + SELECT

**Fichiers** : `backend/modules/concept/router.py:382-394`

```python
cur.execute(psysql.SQL("SELECT COUNT(*) ...").format(full_query), params)
total = cur.fetchone()["cnt"]
cur.execute(psysql.SQL("SELECT * FROM ({}) sub ...").format(full_query), params + [limit, offset])
```

**Probleme** : La requete UNION ALL est executee deux fois — une fois pour le count, une fois pour les resultats. Sur des tables OMOP volumineuses, c'est tres couteux.

**Solution** : Utiliser `COUNT(*) OVER()` comme dans `/search` (P22 fix applique sur search mais pas sur search-source-value).

---

### 2.5 [P2] Export CSV charge tout en memoire

**Fichiers** :
- `backend/modules/concept/router.py:471-475` — `export_source_value_search` charge tous les rows avant export
- `backend/modules/mapping/router.py` — exports mapping
- `backend/main.py` — export audit CSV

**Probleme** : Les resultats sont charges integralement en memoire (`rows = cur.fetchall()`) avant d'etre convertis en CSV. Pour un export de 100K+ lignes, ca consomme beaucoup de RAM.

**Solution** : Utiliser un curseur serveur (`name="export_cursor"`) et streamer ligne par ligne :
```python
def _csv_generator():
    with conn.cursor(name="export_cursor") as cur:
        cur.execute(query, params)
        yield header_row
        for row in cur:
            yield csv_row(row)
return StreamingResponse(_csv_generator(), ...)
```

---

### 2.6 [P2] Requete DOMAIN_CONFIG loop dans `concept/router.py:get_concept_counts()`

**Fichiers** : `backend/modules/concept/router.py:524-547`

**Probleme** : Pour chaque domaine (8 domaines), une requete SELECT est lancee. Soit 8 requetes pour chaque appel.

**Solution** : Construire un UNION ALL unique sur toutes les tables (comme dans `search-source-value`) ou paralleliser avec des futures.

---

### 2.7 [P2] (V2) Suggestion batch sans parallelisation

**Fichiers** : `backend/modules/mapping/suggest.py:102-122`

```python
for term in unmapped_terms:
    suggs = suggest_mappings(conn, sv, sn, domain, ...)
```

**Probleme** : Le batch de suggestions est traite sequentiellement. Chaque terme lance 3-5 requetes SQL. Pour 50 termes, c'est 150-250 requetes sequentielles.

**Solution** : Utiliser `ThreadPoolExecutor` ou des requetes batch SQL (ex: `= ANY(array)` pour la strategy exact match).

---

### 2.8 [P2] Cache manquant pour recherches concepts frequentes

**Fichiers** : `backend/modules/concept/router.py` — `/search`, `/details`, `/hierarchy`

**Probleme** : Les requetes sur la table `concept` sont tres frequentes (auto-complete, exploration). Le meme concept est requete plusieurs fois. Aucun cache.

**Solution** : Cache LRU en memoire pour les resultats de `/details/{concept_id}` et `/hierarchy/{concept_id}` (donnees OMOP statiques qui ne changent qu'a la mise a jour du vocabulaire). TTL 1h.

---

### 2.9 [P3] Thread safety — `_evictor_stop` event partage sans protection

**Fichiers** : `backend/main.py:50-62`

**Probleme** : `_evictor_stop` est un `threading.Event()`, ce qui est thread-safe. Pas de vrai probleme, mais le `_evictor_thread` global est mutable sans lock. Risque theorique si le shutdown est appele pendant un restart.

**Solution** : Encapsuler dans une classe `PoolEvictor` pour clarifier le lifecycle.

---

## 3. ARCHITECTURE & QUALITE DE CODE

### 3.1 [P1] (V2) Pas de migration Alembic initiale

**Fichiers** : `backend/alembic/`

**Probleme** : Alembic est configure mais aucune migration n'a ete generee. `alembic revision --autogenerate` n'a pas ete lance. Les nouveaux index composites et contraintes uniques ajoutees dans `models.py` ne sont donc pas refletes dans un fichier de migration.

**Solution** : Generer la migration initiale : `alembic revision --autogenerate -m "initial schema"`. Ajouter un README expliquant le workflow.

---

### 3.2 [P1] Duplication de `_get_cdm_conn()` dans 5 routers

**Fichiers** :
- `backend/modules/cohort/router.py:85-92`
- `backend/modules/mapping/router.py:84-92`
- `backend/modules/incidence/router.py:27-35`
- `backend/modules/estimation/router.py:27-35`
- `backend/modules/search_router.py:67-74`

**Probleme** : La meme logique (query CdmConfig, decrypt, get_omop_connection, get schema) est dupliquee dans chaque router. Risque de divergence (ex: `search_router` ne valide pas le schema, `incidence` n'utilise pas `safe_identifier`).

**Solution** : Extraire dans un module commun `utils/cdm_helper.py` :
```python
def get_cdm_connection(db, cdm_name) -> tuple[PooledConnection, str]:
    """Return (connection, validated_schema) for a CDM."""
```

---

### 3.3 [P2] Modeles Pydantic manquants — endpoints utilisant `body: dict`

**Fichiers** :
- `backend/main.py:466` — `assign_role(body: dict)` — pas de validation
- `backend/main.py:502` — `remove_role()` — pas de body model
- `backend/main.py:532` — `toggle_user(body: dict)`
- `backend/main.py:668` — `list_access_requests(status_filter: str)` — pas de validation enum

**Probleme** : Les endpoints admin utilisent `body: dict` au lieu de modeles Pydantic. Pas de validation de types, de longueur, ni de documentation OpenAPI.

**Solution** : Creer des modeles Pydantic (`AssignRoleRequest`, `ToggleUserRequest`, etc.) avec validation.

---

### 3.4 [P2] (V2) Logique metier dans `main.py` — fichier trop gros

**Fichiers** : `backend/main.py` (593+ lignes)

**Probleme** : `main.py` contient la logique d'audit, d'admin Keycloak, d'access requests, et d'ajout d'utilisateurs. Ce fichier devrait etre le point d'entree uniquement.

**Solution** : Deplacer vers des routers dedies :
- `modules/admin_router.py` — gestion utilisateurs Keycloak
- `modules/audit_router.py` — logs/stats/export audit
- `modules/access_requests_router.py` — demandes d'acces

---

### 3.5 [P2] Inconsistance dans la gestion des schemas OMOP

**Fichiers** : Multiples routers

**Probleme** : Le schema OMOP est obtenu de 3 facons differentes selon le router :
1. `safe_identifier(_get_omop_schema(db, cdm))` (concept_router) — valide
2. `settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA` (incidence, estimation) — **pas de safe_identifier**
3. `safe_identifier(raw)` dans mapping — valide

Les routers `incidence` et `estimation` n'appliquent pas `safe_identifier` sur le schema.

**Solution** : Centraliser dans `utils/cdm_helper.py` (cf. 3.2).

---

### 3.6 [P3] Imports inline repetes

**Fichiers** : `backend/main.py` (multiples `from db.models import ...` et `from audit.logger import ...` a l'interieur de fonctions)

**Probleme** : Les imports sont repetes dans chaque endpoint pour eviter les imports circulaires. Cela complexifie la lecture et masque les dependances.

**Solution** : Restructurer les imports au niveau module ou utiliser `typing.TYPE_CHECKING`.

---

## 4. FONCTIONNALITES & LOGIQUE METIER

### 4.1 [P1] Endpoint `list_groups()` accessible sans restriction de role

**Fichiers** : `backend/modules/groups_router.py:36`

**Probleme** : Tout utilisateur authentifie peut lister tous les groupes avec leur composition. L'endpoint ne filtre pas par role.

**Solution** : Restreindre aux roles admin/data-manager ou limiter les informations retournees (cacher les membres pour les non-admins).

---

### 4.2 [P1] Endpoint `create_notification()` accessible a tous

**Fichiers** : `backend/modules/notifications_router.py:179`

**Probleme** : N'importe quel utilisateur authentifie peut creer une notification pour n'importe quel autre utilisateur. Potentiel de spam/phishing interne.

**Solution** : Supprimer l'endpoint public ou le restreindre au role admin.

---

### 4.3 [P2] Cohort delete ne supprime pas les CohortShares associes

**Fichiers** : `backend/modules/cohort/router.py` — endpoint DELETE

**Probleme** : Si une cohorte est partagee puis supprimee via l'endpoint direct (pas via cascade CDM delete qui gere les shares), les enregistrements `CohortShare` orphelins restent en base.

**Solution** : Ajouter `db.query(CohortShare).filter(CohortShare.cohort_id == cohort_id).delete()` avant de supprimer la cohorte.

---

### 4.4 [P2] (V2) Pas de nettoyage des taches background terminees

**Fichiers** :
- `backend/modules/cohort/router.py` — `_characterization_tasks`, `_pathways_tasks`
- `backend/modules/mapping/router.py` — `_active_suggestions`

**Probleme** : Les resultats de taches restent en memoire indefiniment. Pas de TTL, pas de max capacity.

**Solution** : Thread de nettoyage periodique (ou integration dans le pool evictor) avec TTL 1h.

---

### 4.5 [P2] `RunRequest` dans `ohdsi/router.py` — schema non valide

**Fichiers** : `backend/modules/ohdsi/router.py:68-73`

```python
class RunRequest(BaseModel):
    results_schema: str = "omop_cdm"
    vocabulary_schema: str = "omop_cdm"
```

**Probleme** : Les schemas `results_schema` et `vocabulary_schema` ne sont pas valides via `safe_identifier` ni via regex pattern Pydantic. Ils sont passes comme variables d'environnement au conteneur Docker, mais une valeur malveillante pourrait causer des problemes.

**Solution** : Ajouter `pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"` sur les champs schema.

---

### 4.6 [P3] Traductions manquantes / incompletes (V2)

**Fichiers** : `backend/i18n/en.json`, `backend/i18n/fr.json`

**Probleme** : Beaucoup de strings sont hardcodees en francais dans le code backend (messages de notification, erreurs specifiques) et ne passent pas par le systeme i18n.

**Exemples** :
- `groups_router.py:69` — `f"Ajouté au groupe : {req.name}"` (hardcode FR)
- `cohort_sharing_router.py:107` — `f"Cohorte partagée : {cohort.name}"` (hardcode FR)
- Messages d'erreur varies en anglais dans les HTTPException

**Solution** : Ajouter les cles dans `en.json`/`fr.json` et utiliser un helper `t(key, lang)`.

---

### 4.7 [P3] Endpoint `/api/quality/analyze` ne verifie pas l'acces CDM

**Fichiers** : `backend/modules/quality/router.py`

**Probleme** : L'endpoint d'analyse ne verifie pas que l'utilisateur a acces au CDM demande via le systeme ACL (`check_cdm_access`). Un utilisateur avec role `chercheur` pourrait lancer une analyse sur un CDM auquel il n'a pas acces.

**Solution** : Ajouter `check_cdm_access(cdm_name, request, db)` en debut d'endpoint.

---

### 4.8 [P3] Pas de verification ACL CDM sur les endpoints incidence/estimation/mapping/pathways

**Fichiers** :
- `backend/modules/incidence/router.py`
- `backend/modules/estimation/router.py`
- `backend/modules/mapping/router.py`
- `backend/modules/cohort/router.py` — pathways

**Probleme** : Meme probleme que 4.7 — ces endpoints prennent `cdm_name` en parametre mais ne verifient pas les droits d'acces.

**Solution** : Ajouter `check_cdm_access` systematiquement.

---

## 5. TESTS & COUVERTURE

### 5.1 [P1] Pas de tests pour les IDOR (items 1.5, 1.6, 1.7)

**Probleme** : Il n'y a pas de tests verifiant qu'un utilisateur non-proprietaire ne peut pas modifier/supprimer les ressources d'un autre.

**Solution** : Ajouter dans `test_role_access.py` :
- Test: user B ne peut pas `PUT /api/saved-queries/{id}` d'user A
- Test: user B ne peut pas `DELETE /api/cohorts/{id}` d'user A
- Test: user B ne peut pas `POST /api/notifications/{id}/read` d'user A

---

### 5.2 [P1] Pas de tests pour les endpoints incidence/estimation

**Probleme** : `test_incidence.py` et `test_estimation.py` n'existent pas. Ces modules contiennent de la logique statistique complexe (Kaplan-Meier, log-rank test, calcul d'incidence) sans couverture.

**Solution** : Ajouter des tests unitaires pour les fonctions de calcul (`compute_km`, `compute_incidence`, `log_rank_test`) avec des jeux de donnees synthetiques.

---

### 5.3 [P2] Pas de tests pour `suggest.py` strategies individuelles

**Probleme** : Les 5 strategies de suggestion ne sont pas testees individuellement. Seul le batch via API est teste.

**Solution** : Ajouter des tests unitaires pour `_exact_match`, `_relationship_match`, `_ingredient_match`, `_fuzzy_match`, `_keyword_match`, `_contextual_match` avec un mock de curseur.

---

### 5.4 [P2] (V2) Tests frontend insuffisants

**Probleme** : Seuls 10 tests frontend existent (client API). Aucun test de composant React (pages, formulaires, interactions).

**Solution** : Ajouter des tests pour :
- `CohortPage` — creation/selection cohorte
- `MappingPage` — workflow de mapping
- `QualityPage` — affichage resultats
- `PathwaysPanel` — interactions sunburst
- Formulaires CDM — validation

---

### 5.5 [P2] Pas de tests pour `sql_builder.py` cas limites

**Probleme** : `sql_builder.py` est un module complexe (550+ lignes) avec des jointures temporelles, ancestors, et CTEs. Les tests existants ne couvrent pas :
- Relations temporelles (before, after, overlaps, etc.)
- Groupes imbriques (AND/OR)
- `include_descendants` avec concept_ancestor
- Cas limites: criteres vides, domaines invalides

**Solution** : Suite de tests dediee `test_sql_builder.py`.

---

### 5.6 [P3] Tests de charge manquants

**Probleme** : Aucun test de charge n'existe. Le connection pool, le rate limiter, et les endpoints de batch ne sont pas testes sous stress.

**Solution** : Ajouter un script `locustfile.py` ou `k6` pour les tests de charge.

---

## 6. DEVOPS & INFRASTRUCTURE

### 6.1 [P1] (V2) Pas de healthcheck pour le backend

**Fichiers** : `docker-compose.yml`

**Probleme** : Le service `opal-backend` n'a pas de healthcheck Docker. Si le processus FastAPI crashe, le conteneur reste "running" sans etre redemarrer.

**Solution** : Ajouter :
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```
Et creer l'endpoint `/api/health` dans `main.py` (verifier DB + pool status).

---

### 6.2 [P1] Pas de healthcheck pour le frontend

**Fichiers** : `docker-compose.yml`

**Probleme** : Le service `opal-frontend` (nginx) n'a pas de healthcheck.

**Solution** : Ajouter `test: ["CMD", "curl", "-f", "http://localhost:3000/"]`.

---

### 6.3 [P2] (V2) CI ne lance pas les tests de securite

**Fichiers** : `.github/workflows/ci.yml`

**Probleme** : Le pipeline CI lance les tests et build, mais ne fait pas :
- Scan de vulnerabilites des dependances (`pip-audit`, `npm audit`)
- Lint de securite (`bandit` pour Python)
- Scan d'image Docker (`trivy`)

**Solution** : Ajouter des jobs dans le CI.

---

### 6.4 [P2] Pas de `.env.example` a jour

**Fichiers** : Racine du projet

**Probleme** : Les nouvelles variables d'environnement ajoutees (`ENVIRONMENT`, `ENCRYPTION_KEY`, `OMOP_POOL_*`, `APP_DB_POOL_*`, `KEYCLOAK_ISSUER_URL`, `EXTERNAL_HOSTNAME`, `DB_EXTERNAL_PORT`) ne sont pas documentees dans un `.env.example`.

**Solution** : Creer/mettre a jour `.env.example` avec toutes les variables et leurs valeurs par defaut.

---

### 6.5 [P3] Logs non structures (texte brut)

**Fichiers** : `backend/main.py` — `logging.basicConfig(format=...)`

**Probleme** : Les logs sont en texte brut. En production avec un aggregateur (ELK, Loki), le parsing est difficile.

**Solution** : Passer en JSON logging (`python-json-logger` ou `structlog`).

---

### 6.6 [P3] (V2) Pas de backup automatise de la base interne

**Probleme** : La base PostgreSQL interne (`opal-db`) stocke toutes les configs, snapshots, cohortes, decisions de mapping. Pas de backup automatise.

**Solution** : Ajouter un script cron ou un sidecar `pg_dump` dans le compose.

---

## 7. FRONTEND

### 7.1 [P2] (V2) Accessibilite (a11y) — ARIA labels manquants

**Fichiers** : `frontend/src/pages/*.tsx`, `frontend/src/components/**/*.tsx`

**Probleme** : Malgre l'ajout d'ARIA basique dans le commit P0/P1, la plupart des composants interactifs manquent encore de :
- `aria-label` sur les boutons iconiques (sans texte visible)
- `aria-live` sur les regions dynamiques (resultats de recherche, notifications)
- `role="alert"` sur les messages d'erreur
- Navigation au clavier sur le sunburst Pathways (interactif mais souris-only)

**Solution** : Audit a11y systematique avec `axe-core` ou `@axe-core/react`.

---

### 7.2 [P2] PathwaysPanel — sunburst non accessible au clavier

**Fichiers** : `frontend/src/components/cohort/PathwaysPanel.tsx`

**Probleme** : Le graphique sunburst est un SVG interactif (hover, click) mais ne gere pas le focus clavier ni le screen reader.

**Solution** : Ajouter `tabIndex`, `onKeyDown`, `aria-label` sur les arcs, et un `<desc>` SVG pour les lecteurs d'ecran.

---

### 7.3 [P2] (V2) `any` usage excessif dans le frontend

**Fichiers** : `frontend/src/pages/*.tsx`, `frontend/src/api/client.ts`

**Probleme** : Plusieurs reponses API sont typees `any` ou `Record<string, any>`. Les interfaces TypeScript dans `types/index.ts` ne couvrent pas tous les endpoints.

**Solution** : Typer les reponses des endpoints non couverts : audit, admin, notifications, favorites, saved queries.

---

### 7.4 [P3] Pas de lazy loading des pages

**Fichiers** : `frontend/src/App.tsx`

**Probleme** : Toutes les pages sont importees statiquement. Le bundle JS charge toutes les pages meme si l'utilisateur n'en visite qu'une.

**Solution** : `React.lazy()` + `Suspense` pour les pages lourdes (CohortPage, MappingPage, QualityPage).

---

### 7.5 [P3] Pas de gestion d'etat global (state management)

**Fichiers** : `frontend/src/App.tsx`

**Probleme** : Le CDM selectionne est passe via props drilling depuis `App.tsx`. Les notifications et le user sont geres via `localStorage` et props.

**Solution** : Introduire un state management leger (Zustand ou React Context) pour le CDM selectionne, le user authentifie, et les notifications.

---

## 8. COMPLEMENT — Findings supplementaires (agent performance)

Les items suivants ont ete identifies par un audit de performance complementaire et ajoutent des findings supplementaires.

### 8.0 Findings supplementaires de l'audit fonctionnel

#### 8.0.1 [P2] Nginx static asset location supprime les security headers

**Fichiers** : `frontend/nginx.conf` — `location ~* \.(js|css|png|...)`

**Probleme** : Le bloc `location` pour les assets statiques n'herite pas des `add_header` du bloc `server`. En nginx, `add_header` dans un bloc enfant ecrase ceux du parent. Les headers CSP, HSTS, X-Frame-Options ne sont pas envoyes sur les fichiers statiques.

**Solution** : Repeter les headers dans le bloc `location` ou utiliser `include` pour les headers communs.

---

#### 8.0.2 [P2] `datetime.utcnow()` deprecie (Python 3.12+)

**Fichiers** : 9 occurrences dans 4 fichiers (modeles, routers)

**Probleme** : `datetime.utcnow()` est deprecie depuis Python 3.12. Il retourne un datetime naive (sans timezone).

**Solution** : Remplacer par `datetime.now(timezone.utc)` (deja utilise dans `models.py:_utcnow()`).

---

#### 8.0.3 [P2] Pas de ForeignKey dans les modeles SQLAlchemy

**Fichiers** : `backend/db/models.py`

**Probleme** : Aucun modele n'utilise `ForeignKey`. Les relations (CohortVersion.cohort_id → Cohort.id, etc.) sont gerees uniquement au niveau applicatif. La base ne garantit pas l'integrite referentielle.

**Solution** : Ajouter les `ForeignKey` avec `ondelete="CASCADE"` la ou c'est pertinent, dans une migration Alembic.

---

#### 8.0.4 [P2] Missing DELETE pour IncidenceAnalysis et EstimationAnalysis

**Fichiers** : `backend/modules/incidence/router.py`, `backend/modules/estimation/router.py`

**Probleme** : Ces modeles ont un CRUD incomplet — create + list + get mais pas de delete. Les analyses sauvegardees ne peuvent pas etre supprimees.

**Solution** : Ajouter des endpoints DELETE avec verification de propriete.

---

#### 8.0.5 [P3] `LandingPage.tsx` est du code mort

**Fichiers** : `frontend/src/pages/LandingPage.tsx`

**Probleme** : La page existe mais n'est routee nulle part dans `App.tsx`.

**Solution** : Supprimer le fichier ou l'ajouter comme route d'accueil.

---

### 8.1 [P0] SQL injection dans `concept_set/router.py` — placeholders manuels

**Fichiers** :
- `backend/modules/concept_set/router.py:167` — `",".join(str(int(i)) for i in expand_ids)` interpole dans SQL
- `backend/modules/concept_set/router.py:202` — meme pattern sur `concept_ids`

**Probleme** : Les concept_ids sont interpoles via f-string dans les requetes SQL. Bien que `int()` protege partiellement, le pattern est un anti-pattern qui invite aux erreurs de copier-coller. Le schema (`omop_schema`) est aussi interpole via f-string sans `safe_identifier`.

**Solution** : Utiliser `WHERE ancestor_concept_id = ANY(%s)` avec un parametre tuple/list, comme dans `concept/router.py`.

---

### 8.2 [P1] Thread safety — task dicts sans lock

**Fichiers** :
- `backend/modules/quality/router.py:31` — `_active_analyses`
- `backend/modules/mapping/router.py:31` — `_active_suggestions`
- `backend/modules/cohort/router.py:897` — `_active_characterizations`
- `backend/modules/datamanagement/router.py:109` — `_active_extractions`

**Probleme** : Ces dicts sont ecrits par des threads background et lus par des threads de requete sans aucun lock. Comparer avec `ohdsi/router.py:61` qui utilise correctement `threading.Lock`.

**Solution** : Ajouter un `threading.Lock` par dict.

---

### 8.3 [P1] Extractions stockent les CSV complets en memoire

**Fichiers** : `backend/modules/datamanagement/router.py:331-349`

**Probleme** : Le CSV d'extraction est construit dans un `StringIO` puis stocke comme string dans `_active_extractions[task_id]["data"]`. Pour une extraction de 100K+ lignes avec beaucoup de colonnes, c'est des dizaines de MB par tache, jamais nettoyes.

**Solution** : Ecrire les extractions dans un fichier temporaire sur disque. Stocker le chemin dans le dict. Streamer depuis le fichier au download. Supprimer apres telechargement ou expiration TTL.

---

### 8.4 [P1] Audit logs charges integralement en memoire

**Fichiers** : `backend/main.py:289-304`

**Probleme** : L'endpoint `/api/audit/logs` lit des fichiers JSONL entiers en memoire, parse toutes les lignes, puis filtre et pagine en Python. Les logs d'audit grandissent sans limite.

**Solution** : Utiliser `itertools.islice` pour une pagination basee sur le comptage de lignes sans charger le fichier entier. Ou indexer les entrees d'audit dans la base applicative.

---

### 8.5 [P1] Dashboard qualite — requetes sequentielles par domaine

**Fichiers** : `backend/modules/quality/domains/dashboard.py:29-87`

**Probleme** : Itere sur `DOMAIN_CONFIG` (14+ domaines) avec un `SELECT COUNT(*)` par table de domaine. Soit ~28 requetes sequentielles par appel.

**Solution** : Construire un `UNION ALL` unique sur toutes les tables avec un label domaine. Executer une seule fois.

---

### 8.6 [P2] `observation_period.py` — 6 requetes repetant le meme CTE

**Fichiers** : `backend/modules/quality/domains/observation_period.py:50-59`

**Probleme** : 6 `execute()` calls qui re-declarent chacune le meme CTE `per_cte`. Le commentaire dit "P13 fix: reduced from 6 to 4 scans" mais il y a encore 6 appels.

**Solution** : Combiner en 2-3 requetes avec plusieurs colonnes de resultat par requete.

---

### 8.7 [P2] `bulk_decision` — charge toutes les decisions puis inserts individuels

**Fichiers** : `backend/modules/mapping/router.py:767-801`

**Probleme** : Charge toutes les decisions existantes d'un CDM+domaine dans un set Python, puis boucle pour creer des `MappingDecision` un par un.

**Solution** : Utiliser `INSERT ... ON CONFLICT DO UPDATE` (upsert) avec `executemany` ou operations bulk SQLAlchemy.

---

### 8.8 [P2] N+1 dans `datamanagement/router.py:list_cohorts_for_extraction()`

**Fichiers** : `backend/modules/datamanagement/router.py:127-133`

```python
for c in cohorts:
    latest = db.query(CohortVersion).filter(...).order_by(...).first()
```

**Probleme** : Pour N cohortes, N requetes individuelles pour obtenir la derniere version (meme pattern que le N+1 corrige dans `cohort/router.py`).

**Solution** : Appliquer le meme fix subquery que dans `list_cohorts`.

---

### 8.9 [P3] Pas de compression des reponses (GZip)

**Fichiers** : `backend/main.py`

**Probleme** : Pas de middleware de compression. Les reponses JSON volumineuses (snapshots qualite, resultats concept search) sont envoyees non compressees.

**Solution** : `app.add_middleware(GZipMiddleware, minimum_size=1000)`.

---

### 8.10 [P3] Handlers synchrones pour appels HTTP Keycloak

**Fichiers** : `backend/main.py:440-461`

**Probleme** : Les appels HTTP vers Keycloak sont synchrones (`requests.post/get`) dans des handlers synchrones. Chaque appel bloque un thread du pool.

**Solution** : Convertir en `async def` avec `httpx.AsyncClient` pour les endpoints Keycloak. Priorite basse car le threadpool par defaut (40 threads) est suffisant pour une charge moderee.

---

## RESUME

| Priorite | Securite | Performance | Architecture | Fonctionnalites | Tests | DevOps | Frontend | Total |
|----------|----------|-------------|-------------|----------------|-------|--------|----------|-------|
| **P0** | 4 | 0 | 0 | 0 | 0 | 0 | 0 | **4** |
| **P1** | 11 | 8 | 2 | 2 | 2 | 2 | 0 | **27** |
| **P2** | 8 | 9 | 5 | 4 | 3 | 2 | 3 | **34** |
| **P3** | 3 | 3 | 1 | 2 | 1 | 2 | 3 | **15** |
| **Total** | **26** | **20** | **8** | **8** | **6** | **6** | **6** | **80** |

### Items V2 (du PLAN_AMELIORATION.md initial, non resolus ou necessitant un 2e passage)
- 1.8 — Rate limiting insuffisant (partiellement corrige, couverture incomplete)
- 1.10 — DNS rebinding SSRF
- 2.2 — Admin cohorts pagination
- 2.7 — Batch suggestions parallelisation
- 3.1 — Migration Alembic initiale
- 3.4 — main.py trop gros
- 4.4 — Nettoyage taches background
- 4.6 — Traductions incompletes
- 5.4 — Tests frontend insuffisants
- 6.3 — CI securite
- 6.6 — Backup automatise
- 7.1 — Accessibilite a11y
- 7.3 — Types `any` dans le frontend
