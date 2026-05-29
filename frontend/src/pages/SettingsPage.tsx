import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { cdmApi, conceptApi, cohortLlmApi } from '../api/client';
import { Card, Button, Input, NumberInput, Alert, Tag, useToast } from '../components/ui';
import SchemaCategoriesEditor from '../components/SchemaCategoriesEditor';
import { Database, RefreshCw, Trash2, Check, X, Loader, Cpu } from 'lucide-react';

interface Props {
  selectedCdm: string | null;
}

export default function SettingsPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const [loading, setLoading] = useState(false);

  // Form state
  const [omopSchema, setOmopSchema] = useState('');
  const [schemaCategories, setSchemaCategories] = useState<Record<string, string>>({});
  const [topUnmappedTerms, setTopUnmappedTerms] = useState<number | null>(null);
  const [topConcepts, setTopConcepts] = useState<number | null>(null);
  const [maxRecordsPerPerson, setMaxRecordsPerPerson] = useState<number | null>(null);
  const [maxObservationMonths, setMaxObservationMonths] = useState<number | null>(null);
  const [comparisonAlertThreshold, setComparisonAlertThreshold] = useState<number | null>(null);

  useEffect(() => {
    if (selectedCdm) {
      cdmApi.getSettings(selectedCdm).then((res) => {
        const data = res.data;
        setOmopSchema(data.omop_schema ?? '');
        setSchemaCategories(data.schema_categories ?? {});
        setTopUnmappedTerms(data.top_unmapped_terms ?? null);
        setTopConcepts(data.top_concepts ?? null);
        setMaxRecordsPerPerson(data.max_records_per_person ?? null);
        setMaxObservationMonths(data.max_observation_months ?? null);
        setComparisonAlertThreshold(data.comparison_alert_threshold ?? null);
      });
    }
  }, [selectedCdm]);

  const handleSave = async () => {
    if (!selectedCdm) return;
    try {
      setLoading(true);
      await cdmApi.updateSettings(selectedCdm, {
        omop_schema: omopSchema,
        schema_categories: schemaCategories,
        top_unmapped_terms: topUnmappedTerms ?? undefined,
        top_concepts: topConcepts ?? undefined,
        max_records_per_person: maxRecordsPerPerson ?? undefined,
        max_observation_months: maxObservationMonths ?? undefined,
        comparison_alert_threshold: comparisonAlertThreshold ?? undefined,
      });
      toast.success(t('settings.saved'));
    } catch {
      toast.error(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h3 className="text-2xl font-bold text-text-bright mb-4">
        {t('settings.title')}{selectedCdm ? ` — ${selectedCdm}` : ''}
      </h3>
      {!selectedCdm && <Alert message={t('cdm.select_cdm')} type="info" showIcon />}
      {selectedCdm && (<>
      <Card className="max-w-lg">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.omop_schema')} <span className="text-red-400">*</span></label>
            <Input value={omopSchema} onChange={(e) => setOmopSchema(e.target.value)} />
          </div>
          <SchemaCategoriesEditor
            value={schemaCategories}
            onChange={setSchemaCategories}
            defaultSchema={omopSchema}
          />
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.top_unmapped_terms')} <span className="text-red-400">*</span></label>
            <NumberInput value={topUnmappedTerms ?? undefined} onChange={(v) => setTopUnmappedTerms(v)} min={1} max={500} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.top_concepts')} <span className="text-red-400">*</span></label>
            <NumberInput value={topConcepts ?? undefined} onChange={(v) => setTopConcepts(v)} min={1} max={500} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.max_records_per_person')} <span className="text-red-400">*</span></label>
            <NumberInput value={maxRecordsPerPerson ?? undefined} onChange={(v) => setMaxRecordsPerPerson(v)} min={10} max={1000} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.max_observation_months')} <span className="text-red-400">*</span></label>
            <NumberInput value={maxObservationMonths ?? undefined} onChange={(v) => setMaxObservationMonths(v)} min={12} max={600} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.comparison_threshold')} <span className="text-red-400">*</span></label>
            <NumberInput value={comparisonAlertThreshold ?? undefined} onChange={(v) => setComparisonAlertThreshold(v)} min={0.1} max={50} step={0.5} />
          </div>
          <Button variant="primary" onClick={handleSave} loading={loading}>
            {t('common.save')}
          </Button>
        </div>
      </Card>

      {/* Source Value Cache */}
      <SourceValueCacheCard cdmName={selectedCdm} />
      </>)}

      {/* Cohort-LLM on-premise config (admin, instance-wide) */}
      <CohortLlmConfigCard />
    </div>
  );
}


// ──── Cohort-LLM on-premise config (admin, instance-wide) ────
// Only rendered in on-premise mode for admins (GET /settings is admin-gated).

function CohortLlmConfigCard() {
  const { t } = useTranslation();
  const toast = useToast();
  const [visible, setVisible] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    cohortLlmApi.config().then((res) => {
      if (res.data.mode !== 'on-premise') return;       // only relevant on-premise
      cohortLlmApi.getSettings()                          // admin-only -> 403 hides the card
        .then((s) => {
          setBaseUrl(s.data.base_url ?? '');
          setModel(s.data.model ?? '');
          setHasKey(s.data.has_api_key);
          setVisible(true);
        })
        .catch(() => setVisible(false));
    }).catch(() => { /* feature off / unreachable */ });
  }, []);

  if (!visible) return null;

  const save = async () => {
    try {
      setLoading(true);
      const payload: { base_url: string; model: string; api_key?: string } = { base_url: baseUrl, model };
      if (apiKey) payload.api_key = apiKey;               // only send when (re)set
      const res = await cohortLlmApi.updateSettings(payload);
      setHasKey(res.data.has_api_key);
      setApiKey('');
      toast.success(t('settings.saved'));
    } catch {
      toast.error(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="max-w-lg mt-4">
      <div className="flex items-center gap-2 mb-2">
        <Cpu className="h-4 w-4 text-emerald-accent" />
        <span className="font-semibold text-text-bright text-sm">
          {t('settings.cohort_llm_title', 'LLM Cohorte (on-premise)')}
        </span>
      </div>
      <p className="text-xs text-text-muted mb-3">
        {t('settings.cohort_llm_help',
          "Endpoint OpenAI-compatible de votre LLM. La clé API est chiffrée et n'est jamais réaffichée.")}
      </p>
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1.5">
            {t('settings.cohort_llm_base_url', 'URL (base OpenAI-compatible)')}
          </label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://llm.chu.fr/v1" />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1.5">
            {t('settings.cohort_llm_model', 'Modèle')}
          </label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="llama3.1:70b-instruct" />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-muted mb-1.5">
            {t('settings.cohort_llm_api_key', 'Clé API')}
          </label>
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                 placeholder={hasKey ? '•••••••• (inchangée)' : t('settings.cohort_llm_api_key_ph', 'optionnelle')} />
        </div>
        <Button variant="primary" onClick={save} loading={loading}>
          {t('common.save')}
        </Button>
      </div>
    </Card>
  );
}


// ──── Source Value Cache Management ────

interface CacheDomainStatus {
  domain: string;
  status: string;
  row_count: number;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

function SourceValueCacheCard({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [domains, setDomains] = useState<CacheDomainStatus[]>([]);
  const [populating, setPopulating] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const resp = await conceptApi.sourceValueCacheStatus(cdmName);
      setDomains(resp.data.domains);
      const isPopulating = resp.data.populating;
      setPopulating(isPopulating);
      return isPopulating;
    } catch {
      return false;
    }
  }, [cdmName]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      const stillRunning = await loadStatus();
      if (!stillRunning) {
        stopPolling();
        toast.success(t('settings.cache_populated', 'Source value cache populated'));
      }
    }, 3000);
  }, [loadStatus, stopPolling, toast, t]);

  // Load on mount + auto-start polling if already running
  useEffect(() => {
    loadStatus().then(isPopulating => {
      if (isPopulating) startPolling();
    });
    return stopPolling;
  }, [loadStatus, startPolling, stopPolling]);

  const handlePopulate = async () => {
    try {
      await conceptApi.populateSourceValueCacheUrl_post(cdmName);
      setDomains([]);          // clear stale rows so a rebuild shows fresh progress
      setPopulating(true);
      startPolling();
    } catch {
      toast.error('Failed to start cache population');
    }
  };

  const handleCancel = async () => {
    try {
      await conceptApi.cancelSourceValueCachePopulate(cdmName);
      toast.info(t('settings.cache_cancelling', 'Cancelling...'));
    } catch { /* ignore */ }
  };

  const handleClear = async () => {
    try {
      await conceptApi.clearSourceValueCache(cdmName);
      toast.success(t('settings.cache_cleared', 'Cache cleared'));
      loadStatus();
    } catch {
      toast.error('Failed to clear cache');
    }
  };

  const totalRows = domains.reduce((s, d) => s + d.row_count, 0);
  const doneDomains = domains.filter(d => d.status === 'done').length;
  const runningDomain = domains.find(d => d.status === 'running');

  return (
    <Card className="max-w-lg mt-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-emerald-accent" />
          <span className="font-semibold text-text-bright text-sm">
            {t('settings.source_value_cache', 'Source Value Cache')}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {domains.length > 0 && !populating && (
            <Button size="small" onClick={handleClear}>
              <Trash2 className="h-3 w-3 mr-1" />
              {t('common.clear', 'Clear')}
            </Button>
          )}
          {populating ? (
            <Button size="small" variant="danger" onClick={handleCancel}>
              <X className="h-3 w-3 mr-1" />
              {t('common.cancel', 'Cancel')}
            </Button>
          ) : (
            <Button size="small" variant="primary" onClick={handlePopulate}>
              <RefreshCw className="h-3 w-3 mr-1" />
              {domains.length > 0
                ? t('settings.refresh_cache', 'Refresh')
                : t('settings.build_cache', 'Build Cache')
              }
            </Button>
          )}
        </div>
      </div>

      {populating && (
        <div className="mb-3">
          <div className="flex justify-between text-xs text-text-muted mb-1">
            <span>{runningDomain ? runningDomain.domain : t('common.starting', 'Starting...')}</span>
            <span>{doneDomains}/{domains.length || '?'}</span>
          </div>
          <div className="w-full bg-surface-dark rounded-full h-1.5">
            <div
              className="bg-emerald-accent h-1.5 rounded-full transition-all"
              style={{ width: domains.length ? `${(doneDomains / domains.length) * 100}%` : '0%' }}
            />
          </div>
        </div>
      )}

      {domains.length === 0 && !populating ? (
        <p className="text-xs text-text-muted">
          {t('settings.no_cache', 'No cache built yet. Build the cache to speed up source value searches.')}
        </p>
      ) : domains.length > 0 ? (
        <div>
          <div className="text-xs text-text-muted mb-2">
            {doneDomains}/{domains.length} domains · {totalRows.toLocaleString()} rows cached
          </div>
          <div className="space-y-1 max-h-48 overflow-auto">
            {domains.map(d => (
              <div key={d.domain} className="flex items-center justify-between text-xs px-2 py-1 bg-surface-dark rounded">
                <span className="text-text-bright">{d.domain}</span>
                <div className="flex items-center gap-2">
                  <span className="text-text-dim">{d.row_count.toLocaleString()}</span>
                  {d.status === 'done' ? (
                    <Check className="h-3 w-3 text-green-400" />
                  ) : d.status === 'running' && populating ? (
                    <Loader className="h-3 w-3 text-blue-400 animate-spin" />
                  ) : d.status === 'error' || d.status === 'running' ? (
                    <X className="h-3 w-3 text-red-400" title={d.error_message || 'Interrompu'} />
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
