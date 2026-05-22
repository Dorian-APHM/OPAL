import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useSessionState } from '../hooks/useSessionState';
import {
  Card, Tabs, Table, Tag, Button, Select, Input, TextArea, NumberInput,
  Statistic, Empty, Spinner, Tooltip, Modal, Confirm, Checkbox, Alert, useToast,
} from '../components/ui';
import type { TabItem, Column } from '../components/ui';
import {
  BarChart3, Search, Lightbulb, History, Download, Check, X, Edit,
  Undo2, Zap, AlertTriangle, StopCircle, RefreshCw, FileEdit, Link, CheckCircle2, Database,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, LineChart, Line, Legend, Rectangle,
} from 'recharts';
import { mappingApi, cdmAccessApi, authDownload } from '../api/client';
import { useChartTheme } from '../hooks/useChartTheme';
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
    {
      key: 'apply-log',
      label: <span className="inline-flex items-center gap-1.5"><Database className="h-4 w-4" /> {t('mapping.apply_log', 'Apply Log')}</span>,
      children: <ApplyLogTab cdmName={selectedCdm} />,
    },
  ];

  return (
    <Tabs items={tabItems} activeKey={activeTab} onChange={handleTabChange} />
  );
}

// ============ TAB 1: MAPPING DASHBOARD ============

function MappingDashboardTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const ct = useChartTheme();
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
      .catch(() => toast.error(t('mapping.load_failed', 'Failed to load mapping dashboard')))
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

  if (loading) return (
    <div className="text-center py-16">
      <Spinner size="large" />
      <p className="text-sm text-text-muted mt-4">{t('mapping.loading', 'Loading mapping dashboard...')}</p>
    </div>
  );

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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        <Card><Statistic title={t('mapping.overall_rate', 'Overall Mapping Rate')} value={pctOverall.toFixed(1)} suffix="%" /></Card>
        <Card><Statistic title={t('mapping.total_terms', 'Total Terms')} value={totalTerms.toLocaleString()} /></Card>
        <Card><Statistic title={t('mapping.mapped', 'Mapped')} value={mappedTerms.toLocaleString()} valueStyle={{ color: '#10B981' }} /></Card>
        <Card><Statistic title={t('mapping.decisions_made', 'Decisions Made')} value={Object.values(decisions).reduce((a, b) => a + b, 0).toLocaleString()} /></Card>
      </div>

      {/* Bar chart */}
      <Card title={t('mapping.rates_by_domain', 'Mapping Rates by Domain')} className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
            <XAxis dataKey="domain" stroke={ct.axis} />
            <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} stroke={ct.axis} />
            <RechartsTooltip cursor={false} formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={ct.tooltipStyle} />
            <Legend />
            <Bar dataKey="pct_terms_mapped" name={t('mapping.terms_pct', '% Terms Mapped')} fill={ct.blue} activeBar={(p: any) => <Rectangle {...p} x={p.x - 3} width={p.width + 6} />} />
            <Bar dataKey="pct_rows_mapped" name={t('mapping.rows_pct', '% Rows Mapped')} fill={ct.emerald} activeBar={(p: any) => <Rectangle {...p} x={p.x - 3} width={p.width + 6} />} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Unmapped volume (weighted by records) */}
      <Card title={t('mapping.unmapped_volume', 'Unmapped Volume (by records)')} className="mb-4">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
            <XAxis dataKey="domain" stroke={ct.axis} />
            <YAxis stroke={ct.axis} />
            <RechartsTooltip cursor={false} formatter={(v: number) => v.toLocaleString()} contentStyle={ct.tooltipStyle} />
            <Bar dataKey="unmapped_rows" name={t('mapping.unmapped_rows', 'Unmapped Rows')} fill={ct.red} activeBar={(p: any) => <Rectangle {...p} x={p.x - 3} width={p.width + 6} />} />
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
            className="w-full sm:w-[150px]"
          />
        }
        className="mb-4"
      >
        {evolution.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={evolution}>
              <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
              <XAxis dataKey="version" label={{ value: 'Version', position: 'insideBottom', offset: -5 }} stroke={ct.axis} />
              <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} stroke={ct.axis} />
              <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={ct.tooltipStyle} />
              <Legend />
              <Line type="monotone" dataKey="pct_terms_mapped" name="% Terms" stroke={ct.blue} strokeWidth={2} />
              <Line type="monotone" dataKey="pct_rows_mapped" name="% Rows" stroke={ct.emerald} strokeWidth={2} />
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
            className="w-full sm:w-[150px]"
            allowClear
            placeholder={t('mapping.all_domains', 'All domains')}
          />
        }
      >
        {strategyData.length > 0 ? (
          <>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={strategyData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} stroke={ct.axis} />
                <YAxis type="category" dataKey="strategy" width={120} tick={{ fontSize: 12 }} stroke={ct.axis} />
                <RechartsTooltip cursor={false} formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={ct.tooltipStyle} />
                <Legend />
                <Bar dataKey="approval_rate" name={t('mapping.approval_rate', 'Approval %')} fill={ct.emerald} stackId="a" activeBar={(p: any) => <Rectangle {...p} y={p.y - 5} height={p.height + 10} />} />
                <Bar dataKey="modification_rate" name={t('mapping.modification_rate', 'Modification %')} fill={ct.orange} stackId="a" activeBar={(p: any) => <Rectangle {...p} y={p.y - 5} height={p.height + 10} />} />
                <Bar dataKey="rejection_rate" name={t('mapping.rejection_rate', 'Rejection %')} fill={ct.red} stackId="a" activeBar={(p: any) => <Rectangle {...p} y={p.y - 5} height={p.height + 10} />} />
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
    {
      title: t('mapping.source_value', 'Source Value'), dataIndex: 'source_value', key: 'sv', ellipsis: true,
      render: (_: string, r: UnmappedItem) => {
        let label = r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value;
        if (r.source_atc) label += ` [ATC: ${r.source_atc}]`;
        return label;
      },
    },
    { title: t('mapping.n_records', 'Records'), dataIndex: 'n_records', key: 'nr',
      render: (v: number) => v.toLocaleString(), sorter: (a: UnmappedItem, b: UnmappedItem) => a.n_records - b.n_records },
    { title: t('mapping.n_persons', 'Persons'), dataIndex: 'n_persons', key: 'np',
      render: (v: number) => v.toLocaleString() },
    {
      title: t('concept.mapped_concept', 'Mapped Concept'),
      dataIndex: 'mapped_concept_id' as any,
      key: 'mapped',
      ellipsis: true,
      render: (_: any, r: UnmappedItem) => {
        if (!r.mapped_concept_id) return <Tag>—</Tag>;
        const tooltip = r.pending
          ? `${t('concept.pending_mapping_tooltip', 'Mapping decided in OPAL but not yet applied to the CDM')}${r.pending_user ? ` — ${r.pending_user}` : ''}`
          : undefined;
        return (
          <span className="text-emerald-accent" title={tooltip}>
            <span className="text-xs opacity-70 mr-1">#{r.mapped_concept_id}</span>
            {r.mapped_concept_name}
            {r.mapped_standard_concept === 'S' && <Tag color="green" className="ml-1">S</Tag>}
            {r.pending && <Tag color="orange" className="ml-1">{t('concept.pending_mapping', 'pending')}</Tag>}
          </span>
        );
      },
    },
  ];

  return (
    <div>
      <Card size="small" className="mb-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={domain}
            onChange={v => { setDomain(v); setPage(1); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-full sm:w-[150px]"
          />
          <Input
            prefix={<Search className="h-4 w-4" />}
            placeholder={t('mapping.search_unmapped', 'Filter...')}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="w-full sm:w-[250px]"
          />
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
        onRow={(r: UnmappedItem) => ({
          className: r.pending ? 'bg-orange-500/8 hover:bg-orange-500/12' : '',
        })}
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
  const [suggestWarnings, setSuggestWarnings] = useSessionState<string[]>('mapping:suggest:warnings', []);
  const [hasRun, setHasRun] = useSessionState('mapping:suggest:hasRun', false);
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
            const r = res.data.results || [];
            const w: string[] = (res.data as any).warnings || [];
            setResults(r);
            setSuggestWarnings(w);
            setLoading(false);
            setTaskId(null);
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            if (r.length > 0) {
              toast.success(t('mapping.suggestions_found', '{{count}} terms with suggestions', { count: r.length }));
            } else {
              toast.info(t('mapping.no_unmapped_found', 'No unmapped terms found for this domain'));
            }
            // Show warnings about limited strategies
            if (w.includes('source_name_missing')) {
              toast.warning(t('mapping.warn_no_source_name', 'No source_name column — relationship/ingredient/keyword strategies disabled'));
            }
            if (w.includes('no_reference_codebook')) {
              toast.warning(t('mapping.warn_no_ref', 'No reference codebook uploaded — code descriptions unavailable'));
            }
            if (w.includes('no_sapbert_embeddings')) {
              toast.warning(t('mapping.warn_no_sapbert', 'No SapBERT embeddings — semantic matching disabled'));
            }
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
        .catch(() => toast.error(t('mapping.load_failed', 'Failed to check suggestion status')));
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
    setHasRun(true);
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
      window.dispatchEvent(new Event('opal:badges-refresh'));
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
    if (count > 0) window.dispatchEvent(new Event('opal:badges-refresh'));
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
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={domain}
            onChange={setDomain}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-full sm:w-[150px]"
          />
          <NumberInput
            min={5}
            max={100}
            value={limit}
            onChange={v => setLimit(v as any)}
            onBlur={() => { if (!limit || limit < 5) setLimit(5); if (limit > 100) setLimit(100); }}
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

      {suggestWarnings.length > 0 && !loading && (
        <Alert
          type="warning"
          showIcon
          closable
          onClose={() => setSuggestWarnings([])}
          className="mb-3"
          message={
            <div className="space-y-1">
              {suggestWarnings.includes('source_name_missing') && (
                <div>{t('mapping.warn_no_source_name', 'No source_name column found — relationship, ingredient, and keyword strategies are disabled. Only exact match and fuzzy search are available.')}</div>
              )}
              {suggestWarnings.includes('no_reference_codebook') && (
                <div>{t('mapping.warn_no_ref', 'No reference codebook uploaded for this domain — code descriptions are unavailable. Upload one in the Reference tab to improve suggestions.')}</div>
              )}
              {suggestWarnings.includes('no_sapbert_embeddings') && (
                <div>{t('mapping.warn_no_sapbert', 'No SapBERT embeddings available — semantic matching is disabled.')}</div>
              )}
            </div>
          }
        />
      )}

      {loading ? (
        <div className="text-center py-10">
          <Spinner size="large" />
          <p className="text-sm text-text-muted mt-4">{t('mapping.loading_suggestions', 'Generating suggestions...')}</p>
        </div>
      ) : results.length === 0 ? (
        <Empty description={hasRun
          ? t('mapping.all_mapped', 'No unmapped terms found — all source values in this domain are already mapped.')
          : t('mapping.no_suggestions', 'Click Generate to get mapping suggestions')
        } />
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
  const [searchPage, setSearchPage] = useState(1);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedMap, setSelectedMap] = useState<Record<string, UnmappedItem>>({});
  const selectedSources = useMemo(() => Object.values(selectedMap), [selectedMap]);
  const selectionSize = selectedSources.length;
  const firstSelected = selectedSources[0] ?? null;
  const isSelected = (sv: string) => sv in selectedMap;
  const SEARCH_PAGE_SIZE = 50;

  // Concept lookup state
  const [conceptIdInput, setConceptIdInput] = useState<number | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [conceptInfo, setConceptInfo] = useState<{
    concept_id: number; concept_name: string; concept_code: string;
    vocabulary_id: string; domain_id: string; standard_concept: string | null;
    concept_class_id: string;
  } | null>(null);
  const [conceptError, setConceptError] = useState('');

  // Single suggestion state
  const [suggestions, setSuggestions] = useState<MappingSuggestion[]>([]);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestRan, setSuggestRan] = useState(false);

  // Decision state
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Reason modal state for suggestion approval
  const [suggReasonModal, setSuggReasonModal] = useState<{
    open: boolean;
    suggestion: MappingSuggestion | null;
    action: 'approved' | 'modified';
  }>({ open: false, suggestion: null, action: 'approved' });
  const [suggReasonText, setSuggReasonText] = useState('');

  const resetMappingForm = () => {
    setConceptInfo(null);
    setConceptIdInput(null);
    setConceptError('');
    setSuggestions([]);
    setSuggestRan(false);
  };
  const toggleSelect = (r: UnmappedItem) => {
    setSelectedMap(prev => {
      const next = { ...prev };
      if (r.source_value in next) delete next[r.source_value];
      else next[r.source_value] = r;
      return next;
    });
    resetMappingForm();
  };
  const clearSelection = () => { setSelectedMap({}); resetMappingForm(); };

  // Search source values
  const handleSearch = useCallback((p: number = 1) => {
    if (!search.trim()) return;
    setSearchLoading(true);
    if (p === 1) {
      clearSelection();
    }
    mappingApi.unmapped(cdmName, domain, p, SEARCH_PAGE_SIZE, search, true)
      .then(r => { setSearchResults(r.data.items); setSearchTotal(r.data.total); setSearchPage(p); })
      .catch(() => { setSearchResults([]); setSearchTotal(0); toast.error(t('common.error', 'An error occurred')); })
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

  // Generate suggestions for selected source (only when a single source is selected)
  const handleSuggest = useCallback(() => {
    if (selectionSize !== 1 || !firstSelected) return;
    setSuggestLoading(true);
    setSuggestRan(true);
    setSuggestions([]);
    mappingApi.suggest(cdmName, domain, firstSelected.source_value, firstSelected.source_name || '')
      .then(r => setSuggestions(r.data.suggestions || []))
      .catch(() => toast.error(t('common.error', 'An error occurred')))
      .finally(() => setSuggestLoading(false));
  }, [cdmName, domain, firstSelected, selectionSize, t, toast]);

  // Open the reason modal before approving a suggestion
  const handleApproveSuggestion = (s: MappingSuggestion, action: 'approved' | 'modified' = 'approved') => {
    setSuggReasonText('');
    setSuggReasonModal({ open: true, suggestion: s, action });
  };

  // Confirm approval after reason modal — iterates over all selected sources
  const handleConfirmSuggestion = async () => {
    const s = suggReasonModal.suggestion;
    const action = suggReasonModal.action;
    if (selectionSize === 0 || !s) return;
    setSubmitting(true);
    try {
      const results = await Promise.allSettled(selectedSources.map(src =>
        mappingApi.decide({
          cdm_name: cdmName,
          domain,
          source_value: src.source_value,
          source_name: src.source_name || '',
          action,
          target_concept_id: s.concept_id,
          target_concept_name: s.concept_name,
          target_vocabulary_id: s.vocabulary_id,
          suggestion_source: s.source || 'manual',
          confidence_score: s.confidence,
          reason: suggReasonText,
        })
      ));
      const ok = results.filter(r => r.status === 'fulfilled').length;
      const failed = results.length - ok;
      if (ok > 0) toast.success(`${t('mapping.approved', 'Approved')}: ${ok} → ${s.concept_name}`);
      if (failed > 0) toast.error(t('mapping.decision_failed', 'Decision failed') + ` (${failed})`);
      window.dispatchEvent(new Event('opal:badges-refresh'));
      setSuggReasonModal({ open: false, suggestion: null, action: 'approved' });
      setSuggReasonText('');
      clearSelection();
      // Refresh search
      if (search.trim()) {
        mappingApi.unmapped(cdmName, domain, searchPage, SEARCH_PAGE_SIZE, search, true)
          .then(r => { setSearchResults(r.data.items); setSearchTotal(r.data.total); })
          .catch(() => {});
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || t('mapping.decision_failed', 'Decision failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const confidenceColor = (c: number): 'green' | 'orange' | 'red' => c >= 80 ? 'green' : c >= 50 ? 'orange' : 'red';
  const sourceLabel = (s: string) => {
    const labels: Record<string, string> = { exact: 'Exact', relationship: 'Maps to', fuzzy: 'Fuzzy', contextual: 'Context', ingredient: 'Ingredient', synonym: 'Synonym', sapbert: 'SapBERT' };
    return labels[s] || s;
  };

  // Submit manual mapping — iterates over all selected sources to the same concept
  const handleApprove = async () => {
    if (selectionSize === 0 || !conceptInfo) return;
    setSubmitting(true);
    try {
      const results = await Promise.allSettled(selectedSources.map(src =>
        mappingApi.decide({
          cdm_name: cdmName,
          domain,
          source_value: src.source_value,
          source_name: src.source_name || '',
          action: 'approved',
          target_concept_id: conceptInfo.concept_id,
          target_concept_name: conceptInfo.concept_name,
          target_vocabulary_id: conceptInfo.vocabulary_id,
          suggestion_source: 'manual',
          confidence_score: 100,
          reason: reason || '',
        })
      ));
      const ok = results.filter(r => r.status === 'fulfilled').length;
      const failed = results.length - ok;
      if (ok > 0) toast.success(`${t('mapping.approved', 'Approved')}: ${ok} → ${conceptInfo.concept_name}`);
      if (failed > 0) toast.error(t('mapping.decision_failed', 'Decision failed') + ` (${failed})`);
      window.dispatchEvent(new Event('opal:badges-refresh'));
      clearSelection();
      setReason('');
      // Refresh search results to remove mapped item
      if (search.trim()) {
        mappingApi.unmapped(cdmName, domain, searchPage, SEARCH_PAGE_SIZE, search, true)
          .then(r => { setSearchResults(r.data.items); setSearchTotal(r.data.total); })
          .catch(() => toast.error(t('mapping.refresh_failed', 'Failed to refresh results')));
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || t('mapping.decision_failed', 'Decision failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const allOnPageSelected = searchResults.length > 0 && searchResults.every(r => isSelected(r.source_value));
  const someOnPageSelected = !allOnPageSelected && searchResults.some(r => isSelected(r.source_value));
  const toggleAllOnPage = () => {
    if (allOnPageSelected) {
      setSelectedMap(prev => {
        const next = { ...prev };
        for (const r of searchResults) delete next[r.source_value];
        return next;
      });
    } else {
      setSelectedMap(prev => {
        const next = { ...prev };
        for (const r of searchResults) next[r.source_value] = r;
        return next;
      });
    }
    resetMappingForm();
  };

  const searchColumns: Column<UnmappedItem>[] = [
    {
      title: (
        <Checkbox
          checked={allOnPageSelected}
          indeterminate={someOnPageSelected}
          onChange={toggleAllOnPage}
        />
      ) as any,
      dataIndex: '__select' as any,
      key: 'select',
      width: 40,
      render: (_: any, r: UnmappedItem) => (
        <Checkbox checked={isSelected(r.source_value)} onChange={() => toggleSelect(r)} />
      ),
    },
    {
      title: t('mapping.source_value', 'Source Value'), dataIndex: 'source_value', key: 'sv', ellipsis: true,
      render: (_: string, r: UnmappedItem) => {
        let label = r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value;
        if (r.source_atc) label += ` [ATC: ${r.source_atc}]`;
        return label;
      },
    },
    { title: t('mapping.n_records', 'Records'), dataIndex: 'n_records', key: 'nr',
      render: (v: number) => v.toLocaleString() },
    { title: t('mapping.n_persons', 'Persons'), dataIndex: 'n_persons', key: 'np',
      render: (v: number) => v.toLocaleString() },
    {
      title: t('concept.mapped_concept', 'Mapped Concept'),
      dataIndex: 'mapped_concept_id' as any,
      key: 'mapped',
      ellipsis: true,
      render: (_: any, r: UnmappedItem) => {
        if (!r.mapped_concept_id) return <Tag>—</Tag>;
        const tooltip = r.pending
          ? `${t('concept.pending_mapping_tooltip', 'Mapping decided in OPAL but not yet applied to the CDM')}${r.pending_user ? ` — ${r.pending_user}` : ''}`
          : undefined;
        return (
          <span className="text-emerald-accent" title={tooltip}>
            <span className="text-xs opacity-70 mr-1">#{r.mapped_concept_id}</span>
            {r.mapped_concept_name}
            {r.mapped_standard_concept === 'S' && <Tag color="green" className="ml-1">S</Tag>}
            {r.pending && <Tag color="orange" className="ml-1">{t('concept.pending_mapping', 'pending')}</Tag>}
          </span>
        );
      },
    },
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
            onChange={v => { setDomain(v); setSearchResults([]); clearSelection(); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-full sm:w-[150px]"
          />
          <Input
            prefix={<Search className="h-4 w-4" />}
            placeholder={t('mapping.search_source_code', 'Search local code...')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSearch(1); }}
            className="w-full sm:w-[300px]"
          />
          <Button variant="primary" onClick={() => handleSearch(1)} loading={searchLoading}>
            {t('mapping.search', 'Search')}
          </Button>
        </div>

        {searchResults.length > 0 && (
          <>
            <Table
              dataSource={searchResults}
              rowKey="source_value"
              size="small"
              pagination={{ pageSize: SEARCH_PAGE_SIZE, current: searchPage, total: searchTotal, onChange: (p: number) => handleSearch(p) }}
              columns={searchColumns}
              onRow={(record) => ({
                onClick: () => toggleSelect(record),
                className: [
                  isSelected(record.source_value) ? 'bg-emerald-accent/10' : '',
                  record.pending && !isSelected(record.source_value) ? 'bg-orange-500/8 hover:bg-orange-500/12' : '',
                ].filter(Boolean).join(' '),
              })}
            />
            <div className="flex items-center justify-between mt-2">
              <span className="text-text-muted text-sm">
                {searchTotal} {t('mapping.results_found', 'results found')} — {t('mapping.click_or_check_to_select', 'click a row or use the checkbox to select')}
              </span>
              {selectionSize > 0 && (
                <span className="text-emerald-accent text-sm">
                  {selectionSize} {t('mapping.selected', 'selected')}
                  <button onClick={clearSelection} className="ml-2 text-xs text-text-muted hover:text-text-bright bg-transparent border-none cursor-pointer underline">
                    {t('common.clear', 'clear')}
                  </button>
                </span>
              )}
            </div>
          </>
        )}
      </Card>

      {/* Step 2: Selected source info + concept ID input */}
      {selectionSize > 0 && (
        <Card
          size="small"
          title={<span className="inline-flex items-center gap-1.5"><Link className="h-4 w-4" />{t('mapping.manual_step2', 'Step 2 — Map to a concept')}{selectionSize > 1 && <Tag color="blue" className="ml-2">{selectionSize} {t('mapping.codes', 'codes')}</Tag>}</span>}
          className="mb-3"
        >
          {/* Selected source summary */}
          {selectionSize === 1 && firstSelected ? (
            <div className="bg-blue-500/8 border border-blue-500/25 rounded-lg px-4 py-2.5 mb-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <span className="text-text-dim text-[11px]">{t('mapping.source_value', 'Source Value')}</span>
                  <div className="font-semibold text-sm text-text-bright">{firstSelected.source_value}</div>
                </div>
                <div>
                  <span className="text-text-dim text-[11px]">{t('mapping.source_name', 'Source Name')}</span>
                  <div className="text-sm text-text-bright">{firstSelected.source_name || '—'}</div>
                </div>
                {firstSelected.source_atc && <div>
                  <span className="text-text-dim text-[11px]">ATC</span>
                  <div className="text-sm text-blue-400 font-medium">{firstSelected.source_atc}</div>
                </div>}
                <div>
                  <span className="text-text-dim text-[11px]">{t('mapping.n_records', 'Records')}</span>
                  <div className="font-semibold text-sm text-text-bright">{firstSelected.n_records.toLocaleString()}</div>
                </div>
                <div>
                  <span className="text-text-dim text-[11px]">{t('mapping.n_persons', 'Persons')}</span>
                  <div className="font-semibold text-sm text-text-bright">{firstSelected.n_persons.toLocaleString()}</div>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-blue-500/8 border border-blue-500/25 rounded-lg px-4 py-2.5 mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-text-bright font-semibold text-sm">
                  {selectionSize} {t('mapping.codes_selected', 'codes selected')}
                </span>
                <button onClick={clearSelection} className="text-xs text-text-muted hover:text-text-bright bg-transparent border-none cursor-pointer underline">
                  {t('common.clear', 'clear')}
                </button>
              </div>
              <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
                {selectedSources.map(src => (
                  <Tag key={src.source_value} className="flex items-center gap-1">
                    <span>{src.source_value}</span>
                    {src.source_name && <span className="text-text-dim text-[10px]">— {src.source_name.length > 30 ? src.source_name.slice(0, 30) + '…' : src.source_name}</span>}
                    <button onClick={() => toggleSelect(src)} className="ml-1 text-text-dim hover:text-text-bright bg-transparent border-none cursor-pointer leading-none" title={t('common.remove', 'remove')}>×</button>
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {selectionSize === 1 && firstSelected?.pending && firstSelected.mapped_concept_id && (
            <Alert
              type="warning"
              className="mb-4"
              message={
                <span>
                  <Tag color="orange" className="mr-2">{t('concept.pending_mapping', 'pending')}</Tag>
                  {t('mapping.already_decided', 'Already decided in OPAL')}: <span className="font-semibold">#{firstSelected.mapped_concept_id} — {firstSelected.mapped_concept_name}</span>
                  {firstSelected.pending_user && <span className="text-text-muted ml-1">({firstSelected.pending_user})</span>}
                </span>
              }
            />
          )}
          {selectionSize > 1 && selectedSources.some(s => s.pending) && (
            <Alert
              type="warning"
              className="mb-4"
              message={
                <span>
                  {selectedSources.filter(s => s.pending).length} {t('mapping.codes_already_decided', 'selected codes already have a pending mapping in OPAL — their decision will be overwritten.')}
                </span>
              }
            />
          )}

          {/* Auto-suggestions — only available when exactly 1 source is selected */}
          {selectionSize === 1 && (
          <div className="mb-4">
            <div className="flex items-center gap-3 mb-2">
              <Button
                variant="primary"
                icon={<Zap className="h-4 w-4" />}
                onClick={handleSuggest}
                loading={suggestLoading}
                size="small"
              >
                {t('mapping.generate_suggestions', 'Generate Suggestions')}
              </Button>
              {suggestRan && !suggestLoading && (
                <span className="text-text-muted text-sm">{suggestions.length} {t('mapping.suggestions_found_count', 'suggestion(s)')}</span>
              )}
            </div>

            {suggestLoading && (
              <div className="text-center py-4">
                <Spinner size="default" />
                <p className="text-xs text-text-muted mt-2">{t('mapping.loading_suggestions', 'Generating suggestions...')}</p>
              </div>
            )}

            {suggestRan && !suggestLoading && suggestions.length > 0 && (
              <div className="flex flex-col gap-0.5">
                {suggestions.map((s, i) => (
                  <div key={s.concept_id} className={`px-2 py-1 rounded flex justify-between items-center ${i === 0 ? 'bg-emerald-500/8' : 'bg-surface-light'}`}>
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
                          onClick={() => handleApproveSuggestion(s, i === 0 ? 'approved' : 'modified')}
                          disabled={submitting}
                        >
                          <Check className="h-4 w-4" />
                        </button>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {suggestRan && !suggestLoading && suggestions.length === 0 && (
              <span className="text-text-dim text-xs">{t('mapping.no_match', 'No suggestions found')}</span>
            )}
          </div>
          )}

          {selectionSize === 1 && (
            <div className="border-t border-glass-border pt-4 mt-2 mb-4">
              <span className="text-text-muted text-xs">{t('mapping.or_manual', 'Or map manually by concept ID:')}</span>
            </div>
          )}

          {/* Concept ID input */}
          <div className="flex items-center gap-3 mb-3">
            <span className="text-text-bright text-sm">{t('mapping.enter_concept_id', 'Concept ID')} <span className="text-red-400">*</span> :</span>
            <NumberInput
              className="w-full sm:w-[180px]"
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
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
                <div>
                  <span className="text-text-dim text-[11px]">Concept ID</span>
                  <div className="font-semibold text-text-bright">{conceptInfo.concept_id}</div>
                </div>
                <div>
                  <span className="text-text-dim text-[11px]">Concept Name</span>
                  <div className="font-semibold text-text-bright">{conceptInfo.concept_name}</div>
                </div>
                <div>
                  <span className="text-text-dim text-[11px]">Vocabulary</span>
                  <div><Tag>{conceptInfo.vocabulary_id}</Tag></div>
                </div>
                <div>
                  <span className="text-text-dim text-[11px]">Domain</span>
                  <div><Tag>{conceptInfo.domain_id}</Tag></div>
                </div>
                <div>
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
              <div>
                <label className="block text-text-bright text-sm mb-1">
                  {t('mapping.reason_label', 'Reason')} <span className="text-text-dim text-xs">({t('common.optional', 'optional')})</span>
                </label>
                <TextArea
                  rows={3}
                  placeholder={t('mapping.reason_placeholder', 'Why this mapping?')}
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                />
              </div>
              <Button
                variant="primary"
                icon={<Check className="h-4 w-4" />}
                onClick={handleApprove}
                loading={submitting}
                size="large"
                block
              >
                {t('mapping.approve_mapping', 'Approve Mapping')}: {selectionSize === 1 && firstSelected ? firstSelected.source_value : `${selectionSize} ${t('mapping.codes', 'codes')}`} → {conceptInfo.concept_name} ({conceptInfo.concept_id})
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* Empty state */}
      {selectionSize === 0 && searchResults.length === 0 && !searchLoading && (
        <Empty
          description={t('mapping.manual_description', 'Search for a local code, then enter a target concept ID to create a manual mapping.')}
          className="mt-12"
        />
      )}

      {/* Reason modal for suggestion approval */}
      <Modal
        open={suggReasonModal.open}
        onClose={() => setSuggReasonModal({ open: false, suggestion: null, action: 'approved' })}
        title={t('mapping.approve_reason', 'Approve — Reason')}
        footer={
          <>
            <Button onClick={() => setSuggReasonModal({ open: false, suggestion: null, action: 'approved' })}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" onClick={handleConfirmSuggestion} loading={submitting}>
              {t('mapping.approve', 'Approve')}
            </Button>
          </>
        }
      >
        {suggReasonModal.suggestion && selectionSize > 0 && (
          <div className="mb-2 text-sm">
            <Tag>{selectionSize === 1 && firstSelected ? firstSelected.source_value : `${selectionSize} ${t('mapping.codes', 'codes')}`}</Tag> → <span className="text-text-bright">{suggReasonModal.suggestion.concept_name}</span>
            <span className="text-text-dim text-[11px] ml-2">({suggReasonModal.suggestion.concept_id})</span>
          </div>
        )}
        <TextArea
          rows={3}
          placeholder={t('mapping.reason_placeholder', 'Reason (optional)')}
          value={suggReasonText}
          onChange={e => setSuggReasonText(e.target.value)}
          autoFocus
        />
      </Modal>
    </div>
  );
}

// ============ REASON CELL WITH CARD HOVER ============

function ReasonCell({ value }: { value: string }) {
  const [hovered, setHovered] = useState(false);
  const [pos, setPos] = useState<{
    top?: number; bottom?: number; left: number; width: number; maxHeight: number; placement: 'below' | 'above';
  } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const handleMouseEnter = () => {
    if (ref.current) {
      const cellRect = ref.current.getBoundingClientRect();
      const tr = ref.current.closest('tr');
      const trRect = tr?.getBoundingClientRect();
      const vh = window.innerHeight;
      const margin = 8;
      const anchorBottom = trRect ? trRect.bottom : cellRect.bottom;
      const anchorTop = trRect ? trRect.top : cellRect.top;
      const spaceBelow = vh - anchorBottom - margin;
      const spaceAbove = anchorTop - margin;
      const placeBelow = spaceBelow >= spaceAbove;
      setPos({
        ...(placeBelow ? { top: anchorBottom } : { bottom: vh - anchorTop }),
        left: cellRect.left,
        width: trRect ? trRect.right - cellRect.left : 300,
        maxHeight: Math.max(120, placeBelow ? spaceBelow : spaceAbove),
        placement: placeBelow ? 'below' : 'above',
      });
    }
    setHovered(true);
  };

  return (
    <div ref={ref} onMouseEnter={handleMouseEnter} onMouseLeave={() => setHovered(false)}>
      <span className="truncate block max-w-[140px] cursor-default">{value}</span>
      {pos && createPortal(
        <div style={{
          position: 'fixed',
          ...(pos.top !== undefined ? { top: pos.top } : { bottom: pos.bottom }),
          left: pos.left,
          width: 'fit-content',
          maxWidth: pos.width,
          maxHeight: pos.maxHeight,
          zIndex: 9999,
          pointerEvents: 'none',
          filter: 'drop-shadow(-2px 2px 8px rgba(50,50,0,0.3))',
          clipPath: hovered ? 'inset(0 0 0 0)' : 'inset(0 100% 0 0)',
          transition: '0.5s ease',
          overflow: 'hidden',
        }}>
          <div style={{
            padding: '14px 16px', backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-glass-border)',
            transition: '0.5s ease', fontSize: '0.85rem', color: 'var(--color-text-bright)',
            wordBreak: 'break-word', lineHeight: 1.5,
            maxHeight: pos.maxHeight,
            overflowY: 'auto',
          }}>
            <span style={{
              display: 'block',
              opacity: hovered ? 1 : 0,
              transition: '0.5s ease',
            }}>
              {value}
            </span>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

// ============ TAB 5: MAPPING HISTORY ============

function MappingHistoryTab({ cdmName, refreshKey }: { cdmName: string; refreshKey?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { roles, username: currentUser } = useAuth();
  const canWriteCdm = roles.includes('admin') || roles.includes('data-manager');
  const [items, setItems] = useState<MappingDecisionEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useSessionState('mapping:history:page', 1);
  const [filterDomain, setFilterDomain] = useSessionState('mapping:history:filterDomain', '');
  const [filterAction, setFilterAction] = useSessionState('mapping:history:filterAction', '');
  const [filterUser, setFilterUser] = useSessionState('mapping:history:filterUser', '');
  const [sortKey, setSortKey] = useSessionState<string | null>('mapping:history:sortKey', null);
  const [sortDir, setSortDir] = useSessionState<'asc' | 'desc'>('mapping:history:sortDir', 'asc');
  const [availableUsers, setAvailableUsers] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [applyDomain, setApplyDomain] = useSessionState('mapping:history:applyDomain', 'Condition');
  const [applyPreview, setApplyPreview] = useState<{ total_decisions: number; impacted_rows: number; impacted_persons: number } | null>(null);
  const [accessibleCdms, setAccessibleCdms] = useState<string[]>([]);
  const [targetCdms, setTargetCdms] = useState<string[]>([cdmName]);

  useEffect(() => {
    cdmAccessApi.getAccessibleCdms().then(r => setAccessibleCdms(r.data.cdms)).catch(() => setAccessibleCdms([cdmName]));
  }, [cdmName]);
  useEffect(() => { setTargetCdms([cdmName]); }, [cdmName]);

  const load = useCallback(() => {
    setLoading(true);
    mappingApi.history(cdmName, filterDomain || undefined, filterAction || undefined, page, undefined, filterUser || undefined, sortKey, sortDir)
      .then(r => { setItems(r.data.items); setTotal(r.data.total); if (r.data.users) setAvailableUsers(r.data.users); })
      .catch(() => { setItems([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [cdmName, filterDomain, filterAction, filterUser, page, sortKey, sortDir]);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Withdraw confirm state
  const [withdrawConfirm, setWithdrawConfirm] = useState<{ open: boolean; id: number }>({ open: false, id: 0 });

  const handleWithdraw = async (id: number) => {
    try {
      await mappingApi.withdraw(id);
      toast.success('Decision withdrawn');
      load();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Withdraw failed');
    }
  };

  const handleApproveFromHistory = async (row: GroupedRow) => {
    try {
      await mappingApi.decide({
        cdm_name: cdmName,
        domain: row.domain,
        source_value: row.source_value,
        source_name: row.source_name,
        action: 'approved',
        target_concept_id: row.target_concept_id ?? undefined,
        target_concept_name: row.target_concept_name || undefined,
        target_vocabulary_id: row.target_vocabulary_id || undefined,
        suggestion_source: 'history',
        confidence_score: row.confidence_score ?? undefined,
      });
      toast.success('Approved');
      load();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Approve failed');
    }
  };

  const handleReject = async (row: GroupedRow) => {
    try {
      // Reject all decisions in this grouped row
      for (const id of row.ids) {
        await mappingApi.reject(id);
      }
      toast.success('Rejected');
      load();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Reject failed');
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
      const r = await mappingApi.apply(cdmName, applyDomain, writeToCdm, writeToCdm ? targetCdms : undefined);
      const data: any = r.data;
      if (writeToCdm && data.per_cdm) {
        const summary = Object.entries(data.per_cdm)
          .map(([c, v]: [string, any]) => v.error ? `${c}: ERROR` : `${c}: ${v.updated_rows} rows`)
          .join(' · ');
        toast.success(`Batch ${data.batch_id?.slice(0, 8)} — ${summary}`);
      } else {
        toast.success(`Applied ${data.count} mappings${writeToCdm ? ' to CDM' : ''}`);
      }
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
    const colors: Record<string, 'green' | 'blue' | 'red' | 'orange' | 'default'> = { approved: 'green', modified: 'blue', rejected: 'red', rolled_back: 'default' };
    return colors[a] || 'default';
  };

  const actionOptions = [
    { value: 'approved', label: 'Approved' },
    { value: 'modified', label: 'Modified' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'rolled_back', label: 'Rolled back' },
  ];

  // ── Group decisions: merge rows when same source_value + same target_concept_id ──
  interface GroupedRow {
    key: string;
    ids: number[];
    userIdMap: Record<string, number>; // user → decision id
    domain: string;
    source_value: string;
    source_name: string;
    action: string;
    target_concept_id: number | null;
    target_concept_name: string;
    target_vocabulary_id: string;
    confidence_score: number | null;
    reason: string;
    users: string[];
    created_at: string | null;
    status: 'consensus' | 'conflict' | 'single';
  }

  const groupedRows = useMemo(() => {
    // 1. Group by (source_value, domain, target_concept_id, action)
    const groupMap = new Map<string, GroupedRow>();
    for (const item of items) {
      const gk = `${item.domain}::${item.source_value}::${item.target_concept_id ?? 'null'}::${item.action}`;
      const existing = groupMap.get(gk);
      if (existing) {
        if (!existing.users.includes(item.user)) existing.users.push(item.user);
        existing.ids.push(item.id);
        existing.userIdMap[item.user] = item.id;
        // Keep highest confidence
        if (item.confidence_score != null && (existing.confidence_score == null || item.confidence_score > existing.confidence_score))
          existing.confidence_score = item.confidence_score;
        // Keep most recent date
        if (item.created_at && (!existing.created_at || item.created_at > existing.created_at))
          existing.created_at = item.created_at;
        // Append reason
        if (item.reason && !existing.reason.includes(item.reason))
          existing.reason = existing.reason ? `${existing.reason}; ${item.reason}` : item.reason;
      } else {
        groupMap.set(gk, {
          key: gk,
          ids: [item.id],
          userIdMap: { [item.user]: item.id },
          domain: item.domain,
          source_value: item.source_value,
          source_name: item.source_name,
          action: item.action,
          target_concept_id: item.target_concept_id,
          target_concept_name: item.target_concept_name,
          target_vocabulary_id: item.target_vocabulary_id,
          confidence_score: item.confidence_score,
          reason: item.reason || '',
          users: [item.user],
          created_at: item.created_at,
          status: 'single',
        });
      }
    }

    const groups = Array.from(groupMap.values());

    // 2. Determine consensus/conflict per source_value+domain
    // Group by source_value+domain to check if multiple different targets exist
    const svGroups = new Map<string, GroupedRow[]>();
    for (const g of groups) {
      const svKey = `${g.domain}::${g.source_value}`;
      const arr = svGroups.get(svKey) || [];
      arr.push(g);
      svGroups.set(svKey, arr);
    }
    for (const arr of svGroups.values()) {
      const mappedGroups = arr.filter(g => g.action === 'approved' || g.action === 'modified');
      const hasMultipleTargets = new Set(mappedGroups.map(g => g.target_concept_id)).size > 1;
      for (const g of mappedGroups) {
        if (g.users.length > 1) {
          // Multiple users agree on this target → consensus (tick vert)
          // But also flag conflict if other groups map to a different target
          g.status = hasMultipleTargets ? 'conflict' : 'consensus';
        } else if (hasMultipleTargets) {
          // Single user but other mappings exist for this source → conflict
          g.status = 'conflict';
        }
        // else: single user, single target → stays 'single' (no icon)
      }
      // Non-mapped groups (rejected, rolled_back) stay 'single'
    }

    // 3. Sort grouped rows. When the user has chosen a sort, follow it so that
    //    grouping doesn't override server ordering. Otherwise group by source_value.
    const mul = sortDir === 'desc' ? -1 : 1;
    const cmpStr = (a?: string | null, b?: string | null) => (a || '').localeCompare(b || '') * mul;
    const cmpNum = (a?: number | null, b?: number | null) => ((a ?? 0) - (b ?? 0)) * mul;
    groups.sort((a, b) => {
      switch (sortKey) {
        case 'domain': return cmpStr(a.domain, b.domain) || a.source_value.localeCompare(b.source_value);
        case 'source': return cmpStr(a.source_name || a.source_value, b.source_name || b.source_value);
        case 'action': return cmpStr(a.action, b.action) || a.source_value.localeCompare(b.source_value);
        case 'target': return cmpStr(a.target_concept_name, b.target_concept_name);
        case 'confidence': return cmpNum(a.confidence_score, b.confidence_score);
        case 'reason': return cmpStr(a.reason, b.reason);
        case 'user': return cmpStr(a.users[0], b.users[0]);
        case 'date': return cmpStr(a.created_at, b.created_at);
        default: {
          const sv = a.source_value.localeCompare(b.source_value);
          if (sv !== 0) return sv;
          const dom = a.domain.localeCompare(b.domain);
          if (dom !== 0) return dom;
          return (a.target_concept_id ?? 0) - (b.target_concept_id ?? 0);
        }
      }
    });

    return groups;
  }, [items, sortKey, sortDir]);

  const columns: Column<GroupedRow>[] = [
    { title: '', key: 'status', width: 45,
      render: (_: any, r: GroupedRow) => {
        if (r.status === 'single') return null;
        const hasConsensus = r.users.length > 1;
        const hasConflict = r.status === 'conflict';
        return (
          <div className="flex items-center gap-0.5">
            {hasConsensus && <Tooltip title={`Consensus — ${r.users.length} users`}><CheckCircle2 className="h-4 w-4 text-emerald-400" /></Tooltip>}
            {hasConflict && <Tooltip title="Conflit — cible différente pour ce terme"><AlertTriangle className="h-4 w-4 text-amber-400" /></Tooltip>}
          </div>
        );
      } },
    { title: t('mapping.domain', 'Domain'), dataIndex: 'domain', key: 'domain', width: 100, sorter: true },
    { title: 'Source', key: 'source', width: 200, sorter: true,
      render: (_: any, r: GroupedRow) => r.source_name
        ? <span title={r.source_value}>{r.source_name} <span className="text-text-muted text-[10px]">({r.source_value})</span></span>
        : <span>{r.source_value}</span> },
    { title: t('mapping.action', 'Action'), key: 'action', width: 100, sorter: true,
      render: (_: any, r: GroupedRow) => {
        const isPending = (r.action === 'approved' || r.action === 'modified') && r.users.length < 2;
        const label = isPending ? 'pending' : r.action;
        const color = isPending ? 'orange' as const : actionColor(r.action);
        return <Tag color={color}>{label}</Tag>;
      } },
    { title: t('mapping.target', 'Target'), key: 'target', width: 200, sorter: true,
      render: (_: any, r: GroupedRow) => r.target_concept_id
        ? <span>{r.target_concept_name} <span className="text-text-muted text-[10px]">({r.target_concept_id})</span></span>
        : <span className="text-text-dim">—</span> },
    { title: t('mapping.confidence', 'Confidence'), dataIndex: 'confidence_score', key: 'confidence', width: 80, sorter: true,
      render: (v: number | null) => v != null ? <Tag>{v}%</Tag> : '—' },
    { title: t('mapping.reason', 'Reason'), dataIndex: 'reason', key: 'reason', width: 140, ellipsis: true, sorter: true,
      render: (v: string) => v
        ? <ReasonCell value={v} />
        : <span className="text-text-dim">—</span> },
    { title: t('mapping.users', 'Users'), key: 'user', width: 130, sorter: true,
      render: (_: any, r: GroupedRow) => (
        <div className="flex flex-wrap gap-1">
          {r.users.map(u => <Tag key={u}>{u}</Tag>)}
          {r.users.length > 1 && <span className="text-[10px] text-emerald-400 font-medium ml-1">×{r.users.length}</span>}
        </div>
      ) },
    { title: t('mapping.date', 'Date'), dataIndex: 'created_at', key: 'date', width: 110, sorter: true,
      render: (v: string) => v?.substring(0, 16).replace('T', ' ') },
    { title: '', key: 'actions', width: 110,
      render: (_: any, r: GroupedRow) => {
        if (r.action === 'rolled_back') return null;
        const isAdmin = roles.includes('admin');
        const alreadyMine = r.users.includes(currentUser);
        const canReject = r.action !== 'rejected' && (alreadyMine || isAdmin);
        const canApprove = !alreadyMine && r.target_concept_id && r.action !== 'rejected';
        const canRollback = alreadyMine || isAdmin;
        return (
          <div className="flex items-center gap-1">
            {canApprove && (
              <Tooltip title="Approve this mapping for me">
                <Button size="small" variant="link" onClick={() => handleApproveFromHistory(r)}>
                  <Check className="h-4 w-4 text-emerald-400" />
                </Button>
              </Tooltip>
            )}
            {canReject && (
              <Tooltip title="Reject this mapping">
                <Button size="small" variant="link" onClick={() => handleReject(r)}>
                  <X className="h-4 w-4 text-red-400" />
                </Button>
              </Tooltip>
            )}
            {canRollback && r.userIdMap[currentUser] && (
              <Tooltip title="Retirer ma décision">
                <Button size="small" variant="link" onClick={() => setWithdrawConfirm({ open: true, id: r.userIdMap[currentUser] })}>
                  <Undo2 className="h-4 w-4" />
                </Button>
              </Tooltip>
            )}
          </div>
        );
      } },
  ];

  return (
    <div>
      <Confirm
        open={withdrawConfirm.open}
        onClose={() => setWithdrawConfirm({ open: false, id: 0 })}
        onConfirm={() => handleWithdraw(withdrawConfirm.id)}
        title="Retirer ma décision ?"
        confirmText="Retirer"
        danger
      />

      <Card size="small" className="mb-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={filterDomain}
            onChange={v => { setFilterDomain(v); setPage(1); }}
            options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
            className="w-full sm:w-[130px]"
            allowClear
            placeholder="All domains"
          />
          <Select
            value={filterAction}
            onChange={v => { setFilterAction(v); setPage(1); }}
            options={actionOptions}
            className="w-full sm:w-[120px]"
            allowClear
            placeholder="All actions"
          />
          <Select
            value={filterUser}
            onChange={v => { setFilterUser(v); setPage(1); }}
            options={availableUsers.map(u => ({ value: u, label: u }))}
            className="w-full sm:w-[130px]"
            allowClear
            placeholder="All users"
          />
          <Button icon={<RefreshCw className="h-4 w-4" />} size="small" onClick={load} loading={loading} />
          <span className="text-text-muted text-sm">{total} {t('mapping.decisions', 'decisions')}</span>

          <span className="border-l border-glass-border pl-3 flex items-center gap-2">
            <span className="text-xs text-text-bright">{t('mapping.apply_to', 'Apply to')}:</span>
            <Select
              size="small"
              value={applyDomain}
              onChange={setApplyDomain}
              options={DOMAIN_LIST.map(d => ({ value: d, label: t(`domains.${d}`, d) }))}
              className="w-full sm:w-[120px]"
            />
            <Button size="small" onClick={handleApplyPreview}>Preview</Button>
          </span>
        </div>
      </Card>

      {applyPreview && (
        <Card size="small" className="mb-3 border-red-500/50 border-2">
          <div className="bg-red-500/8 border border-red-500/25 rounded px-3 py-2 mb-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              <span className="font-semibold text-red-400">
                {t('mapping.write_warning', 'This action will directly UPDATE the concept_id column in the clinical table of the selected CDMs. A rollback log is kept but the operation impacts production data.')}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
              {t('mapping.export_stcm_instead', 'Export as CSV (recommended)')}
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
                <span className="font-semibold text-red-400">{t('mapping.write_confirm_title')}</span>
              </span>
            }
            footer={
              <>
                <Button onClick={() => { setWriteConfirmOpen(false); setWriteConfirmText(''); }}>
                  {t('mapping.write_confirm_cancel')}
                </Button>
                <Button
                  variant="danger"
                  loading={applyLoading}
                  disabled={writeConfirmText !== 'APPLIQUER' || targetCdms.length === 0}
                  onClick={() => handleApply(true)}
                >
                  {t('mapping.write_confirm_submit')}
                </Button>
              </>
            }
          >
            <div className="mb-4">
              <span className="text-text-bright">
                Vous allez appliquer <strong>{applyPreview.total_decisions} mappings</strong> du domaine <strong>{applyDomain}</strong> en faisant un <code>UPDATE</code> direct sur la colonne <code>{applyDomain.toLowerCase()}_concept_id</code> de la table clinique.
              </span>
            </div>
            <div className="mb-4">
              <span className="text-text-bright">
                Impact estimé : <strong>{applyPreview.impacted_rows.toLocaleString()} lignes</strong> et <strong>{applyPreview.impacted_persons.toLocaleString()} patients</strong> par CDM.
              </span>
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-text-muted mb-1">
                {t('mapping.target_cdms', 'Target CDM(s) to apply mapping to')}
              </label>
              <div className="flex flex-wrap gap-1">
                {accessibleCdms.map(c => {
                  const checked = targetCdms.includes(c);
                  return (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setTargetCdms(prev => prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])}
                      className={`px-2 py-1 text-xs rounded border transition-all ${
                        checked
                          ? 'bg-emerald-accent/20 border-emerald-accent/40 text-emerald-accent font-medium'
                          : 'bg-deep-base border-glass-border text-text-dim hover:text-text-muted'
                      }`}
                    >
                      {c}
                    </button>
                  );
                })}
              </div>
              <div className="text-text-dim text-[11px] mt-1">{targetCdms.length} CDM(s) sélectionné(s)</div>
            </div>
            <div className="bg-yellow-500/10 border border-yellow-500/25 rounded px-3 py-2 mb-4">
              <span className="text-yellow-400 text-xs">
                Tapez <code className="font-mono font-bold">APPLIQUER</code> pour confirmer.
              </span>
            </div>
            <Input
              placeholder="APPLIQUER"
              value={writeConfirmText}
              onChange={e => setWriteConfirmText(e.target.value)}
              error={writeConfirmText && writeConfirmText !== 'APPLIQUER' ? 'Le texte ne correspond pas' : undefined}
            />
          </Modal>
        </Card>
      )}

      <Table
        dataSource={groupedRows}
        columns={columns}
        rowKey="key"
        loading={loading}
        pagination={{ pageSize: 50, current: page, total, onChange: setPage }}
        serverSort={{
          key: sortKey,
          dir: sortDir,
          onChange: (k, d) => { setSortKey(k); setSortDir(d); setPage(1); },
        }}
        size="small"
      />
    </div>
  );
}

// ============ TAB: APPLY LOG ============

interface ApplyBatch {
  batch_id: string;
  domain: string;
  applied_by: string;
  applied_at: string | null;
  total_rows: number;
  rolled_back: boolean;
}

interface BatchDetail {
  batch_id: string;
  source_cdm_name: string;
  target_cdm_name: string;
  domain: string;
  table_name: string;
  column_name: string;
  applied_by: string;
  applied_at: string | null;
  rolled_back: boolean;
  entries: {
    source_value: string;
    previous_concept_id: number | null;
    previous_concept_name: string;
    new_concept_id: number;
    new_concept_name: string;
    row_count: number;
  }[];
}

function ApplyLogTab({ cdmName }: { cdmName: string }) {
  const toast = useToast();
  const { roles } = useAuth();
  const canRollback = roles.includes('admin') || roles.includes('data-manager');
  const [accessibleCdms, setAccessibleCdms] = useState<string[]>([]);
  const [filterCdm, setFilterCdm] = useSessionState('mapping:applylog:cdm', cdmName);
  const [batches, setBatches] = useState<ApplyBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [rollbackId, setRollbackId] = useState<string | null>(null);
  const [rollbackLoading, setRollbackLoading] = useState(false);
  const [detailBatch, setDetailBatch] = useState<BatchDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const openDetail = async (batchId: string) => {
    setDetailLoading(true);
    setDetailBatch(null);
    try {
      const r = await mappingApi.applyBatchDetail(batchId);
      setDetailBatch(r.data);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to load batch detail');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    cdmAccessApi.getAccessibleCdms()
      .then(r => setAccessibleCdms(r.data.cdms))
      .catch(() => setAccessibleCdms([cdmName]));
  }, [cdmName]);

  const load = useCallback(() => {
    if (!filterCdm) return;
    setLoading(true);
    mappingApi.applyHistory(filterCdm)
      .then(r => setBatches(r.data.batches))
      .catch(() => setBatches([]))
      .finally(() => setLoading(false));
  }, [filterCdm]);

  useEffect(() => { load(); }, [load]);

  const handleRollback = async () => {
    if (!rollbackId) return;
    setRollbackLoading(true);
    try {
      const r = await mappingApi.applyRollback(rollbackId);
      const data: any = r.data;
      const summary = Object.entries(data.per_cdm || {})
        .map(([c, v]: [string, any]) => v.error ? `${c}: ERROR` : `${c}: ${v.restored_rows} rows restaurées`)
        .join(' · ');
      toast.success(summary || 'Rollback effectué');
      setRollbackId(null);
      load();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Rollback failed');
    } finally {
      setRollbackLoading(false);
    }
  };

  const columns: Column<ApplyBatch>[] = [
    {
      key: 'batch_id', title: 'Batch', dataIndex: 'batch_id',
      render: (v: string) => <code className="text-xs font-mono">{v.slice(0, 8)}</code>,
      width: 100,
    },
    { key: 'domain', title: 'Domain', dataIndex: 'domain', width: 130, render: (v: string) => <Tag>{v}</Tag> },
    { key: 'applied_by', title: 'Par', dataIndex: 'applied_by', width: 150 },
    {
      key: 'applied_at', title: 'Date', dataIndex: 'applied_at',
      render: (v: string) => v ? new Date(v).toLocaleString() : '—',
      width: 180,
    },
    {
      key: 'total_rows', title: 'Lignes modifiées', dataIndex: 'total_rows',
      render: (v: number) => v.toLocaleString(),
      width: 130,
    },
    {
      key: 'status', title: 'Status', dataIndex: 'rolled_back',
      render: (v: boolean) => v ? <Tag color="orange">Rolled back</Tag> : <Tag color="green">Active</Tag>,
      width: 110,
    },
    {
      key: 'actions', title: '', width: 200,
      render: (_: any, r: ApplyBatch) => (
        <div className="flex items-center gap-1">
          <Button size="small" icon={<Search className="h-3.5 w-3.5" />} onClick={() => openDetail(r.batch_id)}>
            Détails
          </Button>
          {!r.rolled_back && canRollback && (
            <Button size="small" variant="danger" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => setRollbackId(r.batch_id)}>
              Rollback
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <Card size="small" className="mb-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-text-bright text-sm">CDM cible :</span>
          <Select
            value={filterCdm}
            onChange={v => setFilterCdm(v)}
            options={accessibleCdms.map(c => ({ value: c, label: c }))}
            className="w-full sm:w-[280px]"
          />
          <Button icon={<RefreshCw className="h-4 w-4" />} size="small" onClick={load} loading={loading} />
          <span className="text-text-muted text-sm">{batches.length} batch(es)</span>
        </div>
      </Card>

      <Table<ApplyBatch>
        dataSource={batches}
        columns={columns}
        rowKey="batch_id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 25 }}
        emptyText="Aucune modification appliquée sur ce CDM"
      />

      <Modal
        open={detailBatch !== null || detailLoading}
        onClose={() => setDetailBatch(null)}
        title={detailBatch ? `Batch ${detailBatch.batch_id.slice(0, 8)}` : 'Chargement...'}
        width="max-w-4xl"
      >
        {detailLoading && <Spinner size="default" />}
        {detailBatch && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3 text-xs">
              <div>
                <span className="text-text-dim">Source CDM</span>
                <div className="text-text-bright font-mono">{detailBatch.source_cdm_name}</div>
              </div>
              <div>
                <span className="text-text-dim">Target CDM</span>
                <div className="text-text-bright font-mono">{detailBatch.target_cdm_name}</div>
              </div>
              <div>
                <span className="text-text-dim">Table modifiée</span>
                <div className="text-text-bright font-mono">{detailBatch.table_name}.{detailBatch.column_name}</div>
              </div>
              <div>
                <span className="text-text-dim">Domaine</span>
                <div><Tag>{detailBatch.domain}</Tag></div>
              </div>
              <div>
                <span className="text-text-dim">Par</span>
                <div className="text-text-bright">{detailBatch.applied_by}</div>
              </div>
              <div>
                <span className="text-text-dim">Date</span>
                <div className="text-text-bright">{detailBatch.applied_at ? new Date(detailBatch.applied_at).toLocaleString() : '—'}</div>
              </div>
              <div>
                <span className="text-text-dim">Status</span>
                <div>{detailBatch.rolled_back ? <Tag color="orange">Rolled back</Tag> : <Tag color="green">Active</Tag>}</div>
              </div>
              <div>
                <span className="text-text-dim">Total entries</span>
                <div className="text-text-bright font-bold">{detailBatch.entries.length}</div>
              </div>
            </div>
            <div className="max-h-[450px] overflow-auto">
              <Table
                dataSource={detailBatch.entries}
                rowKey={(r: any) => `${r.source_value}-${r.previous_concept_id}`}
                size="small"
                pagination={{ pageSize: 50 }}
                columns={[
                  { key: 'source_value', title: 'Source code', dataIndex: 'source_value', width: 120 },
                  {
                    key: 'previous', title: 'Avant',
                    dataIndex: 'previous_concept_id',
                    render: (v: number | null, r: any) => v === null || v === 0
                      ? <span className="text-text-dim">— (non mappé)</span>
                      : <div><span className="font-mono text-xs">{v}</span>{r.previous_concept_name && <div className="text-[11px] text-text-dim">{r.previous_concept_name}</div>}</div>,
                  },
                  {
                    key: 'new', title: 'Après',
                    dataIndex: 'new_concept_id',
                    render: (v: number, r: any) => <div><span className="font-mono text-xs text-emerald-accent">{v}</span>{r.new_concept_name && <div className="text-[11px] text-text-bright">{r.new_concept_name}</div>}</div>,
                  },
                  {
                    key: 'row_count', title: 'Lignes',
                    dataIndex: 'row_count',
                    render: (v: number) => v.toLocaleString(),
                    width: 110,
                  },
                ] as Column<any>[]}
              />
            </div>
          </>
        )}
      </Modal>

      <Confirm
        open={rollbackId !== null}
        onClose={() => setRollbackId(null)}
        onConfirm={handleRollback}
        title="Rollback du batch"
        description={`Restaurer les concept_id précédents pour le batch ${rollbackId?.slice(0, 8)} ? Cette action restaure les valeurs originales dans la table clinique.`}
        confirmText={rollbackLoading ? 'Rollback...' : 'Rollback'}
        danger
      />
    </div>
  );
}
