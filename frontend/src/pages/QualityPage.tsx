import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Play, Zap, ArrowLeftRight, History, Download, LineChart,
  CheckCircle, StopCircle, LayoutDashboard,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { qualityApi, authDownload } from '../api/client';
import { Card, Button, Select, Switch, Checkbox, Tag, Progress, Spinner, Alert, useToast } from '../components/ui';
import AnalysisResults from '../components/quality/AnalysisResults';
import ComparisonView from '../components/quality/ComparisonView';
import SnapshotTimeline from '../components/quality/SnapshotTimeline';
import type { SnapshotMeta, BatchProgressEvent } from '../types';

interface Props {
  selectedCdm: string | null;
}

export default function QualityPage({ selectedCdm }: Props) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
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

  useEffect(() => {
    if (!selectedCdm) { setAnalyzedDomains(new Set()); return; }
    qualityApi.timeline(selectedCdm).then((res) => {
      setAnalyzedDomains(new Set(Object.keys(res.data.timelines)));
    }).catch(() => setAnalyzedDomains(new Set()));
  }, [selectedCdm]);

  useEffect(() => {
    if (selectedCdm && selectedDomain) {
      loadLatestSnapshot();
      loadSnapshots();
    } else {
      setResults(null); setSnapshotId(undefined); setSnapshots([]);
    }
  }, [selectedCdm, selectedDomain]);

  const loadLatestSnapshot = async () => {
    if (!selectedCdm || !selectedDomain) return;
    try {
      const res = await qualityApi.getLatestSnapshot(selectedCdm, selectedDomain);
      setResults(res.data.results); setSnapshotId(res.data.id);
    } catch { setResults(null); setSnapshotId(undefined); }
  };

  const loadSnapshots = async () => {
    if (!selectedCdm || !selectedDomain) return;
    try {
      const res = await qualityApi.listSnapshots(selectedCdm, selectedDomain);
      setSnapshots(res.data.snapshots);
    } catch { setSnapshots([]); }
  };

  const loadSnapshotById = async (id: number) => {
    try {
      const res = await qualityApi.getSnapshotById(id);
      setResults(res.data.results); setSnapshotId(res.data.id);
    } catch { toast.error(t('common.error')); }
  };

  const cancelOperation = () => {
    abortRef.current?.abort(); abortRef.current = null;
    setLoading(false); setBatchLoading(false);
    toast.info(t('common.cancelled', 'Cancelled'));
  };

  const runAnalysis = async () => {
    if (!selectedCdm || !selectedDomain) return;
    const ctrl = new AbortController(); abortRef.current = ctrl;
    setLoading(true);
    try {
      const res = await qualityApi.analyze(selectedCdm, selectedDomain);
      if (ctrl.signal.aborted) return;
      setResults(res.data.results); setSnapshotId(res.data.snapshot_id);
      setAnalyzedDomains(prev => new Set([...prev, selectedDomain]));
      await loadSnapshots();
      toast.success(t('common.success'));
    } catch (err: any) {
      if (ctrl.signal.aborted) return;
      toast.error(err?.response?.data?.detail || t('common.error'));
    } finally { setLoading(false); abortRef.current = null; }
  };

  const runBatchAnalysis = useCallback(async () => {
    if (!selectedCdm || selectedBatch.length === 0) return;
    const ctrl = new AbortController(); abortRef.current = ctrl;
    setBatchLoading(true); setBatchProgress(0); setBatchStatus([]);

    try {
      const response = await qualityApi.analyzeBatchStream(selectedCdm, selectedBatch);
      const reader = response.body?.getReader();
      if (!reader) {
        const res = await qualityApi.analyzeBatch(selectedCdm, selectedBatch);
        setBatchProgress(100);
        toast.success(`${res.data.success_count}/${res.data.total} ${t('common.success')}`);
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        if (ctrl.signal.aborted) { reader.cancel(); break; }
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n'); buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event: BatchProgressEvent = JSON.parse(line.slice(6));
              if (event.type === 'progress') {
                setBatchProgress(Math.round((event.completed / event.total) * 100));
                if (event.domain && event.status && event.status !== 'running') {
                  setBatchStatus(prev => [...prev, { domain: event.domain!, status: event.status! }]);
                  if (event.status === 'success') setAnalyzedDomains(prev => new Set([...prev, event.domain!]));
                }
              } else if (event.type === 'done') {
                setBatchProgress(100);
                toast.success(`${event.completed}/${event.total} ${t('common.success')}`);
              } else if (event.type === 'error') {
                toast.error(event.message || t('common.error'));
              }
            } catch {}
          }
        }
      }
      if (selectedDomain) { await loadLatestSnapshot(); await loadSnapshots(); }
    } catch { toast.error(t('common.error')); }
    finally { setBatchLoading(false); abortRef.current = null; }
  }, [selectedCdm, selectedBatch, selectedDomain]);

  const toggleSelectAll = (checked: boolean) => {
    setSelectedBatch(checked ? domains.filter((d) => d !== 'Dashboard') : []);
  };

  if (!selectedCdm) {
    return (
      <div>
        <h3 className="text-2xl font-bold text-text-bright mb-4">{t('quality.title')}</h3>
        <Alert message={t('cdm.select_cdm')} type="info" />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-2xl font-bold text-text-bright">
          {t('quality.title')} — {selectedCdm}
        </h3>
        <div className="flex items-center gap-3">
          <Button
            icon={<LineChart className="h-4 w-4" />}
            variant={showTimeline ? 'primary' : 'default'}
            onClick={() => setShowTimeline(!showTimeline)}
          >
            {t('quality.timeline_title')}
          </Button>
          <Button
            icon={<Download className="h-4 w-4" />}
            onClick={() => authDownload(
              compareMode && compareCdm
                ? qualityApi.comparisonReportUrl(selectedCdm, compareCdm, i18n.language, selectedDomain || undefined)
                : qualityApi.reportUrl(selectedCdm, i18n.language)
            )}
          >
            HTML
          </Button>
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4 text-text-dim" />
            <Switch checked={compareMode} onChange={setCompareMode} label={t('quality.comparison_mode')} size="small" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Left panel */}
        <div className="col-span-12 lg:col-span-3 space-y-4">
          {/* Domain selector */}
          <Card size="small">
            <div className="space-y-3">
              <span className="text-sm font-semibold text-text-bright">{t('quality.select_domain')}</span>
              <Select
                placeholder={t('quality.select_domain')}
                value={selectedDomain}
                onChange={setSelectedDomain}
                options={domains.map((d) => ({
                  value: d,
                  label: (
                    <span className="flex items-center gap-1.5">
                      {t(`domains.${d}`, d)}
                      {analyzedDomains.has(d) && <CheckCircle className="h-3.5 w-3.5 text-emerald-accent" />}
                    </span>
                  ),
                }))}
                allowClear
              />
              {loading ? (
                <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelOperation} block>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button variant="primary" icon={<Play className="h-4 w-4" />} onClick={runAnalysis} disabled={!selectedDomain} block>
                  {t('quality.run_analysis')}
                </Button>
              )}
            </div>
          </Card>

          {/* Batch analysis */}
          <Card size="small">
            <div className="space-y-3">
              <span className="text-sm font-semibold text-text-bright">{t('quality.run_batch')}</span>
              <Checkbox
                checked={selectedBatch.length === domains.filter((d) => d !== 'Dashboard').length}
                onChange={toggleSelectAll}
              >
                {t('quality.select_all')}
              </Checkbox>
              <div className="max-h-[200px] overflow-y-auto space-y-1">
                {domains.filter((d) => d !== 'Dashboard').map((d) => (
                  <Checkbox
                    key={d}
                    checked={selectedBatch.includes(d)}
                    onChange={(checked) => {
                      if (checked) setSelectedBatch([...selectedBatch, d]);
                      else setSelectedBatch(selectedBatch.filter((x) => x !== d));
                    }}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      {t(`domains.${d}`, d)}
                      {analyzedDomains.has(d) && !batchStatus.find(s => s.domain === d) && (
                        <CheckCircle className="h-3.5 w-3.5 text-emerald-accent" />
                      )}
                      {batchStatus.find(s => s.domain === d) && (
                        <Tag color={batchStatus.find(s => s.domain === d)?.status === 'success' ? 'green' : 'red'}>
                          {batchStatus.find(s => s.domain === d)?.status}
                        </Tag>
                      )}
                    </span>
                  </Checkbox>
                ))}
              </div>
              {batchLoading && <Progress percent={batchProgress} size="small" />}
              {batchLoading ? (
                <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelOperation} block>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button icon={<Zap className="h-4 w-4" />} onClick={runBatchAnalysis} disabled={selectedBatch.length === 0} block>
                  {t('quality.run_batch')}
                </Button>
              )}
            </div>
          </Card>

          {/* Snapshot history */}
          {snapshots.length > 0 && (
            <Card size="small" title={<span className="flex items-center gap-2"><History className="h-4 w-4" />{t('quality.snapshot_history')}</span>}>
              <div className="space-y-1">
                {snapshots.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => loadSnapshotById(s.id)}
                    className={`w-full text-left px-2 py-1.5 rounded-lg text-sm transition-colors cursor-pointer bg-transparent border-none ${
                      s.id === snapshotId ? 'text-emerald-accent font-semibold bg-emerald-accent/8' : 'text-text-muted hover:text-text-bright hover:bg-surface-light'
                    }`}
                  >
                    v{s.version} — {s.created_at ? new Date(s.created_at).toLocaleString() : ''}
                  </button>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* Main content */}
        <div className="col-span-12 lg:col-span-9">
          {showTimeline && (
            <div className="mb-4">
              <SnapshotTimeline selectedCdm={selectedCdm} />
            </div>
          )}

          {loading && (
            <div className="text-center py-16">
              <Spinner size="large" />
              <p className="text-sm text-text-muted mt-4">{t('quality.loading')}</p>
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
              <div className="text-center py-16">
                <LayoutDashboard className="h-16 w-16 text-text-dim/40 mx-auto" />
                <p className="text-sm text-text-muted mt-4">{t('quality.run_first')}</p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
