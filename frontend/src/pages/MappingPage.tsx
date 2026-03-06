import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Tabs, Table, Tag, Button, Select, Input, Space, Typography,
  Statistic, Row, Col, Empty, Spin, message, Popconfirm, Tooltip,
  Progress, Modal, InputNumber, Pagination, Checkbox,
} from 'antd';
import {
  BarChartOutlined, SearchOutlined, BulbOutlined, HistoryOutlined,
  DownloadOutlined, CheckOutlined, CloseOutlined, EditOutlined,
  UndoOutlined, ThunderboltOutlined, ExportOutlined, WarningOutlined,
  StopOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, LineChart, Line, Legend, Cell,
} from 'recharts';
import { mappingApi, authDownload } from '../api/client';
import type {
  MappingDomainStat, MappingEvolutionPoint, UnmappedItem,
  SuggestionResult, MappingSuggestion, MappingDecisionEntry,
} from '../types';

const { Text, Title } = Typography;
const { Option } = Select;
const { TabPane } = Tabs;

const DOMAIN_LIST = ['Condition', 'Drug', 'Measurement', 'Observation', 'Procedure', 'Visit', 'Device', 'Death'];

interface Props {
  selectedCdm: string | null;
}

export default function MappingPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('dashboard');
  const [historyKey, setHistoryKey] = useState(0);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === 'history') setHistoryKey(k => k + 1);
  };

  if (!selectedCdm) {
    return <Empty description={t('mapping.select_cdm', 'Select a CDM connection to explore mappings')} />;
  }

  return (
    <Tabs activeKey={activeTab} onChange={handleTabChange} type="card">
      <TabPane tab={<span><BarChartOutlined /> {t('mapping.dashboard', 'Dashboard')}</span>} key="dashboard">
        <MappingDashboardTab cdmName={selectedCdm} />
      </TabPane>
      <TabPane tab={<span><SearchOutlined /> {t('mapping.explore', 'Unmapped')}</span>} key="explore">
        <UnmappedExplorerTab cdmName={selectedCdm} />
      </TabPane>
      <TabPane tab={<span><BulbOutlined /> {t('mapping.suggestions', 'Suggestions')}</span>} key="suggestions">
        <SuggestionWorkflowTab cdmName={selectedCdm} />
      </TabPane>
      <TabPane tab={<span><HistoryOutlined /> {t('mapping.history', 'History')}</span>} key="history">
        <MappingHistoryTab cdmName={selectedCdm} refreshKey={historyKey} />
      </TabPane>
    </Tabs>
  );
}

// ============ TAB 1: MAPPING DASHBOARD ============

function MappingDashboardTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<MappingDomainStat[]>([]);
  const [decisions, setDecisions] = useState<Record<string, number>>({});
  const [evolution, setEvolution] = useState<MappingEvolutionPoint[]>([]);
  const [evoDomain, setEvoDomain] = useState('Condition');
  const [loading, setLoading] = useState(true);

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

  if (loading) return <Spin />;

  const totalTerms = data.reduce((s, d) => s + d.total_terms, 0);
  const mappedTerms = data.reduce((s, d) => s + d.mapped_terms, 0);
  const pctOverall = totalTerms > 0 ? (mappedTerms / totalTerms * 100) : 0;

  return (
    <div>
      {/* Summary */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title={t('mapping.overall_rate', 'Overall Mapping Rate')} value={pctOverall.toFixed(1)} suffix="%" /></Card></Col>
        <Col span={6}><Card><Statistic title={t('mapping.total_terms', 'Total Terms')} value={totalTerms.toLocaleString()} /></Card></Col>
        <Col span={6}><Card><Statistic title={t('mapping.mapped', 'Mapped')} value={mappedTerms.toLocaleString()} valueStyle={{ color: '#2bc459' }} /></Card></Col>
        <Col span={6}><Card><Statistic title={t('mapping.decisions_made', 'Decisions Made')} value={Object.values(decisions).reduce((a, b) => a + b, 0)} /></Card></Col>
      </Row>

      {/* Bar chart */}
      <Card title={t('mapping.rates_by_domain', 'Mapping Rates by Domain')} style={{ marginBottom: 16 }}>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="domain" />
            <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
            <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
            <Legend />
            <Bar dataKey="pct_terms_mapped" name={t('mapping.terms_pct', '% Terms Mapped')} fill="#1f77b4" />
            <Bar dataKey="pct_rows_mapped" name={t('mapping.rows_pct', '% Rows Mapped')} fill="#2bc459" />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Unmapped volume (weighted by records) */}
      <Card title={t('mapping.unmapped_volume', 'Unmapped Volume (by records)')} style={{ marginBottom: 16 }}>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="domain" />
            <YAxis />
            <RechartsTooltip formatter={(v: number) => v.toLocaleString()} />
            <Bar dataKey="unmapped_rows" name={t('mapping.unmapped_rows', 'Unmapped Rows')} fill="#ff4d4f" />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Evolution */}
      <Card
        title={t('mapping.evolution', 'Mapping Evolution')}
        extra={
          <Select size="small" value={evoDomain} onChange={setEvoDomain} style={{ width: 150 }}>
            {DOMAIN_LIST.map(d => <Option key={d} value={d}>{d}</Option>)}
          </Select>
        }
      >
        {evolution.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={evolution}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="version" label={{ value: 'Version', position: 'insideBottom', offset: -5 }} />
              <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
              <RechartsTooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
              <Legend />
              <Line type="monotone" dataKey="pct_terms_mapped" name="% Terms" stroke="#1f77b4" strokeWidth={2} />
              <Line type="monotone" dataKey="pct_rows_mapped" name="% Rows" stroke="#2bc459" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <Text type="secondary">{t('mapping.no_evolution', 'Run multiple analyses to see evolution')}</Text>
        )}
      </Card>
    </div>
  );
}

// ============ TAB 2: UNMAPPED EXPLORER ============

function UnmappedExplorerTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [domain, setDomain] = useState('Condition');
  const [items, setItems] = useState<UnmappedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    mappingApi.unmapped(cdmName, domain, page, 50, search)
      .then(r => { setItems(r.data.items); setTotal(r.data.total); })
      .catch(() => { setItems([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [cdmName, domain, page, search]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: t('mapping.source_value', 'Source Value'), dataIndex: 'source_value', key: 'sv', ellipsis: true },
    { title: t('mapping.source_name', 'Source Name'), dataIndex: 'source_name', key: 'sn', ellipsis: true,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: t('mapping.n_records', 'Records'), dataIndex: 'n_records', key: 'nr',
      render: (v: number) => v.toLocaleString(), sorter: (a: UnmappedItem, b: UnmappedItem) => a.n_records - b.n_records },
    { title: t('mapping.n_persons', 'Persons'), dataIndex: 'n_persons', key: 'np',
      render: (v: number) => v.toLocaleString() },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }} bodyStyle={{ padding: '8px 16px' }}>
        <Space>
          <Select value={domain} onChange={v => { setDomain(v); setPage(1); }} style={{ width: 150 }}>
            {DOMAIN_LIST.map(d => <Option key={d} value={d}>{d}</Option>)}
          </Select>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('mapping.search_unmapped', 'Filter...')}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            allowClear
            style={{ width: 250 }}
            size="small"
          />
          <Button
            icon={<DownloadOutlined />}
            onClick={() => authDownload(mappingApi.exportUnmappedUrl(cdmName, domain))}
            size="small"
          >
            CSV
          </Button>
          <Text type="secondary">{total.toLocaleString()} {t('mapping.terms', 'terms')}</Text>
        </Space>
      </Card>
      <Table
        dataSource={items}
        columns={columns}
        rowKey="source_value"
        loading={loading}
        pagination={false}
        size="small"
      />
      <div style={{ textAlign: 'right', marginTop: 8 }}>
        <Pagination
          current={page}
          total={total}
          pageSize={50}
          onChange={setPage}
          showSizeChanger={false}
          size="small"
        />
      </div>
    </div>
  );
}

// ============ TAB 3: SUGGESTION WORKFLOW ============

function SuggestionWorkflowTab({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [domain, setDomain] = useState('Condition');
  const [results, setResults] = useState<SuggestionResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [limit, setLimit] = useState(20);
  const [enableFuzzy, setEnableFuzzy] = useState(true);
  const [enableKeyword, setEnableKeyword] = useState(true);
  const [enableContextual, setEnableContextual] = useState(true);
  const [enableSapbert, setEnableSapbert] = useState(true);

  const abortRef = useRef<AbortController | null>(null);

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
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    mappingApi.suggestBatch(cdmName, domain, limit, {
      enable_fuzzy: enableFuzzy,
      enable_keyword: enableKeyword,
      enable_contextual: enableContextual,
      enable_sapbert: enableSapbert,
    })
      .then(r => { if (!ctrl.signal.aborted) setResults(r.data.results); })
      .catch(e => { if (!ctrl.signal.aborted) message.error(e.response?.data?.detail || 'Suggestion failed'); })
      .finally(() => { setLoading(false); abortRef.current = null; });
  };

  const cancelBatch = () => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setLoading(false);
    message.info('Cancelled');
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
      message.success(`${action}: ${sv}`);
      setResults(prev => prev.filter(r => r.source_value !== sv));
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Decision failed');
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
    message.success(`Approved ${count} mappings`);
    setResults(prev => prev.filter(r =>
      !(r.suggestions.length > 0 && r.suggestions[0].confidence >= minConfidence)
    ));
  };

  const confidenceColor = (c: number) => c >= 80 ? 'green' : c >= 50 ? 'orange' : 'red';
  const sourceLabel = (s: string) => {
    const labels: Record<string, string> = { exact: 'Exact', relationship: 'Maps to', fuzzy: 'Fuzzy', contextual: 'Context', ingredient: 'Ingredient', synonym: 'Synonym', sapbert: 'SapBERT' };
    return labels[s] || s;
  };

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }} bodyStyle={{ padding: '8px 16px' }}>
        <Space>
          <Select value={domain} onChange={setDomain} style={{ width: 150 }}>
            {DOMAIN_LIST.map(d => <Option key={d} value={d}>{d}</Option>)}
          </Select>
          <InputNumber size="small" min={5} max={100} value={limit} onChange={v => setLimit(v || 20)} style={{ width: 70 }} />
          <span style={{ borderLeft: '1px solid #d9d9d9', paddingLeft: 8, marginLeft: 4 }}>
            <Checkbox checked={enableFuzzy} onChange={e => setEnableFuzzy(e.target.checked)} style={{ fontSize: 12 }}>Fuzzy</Checkbox>
            <Checkbox checked={enableKeyword} onChange={e => setEnableKeyword(e.target.checked)} style={{ fontSize: 12 }}>{t('mapping.keyword', 'Keyword')}</Checkbox>
            <Checkbox checked={enableContextual} onChange={e => setEnableContextual(e.target.checked)} style={{ fontSize: 12 }}>{t('mapping.contextual', 'Contextual')}</Checkbox>
            {domain === 'Procedure' && (
              <Checkbox checked={enableSapbert} onChange={e => setEnableSapbert(e.target.checked)} style={{ fontSize: 12 }}>SapBERT</Checkbox>
            )}
          </span>
          {loading ? (
            <Button danger icon={<StopOutlined />} onClick={cancelBatch} size="small">
              {t('common.cancel')}
            </Button>
          ) : (
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={runBatch} size="small">
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
          <Text type="secondary">{results.length} {t('mapping.pending', 'pending')}</Text>
        </Space>
      </Card>

      {loading ? <Spin /> : results.length === 0 ? (
        <Empty description={t('mapping.no_suggestions', 'Click Generate to get mapping suggestions')} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {results.map(r => (
            <Card key={r.source_value} size="small" bodyStyle={{ padding: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <Text strong>{r.source_value}</Text>
                  {r.source_name && <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{r.source_name}</Text>}
                  <div style={{ marginTop: 4 }}>
                    {r.suggestions.length === 0 ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>{t('mapping.no_match', 'No suggestions found')}</Text>
                    ) : (
                      r.suggestions.map((s, i) => (
                        <div key={s.concept_id} style={{
                          padding: '4px 8px',
                          background: i === 0 ? '#f6ffed' : '#fafafa',
                          borderRadius: 4,
                          marginTop: 2,
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <Space size={4}>
                            <Tag color={confidenceColor(s.confidence)} style={{ fontSize: 10 }}>{s.confidence}%</Tag>
                            <Tag style={{ fontSize: 10 }}>{sourceLabel(s.source)}</Tag>
                            <Text style={{ fontSize: 12, color: '#222' }}>{s.concept_name}</Text>
                            <Text style={{ fontSize: 10, color: '#666' }}>{s.concept_id} · {s.concept_code} · {s.vocabulary_id}</Text>
                          </Space>
                          <Space size={2}>
                            <Tooltip title={t('mapping.approve', 'Approve')}>
                              <Button size="small" type="link" style={{ color: '#2bc459' }}
                                onClick={() => promptDecision(r.source_value, r.source_name, 'approved', s)}>
                                <CheckOutlined />
                              </Button>
                            </Tooltip>
                            {i !== 0 && (
                              <Tooltip title={t('mapping.approve_this', 'Approve this instead')}>
                                <Button size="small" type="link"
                                  onClick={() => promptDecision(r.source_value, r.source_name, 'modified', s)}>
                                  <EditOutlined />
                                </Button>
                              </Tooltip>
                            )}
                          </Space>
                        </div>
                      ))
                    )}
                  </div>
                </div>
                <Space direction="vertical" size={2} style={{ marginLeft: 8 }}>
                  <Tooltip title={t('mapping.reject', 'Reject')}>
                    <Button size="small" danger onClick={() => promptDecision(r.source_value, r.source_name, 'rejected')}>
                      <CloseOutlined />
                    </Button>
                  </Tooltip>
                </Space>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={reasonModal.open}
        title={reasonModal.action === 'rejected' ? t('mapping.reject_reason', 'Reject — Reason') : t('mapping.approve_reason', 'Approve — Reason')}
        okText={reasonModal.action === 'rejected' ? t('mapping.reject', 'Reject') : t('mapping.approve', 'Approve')}
        okButtonProps={{ danger: reasonModal.action === 'rejected' }}
        cancelText={t('common.cancel', 'Cancel')}
        onOk={submitDecision}
        onCancel={() => setReasonModal({ open: false, sv: '', sn: '', action: '' })}
        destroyOnClose
      >
        <p style={{ marginBottom: 8 }}>
          <Tag>{reasonModal.sv}</Tag> {reasonModal.sn && <Text type="secondary">{reasonModal.sn}</Text>}
        </p>
        <Input.TextArea
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

// ============ TAB 4: MAPPING HISTORY ============

function MappingHistoryTab({ cdmName, refreshKey }: { cdmName: string; refreshKey?: number }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<MappingDecisionEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterDomain, setFilterDomain] = useState<string>('');
  const [filterAction, setFilterAction] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [applyDomain, setApplyDomain] = useState('Condition');
  const [applyPreview, setApplyPreview] = useState<{ total_decisions: number; impacted_rows: number; impacted_persons: number } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    mappingApi.history(cdmName, filterDomain || undefined, filterAction || undefined, page)
      .then(r => { setItems(r.data.items); setTotal(r.data.total); })
      .catch(() => { setItems([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [cdmName, filterDomain, filterAction, page]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const handleRollback = async (id: number) => {
    try {
      await mappingApi.rollback(id);
      message.success('Rolled back');
      load();
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Rollback failed');
    }
  };

  const handleApplyPreview = async () => {
    try {
      const r = await mappingApi.applyPreview(cdmName, applyDomain);
      setApplyPreview(r.data);
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Preview failed');
    }
  };

  const [writeConfirmOpen, setWriteConfirmOpen] = useState(false);
  const [writeConfirmText, setWriteConfirmText] = useState('');
  const [applyLoading, setApplyLoading] = useState(false);

  const handleApply = async (writeToCdm: boolean) => {
    setApplyLoading(true);
    try {
      const r = await mappingApi.apply(cdmName, applyDomain, writeToCdm);
      message.success(`Applied ${r.data.count} mappings${writeToCdm ? ' to CDM' : ''}`);
      setApplyPreview(null);
      setWriteConfirmOpen(false);
      setWriteConfirmText('');
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Apply failed');
    } finally {
      setApplyLoading(false);
    }
  };

  const actionColor = (a: string) => {
    const colors: Record<string, string> = { approved: 'green', modified: 'blue', rejected: 'red', rolled_back: 'orange' };
    return colors[a] || 'default';
  };

  const columns = [
    { title: t('mapping.domain', 'Domain'), dataIndex: 'domain', key: 'd', width: 100 },
    { title: t('mapping.source_value', 'Source'), dataIndex: 'source_value', key: 'sv', ellipsis: true },
    { title: t('mapping.action', 'Action'), dataIndex: 'action', key: 'a', width: 100,
      render: (a: string) => <Tag color={actionColor(a)}>{a}</Tag> },
    { title: t('mapping.target', 'Target'), key: 'target', width: 200,
      render: (_: any, r: MappingDecisionEntry) => r.target_concept_id
        ? <span>{r.target_concept_name} <Text type="secondary" style={{ fontSize: 10 }}>({r.target_concept_id})</Text></span>
        : <Text type="secondary">—</Text> },
    { title: t('mapping.confidence', 'Confidence'), dataIndex: 'confidence_score', key: 'c', width: 80,
      render: (v: number | null) => v != null ? <Tag>{v}%</Tag> : '—' },
    { title: t('mapping.reason', 'Reason'), dataIndex: 'reason', key: 'reason', width: 150, ellipsis: true,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: t('mapping.date', 'Date'), dataIndex: 'created_at', key: 'date', width: 120,
      render: (v: string) => v?.substring(0, 16).replace('T', ' ') },
    { title: '', key: 'actions', width: 50,
      render: (_: any, r: MappingDecisionEntry) => r.action !== 'rolled_back' ? (
        <Popconfirm title="Rollback?" onConfirm={() => handleRollback(r.id)}>
          <Button size="small" type="link"><UndoOutlined /></Button>
        </Popconfirm>
      ) : null },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }} bodyStyle={{ padding: '8px 16px' }}>
        <Space wrap>
          <Select value={filterDomain} onChange={v => { setFilterDomain(v); setPage(1); }} style={{ width: 130 }} allowClear placeholder="All domains">
            {DOMAIN_LIST.map(d => <Option key={d} value={d}>{d}</Option>)}
          </Select>
          <Select value={filterAction} onChange={v => { setFilterAction(v); setPage(1); }} style={{ width: 120 }} allowClear placeholder="All actions">
            <Option value="approved">Approved</Option>
            <Option value="modified">Modified</Option>
            <Option value="rejected">Rejected</Option>
            <Option value="rolled_back">Rolled back</Option>
          </Select>
          <Button icon={<DownloadOutlined />} onClick={() => authDownload(mappingApi.exportHistoryUrl(cdmName, filterDomain || undefined))} size="small">
            {t('mapping.export_history', 'Export')}
          </Button>
          <Button icon={<ReloadOutlined />} size="small" onClick={load} loading={loading} />
          <Text type="secondary">{total} {t('mapping.decisions', 'decisions')}</Text>

          <span style={{ borderLeft: '1px solid #ddd', paddingLeft: 8 }}>
            <Text style={{ fontSize: 12, marginRight: 4 }}>{t('mapping.apply_to', 'Apply to')}:</Text>
            <Select size="small" value={applyDomain} onChange={setApplyDomain} style={{ width: 120 }}>
              {DOMAIN_LIST.map(d => <Option key={d} value={d}>{d}</Option>)}
            </Select>
            <Button size="small" style={{ marginLeft: 4 }} onClick={handleApplyPreview}>Preview</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => authDownload(mappingApi.exportStcmUrl(cdmName, applyDomain))} style={{ marginLeft: 4 }}>
              STCM CSV
            </Button>
          </span>
        </Space>
      </Card>

      {applyPreview && (
        <Card size="small" style={{ marginBottom: 12, borderColor: '#ff4d4f', borderWidth: 2 }}>
          <div style={{ background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 4, padding: '8px 12px', marginBottom: 12 }}>
            <Space>
              <WarningOutlined style={{ color: '#ff4d4f', fontSize: 18 }} />
              <Text strong style={{ color: '#ff4d4f' }}>
                {t('mapping.write_warning', 'Cette action va modifier directement la table source_to_concept_map du CDM. Cette opération est difficilement réversible.')}
              </Text>
            </Space>
          </div>
          <Row gutter={16}>
            <Col span={8}><Statistic title={t('mapping.approved_decisions', 'Approved Decisions')} value={applyPreview.total_decisions} /></Col>
            <Col span={8}><Statistic title={t('mapping.impacted_rows', 'Impacted Rows')} value={applyPreview.impacted_rows.toLocaleString()} valueStyle={{ color: '#ff4d4f' }} /></Col>
            <Col span={8}><Statistic title={t('mapping.impacted_persons', 'Impacted Persons')} value={applyPreview.impacted_persons.toLocaleString()} valueStyle={{ color: '#ff4d4f' }} /></Col>
          </Row>
          <Space style={{ marginTop: 12 }}>
            <Button type="primary" danger size="small" onClick={() => setWriteConfirmOpen(true)}>
              <WarningOutlined /> {t('mapping.write_to_cdm', 'Write to CDM')}
            </Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => authDownload(mappingApi.exportStcmUrl(cdmName, applyDomain))}>
              {t('mapping.export_stcm_instead', 'Exporter en CSV (recommandé)')}
            </Button>
            <Button size="small" onClick={() => { setApplyPreview(null); setWriteConfirmOpen(false); setWriteConfirmText(''); }}>
              {t('common.close', 'Close')}
            </Button>
          </Space>

          <Modal
            title={<Space><WarningOutlined style={{ color: '#ff4d4f' }} /><Text strong style={{ color: '#ff4d4f' }}>Confirmation requise</Text></Space>}
            open={writeConfirmOpen}
            onCancel={() => { setWriteConfirmOpen(false); setWriteConfirmText(''); }}
            footer={[
              <Button key="cancel" onClick={() => { setWriteConfirmOpen(false); setWriteConfirmText(''); }}>
                Annuler
              </Button>,
              <Button
                key="confirm"
                type="primary"
                danger
                loading={applyLoading}
                disabled={writeConfirmText !== cdmName}
                onClick={() => handleApply(true)}
              >
                Confirmer l'écriture
              </Button>,
            ]}
          >
            <div style={{ marginBottom: 16 }}>
              <Text>Vous allez écrire <Text strong>{applyPreview.total_decisions} mappings</Text> dans la table <Text code>source_to_concept_map</Text> du CDM <Text strong style={{ color: '#ff4d4f' }}>{cdmName}</Text>.</Text>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Text>Cela impactera <Text strong style={{ color: '#ff4d4f' }}>{applyPreview.impacted_rows.toLocaleString()} lignes</Text> et <Text strong style={{ color: '#ff4d4f' }}>{applyPreview.impacted_persons.toLocaleString()} patients</Text>.</Text>
            </div>
            <div style={{ background: '#fff7e6', border: '1px solid #ffd591', borderRadius: 4, padding: 8, marginBottom: 16 }}>
              <Text type="warning" style={{ fontSize: 12 }}>Pour confirmer, tapez le nom exact du CDM ci-dessous :</Text>
            </div>
            <Input
              placeholder={cdmName}
              value={writeConfirmText}
              onChange={e => setWriteConfirmText(e.target.value)}
              status={writeConfirmText && writeConfirmText !== cdmName ? 'error' : undefined}
            />
          </Modal>
        </Card>
      )}

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
      />
      <div style={{ textAlign: 'right', marginTop: 8 }}>
        <Pagination current={page} total={total} pageSize={50} onChange={setPage} showSizeChanger={false} size="small" />
      </div>
    </div>
  );
}
