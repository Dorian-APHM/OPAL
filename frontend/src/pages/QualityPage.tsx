import { useState, useEffect, useCallback, useRef } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import {
  Play, Zap, ArrowLeftRight, History, Download, LineChart,
  CheckCircle, StopCircle, LayoutDashboard, ShieldCheck,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { qualityApi, conformityApi, authDownload } from '../api/client';
import { Card, Button, Select, Switch, Tag, Progress, Spinner, Alert, Tabs, Table, useToast } from '../components/ui';
import type { Column } from '../components/ui';
import AnalysisResults from '../components/quality/AnalysisResults';
import ComparisonView from '../components/quality/ComparisonView';
import SnapshotTimeline from '../components/quality/SnapshotTimeline';
import { useNotifDots } from '../hooks/useNotifDots';
import type { SnapshotMeta, BatchProgressEvent } from '../types';

interface Props {
  selectedCdm: string | null;
}

/* ─── Conformity Tab ──────────────────────────────────────────────── */

interface ConformityCheck {
  id: string;
  category: string;
  description: string;
  status: 'pass' | 'warning' | 'fail';
  detail: string;
  value?: unknown;
}

interface ConformityResult {
  score: number;
  total_checks: number;
  passed: number;
  warnings: number;
  failures: number;
  checks: ConformityCheck[];
}

interface ConformitySnapshot {
  result: ConformityResult | null;
  snapshot_id?: number;
  version?: number;
  created_at?: string;
}

function ConformityTab({ selectedCdm }: { selectedCdm: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [running, setRunning] = useSessionState('quality:conformityRunning', false);
  const [analysisId, setAnalysisId] = useSessionState<string | null>('quality:conformityAnalysisId', null);
  const [result, setResult] = useSessionState<ConformityResult | null>('quality:conformityResult', null);
  const [snapshotMeta, setSnapshotMeta] = useSessionState<{ version?: number; created_at?: string } | null>('quality:conformityMeta', null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<{ completed: number; total: number; step: string } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const loadResult = useCallback(() => {
    return conformityApi.get(selectedCdm)
      .then(res => {
        if (!mountedRef.current) return;
        const snap = res.data as ConformitySnapshot;
        if (snap.result) {
          setResult(snap.result);
          setSnapshotMeta({ version: snap.version, created_at: snap.created_at });
        } else {
          setResult(null);
          setSnapshotMeta(null);
        }
      })
      .catch(() => { if (mountedRef.current) { setResult(null); setSnapshotMeta(null); } });
  }, [selectedCdm]);

  // Load existing result on mount + check if a conformity check is already running
  useEffect(() => {
    mountedRef.current = true;
    setLoading(true);

    loadResult().finally(() => { if (mountedRef.current) setLoading(false); });

    // Check if a conformity analysis is running for this CDM
    qualityApi.activeAnalyses()
      .then(res => {
        if (!mountedRef.current) return;
        const active = (res.data.active ?? []).find(
          a => a.type === 'conformity' && a.cdm_name === selectedCdm && !a.cancelled
        );
        if (active) {
          setRunning(true);
          setAnalysisId(active.analysis_id);
          startPolling(active.analysis_id);
        } else {
          // No active analysis — clear stale running state
          setRunning(false);
          setAnalysisId(null);
        }
      })
      .catch(() => toast.error(t('quality.load_failed', 'Failed to check analysis status')));

    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [selectedCdm]);

  const startPolling = useCallback((id: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      qualityApi.activeAnalyses()
        .then(activeRes => {
          if (!mountedRef.current) return;
          const entry = activeRes.data.active.find(
            (a: any) => a.analysis_id === id && !a.cancelled
          );
          if (entry) {
            setProgress({
              completed: entry.completed || 0,
              total: entry.total || 9,
              step: entry.current_step || '',
            });
          } else {
            loadResult().then(() => {
              if (mountedRef.current) {
                toast.success(t('common.success', 'Conformity check complete'));
              }
            });
            setRunning(false);
            setAnalysisId(null);
            setProgress(null);
            if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        })
        .catch(() => {});
    }, 2000);
  }, [selectedCdm, t, toast, loadResult]);

  const STEP_LABELS: Record<string, string> = {
    structure: 'Tables requises',
    person: 'Person',
    observation_period: 'Observation Period',
    condition_occurrence: 'Condition Occurrence',
    drug_exposure: 'Drug Exposure',
    measurement: 'Measurement',
    procedure_occurrence: 'Procedure Occurrence',
    observation: 'Observation',
    visit_occurrence: 'Visit Occurrence',
  };

  const runConformity = async () => {
    setRunning(true);
    setResult(null);
    setSnapshotMeta(null);
    setProgress({ completed: 0, total: 9, step: '' });
    setElapsed(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => setElapsed(prev => prev + 1), 1000);
    try {
      const res = await conformityApi.run(selectedCdm);
      const id = res.data.analysis_id;
      setAnalysisId(id);
      startPolling(id);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || err?.message || t('common.error'));
      setRunning(false);
    }
  };

  const cancelConformity = async () => {
    if (!analysisId) return;
    try {
      await conformityApi.cancel(analysisId);
      toast.info(t('common.cancelled', 'Cancelled'));
    } catch {
      toast.error(t('common.error', 'An error occurred'));
    }
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setRunning(false);
    setAnalysisId(null);
  };

  const scoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-400';
    if (score >= 50) return 'text-orange-400';
    return 'text-red-400';
  };

  const scoreBg = (score: number) => {
    if (score >= 80) return 'bg-emerald-500/12 border-emerald-500/25';
    if (score >= 50) return 'bg-orange-500/12 border-orange-500/25';
    return 'bg-red-500/12 border-red-500/25';
  };

  const statusTag = (status: string) => {
    if (status === 'pass') return <Tag color="green">PASS</Tag>;
    if (status === 'warning') return <Tag color="orange">WARN</Tag>;
    return <Tag color="red">FAIL</Tag>;
  };

  const columns: Column<ConformityCheck>[] = [
    {
      key: 'category',
      title: 'Category',
      dataIndex: 'category',
      sorter: (a, b) => a.category.localeCompare(b.category),
    },
    {
      key: 'description',
      title: 'Check',
      dataIndex: 'description',
    },
    {
      key: 'status',
      title: 'Status',
      dataIndex: 'status',
      width: 100,
      align: 'center',
      render: (val: string) => statusTag(val),
      sorter: (a, b) => {
        const order: Record<string, number> = { fail: 0, warning: 1, pass: 2 };
        return (order[a.status] ?? 1) - (order[b.status] ?? 1);
      },
    },
    {
      key: 'detail',
      title: 'Detail',
      dataIndex: 'detail',
      ellipsis: true,
    },
  ];

  if (loading && !result) {
    return (
      <div className="text-center py-16">
        <Spinner size="large" />
        <p className="text-sm text-text-muted mt-4">{t('quality.loading', 'Loading...')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Action bar */}
      <div className="flex items-center gap-3 flex-wrap">
        {running ? (
          <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelConformity}>
            {t('common.cancel', 'Cancel')}
          </Button>
        ) : (
          <Button variant="primary" icon={<Play className="h-4 w-4" />} onClick={runConformity}>
            {t('quality.run_conformity', 'Run Conformity Check')}
          </Button>
        )}
        {running && <Spinner size="small" />}
        {running && progress && (
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-text-muted truncate">
                  {progress.step ? STEP_LABELS[progress.step] || progress.step : t('quality.conformity_running', 'Running conformity checks...')}
                </span>
                <span className="text-xs text-text-dim shrink-0 ml-2">
                  {progress.completed}/{progress.total} — {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-glass-border overflow-hidden">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all duration-500 ease-out"
                  style={{ width: `${progress.total > 0 ? (progress.completed / progress.total) * 100 : 0}%` }}
                />
              </div>
            </div>
          </div>
        )}
        {running && !progress && <span className="text-sm text-text-muted">{t('quality.conformity_running', 'Running conformity checks...')}</span>}
        {snapshotMeta && !running && (
          <span className="text-xs text-text-dim ml-auto">
            v{snapshotMeta.version} — {snapshotMeta.created_at ? new Date(snapshotMeta.created_at).toLocaleString() : ''}
          </span>
        )}
      </div>

      {/* Results */}
      {result && (
        <>
          {/* Score + Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <Card size="small">
              <div className="flex flex-col items-center py-4">
                <span className="text-xs uppercase tracking-wider text-text-dim mb-2">Score</span>
                <div className={`text-5xl font-bold ${scoreColor(result.score)}`}>
                  {result.score}
                </div>
                <div className={`mt-2 px-3 py-1 rounded-full border text-xs font-medium ${scoreBg(result.score)} ${scoreColor(result.score)}`}>
                  {result.score >= 80 ? 'Good' : result.score >= 50 ? 'Needs Improvement' : 'Critical'}
                </div>
              </div>
            </Card>
            <Card size="small">
              <div className="flex flex-col items-center py-4">
                <span className="text-xs uppercase tracking-wider text-text-dim mb-2">Passed</span>
                <div className="text-4xl font-bold text-emerald-400">{result.passed}</div>
                <span className="text-xs text-text-dim mt-1">/ {result.total_checks}</span>
              </div>
            </Card>
            <Card size="small">
              <div className="flex flex-col items-center py-4">
                <span className="text-xs uppercase tracking-wider text-text-dim mb-2">Warnings</span>
                <div className="text-4xl font-bold text-orange-400">{result.warnings}</div>
              </div>
            </Card>
            <Card size="small">
              <div className="flex flex-col items-center py-4">
                <span className="text-xs uppercase tracking-wider text-text-dim mb-2">Failures</span>
                <div className="text-4xl font-bold text-red-400">{result.failures}</div>
              </div>
            </Card>
          </div>

          {/* Checks table */}
          <Card size="small" title={`Individual Checks (${result.checks?.length || 0})`}>
            <Table<ConformityCheck>
              columns={columns}
              dataSource={result.checks || []}
              rowKey={(r) => r.id || `${r.category}-${r.description}`}
              size="small"
              pagination={result.checks && result.checks.length > 20 ? { pageSize: 20 } : false}
            />
          </Card>
        </>
      )}

      {/* Empty state */}
      {!result && !running && (
        <Card>
          <div className="text-center py-16">
            <ShieldCheck className="h-16 w-16 text-text-dim/40 mx-auto" />
            <p className="text-sm text-text-muted mt-4">
              {t('quality.conformity_empty', 'Run a conformity check to validate your CDM against OMOP standards.')}
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ─── Main Quality Page ───────────────────────────────────────────── */

export default function QualityPage({ selectedCdm }: Props) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const [domains, setDomains] = useState<string[]>([]);
  const [selectedDomain, setSelectedDomain] = useSessionState<string | null>('quality:selectedDomain', null);
  const [results, setResults] = useSessionState<any>(  'quality:results', null);
  const [snapshotId, setSnapshotId] = useSessionState<number | undefined>('quality:snapshotId', undefined);
  const [loading, setLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useSessionState('quality:batchLoading', false);
  const [batchProgress, setBatchProgress] = useSessionState('quality:batchProgress', 0);
  const [batchStatus, setBatchStatus] = useSessionState('quality:batchStatus', [] as { domain: string; status: string }[]);
  const [selectedBatch, setSelectedBatch] = useSessionState('quality:selectedBatch', [] as string[]);
  const [compareMode, setCompareMode] = useSessionState('quality:compareMode', false);
  const [compareCdm, setCompareCdm] = useSessionState<string | null>('quality:compareCdm', null);
  const [snapshots, setSnapshots] = useSessionState('quality:snapshots', [] as SnapshotMeta[]);
  const [showTimeline, setShowTimeline] = useSessionState('quality:showTimeline', false);
  const [analyzedDomains, setAnalyzedDomains] = useSessionState('quality:analyzedDomains', new Set<string>());
  const streamAbortRef = useRef<AbortController | null>(null);
  const analysisIdRef = useRef<string | null>(null);
  const singleAnalysisIdRef = useRef<string | null>(null);
  const singlePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { hasNotif, markRead, hasAnyNotifExcept } = useNotifDots('quality_done');

  // Track mounted state
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Only abort the stream reader, NOT the server analysis
      if (streamAbortRef.current) streamAbortRef.current.abort();
      streamAbortRef.current = null;
      if (batchPollRef.current) clearInterval(batchPollRef.current);
      if (singlePollRef.current) clearInterval(singlePollRef.current);
    };
  }, []);

  // Refresh data when a quality_done notification arrives (analysis finished while on this page or after navigating back)
  useEffect(() => {
    const handler = (e: Event) => {
      const notif = (e as CustomEvent).detail;
      if (!notif || notif.type !== 'quality_done') return;
      if (selectedCdm && notif.link && notif.link.includes(`cdm=${selectedCdm}`)) {
        qualityApi.timeline(selectedCdm).then((r) => {
          if (mountedRef.current) setAnalyzedDomains(new Set(Object.keys(r.data.timelines ?? {})));
        }).catch(() => {});
        if (selectedDomain) {
          loadLatestSnapshot();
          loadSnapshots();
        }
      }
    };
    window.addEventListener('opal:notification', handler);
    return () => window.removeEventListener('opal:notification', handler);
  }, [selectedCdm, selectedDomain]);

  useEffect(() => {
    qualityApi.domains(selectedCdm || undefined)
      .then((res) => setDomains(res.data.domains ?? []))
      .catch(() => setDomains([]));
  }, [selectedCdm]);

  useEffect(() => {
    if (!selectedCdm) { setAnalyzedDomains(new Set()); return; }
    qualityApi.timeline(selectedCdm).then((res) => {
      setAnalyzedDomains(new Set(Object.keys(res.data.timelines ?? {})));
    }).catch(() => setAnalyzedDomains(new Set()));
  }, [selectedCdm]);

  // Check for running batch/single analyses on mount / CDM change
  useEffect(() => {
    if (!selectedCdm) return;
    qualityApi.activeAnalyses()
      .then(res => {
        if (!mountedRef.current) return;
        const active = res.data.active ?? [];
        // Resume batch if running
        const batch = active.find(
          a => a.type === 'batch' && a.cdm_name === selectedCdm && !a.cancelled
        );
        if (batch) {
          analysisIdRef.current = batch.analysis_id;
          setBatchLoading(true);
          const pct = batch.total > 0 ? Math.round((batch.completed / batch.total) * 100) : 0;
          setBatchProgress(pct);
          if (batch.domain_status?.length) setBatchStatus(batch.domain_status);
          startBatchPolling(batch.analysis_id, batch.domains);
        } else {
          // No active batch — clear stale loading state
          setBatchLoading(false);
          analysisIdRef.current = null;
        }
        // Resume single-domain if running
        const single = active.find(
          a => a.type === 'single' && a.cdm_name === selectedCdm && !a.cancelled
        );
        if (single) {
          singleAnalysisIdRef.current = single.analysis_id;
          setLoading(true);
          startSinglePolling(single.analysis_id, single.domains[0]);
        } else {
          // No active single — clear stale loading state
          setLoading(false);
          singleAnalysisIdRef.current = null;
        }
      })
      .catch(() => toast.error(t('quality.load_failed', 'Failed to check analysis status')));
  }, [selectedCdm]);

  // Poll for batch analysis completion when we've reconnected
  const startBatchPolling = useCallback((aid: string, batchDomains: string[]) => {
    if (batchPollRef.current) clearInterval(batchPollRef.current);
    batchPollRef.current = setInterval(() => {
      qualityApi.activeAnalyses()
        .then(res => {
          if (!mountedRef.current) return;
          // Malformed/partial response — keep polling rather than assuming finished.
          if (!Array.isArray(res.data.active)) return;
          const entry = res.data.active.find(a => a.analysis_id === aid && !a.cancelled);
          if (entry) {
            // Update progress from server
            const pct = entry.total > 0 ? Math.round((entry.completed / entry.total) * 100) : 0;
            setBatchProgress(pct);
            if (entry.domain_status?.length) {
              setBatchStatus(entry.domain_status);
              entry.domain_status.forEach((ds: { domain: string; status: string }) => {
                if (ds.status === 'success') setAnalyzedDomains(prev => new Set([...prev, ds.domain]));
              });
            }
            return;
          }
          // No longer in the active list — batch finished, refresh data.
          {
            setBatchLoading(false);
            setBatchProgress(100);
            analysisIdRef.current = null;
            if (batchPollRef.current) clearInterval(batchPollRef.current);
            batchPollRef.current = null;
            // Toast is handled globally by TopNav via WebSocket notification
            // Refresh analyzed domains
            if (selectedCdm) {
              qualityApi.timeline(selectedCdm).then((r) => {
                if (mountedRef.current) setAnalyzedDomains(new Set(Object.keys(r.data.timelines ?? {})));
              }).catch(() => toast.error(t('quality.timeline_failed', 'Failed to refresh timeline')));
            }
            // Reload current snapshot if viewing an analyzed domain
            if (selectedDomain) {
              loadLatestSnapshot();
              loadSnapshots();
            }
          }
        })
        .catch(() => {}); // polling — silent
    }, 2000);
  }, [selectedCdm, selectedDomain, t, toast]);

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
      if (mountedRef.current) { setResults(res.data.results); setSnapshotId(res.data.id); }
    } catch { if (mountedRef.current) { setResults(null); setSnapshotId(undefined); } }
  };

  const loadSnapshots = async () => {
    if (!selectedCdm || !selectedDomain) return;
    try {
      const res = await qualityApi.listSnapshots(selectedCdm, selectedDomain);
      if (mountedRef.current) setSnapshots(res.data.snapshots);
    } catch { if (mountedRef.current) setSnapshots([]); }
  };

  const loadSnapshotById = async (id: number) => {
    try {
      const res = await qualityApi.getSnapshotById(id);
      setResults(res.data.results); setSnapshotId(res.data.id);
    } catch { toast.error(t('common.error')); }
  };

  const cancelBatchAnalysis = () => {
    // Abort the SSE stream reader
    if (streamAbortRef.current) { streamAbortRef.current.abort(); streamAbortRef.current = null; }
    // Cancel the server-side analysis
    if (analysisIdRef.current) {
      qualityApi.cancelAnalysis(analysisIdRef.current).catch(() => {});
      analysisIdRef.current = null;
    }
    if (batchPollRef.current) { clearInterval(batchPollRef.current); batchPollRef.current = null; }
    setBatchLoading(false);
    setBatchProgress(0);
    toast.info(t('common.cancelled', 'Cancelled'));
  };

  // Poll for single-domain analysis completion
  const startSinglePolling = useCallback((aid: string, domain: string) => {
    if (singlePollRef.current) clearInterval(singlePollRef.current);
    singlePollRef.current = setInterval(() => {
      qualityApi.activeAnalyses()
        .then(res => {
          if (!mountedRef.current) return;
          // Malformed/partial response — keep polling rather than declaring success.
          if (!Array.isArray(res.data.active)) return;
          const entry = res.data.active.find(a => a.analysis_id === aid);
          if (entry && !entry.cancelled) return; // still running
          // Finished or cancelled — stop polling
          if (singlePollRef.current) clearInterval(singlePollRef.current);
          singlePollRef.current = null;
          singleAnalysisIdRef.current = null;
          setLoading(false);
          // Check if it succeeded
          const succeeded = !entry; // entry removed = finished
          if (succeeded) {
            setAnalyzedDomains(prev => new Set([...prev, domain]));
            toast.success(t('common.success'));
            if (selectedDomain === domain) {
              loadLatestSnapshot();
              loadSnapshots();
            }
          } else {
            toast.info(t('common.cancelled', 'Cancelled'));
          }
        })
        .catch(() => {}); // polling — silent
    }, 2000);
  }, [selectedDomain, t, toast]);

  const cancelSingleAnalysis = () => {
    if (singleAnalysisIdRef.current) {
      qualityApi.cancelAnalysis(singleAnalysisIdRef.current).catch(() => {});
      singleAnalysisIdRef.current = null;
    }
    if (singlePollRef.current) { clearInterval(singlePollRef.current); singlePollRef.current = null; }
    setLoading(false);
    toast.info(t('common.cancelled', 'Cancelled'));
  };

  const runAnalysis = async () => {
    if (!selectedCdm || !selectedDomain) return;
    setLoading(true);
    try {
      const res = await qualityApi.analyze(selectedCdm, selectedDomain);
      const aid = res.data.analysis_id;
      singleAnalysisIdRef.current = aid;
      startSinglePolling(aid, selectedDomain);
    } catch (err: any) {
      if (!mountedRef.current) return;
      toast.error(err?.response?.data?.detail || t('common.error'));
      setLoading(false);
    }
  };

  const runBatchAnalysis = useCallback(async () => {
    if (!selectedCdm || selectedBatch.length === 0) return;
    const ctrl = new AbortController(); streamAbortRef.current = ctrl;
    setBatchLoading(true); setBatchProgress(0); setBatchStatus([]);

    try {
      const response = await qualityApi.analyzeBatchStream(selectedCdm, selectedBatch);
      const reader = response.body?.getReader();
      if (!reader) {
        const res = await qualityApi.analyzeBatch(selectedCdm, selectedBatch);
        if (mountedRef.current) {
          setBatchProgress(100);
          toast.success(`${res.data.success_count}/${res.data.total} ${t('common.success')}`);
        }
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      let gotStart = false;

      // Start polling as fallback — authoritative source for batchStatus & progress
      const pollFallback = setInterval(() => {
        if (!mountedRef.current) return;
        qualityApi.activeAnalyses().then(res => {
          if (!mountedRef.current) return;
          const aid = analysisIdRef.current;
          if (!aid) return;
          if (!Array.isArray(res.data.active)) return;
          const entry = res.data.active.find(a => a.analysis_id === aid && !a.cancelled);
          if (entry) {
            const pct = entry.total > 0 ? Math.round((entry.completed / entry.total) * 100) : 0;
            setBatchProgress(pct);
            if (entry.domain_status?.length) {
              setBatchStatus(entry.domain_status);
              entry.domain_status.forEach((ds: { domain: string; status: string }) => {
                if (ds.status === 'success') setAnalyzedDomains(prev => new Set([...prev, ds.domain]));
              });
            }
          }
        }).catch(() => {});
      }, 2000);

      try {
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
                if (event.type === 'start' && event.analysis_id) {
                  analysisIdRef.current = event.analysis_id;
                  gotStart = true;
                } else if (event.type === 'progress') {
                  if (mountedRef.current) {
                    setBatchProgress(Math.round((event.completed / event.total) * 100));
                    if (event.domain && event.status && event.status !== 'running') {
                      // Dedupe by domain — the stream and the poll fallback both write
                      // batchStatus, and a domain may emit several non-running events.
                      setBatchStatus(prev => [
                        ...prev.filter(s => s.domain !== event.domain),
                        { domain: event.domain!, status: event.status! },
                      ]);
                      if (event.status === 'success') setAnalyzedDomains(prev => new Set([...prev, event.domain!]));
                    }
                  }
                } else if (event.type === 'done') {
                  if (mountedRef.current) {
                    setBatchProgress(100);
                  }
                } else if (event.type === 'error') {
                  if (mountedRef.current) toast.error(event.message || t('common.error'));
                }
              } catch {}
            }
          }
        }
      } finally {
        clearInterval(pollFallback);
      }

      // If we never got the start event (stream was fully buffered), get analysis_id from active
      if (!gotStart && !analysisIdRef.current) {
        try {
          const res = await qualityApi.activeAnalyses();
          const batch = (res.data.active ?? []).find(a => a.type === 'batch' && a.cdm_name === selectedCdm && !a.cancelled);
          if (batch) analysisIdRef.current = batch.analysis_id;
        } catch {}
      }

      if (mountedRef.current && selectedDomain) { await loadLatestSnapshot(); await loadSnapshots(); }
    } catch {
      if (mountedRef.current) toast.error(t('common.error'));
    } finally {
      if (mountedRef.current) { setBatchLoading(false); }
      streamAbortRef.current = null;
      analysisIdRef.current = null;
    }
  }, [selectedCdm, selectedBatch, selectedDomain]);

  const toggleSelectAll = (checked: boolean) => {
    setSelectedBatch(checked ? domains.filter((d) => d !== 'Dashboard') : []);
  };

  const handleDomainChange = (domain: string | null) => {
    setSelectedDomain(domain);
    if (domain) markRead(domain);
  };

  if (!selectedCdm) {
    return (
      <div>
        <h3 className="text-2xl font-bold text-text-bright mb-4">{t('quality.title')}</h3>
        <Alert message={t('cdm.select_cdm')} type="info" />
      </div>
    );
  }

  const analysisContent = (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <h3 className="text-xl sm:text-2xl font-bold text-text-bright">
          {t('quality.title')} — {selectedCdm}
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            icon={<LineChart className="h-4 w-4" />}
            variant={showTimeline ? 'primary' : 'default'}
            onClick={() => setShowTimeline(!showTimeline)}
            size="small"
          >
            {t('quality.timeline_title')}
          </Button>
          <Button
            icon={<Download className="h-4 w-4" />}
            size="small"
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

      <div className="flex flex-col lg:grid lg:grid-cols-12 gap-3">
        {/* Left panel */}
        <div className="w-full lg:col-span-2 space-y-3">
          {/* Domain selector */}
          <Card size="small">
            <div className="space-y-3">
              <span className="text-sm font-semibold text-text-bright">{t('quality.select_domain')}</span>
              <Select
                placeholder={t('quality.select_domain')}
                value={selectedDomain}
                onChange={handleDomainChange}
                options={domains.map((d) => ({
                  value: d,
                  label: (
                    <span className="flex items-center gap-1.5">
                      {t(`domains.${d}`, d)}
                      {hasNotif(d) && <span className="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0" />}
                      {analyzedDomains.has(d) && <CheckCircle className="h-3.5 w-3.5 text-emerald-accent" />}
                    </span>
                  ),
                }))}
                allowClear
              />
              {loading ? (
                <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelSingleAnalysis} block>
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
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-text-bright">{t('quality.run_batch')}</span>
                <button
                  onClick={() => toggleSelectAll(selectedBatch.length !== domains.filter((d) => d !== 'Dashboard').length)}
                  className="text-xs text-emerald-accent hover:text-emerald-accent-light cursor-pointer bg-transparent border-none"
                >
                  {selectedBatch.length === domains.filter((d) => d !== 'Dashboard').length ? t('common.clear', 'Clear') : t('quality.select_all')}
                </button>
              </div>
              <div className="max-h-[280px] overflow-y-auto -mx-2">
                {domains.filter((d) => d !== 'Dashboard').map((d) => {
                  const isSelected = selectedBatch.includes(d);
                  const batchItem = batchStatus.find(s => s.domain === d);
                  return (
                    <button
                      key={d}
                      onClick={() => {
                        if (isSelected) setSelectedBatch(selectedBatch.filter((x) => x !== d));
                        else setSelectedBatch([...selectedBatch, d]);
                      }}
                      className={`
                        w-full flex items-center justify-between px-2 py-1.5 text-sm rounded-md
                        transition-all duration-150 cursor-pointer bg-transparent border-none text-left
                        ${isSelected
                          ? 'text-emerald-accent bg-emerald-accent/10'
                          : 'text-text-muted hover:text-text-bright hover:bg-surface-light'
                        }
                      `}
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        {t(`domains.${d}`, d)}
                      </span>
                      <span className="flex items-center gap-1 shrink-0 ml-1">
                        {batchItem ? (
                          <Tag color={batchItem.status === 'success' ? 'green' : 'red'} style={{ fontSize: 10 }}>
                            {batchItem.status}
                          </Tag>
                        ) : analyzedDomains.has(d) ? (
                          <CheckCircle className="h-3 w-3 text-emerald-accent/60" />
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
              {batchLoading && <Progress percent={batchProgress} size="small" />}
              {batchLoading ? (
                <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelBatchAnalysis} block>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button icon={<Zap className="h-4 w-4" />} onClick={runBatchAnalysis} disabled={selectedBatch.length === 0} block>
                  {t('quality.run_batch')} {selectedBatch.length > 0 && `(${selectedBatch.length})`}
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
        <div className="w-full lg:col-span-10">
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

  const handleTabChange = (key: string) => {
    if (key === 'conformity') {
      markRead('Conformity');
    }
  };

  return (
    <Tabs
      onChange={handleTabChange}
      items={[
        {
          key: 'analysis',
          label: (
            <span className="flex items-center gap-2">
              <LayoutDashboard className="h-4 w-4" />
              {t('quality.tab_analysis', 'Analysis')}
              {hasAnyNotifExcept('Conformity') && (
                <span className="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0" />
              )}
            </span>
          ),
          children: analysisContent,
        },
        {
          key: 'conformity',
          label: (
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              {t('quality.tab_conformity', 'Conformity')}
              {hasNotif('Conformity') && (
                <span className="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0" />
              )}
            </span>
          ),
          children: <ConformityTab selectedCdm={selectedCdm} />,
        },
      ]}
    />
  );
}
