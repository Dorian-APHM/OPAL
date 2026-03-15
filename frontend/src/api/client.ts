import axios from 'axios';
import type {
  CdmConfig,
  SnapshotMeta,
  Snapshot,
  ComparisonResult,
  AnalysisSettingsType,
  CohortSummary,
  CohortDetail,
  CohortCriteria,
  OmopConcept,
  AttritionStep,
  SamplePatient,
  CharacterizationResult,
  MappingDashboardData,
  MappingEvolutionPoint,
  UnmappedItem,
  SuggestionResult,
  MappingDecisionEntry,
  CohortComparisonResult,
  StrategyStats,
  PatientJourneyEvent,
  PatientJourneyInfo,
  AuditEntry,
  AuditStats,
  AdminUser,
  AccessRequest,
  ConceptSetSummary,
  ConceptSetDetail,
  IncidenceResult,
  IncidenceAnalysisSummary,
  KaplanMeierResult,
  EstimationAnalysisSummary,
  GroupSummary,
  GroupDetail,
  CohortShareInfo,
  PathwaysResult,
  PathwaysEventCohort,
} from '../types';

const api = axios.create({
  baseURL: '/api',
});

// Token getter & refresher — set by AuthProvider once Keycloak is initialized
let _getToken: (() => string | undefined) | null = null;
let _refreshToken: (() => Promise<string | undefined>) | null = null;
export function setTokenGetter(getter: () => string | undefined) {
  _getToken = getter;
}
export function setTokenRefresher(refresher: () => Promise<string | undefined>) {
  _refreshToken = refresher;
}

// Attach Keycloak Bearer token to all API requests
api.interceptors.request.use((config) => {
  const token = _getToken?.();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Token refresh queue to avoid concurrent refresh calls
let _isRefreshing = false;
let _refreshQueue: Array<(token: string | undefined) => void> = [];

function _processQueue(token: string | undefined) {
  _refreshQueue.forEach((resolve) => resolve(token));
  _refreshQueue = [];
}

// Unified error response interceptor with 401 retry
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (axios.isAxiosError(error) && error.response) {
      const { status, data } = error.response;
      const detail = data?.detail || data?.message || data?.error;
      if (detail && typeof detail === 'string') {
        error.message = detail;
      }

      // Attempt token refresh on 401 (only once per request)
      if (status === 401 && _refreshToken && !originalRequest._retry) {
        if (_isRefreshing) {
          // Queue this request until token refresh completes
          return new Promise((resolve) => {
            _refreshQueue.push((newToken) => {
              if (newToken) {
                originalRequest.headers.Authorization = `Bearer ${newToken}`;
              }
              resolve(api(originalRequest));
            });
          });
        }

        originalRequest._retry = true;
        _isRefreshing = true;
        try {
          const newToken = await _refreshToken();
          _isRefreshing = false;
          _processQueue(newToken);
          if (newToken) {
            originalRequest.headers.Authorization = `Bearer ${newToken}`;
            return api(originalRequest);
          }
        } catch {
          _isRefreshing = false;
          _processQueue(undefined);
        }
        error.message = 'Session expired. Please log in again.';
      } else if (status === 401) {
        error.message = 'Session expired. Please log in again.';
      } else if (status === 504) {
        error.message = detail || 'Query timed out. Try a simpler query.';
      } else if (status === 502) {
        error.message = detail || 'External database connection error.';
      } else if (status === 503) {
        error.message = detail || 'Service temporarily unavailable. Please try again.';
      } else if (status === 429) {
        error.message = 'Too many requests. Please slow down.';
      }
    } else if (error.code === 'ERR_NETWORK') {
      error.message = 'Network error. Please check your connection.';
    }
    return Promise.reject(error);
  },
);

// Global request timeout
api.defaults.timeout = 30000; // 30 seconds

/** Get current auth token (for fetch/download calls outside axios) */
export function getAuthToken(): string | undefined {
  return _getToken?.();
}

/** Authenticated fetch wrapper for streaming endpoints */
export function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const token = _getToken?.();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(url, { ...init, headers });
}

/** Open an authenticated download URL (for exports that return files) */
export function authDownload(url: string, filename?: string) {
  const token = _getToken?.();
  const xhr = new XMLHttpRequest();
  xhr.open('GET', url, true);
  xhr.responseType = 'blob';
  if (token) {
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
  }
  xhr.onload = () => {
    if (xhr.status === 200) {
      const blob = xhr.response;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename || url.split('/').pop() || 'download';
      // Try to extract filename from Content-Disposition header
      const cd = xhr.getResponseHeader('Content-Disposition');
      if (cd) {
        const match = cd.match(/filename="?([^";\n]+)"?/);
        if (match) a.download = match[1];
      }
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    }
  };
  xhr.send();
}

// CDM endpoints
export const cdmApi = {
  list: () => api.get<{ cdms: CdmConfig[] }>('/cdm/'),
  create: (data: {
    name: string;
    db_host: string;
    db_port: number;
    db_name: string;
    db_user: string;
    db_password: string;
    omop_schema?: string;
  }) => api.post('/cdm/', data),
  test: (data: {
    db_host: string;
    db_port: number;
    db_name: string;
    db_user: string;
    db_password: string;
  }) => api.post('/cdm/test', data),
  testSaved: (cdmName: string) => api.post(`/cdm/${cdmName}/test`),
  update: (cdmName: string, data: Record<string, unknown>) =>
    api.put(`/cdm/${cdmName}`, data),
  delete: (cdmName: string) => api.delete(`/cdm/${cdmName}`),
  getSettings: (cdmName: string) =>
    api.get<AnalysisSettingsType>(`/cdm/${cdmName}/settings`),
  updateSettings: (cdmName: string, data: Partial<AnalysisSettingsType>) =>
    api.put(`/cdm/${cdmName}/settings`, data),
};

// Quality endpoints
export const qualityApi = {
  domains: () => api.get<{ domains: string[] }>('/quality/domains'),
  analyze: (cdmName: string, domain: string) =>
    api.post('/quality/analyze', { cdm_name: cdmName, domain }),
  analyzeBatch: (cdmName: string, domains: string[]) =>
    api.post('/quality/analyze/batch', { cdm_name: cdmName, domains }),
  listSnapshots: (cdmName: string, domain: string) =>
    api.get<{ cdm_name: string; domain: string; snapshots: SnapshotMeta[] }>(
      `/quality/snapshots/${cdmName}/${domain}`
    ),
  getLatestSnapshot: (cdmName: string, domain: string) =>
    api.get<Snapshot>(`/quality/snapshots/${cdmName}/${domain}/latest`),
  getSnapshotById: (id: number) =>
    api.get<Snapshot>(`/quality/snapshots/by-id/${id}`),
  compare: (data: {
    cdm_name_a: string;
    cdm_name_b: string;
    domain: string;
    snapshot_id_a?: number;
    snapshot_id_b?: number;
  }) => api.post<ComparisonResult>('/quality/compare', data),
  exportCsv: (snapshotId: number, tableType: string) =>
    `/api/quality/export/${snapshotId}/${tableType}`,
  analyzeBatchStream: (cdmName: string, domains: string[]) => {
    return authFetch('/api/quality/analyze/batch/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cdm_name: cdmName, domains }),
    });
  },
  cancelAnalysis: (analysisId: string) =>
    api.post(`/quality/analyze/cancel/${analysisId}`),
  activeAnalyses: () =>
    api.get<{ active: { analysis_id: string; cancelled: boolean; cdm_name: string; type: string; domains: string[]; completed: number; total: number; domain_status: { domain: string; status: string }[] }[] }>('/quality/analyze/active'),
  timeline: (cdmName: string, domain?: string) =>
    api.get<{ cdm_name: string; timelines: Record<string, any[]> }>(
      `/quality/timeline/${cdmName}`, { params: domain ? { domain } : {} }
    ),
  reportUrl: (cdmName: string, lang: string = 'en') =>
    `/api/quality/report/${cdmName}?lang=${lang}`,
  comparisonReportUrl: (cdmNameA: string, cdmNameB: string, lang: string = 'en', domain?: string) =>
    `/api/quality/report/comparison?cdm_name_a=${encodeURIComponent(cdmNameA)}&cdm_name_b=${encodeURIComponent(cdmNameB)}&lang=${lang}${domain ? `&domain=${encodeURIComponent(domain)}` : ''}`,
};

// Cohort endpoints
export const cohortApi = {
  list: (cdmName?: string) =>
    api.get<{ cohorts: CohortSummary[] }>('/cohorts/', { params: cdmName ? { cdm_name: cdmName } : {} }),
  get: (id: number) => api.get<CohortDetail>(`/cohorts/${id}`),
  create: (data: { cdm_name: string; name: string; description?: string; criteria: CohortCriteria }) =>
    api.post('/cohorts/', data),
  update: (id: number, data: { name?: string; description?: string; criteria?: CohortCriteria }) =>
    api.put(`/cohorts/${id}`, data),
  delete: (id: number) => api.delete(`/cohorts/${id}`),
  execute: (id: number) => api.post(`/cohorts/${id}/execute`),
  exportUrl: (id: number, format: 'csv' | 'sql') =>
    `/api/cohorts/${id}/export?format=${format}`,
  count: (cdmName: string, criteria: CohortCriteria) =>
    api.post<{ patient_count: number; sql: string }>('/cohorts/count', { cdm_name: cdmName, criteria }),
  countApprox: (cdmName: string, criteria: CohortCriteria) =>
    api.post<{ patient_count: number; approximate: boolean }>('/cohorts/count/approximate', { cdm_name: cdmName, criteria }),
  attrition: (cdmName: string, criteria: CohortCriteria) =>
    api.post<{ steps: AttritionStep[] }>('/cohorts/attrition', { cdm_name: cdmName, criteria }),
  sample: (cdmName: string, criteria: CohortCriteria, limit?: number) =>
    api.post<{ patients: SamplePatient[]; count: number }>('/cohorts/sample', { cdm_name: cdmName, criteria, limit: limit || 10 }),
  sampleDetailed: (cdmName: string, criteria: CohortCriteria, limit?: number) =>
    api.post<{ patients: Record<string, any>[]; count: number; columns: { key: string; label: string; domain: string }[] }>('/cohorts/sample/detailed', { cdm_name: cdmName, criteria, limit: limit || 10 }),
  searchConcepts: (cdmName: string, query: string, domain?: string, vocabularyId?: string, standardOnly?: boolean) =>
    api.post<{ concepts: OmopConcept[]; count: number }>('/cohorts/concepts/search', {
      cdm_name: cdmName, query, domain: domain || null, vocabulary_id: vocabularyId || null, standard_only: standardOnly || false,
    }),
  listVocabularies: (cdmName: string) =>
    api.get<{ vocabularies: { vocabulary_id: string; vocabulary_name: string }[] }>('/cohorts/concepts/vocabularies', { params: { cdm_name: cdmName } }),
  listDomains: () =>
    api.get<{ domains: { name: string; table: string }[] }>('/cohorts/domains'),
  characterize: (cdmName: string, criteria: CohortCriteria, topN?: number, _signal?: AbortSignal, visitLevel?: boolean) =>
    api.post<{ task_id: string; status: string }>('/cohorts/characterize', { cdm_name: cdmName, criteria, top_n: topN || 25, visit_level: visitLevel || false }),
  characterizeStatus: (taskId: string) =>
    api.get<{ task_id: string; status: string; result?: CharacterizationResult; error?: string; completed?: number; total?: number; current_step?: string }>(`/cohorts/characterize/status/${taskId}`),
  characterizeCancel: (taskId: string) =>
    api.post(`/cohorts/characterize/cancel/${taskId}`),
  characterizeActive: () =>
    api.get<{ task_id: string | null; status: string }>('/cohorts/characterize/active'),
  saveCharacterization: (cohortId: number, characterization: CharacterizationResult) =>
    api.put(`/cohorts/${cohortId}/characterization`, { characterization }),
  getCharacterization: (cohortId: number) =>
    api.get<{ characterization: CharacterizationResult | null; characterized_at: string | null; version: number }>(`/cohorts/${cohortId}/characterization`),
  compare: (cdmName: string, cohortIdA: number, cohortIdB: number, visitLevel?: boolean) =>
    api.post<CohortComparisonResult>('/cohorts/compare', {
      cdm_name: cdmName,
      cohort_id_a: cohortIdA,
      cohort_id_b: cohortIdB,
      visit_level: visitLevel || false,
    }),
  sqlSchema: (cdmName: string) =>
    api.get<{ schema: string; tables: Record<string, string[]> }>(
      '/cohorts/sql/schema', { params: { cdm_name: cdmName } }
    ),
  executeSql: (cdmName: string, sql: string, limit?: number) =>
    api.post<{ columns: string[]; rows: Record<string, any>[]; row_count: number; truncated: boolean }>(
      '/cohorts/sql/execute', { cdm_name: cdmName, sql, limit: limit || 1000 }
    ),
  exportSql: (cdmName: string, sql: string) =>
    api.post('/cohorts/sql/export', { cdm_name: cdmName, sql }, { responseType: 'blob' }),
  patientJourney: (cdmName: string, personId: number) =>
    api.get<{ person: PatientJourneyInfo; events: PatientJourneyEvent[] }>(
      `/cohorts/patient/${personId}/journey`, { params: { cdm_name: cdmName } }
    ),
  // Pathways Analysis
  pathways: (cdmName: string, criteria: CohortCriteria, eventCohorts: PathwaysEventCohort[], options?: {
    max_depth?: number; min_cell_count?: number; combo_window?: number;
  }) =>
    api.post<{ task_id: string; status: string }>('/cohorts/pathways', {
      cdm_name: cdmName, criteria, event_cohorts: eventCohorts, ...(options || {}),
    }),
  pathwaysStatus: (taskId: string) =>
    api.get<{
      task_id: string; status: string; result?: PathwaysResult;
      error?: string; completed?: number; total?: number; current_step?: string;
    }>(`/cohorts/pathways/status/${taskId}`),
  pathwaysCancel: (taskId: string) =>
    api.post(`/cohorts/pathways/cancel/${taskId}`),
};

// Mapping endpoints
export const mappingApi = {
  dashboard: (cdmName: string) =>
    api.get<MappingDashboardData>(`/mapping/dashboard/${cdmName}`),
  strategyStats: (cdmName: string, domain?: string) =>
    api.get<{ cdm_name: string; domain: string | null; strategies: StrategyStats[]; total_decisions: number }>(
      `/mapping/strategies/${cdmName}`, { params: domain ? { domain } : {} }
    ),
  evolution: (cdmName: string, domain: string) =>
    api.get<{ evolution: MappingEvolutionPoint[] }>(`/mapping/dashboard/${cdmName}/evolution`, { params: { domain } }),
  unmapped: (cdmName: string, domain: string, page?: number, pageSize?: number, search?: string, includeMapped?: boolean) =>
    api.get<{ domain: string; total: number; page: number; page_size: number; total_pages: number; items: UnmappedItem[] }>(
      `/mapping/unmapped/${cdmName}/${domain}`, { params: { page: page || 1, page_size: pageSize || 50, search: search || '', include_mapped: includeMapped || false } }
    ),
  exportUnmappedUrl: (cdmName: string, domain: string) =>
    `/api/mapping/unmapped/${cdmName}/${domain}/export`,
  suggest: (cdmName: string, domain: string, sourceValue: string, sourceName?: string) =>
    api.post<{ source_value: string; suggestions: import('../types').MappingSuggestion[] }>('/mapping/suggest', {
      cdm_name: cdmName, domain, source_value: sourceValue, source_name: sourceName || '',
    }),
  suggestBatch: (cdmName: string, domain: string, limit?: number, options?: {
    enable_fuzzy?: boolean; enable_keyword?: boolean;
    enable_contextual?: boolean; enable_sapbert?: boolean;
  }) =>
    api.post<{ task_id: string; status: string }>('/mapping/suggest/batch', {
      cdm_name: cdmName, domain, limit: limit || 20, ...options,
    }),
  suggestStatus: (taskId: string) =>
    api.get<{ task_id: string; status: string; domain?: string; results?: SuggestionResult[]; error?: string }>(`/mapping/suggest/status/${taskId}`),
  suggestCancel: (taskId: string) =>
    api.post(`/mapping/suggest/cancel/${taskId}`),
  suggestActive: () =>
    api.get<{ active: { task_id: string; cdm_name: string; domain: string; status: string }[] }>('/mapping/suggest/active'),
  decide: (data: {
    cdm_name: string; domain: string; source_value: string; source_name?: string;
    action: string; target_concept_id?: number; target_concept_name?: string;
    target_vocabulary_id?: string; suggestion_source?: string; confidence_score?: number;
    reason?: string;
  }) => api.post('/mapping/decide', data),
  apply: (cdmName: string, domain: string, writeToCdm?: boolean) =>
    api.post('/mapping/apply', { cdm_name: cdmName, domain, write_to_cdm: writeToCdm || false }),
  applyPreview: (cdmName: string, domain: string) =>
    api.post<{ total_decisions: number; impacted_rows: number; impacted_persons: number }>(
      '/mapping/apply/preview', { cdm_name: cdmName, domain }
    ),
  exportStcmUrl: (cdmName: string, domain: string) =>
    `/api/mapping/apply/export/${cdmName}/${domain}`,
  history: (cdmName: string, domain?: string, action?: string, page?: number, pageSize?: number) =>
    api.get<{ total: number; page: number; total_pages: number; items: MappingDecisionEntry[] }>(
      `/mapping/history/${cdmName}`, { params: { domain: domain || '', action: action || '', page: page || 1, page_size: pageSize || 50 } }
    ),
  rollback: (decisionId: number) =>
    api.post(`/mapping/history/${decisionId}/rollback`),
  exportHistoryUrl: (cdmName: string, domain?: string) =>
    `/api/mapping/history/${cdmName}/export${domain ? `?domain=${domain}` : ''}`,
  conceptLookup: (cdmName: string, conceptId: number) =>
    api.get<{
      concept_id: number; concept_name: string; concept_code: string;
      vocabulary_id: string; domain_id: string; standard_concept: string | null;
      concept_class_id: string;
    }>(`/mapping/concept-lookup/${cdmName}/${conceptId}`),
};

// Concept Explorer endpoints
export const conceptApi = {
  search: (cdmName: string, params: {
    q?: string; domain?: string; vocabulary?: string;
    standard_only?: boolean; limit?: number; offset?: number;
  }) => api.get<{ concepts: any[]; total: number; limit: number; offset: number }>(
    '/concepts/search', { params: { cdm_name: cdmName, ...params } }
  ),
  details: (cdmName: string, conceptId: number) =>
    api.get<{ concept: any; relationships: any[]; synonyms: any[] }>(
      `/concepts/details/${conceptId}`, { params: { cdm_name: cdmName } }
    ),
  hierarchy: (cdmName: string, conceptId: number) =>
    api.get<{ concept_id: number; ancestors: any[]; descendants: any[] }>(
      `/concepts/hierarchy/${conceptId}`, { params: { cdm_name: cdmName } }
    ),
  sourceValues: (cdmName: string, conceptId: number) =>
    api.get<{ concept_id: number; source_values: any[] }>(
      `/concepts/source-values/${conceptId}`, { params: { cdm_name: cdmName } }
    ),
  domains: (cdmName: string) =>
    api.get<{ domains: { domain_id: string; count: number }[] }>(
      '/concepts/domains', { params: { cdm_name: cdmName } }
    ),
  vocabularies: (cdmName: string) =>
    api.get<{ vocabularies: { vocabulary_id: string; count: number }[] }>(
      '/concepts/vocabularies', { params: { cdm_name: cdmName } }
    ),
  searchSourceValue: (cdmName: string, params: {
    q?: string; domain?: string; limit?: number; offset?: number;
  }) => api.get<{ results: any[]; total: number; limit: number; offset: number }>(
    '/concepts/search-source-value', { params: { cdm_name: cdmName, ...params } }
  ),
  exportSourceValueUrl: (cdmName: string, q: string, domain?: string) =>
    `/api/concepts/search-source-value/export?cdm_name=${encodeURIComponent(cdmName)}&q=${encodeURIComponent(q)}${domain ? `&domain=${encodeURIComponent(domain)}` : ''}`,
  counts: (cdmName: string, conceptIds: number[]) =>
    api.post<{ counts: Record<number, { n_records: number; n_persons: number }> }>(
      `/concepts/counts?cdm_name=${encodeURIComponent(cdmName)}`,
      { concept_ids: conceptIds },
    ),
  sourceCounts: (cdmName: string, conceptIds: number[], domains?: string[]) =>
    api.post<{ counts: Record<number, { n_source_records: number; n_source_persons: number }> }>(
      `/concepts/counts/source?cdm_name=${encodeURIComponent(cdmName)}`,
      { concept_ids: conceptIds, domains: domains || null },
    ),
};

// OHDSI Tools endpoints
export const ohdsiApi = {
  run: (service: string, params: {
    cdm_name: string;
    results_schema: string;
    vocabulary_schema: string;
    cdm_version: string;
    cdm_source_name: string;
  }) => api.post(`/ohdsi/run/${service}`, params),
  stop: (service: string) => api.post(`/ohdsi/stop/${service}`),
  status: () => api.get<Record<string, { status: string; log_count: number }>>('/ohdsi/status'),
  logsUrl: async (service: string, offset?: number): Promise<string> => {
    const params = new URLSearchParams();
    if (offset) params.set('offset', String(offset));
    try {
      const resp = await api.post<{ ticket: string }>('/auth/sse-ticket');
      params.set('ticket', resp.data.ticket);
    } catch { /* will get 401 on SSE if ticket fails */ }
    const qs = params.toString();
    return `/api/ohdsi/logs/${service}${qs ? `?${qs}` : ''}`;
  },
  logsHistory: (service: string) =>
    api.get<{ status: string; logs: string[]; offset: number }>(`/ohdsi/logs/${service}/history`),
  files: (path?: string) => api.get(`/ohdsi/files/${path || ''}`),
  fileUrl: (path: string) => `/api/ohdsi/files/${path}`,
};

// Audit endpoints (admin only)
export const auditApi = {
  logs: (params: {
    date_from?: string; date_to?: string; date?: string;
    user?: string; action?: string; page?: number; page_size?: number;
  }) => api.get<{
    entries: AuditEntry[]; total: number; page: number;
    page_size: number; total_pages: number;
  }>('/audit/logs', { params }),
  stats: (params?: { date_from?: string; date_to?: string }) =>
    api.get<AuditStats>('/audit/stats', { params }),
  dates: () => api.get<{ dates: string[] }>('/audit/dates'),
  exportUrl: (params: { date_from?: string; date_to?: string; user?: string; action?: string }) => {
    const qs = new URLSearchParams();
    if (params.date_from) qs.set('date_from', params.date_from);
    if (params.date_to) qs.set('date_to', params.date_to);
    if (params.user) qs.set('user', params.user);
    if (params.action) qs.set('action', params.action);
    return `/api/audit/export?${qs.toString()}`;
  },
};

// Admin endpoints (admin only)
export const adminApi = {
  users: () => api.get<{ users: AdminUser[]; error?: string }>('/admin/users'),
  assignRole: (userId: string, role: string) =>
    api.post(`/admin/users/${userId}/roles`, { role }),
  removeRole: (userId: string, role: string) =>
    api.delete(`/admin/users/${userId}/roles/${role}`),
  toggleUser: (userId: string, enabled: boolean) =>
    api.put(`/admin/users/${userId}/toggle`, { enabled }),
  accessRequests: (statusFilter = 'pending') =>
    api.get<{ requests: AccessRequest[] }>('/admin/access-requests', { params: { status_filter: statusFilter } }),
  addUser: (username: string, role: string) =>
    api.post('/admin/users/add', { username, role }),
  approveRequest: (id: number) =>
    api.post(`/admin/access-requests/${id}/approve`),
  rejectRequest: (id: number) =>
    api.post(`/admin/access-requests/${id}/reject`),
};

// Public endpoint (no auth needed)
export const publicApi = {
  submitAccessRequest: (data: {
    username: string; requested_role: string;
    email?: string; first_name?: string; last_name?: string;
  }) => api.post('/access-requests', data),
};

// Concept Sets endpoints
export const conceptSetApi = {
  list: (cdmName?: string, domain?: string) =>
    api.get<{ concept_sets: ConceptSetSummary[] }>('/concept-sets/', { params: { cdm_name: cdmName, domain } }),
  get: (id: number) => api.get<ConceptSetDetail>(`/concept-sets/${id}`),
  create: (data: { name: string; cdm_name: string; domain?: string; description?: string; concepts: any[] }) =>
    api.post<{ id: number; name: string }>('/concept-sets/', data),
  update: (id: number, data: { name?: string; domain?: string; description?: string; concepts?: any[] }) =>
    api.put(`/concept-sets/${id}`, data),
  delete: (id: number) => api.delete(`/concept-sets/${id}`),
  resolve: (id: number, cdmName?: string) =>
    api.get<{ concept_ids: number[]; total: number }>(`/concept-sets/${id}/resolve`, { params: { cdm_name: cdmName } }),
  counts: (id: number, cdmName: string) =>
    api.post<{ counts: Record<number, { n_records: number; n_persons: number }> }>(`/concept-sets/${id}/counts`, { cdm_name: cdmName }),
};

// Incidence Rate endpoints
export const incidenceApi = {
  compute: (data: {
    cdm_name: string; target_cohort_id: number; outcome_cohort_id: number;
    time_at_risk_start?: number; time_at_risk_end?: string | number;
    strata?: string[]; age_groups?: any[]; clean_window?: number;
  }) => api.post<IncidenceResult>('/incidence/compute', data),
  save: (data: {
    cdm_name: string; name: string; target_cohort_id: number; outcome_cohort_id: number;
    parameters?: any; results?: any;
  }) => api.post<{ id: number; name: string }>('/incidence/save', data),
  list: (cdmName?: string) =>
    api.get<{ analyses: IncidenceAnalysisSummary[] }>('/incidence/', { params: { cdm_name: cdmName } }),
  get: (id: number) => api.get('/incidence/' + id),
};

// Estimation endpoints (Kaplan-Meier)
export const estimationApi = {
  kaplanMeier: (data: {
    cdm_name: string; target_cohort_id: number; outcome_cohort_id: number;
    time_at_risk_end?: number | null; time_unit?: string;
    strata?: string[]; confidence_level?: number;
  }) => api.post<KaplanMeierResult>('/estimation/kaplan-meier', data),
  save: (data: {
    cdm_name: string; name: string; analysis_type?: string;
    target_cohort_id: number; outcome_cohort_id: number;
    parameters?: any; results?: any;
  }) => api.post<{ id: number; name: string }>('/estimation/save', data),
  list: (cdmName?: string) =>
    api.get<{ analyses: EstimationAnalysisSummary[] }>('/estimation/', { params: { cdm_name: cdmName } }),
  get: (id: number) => api.get('/estimation/' + id),
};

// Data Management endpoints
export const dataManagementApi = {
  listCohorts: (cdmName: string) =>
    api.get<{ cohorts: any[] }>('/datamanagement/cohorts', { params: { cdm_name: cdmName } }),
  listTables: (cdmName: string) =>
    api.get<{ tables: { table_name: string; has_visit: boolean }[] }>('/datamanagement/tables', { params: { cdm_name: cdmName } }),
  listColumns: (cdmName: string, tableName: string) =>
    api.get<{ table: string; columns: { column_name: string; data_type: string }[] }>(
      `/datamanagement/tables/${tableName}/columns`, { params: { cdm_name: cdmName } }
    ),
  extractStart: (data: {
    cohort_id: number; same_visit_only: boolean;
    table_selections: { table: string; columns: string[] }[];
    preview_limit?: number;
  }) => api.post<{ task_id: string; status: string }>('/datamanagement/extract/start', data),
  extractStatus: (taskId: string) =>
    api.get<{
      task_id: string; status: string;
      completed?: number; total?: number; current_step?: string;
      cohort_name?: string;
      result?: {
        columns: string[]; rows: Record<string, any>[];
        total_count: number; preview_limit: number;
        cohort_name: string; sql: string;
      };
      error?: string;
    }>(`/datamanagement/extract/status/${taskId}`),
  extractDownloadUrl: (taskId: string) =>
    `/api/datamanagement/extract/download/${taskId}`,
  extractCancel: (taskId: string) =>
    api.post(`/datamanagement/extract/cancel/${taskId}`),
  extractActive: () =>
    api.get<{
      task_id: string | null; status: string;
      cdm_name?: string; cohort_name?: string;
      completed?: number; total?: number; current_step?: string;
    }>('/datamanagement/extract/active'),
  // Legacy synchronous endpoints (kept for backwards compat)
  extractPreview: (data: {
    cohort_id: number; same_visit_only: boolean;
    table_selections: { table: string; columns: string[] }[];
    preview_limit?: number;
  }) => api.post<{
    columns: string[]; rows: Record<string, any>[];
    total_count: number; preview_limit: number;
    cohort_name: string; sql: string;
  }>('/datamanagement/extract/preview', data),
  extractDownload: (data: {
    cohort_id: number; same_visit_only: boolean;
    table_selections: { table: string; columns: string[] }[];
  }) => api.post('/datamanagement/extract/download', data, { responseType: 'blob' }),
};

// CDM Access Control endpoints
export const cdmAccessApi = {
  list: (cdmName?: string, username?: string) =>
    api.get<{ grants: any[]; group_grants: any[] }>('/cdm-access/', { params: { cdm_name: cdmName, username } }),
  getAccessibleCdms: () =>
    api.get<{ cdms: string[] }>('/cdm-access/cdms-for-user'),
  grant: (cdmName: string, username: string) =>
    api.post('/cdm-access/grant', { cdm_name: cdmName, username }),
  grantGroup: (cdmName: string, groupName: string) =>
    api.post('/cdm-access/grant-group', { cdm_name: cdmName, group_name: groupName }),
  revoke: (cdmName: string, username: string) =>
    api.post('/cdm-access/revoke', { cdm_name: cdmName, username }),
  revokeGroup: (cdmName: string, groupName: string) =>
    api.post('/cdm-access/revoke-group', { cdm_name: cdmName, group_name: groupName }),
  clearCdm: (cdmName: string) =>
    api.delete(`/cdm-access/cdm/${cdmName}`),
};

// Notifications endpoints
export const notificationsApi = {
  list: (unreadOnly?: boolean, limit?: number, notifType?: string) =>
    api.get<{ notifications: any[] }>('/notifications/', { params: { unread_only: unreadOnly, limit, notif_type: notifType } }),
  badges: () =>
    api.get<{ badges: Record<string, number>; total: number }>('/notifications/badges'),
  items: (notifType?: string) =>
    api.get<{ items: Record<string, { item_id: string; notif_id: number }[]> }>('/notifications/items', { params: { notif_type: notifType } }),
  markRead: (id: number) =>
    api.post(`/notifications/${id}/read`),
  markItemRead: (notifType: string, itemId: string) =>
    api.post('/notifications/read-item', null, { params: { notif_type: notifType, item_id: itemId } }),
  markAllRead: (type?: string) =>
    api.post('/notifications/read-all', null, { params: { notif_type: type } }),
};

// Favorites endpoints
export const favoritesApi = {
  list: (itemType?: string) =>
    api.get<{ favorites: any[] }>('/favorites/', { params: { item_type: itemType } }),
  add: (data: { item_type: string; item_id: string; item_label?: string; item_meta?: any }) =>
    api.post('/favorites/', data),
  remove: (id: number) =>
    api.delete(`/favorites/${id}`),
};

// Saved Queries endpoints
export const savedQueriesApi = {
  list: (cdmName?: string) =>
    api.get<{ queries: any[] }>('/saved-queries/', { params: { cdm_name: cdmName } }),
  create: (data: { cdm_name: string; name: string; sql: string; description?: string }) =>
    api.post('/saved-queries/', data),
  update: (id: number, data: { name?: string; sql?: string; description?: string }) =>
    api.put(`/saved-queries/${id}`, data),
  delete: (id: number) =>
    api.delete(`/saved-queries/${id}`),
};

// Cohort Templates endpoints
export const cohortTemplatesApi = {
  list: (category?: string) =>
    api.get<{ templates: any[] }>('/cohort-templates/', { params: { category } }),
  categories: () =>
    api.get<{ categories: string[] }>('/cohort-templates/categories'),
  get: (id: number) =>
    api.get('/cohort-templates/' + id),
  create: (data: { name: string; category?: string; description?: string; criteria_json: any }) =>
    api.post('/cohort-templates/', data),
  delete: (id: number) =>
    api.delete(`/cohort-templates/${id}`),
};

// User Groups endpoints
export const groupApi = {
  list: () =>
    api.get<{ groups: GroupSummary[] }>('/groups/'),
  get: (groupName: string) =>
    api.get<GroupDetail>(`/groups/${encodeURIComponent(groupName)}`),
  create: (data: { name: string; description?: string; members?: string[] }) =>
    api.post('/groups/', data),
  update: (groupName: string, data: { description?: string; members?: string[] }) =>
    api.put(`/groups/${encodeURIComponent(groupName)}`, data),
  delete: (groupName: string) =>
    api.delete(`/groups/${encodeURIComponent(groupName)}`),
  addMember: (groupName: string, username: string) =>
    api.post(`/groups/${encodeURIComponent(groupName)}/members`, { username }),
  removeMember: (groupName: string, username: string) =>
    api.delete(`/groups/${encodeURIComponent(groupName)}/members/${encodeURIComponent(username)}`),
};

// Cohort Sharing endpoints
export const cohortSharingApi = {
  listShares: (cohortId: number) =>
    api.get<CohortShareInfo>(`/cohorts/${cohortId}/shares`),
  share: (cohortId: number, shareType: string, shareTarget?: string) =>
    api.post(`/cohorts/${cohortId}/share`, { share_type: shareType, share_target: shareTarget || '' }),
  unshare: (cohortId: number, shareType: string, shareTarget?: string) =>
    api.post(`/cohorts/${cohortId}/unshare`, { share_type: shareType, share_target: shareTarget || '' }),
};

// OPAL users (lightweight, for sharing dropdowns)
export const usersApi = {
  listOpalUsers: () =>
    api.get<{ users: string[] }>('/users/list'),
};

// Global Search endpoint
export const searchApi = {
  search: (q: string, cdmName?: string, limit?: number) =>
    api.get<{ query: string; total: number; results: Record<string, any[]> }>(
      '/search/', { params: { q, cdm_name: cdmName, limit } }
    ),
};

// Quality Conformity endpoints (background thread + persist)
export const conformityApi = {
  run: (cdmName: string) =>
    api.post<{ cdm_name: string; analysis_id: string; status: string }>(
      '/quality/conformity', { cdm_name: cdmName, domain: 'conformity' }
    ),
  cancel: (analysisId: string) =>
    api.post(`/quality/conformity/cancel/${analysisId}`),
  get: (cdmName: string) =>
    api.get<{ cdm_name: string; snapshot_id?: number; version?: number; created_at?: string; result: any | null }>(
      `/quality/conformity/${encodeURIComponent(cdmName)}`
    ),
};

export default api;
