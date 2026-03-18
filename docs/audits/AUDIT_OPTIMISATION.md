# Audit d'Optimisation & Performance — OPAL v1.2.0

**Date** : 2026-03-18
**Périmètre** : Backend (FastAPI/psycopg2), Frontend (React/Vite), Infrastructure (Docker/PostgreSQL)
**Méthodologie** : Analyse statique du code, revue des patterns de requêtes, évaluation architecturale

---

## Résumé Exécutif

| Sévérité | Nombre |
|----------|--------|
| CRITIQUE | 3 |
| HAUTE | 7 |
| MOYENNE | 7 |
| BASSE | 4 |
| **Total** | **21** |

L'application est globalement bien conçue avec des choix architecturaux judicieux (connection pooling, GZip, lazy loading, cache i18n). Les problèmes principaux concernent l'absence de pagination sur certains endpoints critiques, le manque d'optimisation des requêtes SQL dans les modules analytiques, et l'absence de code splitting avancé côté frontend.

---

## Constats Positifs

- **Connection pooling OMOP** : `ThreadedConnectionPool` par CDM avec éviction automatique (`omop_connector.py`)
- **Pool de connexions app** : SQLAlchemy avec pool_size/max_overflow/pool_recycle configurables (`config.py:62-64`)
- **GZip middleware** activé avec seuil 1000 bytes (`main.py:174`)
- **Cache i18n** au démarrage — pas de lecture fichier par requête (`main.py:254-257`)
- **Lazy loading** des pages frontend (`App.tsx:12-23`)
- **Statement timeout** de 5 min sur les connexions OMOP (`omop_connector.py:24`)
- **Health checks** sur tous les services Docker avec `start_period` (`docker-compose.yml`)
- **Resource limits** Docker sur tous les containers (`docker-compose.yml:34-38, 56-59, 80-83, 107-111`)
- **Indexes composites** sur les tables fréquemment filtrées (`models.py:36-38, 80-82, 103-104, 267-268`)
- **Notification badge** utilise correctement `GROUP BY` au lieu de N+1 (`notifications_router.py:101-106`)
- **Rollback systématique** avant réutilisation de connexion poolée (`omop_connector.py:80, 173-174`)

---

## CRITIQUE

### P1 — Absence de pagination sur `list_snapshots`

**Fichier** : `backend/modules/quality/router.py:587-607`

```python
@router.get("/snapshots/{cdm_name}/{domain}")
def list_snapshots(cdm_name: str, domain: str, db: Session = Depends(get_db)):
    snapshots = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == domain)
        .order_by(AnalysisSnapshot.version.desc())
        .all()  # ← Charge TOUT en mémoire
    )
```

Pour un CDM avec 200+ analyses par domaine (usage intensif sur plusieurs mois), cette requête charge toutes les lignes avec leur colonne `results` (JSON volumineux contenant les résultats d'analyse complets).

**Impact** : Réponses de plusieurs Mo, OOM possible sur le backend, latence de plusieurs secondes.

**Remédiation** :
```python
limit: int = Query(default=50, ge=1, le=200),
offset: int = Query(default=0, ge=0),
# Ne PAS charger results dans la liste
snapshots = db.query(
    AnalysisSnapshot.id, AnalysisSnapshot.version, AnalysisSnapshot.created_at
).filter(...).order_by(...).offset(offset).limit(limit).all()
```

---

### P2 — Logs d'audit chargés intégralement en mémoire

**Fichier** : `backend/main.py:310-369`

```python
@app.get("/api/audit/logs")
def get_audit_logs(...):
    entries = []
    for dt_str in dates:
        log_file = AUDIT_LOG_DIR / f"{dt_str}.jsonl"
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                # Filtrage en Python...
                total += 1
                entries.append(entry)  # ← TOUT en mémoire
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return {"entries": entries[start:start + page_size], ...}
```

Le endpoint charge TOUTES les entrées d'audit d'une plage de dates en mémoire, les trie, puis pagine. Pour un système actif (10000+ requêtes/jour), un fichier JSONL quotidien peut atteindre 50-100 Mo.

**Impact** : OOM sur le backend, latence de 10+ secondes pour une requête multi-jours.

**Remédiation** :
- Lire les fichiers en streaming avec early-exit après pagination
- Pour les requêtes multi-jours, utiliser un compteur pour le skip et ne charger que `page_size` entrées
- Ou migrer les logs d'audit vers une table PostgreSQL avec indexes

---

### P3 — Export CSV sans streaming réel

**Fichier** : `backend/main.py:423-479`

```python
@app.get("/api/audit/export")
def export_audit_csv(...):
    entries = []  # Charge tout
    # ... lecture identique à P2 ...
    output = io.StringIO()
    writer = csv.writer(output)
    for e in entries:
        writer.writerow([...])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]))  # ← Faux streaming
```

`iter([output.getvalue()])` crée un itérateur sur un SEUL élément : la totalité du CSV en mémoire. C'est un `StreamingResponse` de nom mais pas de fait.

**Impact** : Consommation mémoire 2x (entries + CSV string), pas de first-byte latency réduite.

**Remédiation** : Utiliser un générateur qui yield ligne par ligne.

---

## HAUTE

### P4 — Requêtes SQL non optimisées dans l'analyse clinique

**Fichier** : `backend/modules/quality/domains/clinical.py`

L'analyse clinique exécute de multiples requêtes séquentielles pour chaque domaine :
1. Count total
2. Unmapped source values (TOP N)
3. Top concepts par fréquence
4. Records per person distribution
5. Temporal distribution

Pour un domaine avec 100M+ de lignes (ex: `measurement`), chaque requête fait un full scan potentiel. Les requêtes `_get_records_per_person()` font un double GROUP BY :

```sql
SELECT cnt, COUNT(*) FROM (
    SELECT person_id, COUNT(*) AS cnt FROM schema.table GROUP BY person_id
) t GROUP BY cnt ORDER BY cnt
```

**Impact** : 5-10 minutes par domaine sur un CDM de 100M lignes. L'analyse complète (8 domaines) peut prendre 1h+.

**Remédiation** :
- Combiner les requêtes indépendantes en un seul scan avec `CASE/FILTER`
- Utiliser des requêtes avec `TABLESAMPLE` pour les distributions sur très grands jeux de données
- Ajouter un timeout progressif avec annulation

---

### P5 — Suggestions de mapping : traitement séquentiel par batch

**Fichier** : `backend/modules/mapping/suggest.py`

Les suggestions de mapping traitent chaque terme non-mappé séquentiellement avec 6 stratégies par terme. Pour 500 termes non-mappés, cela signifie potentiellement 3000 requêtes séquentielles sur une seule connexion.

**Impact** : 30-60 secondes pour 100 termes, plusieurs minutes pour 500+.

**Remédiation** :
- Utiliser `ThreadPoolExecutor(max_workers=4)` avec des connexions séparées du pool
- Regrouper les requêtes exact-match en un seul `IN (...)` au lieu d'une requête par terme
- Pré-charger le cache de résultats SapBERT en mémoire

---

### P6 — Recherche de concepts avec ILIKE sans index trigram

**Fichier** : `backend/modules/concept/router.py`

La recherche de concepts utilise `ILIKE %term%` sur `concept_name` et `concept_code`. Sans index `pg_trgm`, chaque recherche fait un full scan de la table `concept` (2.5M+ lignes dans un CDM standard).

**Impact** : 2-5 secondes par recherche au lieu de <100ms avec un index trigram.

**Remédiation** :
- Documenter la création d'un index `CREATE INDEX idx_concept_trgm ON concept USING gin (concept_name gin_trgm_ops)` sur les CDMs externes
- En alternative, préférer la recherche par préfixe (`ILIKE 'term%'`) qui peut utiliser un index B-tree

---

### P7 — Cache TTL manuel dans le module concept

**Fichier** : `backend/modules/concept/router.py`

Le cache utilise un dictionnaire avec `time.monotonic()` pour le TTL. Les problèmes :
1. Pas de limite de taille — le cache peut croître indéfiniment
2. Pas d'invalidation quand un CDM est modifié
3. La clé de cache n'est pas toujours complète (risque de collision)

**Impact** : Consommation mémoire croissante, données périmées servies après modification du CDM.

**Remédiation** : Utiliser `functools.lru_cache` avec `maxsize` ou `cachetools.TTLCache(maxsize=1000, ttl=300)`. Invalider le cache dans `cdm_router` lors d'un update/delete.

---

### P8 — Vite : pas de code splitting avancé

**Fichier** : `frontend/vite.config.ts`

```typescript
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Pas de rollupOptions.output.manualChunks
})
```

Les bibliothèques lourdes (Recharts, CodeMirror, Framer Motion) sont bundlées dans le chunk principal ou dans des chunks non optimisés. Le lazy loading des pages est bien présent (`App.tsx:12-23`), mais les dépendances communes ne sont pas séparées.

**Impact** : Bundle principal plus gros que nécessaire, temps de chargement initial plus long.

**Remédiation** :
```typescript
build: {
  rollupOptions: {
    output: {
      manualChunks: {
        'recharts': ['recharts'],
        'framer': ['framer-motion'],
        'vendor': ['react', 'react-dom', 'react-router-dom'],
      }
    }
  }
}
```

---

### P9 — Pool evictor : fréquence de 5 minutes trop lente

**Fichier** : `backend/main.py:49-54`

```python
def _pool_evictor():
    while not _evictor_stop.is_set():
        _evictor_stop.wait(300)  # 5 minutes
        evict_idle_pools()
```

Avec `OMOP_POOL_IDLE_TIMEOUT=1800` (30 min), un pool peut rester ouvert jusqu'à 35 minutes (30 + 5 de délai d'éviction). Chaque pool maintient `POOL_MIN_CONN=2` connexions ouvertes.

**Impact** : Avec 20 CDMs différents accédés dans la journée, 40 connexions PostgreSQL restent ouvertes inutilement pendant 35 min.

**Remédiation** : Réduire l'intervalle à 60 secondes, ou implémenter un callback de dernière utilisation.

---

### P10 — WebSocket `_user_roles` ne se nettoie pas complètement

**Fichier** : `backend/utils/ws_manager.py:34-42`

```python
def disconnect(self, websocket: WebSocket, username: str):
    conns = self._connections.get(username)
    if conns:
        conns.discard(websocket)
        if not conns:
            del self._connections[username]
            for role_users in self._user_roles.values():
                role_users.discard(username)
```

Si un utilisateur a encore d'autres connexions actives (multiple tabs), les rôles ne sont pas nettoyés. Correct. Mais si TOUTES les connexions sont fermées et que `role_users` devient un set vide, la clé du rôle reste dans `_user_roles`.

**Impact** : Fuite mémoire lente — les clés de rôle avec des sets vides s'accumulent. Faible en pratique (peu de rôles distincts), mais indicatif d'un manque de rigueur.

**Remédiation** : Nettoyer les entrées vides :
```python
self._user_roles = {k: v for k, v in self._user_roles.items() if v}
```

---

## MOYENNE

### P11 — `quality/router.py` : analyse SSE avec Queue bloquante

**Fichier** : `backend/modules/quality/router.py`

L'analyse qualité avec SSE utilise un `queue.Queue` + `loop.run_in_executor()` pour le polling. Le thread d'analyse écrit dans la queue, le générateur SSE lit en async. Le pattern fonctionne, mais :
- Chaque analyse en cours consomme un thread du pool executor
- La limite de 100 analyses concurrentes (`_active_analyses`) est globale, pas par CDM
- Pas de priorité entre analyses

**Impact** : Sur un serveur avec beaucoup d'utilisateurs, le pool executor peut être saturé.

**Remédiation** : Utiliser `asyncio.Queue` avec un worker pool dédié, limiter à 5 analyses par CDM.

---

### P12 — `notification_cleaner` : session DB non optimale

**Fichier** : `backend/main.py:89-112`

```python
def _notification_cleaner():
    while not _evictor_stop.is_set():
        _evictor_stop.wait(21600)  # 6h
        db: _Session = SessionLocal()
        deleted = db.query(_Notif).filter(...).delete(synchronize_session=False)
        db.commit()
        db.close()
```

Utilise `synchronize_session=False` mais charge quand même les IDs pour le DELETE. Sur des milliers de notifications, cela peut être lent.

**Remédiation** : Utiliser un `DELETE FROM ... WHERE ...` brut via `db.execute(text(...))` pour éviter le chargement ORM.

---

### P13 — Pathways : tables temporaires sans ANALYZE

**Fichier** : `backend/modules/cohort/pathways.py:93-103`

Les tables temporaires `_pw_target`, `_pw_events`, `_pw_eras` sont créées avec des index, mais sans `ANALYZE`. Le planificateur PostgreSQL n'a pas de statistiques sur ces tables et peut choisir un plan d'exécution sous-optimal.

**Remédiation** : Ajouter `cur.execute("ANALYZE _pw_target")` après l'insertion et l'indexation.

---

### P14 — Pas de compression Brotli

**Fichier** : `backend/main.py:173-174`

Le backend utilise GZip mais pas Brotli, qui offre un taux de compression ~20% meilleur pour les réponses JSON/HTML.

**Remédiation** : Ajouter Brotli via le reverse proxy Nginx ou un middleware Python.

---

### P15 — Absence de métriques de performance

Le backend n'expose aucun endpoint de métriques (Prometheus, StatsD). Il n'y a pas de suivi :
- Taille des pools de connexion
- Latence P50/P95/P99 des endpoints
- Taux d'erreur par endpoint
- Utilisation mémoire/CPU

**Remédiation** : Intégrer `prometheus-fastapi-instrumentator` pour exposer `/metrics`.

---

### P16 — PostgreSQL app : pas de configuration de tuning

**Fichier** : `docker-compose.yml:68-89`

Le PostgreSQL interne utilise la configuration par défaut de `postgres:16-alpine`. Pour une application avec des requêtes JSON et des tables avec des colonnes `JSON`, les paramètres par défaut sont sous-optimaux.

**Remédiation** : Ajouter un `postgresql.conf` ou des arguments de commande :
```yaml
command: postgres -c shared_buffers=256MB -c work_mem=16MB -c effective_cache_size=512MB
```

---

### P17 — Frontend : pas de `React.memo` sur les composants lourds

Les composants UI comme `AnimatedList`, `Toast`, `SkeletonPatterns` ne sont pas wrappés avec `React.memo`. Chaque re-render du parent déclenche un re-render des enfants.

**Impact** : Faible en pratique grâce au lazy loading, mais perceptible sur les pages complexes (CohortPage, QualityPage).

---

## BASSE

### P18 — `AuditMiddleware` hérite de `BaseHTTPMiddleware`

`BaseHTTPMiddleware` bufferise les réponses avant de les renvoyer. Pour les endpoints SSE (analyse qualité avec streaming), cela peut introduire un délai de première réponse.

**Note** : Le middleware Keycloak utilise correctement un ASGI pur. L'audit devrait faire de même.

---

### P19 — Pas de `connection_timeout` configurable pour les pools OMOP

**Fichier** : `backend/db/omop_connector.py:126`

`connect_timeout=10` est hardcodé. Sur des réseaux lents, 10 secondes peuvent être insuffisants ; sur des réseaux rapides, c'est trop long pour un fail-fast.

---

### P20 — Requêtes de déduplication absentes dans les analyses concurrentes

Si deux utilisateurs lancent la même analyse (même CDM, même domaine) simultanément, les deux s'exécutent en parallèle au lieu de partager le résultat.

**Remédiation** : Implémenter un pattern single-flight avec fingerprint de requête.

---

### P21 — Pas de slow query logging configuré

Ni le PostgreSQL interne ni les connexions OMOP n'ont de `log_min_duration_statement` configuré. Les requêtes lentes passent inaperçues.

---

## Quick Wins (Effort faible, impact élevé)

| # | Action | Effort | Gain estimé |
|---|--------|--------|-------------|
| 1 | Ajouter pagination à `list_snapshots` (P1) | 15 min | Réponses 10-100x plus légères |
| 2 | Streaming réel pour export CSV (P3) | 30 min | -50% mémoire sur les exports |
| 3 | `manualChunks` dans Vite config (P8) | 15 min | -30% taille bundle initial |
| 4 | Nettoyer `_user_roles` vides (P10) | 5 min | Prévient fuite mémoire |
| 5 | `ANALYZE` sur tables temp pathways (P13) | 5 min | Plans d'exécution optimaux |
| 6 | Réduire intervalle evictor à 60s (P9) | 2 min | -40 connexions zombies |
