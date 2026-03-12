import { useState, useEffect, useCallback, useRef } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import {
  Card,
  Button,
  Select,
  Switch,
  Checkbox,
  Table,
  Tag,
  Spinner,
  Empty,
  Alert,
  Tooltip,
  Progress,
  useToast,
} from '../components/ui';
import type { Column } from '../components/ui';
import {
  Database,
  Download,
  Eye,
  Table2,
  ChevronRight,
  Info,
  Users,
  Columns3,
  FileSpreadsheet,
  Link2,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { dataManagementApi } from '../api/client';
import { authDownload } from '../api/client';

// ---------- Types ----------

interface CohortForExtraction {
  id: number;
  name: string;
  description: string;
  cdm_name: string;
  patient_count: number | null;
  latest_version: number | null;
  has_same_visit: boolean;
  updated_at: string | null;
}

interface TableInfo {
  table_name: string;
  has_visit: boolean;
}

interface ColumnInfo {
  column_name: string;
  data_type: string;
}

interface TableColumnState {
  [tableName: string]: {
    selected: boolean;
    columns: ColumnInfo[];
    selectedColumns: Set<string>;
    loading: boolean;
  };
}

interface Props {
  selectedCdm: string | null;
}

// ---------- Component ----------

export default function DataManagementPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();

  // ── Persisted state (survives navigation) ──
  const [cohorts, setCohorts] = useSessionState<CohortForExtraction[]>('data:cohorts', []);
  const [loadingCohorts, setLoadingCohorts] = useState(false);
  const [selectedCohortId, setSelectedCohortId] = useSessionState<string | null>('data:selectedCohortId', null);
  const [tables, setTables] = useSessionState<TableInfo[]>('data:tables', []);
  const [loadingTables, setLoadingTables] = useState(false);
  const [tableState, setTableState] = useSessionState<TableColumnState>('data:tableState', {});
  const [sameVisitOnly, setSameVisitOnly] = useSessionState('data:sameVisitOnly', false);

  // ── Task state (persisted — survives navigation) ──
  const [taskId, setTaskId] = useSessionState<string | null>('data:taskId', null);
  const [loading, setLoading] = useSessionState('data:loading', false);
  const [progressCompleted, setProgressCompleted] = useSessionState('data:progDone', 0);
  const [progressTotal, setProgressTotal] = useSessionState('data:progTotal', 3);
  const [currentStep, setCurrentStep] = useSessionState('data:step', '');

  // ── Result state (persisted) ──
  const [previewData, setPreviewData] = useSessionState<{
    columns: string[];
    rows: Record<string, any>[];
    total_count: number;
  } | null>('data:previewData', null);
  const [completedTaskId, setCompletedTaskId] = useSessionState<string | null>('data:completedTaskId', null);
  const [error, setError] = useState('');

  // Expanded tables (for accordion behavior)
  const [expandedTable, setExpandedTable] = useState<string | null>(null);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cohortIdNum = selectedCohortId ? parseInt(selectedCohortId, 10) : null;
  const selectedCohort = cohorts.find((c) => c.id === cohortIdNum) || null;

  // ── Polling ──

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback((tid: string) => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const resp = await dataManagementApi.extractStatus(tid);
        if (resp.data.completed != null) setProgressCompleted(resp.data.completed);
        if (resp.data.total != null) setProgressTotal(resp.data.total);
        if (resp.data.current_step) setCurrentStep(resp.data.current_step);

        if (resp.data.status === 'completed' && resp.data.result) {
          setPreviewData({
            columns: resp.data.result.columns,
            rows: resp.data.result.rows,
            total_count: resp.data.result.total_count,
          });
          setCompletedTaskId(tid);
          setLoading(false);
          setTaskId(null);
          setProgressCompleted(0);
          setProgressTotal(3);
          setCurrentStep('');
          stopPolling();
          toast.success(
            `${t('datamanagement.extraction_complete', 'Extraction complete')} — ${resp.data.result.total_count.toLocaleString()} ${t('datamanagement.rows', 'rows')}`
          );
        } else if (resp.data.status === 'error') {
          setError(resp.data.error || 'Extraction failed');
          setLoading(false);
          setTaskId(null);
          setProgressCompleted(0);
          setProgressTotal(3);
          setCurrentStep('');
          stopPolling();
        }
      } catch {
        // Network error — keep polling
      }
    }, 2000);
  }, [stopPolling]);

  // On mount: reconnect to running task if we have a taskId, or check server
  useEffect(() => {
    if (taskId && loading) {
      startPolling(taskId);
    } else if (!taskId && loading) {
      dataManagementApi.extractActive().then(resp => {
        if (resp.data.task_id && resp.data.status === 'running') {
          setTaskId(resp.data.task_id);
          startPolling(resp.data.task_id);
        } else if (resp.data.task_id && resp.data.status === 'completed') {
          // Completed while away — fetch result
          dataManagementApi.extractStatus(resp.data.task_id).then(r => {
            if (r.data.result) {
              setPreviewData({
                columns: r.data.result.columns,
                rows: r.data.result.rows,
                total_count: r.data.result.total_count,
              });
              setCompletedTaskId(resp.data.task_id!);
            }
            setLoading(false);
            setTaskId(null);
          }).catch(() => setLoading(false));
        } else {
          setLoading(false);
        }
      }).catch(() => setLoading(false));
    }
    return stopPolling;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load cohorts and tables when CDM changes
  const prevCdmRef = useRef<string | null>(selectedCdm);
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!selectedCdm) return;
    const cdmChanged = prevCdmRef.current !== null && prevCdmRef.current !== selectedCdm;
    prevCdmRef.current = selectedCdm;

    // On first mount, only reload lists if not already cached
    if (!mountedRef.current) {
      mountedRef.current = true;
      // Refresh cohort list silently (don't clear selections)
      setLoadingCohorts(true);
      dataManagementApi
        .listCohorts(selectedCdm)
        .then((res) => setCohorts(res.data.cohorts))
        .catch(() => setCohorts([]))
        .finally(() => setLoadingCohorts(false));
      if (tables.length === 0) {
        setLoadingTables(true);
        dataManagementApi
          .listTables(selectedCdm)
          .then((res) => {
            setTables(res.data.tables);
            const initial: TableColumnState = {};
            for (const tbl of res.data.tables) {
              initial[tbl.table_name] = {
                selected: false,
                columns: [],
                selectedColumns: new Set(),
                loading: false,
              };
            }
            setTableState(initial);
          })
          .catch(() => setTables([]))
          .finally(() => setLoadingTables(false));
      }
      return;
    }

    // CDM actually changed by user — reset everything
    if (cdmChanged) {
      setSelectedCohortId(null);
      setPreviewData(null);
      setCompletedTaskId(null);
    }
    setLoadingCohorts(true);
    dataManagementApi
      .listCohorts(selectedCdm)
      .then((res) => setCohorts(res.data.cohorts))
      .catch(() => setCohorts([]))
      .finally(() => setLoadingCohorts(false));

    if (cdmChanged) {
      setLoadingTables(true);
      dataManagementApi
        .listTables(selectedCdm)
        .then((res) => {
          setTables(res.data.tables);
          const initial: TableColumnState = {};
          for (const tbl of res.data.tables) {
            initial[tbl.table_name] = {
              selected: false,
              columns: [],
              selectedColumns: new Set(),
              loading: false,
            };
          }
          setTableState(initial);
        })
        .catch(() => setTables([]))
        .finally(() => setLoadingTables(false));
    }
  }, [selectedCdm]);

  // Reset sameVisitOnly when cohort actually changes (not on remount)
  const prevCohortRef = useRef<string | null>(selectedCohortId);
  useEffect(() => {
    if (prevCohortRef.current === selectedCohortId) return; // skip remount
    prevCohortRef.current = selectedCohortId;
    setSameVisitOnly(false);
    setPreviewData(null);
    setCompletedTaskId(null);
  }, [selectedCohortId]);

  // Load columns when a table is selected
  const handleTableToggle = useCallback(
    (tableName: string, checked: boolean) => {
      if (!selectedCdm) return;
      setTableState((prev) => {
        const next = { ...prev };
        next[tableName] = { ...next[tableName], selected: checked };

        if (checked && next[tableName].columns.length === 0) {
          next[tableName].loading = true;
          dataManagementApi
            .listColumns(selectedCdm, tableName)
            .then((res) => {
              const cols: ColumnInfo[] = res.data.columns;
              setTableState((p) => ({
                ...p,
                [tableName]: {
                  ...p[tableName],
                  columns: cols,
                  selectedColumns: new Set(cols.map((c) => c.column_name)),
                  loading: false,
                },
              }));
            })
            .catch(() => {
              setTableState((p) => ({
                ...p,
                [tableName]: { ...p[tableName], loading: false },
              }));
            });
        }
        return next;
      });
      if (checked) setExpandedTable(tableName);
    },
    [selectedCdm],
  );

  const handleColumnToggle = (tableName: string, colName: string, checked: boolean) => {
    setTableState((prev) => {
      const ts = { ...prev[tableName] };
      const next = new Set(ts.selectedColumns);
      if (checked) next.add(colName);
      else next.delete(colName);
      return { ...prev, [tableName]: { ...ts, selectedColumns: next } };
    });
  };

  const handleSelectAllColumns = (tableName: string, checked: boolean) => {
    setTableState((prev) => {
      const ts = { ...prev[tableName] };
      const next = checked ? new Set(ts.columns.map((c) => c.column_name)) : new Set<string>();
      return { ...prev, [tableName]: { ...ts, selectedColumns: next } };
    });
  };

  const getTableSelections = () => {
    const selections: { table: string; columns: string[] }[] = [];
    for (const [tableName, state] of Object.entries(tableState)) {
      if (state.selected && state.selectedColumns.size > 0) {
        selections.push({
          table: tableName,
          columns: Array.from(state.selectedColumns),
        });
      }
    }
    return selections;
  };

  const canExtract = cohortIdNum !== null && getTableSelections().length > 0 && !loading;
  const selectedTableCount = Object.values(tableState).filter((s) => s.selected).length;
  const [previewLoading, setPreviewLoading] = useSessionState('data:previewLoading', false);
  const previewAbortRef = useRef<AbortController | null>(null);

  // ── Quick preview (synchronous, no CSV build) ──
  const runPreview = useCallback(async () => {
    if (!cohortIdNum) return;
    const sels = getTableSelections();
    if (sels.length === 0) return;
    // Cancel any in-flight preview
    if (previewAbortRef.current) previewAbortRef.current.abort();
    const ctrl = new AbortController();
    previewAbortRef.current = ctrl;
    setPreviewLoading(true);
    setError('');
    try {
      const resp = await dataManagementApi.extractPreview({
        cohort_id: cohortIdNum,
        same_visit_only: sameVisitOnly,
        table_selections: sels,
        preview_limit: 50,
      });
      if (ctrl.signal.aborted) return;
      setPreviewData({
        columns: resp.data.columns,
        rows: resp.data.rows,
        total_count: resp.data.total_count,
      });
    } catch (err: any) {
      if (ctrl.signal.aborted) return;
      setError(err.response?.data?.detail || err.message || 'Preview failed');
    } finally {
      if (!ctrl.signal.aborted) setPreviewLoading(false);
    }
  }, [cohortIdNum, sameVisitOnly, tableState]);

  const handlePreview = () => { runPreview(); };

  // Re-launch preview on remount if it was in progress
  const previewResumedRef = useRef(false);
  useEffect(() => {
    if (previewLoading && !previewResumedRef.current && cohortIdNum) {
      previewResumedRef.current = true;
      runPreview();
    }
    return () => { if (previewAbortRef.current) previewAbortRef.current.abort(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Launch full extraction (background, builds CSV for download) ──
  const handleExtract = async () => {
    if (!canExtract) return;
    setLoading(true);
    setError('');
    setCompletedTaskId(null);
    try {
      const resp = await dataManagementApi.extractStart({
        cohort_id: cohortIdNum!,
        same_visit_only: sameVisitOnly,
        table_selections: getTableSelections(),
        preview_limit: 50,
      });
      const tid = resp.data.task_id;
      setTaskId(tid);
      startPolling(tid);
    } catch (err: any) {
      setError(err.message || 'Failed to start extraction');
      setLoading(false);
    }
  };

  // ── Cancel extraction ──
  const handleCancel = () => {
    stopPolling();
    if (taskId) {
      dataManagementApi.extractCancel(taskId).catch(() => {});
    }
    setTaskId(null);
    setLoading(false);
    setProgressCompleted(0);
    setProgressTotal(3);
    setCurrentStep('');
  };

  // ── Download CSV ──
  const handleDownload = () => {
    if (!completedTaskId) return;
    const url = dataManagementApi.extractDownloadUrl(completedTaskId);
    authDownload(url);
    // Don't clear completedTaskId — user might want to download again
    // The backend cleans up the task after download
  };

  // ---------- Render ----------

  if (!selectedCdm) {
    return (
      <div className="p-6">
        <Alert
          type="info"
          message={t('datamanagement.select_cdm', 'Please select a CDM database from the sidebar.')}
        />
      </div>
    );
  }

  const progressPct = progressTotal > 0 ? Math.round((progressCompleted / progressTotal) * 100) : 0;

  return (
    <div className="p-6 max-w-[1400px] space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400">
          <Database className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-text-bright">
            {t('datamanagement.title', 'Data Management')}
          </h2>
          <p className="text-xs text-text-dim mt-0.5">
            {t('datamanagement.subtitle', 'Extract datasets from cohorts for analysis')}
          </p>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 text-xs text-text-dim">
        <StepBadge step={1} active={!selectedCohortId} done={!!selectedCohortId} />
        <span className={selectedCohortId ? 'text-text-muted' : ''}>
          {t('datamanagement.select_cohort', 'Select Cohort')}
        </span>
        <ChevronRight className="h-3.5 w-3.5 text-text-dim" />
        <StepBadge step={2} active={!!selectedCohortId && selectedTableCount === 0} done={selectedTableCount > 0} />
        <span className={selectedTableCount > 0 ? 'text-text-muted' : ''}>
          {t('datamanagement.select_tables', 'Tables & Columns')}
        </span>
        <ChevronRight className="h-3.5 w-3.5 text-text-dim" />
        <StepBadge step={3} active={canExtract} done={!!previewData} />
        <span className={previewData ? 'text-text-muted' : ''}>
          {t('datamanagement.extract', 'Extract')}
        </span>
      </div>

      {/* Step 1: Select Cohort */}
      <Card
        size="small"
        title={
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-emerald-400" />
            <span>{t('datamanagement.step1_title', 'Select a Cohort')}</span>
          </div>
        }
        extra={
          selectedCohort?.patient_count != null ? (
            <Tag color="blue">{selectedCohort.patient_count.toLocaleString()} patients</Tag>
          ) : undefined
        }
      >
        <div className="p-4 space-y-4">
          {loadingCohorts ? (
            <Spinner size="small" tip="Loading cohorts..." />
          ) : (
            <Select
              placeholder={t('datamanagement.choose_cohort', 'Choose a saved cohort...')}
              value={selectedCohortId}
              onChange={(val) => setSelectedCohortId(val || null)}
              allowClear
              options={cohorts.map((c) => ({
                value: String(c.id),
                label: `${c.name}${c.patient_count != null ? ` (${c.patient_count.toLocaleString()} patients)` : ''}`,
              }))}
            />
          )}

          {selectedCohort && (
            <div className="space-y-3">
              {selectedCohort.description && (
                <p className="text-sm text-text-dim">{selectedCohort.description}</p>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {selectedCohort.patient_count != null && (
                  <Tag color="blue">
                    <Users className="h-3 w-3 mr-1 inline" />
                    {selectedCohort.patient_count.toLocaleString()} patients
                  </Tag>
                )}
                <Tag color={selectedCohort.has_same_visit ? 'green' : 'default'}>
                  <Link2 className="h-3 w-3 mr-1 inline" />
                  {selectedCohort.has_same_visit ? 'Same Visit' : 'No Same Visit'}
                </Tag>
                {selectedCohort.latest_version && (
                  <Tag color="purple">v{selectedCohort.latest_version}</Tag>
                )}
              </div>

              {/* Same Visit Only toggle */}
              <div className="flex items-center gap-3 p-3 rounded-xl bg-surface-dark border border-glass-border">
                <Switch
                  checked={sameVisitOnly}
                  onChange={setSameVisitOnly}
                  disabled={!selectedCohort.has_same_visit}
                  size="small"
                />
                <span className="text-sm font-medium text-text-bright">
                  {t('datamanagement.same_visit_only', 'Same Visit Only')}
                </span>
                <Tooltip
                  title={
                    !selectedCohort.has_same_visit
                      ? t(
                          'datamanagement.same_visit_disabled',
                          'This cohort was not built with Same Visit enabled. Enable Same Visit in the Cohort Builder to use this option.',
                        )
                      : t(
                          'datamanagement.same_visit_tooltip',
                          'When enabled, only extract data for the specific visits matched by the cohort. When disabled, extract all visits for each patient.',
                        )
                  }
                >
                  <span>
                    <Info className="h-4 w-4 text-text-dim" />
                  </span>
                </Tooltip>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Step 2: Select Tables & Columns */}
      <Card
        size="small"
        title={
          <div className="flex items-center gap-2">
            <Columns3 className="h-4 w-4 text-emerald-400" />
            <span>{t('datamanagement.step2_title', 'Select Tables & Columns')}</span>
            {selectedTableCount > 0 && (
              <Tag color="emerald">
                {selectedTableCount} {t('datamanagement.tables_selected', 'selected')}
              </Tag>
            )}
          </div>
        }
      >
        <div className="p-4">
          {loadingTables ? (
            <Spinner size="small" tip="Loading tables..." />
          ) : tables.length === 0 ? (
            <Empty description={t('datamanagement.no_tables', 'No tables found')} />
          ) : (
            <div className="space-y-1">
              {tables.map((tbl) => {
                const ts = tableState[tbl.table_name];
                if (!ts) return null;
                const colCount = ts.selectedColumns.size;
                const totalCols = ts.columns.length;
                const isExpanded = expandedTable === tbl.table_name;

                return (
                  <div key={tbl.table_name}>
                    {/* Table row — click to toggle selection */}
                    <button
                      className={`
                        w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                        transition-all duration-150 cursor-pointer bg-transparent border-none text-left
                        ${ts.selected
                          ? 'text-emerald-accent bg-emerald-accent/10 border border-emerald-accent/20'
                          : 'text-text-muted hover:text-text-bright hover:bg-surface-light border border-transparent'
                        }
                      `}
                      onClick={() => handleTableToggle(tbl.table_name, !ts.selected)}
                    >
                      <Table2 className={`h-4 w-4 shrink-0 ${ts.selected ? 'text-emerald-accent' : 'text-text-dim'}`} />
                      <span className="font-medium">{tbl.table_name}</span>
                      {ts.selected && totalCols > 0 && (
                        <Tag color={colCount === totalCols ? 'green' : 'orange'}>
                          {colCount}/{totalCols} col
                        </Tag>
                      )}
                      {tbl.has_visit && (
                        <Tag color="purple" className="text-[10px]">visit</Tag>
                      )}
                      {ts.selected && (
                        <span
                          className="ml-auto text-text-dim hover:text-text-bright"
                          onClick={(e) => {
                            e.stopPropagation();
                            setExpandedTable(isExpanded ? null : tbl.table_name);
                          }}
                        >
                          <ChevronRight
                            className={`h-4 w-4 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                          />
                        </span>
                      )}
                    </button>

                    {/* Columns panel — only when selected + expanded */}
                    {ts.selected && isExpanded && (
                      <div className="ml-7 px-3 py-2.5 mb-1 rounded-lg bg-surface-dark/50 border border-glass-border/50">
                        {ts.loading ? (
                          <Spinner size="small" />
                        ) : ts.columns.length === 0 ? (
                          <p className="text-sm text-text-dim">
                            {t('datamanagement.loading_columns', 'Loading columns...')}
                          </p>
                        ) : (
                          <div className="space-y-2">
                            <Checkbox
                              checked={colCount === totalCols}
                              indeterminate={colCount > 0 && colCount < totalCols}
                              onChange={(checked) => handleSelectAllColumns(tbl.table_name, checked)}
                            >
                              <span className="font-medium text-xs">
                                {t('datamanagement.select_all', 'Select All')}
                              </span>
                            </Checkbox>
                            <div className="flex flex-wrap gap-x-3 gap-y-1">
                              {ts.columns.map((col) => (
                                <Tooltip key={col.column_name} title={col.data_type}>
                                  <span>
                                    <Checkbox
                                      checked={ts.selectedColumns.has(col.column_name)}
                                      onChange={(checked) =>
                                        handleColumnToggle(tbl.table_name, col.column_name, checked)
                                      }
                                    >
                                      <span className="text-xs">{col.column_name}</span>
                                    </Checkbox>
                                  </span>
                                </Tooltip>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Step 3: Extract Dataset */}
      <Card
        size="small"
        title={
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
            <span>{t('datamanagement.step3_title', 'Extract Dataset')}</span>
          </div>
        }
      >
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-3">
            {loading ? (
              <Button
                variant="danger"
                size="small"
                icon={<X className="h-4 w-4" />}
                onClick={handleCancel}
              >
                {t('common.cancel', 'Cancel')}
              </Button>
            ) : (
              <>
                <Button
                  variant="primary"
                  onClick={handlePreview}
                  disabled={!canExtract || previewLoading}
                  loading={previewLoading}
                  icon={<Eye className="h-4 w-4" />}
                >
                  {previewData
                    ? t('datamanagement.re_preview', 'Re-preview')
                    : t('datamanagement.preview', 'Preview')}
                </Button>
                <Button
                  onClick={handleExtract}
                  disabled={!canExtract}
                  icon={<Download className="h-4 w-4" />}
                  className="!bg-emerald-600 hover:!bg-emerald-500"
                >
                  {t('datamanagement.extract_csv', 'Extract CSV')}
                </Button>
              </>
            )}
            {completedTaskId && !loading && (
              <Button
                variant="primary"
                onClick={handleDownload}
                icon={<Download className="h-4 w-4" />}
                className="!bg-emerald-600 hover:!bg-emerald-500"
              >
                {t('datamanagement.download_csv', 'Download CSV')}
              </Button>
            )}
          </div>

          {!canExtract && !loading && !previewData && (
            <p className="text-xs text-text-dim">
              {!cohortIdNum
                ? t('datamanagement.hint_select_cohort', 'Select a cohort to begin.')
                : t('datamanagement.hint_select_tables', 'Select at least one table with columns to extract.')}
            </p>
          )}

          {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

          {/* Progress bar */}
          {loading && (
            <div className="text-center py-6">
              <Spinner size="large" />
              <div className="mt-4 space-y-2">
                <span className="text-text-muted text-sm">
                  {t('datamanagement.extracting', 'Extracting dataset...')}
                </span>
                {progressTotal > 0 && (
                  <div className="max-w-xs mx-auto space-y-1">
                    <Progress
                      percent={progressPct}
                      size="small"
                      strokeColor="#10B981"
                    />
                    <div className="text-xs text-text-dim">
                      {currentStep} ({progressCompleted}/{progressTotal})
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {previewData && !loading && (
            <>
              <div className="h-px bg-glass-border" />

              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-text-bright">
                  {t('datamanagement.total_rows', 'Total rows')}: {previewData.total_count.toLocaleString()}
                </span>
                <span className="text-xs text-text-dim">
                  ({t('datamanagement.showing', 'showing')} {Math.min(previewData.rows.length, 50)})
                </span>
              </div>

              <div className="overflow-auto max-h-[420px] rounded-xl border border-glass-border">
                <Table
                  dataSource={previewData.rows.map((r, i) => ({ ...r, _key: String(i) }))}
                  rowKey="_key"
                  columns={previewData.columns.map(
                    (col): Column<Record<string, any>> => ({
                      key: col,
                      title: col,
                      dataIndex: col,
                      width: 150,
                      ellipsis: true,
                      render: (val: any) =>
                        val === null ? (
                          <span className="text-text-dim italic">NULL</span>
                        ) : (
                          String(val)
                        ),
                    }),
                  )}
                  size="small"
                  pagination={false}
                  scroll={{ x: true }}
                />
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

// ---------- Step badge sub-component ----------

function StepBadge({ step, active, done }: { step: number; active: boolean; done: boolean }) {
  const base = 'inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold';
  if (done) {
    return <span className={`${base} bg-emerald-500/20 text-emerald-400 border border-emerald-500/30`}>{step}</span>;
  }
  if (active) {
    return <span className={`${base} bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 animate-pulse`}>{step}</span>;
  }
  return <span className={`${base} bg-surface-light text-text-dim border border-glass-border`}>{step}</span>;
}
