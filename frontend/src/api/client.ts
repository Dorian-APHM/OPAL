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
  MappingDashboardData,
  MappingEvolutionPoint,
  UnmappedItem,
  SuggestionResult,
  MappingDecisionEntry,
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
  searchConcepts: (cdmName: string, query: string, domain?: string, vocabularyId?: string) =>
    api.post<{ concepts: OmopConcept[]; count: number }>('/cohorts/concepts/search', {
      cdm_name: cdmName, query, domain: domain || null, vocabulary_id: vocabularyId || null,
    }),
  listVocabularies: (cdmName: string) =>
    api.get<{ vocabularies: { vocabulary_id: string; vocabulary_name: string }[] }>('/cohorts/concepts/vocabularies', { params: { cdm_name: cdmName } }),
  listDomains: () =>
    api.get<{ domains: { name: string; table: string }[] }>('/cohorts/domains'),
  exportDirect: (cdmName: string, criteria: CohortCriteria) =>
    api.post('/cohorts/export/direct', { cdm_name: cdmName, criteria }, { responseType: 'blob' }),
};

// Mapping endpoints
export const mappingApi = {
  dashboard: (cdmName: string) =>
    api.get<MappingDashboardData>(`/mapping/dashboard/${cdmName}`),
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
  decideBulk: (data: {
    cdm_name: string; domain: string; action: string;
    min_confidence?: number; source_values?: string[];
  }) => api.post('/mapping/decide/bulk', data),
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
  listReferences: () =>
    api.get<{ references: { name: string; domain: string; count: number; uploaded_at: string | null }[] }>('/mapping/reference'),
  uploadReference: (name: string, domain: string, file: File) => {
    const form = new FormData();
    form.append('name', name);
    form.append('domain', domain);
    form.append('file', file);
    return api.post<{ name: string; domain: string; count: number }>('/mapping/reference/upload', form);
  },
  deleteReference: (name: string) =>
    api.delete(`/mapping/reference/${name}`),
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

// i18n
export const i18nApi = {
  getTranslations: (lang: string) => api.get(`/i18n/${lang}`),
};

export default api;
