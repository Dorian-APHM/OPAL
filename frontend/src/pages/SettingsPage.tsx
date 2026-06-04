import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { cdmApi, conceptApi, cohortLlmApi, sapbertApi, type SapbertDomainState } from '../api/client';
import { Card, Button, Input, NumberInput, Alert, Tag, useToast, Checkbox, Confirm } from '../components/ui';
import SchemaCategoriesEditor from '../components/SchemaCategoriesEditor';
import { Database, RefreshCw, Trash2, Check, X, Loader, Cpu, Sparkles } from 'lucide-react';

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
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 items-start">
      {selectedCdm && (<>
      <Card>
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

      {/* Cohort-LLM card: on-premise LLM config (admin) + RAG index build */}
      <CohortLlmConfigCard selectedCdm={selectedCdm} />
      </div>
    </div>
  );
}


// ──── Cohort-LLM card: on-premise LLM config (admin) + RAG index build ────
// Shown for admins (GET /settings is admin-gated) when the feature is on:
//   on-premise -> LLM endpoint config + RAG build button
//   embedded   -> RAG build button only
//   off        -> hidden

function CohortLlmConfigCard({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [visible, setVisible] = useState(false);
  const [mode, setMode] = useState<'embedded' | 'on-premise'>('embedded');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    cohortLlmApi.config().then((res) => {
      const m = res.data.mode;
      if (m === 'off') return;                            // off -> no card
      cohortLlmApi.getSettings()                          // admin-gate (200 admin / 403 else)
        .then((s) => {
          setMode(m);
          if (m === 'on-premise') {
            setBaseUrl(s.data.base_url ?? '');
            setModel(s.data.model ?? '');
            setHasKey(s.data.has_api_key);
          }
          setVisible(true);
        })
        .catch(() => setVisible(false));                  // non-admin / error -> hidden
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

  const rebuildRag = async () => {
    if (!selectedCdm) return;
    try {
      setRebuilding(true);
      await cohortLlmApi.rebuildRag(selectedCdm);
      toast.success(t('settings.cohort_llm_rag_done', 'Index RAG reconstruit'));
    } catch {
      toast.error(t('common.error'));
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <Card>
      {mode === 'on-premise' && (
        <>
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
        </>
      )}

      {/* RAG index build — shown in both embedded and on-premise */}
      <div className={mode === 'on-premise' ? 'border-t border-glass pt-4 mt-4' : ''}>
        <div className="flex items-center gap-2 mb-1.5">
          <Sparkles className="h-4 w-4 text-emerald-accent" />
          <span className="font-semibold text-text-bright text-sm">
            {t('settings.cohort_llm_rag_title', "Index RAG de l'assistant IA")}
          </span>
        </div>
        <p className="text-xs text-text-muted mb-3">
          {t('settings.cohort_llm_rag_help',
            "Reconstruit l'index sémantique (embeddings SapBERT) à partir du Source Value Cache du CDM. À relancer après une mise à jour du cache.")}
        </p>
        <Button variant="default" onClick={() => setConfirmOpen(true)} loading={rebuilding} disabled={!selectedCdm}>
          {t('settings.cohort_llm_rag_build', "Construire l'index RAG")}{selectedCdm ? ` — ${selectedCdm}` : ''}
        </Button>
        {!selectedCdm && (
          <p className="text-xs text-text-muted mt-1.5">
            {t('settings.cohort_llm_rag_need_cdm', 'Sélectionnez un CDM pour construire son index.')}
          </p>
        )}
      </div>

      <Confirm
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={rebuildRag}
        title={t('settings.cohort_llm_rag_confirm_title', "Construire l'index RAG ?")}
        description={t('settings.cohort_llm_rag_confirm',
          "Avez-vous bien construit le Source Value Cache de ce CDM avant de lancer cette étape ? L'index est calculé à partir de ce cache.")}
        confirmText={t('settings.cohort_llm_rag_build', "Construire l'index RAG")}
      />
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
  const [sapbertEnabled, setSapbertEnabled] = useState(false);   // feature available
  const [useSapbert, setUseSapbert] = useState(false);           // checkbox for next build
  const [sapbertDomains, setSapbertDomains] = useState<SapbertDomainState[]>([]);
  const [sapbertBuilding, setSapbertBuilding] = useState(false);
  const [sapbertCancelling, setSapbertCancelling] = useState(false);
  const [buildable, setBuildable] = useState<{ domain: string; labelled: number }[]>([]);
  const [buildSel, setBuildSel] = useState<Record<string, boolean>>({});
  const [buildingDomains, setBuildingDomains] = useState<string[]>([]);  // domains in the current build
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sapbertPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const stopSapbertPolling = useCallback(() => {
    if (sapbertPollRef.current) {
      clearInterval(sapbertPollRef.current);
      sapbertPollRef.current = null;
    }
  }, []);

  // Poll SapBERT build progress (standalone build over the existing cache).
  const startSapbertPolling = useCallback(() => {
    stopSapbertPolling();
    sapbertPollRef.current = setInterval(async () => {
      try {
        const sb = await sapbertApi.domains(cdmName);
        setSapbertDomains(sb.data.domains ?? []);
        setSapbertBuilding(sb.data.building);
        if (!sb.data.building) {
          stopSapbertPolling();
          setSapbertCancelling(false);
          const dl = sb.data.domains ?? [];
          if (dl.some(d => d.status === 'cancelled')) toast.info(t('settings.sapbert_cancelled', 'SapBERT build cancelled'));
          else if (dl.some(d => d.status === 'error')) toast.error(t('settings.sapbert_build_error', 'SapBERT build finished with errors'));
          else toast.success(t('settings.sapbert_built', 'SapBERT suggestions built'));
        }
      } catch { /* ignore */ }
    }, 3000);
  }, [cdmName, stopSapbertPolling, toast, t]);

  // Is the SapBERT feature enabled on the backend? (gates the checkbox)
  useEffect(() => {
    sapbertApi.config().then(r => setSapbertEnabled(!!r.data.enabled)).catch(() => {});
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const resp = await conceptApi.sourceValueCacheStatus(cdmName);
      const list: CacheDomainStatus[] = resp.data.domains ?? [];
      setDomains(list);
      const isPopulating = resp.data.populating;
      setPopulating(isPopulating);
      if (sapbertEnabled) {
        try {
          const sb = await sapbertApi.domains(cdmName);
          setSapbertDomains(sb.data.domains ?? []);
          setSapbertBuilding(sb.data.building);
        } catch { /* ignore */ }
      }
      const hasError = list.some(d => d.status === 'error' || d.error_message);
      return { populating: isPopulating, hasError };
    } catch {
      return { populating: false, hasError: false };
    }
  }, [cdmName, sapbertEnabled]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      const { populating: stillRunning, hasError } = await loadStatus();
      if (!stillRunning) {
        stopPolling();
        // Don't claim success when the population actually failed.
        if (hasError) toast.error(t('common.error', 'An error occurred'));
        else toast.success(t('settings.cache_populated', 'Source value cache populated'));
      }
    }, 3000);
  }, [loadStatus, stopPolling, toast, t]);

  // Load on mount + auto-start polling if already running
  useEffect(() => {
    loadStatus().then(({ populating: isPopulating }) => {
      if (isPopulating) startPolling();
    });
    return stopPolling;
  }, [loadStatus, startPolling, stopPolling]);

  // When the SapBERT feature is on, load its per-domain state + the buildable
  // domains, and resume polling if a standalone build is already in progress.
  useEffect(() => {
    if (!sapbertEnabled) return;
    sapbertApi.domains(cdmName).then(r => {
      setSapbertDomains(r.data.domains ?? []);
      setSapbertBuilding(r.data.building);
      if (r.data.building) startSapbertPolling();
    }).catch(() => {});
    sapbertApi.buildable(cdmName).then(r => {
      const list = r.data.domains ?? [];
      setBuildable(list);
      setBuildSel(Object.fromEntries(list.map(d => [d.domain, true])));  // all selected by default
    }).catch(() => { setBuildable([]); });
    return stopSapbertPolling;
  }, [sapbertEnabled, cdmName, startSapbertPolling, stopSapbertPolling]);

  const handleBuildSapbert = async () => {
    const selected = buildable.map(d => d.domain).filter(d => buildSel[d]);
    if (buildable.length > 0 && selected.length === 0) {
      toast.error(t('settings.sapbert_pick_domain', 'Select at least one domain to build'));
      return;
    }
    try {
      // If everything is selected, send no filter (build all); else send the subset.
      const r = await sapbertApi.build(cdmName, selected.length === buildable.length ? undefined : selected);
      setBuildingDomains(r.data.domains ?? selected);  // remember what THIS build covers
      setSapbertDomains([]);   // clear stale rows; polling repopulates with fresh pending → done
      setSapbertBuilding(true);
      startSapbertPolling();
    } catch {
      toast.error(t('settings.sapbert_build_failed', 'Failed to start SapBERT build'));
    }
  };

  const handleCancelSapbert = async () => {
    setSapbertCancelling(true);
    try {
      await sapbertApi.buildCancel(cdmName);
      // The build stops at the next safe point (between encoding steps), not instantly.
      toast.info(t('settings.sapbert_cancelling', 'Cancelling… stops after the current step'));
    } catch {
      setSapbertCancelling(false);
    }
  };

  const handlePopulate = async () => {
    try {
      await conceptApi.populateSourceValueCacheUrl_post(cdmName, useSapbert);
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
    <Card>
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

      {sapbertEnabled && !populating && (
        <div className="mb-3">
          <Checkbox checked={useSapbert} onChange={setUseSapbert}>
            {t('settings.sapbert_build', 'Build SapBERT semantic suggestions')}
          </Checkbox>
          <p className="text-[11px] text-text-dim mt-1 ml-6">
            {t('settings.sapbert_hint', 'Multilingual semantic mapping suggestions for domains that have labels (référentiels or source names). Longer build.')}
          </p>
        </div>
      )}

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

      {sapbertEnabled && domains.length > 0 && (
        <div className="mt-3 pt-3 border-t border-glass-border">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-emerald-accent" />
              <span className="text-xs font-semibold text-text-bright">
                {t('settings.sapbert_status', 'SapBERT suggestions')}
              </span>
            </div>
            {sapbertBuilding ? (
              <Button size="small" variant="danger" onClick={handleCancelSapbert} disabled={sapbertCancelling}>
                <X className="h-3 w-3 mr-1" />
                {sapbertCancelling ? t('settings.sapbert_cancelling_short', 'Cancelling…') : t('common.cancel', 'Cancel')}
              </Button>
            ) : (
              <Button size="small" onClick={handleBuildSapbert} disabled={populating}>
                <Sparkles className="h-3 w-3 mr-1" />
                {sapbertDomains.length > 0
                  ? t('settings.rebuild_sapbert', 'Rebuild SapBERT')
                  : t('settings.build_sapbert', 'Build SapBERT')}
              </Button>
            )}
          </div>
          <p className="text-[11px] text-text-dim mb-2">
            {t('settings.sapbert_build_existing', 'Runs on the existing cache — no need to rebuild it.')}
          </p>

          {!sapbertBuilding && buildable.length > 0 && (
            <div className="mb-3">
              <div className="text-[11px] text-text-dim mb-1">
                {t('settings.sapbert_pick_domains', 'Domains to build (uncheck to exclude, e.g. Drug — slow):')}
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {buildable.map(d => (
                  <Checkbox
                    key={d.domain}
                    checked={!!buildSel[d.domain]}
                    onChange={c => setBuildSel(prev => ({ ...prev, [d.domain]: c }))}
                  >
                    <span className="text-xs">{d.domain} <span className="text-text-dim">({d.labelled.toLocaleString()})</span></span>
                  </Checkbox>
                ))}
              </div>
            </div>
          )}

          {(() => {
            // Show built domains (rows>0), the active ones, and those in THIS build —
            // hide stale error/0 rows (e.g. a domain excluded from the current build).
            const visible = sapbertDomains.filter(d =>
              d.row_count > 0 || d.status === 'running' || d.status === 'pending' || buildingDomains.includes(d.domain)
            );
            if (visible.length > 0) return (
              <div className="space-y-1 max-h-40 overflow-auto">
                {visible.map(d => (
                  <div key={d.domain} className="flex items-center justify-between text-xs px-2 py-1 bg-surface-dark rounded">
                    <span className="text-text-bright">{d.domain}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-text-dim">{d.row_count.toLocaleString()}</span>
                      {d.status === 'done' ? (
                        <Check className="h-3 w-3 text-green-400" />
                      ) : (d.status === 'running' || d.status === 'pending') ? (
                        <Loader className="h-3 w-3 text-blue-400 animate-spin" />
                      ) : d.status === 'error' ? (
                        <X className="h-3 w-3 text-red-400" title={d.error_message || ''} />
                      ) : d.status === 'cancelled' ? (
                        <X className="h-3 w-3 text-text-dim" title={t('common.cancelled', 'Cancelled')} />
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            );
            return !sapbertBuilding ? (
              <p className="text-xs text-text-muted">
                {t('settings.sapbert_none', 'No SapBERT suggestions built yet for this CDM.')}
              </p>
            ) : null;
          })()}
        </div>
      )}
    </Card>
  );
}
