# Plan d'amélioration OPAL — Combler le delta Atlas

> Contrainte : pas de drug_era / condition_era dans nos CDM.
> Toutes les features s'appuient sur les tables existantes (observation_period, *_occurrence, concept_ancestor, concept_relationship).

---

## P0-1 : Concept Sets (groupes de concepts réutilisables)

**Pourquoi** : Prérequis pour toutes les autres features. Aujourd'hui chaque critère de cohorte re-sélectionne ses concepts à la main. Atlas en fait la brique de base.

### Backend

**Nouveau modèle** (`db/models.py`) :
```python
class ConceptSet(Base):
    __tablename__ = "concept_sets"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    cdm_name = Column(String, index=True, nullable=False)
    domain = Column(String, nullable=True)          # optionnel, pour filtrer
    description = Column(String, nullable=True)
    concepts_json = Column(Text, nullable=False)     # [{concept_id, concept_name, concept_code, vocabulary_id, include_descendants: bool}]
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

**Nouveau router** (`modules/concept_set/router.py`) :
- `POST /api/concept-sets/` — Créer un concept set
- `GET /api/concept-sets/` — Lister (filtre cdm_name, domain)
- `GET /api/concept-sets/{id}` — Détail avec résolution des descendants
- `PUT /api/concept-sets/{id}` — Modifier
- `DELETE /api/concept-sets/{id}` — Supprimer
- `GET /api/concept-sets/{id}/resolve` — Résoudre : retourne la liste complète des concept_id (avec descendants si demandé), en requêtant concept_ancestor sur le CDM cible
- `POST /api/concept-sets/{id}/counts` — Nombre de records et patients pour chaque concept du set

**Intégration au cohort builder** (`modules/cohort/sql_builder.py`) :
- Ajouter un champ optionnel `concept_set_id` sur `CohortCriterion` (en plus de `concepts[]`)
- Dans `_build_concept_filter()` (ligne ~640) : si `concept_set_id` présent, charger les concepts depuis la DB app et les injecter comme si c'était `concepts[]`

### Frontend

- Nouvelle page `ConceptSetPage.tsx` : CRUD avec recherche de concepts (réutiliser le composant de recherche existant de `CriteriaPanel.tsx`)
- Dans `CriteriaPanel.tsx` : ajouter un sélecteur "Choisir un Concept Set" en alternative à la sélection manuelle
- Type `ConceptSet` dans `types/index.ts`

### Estimation d'effort
~3-4 jours dev

---

## P0-2 : Incidence Rates (taux d'incidence)

**Pourquoi** : Métrique épidémiologique fondamentale. Calculable directement depuis observation_period + les tables *_occurrence existantes, sans eras.

### Backend

**Nouveau module** (`modules/incidence/`) :

**`router.py`** — Endpoints :
- `POST /api/incidence/compute` — Calcul d'incidence
- `POST /api/incidence/save` — Sauvegarder une analyse
- `GET /api/incidence/` — Lister les analyses sauvegardées
- `GET /api/incidence/{id}` — Résultat détaillé

**`engine.py`** — Moteur de calcul :

Input :
```python
class IncidenceRequest(BaseModel):
    cdm_name: str
    target_cohort_id: int           # Population à risque (cohorte OPAL existante)
    outcome_cohort_id: int          # Événement d'intérêt (cohorte OPAL existante)
    time_at_risk_start: int = 0     # Jours après index (0 = index date)
    time_at_risk_end: str = "observation_end"  # "observation_end" | int (jours)
    strata: list[str] = []          # ["age_group", "gender", "year"]
    age_groups: list[dict] = [{"min": 0, "max": 17, "label": "0-17"}, ...]
    clean_window: int = 0           # Jours d'exclusion post-outcome (sans eras, on exclut les patients avec outcome avant index)
```

SQL généré (s'appuie sur `sql_builder.build_cohort_sql()` existant) :
```sql
WITH target AS (
    -- SQL de la cohorte cible (réutilise sql_builder)
    SELECT person_id, MIN(index_date) as cohort_start
    FROM ({target_cohort_sql}) t
    GROUP BY person_id
),
target_with_obs AS (
    -- Joindre observation_period pour calculer le time-at-risk
    SELECT t.person_id, t.cohort_start,
           LEAST(op.observation_period_end_date,
                 t.cohort_start + INTERVAL '{tar_end} days') as tar_end,
           t.cohort_start + INTERVAL '{tar_start} days' as tar_start
    FROM target t
    JOIN {schema}.observation_period op ON t.person_id = op.person_id
        AND t.cohort_start BETWEEN op.observation_period_start_date AND op.observation_period_end_date
),
outcomes AS (
    -- SQL de la cohorte outcome
    SELECT person_id, MIN(outcome_date) as outcome_date
    FROM ({outcome_cohort_sql}) o
    GROUP BY person_id
),
analysis AS (
    SELECT
        twr.person_id,
        twr.tar_start,
        CASE WHEN o.outcome_date BETWEEN twr.tar_start AND twr.tar_end
             THEN 1 ELSE 0 END as had_outcome,
        CASE WHEN o.outcome_date BETWEEN twr.tar_start AND twr.tar_end
             THEN o.outcome_date - twr.tar_start
             ELSE twr.tar_end - twr.tar_start END as time_days,
        -- strata columns
        EXTRACT(YEAR FROM twr.tar_start) - p.year_of_birth as age,
        p.gender_concept_id,
        EXTRACT(YEAR FROM twr.tar_start) as calendar_year
    FROM target_with_obs twr
    LEFT JOIN outcomes o ON twr.person_id = o.person_id
    JOIN {schema}.person p ON twr.person_id = p.person_id
    WHERE twr.tar_start < twr.tar_end  -- Exclure TAR invalides
)
SELECT
    {strata_columns},
    COUNT(*) as persons_at_risk,
    SUM(had_outcome) as persons_with_outcome,
    SUM(time_days) / 365.25 as person_years,
    SUM(had_outcome)::float / NULLIF(SUM(time_days) / 365.25, 0) as incidence_rate,
    -- Proportion
    SUM(had_outcome)::float / NULLIF(COUNT(*), 0) as incidence_proportion
FROM analysis
GROUP BY {strata_columns}
ORDER BY {strata_columns}
```

Output :
```python
class IncidenceResult(BaseModel):
    target_count: int
    outcome_count: int
    person_years: float
    incidence_rate: float           # par personne-année
    incidence_proportion: float     # proportion
    strata: list[StrataResult]      # résultats par strate
    summary: dict                   # IC 95% via formule exacte de Poisson
```

**Nouveau modèle** (`db/models.py`) :
```python
class IncidenceAnalysis(Base):
    __tablename__ = "incidence_analyses"
    id = Column(Integer, primary_key=True)
    cdm_name = Column(String, index=True)
    name = Column(String)
    target_cohort_id = Column(Integer, ForeignKey("cohorts.id"))
    outcome_cohort_id = Column(Integer, ForeignKey("cohorts.id"))
    parameters_json = Column(Text)
    results_json = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
```

### Frontend

- Nouvelle page `IncidencePage.tsx` :
  - Sélecteur de cohorte cible + cohorte outcome (dropdown des cohortes existantes)
  - Configuration TAR (time at risk)
  - Configuration strates (age groups, gender, calendar year)
  - Résultats : table + graphiques (barres par strate, trend par année)
- Composant `IncidenceChart.tsx` : Recharts bar/line chart pour les taux par strate
- Ajout dans le Sidebar + routing

### Estimation d'effort
~4-5 jours dev

---

## P0-3 : Critères temporels inter-critères

**Pourquoi** : Aujourd'hui le temporal est "relatif à l'index" ou "absolu". Atlas permet "Condition A dans les 30j AVANT Drug B". C'est fondamental pour la causalité clinique.

### Backend (`modules/cohort/sql_builder.py`)

**Nouveau champ** sur `CohortCriterion` :
```python
class TemporalConstraint(BaseModel):
    type: str  # "any_time" | "absolute_window" | "within_days" | "relative_to_criterion"
    # ... champs existants ...
    # Nouveaux champs :
    reference_criterion_id: str | None = None   # UUID du critère de référence
    days_before: int | None = None
    days_after: int | None = None
    # "A dans les 30j avant B" → sur A: reference=B, days_before=30, days_after=0
```

**Modification de `_build_single_cte()`** (ligne ~630) :
- Si `temporal.type == "relative_to_criterion"` :
  - Au lieu de filtrer sur une date absolue, générer un JOIN avec le CTE du critère référencé
  - Le CTE référencé doit déjà être construit (topological sort des dépendances)

```sql
-- Critère A "dans les 30j avant critère B"
cte_a AS (
    SELECT DISTINCT a.person_id
    FROM {schema}.condition_occurrence a
    JOIN cte_b b ON a.person_id = b.person_id
        AND a.condition_start_date BETWEEN b.event_date - INTERVAL '30 days' AND b.event_date
    WHERE a.condition_concept_id IN (...)
)
```

**Impact sur la construction** :
1. Modifier `_build_group_sql()` pour détecter les dépendances inter-critères
2. Construire un graphe de dépendances et trier les CTEs en ordre topologique
3. Stocker `event_date` dans les CTEs intermédiaires (aujourd'hui seul `person_id` est retourné)
4. Ajouter la colonne date dans le SELECT des CTEs quand un autre critère y fait référence

**Impact sur `_build_concept_filter()` et `_build_date_filter()`** :
- Nouveau cas dans `_build_date_filter()` (~ligne 670) : `relative_to_criterion` génère un placeholder `{ref_cte_name}` résolu lors de l'assemblage final

### Frontend (`components/cohort/CriteriaPanel.tsx`)

- Dans la section "Temporal Constraint" : nouveau type "Relative to another criterion"
- Dropdown listant les autres critères du même groupe d'inclusion
- Champs days_before / days_after

### Estimation d'effort
~3-4 jours dev (complexité surtout dans le topological sort + tests)

---

## P0-4 : Cohort Exit Criteria + Time-at-Risk

**Pourquoi** : Aujourd'hui une cohorte OPAL définit seulement QUI entre dans la cohorte. Il n'y a pas de notion de QUAND on en sort. C'est indispensable pour : incidence rates (P0-2), survie, et toute analyse temporelle.

### Backend

**Modification de `CohortCriteria`** (types + sql_builder) :

```python
class CohortExitCriteria(BaseModel):
    type: str  # "end_of_observation" | "fixed_duration" | "event_based"
    # fixed_duration
    duration_days: int | None = None
    # event_based
    exit_event: CriteriaGroup | None = None  # Réutilise le même format que inclusion
```

Ajout dans `CohortCriteria` :
```python
class CohortCriteria(BaseModel):
    name: str
    inclusion: CriteriaGroup
    exclusion: CriteriaGroup | None
    demographics: DemographicConstraints | None
    exit_criteria: CohortExitCriteria | None = None  # NOUVEAU
```

**Modification de `sql_builder.py`** :

Nouvelle fonction `build_cohort_sql_with_dates()` qui retourne `(person_id, cohort_start_date, cohort_end_date)` :

```sql
WITH cohort_entry AS (
    -- SQL existant mais retourne aussi MIN(date_col) as cohort_start_date
    SELECT person_id, MIN({date_col}) as cohort_start_date
    FROM ...
    GROUP BY person_id
),
cohort_with_exit AS (
    SELECT
        ce.person_id,
        ce.cohort_start_date,
        CASE
            WHEN '{exit_type}' = 'end_of_observation'
            THEN op.observation_period_end_date
            WHEN '{exit_type}' = 'fixed_duration'
            THEN ce.cohort_start_date + INTERVAL '{duration} days'
            WHEN '{exit_type}' = 'event_based'
            THEN COALESCE(exit_event.event_date, op.observation_period_end_date)
        END as cohort_end_date
    FROM cohort_entry ce
    JOIN {schema}.observation_period op ON ce.person_id = op.person_id
        AND ce.cohort_start_date BETWEEN op.observation_period_start_date
                                     AND op.observation_period_end_date
    LEFT JOIN ({exit_event_sql}) exit_event ON ce.person_id = exit_event.person_id
)
SELECT person_id, cohort_start_date, cohort_end_date
FROM cohort_with_exit
```

**Impact sur les fonctions existantes** :
- `build_cohort_sql()` : reste inchangé (backward compatible, retourne juste person_id)
- `build_count_sql()` : inchangé
- Nouvelle `build_cohort_dated_sql()` : utilisée par incidence (P0-2) et la future survie
- Modification de `build_attrition_sql()` : optionnel, peut afficher la durée médiane de suivi par étape
- Modification de `build_sample_sql()` : ajouter cohort_start/end dans le sample

### Frontend

- Dans `QueryCanvas.tsx` : nouvelle section "Exit Criteria" sous les critères d'exclusion
- 3 options radio : "Fin d'observation", "Durée fixe (N jours)", "Événement"
- Pour "Événement" : réutiliser le composant `CriteriaPanel` existant (même UX que l'inclusion)
- Affichage de la durée médiane de suivi dans `ResultsPanel.tsx`

### Estimation d'effort
~3-4 jours dev

---

## P0-5 : Survie (Kaplan-Meier)

**Pourquoi** : C'est LA feature d'estimation la plus demandée. Avec les exit criteria (P0-4) et les cohortes existantes, c'est calculable en SQL pur sans R.

**Prérequis** : P0-4 (exit criteria pour le time-at-risk)

### Backend

**Nouveau module** (`modules/estimation/`) :

**`router.py`** :
- `POST /api/estimation/kaplan-meier` — Calculer une courbe KM
- `POST /api/estimation/save` — Sauvegarder
- `GET /api/estimation/` — Lister
- `GET /api/estimation/{id}` — Détail

**`survival.py`** — Moteur KM :

Input :
```python
class KaplanMeierRequest(BaseModel):
    cdm_name: str
    target_cohort_id: int
    outcome_cohort_id: int
    time_at_risk_start: int = 0
    time_at_risk_end: int | None = None  # None = end of observation
    time_unit: str = "days"  # "days" | "months" | "years"
    strata: list[str] = []   # ["gender", "age_group"]
    age_groups: list[dict] = []
    confidence_level: float = 0.95
```

Algorithme (en Python, pas en SQL — le dataset est ramené en mémoire) :
1. Exécuter `build_cohort_dated_sql()` pour target → `(person_id, cohort_start, cohort_end)`
2. Exécuter `build_cohort_sql()` pour outcome → `(person_id)` avec date de l'outcome
3. Joindre : pour chaque patient, calculer `time = min(outcome_date, cohort_end) - cohort_start`, `event = 1 si outcome dans [start, end], 0 sinon`
4. Trier par time, calculer KM :

```python
def compute_km(times, events):
    """Kaplan-Meier estimator — pur Python, pas de dépendance."""
    unique_times = sorted(set(t for t, e in zip(times, events) if e == 1))
    n = len(times)
    survival = 1.0
    curve = [{"time": 0, "survival": 1.0, "ci_lower": 1.0, "ci_upper": 1.0, "at_risk": n, "events": 0}]

    for t in unique_times:
        at_risk = sum(1 for ti in times if ti >= t)
        events_at_t = sum(1 for ti, ei in zip(times, events) if ti == t and ei == 1)
        censored_before = sum(1 for ti, ei in zip(times, events) if ti < t and ei == 0)

        survival *= (1 - events_at_t / at_risk)

        # Greenwood CI
        se = survival * sqrt(sum(
            d / (n_r * (n_r - d))
            for t2, d, n_r in risk_table if t2 <= t and n_r > d
        ))
        z = 1.96  # 95% CI
        curve.append({
            "time": t,
            "survival": survival,
            "ci_lower": max(0, survival - z * se),
            "ci_upper": min(1, survival + z * se),
            "at_risk": at_risk,
            "events": events_at_t
        })

    return curve
```

5. Si strates demandées : grouper les patients et calculer KM par sous-groupe
6. Log-rank test entre strates :
```python
def log_rank_test(groups):
    """Chi-squared log-rank test entre groupes."""
    # O_i - E_i pour chaque groupe, chi2 = sum((O-E)^2 / E)
    ...
    return {"chi_square": chi2, "p_value": p, "df": len(groups) - 1}
```

Output :
```python
class KaplanMeierResult(BaseModel):
    overall: list[KMPoint]            # Courbe globale
    strata: dict[str, list[KMPoint]]  # Courbes par strate
    log_rank: dict | None             # Test si strates
    median_survival: float | None     # Temps médian
    summary: dict                     # N, events, censored
```

**Nouveau modèle** :
```python
class EstimationAnalysis(Base):
    __tablename__ = "estimation_analyses"
    id = Column(Integer, primary_key=True)
    cdm_name = Column(String, index=True)
    name = Column(String)
    analysis_type = Column(String)  # "kaplan_meier" pour l'instant
    target_cohort_id = Column(Integer, ForeignKey("cohorts.id"))
    outcome_cohort_id = Column(Integer, ForeignKey("cohorts.id"))
    parameters_json = Column(Text)
    results_json = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
```

### Frontend

- Nouvelle page `EstimationPage.tsx` :
  - Sélection cohorte cible + outcome
  - Configuration TAR + strates
  - Bouton "Compute"
- Composant `KaplanMeierChart.tsx` :
  - Recharts AreaChart avec step interpolation
  - Bandes de confiance (Area avec fillOpacity)
  - Table "Number at risk" sous le graphique
  - Légende par strate si applicable
  - Médiane en ligne pointillée horizontale
- Affichage du log-rank p-value si strates

### Estimation d'effort
~5-6 jours dev (dont ~2 pour le chart KM)

---

## Résumé & Priorisation

| # | Feature | Prérequis | Effort | Valeur |
|---|---------|-----------|--------|--------|
| **P0-1** | Concept Sets | Aucun | 3-4j | Fondation pour tout le reste |
| **P0-2** | Incidence Rates | P0-4 (partiel) | 4-5j | Épidémiologie de base |
| **P0-3** | Temporal inter-critères | Aucun | 3-4j | Cohort builder crédible |
| **P0-4** | Exit Criteria + TAR | Aucun | 3-4j | Prérequis P0-2 et P0-5 |
| **P0-5** | Kaplan-Meier | P0-4 | 5-6j | Feature signature |

### Ordre de développement recommandé

```
P0-1 (Concept Sets)     ←  indépendant, débloque l'UX
    ↓
P0-3 (Temporal)          ←  indépendant, améliore le cohort builder
    ↓
P0-4 (Exit Criteria)     ←  indépendant, débloque P0-2 et P0-5
    ↓
P0-2 (Incidence)         ←  dépend de P0-4
    ↓
P0-5 (Kaplan-Meier)      ←  dépend de P0-4
```

P0-1 et P0-3 peuvent être développés **en parallèle**.
P0-2 et P0-5 peuvent être développés **en parallèle** une fois P0-4 terminé.

**Effort total estimé : ~18-23 jours dev**

---

## Fichiers impactés (récapitulatif)

### Nouveaux fichiers
- `backend/modules/concept_set/router.py`
- `backend/modules/incidence/router.py`
- `backend/modules/incidence/engine.py`
- `backend/modules/estimation/router.py`
- `backend/modules/estimation/survival.py`
- `frontend/src/pages/ConceptSetPage.tsx`
- `frontend/src/pages/IncidencePage.tsx`
- `frontend/src/pages/EstimationPage.tsx`
- `frontend/src/components/estimation/KaplanMeierChart.tsx`
- `frontend/src/components/incidence/IncidenceChart.tsx`

### Fichiers modifiés
- `backend/db/models.py` — 3 nouveaux modèles (ConceptSet, IncidenceAnalysis, EstimationAnalysis)
- `backend/main.py` — Enregistrer 3 nouveaux routers
- `backend/modules/cohort/sql_builder.py` — Temporal inter-critères, exit criteria, concept_set_id
- `frontend/src/types/index.ts` — Nouveaux types
- `frontend/src/api/client.ts` — Nouveaux API clients
- `frontend/src/App.tsx` — Nouvelles routes
- `frontend/src/components/layout/Sidebar.tsx` — Nouveaux liens nav
- `frontend/src/components/cohort/CriteriaPanel.tsx` — Concept set picker + temporal relatif
- `frontend/src/components/cohort/QueryCanvas.tsx` — Section exit criteria
- `backend/i18n/en.json` + `backend/i18n/fr.json` — Traductions
