# OPAL API - Documentation Technique

**Version** : 1.0.0
**Base URL** : `http://<host>:8000/api`
**Authentification** : Keycloak (Bearer token) si `AUTH_ENABLED=true`

---

## Quick Start - Chargement des donnees

Apres un `docker compose up -d`, la BDD applicative est vide. Voici comment charger les donnees necessaires.

### 1. Enregistrer un CDM

```bash
curl --noproxy '*' -s -X POST "http://<host>:8000/api/cdm/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CHU_OMOP",
    "db_host": "10.0.0.1",
    "db_port": 5432,
    "db_name": "omop_prod",
    "db_user": "reader",
    "db_password": "secret",
    "omop_schema": "omop_cdm"
  }'
```

### 2. Tester la connexion

```bash
curl --noproxy '*' -s -X POST "http://<host>:8000/api/cdm/CHU_OMOP/test"
```

### 3. Charger les codebooks de reference (mapping)

Les codebooks enrichissent les suggestions de mapping avec des descriptions textuelles.

```bash
# CCAM EN (descriptions anglaises, 9500 codes)
curl --noproxy '*' -s -X POST "http://<host>:8000/api/mapping/reference/upload" \
  -F "name=CCAM_EN" \
  -F "domain=Procedure" \
  -F "file=@data/ccam_athena.csv"

# CCAM FR (descriptions francaises, 1969 codes)
curl --noproxy '*' -s -X POST "http://<host>:8000/api/mapping/reference/upload" \
  -F "name=CCAM" \
  -F "domain=Procedure" \
  -F "file=@data/interhop-actes-ameli.csv"
```

Le CSV doit avoir au minimum 2 colonnes. Le delimiteur (`,` ou `;`) est auto-detecte. Les colonnes code et description sont detectees automatiquement parmi : `code`, `ccam`, `code_ccam`, `code_cim`, `description`, `libelle`, `label`, etc. Sinon, les deux premieres colonnes sont utilisees.

### 4. Charger les mappings SapBERT pre-calcules

Les mappings SapBERT fournissent des suggestions instantanees basees sur des embeddings semantiques. Le fichier CSV est genere par `scripts/sapbert_mapping.py`.

```bash
curl --noproxy '*' -s -X POST "http://<host>:8000/api/mapping/sapbert/upload" \
  -F "domain=Procedure" \
  -F "file=@data/sapbert_results.csv"
```

**Format CSV attendu :**

| Colonne | Description |
|---------|-------------|
| `source_code` | Code source (ex: `FGLF671`) |
| `source_name` | Description source (ex: `Appendicectomie`) |
| `rank` | Rang de la suggestion (1 = meilleure) |
| `target_concept_id` | ID du concept OMOP cible |
| `target_concept_code` | Code du concept cible |
| `target_concept_name` | Nom du concept cible |
| `target_vocabulary_id` | Vocabulaire cible (ex: `SNOMED`) |
| `similarity` | Score de similarite (0.0 a 1.0) |

### 5. Lancer une analyse qualite

```bash
# Analyse complete (tous les domaines, avec progression SSE)
curl --noproxy '*' -s -X POST "http://<host>:8000/api/quality/analyze/batch" \
  -H "Content-Type: application/json" \
  -d '{"cdm_name": "CHU_OMOP", "domains": ["Dashboard", "Person", "Condition", "Drug", "Procedure"]}'
```

### 6. Verifier les donnees chargees

```bash
# Codebooks de reference charges
curl --noproxy '*' -s "http://<host>:8000/api/mapping/reference"

# Sets SapBERT charges
curl --noproxy '*' -s "http://<host>:8000/api/mapping/sapbert"

# Snapshots qualite disponibles
curl --noproxy '*' -s "http://<host>:8000/api/quality/snapshots/CHU_OMOP/Dashboard/latest"
```

---

## Table des matieres

1. [Health & System](#1-health--system)
2. [CDM Management](#2-cdm-management)
3. [Quality Analysis](#3-quality-analysis)
4. [Cohort Builder](#4-cohort-builder)
5. [Mapping](#5-mapping)
6. [Concept Explorer](#6-concept-explorer)
7. [OHDSI Integration](#7-ohdsi-integration)
8. [Modeles de donnees](#8-modeles-de-donnees)
9. [Configuration](#9-configuration)

---

## 1. Health & System

### `GET /api/health`

Health check.

**Response :**
```json
{ "status": "ok", "service": "opal-backend" }
```

### `GET /api/i18n/{lang}`

Retourne les traductions pour une langue (`en` ou `fr`).

| Param | Type | Description |
|-------|------|-------------|
| `lang` | path, string | Code langue : `en`, `fr` |

**Response :** Objet JSON clef/valeur des traductions.

### `GET /api/auth/me`

Retourne l'utilisateur courant (depuis le token Keycloak).

**Response :**
```json
{
  "username": "admin",
  "email": "admin@example.com",
  "roles": ["admin"]
}
```

**Erreur :** `401` si non authentifie.

### `GET /api/audit/logs`

Retourne les logs d'audit (admin uniquement).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | query, string | aujourd'hui | Date ISO (YYYY-MM-DD) |
| `user` | query, string | - | Filtrer par username |
| `limit` | query, int | 200 | Nombre max d'entrees |

**Response :**
```json
{
  "date": "2026-03-06",
  "entries": [
    {
      "timestamp": "2026-03-06T10:30:00",
      "user": "admin",
      "method": "POST",
      "path": "/api/quality/analyze",
      "status": 200
    }
  ]
}
```

---

## 2. CDM Management

Prefix : `/api/cdm`

### `GET /api/cdm/`

Liste toutes les connexions CDM enregistrees.

**Response :**
```json
{
  "cdms": [
    {
      "id": 1,
      "name": "CHU_OMOP",
      "db_host": "10.0.0.1",
      "db_port": 5432,
      "db_name": "omop_prod",
      "db_user": "reader",
      "omop_schema": "omop_cdm",
      "created_at": "2026-01-15T10:00:00"
    }
  ]
}
```

### `POST /api/cdm/`

Enregistre une nouvelle connexion CDM.

**Body :**
```json
{
  "name": "CHU_OMOP",
  "db_host": "10.0.0.1",
  "db_port": 5432,
  "db_name": "omop_prod",
  "db_user": "reader",
  "db_password": "secret",
  "omop_schema": "omop_cdm"
}
```

| Champ | Type | Requis | Default | Description |
|-------|------|--------|---------|-------------|
| `name` | string | oui | - | Nom unique du CDM |
| `db_host` | string | oui | - | Hote PostgreSQL |
| `db_port` | int | non | 5432 | Port |
| `db_name` | string | oui | - | Nom de la base |
| `db_user` | string | oui | - | Utilisateur |
| `db_password` | string | oui | - | Mot de passe (chiffre Fernet au stockage) |
| `omop_schema` | string | non | `omop_cdm` | Schema OMOP |

**Response :** `{ "id": 1, "name": "CHU_OMOP", "message": "..." }`
**Erreur :** `409` si le nom existe deja.

### `POST /api/cdm/test`

Teste une connexion CDM sans la sauvegarder.

**Body :**
```json
{
  "db_host": "10.0.0.1",
  "db_port": 5432,
  "db_name": "omop_prod",
  "db_user": "reader",
  "db_password": "secret"
}
```

**Response :** `{ "success": true, "message": "...", "person_count": 150000 }`
**Erreur :** `502` si connexion echouee.

### `POST /api/cdm/{cdm_name}/test`

Teste la connexion d'un CDM deja enregistre.

### `PUT /api/cdm/{cdm_name}`

Met a jour une connexion CDM. Tous les champs sont optionnels.

**Body :**
```json
{
  "db_host": "10.0.0.2",
  "db_password": "new_secret"
}
```

### `DELETE /api/cdm/{cdm_name}`

Supprime une connexion CDM.

### `GET /api/cdm/{cdm_name}/settings`

Retourne les parametres d'analyse pour un CDM.

**Response :**
```json
{
  "cdm_name": "CHU_OMOP",
  "omop_schema": "omop_cdm",
  "top_unmapped_terms": 50,
  "top_concepts": 50,
  "max_records_per_person": 100,
  "max_observation_months": 120,
  "comparison_alert_threshold": 5.0
}
```

### `PUT /api/cdm/{cdm_name}/settings`

Met a jour les parametres d'analyse. Tous les champs sont optionnels.

**Body :**
```json
{
  "top_unmapped_terms": 100,
  "comparison_alert_threshold": 10.0
}
```

---

## 3. Quality Analysis

Prefix : `/api/quality`

### `GET /api/quality/domains`

Liste les domaines d'analyse disponibles.

**Response :**
```json
{
  "domains": ["Dashboard", "Person", "ObservationPeriod", "Condition", "Drug", "Measurement", "Observation", "Procedure", "Visit", "Device", "Death"]
}
```

### `POST /api/quality/analyze`

Lance l'analyse d'un domaine unique. Sauvegarde automatiquement un snapshot versionne.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Condition"
}
```

**Response :**
```json
{
  "snapshot_id": 42,
  "version": 3,
  "domain": "Condition",
  "cdm_name": "CHU_OMOP",
  "results": {
    "domain": "Condition",
    "achilles_like": { "global": { "total_rows": 500000, "distinct_persons": 12000 }, "top_concepts": [...] },
    "mapping": { "terms": { "total_terms": 200, "mapped_terms": 150, "pct_terms_mapped": 75.0 }, "rows": {...}, "top_unmapped_terms": [...] }
  }
}
```

### `POST /api/quality/analyze/batch`

Lance l'analyse de plusieurs domaines. Retourne un resume synchrone.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domains": ["Dashboard", "Person", "Condition", "Drug"]
}
```

**Response :**
```json
{
  "cdm_name": "CHU_OMOP",
  "completed": [{ "domain": "Dashboard", "snapshot_id": 43, "version": 1, "status": "success" }],
  "errors": [],
  "total": 4,
  "success_count": 4,
  "error_count": 0
}
```

### `POST /api/quality/analyze/batch/stream`

Identique a `/analyze/batch` mais retourne un flux **SSE** (Server-Sent Events) pour suivre la progression en temps reel.

**Content-Type :** `text/event-stream`

**Events :**
```
data: {"type": "progress", "domain": "Condition", "status": "running", "completed": 0, "total": 4}
data: {"type": "progress", "domain": "Condition", "status": "success", "completed": 1, "total": 4}
data: {"type": "done", "completed": 4, "total": 4}
```

### `GET /api/quality/snapshots/{cdm_name}/{domain}`

Liste tous les snapshots pour un couple CDM/domaine.

**Response :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Condition",
  "snapshots": [
    { "id": 42, "version": 3, "created_at": "2026-03-06T10:00:00" },
    { "id": 30, "version": 2, "created_at": "2026-02-15T14:00:00" }
  ]
}
```

### `GET /api/quality/snapshots/{cdm_name}/{domain}/latest`

Retourne le dernier snapshot (avec les resultats complets).

### `GET /api/quality/snapshots/by-id/{snapshot_id}`

Retourne un snapshot specifique par son ID.

### `GET /api/quality/export/{snapshot_id}/{table_type}`

Exporte une table d'un snapshot en CSV.

| Param | Type | Description |
|-------|------|-------------|
| `snapshot_id` | path, int | ID du snapshot |
| `table_type` | path, string | Type de table a exporter |

**Valeurs de `table_type` :**

| Valeur | Description | Colonnes |
|--------|-------------|----------|
| `top_concepts` | Top concepts du domaine | concept_id, concept_name, source_value, n_records, n_persons |
| `top_unmapped` | Termes non mappes | source_value, [source_name], count |
| `domain_stats` | Stats par domaine (Dashboard) | domain, total_records, distinct_persons, pct_persons, total_terms, mapped_terms, unmapped_terms, pct_terms_mapped |
| `age_by_gender` | Distribution age par genre | gender_name, n, mean_age, p10, p25, median_age, p75, p90 |
| `duration_by_gender` | Duree observation par genre | gender_name, n, mean_months, p10, p25, median_months, p75, p90 |

**Response :** Fichier CSV (`Content-Disposition: attachment`).

### `GET /api/quality/timeline/{cdm_name}`

Evolution des KPIs a travers les versions de snapshots.

| Param | Type | Description |
|-------|------|-------------|
| `domain` | query, string, optional | Filtrer sur un domaine |

**Response :**
```json
{
  "cdm_name": "CHU_OMOP",
  "timelines": {
    "Condition": [
      { "snapshot_id": 30, "version": 2, "created_at": "...", "total_records": 500000, "pct_terms_mapped": 75.0 }
    ]
  }
}
```

### `POST /api/quality/compare`

Compare deux CDMs ou deux snapshots pour un domaine.

**Body :**
```json
{
  "cdm_name_a": "CHU_OMOP",
  "cdm_name_b": "CHU_TEST",
  "domain": "Condition",
  "snapshot_id_a": null,
  "snapshot_id_b": null
}
```

Si `snapshot_id_a/b` sont `null`, utilise le dernier snapshot de chaque CDM.

**Response :**
```json
{
  "domain": "Condition",
  "diffs": [{ "metric": "total_records", "value_a": 500000, "value_b": 480000, "diff_pct": -4.0 }],
  "alerts": [{ "metric": "...", "diff_pct": 15.0, "severity": "warning" }],
  "threshold": 5.0,
  "snapshot_a": { "id": 42, "cdm_name": "CHU_OMOP", "version": 3 },
  "snapshot_b": { "id": 38, "cdm_name": "CHU_TEST", "version": 2 },
  "results_a": { ... },
  "results_b": { ... }
}
```

### `GET /api/quality/report/{cdm_name}`

Genere un rapport HTML qualite complet (tous les domaines).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `lang` | query, string | `en` | Langue du rapport (`en`, `fr`) |

**Response :** Fichier HTML (`Content-Disposition: attachment`).

### `GET /api/quality/report/comparison`

Genere un rapport HTML de comparaison entre deux CDMs.

| Param | Type | Description |
|-------|------|-------------|
| `cdm_name_a` | query, string | Premier CDM |
| `cdm_name_b` | query, string | Second CDM |
| `domain` | query, string, optional | Domaine specifique (sinon tous) |
| `lang` | query, string | Langue (`en`, `fr`) |

**Response :** Fichier HTML.

---

## 4. Cohort Builder

Prefix : `/api/cohorts`

### `GET /api/cohorts/domains`

Liste les domaines OMOP disponibles pour les criteres de cohorte.

**Response :**
```json
{
  "domains": [
    { "name": "Condition", "table": "condition_occurrence" },
    { "name": "Drug", "table": "drug_exposure" },
    { "name": "Procedure", "table": "procedure_occurrence" }
  ]
}
```

### `POST /api/cohorts/concepts/search`

Recherche de concepts OMOP par nom ou code.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "query": "diabetes",
  "domain": "Condition",
  "vocabulary_id": null,
  "limit": 30
}
```

**Response :**
```json
{
  "concepts": [
    {
      "concept_id": 201826,
      "concept_name": "Type 2 diabetes mellitus",
      "concept_code": "44054006",
      "domain_id": "Condition",
      "vocabulary_id": "SNOMED",
      "concept_class_id": "Clinical Finding",
      "standard_concept": "S"
    }
  ],
  "count": 15
}
```

### `GET /api/cohorts/concepts/vocabularies`

Liste les vocabulaires disponibles dans le CDM.

| Param | Type | Description |
|-------|------|-------------|
| `cdm_name` | query, string | Nom du CDM |

### `GET /api/cohorts/`

Liste toutes les cohortes sauvegardees.

| Param | Type | Description |
|-------|------|-------------|
| `cdm_name` | query, string, optional | Filtrer par CDM |

**Response :**
```json
{
  "cohorts": [
    {
      "id": 1,
      "cdm_name": "CHU_OMOP",
      "name": "Diabetiques T2",
      "description": "Patients avec diagnostic de diabete de type 2",
      "created_at": "2026-03-01T10:00:00",
      "updated_at": "2026-03-05T14:00:00",
      "latest_version": 3,
      "patient_count": 1250
    }
  ]
}
```

### `POST /api/cohorts/`

Cree une nouvelle cohorte avec des criteres initiaux.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "name": "Diabetiques T2",
  "description": "...",
  "criteria": {
    "inclusion": {
      "criteria": [
        {
          "id": "abc123",
          "domain": "Condition",
          "concepts": [{ "concept_id": 201826, "concept_name": "Type 2 diabetes mellitus" }],
          "include_descendants": true,
          "source_codes": [],
          "temporal": { "type": "any_time" },
          "occurrence": { "type": "any", "count": 1 },
          "operatorWithNext": "AND"
        }
      ]
    },
    "exclusion": { "criteria": [] }
  }
}
```

**Structure des criteres :**

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | Identifiant unique du critere |
| `domain` | string | Domaine OMOP (Condition, Drug, Procedure...) |
| `concepts` | array | Liste de concepts `{concept_id, concept_name}` |
| `include_descendants` | bool | Inclure les descendants via `concept_ancestor` (default: true) |
| `source_codes` | array | Codes source directs (ex: `["E11.9", "FGLF671"]`) |
| `temporal.type` | string | `any_time`, `before`, `after`, `between` |
| `occurrence.type` | string | `any`, `at_least`, `exactly` |
| `occurrence.count` | int | Nombre d'occurrences |
| `operatorWithNext` | string | `AND` ou `OR` — operateur avec le critere suivant |
| `sameVisit` | bool | JOIN sur `visit_occurrence_id` pour les criteres AND |

**Logique SQL :** Les criteres consecutifs en `OR` sont groupes en `UNION`, les groupes `AND` sont combines par `INTERSECT`.

**Response :**
```json
{ "id": 1, "name": "Diabetiques T2", "version": 1, "generated_sql": "SELECT DISTINCT..." }
```

### `GET /api/cohorts/{cohort_id}`

Details d'une cohorte avec toutes ses versions.

### `PUT /api/cohorts/{cohort_id}`

Met a jour une cohorte. Si les criteres changent, cree une nouvelle version.

### `DELETE /api/cohorts/{cohort_id}`

Supprime une cohorte (admin/omop-dim uniquement).

### `POST /api/cohorts/count`

Execute les criteres et retourne le nombre de patients.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "criteria": { ... }
}
```

**Response :**
```json
{ "patient_count": 1250, "sql": "SELECT COUNT(DISTINCT person_id)..." }
```

### `POST /api/cohorts/count/approximate`

Comptage rapide (identique au count exact pour l'instant, TABLESAMPLE prevu).

### `POST /api/cohorts/attrition`

Analyse d'attrition : execute chaque critere incrementalement.

**Body :** Identique a `/count`.

**Response :**
```json
{
  "steps": [
    { "step": 1, "label": "Condition: Type 2 diabetes mellitus", "count": 5000 },
    { "step": 2, "label": "Drug: Metformin", "count": 3200 },
    { "step": 3, "label": "After exclusions", "count": 2800 }
  ]
}
```

### `POST /api/cohorts/sample`

Retourne un echantillon aleatoire de patients.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "criteria": { ... },
  "limit": 10
}
```

**Response :**
```json
{
  "patients": [
    {
      "person_id": 12345,
      "year_of_birth": 1965,
      "gender": "FEMALE",
      "race": "Unknown",
      "observation_period_start_date": "2015-01-01",
      "observation_period_end_date": "2024-12-31"
    }
  ],
  "count": 10
}
```

### `POST /api/cohorts/export/direct`

Exporte la liste complete des patients en CSV (sans sauvegarder la cohorte).

**Body :** Identique a `/count`.

**Response :** Fichier CSV avec colonnes : `person_id, year_of_birth, gender, race, observation_period_start_date, observation_period_end_date`.

### `POST /api/cohorts/{cohort_id}/execute`

Execute la derniere version d'une cohorte sauvegardee et enregistre le `patient_count`.

### `GET /api/cohorts/{cohort_id}/export`

Exporte une cohorte sauvegardee.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | query, string | `csv` | `csv` (person_ids) ou `sql` (requete SQL generee) |

---

## 5. Mapping

Prefix : `/api/mapping`

### 5.1 Dashboard

#### `GET /api/mapping/dashboard/{cdm_name}`

Taux de mapping par domaine avec compteurs.

**Response :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domains": [
    {
      "domain": "Condition",
      "total_terms": 200,
      "mapped_terms": 150,
      "unmapped_terms": 50,
      "pct_terms_mapped": 75.0,
      "total_rows": 500000,
      "mapped_rows": 450000,
      "unmapped_rows": 50000,
      "pct_rows_mapped": 90.0,
      "version": 3,
      "snapshot_date": "2026-03-06T10:00:00"
    }
  ],
  "decisions_summary": { "approved": 45, "modified": 3, "rejected": 12 }
}
```

#### `GET /api/mapping/dashboard/{cdm_name}/evolution`

Evolution du taux de mapping a travers les versions.

| Param | Type | Description |
|-------|------|-------------|
| `domain` | query, string | Domaine |

### 5.2 Unmapped Exploration

#### `GET /api/mapping/unmapped/{cdm_name}/{domain}`

Liste paginee des termes source non mappes, requetee directement depuis le CDM.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | query, int | 1 | Page |
| `page_size` | query, int | 50 | Taille de page (max 500) |
| `search` | query, string | - | Filtrer par code ou label |

**Response :**
```json
{
  "domain": "Procedure",
  "total": 450,
  "page": 1,
  "page_size": 50,
  "total_pages": 9,
  "items": [
    {
      "source_value": "FGLF671",
      "source_name": "Appendicectomie",
      "n_records": 1200,
      "n_persons": 950
    }
  ]
}
```

#### `GET /api/mapping/unmapped/{cdm_name}/{domain}/export`

Exporte tous les termes non mappes en CSV.

### 5.3 Auto-Suggestion

#### `POST /api/mapping/suggest`

Suggestions de mapping pour un terme source unique.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Procedure",
  "source_value": "FGLF671",
  "source_name": "Appendicectomie"
}
```

**Strategies de suggestion (par ordre de priorite) :**

| Strategie | Description |
|-----------|-------------|
| `sapbert` | Pre-calcule par SapBERT (embeddings semantiques). Instantane. |
| `exact` | Correspondance exacte dans `concept.concept_name` ou `concept_code` |
| `relationship` | Concepts lies via `concept_relationship` |
| `keyword` | Recherche progressive par mots-cles AND |
| `fuzzy` | Recherche floue par trigrammes (`pg_trgm`) |
| `contextual` | Recherche dans le meme domaine avec scoring par forme/marque (Drug) |

**Response :**
```json
{
  "source_value": "FGLF671",
  "suggestions": [
    {
      "concept_id": 4097430,
      "concept_name": "Appendectomy",
      "concept_code": "80146002",
      "vocabulary_id": "SNOMED",
      "domain_id": "Procedure",
      "standard_concept": "S",
      "confidence": 92,
      "source": "sapbert"
    }
  ]
}
```

#### `POST /api/mapping/suggest/batch`

Suggestions pour les top N termes non mappes d'un domaine.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Procedure",
  "limit": 20,
  "enable_fuzzy": true,
  "enable_keyword": true,
  "enable_contextual": true,
  "enable_sapbert": true
}
```

Les termes deja approuves/rejetes sont automatiquement exclus.
Les termes avec des resultats SapBERT ne passent pas par les strategies SQL (performance).

**Response :**
```json
{
  "domain": "Procedure",
  "results": [
    {
      "source_value": "FGLF671",
      "source_name": "Appendicectomie",
      "suggestions": [...]
    }
  ]
}
```

### 5.4 Validation Workflow

#### `POST /api/mapping/decide`

Enregistre une decision de mapping (approuver, modifier, rejeter).

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Procedure",
  "source_value": "FGLF671",
  "source_name": "Appendicectomie",
  "action": "approved",
  "target_concept_id": 4097430,
  "target_concept_name": "Appendectomy",
  "target_vocabulary_id": "SNOMED",
  "suggestion_source": "sapbert",
  "confidence_score": 92.0,
  "reason": "Correspondance exacte validee"
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `action` | string | `approved`, `modified`, ou `rejected` |
| `reason` | string | Raison (optionnelle, affichee dans l'historique) |
| `target_concept_id` | int, null | Concept cible (null si rejected) |

#### `POST /api/mapping/decide/bulk`

Decision en masse (approuver ou rejeter au-dessus d'un seuil de confiance).

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Procedure",
  "action": "approved",
  "min_confidence": 80.0,
  "source_values": ["FGLF671", "HBFA003"]
}
```

### 5.5 Apply Mapping

#### `POST /api/mapping/apply`

Genere les entrees `source_to_concept_map` a partir des decisions approuvees.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "domain": "Procedure",
  "write_to_cdm": false
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `write_to_cdm` | bool | Si `true`, ecrit directement dans la table `source_to_concept_map` du CDM (UPSERT) |

**Response :**
```json
{
  "count": 45,
  "written_to_cdm": false,
  "rows": [
    {
      "source_code": "FGLF671",
      "source_concept_id": 0,
      "source_vocabulary_id": "OPAL_Procedure",
      "source_code_description": "Appendicectomie",
      "target_concept_id": 4097430,
      "target_vocabulary_id": "SNOMED",
      "valid_start_date": "1970-01-01",
      "valid_end_date": "2099-12-31",
      "invalid_reason": null
    }
  ]
}
```

#### `POST /api/mapping/apply/preview`

Previsualise l'impact avant application (nombre de lignes/patients concernes).

**Response :**
```json
{
  "total_decisions": 45,
  "impacted_rows": 25000,
  "impacted_persons": 8000
}
```

#### `GET /api/mapping/apply/export/{cdm_name}/{domain}`

Exporte les mappings approuves au format CSV `source_to_concept_map`.

### 5.6 History & Audit

#### `GET /api/mapping/history/{cdm_name}`

Historique pagine des decisions de mapping.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `domain` | query, string | - | Filtrer par domaine |
| `action` | query, string | - | Filtrer par action (`approved`, `modified`, `rejected`, `rolled_back`) |
| `page` | query, int | 1 | Page |
| `page_size` | query, int | 50 | Taille (max 200) |

**Response :**
```json
{
  "total": 60,
  "page": 1,
  "page_size": 50,
  "total_pages": 2,
  "items": [
    {
      "id": 1,
      "domain": "Procedure",
      "source_value": "FGLF671",
      "source_name": "Appendicectomie",
      "action": "approved",
      "target_concept_id": 4097430,
      "target_concept_name": "Appendectomy",
      "target_vocabulary_id": "SNOMED",
      "previous_concept_id": null,
      "suggestion_source": "sapbert",
      "confidence_score": 92.0,
      "user": "admin",
      "reason": "Correspondance exacte",
      "created_at": "2026-03-06T10:30:00"
    }
  ]
}
```

#### `POST /api/mapping/history/{decision_id}/rollback`

Annule une decision de mapping. Cree une entree `rolled_back` et supprime l'originale.

#### `GET /api/mapping/history/{cdm_name}/export`

Exporte l'historique complet en CSV.

### 5.7 Reference Codebooks

#### `POST /api/mapping/reference/upload`

Upload d'un codebook de reference CSV (CCAM, CIM-10...).

**Content-Type :** `multipart/form-data`

| Champ | Type | Description |
|-------|------|-------------|
| `name` | form, string | Nom du codebook (ex: `CCAM`, `CIM-10`) |
| `domain` | form, string | Domaine associe (ex: `Procedure`, `Condition`) |
| `file` | form, file | Fichier CSV |

Le CSV est auto-detecte (delimiteur `,` ou `;`, colonnes code/description). Les entrees existantes pour ce nom sont remplacees.

**Response :**
```json
{ "name": "CCAM", "domain": "Procedure", "count": 9500 }
```

#### `GET /api/mapping/reference`

Liste les codebooks charges.

#### `DELETE /api/mapping/reference/{name}`

Supprime un codebook.

### 5.8 SapBERT Pre-computed Mappings

#### `POST /api/mapping/sapbert/upload`

Upload des resultats SapBERT pre-calcules (CSV genere par `scripts/sapbert_mapping.py`).

**Content-Type :** `multipart/form-data`

| Champ | Type | Description |
|-------|------|-------------|
| `domain` | form, string | Domaine (ex: `Procedure`) |
| `file` | form, file | CSV avec colonnes: `source_code, source_name, rank, target_concept_id, target_concept_code, target_concept_name, target_vocabulary_id, similarity` |

Les entrees existantes pour ce domaine sont remplacees.

**Response :**
```json
{ "domain": "Procedure", "count": 47500 }
```

#### `GET /api/mapping/sapbert`

Liste les sets SapBERT charges.

**Response :**
```json
{
  "sapbert_sets": [
    { "domain": "Procedure", "count": 47500, "source_count": 9500, "uploaded_at": "2026-03-04T16:33:00" }
  ]
}
```

#### `DELETE /api/mapping/sapbert/{domain}`

Supprime les mappings SapBERT d'un domaine.

---

## 6. Concept Explorer

Prefix : `/api/concepts`

### `GET /api/concepts/search`

Recherche de concepts par nom, code ou ID.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `cdm_name` | query, string | - | Nom du CDM (requis) |
| `q` | query, string | - | Terme de recherche (texte ou concept_id numerique) |
| `domain` | query, string | - | Filtrer par domaine |
| `vocabulary` | query, string | - | Filtrer par vocabulaire |
| `standard_only` | query, bool | false | Uniquement les concepts standard |
| `limit` | query, int | 50 | Limite (max 200) |
| `offset` | query, int | 0 | Offset pour pagination |

**Response :**
```json
{
  "concepts": [
    {
      "concept_id": 201826,
      "concept_name": "Type 2 diabetes mellitus",
      "concept_code": "44054006",
      "domain_id": "Condition",
      "vocabulary_id": "SNOMED",
      "concept_class_id": "Clinical Finding",
      "standard_concept": "S",
      "valid_start_date": "1970-01-01",
      "valid_end_date": "2099-12-31",
      "invalid_reason": null
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/concepts/details/{concept_id}`

Details complets d'un concept : relations, synonymes.

| Param | Type | Description |
|-------|------|-------------|
| `cdm_name` | query, string | Nom du CDM |

**Response :**
```json
{
  "concept": { "concept_id": 201826, "concept_name": "...", ... },
  "relationships": [
    {
      "relationship_id": "Maps to",
      "related_concept_id": 201826,
      "related_concept_name": "Type 2 diabetes mellitus",
      "related_vocabulary_id": "SNOMED",
      "related_concept_class_id": "Clinical Finding",
      "related_standard_concept": "S"
    }
  ],
  "synonyms": [
    { "concept_synonym_name": "Diabetes mellitus type II", "language_concept_id": 4180186 }
  ]
}
```

### `GET /api/concepts/hierarchy/{concept_id}`

Ancetres et descendants via la table `concept_ancestor`.

**Response :**
```json
{
  "concept_id": 201826,
  "ancestors": [
    {
      "concept_id": 4008576,
      "concept_name": "Endocrine disease",
      "concept_code": "362969004",
      "vocabulary_id": "SNOMED",
      "min_levels_of_separation": 2,
      "max_levels_of_separation": 4
    }
  ],
  "descendants": [
    {
      "concept_id": 4193704,
      "concept_name": "Type 2 diabetes mellitus without complication",
      "min_levels_of_separation": 1,
      "max_levels_of_separation": 1
    }
  ]
}
```

### `GET /api/concepts/source-values/{concept_id}`

Trouve les valeurs source dans les tables cliniques mappees vers ce concept.

**Response :**
```json
{
  "concept_id": 201826,
  "source_values": [
    { "domain": "Condition", "source_value": "E11.9", "n_records": 5000, "n_persons": 3200 }
  ]
}
```

### `GET /api/concepts/search-source-value`

Recherche dans les tables cliniques par code source OU label (quand disponible).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `cdm_name` | query, string | - | Nom du CDM |
| `q` | query, string | - | Recherche (code ou label, ex: `HYDROXYZINE` ou `N3412`) |
| `domain` | query, string | - | Filtrer par domaine |
| `limit` | query, int | 50 | Limite (max 200) |
| `offset` | query, int | 0 | Offset |

Recherche dans `source_value` ET `source_name` (pour Drug et Measurement qui ont une colonne `source_name` dans le CDM).

**Response :**
```json
{
  "results": [
    {
      "domain": "Drug",
      "source_value": "9001497",
      "source_name": "HYDROXYZINE 25MG CPR",
      "n_records": 850,
      "n_persons": 420,
      "mapped_concept_id": 0,
      "mapped_concept_name": null,
      "mapped_vocabulary_id": null,
      "mapped_standard_concept": null
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/concepts/search-source-value/export`

Exporte les resultats de recherche source en CSV.

### `POST /api/concepts/counts`

Compteurs (records/persons) pour une liste de concept_ids a travers toutes les tables cliniques.

**Body :**
```json
{ "concept_ids": [201826, 4097430, 1332419] }
```

| Param | Type | Description |
|-------|------|-------------|
| `cdm_name` | query, string | Nom du CDM |

**Response :**
```json
{
  "counts": {
    "201826": { "n_records": 5000, "n_persons": 3200 },
    "4097430": { "n_records": 0, "n_persons": 0 }
  }
}
```

Maximum 200 concept_ids par requete.

### `GET /api/concepts/domains`

Liste les `domain_id` distincts de la table `concept`.

### `GET /api/concepts/vocabularies`

Liste les `vocabulary_id` distincts de la table `concept`.

---

## 7. OHDSI Integration

Prefix : `/api/ohdsi`

Lance des conteneurs Docker OHDSI (Achilles, DQD, CDM Onboarding) et streame leurs logs.

### Services disponibles

| Service | Description | Image Docker |
|---------|-------------|-------------|
| `achilles` | Characterization (Achilles) | `ohdsi-docker-achilles` |
| `achilles-export` | Export Achilles Results | `ohdsi-docker-achilles-export` |
| `dqd` | Data Quality Dashboard | `ohdsi-docker-dqd` |
| `cdmonboarding` | CDM Onboarding Report | `ohdsi-docker-cdmonboarding` |

### `POST /api/ohdsi/run/{service_name}`

Lance un service OHDSI.

**Body :**
```json
{
  "cdm_name": "CHU_OMOP",
  "results_schema": "omop_cdm",
  "vocabulary_schema": "omop_cdm",
  "cdm_version": "5.4",
  "cdm_source_name": ""
}
```

**Response :** `{ "ok": true }`
**Erreur :** `409` si deja en cours.

### `POST /api/ohdsi/stop/{service_name}`

Arrete un service OHDSI en cours.

### `GET /api/ohdsi/status`

Statut de tous les services.

**Response :**
```json
{
  "achilles": { "status": "done", "log_count": 250 },
  "dqd": { "status": "idle", "log_count": 0 },
  "achilles-export": { "status": "running", "log_count": 42 },
  "cdmonboarding": { "status": "idle", "log_count": 0 }
}
```

Valeurs de `status` : `idle`, `running`, `done`, `error`.

### `GET /api/ohdsi/logs/{service_name}`

Flux SSE des logs en temps reel.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | query, int | 0 | Reprendre depuis cette position |

**Content-Type :** `text/event-stream`

```
data: {"status": "running", "lines": ["[INFO] Starting Achilles..."], "offset": 1}
data: {"status": "done", "lines": [], "offset": 250}
```

### `GET /api/ohdsi/logs/{service_name}/history`

Retourne tous les logs accumules (pour rechargement de page).

### `GET /api/ohdsi/files/{path}`

Browse et telecharge les fichiers de sortie OHDSI.

- Si `path` est un dossier : retourne la liste des fichiers.
- Si `path` est un fichier : retourne le fichier en telechargement.

---

## 8. Modeles de donnees

### Tables de la BDD applicative (`opal`)

| Table | Description |
|-------|-------------|
| `cdm_configs` | Connexions CDM enregistrees (mot de passe chiffre Fernet) |
| `analysis_snapshots` | Snapshots d'analyse versionnees (resultats JSON) |
| `analysis_settings` | Parametres d'analyse par CDM |
| `cohorts` | Definitions de cohortes |
| `cohort_versions` | Versions des criteres de cohorte (criteres JSON + SQL genere) |
| `mapping_decisions` | Decisions de mapping (audit trail complet) |
| `reference_codebooks` | Codebooks de reference (CCAM, CIM-10...) |
| `sapbert_mappings` | Mappings SapBERT pre-calcules |

### Domaines OMOP supportes

| Domaine | Table CDM | Colonne concept_id | Colonne source_value | Colonne source_name |
|---------|-----------|---------------------|----------------------|---------------------|
| Condition | condition_occurrence | condition_concept_id | condition_source_value | - |
| Drug | drug_exposure | drug_concept_id | drug_source_value | drug_source_name |
| Measurement | measurement | measurement_concept_id | measurement_source_value | measurement_source_name |
| Observation | observation | observation_concept_id | observation_source_value | - |
| Procedure | procedure_occurrence | procedure_concept_id | procedure_source_value | - |
| Visit | visit_occurrence | visit_concept_id | visit_source_value | - |
| Device | device_exposure | device_concept_id | device_source_value | - |
| Death | death | cause_concept_id | cause_source_value | - |

---

## 9. Configuration

### Variables d'environnement

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://opal:opal@opal-db:5432/opal` | URL PostgreSQL de la BDD applicative |
| `SECRET_KEY` | `change-me-in-production` | Cle pour le chiffrement Fernet des mots de passe CDM |
| `AUTH_ENABLED` | `false` | Active l'authentification Keycloak |
| `KEYCLOAK_URL` | `http://keycloak:8080` | URL interne Keycloak |
| `KEYCLOAK_REALM` | `opal` | Realm Keycloak |
| `KEYCLOAK_CLIENT_ID` | `opal-frontend` | Client ID Keycloak |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Origines CORS autorisees (separees par virgule) |

### Roles Keycloak

| Role | Acces |
|------|-------|
| `admin` | Acces complet + audit logs + suppression |
| `omop-dim` | Quality, Cohort, Mapping, Concepts, OHDSI |
| `chercheur` | Quality, Cohort, Concepts |
| `medecin` | Mapping, Cohort, Concepts |

### Codes d'erreur HTTP

| Code | Signification |
|------|---------------|
| `400` | Requete invalide (domaine inconnu, criteres malformes...) |
| `401` | Non authentifie |
| `403` | Acces refuse (role insuffisant) |
| `404` | Ressource non trouvee (CDM, snapshot, cohorte...) |
| `409` | Conflit (CDM existe deja, service deja en cours...) |
| `500` | Erreur interne (query SQL echouee, analyse echouee...) |
| `502` | Connexion au CDM externe echouee |
