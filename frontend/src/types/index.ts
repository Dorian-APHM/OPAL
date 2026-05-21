/** CDM connection configuration */
export interface CdmConfig {
  id: number;
  name: string;
  db_host: string;
  db_port: number;
  db_name: string;
  db_user: string;
  omop_schema: string;
  created_at: string | null;
}

/** Analysis snapshot metadata */
export interface SnapshotMeta {
  id: number;
  version: number;
  created_at: string | null;
}

/** Full snapshot with results */
export interface Snapshot extends SnapshotMeta {
  cdm_name?: string;
  domain?: string;
  results: AnalysisResults;
}

/** Analysis results — varies by domain type */
export type AnalysisResults = DashboardResults | PersonResults | ObsPeriodResults | ClinicalResults;

/** Dashboard results */
export interface DashboardResults {
  domain: 'Dashboard';
  table: string;
  summary: {
    total_persons: number;
    domains: DomainStat[];
  };
}

export interface DomainStat {
  domain: string;
  total_records: number;
  distinct_persons: number;
  pct_persons: number;
  total_terms: number;
  mapped_terms: number;
  unmapped_terms: number;
  pct_terms_mapped: number;
  sparkline?: number[];
  error?: string;
}

/** Person results */
export interface PersonResults {
  domain: 'Person';
  table: string;
  achilles_like: {
    person_summary: {
      total_persons: number;
      gender_distribution: {
        gender_concept_id: (number | null)[];
        gender_name: string[];
        count: number[];
      };
      birth_year_distribution: {
        year_of_birth: number[];
        count: number[];
      };
      race_distribution?: {
        race_concept_id: (number | null)[];
        race_name: string[];
        count: number[];
      };
      ethnicity_distribution?: {
        ethnicity_concept_id: (number | null)[];
        ethnicity_name: string[];
        count: number[];
      };
    };
  };
  mapping: Record<string, unknown>;
}

/** Observation Period results */
export interface ObsPeriodResults {
  domain: 'ObservationPeriod';
  table: string;
  achilles_like: {
    age_at_first_observation: { age: number[]; count: number[] };
    age_by_gender: {
      rows: BoxPlotRow[];
    };
    observation_length_months: {
      months: number[];
      n_persons: number[];
      cap_months: number;
    };
    duration_by_gender: {
      rows: BoxPlotRow[];
    };
    cumulative_observation: {
      months_threshold: number[];
      pct_persons: number[];
    };
    continuous_observation_by_year: {
      year: number[];
      n_persons: number[];
    };
  };
  mapping: Record<string, unknown>;
}

export interface BoxPlotRow {
  gender_concept_id: string;
  gender_name: string;
  n: number;
  mean_age?: number | null;
  mean_months?: number | null;
  p10: number | null;
  p25: number | null;
  median_age?: number | null;
  median_months?: number | null;
  p75: number | null;
  p90: number | null;
}

/** Clinical domain results */
export interface ClinicalResults {
  domain: string;
  table: string;
  achilles_like: {
    global: { total_rows: number; distinct_persons: number };
    by_month: { month_start: string[]; count: number[] };
    records_per_person: {
      records_per_person: number[];
      n_persons: number[];
      max_bin: number;
    };
    top_concepts: ConceptRow[];
  };
  mapping: {
    terms: MappingTerms;
    rows: MappingRows;
    top_unmapped_terms: UnmappedTerm[];
  };
}

export interface ConceptRow {
  concept_id: string;
  concept_name: string;
  source_value: string;
  n_records: number;
  n_persons: number;
}

export interface MappingTerms {
  total_terms: number;
  mapped_terms: number;
  unmapped_terms: number;
  pct_terms_mapped: number | null;
}

export interface MappingRows {
  total_rows: number;
  mapped_rows: number;
  unmapped_rows: number;
  pct_rows_mapped: number | null;
}

export interface UnmappedTerm {
  source_value: string;
  source_name?: string;
  count: number;
}

/** Comparison result */
export interface ComparisonResult {
  domain: string;
  diffs: Record<string, { a: unknown; b: unknown; pct_change: number | null }>;
  alerts: ComparisonAlert[];
  threshold: number;
  snapshot_a: { id: number; cdm_name: string; version: number };
  snapshot_b: { id: number; cdm_name: string; version: number };
  results_a: AnalysisResults;
  results_b: AnalysisResults;
}

export interface ComparisonAlert {
  metric: string;
  value_a: unknown;
  value_b: unknown;
  pct_change: number;
  severity: 'warning' | 'critical';
}

/** Analysis settings */
export interface AnalysisSettingsType {
  cdm_name: string;
  omop_schema: string;
  top_unmapped_terms: number;
  top_concepts: number;
  max_records_per_person: number;
  max_observation_months: number;
  comparison_alert_threshold: number;
}

/** SSE batch progress event */
export interface BatchProgressEvent {
  type: 'start' | 'progress' | 'done' | 'error' | 'cancelled';
  analysis_id?: string;
  domain?: string;
  status?: 'running' | 'success' | 'error';
  error?: string;
  completed: number;
  total: number;
  message?: string;
}

// ──── Phase 2: Cohort types ────

/** OMOP concept from the concept table */
export interface OmopConcept {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  domain_id: string;
  vocabulary_id: string;
  concept_class_id: string;
  standard_concept: string | null;
}

/** Temporal relation between two criteria (Allen's interval algebra subset) */
export type TemporalRelation =
  | 'before'          // A ends before B starts
  | 'after'           // A starts after B ends
  | 'starts_before'   // A starts before B starts
  | 'starts_after'    // A starts after B starts
  | 'ends_before'     // A ends before B ends
  | 'ends_after'      // A ends after B ends
  | 'overlaps'        // A and B overlap in time
  | 'contains'        // A fully contains B
  | 'during';         // A occurs during B

/** Temporal constraint for a criterion */
export interface TemporalConstraint {
  type: 'any_time' | 'absolute_window' | 'within_days' | 'during_visit' | 'relative_to_criterion';
  date_from?: string;
  date_to?: string;
  days_before?: number;
  days_after?: number;
  relative_to?: 'index';
  reference_criterion_id?: string;
  /** Temporal relation when type='relative_to_criterion' (default: 'before') */
  relation?: TemporalRelation;
}

/** Occurrence (frequency) constraint */
export interface OccurrenceConstraint {
  type: 'any' | 'at_least' | 'exactly' | 'at_most';
  count: number;
  within_days?: number;
}

/** Value constraint (for Measurement) */
export interface ValueConstraint {
  operator: '>' | '<' | '>=' | '<=' | '=' | 'between';
  value: number;
  value_high?: number;
  value_as_concept_id?: number;
  unit_concept_id?: number;
}

/** A single criterion block in the query builder */
export interface CohortCriterion {
  id: string; // client-side UUID
  domain: string;
  concepts: OmopConcept[];
  include_descendants: boolean;
  source_codes: string[];
  temporal: TemporalConstraint;
  occurrence: OccurrenceConstraint;
  value?: ValueConstraint;
  operatorWithNext?: 'AND' | 'OR'; // operator linking to the NEXT criterion
}

/** A node in the criteria tree: either a leaf criterion or a nested group */
export type CriteriaNode =
  | { type: 'criterion'; criterion: CohortCriterion }
  | { type: 'group'; group: CriteriaGroup };

/** Logical group of criteria (AND/OR) — supports nested sub-groups */
export interface CriteriaGroup {
  operator: 'AND' | 'OR';
  criteria: CohortCriterion[];
  groups?: CriteriaGroup[];
  /** Ordered children mixing criteria and sub-groups (preferred over separate arrays) */
  children?: CriteriaNode[];
  sameVisit?: boolean;
}

/** Demographic constraints */
export interface DemographicConstraints {
  age?: { min?: number; max?: number; at?: 'index' | 'current' };
  gender?: number[];
  race?: number[];
  ethnicity?: number[];
}

/** Full cohort criteria JSON (sent to backend) */
export interface CohortCriteria {
  name?: string;
  inclusion: CriteriaGroup;
  exclusion: CriteriaGroup;
  demographics?: DemographicConstraints;
  exit_criteria?: CohortExitCriteria;
  /** ID of the criterion designated as the initial/index event (cohort entry) */
  initial_event_criterion_id?: string;
}

/** Cohort summary from list endpoint */
export interface CohortSummary {
  id: number;
  cdm_name: string;
  name: string;
  description: string;
  created_by?: string;
  shared_with_all?: boolean;
  created_at: string | null;
  updated_at: string | null;
  latest_version: number;
  patient_count: number | null;
}

/** Cohort version detail */
export interface CohortVersionDetail {
  id: number;
  version: number;
  criteria_json: CohortCriteria;
  generated_sql: string;
  patient_count: number | null;
  created_at: string | null;
}

/** Cohort full detail */
export interface CohortDetail {
  id: number;
  cdm_name: string;
  name: string;
  description: string;
  created_at: string | null;
  updated_at: string | null;
  versions: CohortVersionDetail[];
}

/** Attrition step result */
export interface AttritionStep {
  step: number;
  label: string;
  count: number | null;
  error?: string;
}

/** Patient journey event (from timeline endpoint) */
export interface PatientJourneyEvent {
  domain: string;
  start_date: string | null;
  end_date?: string;
  concept_id: number | null;
  concept_name: string;
  source_value: string;
  source_concept_name?: string;
  value_as_number?: number;
  unit_source_value?: string;
  quantity?: number;
}

/** Patient info returned with journey */
export interface PatientJourneyInfo {
  person_id: number;
  year_of_birth: number;
  gender: string;
  observation_period_start_date: string | null;
  observation_period_end_date: string | null;
}

/** Sample patient row */
export interface SamplePatient {
  person_id: number;
  year_of_birth: number;
  gender: string;
  race: string;
  observation_period_start_date: string | null;
  observation_period_end_date: string | null;
}

// ──── Characterization (Table 1) types ────

/** Demographics section of characterization */
export interface CharacterizationDemographics {
  age: {
    n: number;
    mean_age: number | null;
    std_age: number | null;
    min_age: number | null;
    max_age: number | null;
    q1_age: number | null;
    median_age: number | null;
    q3_age: number | null;
  };
  age_groups: { age_group: string; count: number }[];
  gender: { label: string; concept_id: number | null; count: number }[];
  race: { label: string; concept_id: number | null; count: number }[];
  ethnicity: { label: string; concept_id: number | null; count: number }[];
}

/** Top concept in a domain */
export interface CharacterizationConcept {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  vocabulary_id: string;
  n_persons: number;
  n_records: number;
  pct_persons: number;
}

/** Domain prevalence section */
export interface CharacterizationDomainPrevalence {
  domain: string;
  patients_with_data: number;
  pct_with_data: number;
  top_concepts: CharacterizationConcept[];
  error?: string;
}

/** Measurement value stats */
export interface CharacterizationMeasurementStat {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  n_persons: number;
  pct_persons: number;
  mean_value: number | null;
  std_value: number | null;
  median_value: number | null;
  min_value: number | null;
  max_value: number | null;
  unit: string;
}

/** Visit type distribution */
export interface CharacterizationVisitType {
  concept_id: number;
  concept_name: string;
  n_persons: number;
  n_records: number;
  pct_persons: number;
}

/** Observation period stats */
export interface CharacterizationObsPeriod {
  n_periods: number;
  n_persons: number;
  mean_days: number | null;
  std_days: number | null;
  min_days: number | null;
  max_days: number | null;
  median_days: number | null;
  earliest_start: string | null;
  latest_end: string | null;
}

/** Full characterization result */
export interface CharacterizationVisitDuration {
  n_visits: number;
  mean_days: number | null;
  std_days: number | null;
  min_days: number | null;
  max_days: number | null;
  median_days: number | null;
  by_type?: { visit_type: string; n_visits: number; mean_days: number | null; std_days: number | null; median_days: number | null }[];
}

export interface CharacterizationResult {
  cohort_size: number;
  demographics: CharacterizationDemographics;
  domain_prevalence: CharacterizationDomainPrevalence[];
  measurement_stats: CharacterizationMeasurementStat[];
  visit_types: CharacterizationVisitType[];
  visit_duration?: CharacterizationVisitDuration;
  observation_period: CharacterizationObsPeriod;
}

// ──── Cohort Comparison (SMD) types ────

export interface CohortComparisonDemographicCategory {
  label: string;
  pct_a: number;
  pct_b: number;
  smd: number | null;
}

export interface CohortComparisonConcept {
  concept_id: number;
  concept_name: string;
  pct_persons_a: number;
  pct_persons_b: number;
  smd: number | null;
}

export interface CohortComparisonDomain {
  domain: string;
  pct_with_data_a: number;
  pct_with_data_b: number;
  smd: number | null;
  concepts: CohortComparisonConcept[];
}

export interface CohortComparisonMeasurement {
  concept_id: number;
  concept_name: string;
  unit: string;
  mean_a: number | null;
  std_a: number | null;
  mean_b: number | null;
  std_b: number | null;
  smd: number | null;
  pct_persons_a: number;
  pct_persons_b: number;
  prevalence_smd: number | null;
}

export interface CohortComparisonVisitType {
  concept_id: number;
  concept_name: string;
  pct_persons_a: number;
  pct_persons_b: number;
  smd: number | null;
}

export interface CohortComparisonVariable {
  category: string;
  variable: string;
  smd: number | null;
}

export interface CohortComparisonResult {
  cohort_a_name: string;
  cohort_b_name: string;
  cohort_a_size: number;
  cohort_b_size: number;
  demographics: {
    age: { mean_a: number | null; std_a: number | null; mean_b: number | null; std_b: number | null; smd: number | null };
    gender: CohortComparisonDemographicCategory[];
    race: CohortComparisonDemographicCategory[];
    ethnicity: CohortComparisonDemographicCategory[];
    age_groups: (CohortComparisonDemographicCategory & { age_group: string })[];
  };
  domain_prevalence: CohortComparisonDomain[];
  measurement_stats: CohortComparisonMeasurement[];
  visit_types: CohortComparisonVisitType[];
  observation_period: {
    mean_days_a: number | null; std_days_a: number | null;
    mean_days_b: number | null; std_days_b: number | null;
    smd: number | null;
  };
  all_variables: CohortComparisonVariable[];
}

// ──── Pathways Analysis types ────

export interface PathwaysSunburstNode {
  name: string;
  count: number;
  pct: number;
  children: PathwaysSunburstNode[];
}

export interface PathwaysTableRow {
  pathway: string[];
  count: number;
  pct: number;
}

export interface PathwaysResult {
  target_size: number;
  persons_with_pathways: number;
  pathways_table: PathwaysTableRow[];
  sunburst_tree: PathwaysSunburstNode;
  event_colors: Record<string, string>;
}

export interface PathwaysEventCohort {
  name: string;
  domain: string;
  concept_ids: number[];
  include_descendants: boolean;
  source_codes: string[];
}

// ──── Phase 3: Mapping types ────

/** Domain mapping stats from dashboard */
export interface MappingDomainStat {
  domain: string;
  total_terms: number;
  mapped_terms: number;
  unmapped_terms: number;
  pct_terms_mapped: number;
  total_rows: number;
  mapped_rows: number;
  unmapped_rows: number;
  pct_rows_mapped: number;
  version: number;
  snapshot_date: string | null;
}

/** Strategy confidence statistics */
export interface StrategyStats {
  strategy: string;
  total_decisions: number;
  approved: number;
  modified: number;
  rejected: number;
  approval_rate: number;
  rejection_rate: number;
  modification_rate: number;
  avg_confidence: number | null;
  avg_confidence_approved: number | null;
  avg_confidence_rejected: number | null;
}

/** Mapping dashboard response */
export interface MappingDashboardData {
  cdm_name: string;
  domains: MappingDomainStat[];
  decisions_summary: Record<string, number>;
}

/** Mapping evolution point */
export interface MappingEvolutionPoint {
  version: number;
  date: string | null;
  pct_terms_mapped: number;
  pct_rows_mapped: number;
  total_terms: number;
  unmapped_terms: number;
}

/** Unmapped term */
export interface UnmappedItem {
  source_value: string;
  source_name: string;
  source_atc?: string;
  n_records: number;
  n_persons: number;
  pending?: boolean;
  pending_concept_id?: number;
  pending_concept_name?: string;
  pending_vocabulary_id?: string;
  pending_user?: string;
  pending_at?: string;
}

/** Mapping suggestion */
export interface MappingSuggestion {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  vocabulary_id: string;
  domain_id: string;
  standard_concept: string | null;
  confidence: number;
  source: 'exact' | 'relationship' | 'fuzzy' | 'contextual';
}

/** Suggestion result for one term */
export interface SuggestionResult {
  source_value: string;
  source_name: string;
  suggestions: MappingSuggestion[];
}

/** Mapping decision (history entry) */
export interface MappingDecisionEntry {
  id: number;
  domain: string;
  source_value: string;
  source_name: string;
  action: 'approved' | 'modified' | 'rejected' | 'rolled_back';
  target_concept_id: number | null;
  target_concept_name: string;
  target_vocabulary_id: string;
  previous_concept_id: number | null;
  suggestion_source: string;
  confidence_score: number | null;
  user: string;
  reason: string;
  created_at: string | null;
}

// ──── Concept Sets ────

export interface ConceptSetItem {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  vocabulary_id: string;
  include_descendants: boolean;
}

export interface ConceptSetSummary {
  id: number;
  name: string;
  cdm_name: string;
  domain: string | null;
  description: string;
  concept_count: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface ConceptSetDetail extends ConceptSetSummary {
  concepts: ConceptSetItem[];
  source_codes?: { source_value: string; source_name: string; domain: string }[];
}

// ──── Exit Criteria ────

export interface CohortExitCriteria {
  type: 'end_of_observation' | 'fixed_duration' | 'event_based';
  duration_days?: number;
  exit_event?: CriteriaGroup;
}

// ──── Incidence Rate ────

export interface IncidenceStrataResult {
  strata_values: Record<string, string>;
  target_count: number;
  outcome_count: number;
  person_years: number;
  incidence_rate: number;
  incidence_proportion: number;
  ci_lower: number;
  ci_upper: number;
}

export interface IncidenceResult {
  target_count: number;
  outcome_count: number;
  person_years: number;
  incidence_rate: number;
  incidence_proportion: number;
  ci_lower: number;
  ci_upper: number;
  target_name: string;
  outcome_name: string;
  strata: IncidenceStrataResult[];
  sql?: string;
}

export interface IncidenceAnalysisSummary {
  id: number;
  cdm_name: string;
  name: string;
  target_cohort_id: number;
  outcome_cohort_id: number;
  created_at: string | null;
}

// ──── Kaplan-Meier ────

export interface KMPoint {
  time: number;
  survival: number;
  ci_lower: number;
  ci_upper: number;
  at_risk: number;
  events: number;
  censored: number;
}

export interface KaplanMeierResult {
  target_name: string;
  outcome_name: string;
  overall: KMPoint[];
  strata: Record<string, KMPoint[]>;
  log_rank: { chi_square: number; p_value: number; df: number } | null;
  median_survival: number | null;
  time_unit: string;
  summary: { n: number; events: number; censored: number };
}

export interface EstimationAnalysisSummary {
  id: number;
  cdm_name: string;
  name: string;
  analysis_type: string;
  target_cohort_id: number;
  outcome_cohort_id: number;
  created_at: string | null;
}

// ──── Audit types ────

/** Audit log entry */
export interface AuditEntry {
  ts: string;
  user: string;
  roles: string[];
  action: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  ip: string;
  params?: Record<string, string>;
}

/** Audit stats */
export interface AuditStats {
  total_events: number;
  by_user: { user: string; count: number }[];
  by_action: { action: string; count: number }[];
}

// ──── Admin user types ────

/** Keycloak user */
export interface AdminUser {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  enabled: boolean;
  created_at: number | null;
  roles: string[];
}

/** User group summary (from /api/groups/) */
export interface GroupSummary {
  name: string;
  description: string;
  created_by: string;
  member_count: number;
  created_at: string | null;
}

/** User group detail (from /api/groups/:name) */
export interface GroupDetail {
  name: string;
  description: string;
  created_by: string;
  members: { username: string; added_by: string }[];
}

/** Cohort sharing info (from /api/cohorts/:id/shares) */
export interface CohortShareInfo {
  cohort_id: number;
  shared_with_all: boolean;
  shares: { type: string; target: string; shared_by: string; created_at: string | null }[];
}

/** Access request */
export interface AccessRequest {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  requested_role: string;
  status: 'pending' | 'approved' | 'rejected';
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
}
