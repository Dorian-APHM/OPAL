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
} from '../types';

const api = axios.create({
  baseURL: '/api',
});

// Token getter — set by AuthProvider once Keycloak is initialized
let _getToken: (() => string | undefined) | null = null;
export function setTokenGetter(getter: () => string | undefined) {
  _getToken = getter;
}

// Attach Keycloak Bearer token to all API requests
api.interceptors.request.use((config) => {
  const token = _getToken?.();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Unified error response interceptor
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response) {
      const { status, data } = error.response;
      const detail = data?.detail || data?.message || data?.error;
      if (detail && typeof detail === 'string') {
        error.message = detail;
      }
      if (status === 401) {
        error.message = 'Session expired. Please log in again.';
      } else if (status === 504) {
        error.message = detail || 'Query timed out. Try a simpler query.';
      } else if (status === 502) {
        error.message = detail || 'External database connection error.';
      }
    } else if (error.code === 'ERR_NETWORK') {
      error.message = 'Network error. Please check your connection.';
    }
    return Promise.reject(error);
  },
);

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
  searchConcepts: (cdmName: string, query: string, domain?: string, vocabularyId?: string) =>
    api.post<{ concepts: OmopConcept[]; count: number }>('/cohorts/concepts/search', {
      cdm_name: cdmName, query, domain: domain || null, vocabulary_id: vocabularyId || null,
    }),
  listVocabularies: (cdmName: string) =>
    api.get<{ vocabularies: { vocabulary_id: string; vocabulary_name: string }[] }>('/cohorts/concepts/vocabularies', { params: { cdm_name: cdmName } }),
  listDomains: () =>
    api.get<{ domains: { name: string; table: string }[] }>('/cohorts/domains'),
  characterize: (cdmName: string, criteria: CohortCriteria, topN?: number, signal?: AbortSignal, visitLevel?: boolean) =>
    api.post<CharacterizationResult>('/cohorts/characterize', { cdm_name: cdmName, criteria, top_n: topN || 25, visit_level: visitLevel || false }, { signal }),
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
  unmapped: (cdmName: string, domain: string, page?: number, pageSize?: number, search?: string) =>
    api.get<{ domain: string; total: number; page: number; page_size: number; total_pages: number; items: UnmappedItem[] }>(
      `/mapping/unmapped/${cdmName}/${domain}`, { params: { page: page || 1, page_size: pageSize || 50, search: search || '' } }
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
    api.post<{ domain: string; results: SuggestionResult[] }>('/mapping/suggest/batch', {
      cdm_name: cdmName, domain, limit: limit || 20, ...options,
    }),
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
  logsUrl: (service: string, offset?: number) => {
    const token = _getToken?.();
    const params = new URLSearchParams();
    if (offset) params.set('offset', String(offset));
    if (token) params.set('token', token);
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
  approveRequest: (id: number) =>
    api.post(`/admin/access-requests/${id}/approve`),
  rejectRequest: (id: number) =>
    api.post(`/admin/access-requests/${id}/reject`),
};

// Public endpoint (no auth needed)
export const publicApi = {
  submitAccessRequest: (data: {
    username: string; email: string;
    first_name: string; last_name: string; requested_role: string;
  }) => api.post('/access-requests', data),
};

export default api;
