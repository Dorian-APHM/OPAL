import { useState, useEffect, useCallback, useRef } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import {
  Card, Tabs, Table, Tag, Button, Select, Input, TextArea, NumberInput,
  Statistic, Empty, Spinner, Tooltip, Modal, Confirm, Checkbox, useToast,
} from '../components/ui';
import type { TabItem, Column } from '../components/ui';
import {
  BarChart3, Search, Lightbulb, History, Download, Check, X, Edit,
  Undo2, Zap, AlertTriangle, StopCircle, RefreshCw, FileEdit, Link,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, LineChart, Line, Legend,
} from 'recharts';
import { mappingApi, authDownload } from '../api/client';
import { useAuth } from '../auth/KeycloakContext';
import { useNotifDots } from '../hooks/useNotifDots';
import type {
  MappingDomainStat, MappingEvolutionPoint, UnmappedItem,
  SuggestionResult, MappingSuggestion, MappingDecisionEntry,
  StrategyStats,
} from '../types';

const DOMAIN_LIST = ['Condition', 'Drug', 'Measurement', 'Observation', 'Procedure', 'Visit', 'Device', 'Death'];

interface Props {
  selectedCdm: string | null;
}

export default function MappingPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useSessionState('mapping:activeTab', 'dashboard');
  const [historyKey, setHistoryKey] = useState(0);
  const { markAllReadForType, count: mappingNotifCount } = useNotifDots('mapping_review');

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === 'history') {
      setHistoryKey(k => k + 1);
      markAllReadForType();
    }
  };

  if (!selectedCdm) {
    return <Empty description={t('mapping.select_cdm', 'Select a CDM connection to explore mappings')} />;
  }

  const tabItems: TabItem[] = [
    {
      key: 'dashboard',
      label: <span className="inline-flex items-center gap-1.5"><BarChart3 className="h-4 w-4" /> {t('mapping.dashboard', 'Dashboard')}</span>,
      children: <MappingDashboardTab cdmName={selectedCdm} />,
    },
    {
      key: 'explore',
      label: <span className="inline-flex items-center gap-1.5"><Search className="h-4 w-4" /> {t('mapping.explore', 'Unmapped')}</span>,
      children: <UnmappedExplorerTab cdmName={selectedCdm} />,
    },
    {
      key: 'suggestions',
      label: <span className="inline-flex items-center gap-1.5"><Lightbulb className="h-4 w-4" /> {t('mapping.suggestions', 'Suggestions')}</span>,
      children: <SuggestionWorkflowTab cdmName={selectedCdm} />,
    },
    {
      key: 'manual',
      label: <span className="inline-flex items-center gap-1.5"><FileEdit className="h-4 w-4" /> {t('mapping.manual', 'Manual')}</span>,
      children: <ManualMappingTab cdmName={selectedCdm} />,
    },
    {
      key: 'history',
      label: (
        <span className="inline-flex items-center gap-1.5">
          <History className="h-4 w-4" /> {t('mapping.history', 'History')}
          {mappingNotifCount > 0 && (
            <span className="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0" />
          )}
        </span>
      ),
      children: <MappingHistoryTab cdmName={selectedCdm} refreshKey={historyKey} />,
    },
  ];

  return (
    <Tabs items={tabItems} activeKey={activeTab} onChange={handleTabChange} />
  );
}

// ============ TAB 1: MAPPING DASHBOARD ============

function MappingDashboardTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<MappingDomainStat[]>([]);
  const [decisions, setDecisions] = useState<Record<string, number>>({});
  const [evolution, setEvolution] = useState<MappingEvolutionPoint[]>([]);
  const [evoDomain, setEvoDomain] = useSessionState('mapping:dashboard:evoDomain', 'Condition');
  const [loading, setLoading] = useState(true);
  const [strategyData, setStrategyData] = useState<StrategyStats[]>([]);
  const [strategyDomain, setStrategyDomain] = useSessionState<string | undefined>('mapping:dashboard:strategyDomain', undefined);

  useEffect(() => {
    setLoading(true);
    mappingApi.dashboard(cdmName)
      .then(r => { setData(r.data.domains); setDecisions(r.data.decisions_summary); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [cdmName]);

  useEffect(() => {
    mappingApi.evolution(cdmName, evoDomain)
      .then(r => setEvolution(r.data.evolution))
      .catch(() => setEvolution([]));
  }, [cdmName, evoDomain]);

  useEffect(() => {
    mappingApi.strategyStats(cdmName, strategyDomain)
      .then(r => setStrategyData(r.data.strategies))
      .catch(() => setStrategyData([]));
  }, [cdmName, strategyDomain]);

  if (loading) return <Spinner />;

  const totalTerms = data.reduce((s, d) => s + d.total_terms, 0);
  const mappedTerms = data.reduce((s, d) => s + d.mapped_terms, 0);
  const pctOverall = totalTerms > 0 ? (mappedTerms / totalTerms * 100) : 0;

  const strategyColumns: Column<StrategyStats>[] = [
    { title: t('mapping.strategy', 'Strategy'), dataIndex: 'strategy', key: 'strategy',
      render: (v: string) => <Tag>{v}</Tag> },
    { title: t('mapping.total_decisions', 'Decisions'), dataIndex: 'total_decisions', key: 'total' },
    { title: t('mapping.approved', 'Approved'), dataIndex: 'approved', key: 'approved',
      render: (v: number, r: StrategyStats) => <span className="text-emerald-400">{v} ({r.approval_rate}%)</span> },
    { title: t('mapping.modified', 'Modified'), dataIndex: 'modified', key: 'modified',
      render: (v: number, r: StrategyStats) => <span className="text-yellow-400">{v} ({r.modification_rate}%)</span> },
    { title: t('mapping.rejected', 'Rejected'), dataIndex: 'rejected', key: 'rejected',
      render: (v: number, r: StrategyStats) => <span className="text-red-400">{v} ({r.rejection_rate}%)</span> },
    { title: t('mapping.avg_confidence', 'Avg Confidence'), dataIndex: 'avg_confidence', key: 'conf',
      render: (v: number | null) => v != null ? `${v}%` : '—' },
    { title: t('mapping.avg_conf_approved', 'Avg Conf. (Approved)'), dataIndex: 'avg_confidence_approved', key: 'conf_a',
      render: (v: number | null) => v != null ? <span className="text-emerald-400">{v}%</span> : '—' },
  ];

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-4 gap-4 mb-4">
        <Card><Statistic title={t('mapping.overall_rate', 'Overall Mapping Rate')} value={pctOverall.toFixed(1)} suffix="%" /></Card>
        <Card><Statistic title={t('mapping.total_terms', 'Total Terms')} value={totalTerms.toLocaleString()} /></Card>
        <Card><Statistic title={t('mapping.mapped', 'Mapped')} value={mappedTerms.toLocaleString()} valueStyle={{ color: '#10B981' }} /></Card>
        <Card><Statistic title={t('mapping.decisions_made', 'Decisions Made')} value={Object.values(decisions).reduce((a, b) => a + b, 0).toLocaleString()} /></Card>
      </div>

      {/* Bar chart */}
      <Card title={t('mapping.rates_by_domain', 'Mapping Rates by Domain')} className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="domain" stroke="#64748b" />
            <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} stroke="#64748b" />
            <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={{ backgroundColor: '#0f1629', border: '1px solid #1e293b', borderRadius: 8 }} />
            <Legend />
            <Bar dataKey="pct_terms_mapped" name={t('mapping.terms_pct', '% Terms Mapped')} fill="#3B82F6" />
            <Bar dataKey="pct_rows_mapped" name={t('mapping.rows_pct', '% Rows Mapped')} fill="#10B981" />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Unmapped volume (weighted by records) */}
      <Card title={t('mapping.unmapped_volume', 'Unmapped Volume (by records)')} className="mb-4">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="domain" stroke="#64748b" />
            <YAxis stroke="#64748b" />
            <RechartsTooltip formatter={(v: number) => v.toLocaleString()} contentStyle={{ backgroundColor: '#0f1629', border: '1px solid #1e293b', borderRadius: 8 }} />
            <Bar dataKey="unmapped_rows" name={t('mapping.unmapped_rows', 'Unmapped Rows')} fill="#ef4444" />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Evolution */}
      <Card
        title={t('mapping.evolution', 'Mapping Evolution')}
        extra={
          <Select
            size="small"
            value={evoDomain}
            onChange={setEvoDomain}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[150px]"
          />
        }
        className="mb-4"
      >
        {evolution.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={evolution}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="version" label={{ value: 'Version', position: 'insideBottom', offset: -5 }} stroke="#64748b" />
              <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} stroke="#64748b" />
              <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={{ backgroundColor: '#0f1629', border: '1px solid #1e293b', borderRadius: 8 }} />
              <Legend />
              <Line type="monotone" dataKey="pct_terms_mapped" name="% Terms" stroke="#3B82F6" strokeWidth={2} />
              <Line type="monotone" dataKey="pct_rows_mapped" name="% Rows" stroke="#10B981" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <span className="text-text-muted">{t('mapping.no_evolution', 'Run multiple analyses to see evolution')}</span>
        )}
      </Card>

      {/* Strategy Confidence Stats */}
      <Card
        title={t('mapping.strategy_stats', 'Strategy Performance')}
        extra={
          <Select
            size="small"
            value={strategyDomain ?? ''}
            onChange={(v) => setStrategyDomain(v || undefined)}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[150px]"
            allowClear
            placeholder={t('mapping.all_domains', 'All domains')}
          />
        }
      >
        {strategyData.length > 0 ? (
          <>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={strategyData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} stroke="#64748b" />
                <YAxis type="category" dataKey="strategy" width={120} tick={{ fontSize: 12 }} stroke="#64748b" />
                <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={{ backgroundColor: '#0f1629', border: '1px solid #1e293b', borderRadius: 8 }} />
                <Legend />
                <Bar dataKey="approval_rate" name={t('mapping.approval_rate', 'Approval %')} fill="#10B981" stackId="a" />
                <Bar dataKey="modification_rate" name={t('mapping.modification_rate', 'Modification %')} fill="#f59e0b" stackId="a" />
                <Bar dataKey="rejection_rate" name={t('mapping.rejection_rate', 'Rejection %')} fill="#ef4444" stackId="a" />
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-3">
              <Table
                size="small"
                dataSource={strategyData}
                rowKey="strategy"
                pagination={false}
                columns={strategyColumns}
              />
            </div>
          </>
        ) : (
          <Empty description={t('mapping.no_strategy_data', 'No mapping decisions yet. Approve or reject suggestions to see strategy performance.')} />
        )}
      </Card>
    </div>
  );
}

// ============ TAB 2: UNMAPPED EXPLORER ============

function UnmappedExplorerTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [domain, setDomain] = useSessionState('mapping:unmapped:domain', 'Condition');
  const [items, setItems] = useState<UnmappedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useSessionState('mapping:unmapped:page', 1);
  const [search, setSearch] = useSessionState('mapping:unmapped:search', '');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    mappingApi.unmapped(cdmName, domain, page, 50, search)
      .then(r => { setItems(r.data.items); setTotal(r.data.total); })
      .catch(() => { setItems([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [cdmName, domain, page, search]);

  useEffect(() => { load(); }, [load]);

  const columns: Column<UnmappedItem>[] = [
    { title: t('mapping.source_value', 'Source Value'), dataIndex: 'source_value', key: 'sv', ellipsis: true },
    { title: t('mapping.source_name', 'Source Name'), dataIndex: 'source_name', key: 'sn', ellipsis: true,
      render: (v: string) => v || <span className="text-text-dim">—</span> },
    { title: t('mapping.n_records', 'Records'), dataIndex: 'n_records', key: 'nr',
      render: (v: number) => v.toLocaleString(), sorter: (a: UnmappedItem, b: UnmappedItem) => a.n_records - b.n_records },
    { title: t('mapping.n_persons', 'Persons'), dataIndex: 'n_persons', key: 'np',
      render: (v: number) => v.toLocaleString() },
  ];

  return (
    <div>
      <Card size="small" className="mb-3">
        <div className="flex items-center gap-3">
          <Select
            value={domain}
            onChange={v => { setDomain(v); setPage(1); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[150px]"
          />
          <Input
            prefix={<Search className="h-4 w-4" />}
            placeholder={t('mapping.search_unmapped', 'Filter...')}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="w-[250px]"
          />
          <Button
            icon={<Download className="h-4 w-4" />}
            onClick={() => authDownload(mappingApi.exportUnmappedUrl(cdmName, domain))}
            size="small"
          >
            CSV
          </Button>
          <span className="text-text-muted text-sm">{total.toLocaleString()} {t('mapping.terms', 'terms')}</span>
        </div>
      </Card>
      <Table
        dataSource={items}
        columns={columns}
        rowKey="source_value"
        loading={loading}
        pagination={{ pageSize: 50, current: page, total, onChange: setPage }}
        size="small"
      />
    </div>
  );
}

// ============ TAB 3: SUGGESTION WORKFLOW ============

function SuggestionWorkflowTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [domain, setDomain] = useSessionState('mapping:suggest:domain', 'Condition');
  const [results, setResults] = useSessionState<SuggestionResult[]>('mapping:suggest:results', []);
  const [loading, setLoading] = useSessionState('mapping:suggest:loading', false);
  const [taskId, setTaskId] = useSessionState<string | null>('mapping:suggest:taskId', null);
  const [limit, setLimit] = useSessionState('mapping:suggest:limit', 20);
  const [enableFuzzy, setEnableFuzzy] = useSessionState('mapping:suggest:enableFuzzy', true);
  const [enableKeyword, setEnableKeyword] = useSessionState('mapping:suggest:enableKeyword', true);
  const [enableContextual, setEnableContextual] = useSessionState('mapping:suggest:enableContextual', true);
  const [enableSapbert, setEnableSapbert] = useSessionState('mapping:suggest:enableSapbert', true);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  // Poll for suggestion task completion
  const startPolling = useCallback((tid: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      mappingApi.suggestStatus(tid)
        .then(res => {
          if (!mountedRef.current) return;
          if (res.data.status === 'done') {
            setResults(res.data.results || []);
            setLoading(false);
            setTaskId(null);
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            toast.success(t('common.success'));
          } else if (res.data.status === 'error') {
            toast.error(res.data.error || t('common.error'));
            setLoading(false);
            setTaskId(null);
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        })
        .catch(() => {
          // Task not found — may have finished and been cleaned up
          if (mountedRef.current) {
            setLoading(false);
            setTaskId(null);
          }
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        });
    }, 2000);
  }, [t, toast]);

  // On mount: check if there's an active suggestion task
  useEffect(() => {
    mountedRef.current = true;

    if (taskId) {
      // Resume polling for existing task
      setLoading(true);
      startPolling(taskId);
    } else if (loading) {
      // Stale loading state without a task — clear it
      setLoading(false);
    }

    // Also check server for any active tasks for this CDM
    if (!taskId) {
      mappingApi.suggestActive()
        .then(res => {
          if (!mountedRef.current) return;
          const active = res.data.active.find(a => a.cdm_name === cdmName && a.status === 'running');
          if (active) {
            setTaskId(active.task_id);
            setLoading(true);
            startPolling(active.task_id);
          }
        })
        .catch(() => {});
    }

    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [cdmName]);

  // Pre-configure strategies per domain
  useEffect(() => {
    if (domain === 'Procedure') {
      setEnableFuzzy(false);
      setEnableKeyword(false);
      setEnableContextual(false);
      setEnableSapbert(true);
    } else {
      setEnableFuzzy(true);
      setEnableKeyword(true);
      setEnableContextual(true);
      setEnableSapbert(true);
    }
  }, [domain]);

  const runBatch = () => {
    setLoading(true);
    setResults([]);
    mappingApi.suggestBatch(cdmName, domain, limit, {
      enable_fuzzy: enableFuzzy,
      enable_keyword: enableKeyword,
      enable_contextual: enableContextual,
      enable_sapbert: enableSapbert,
    })
      .then(r => {
        if (!mountedRef.current) return;
        const tid = r.data.task_id;
        setTaskId(tid);
        startPolling(tid);
      })
      .catch(e => {
        if (mountedRef.current) {
          toast.error(e.response?.data?.detail || 'Suggestion failed');
          setLoading(false);
        }
      });
  };

  const cancelBatch = () => {
    if (taskId) {
      mappingApi.suggestCancel(taskId).catch(() => {});
      setTaskId(null);
    }
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setLoading(false);
    toast.info('Cancelled');
  };

  // Reason modal state
  const [reasonModal, setReasonModal] = useState<{
    open: boolean;
    sv: string;
    sn: string;
    action: string;
    suggestion?: MappingSuggestion;
  }>({ open: false, sv: '', sn: '', action: '' });
  const [reasonText, setReasonText] = useState('');

  const promptDecision = (
    sv: string, sn: string, action: string,
    suggestion?: MappingSuggestion,
  ) => {
    setReasonText('');
    setReasonModal({ open: true, sv, sn, action, suggestion });
  };

  const submitDecision = async () => {
    const { sv, sn, action, suggestion } = reasonModal;
    try {
      await mappingApi.decide({
        cdm_name: cdmName,
        domain,
        source_value: sv,
        source_name: sn,
        action,
        target_concept_id: suggestion?.concept_id,
        target_concept_name: suggestion?.concept_name || '',
        target_vocabulary_id: suggestion?.vocabulary_id || '',
        suggestion_source: suggestion?.source || 'manual',
        confidence_score: suggestion?.confidence,
        reason: reasonText,
      });
      toast.success(`${action}: ${sv}`);
      setResults(prev => prev.filter(r => r.source_value !== sv));
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Decision failed');
    }
    setReasonModal({ open: false, sv: '', sn: '', action: '' });
  };

  const handleBulkApprove = async (minConfidence: number) => {
    const toApprove = results.filter(r =>
      r.suggestions.length > 0 && r.suggestions[0].confidence >= minConfidence
    );
    let count = 0;
    for (const r of toApprove) {
      try {
        await mappingApi.decide({
          cdm_name: cdmName, domain,
          source_value: r.source_value, source_name: r.source_name,
          action: 'approved',
          target_concept_id: r.suggestions[0].concept_id,
          target_concept_name: r.suggestions[0].concept_name,
          target_vocabulary_id: r.suggestions[0].vocabulary_id,
          suggestion_source: r.suggestions[0].source,
          confidence_score: r.suggestions[0].confidence,
        });
        count++;
      } catch { /* continue */ }
    }
    toast.success(`Approved ${count} mappings`);
    setResults(prev => prev.filter(r =>
      !(r.suggestions.length > 0 && r.suggestions[0].confidence >= minConfidence)
    ));
  };

  const confidenceColor = (c: number): 'green' | 'orange' | 'red' => c >= 80 ? 'green' : c >= 50 ? 'orange' : 'red';
  const sourceLabel = (s: string) => {
    const labels: Record<string, string> = { exact: 'Exact', relationship: 'Maps to', fuzzy: 'Fuzzy', contextual: 'Context', ingredient: 'Ingredient', synonym: 'Synonym', sapbert: 'SapBERT' };
    return labels[s] || s;
  };

  return (
    <div>
      <Card size="small" className="mb-3">
        <div className="flex items-center gap-3">
          <Select
            value={domain}
            onChange={setDomain}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[150px]"
          />
          <NumberInput
            min={5}
            max={100}
            value={limit}
            onChange={v => setLimit(v || 20)}
            className="w-[70px]"
          />
          <span className="border-l border-glass-border pl-3 ml-1 flex items-center gap-3">
            <Checkbox checked={enableFuzzy} onChange={setEnableFuzzy}>
              <span className="text-xs">Fuzzy</span>
            </Checkbox>
            <Checkbox checked={enableKeyword} onChange={setEnableKeyword}>
              <span className="text-xs">{t('mapping.keyword', 'Keyword')}</span>
            </Checkbox>
            <Checkbox checked={enableContextual} onChange={setEnableContextual}>
              <span className="text-xs">{t('mapping.contextual', 'Contextual')}</span>
            </Checkbox>
            {domain === 'Procedure' && (
              <Checkbox checked={enableSapbert} onChange={setEnableSapbert}>
                <span className="text-xs">SapBERT</span>
              </Checkbox>
            )}
          </span>
          {loading ? (
            <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelBatch} size="small">
              {t('common.cancel')}
            </Button>
          ) : (
            <Button variant="primary" icon={<Zap className="h-4 w-4" />} onClick={runBatch} size="small">
              {t('mapping.generate', 'Generate Suggestions')}
            </Button>
          )}
          {results.length > 0 && (
            <>
              <Button size="small" onClick={() => handleBulkApprove(80)}>
                {t('mapping.bulk_approve_80', 'Bulk Approve ≥80%')}
              </Button>
              <Button size="small" onClick={() => handleBulkApprove(90)}>
                ≥90%
              </Button>
            </>
          )}
          <span className="text-text-muted text-sm">{results.length} {t('mapping.pending', 'pending')}</span>
        </div>
      </Card>

      {loading ? <Spinner /> : results.length === 0 ? (
        <Empty description={t('mapping.no_suggestions', 'Click Generate to get mapping suggestions')} />
      ) : (
        <div className="flex flex-col gap-2">
          {results.map(r => (
            <Card key={r.source_value} size="small">
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <span className="font-semibold text-text-bright">{r.source_value}</span>
                  {r.source_name && <span className="text-text-muted ml-2 text-xs">{r.source_name}</span>}
                  <div className="mt-1">
                    {r.suggestions.length === 0 ? (
                      <span className="text-text-dim text-xs">{t('mapping.no_match', 'No suggestions found')}</span>
                    ) : (
                      r.suggestions.map((s, i) => (
                        <div key={s.concept_id} className={`px-2 py-1 rounded mt-0.5 flex justify-between items-center ${i === 0 ? 'bg-emerald-500/8' : 'bg-surface-light'}`}>
                          <div className="flex items-center gap-1">
                            <Tag color={confidenceColor(s.confidence)} className="text-[10px]">{s.confidence}%</Tag>
                            <Tag className="text-[10px]">{sourceLabel(s.source)}</Tag>
                            <span className="text-xs text-text-bright">{s.concept_name}</span>
                            <span className="text-[10px] text-text-dim">{s.concept_id} · {s.concept_code} · {s.vocabulary_id}</span>
                          </div>
                          <div className="flex items-center gap-0.5">
                            <Tooltip title={t('mapping.approve', 'Approve')}>
                              <button
                                className="p-1 text-emerald-400 hover:text-emerald-300 bg-transparent border-none cursor-pointer"
                                onClick={() => promptDecision(r.source_value, r.source_name, 'approved', s)}
                              >
                                <Check className="h-4 w-4" />
                              </button>
                            </Tooltip>
                            {i !== 0 && (
                              <Tooltip title={t('mapping.approve_this', 'Approve this instead')}>
                                <button
                                  className="p-1 text-text-muted hover:text-emerald-accent bg-transparent border-none cursor-pointer"
                                  onClick={() => promptDecision(r.source_value, r.source_name, 'modified', s)}
                                >
                                  <Edit className="h-4 w-4" />
                                </button>
                              </Tooltip>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
                <div className="flex flex-col gap-0.5 ml-2">
                  <Tooltip title={t('mapping.reject', 'Reject')}>
                    <Button size="small" variant="danger" onClick={() => promptDecision(r.source_value, r.source_name, 'rejected')}>
                      <X className="h-4 w-4" />
                    </Button>
                  </Tooltip>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={reasonModal.open}
        onClose={() => setReasonModal({ open: false, sv: '', sn: '', action: '' })}
        title={reasonModal.action === 'rejected' ? t('mapping.reject_reason', 'Reject — Reason') : t('mapping.approve_reason', 'Approve — Reason')}
        footer={
          <>
            <Button onClick={() => setReasonModal({ open: false, sv: '', sn: '', action: '' })}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant={reasonModal.action === 'rejected' ? 'danger' : 'primary'}
              onClick={submitDecision}
            >
              {reasonModal.action === 'rejected' ? t('mapping.reject', 'Reject') : t('mapping.approve', 'Approve')}
            </Button>
          </>
        }
      >
        <p className="mb-2">
          <Tag>{reasonModal.sv}</Tag> {reasonModal.sn && <span className="text-text-muted">{reasonModal.sn}</span>}
        </p>
        <TextArea
          rows={3}
          placeholder={t('mapping.reason_placeholder', 'Reason (optional)')}
          value={reasonText}
          onChange={e => setReasonText(e.target.value)}
          autoFocus
        />
      </Modal>
    </div>
  );
}

// ============ TAB 4: MANUAL MAPPING ============

function ManualMappingTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [domain, setDomain] = useSessionState('mapping:manual:domain', 'Condition');
  const [search, setSearch] = useSessionState('mapping:manual:search', '');
  const [searchResults, setSearchResults] = useState<UnmappedItem[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<UnmappedItem | null>(null);

  // Concept lookup state
  const [conceptIdInput, setConceptIdInput] = useState<number | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [conceptInfo, setConceptInfo] = useState<{
    concept_id: number; concept_name: string; concept_code: string;
    vocabulary_id: string; domain_id: string; standard_concept: string | null;
    concept_class_id: string;
  } | null>(null);
  const [conceptError, setConceptError] = useState('');

  // Decision state
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Search source values
  const handleSearch = useCallback(() => {
    if (!search.trim()) return;
    setSearchLoading(true);
    setSelectedSource(null);
    setConceptInfo(null);
    setConceptIdInput(null);
    setConceptError('');
    mappingApi.unmapped(cdmName, domain, 1, 20, search, true)
      .then(r => { setSearchResults(r.data.items); setSearchTotal(r.data.total); })
      .catch(() => { setSearchResults([]); setSearchTotal(0); })
      .finally(() => setSearchLoading(false));
  }, [cdmName, domain, search]);

  // Lookup concept by ID
  const handleConceptLookup = useCallback(() => {
    if (!conceptIdInput) return;
    setConceptLoading(true);
    setConceptInfo(null);
    setConceptError('');
    mappingApi.conceptLookup(cdmName, conceptIdInput)
      .then(r => setConceptInfo(r.data))
      .catch((e: any) => {
        setConceptError(e.response?.data?.detail || t('mapping.concept_not_found', 'Concept not found'));
      })
      .finally(() => setConceptLoading(false));
  }, [cdmName, conceptIdInput, t]);

  // Submit manual mapping
  const handleApprove = async () => {
    if (!selectedSource || !conceptInfo) return;
    setSubmitting(true);
    try {
      await mappingApi.decide({
        cdm_name: cdmName,
        domain,
        source_value: selectedSource.source_value,
        source_name: selectedSource.source_name || '',
        action: 'approved',
        target_concept_id: conceptInfo.concept_id,
        target_concept_name: conceptInfo.concept_name,
        target_vocabulary_id: conceptInfo.vocabulary_id,
        suggestion_source: 'manual',
        confidence_score: 100,
        reason: reason || '',
      });
      toast.success(`${t('mapping.approved', 'Approved')}: ${selectedSource.source_value} → ${conceptInfo.concept_name}`);
      // Reset form
      setSelectedSource(null);
      setConceptInfo(null);
      setConceptIdInput(null);
      setConceptError('');
      setReason('');
      // Refresh search results to remove mapped item
      if (search.trim()) {
        mappingApi.unmapped(cdmName, domain, 1, 20, search, true)
          .then(r => { setSearchResults(r.data.items); setSearchTotal(r.data.total); })
          .catch(() => {});
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || t('mapping.decision_failed', 'Decision failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const searchColumns: Column<UnmappedItem>[] = [
    { title: t('mapping.source_value', 'Source Value'), dataIndex: 'source_value', key: 'sv', ellipsis: true },
    { title: t('mapping.source_name', 'Source Name'), dataIndex: 'source_name', key: 'sn', ellipsis: true,
      render: (v: string) => v || <span className="text-text-dim">—</span> },
    { title: t('mapping.n_records', 'Records'), dataIndex: 'n_records', key: 'nr',
      render: (v: number) => v.toLocaleString() },
    { title: t('mapping.n_persons', 'Persons'), dataIndex: 'n_persons', key: 'np',
      render: (v: number) => v.toLocaleString() },
  ];

  return (
    <div>
      {/* Step 1: Search for a source code */}
      <Card
        size="small"
        title={<span className="inline-flex items-center gap-1.5"><Search className="h-4 w-4" />{t('mapping.manual_step1', 'Step 1 — Select a local code')}</span>}
        className="mb-3"
      >
        <div className="flex items-center gap-3 mb-3">
          <Select
            value={domain}
            onChange={v => { setDomain(v); setSearchResults([]); setSelectedSource(null); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[150px]"
          />
          <Input
            prefix={<Search className="h-4 w-4" />}
            placeholder={t('mapping.search_source_code', 'Search local code...')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSearch(); }}
            className="w-[300px]"
          />
          <Button variant="primary" onClick={handleSearch} loading={searchLoading}>
            {t('mapping.search', 'Search')}
          </Button>
        </div>

        {searchResults.length > 0 && (
          <>
            <Table
              dataSource={searchResults}
              rowKey="source_value"
              size="small"
              pagination={false}
              columns={searchColumns}
              onRow={(record) => ({
                onClick: () => {
                  setSelectedSource(record);
                  setConceptInfo(null);
                  setConceptIdInput(null);
                  setConceptError('');
                },
                className: selectedSource?.source_value === record.source_value ? 'bg-emerald-accent/10' : '',
              })}
            />
            <span className="text-text-muted text-sm mt-2 block">{searchTotal} {t('mapping.results_found', 'results found')} — {t('mapping.click_to_select', 'click a row to select')}</span>
          </>
        )}
      </Card>

      {/* Step 2: Selected source info + concept ID input */}
      {selectedSource && (
        <Card
          size="small"
          title={<span className="inline-flex items-center gap-1.5"><Link className="h-4 w-4" />{t('mapping.manual_step2', 'Step 2 — Map to a concept')}</span>}
          className="mb-3"
        >
          {/* Selected source summary */}
          <div className="bg-blue-500/8 border border-blue-500/25 rounded-lg px-4 py-2.5 mb-4">
            <div className="grid grid-cols-12 gap-6">
              <div className="col-span-4">
                <span className="text-text-dim text-[11px]">{t('mapping.source_value', 'Source Value')}</span>
                <div className="font-semibold text-sm text-text-bright">{selectedSource.source_value}</div>
              </div>
              <div className="col-span-4">
                <span className="text-text-dim text-[11px]">{t('mapping.source_name', 'Source Name')}</span>
                <div className="text-sm text-text-bright">{selectedSource.source_name || '—'}</div>
              </div>
              <div className="col-span-2">
                <span className="text-text-dim text-[11px]">{t('mapping.n_records', 'Records')}</span>
                <div className="font-semibold text-sm text-text-bright">{selectedSource.n_records.toLocaleString()}</div>
              </div>
              <div className="col-span-2">
                <span className="text-text-dim text-[11px]">{t('mapping.n_persons', 'Persons')}</span>
                <div className="font-semibold text-sm text-text-bright">{selectedSource.n_persons.toLocaleString()}</div>
              </div>
            </div>
          </div>

          {/* Concept ID input */}
          <div className="flex items-center gap-3 mb-3">
            <span className="text-text-bright text-sm">{t('mapping.enter_concept_id', 'Concept ID')} :</span>
            <NumberInput
              className="w-[180px]"
              placeholder="e.g. 4329847"
              value={conceptIdInput ?? undefined}
              onChange={v => { setConceptIdInput(v); setConceptInfo(null); setConceptError(''); }}
              onKeyDown={e => { if (e.key === 'Enter') handleConceptLookup(); }}
              min={1}
            />
            <Button onClick={handleConceptLookup} loading={conceptLoading} disabled={!conceptIdInput}>
              {t('mapping.lookup', 'Lookup')}
            </Button>
          </div>

          {/* Concept error */}
          {conceptError && (
            <div className="text-red-400 mb-3 flex items-center gap-1">
              <X className="h-4 w-4" />{conceptError}
            </div>
          )}

          {/* Concept info display */}
          {conceptInfo && (
            <div className="bg-emerald-500/8 border border-emerald-500/25 rounded-lg px-4 py-2.5 mb-4">
              <div className="grid grid-cols-12 gap-4">
                <div className="col-span-3">
                  <span className="text-text-dim text-[11px]">Concept ID</span>
                  <div className="font-semibold text-text-bright">{conceptInfo.concept_id}</div>
                </div>
                <div className="col-span-4">
                  <span className="text-text-dim text-[11px]">Concept Name</span>
                  <div className="font-semibold text-text-bright">{conceptInfo.concept_name}</div>
                </div>
                <div className="col-span-2">
                  <span className="text-text-dim text-[11px]">Vocabulary</span>
                  <div><Tag>{conceptInfo.vocabulary_id}</Tag></div>
                </div>
                <div className="col-span-1.5">
                  <span className="text-text-dim text-[11px]">Domain</span>
                  <div><Tag>{conceptInfo.domain_id}</Tag></div>
                </div>
                <div className="col-span-1.5">
                  <span className="text-text-dim text-[11px]">Standard</span>
                  <div>
                    {conceptInfo.standard_concept === 'S'
                      ? <Tag color="green">Standard</Tag>
                      : conceptInfo.standard_concept === 'C'
                      ? <Tag color="orange">Classification</Tag>
                      : <Tag color="red">Non-standard</Tag>}
                  </div>
                </div>
              </div>
              <div className="mt-2">
                <span className="text-text-dim text-[11px]">Code: </span>
                <span className="font-mono text-sm bg-surface-light px-1.5 py-0.5 rounded text-text-bright">{conceptInfo.concept_code}</span>
                <span className="text-text-dim text-[11px] ml-4">Class: </span>
                <span className="text-text-bright text-sm">{conceptInfo.concept_class_id}</span>
              </div>
            </div>
          )}

          {/* Reason + approve button */}
          {conceptInfo && (
            <div className="flex flex-col gap-3 w-full">
              <TextArea
                rows={2}
                placeholder={t('mapping.reason_placeholder', 'Reason (optional)')}
                value={reason}
                onChange={e => setReason(e.target.value)}
              />
              <Button
                variant="primary"
                icon={<Check className="h-4 w-4" />}
                onClick={handleApprove}
                loading={submitting}
                size="large"
                block
              >
                {t('mapping.approve_mapping', 'Approve Mapping')}: {selectedSource.source_value} → {conceptInfo.concept_name} ({conceptInfo.concept_id})
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* Empty state */}
      {!selectedSource && searchResults.length === 0 && !searchLoading && (
        <Empty
          description={t('mapping.manual_description', 'Search for a local code, then enter a target concept ID to create a manual mapping.')}
          className="mt-12"
        />
      )}
    </div>
  );
}

// ============ TAB 5: MAPPING HISTORY ============

function MappingHistoryTab({ cdmName, refreshKey }: { cdmName: string; refreshKey?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { roles } = useAuth();
  const canWriteCdm = roles.includes('admin') || roles.includes('data-manager');
  const [items, setItems] = useState<MappingDecisionEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useSessionState('mapping:history:page', 1);
  const [filterDomain, setFilterDomain] = useSessionState('mapping:history:filterDomain', '');
  const [filterAction, setFilterAction] = useSessionState('mapping:history:filterAction', '');
  const [loading, setLoading] = useState(false);
  const [applyDomain, setApplyDomain] = useSessionState('mapping:history:applyDomain', 'Condition');
  const [applyPreview, setApplyPreview] = useState<{ total_decisions: number; impacted_rows: number; impacted_persons: number } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    mappingApi.history(cdmName, filterDomain || undefined, filterAction || undefined, page)
      .then(r => { setItems(r.data.items); setTotal(r.data.total); })
      .catch(() => { setItems([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [cdmName, filterDomain, filterAction, page]);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Rollback confirm state
  const [rollbackConfirm, setRollbackConfirm] = useState<{ open: boolean; id: number }>({ open: false, id: 0 });

  const handleRollback = async (id: number) => {
    try {
      await mappingApi.rollback(id);
      toast.success('Rolled back');
      load();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Rollback failed');
    }
  };

  const handleApplyPreview = async () => {
    try {
      const r = await mappingApi.applyPreview(cdmName, applyDomain);
      setApplyPreview(r.data);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Preview failed');
    }
  };

  const [writeConfirmOpen, setWriteConfirmOpen] = useState(false);
  const [writeConfirmText, setWriteConfirmText] = useState('');
  const [applyLoading, setApplyLoading] = useState(false);

  const handleApply = async (writeToCdm: boolean) => {
    setApplyLoading(true);
    try {
      const r = await mappingApi.apply(cdmName, applyDomain, writeToCdm);
      toast.success(`Applied ${r.data.count} mappings${writeToCdm ? ' to CDM' : ''}`);
      setApplyPreview(null);
      setWriteConfirmOpen(false);
      setWriteConfirmText('');
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Apply failed');
    } finally {
      setApplyLoading(false);
    }
  };

  const actionColor = (a: string): 'green' | 'blue' | 'red' | 'orange' | 'default' => {
    const colors: Record<string, 'green' | 'blue' | 'red' | 'orange'> = { approved: 'green', modified: 'blue', rejected: 'red', rolled_back: 'orange' };
    return colors[a] || 'default';
  };

  const actionOptions = [
    { value: 'approved', label: 'Approved' },
    { value: 'modified', label: 'Modified' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'rolled_back', label: 'Rolled back' },
  ];

  const columns: Column<MappingDecisionEntry>[] = [
    { title: t('mapping.domain', 'Domain'), dataIndex: 'domain', key: 'd', width: 100 },
    { title: t('mapping.source_value', 'Source'), dataIndex: 'source_value', key: 'sv', ellipsis: true },
    { title: t('mapping.action', 'Action'), dataIndex: 'action', key: 'a', width: 100,
      render: (a: string) => <Tag color={actionColor(a)}>{a}</Tag> },
    { title: t('mapping.target', 'Target'), key: 'target', width: 200,
      render: (_: any, r: MappingDecisionEntry) => r.target_concept_id
        ? <span>{r.target_concept_name} <span className="text-text-muted text-[10px]">({r.target_concept_id})</span></span>
        : <span className="text-text-dim">—</span> },
    { title: t('mapping.confidence', 'Confidence'), dataIndex: 'confidence_score', key: 'c', width: 80,
      render: (v: number | null) => v != null ? <Tag>{v}%</Tag> : '—' },
    { title: t('mapping.reason', 'Reason'), dataIndex: 'reason', key: 'reason', width: 150, ellipsis: true,
      render: (v: string) => v || <span className="text-text-dim">—</span> },
    { title: t('mapping.date', 'Date'), dataIndex: 'created_at', key: 'date', width: 120,
      render: (v: string) => v?.substring(0, 16).replace('T', ' ') },
    { title: '', key: 'actions', width: 50,
      render: (_: any, r: MappingDecisionEntry) => r.action !== 'rolled_back' ? (
        <Button
          size="small"
          variant="link"
          onClick={() => setRollbackConfirm({ open: true, id: r.id })}
        >
          <Undo2 className="h-4 w-4" />
        </Button>
      ) : null },
  ];

  return (
    <div>
      <Confirm
        open={rollbackConfirm.open}
        onClose={() => setRollbackConfirm({ open: false, id: 0 })}
        onConfirm={() => handleRollback(rollbackConfirm.id)}
        title="Rollback?"
        confirmText="Rollback"
        danger
      />

      <Card size="small" className="mb-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={filterDomain}
            onChange={v => { setFilterDomain(v); setPage(1); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-[130px]"
            allowClear
            placeholder="All domains"
          />
          <Select
            value={filterAction}
            onChange={v => { setFilterAction(v); setPage(1); }}
            options={actionOptions}
            className="w-[120px]"
            allowClear
            placeholder="All actions"
          />
          <Button icon={<Download className="h-4 w-4" />} onClick={() => authDownload(mappingApi.exportHistoryUrl(cdmName, filterDomain || undefined))} size="small">
            {t('mapping.export_history', 'Export')}
          </Button>
          <Button icon={<RefreshCw className="h-4 w-4" />} size="small" onClick={load} loading={loading} />
          <span className="text-text-muted text-sm">{total} {t('mapping.decisions', 'decisions')}</span>

          <span className="border-l border-glass-border pl-3 flex items-center gap-2">
            <span className="text-xs text-text-bright">{t('mapping.apply_to', 'Apply to')}:</span>
            <Select
              size="small"
              value={applyDomain}
              onChange={setApplyDomain}
              options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
              className="w-[120px]"
            />
            <Button size="small" onClick={handleApplyPreview}>Preview</Button>
            <Button size="small" icon={<Download className="h-4 w-4" />} onClick={() => authDownload(mappingApi.exportStcmUrl(cdmName, applyDomain))}>
              STCM CSV
            </Button>
          </span>
        </div>
      </Card>

      {applyPreview && (
        <Card size="small" className="mb-3 border-red-500/50 border-2">
          <div className="bg-red-500/8 border border-red-500/25 rounded px-3 py-2 mb-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              <span className="font-semibold text-red-400">
                {t('mapping.write_warning', 'Cette action va modifier directement la table source_to_concept_map du CDM. Cette opération est difficilement réversible.')}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <Statistic title={t('mapping.approved_decisions', 'Approved Decisions')} value={applyPreview.total_decisions} />
            <Statistic title={t('mapping.impacted_rows', 'Impacted Rows')} value={applyPreview.impacted_rows.toLocaleString()} valueStyle={{ color: '#ef4444' }} />
            <Statistic title={t('mapping.impacted_persons', 'Impacted Persons')} value={applyPreview.impacted_persons.toLocaleString()} valueStyle={{ color: '#ef4444' }} />
          </div>
          <div className="flex items-center gap-3 mt-3">
            {canWriteCdm && (
              <Button variant="danger" size="small" onClick={() => setWriteConfirmOpen(true)}>
                <AlertTriangle className="h-4 w-4" /> {t('mapping.write_to_cdm', 'Write to CDM')}
              </Button>
            )}
            <Button size="small" icon={<Download className="h-4 w-4" />} onClick={() => authDownload(mappingApi.exportStcmUrl(cdmName, applyDomain))}>
              {t('mapping.export_stcm_instead', 'Exporter en CSV (recommandé)')}
            </Button>
            <Button size="small" onClick={() => { setApplyPreview(null); setWriteConfirmOpen(false); setWriteConfirmText(''); }}>
              {t('common.close', 'Close')}
            </Button>
          </div>

          <Modal
            open={writeConfirmOpen}
            onClose={() => { setWriteConfirmOpen(false); setWriteConfirmText(''); }}
            title={
              <span className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-400" />
                <span className="font-semibold text-red-400">Confirmation requise</span>
              </span>
            }
            footer={
              <>
                <Button onClick={() => { setWriteConfirmOpen(false); setWriteConfirmText(''); }}>
                  Annuler
                </Button>
                <Button
                  variant="danger"
                  loading={applyLoading}
                  disabled={writeConfirmText !== cdmName}
                  onClick={() => handleApply(true)}
                >
                  Confirmer l&apos;écriture
                </Button>
              </>
            }
          >
            <div className="mb-4">
              <span className="text-text-bright">Vous allez écrire <strong>{applyPreview.total_decisions} mappings</strong> dans la table <span className="font-mono text-sm bg-surface-light px-1.5 py-0.5 rounded">source_to_concept_map</span> du CDM <strong className="text-red-400">{cdmName}</strong>.</span>
            </div>
            <div className="mb-4">
              <span className="text-text-bright">Cela impactera <strong className="text-red-400">{applyPreview.impacted_rows.toLocaleString()} lignes</strong> et <strong className="text-red-400">{applyPreview.impacted_persons.toLocaleString()} patients</strong>.</span>
            </div>
            <div className="bg-yellow-500/10 border border-yellow-500/25 rounded px-3 py-2 mb-4">
              <span className="text-yellow-400 text-xs">Pour confirmer, tapez le nom exact du CDM ci-dessous :</span>
            </div>
            <Input
              placeholder={cdmName}
              value={writeConfirmText}
              onChange={e => setWriteConfirmText(e.target.value)}
              error={writeConfirmText && writeConfirmText !== cdmName ? 'CDM name does not match' : undefined}
            />
          </Modal>
        </Card>
      )}

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 50, current: page, total, onChange: setPage }}
        size="small"
      />
    </div>
  );
}
