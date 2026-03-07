import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Select, Button, Space, Checkbox, Spin, Alert, Typography,
  Switch, Row, Col, message, Progress, List, Tag,
} from 'antd';
import {
  PlayCircleOutlined, ThunderboltOutlined, SwapOutlined, HistoryOutlined,
  DownloadOutlined, LineChartOutlined, CheckCircleOutlined, StopOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { qualityApi, authDownload } from '../api/client';
import AnalysisResults from '../components/quality/AnalysisResults';
import ComparisonView from '../components/quality/ComparisonView';
import SnapshotTimeline from '../components/quality/SnapshotTimeline';
import type { SnapshotMeta, BatchProgressEvent } from '../types';

const { Title, Text } = Typography;

interface Props {
  selectedCdm: string | null;
}

export default function QualityPage({ selectedCdm }: Props) {
  const { t, i18n } = useTranslation();
  const [domains, setDomains] = useState<string[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [results, setResults] = useState<any>(null);
  const [snapshotId, setSnapshotId] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchProgress, setBatchProgress] = useState(0);
  const [batchStatus, setBatchStatus] = useState<{ domain: string; status: string }[]>([]);
  const [selectedBatch, setSelectedBatch] = useState<string[]>([]);
  const [compareMode, setCompareMode] = useState(false);
  const [compareCdm, setCompareCdm] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotMeta[]>([]);
  const [showTimeline, setShowTimeline] = useState(false);
  const [analyzedDomains, setAnalyzedDomains] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    qualityApi.domains().then((res) => setDomains(res.data.domains));
  }, []);

  // Fetch which domains already have snapshots
  useEffect(() => {
    if (!selectedCdm) {
      setAnalyzedDomains(new Set());
      return;
    }
    qualityApi.timeline(selectedCdm).then((res) => {
      setAnalyzedDomains(new Set(Object.keys(res.data.timelines)));
    }).catch(() => setAnalyzedDomains(new Set()));
  }, [selectedCdm]);

  useEffect(() => {
    if (selectedCdm && selectedDomain) {
      loadLatestSnapshot();
      loadSnapshots();
    } else {
      setResults(null);
      setSnapshotId(undefined);
      setSnapshots([]);
    }
  }, [selectedCdm, selectedDomain]);

  const loadLatestSnapshot = async () => {
    if (!selectedCdm || !selectedDomain) return;
    try {
      const res = await qualityApi.getLatestSnapshot(selectedCdm, selectedDomain);
      setResults(res.data.results);
      setSnapshotId(res.data.id);
    } catch {
      setResults(null);
      setSnapshotId(undefined);
    }
  };

  const loadSnapshots = async () => {
    if (!selectedCdm || !selectedDomain) return;
    try {
      const res = await qualityApi.listSnapshots(selectedCdm, selectedDomain);
      setSnapshots(res.data.snapshots);
    } catch {
      setSnapshots([]);
    }
  };

  const loadSnapshotById = async (id: number) => {
    try {
      const res = await qualityApi.getSnapshotById(id);
      setResults(res.data.results);
      setSnapshotId(res.data.id);
    } catch {
      message.error(t('common.error'));
    }
  };

  const cancelOperation = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setLoading(false);
    setBatchLoading(false);
    message.info(t('common.cancelled', 'Cancelled'));
  };

  const runAnalysis = async () => {
    if (!selectedCdm || !selectedDomain) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      const res = await qualityApi.analyze(selectedCdm, selectedDomain);
      if (ctrl.signal.aborted) return;
      setResults(res.data.results);
      setSnapshotId(res.data.snapshot_id);
      setAnalyzedDomains(prev => new Set([...prev, selectedDomain]));
      await loadSnapshots();
      message.success(t('common.success'));
    } catch (err: any) {
      if (ctrl.signal.aborted) return;
      message.error(err?.response?.data?.detail || t('common.error'));
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  const runBatchAnalysis = useCallback(async () => {
    if (!selectedCdm || selectedBatch.length === 0) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBatchLoading(true);
    setBatchProgress(0);
    setBatchStatus([]);

    try {
      const response = await qualityApi.analyzeBatchStream(selectedCdm, selectedBatch);
      const reader = response.body?.getReader();
      if (!reader) {
        // Fallback to regular batch
        const res = await qualityApi.analyzeBatch(selectedCdm, selectedBatch);
        setBatchProgress(100);
        message.success(`${res.data.success_count}/${res.data.total} ${t('common.success')}`);
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        if (ctrl.signal.aborted) { reader.cancel(); break; }
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event: BatchProgressEvent = JSON.parse(line.slice(6));
              if (event.type === 'progress') {
                const pct = Math.round((event.completed / event.total) * 100);
                setBatchProgress(pct);
                if (event.domain && event.status && event.status !== 'running') {
                  setBatchStatus(prev => [...prev, { domain: event.domain!, status: event.status! }]);
                  if (event.status === 'success') {
                    setAnalyzedDomains(prev => new Set([...prev, event.domain!]));
                  }
                }
              } else if (event.type === 'done') {
                setBatchProgress(100);
                message.success(`${event.completed}/${event.total} ${t('common.success')}`);
              } else if (event.type === 'error') {
                message.error(event.message || t('common.error'));
              }
            } catch {}
          }
        }
      }

      if (selectedDomain) {
        await loadLatestSnapshot();
        await loadSnapshots();
      }
    } catch (err: any) {
      message.error(t('common.error'));
    } finally {
      setBatchLoading(false);
      abortRef.current = null;
    }
  }, [selectedCdm, selectedBatch, selectedDomain]);

  const toggleSelectAll = (checked: boolean) => {
    setSelectedBatch(checked ? domains.filter((d) => d !== 'Dashboard') : []);
  };

  if (!selectedCdm) {
    return (
      <div>
        <Title level={3}>{t('quality.title')}</Title>
        <Alert message={t('cdm.select_cdm')} type="info" showIcon />
      </div>
    );
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={3} style={{ margin: 0 }}>
            {t('quality.title')} — {selectedCdm}
          </Title>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<LineChartOutlined />}
              onClick={() => setShowTimeline(!showTimeline)}
              type={showTimeline ? 'primary' : 'default'}
            >
              {t('quality.timeline_title')}
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => authDownload(
                compareMode && compareCdm
                  ? qualityApi.comparisonReportUrl(selectedCdm, compareCdm, i18n.language, selectedDomain || undefined)
                  : qualityApi.reportUrl(selectedCdm, i18n.language)
              )}
            >
              HTML
            </Button>
            <SwapOutlined />
            <Switch
              checked={compareMode}
              onChange={setCompareMode}
              checkedChildren={t('quality.comparison_mode')}
              unCheckedChildren={t('quality.comparison_mode')}
            />
          </Space>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* Left panel */}
        <Col span={6}>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text strong>{t('quality.select_domain')}</Text>
              <Select
                placeholder={t('quality.select_domain')}
                value={selectedDomain}
                onChange={setSelectedDomain}
                style={{ width: '100%' }}
                options={domains.map((d) => ({
                  value: d,
                  label: <span>{t(`domains.${d}`, d)} {analyzedDomains.has(d) && <CheckCircleOutlined style={{ color: '#2bc459', marginLeft: 4 }} />}</span>,
                }))}
                allowClear
              />
              {loading ? (
                <Button danger icon={<StopOutlined />} onClick={cancelOperation} block>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={runAnalysis}
                  disabled={!selectedDomain}
                  block
                >
                  {t('quality.run_analysis')}
                </Button>
              )}
            </Space>
          </Card>

          {/* Batch analysis */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text strong>{t('quality.run_batch')}</Text>
              <Checkbox
                onChange={(e) => toggleSelectAll(e.target.checked)}
                checked={selectedBatch.length === domains.filter((d) => d !== 'Dashboard').length}
              >
                {t('quality.select_all')}
              </Checkbox>
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {domains.filter((d) => d !== 'Dashboard').map((d) => (
                  <div key={d}>
                    <Checkbox
                      checked={selectedBatch.includes(d)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedBatch([...selectedBatch, d]);
                        } else {
                          setSelectedBatch(selectedBatch.filter((x) => x !== d));
                        }
                      }}
                    >
                      {t(`domains.${d}`, d)}
                      {analyzedDomains.has(d) && !batchStatus.find(s => s.domain === d) && (
                        <CheckCircleOutlined style={{ color: '#2bc459', marginLeft: 4 }} />
                      )}
                      {batchStatus.find(s => s.domain === d) && (
                        <Tag
                          color={batchStatus.find(s => s.domain === d)?.status === 'success' ? 'green' : 'red'}
                          style={{ marginLeft: 4 }}
                        >
                          {batchStatus.find(s => s.domain === d)?.status}
                        </Tag>
                      )}
                    </Checkbox>
                  </div>
                ))}
              </div>
              {batchLoading && <Progress percent={batchProgress} size="small" status="active" />}
              {batchLoading ? (
                <Button danger icon={<StopOutlined />} onClick={cancelOperation} block>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button
                  icon={<ThunderboltOutlined />}
                  onClick={runBatchAnalysis}
                  disabled={selectedBatch.length === 0}
                  block
                >
                  {t('quality.run_batch')}
                </Button>
              )}
            </Space>
          </Card>

          {/* Snapshot history */}
          {snapshots.length > 0 && (
            <Card
              size="small"
              title={<Space><HistoryOutlined />{t('quality.snapshot_history')}</Space>}
            >
              <List
                size="small"
                dataSource={snapshots}
                renderItem={(s) => (
                  <List.Item
                    style={{ cursor: 'pointer', padding: '4px 0' }}
                    onClick={() => loadSnapshotById(s.id)}
                  >
                    <Text style={{ fontWeight: s.id === snapshotId ? 'bold' : 'normal' }}>
                      v{s.version} — {s.created_at ? new Date(s.created_at).toLocaleString() : ''}
                    </Text>
                  </List.Item>
                )}
              />
            </Card>
          )}
        </Col>

        {/* Main content */}
        <Col span={18}>
          {showTimeline && (
            <div style={{ marginBottom: 16 }}>
              <SnapshotTimeline selectedCdm={selectedCdm} />
            </div>
          )}

          {loading && (
            <div style={{ textAlign: 'center', padding: 60 }}>
              <Spin size="large" />
              <div style={{ marginTop: 16 }}>
                <Text type="secondary">{t('quality.loading')}</Text>
              </div>
            </div>
          )}

          {!loading && !compareMode && results && (
            <AnalysisResults results={results} snapshotId={snapshotId} />
          )}

          {!loading && compareMode && selectedDomain && (
            <ComparisonView
              cdmNameA={selectedCdm}
              cdmNameB={compareCdm}
              domain={selectedDomain}
              onCdmBChange={setCompareCdm}
            />
          )}

          {!loading && !results && !compareMode && (
            <Card>
              <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
                <DashboardIcon />
                <div style={{ marginTop: 16 }}>
                  <Text type="secondary">{t('quality.run_first')}</Text>
                </div>
              </div>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}

function DashboardIcon() {
  return (
    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#ccc" strokeWidth="1.5">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}
