import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import {
  Card,
  Button,
  Select,
  Switch,
  Checkbox,
  Tag,
  Spinner,
  Empty,
  Alert,
  Tooltip,
  Progress,
  Modal,
  Input,
  useToast,
} from '../components/ui';
import {
  Database,
  Download,
  Table2,
  ChevronRight,
  Info,
  Users,
  Columns3,
  FileArchive,
  Link2,
  X,
  Search,
  RotateCcw,
  ClipboardList,
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

interface SchemaTable {
  name: string;
  columns: { name: string; data_type?: string; selected: boolean }[];
  pk: string;
}

interface SchemaRelationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
}

interface SchemaData {
  tables: SchemaTable[];
  relationships: SchemaRelationship[];
}

interface ExtractionResult {
  table_row_counts: Record<string, number>;
  total_rows: number;
  num_tables: number;
  cohort_name: string;
}

interface Props {
  selectedCdm: string | null;
}

// Default columns to pre-select per OMOP table
const _DEFAULT_COLUMNS: Record<string, Set<string>> = {
  person: new Set([
    'person_id', 'gender_concept_id', 'year_of_birth', 'month_of_birth',
    'day_of_birth', 'birth_datetime', 'death_datetime', 'person_source_value',
  ]),
  visit_occurrence: new Set([
    'visit_occurrence_id', 'person_id', 'visit_concept_id', 'visit_start_date',
    'visit_end_date', 'visit_source_value', 'admitted_from_concept_id',
    'discharged_to_concept_id',
  ]),
  condition_occurrence: new Set([
    'condition_occurrence_id', 'person_id', 'visit_occurrence_id',
    'condition_concept_id', 'condition_start_date', 'condition_end_date',
    'condition_source_value', 'condition_status_concept_id',
  ]),
  drug_exposure: new Set([
    'drug_exposure_id', 'person_id', 'visit_occurrence_id', 'drug_concept_id',
    'drug_exposure_start_date', 'drug_exposure_end_date', 'drug_source_value',
    'quantity', 'days_supply', 'route_concept_id',
  ]),
  measurement: new Set([
    'measurement_id', 'person_id', 'visit_occurrence_id', 'measurement_concept_id',
    'measurement_date', 'value_as_number', 'value_as_concept_id', 'unit_concept_id',
    'measurement_source_value', 'range_low', 'range_high',
  ]),
  observation: new Set([
    'observation_id', 'person_id', 'visit_occurrence_id', 'observation_concept_id',
    'observation_date', 'value_as_number', 'value_as_string', 'value_as_concept_id',
    'unit_concept_id', 'observation_source_value',
  ]),
  procedure_occurrence: new Set([
    'procedure_occurrence_id', 'person_id', 'visit_occurrence_id',
    'procedure_concept_id', 'procedure_date', 'procedure_end_date',
    'procedure_source_value', 'quantity',
  ]),
  device_exposure: new Set([
    'device_exposure_id', 'person_id', 'visit_occurrence_id', 'device_concept_id',
    'device_exposure_start_date', 'device_exposure_end_date', 'device_source_value',
    'quantity',
  ]),
  death: new Set([
    'person_id', 'death_date', 'cause_concept_id', 'cause_source_value',
  ]),
  observation_period: new Set([
    'observation_period_id', 'person_id', 'observation_period_start_date',
    'observation_period_end_date',
  ]),
};

const MINIMAL_PRESET = ['person', 'visit_occurrence'];

// ---------- Column grouping ----------

type ColumnGroupKey = 'ids' | 'dates' | 'concepts' | 'source' | 'other';

const COLUMN_GROUP_ORDER: ColumnGroupKey[] = ['ids', 'dates', 'concepts', 'source', 'other'];

function columnGroup(name: string): ColumnGroupKey {
  const n = name.toLowerCase();
  if (n.includes('source')) return 'source';
  if (n.includes('concept')) return 'concepts';
  if (n.includes('date') || n.includes('time')) return 'dates';
  if (n.endsWith('_id')) return 'ids';
  return 'other';
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
  const [progressTotal, setProgressTotal] = useSessionState('data:progTotal', 0);
  const [currentStep, setCurrentStep] = useSessionState('data:step', '');

  // ── Result state (persisted) ──
  const [extractionResult, setExtractionResult] = useSessionState<ExtractionResult | null>('data:extractResult', null);
  const [completedTaskId, setCompletedTaskId] = useSessionState<string | null>('data:completedTaskId', null);
  const [error, setError] = useState('');

  // ── Schema state ──
  const [schemaData, setSchemaData] = useSessionState<SchemaData | null>('data:schema', null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaOpen, setSchemaOpen] = useState(false);

  // ── Filters / expansion ──
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [tableFilter, setTableFilter] = useState('');
  const [columnFilter, setColumnFilter] = useState('');

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
          setExtractionResult(resp.data.result);
          setCompletedTaskId(tid);
          setLoading(false);
          setTaskId(null);
          setProgressCompleted(0);
          setProgressTotal(0);
          setCurrentStep('');
          stopPolling();
          toast.success(
            `${t('datamanagement.extraction_complete', 'Extraction complete')} — ${resp.data.result.total_rows.toLocaleString()} ${t('datamanagement.rows', 'rows')} (${resp.data.result.num_tables} tables)`
          );
        } else if (resp.data.status === 'error') {
          setError(resp.data.error || 'Extraction failed');
          setLoading(false);
          setTaskId(null);
          setProgressCompleted(0);
          setProgressTotal(0);
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
          dataManagementApi.extractStatus(resp.data.task_id).then(r => {
            if (r.data.result) {
              setExtractionResult(r.data.result);
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

    if (!mountedRef.current) {
      mountedRef.current = true;
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

    if (cdmChanged) {
      setSelectedCohortId(null);
      setExtractionResult(null);
      setCompletedTaskId(null);
      setSchemaData(null);
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

  // Reset sameVisitOnly when cohort actually changes
  const prevCohortRef = useRef<string | null>(selectedCohortId);
  useEffect(() => {
    if (prevCohortRef.current === selectedCohortId) return;
    prevCohortRef.current = selectedCohortId;
    setSameVisitOnly(false);
    setExtractionResult(null);
    setCompletedTaskId(null);
  }, [selectedCohortId]);

  // ── Column fetching ──

  const fetchColumnsFor = useCallback((tableName: string) => {
    if (!selectedCdm) return;
    dataManagementApi
      .listColumns(selectedCdm, tableName)
      .then((res) => {
        const cols: ColumnInfo[] = res.data.columns ?? [];
        const preset = _DEFAULT_COLUMNS[tableName];
        const selected = preset
          ? new Set(cols.filter((c) => preset.has(c.column_name)).map((c) => c.column_name))
          : new Set(cols.map((c) => c.column_name));
        setTableState((p) => ({
          ...p,
          [tableName]: { ...p[tableName], columns: cols, selectedColumns: selected, loading: false },
        }));
      })
      .catch(() => {
        setTableState((p) => ({
          ...p,
          [tableName]: { ...p[tableName], loading: false },
        }));
      });
  }, [selectedCdm]);

  // Select/deselect a table (checkbox). Selecting loads columns and expands;
  // deselecting collapses but keeps the column configuration in memory.
  const handleTableToggle = useCallback(
    (tableName: string, checked: boolean) => {
      if (!selectedCdm) return;
      const needsFetch = checked && (tableState[tableName]?.columns.length ?? 0) === 0;

      setTableState((prev) => ({
        ...prev,
        [tableName]: { ...prev[tableName], selected: checked, loading: needsFetch ? true : prev[tableName]?.loading },
      }));

      if (needsFetch) fetchColumnsFor(tableName);
      if (checked) {
        setExpandedTable(tableName);
        setColumnFilter('');
      } else if (expandedTable === tableName) {
        setExpandedTable(null);
      }
      // Clear schema when selection changes
      setSchemaData(null);
    },
    [selectedCdm, tableState, expandedTable, fetchColumnsFor],
  );

  // Row click: select if not selected, otherwise toggle expansion.
  // Deselection only happens through the checkbox — no accidental config loss.
  const handleRowClick = (tableName: string) => {
    const ts = tableState[tableName];
    if (!ts?.selected) {
      handleTableToggle(tableName, true);
    } else {
      setColumnFilter('');
      setExpandedTable(expandedTable === tableName ? null : tableName);
    }
  };

  // ── Presets ──

  const applyPreset = (names: string[]) => {
    const wanted = new Set(names.filter((n) => tables.some((tbl) => tbl.table_name === n)));
    setTableState((prev) => {
      const next: TableColumnState = { ...prev };
      for (const tbl of tables) {
        const st = next[tbl.table_name];
        if (!st) continue;
        const sel = wanted.has(tbl.table_name);
        next[tbl.table_name] = {
          ...st,
          selected: sel,
          loading: sel && st.columns.length === 0 ? true : st.loading,
        };
      }
      return next;
    });
    for (const name of wanted) {
      if ((tableState[name]?.columns.length ?? 0) === 0) fetchColumnsFor(name);
    }
    setExpandedTable(null);
    setSchemaData(null);
  };

  const handleColumnToggle = (tableName: string, colName: string, checked: boolean) => {
    setTableState((prev) => {
      const ts = { ...prev[tableName] };
      const next = new Set(ts.selectedColumns);
      if (checked) next.add(colName);
      else next.delete(colName);
      return { ...prev, [tableName]: { ...ts, selectedColumns: next } };
    });
    setSchemaData(null);
  };

  const handleSelectAllColumns = (tableName: string, checked: boolean) => {
    setTableState((prev) => {
      const ts = { ...prev[tableName] };
      const next = checked ? new Set(ts.columns.map((c) => c.column_name)) : new Set<string>();
      return { ...prev, [tableName]: { ...ts, selectedColumns: next } };
    });
    setSchemaData(null);
  };

  const handleResetDefaultColumns = (tableName: string) => {
    setTableState((prev) => {
      const ts = { ...prev[tableName] };
      const preset = _DEFAULT_COLUMNS[tableName];
      const next = preset
        ? new Set(ts.columns.filter((c) => preset.has(c.column_name)).map((c) => c.column_name))
        : new Set(ts.columns.map((c) => c.column_name));
      return { ...prev, [tableName]: { ...ts, selectedColumns: next } };
    });
    setSchemaData(null);
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
  const selectedTables = tables.filter((tbl) => tableState[tbl.table_name]?.selected);
  const selectedTableCount = selectedTables.length;
  const totalSelectedColumns = selectedTables.reduce(
    (acc, tbl) => acc + (tableState[tbl.table_name]?.selectedColumns.size ?? 0),
    0,
  );

  const visibleTables = useMemo(() => {
    const f = tableFilter.trim().toLowerCase();
    if (!f) return tables;
    return tables.filter((tbl) => tbl.table_name.toLowerCase().includes(f));
  }, [tables, tableFilter]);

  // ── Load BDR schema (on demand, when the modal opens) ──
  const loadSchema = useCallback(async () => {
    if (!selectedCdm) return;
    const sels = getTableSelections();
    if (sels.length === 0) {
      setSchemaData(null);
      return;
    }
    setSchemaLoading(true);
    try {
      const resp = await dataManagementApi.extractSchema(selectedCdm, {
        table_selections: sels,
      });
      setSchemaData(resp.data);
    } catch {
      // Silent fail — schema is informational
    } finally {
      setSchemaLoading(false);
    }
  }, [selectedCdm, tableState]);

  const openSchema = () => {
    setSchemaOpen(true);
    if (!schemaData) loadSchema();
  };

  // ── Launch full extraction (background, builds ZIP) ──
  const handleExtract = async () => {
    if (!canExtract) return;
    setLoading(true);
    setError('');
    setCompletedTaskId(null);
    setExtractionResult(null);
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
    setProgressTotal(0);
    setCurrentStep('');
  };

  // ── Download ZIP ──
  const handleDownload = () => {
    if (!completedTaskId) return;
    const url = dataManagementApi.extractDownloadUrl(completedTaskId);
    authDownload(url);
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

  const groupLabels: Record<ColumnGroupKey, string> = {
    ids: t('datamanagement.col_group_ids', 'Identifiers'),
    dates: t('datamanagement.col_group_dates', 'Dates'),
    concepts: t('datamanagement.col_group_concepts', 'Concepts'),
    source: t('datamanagement.col_group_source', 'Source values'),
    other: t('datamanagement.col_group_other', 'Other'),
  };

  return (
    <div className="p-6 max-w-[1500px] space-y-5">
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

      <div className="flex flex-col lg:grid lg:grid-cols-12 gap-5 lg:items-start">
        {/* ── Left column: configuration ── */}
        <div className="w-full lg:col-span-8 space-y-5">
          {/* Cohort */}
          <Card
            size="small"
            title={
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-emerald-400" />
                <span>{t('datamanagement.step1_title', 'Select a Cohort')}</span>
              </div>
            }
          >
            <div className="p-4 space-y-3">
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
              {selectedCohort?.description && (
                <p className="text-sm text-text-dim">{selectedCohort.description}</p>
              )}
            </div>
          </Card>

          {/* Tables & columns */}
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
            <div className="p-4 space-y-3">
              {/* Toolbar: search + presets */}
              <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
                <div className="flex-1 min-w-0">
                  <Input
                    prefix={<Search className="h-3.5 w-3.5" />}
                    placeholder={t('datamanagement.filter_tables', 'Filter tables...')}
                    value={tableFilter}
                    onChange={(e) => setTableFilter(e.target.value)}
                  />
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs text-text-dim mr-0.5">
                    {t('datamanagement.presets', 'Presets')}:
                  </span>
                  <Button size="small" onClick={() => applyPreset(Object.keys(_DEFAULT_COLUMNS))}>
                    {t('datamanagement.preset_standard', 'Standard')}
                  </Button>
                  <Button size="small" onClick={() => applyPreset(MINIMAL_PRESET)}>
                    {t('datamanagement.preset_minimal', 'Minimal')}
                  </Button>
                  <Button size="small" onClick={() => applyPreset(tables.map((tbl) => tbl.table_name))}>
                    {t('datamanagement.preset_all', 'All')}
                  </Button>
                  <Tooltip title={t('datamanagement.preset_none', 'Clear selection')}>
                    <span>
                      <Button
                        size="small"
                        icon={<X className="h-3.5 w-3.5" />}
                        onClick={() => applyPreset([])}
                        aria-label={t('datamanagement.preset_none', 'Clear selection')}
                      />
                    </span>
                  </Tooltip>
                </div>
              </div>

              {loadingTables ? (
                <Spinner size="small" tip="Loading tables..." />
              ) : tables.length === 0 ? (
                <Empty description={t('datamanagement.no_tables', 'No tables found')} />
              ) : (
                <div className="space-y-1">
                  {visibleTables.map((tbl) => {
                    const ts = tableState[tbl.table_name];
                    if (!ts) return null;
                    const colCount = ts.selectedColumns.size;
                    const totalCols = ts.columns.length;
                    const isExpanded = expandedTable === tbl.table_name;

                    // Group + filter visible columns for the expanded panel
                    const colFilter = columnFilter.trim().toLowerCase();
                    const filteredCols = colFilter
                      ? ts.columns.filter((c) => c.column_name.toLowerCase().includes(colFilter))
                      : ts.columns;
                    const grouped: Record<ColumnGroupKey, ColumnInfo[]> = {
                      ids: [], dates: [], concepts: [], source: [], other: [],
                    };
                    if (isExpanded) {
                      for (const col of filteredCols) grouped[columnGroup(col.column_name)].push(col);
                    }

                    return (
                      <div key={tbl.table_name}>
                        <div
                          role="button"
                          tabIndex={0}
                          className={`
                            w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                            transition-all duration-150 cursor-pointer text-left
                            ${ts.selected
                              ? 'text-emerald-accent bg-emerald-accent/10 border border-emerald-accent/20'
                              : 'text-text-muted hover:text-text-bright hover:bg-surface-light border border-transparent'
                            }
                          `}
                          onClick={() => handleRowClick(tbl.table_name)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              handleRowClick(tbl.table_name);
                            }
                          }}
                        >
                          <span onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              checked={ts.selected}
                              onChange={(checked) => handleTableToggle(tbl.table_name, checked)}
                            />
                          </span>
                          <Table2 className={`h-4 w-4 shrink-0 ${ts.selected ? 'text-emerald-accent' : 'text-text-dim'}`} />
                          <span className="font-medium">{tbl.table_name}</span>
                          {ts.selected && totalCols > 0 && (
                            <Tag color={colCount === totalCols ? 'green' : colCount === 0 ? 'red' : 'orange'}>
                              {colCount}/{totalCols} col
                            </Tag>
                          )}
                          {tbl.has_visit && (
                            <Tag color="purple" className="text-[10px]">visit</Tag>
                          )}
                          {ts.selected && (
                            <span className="ml-auto text-text-dim">
                              <ChevronRight
                                className={`h-4 w-4 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                              />
                            </span>
                          )}
                        </div>

                        {ts.selected && isExpanded && (
                          <div className="ml-7 px-3 py-2.5 mb-1 rounded-lg bg-surface-dark/50 border border-glass-border/50">
                            {ts.loading ? (
                              <Spinner size="small" />
                            ) : ts.columns.length === 0 ? (
                              <p className="text-sm text-text-dim">
                                {t('datamanagement.loading_columns', 'Loading columns...')}
                              </p>
                            ) : (
                              <div className="space-y-3">
                                {/* Column toolbar */}
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="flex-1 min-w-[160px]">
                                    <Input
                                      prefix={<Search className="h-3 w-3" />}
                                      placeholder={t('datamanagement.filter_columns', 'Filter columns...')}
                                      value={columnFilter}
                                      onChange={(e) => setColumnFilter(e.target.value)}
                                    />
                                  </div>
                                  <Button size="small" onClick={() => handleSelectAllColumns(tbl.table_name, true)}>
                                    {t('datamanagement.select_all', 'Select All')}
                                  </Button>
                                  <Button size="small" onClick={() => handleSelectAllColumns(tbl.table_name, false)}>
                                    {t('datamanagement.select_none', 'None')}
                                  </Button>
                                  <Button
                                    size="small"
                                    icon={<RotateCcw className="h-3 w-3" />}
                                    onClick={() => handleResetDefaultColumns(tbl.table_name)}
                                  >
                                    {t('datamanagement.reset_default', 'Default')}
                                  </Button>
                                </div>

                                {/* Grouped columns */}
                                {COLUMN_GROUP_ORDER.map((gk) =>
                                  grouped[gk].length === 0 ? null : (
                                    <div key={gk}>
                                      <div className="text-[11px] uppercase tracking-wide text-text-dim mb-1">
                                        {groupLabels[gk]}
                                      </div>
                                      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-x-3 gap-y-1">
                                        {grouped[gk].map((col) => (
                                          <Checkbox
                                            key={col.column_name}
                                            checked={ts.selectedColumns.has(col.column_name)}
                                            onChange={(checked) =>
                                              handleColumnToggle(tbl.table_name, col.column_name, checked)
                                            }
                                          >
                                            <span className="text-xs">{col.column_name}</span>
                                            <span className="text-[10px] text-text-dim ml-1.5">{col.data_type}</span>
                                          </Checkbox>
                                        ))}
                                      </div>
                                    </div>
                                  ),
                                )}
                                {colFilter && filteredCols.length === 0 && (
                                  <p className="text-xs text-text-dim">
                                    {t('datamanagement.no_columns_match', 'No columns match the filter.')}
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {tableFilter && visibleTables.length === 0 && (
                    <p className="text-sm text-text-dim px-3 py-2">
                      {t('datamanagement.no_tables_match', 'No tables match the filter.')}
                    </p>
                  )}
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* ── Right column: sticky summary ── */}
        <div className="w-full lg:col-span-4 lg:sticky lg:top-2">
          <Card
            size="small"
            title={
              <div className="flex items-center gap-2">
                <ClipboardList className="h-4 w-4 text-emerald-400" />
                <span>{t('datamanagement.summary_title', 'Summary')}</span>
              </div>
            }
          >
            <div className="p-4 space-y-4">
              {/* Cohort */}
              {!selectedCohort ? (
                <p className="text-xs text-text-dim">
                  {t('datamanagement.hint_select_cohort', 'Select a cohort to begin.')}
                </p>
              ) : (
                <div className="space-y-2">
                  <div className="text-sm font-semibold text-text-bright truncate">
                    {selectedCohort.name}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {selectedCohort.patient_count != null && (
                      <Tag color="blue">
                        <Users className="h-3 w-3 mr-1 inline" />
                        {selectedCohort.patient_count.toLocaleString()} patients
                      </Tag>
                    )}
                    {selectedCohort.latest_version && (
                      <Tag color="purple">v{selectedCohort.latest_version}</Tag>
                    )}
                    <Tag color={selectedCohort.has_same_visit ? 'green' : 'default'}>
                      <Link2 className="h-3 w-3 mr-1 inline" />
                      {selectedCohort.has_same_visit ? 'Same Visit' : 'No Same Visit'}
                    </Tag>
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <Switch
                      checked={sameVisitOnly}
                      onChange={setSameVisitOnly}
                      disabled={!selectedCohort.has_same_visit}
                      size="small"
                    />
                    <span className="text-xs font-medium text-text-bright">
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
                        <Info className="h-3.5 w-3.5 text-text-dim" />
                      </span>
                    </Tooltip>
                  </div>
                </div>
              )}

              <div className="h-px bg-glass-border" />

              {/* Selections */}
              {selectedTableCount === 0 ? (
                <p className="text-xs text-text-dim">
                  {t('datamanagement.hint_select_tables', 'Select at least one table with columns to extract.')}
                </p>
              ) : (
                <div className="space-y-1.5">
                  <div className="text-xs font-semibold text-text-bright">
                    {selectedTableCount} tables · {totalSelectedColumns} {t('datamanagement.columns', 'columns')}
                  </div>
                  <div className="space-y-0.5 max-h-[220px] overflow-y-auto">
                    {selectedTables.map((tbl) => {
                      const ts = tableState[tbl.table_name];
                      const n = ts?.selectedColumns.size ?? 0;
                      return (
                        <button
                          key={tbl.table_name}
                          onClick={() => setExpandedTable(tbl.table_name)}
                          className="w-full flex items-center justify-between gap-2 px-2 py-1 rounded-md text-xs cursor-pointer bg-transparent border-none text-left hover:bg-surface-light transition-colors"
                        >
                          <span className="truncate text-text-muted">{tbl.table_name}</span>
                          <span className={`shrink-0 ${n === 0 ? 'text-red-400' : 'text-text-dim'}`}>
                            {n} col
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <Button
                    size="small"
                    block
                    icon={<Database className="h-3.5 w-3.5" />}
                    onClick={openSchema}
                    disabled={getTableSelections().length === 0}
                  >
                    {t('datamanagement.view_schema', 'View schema')}
                  </Button>
                </div>
              )}

              <div className="h-px bg-glass-border" />

              {/* Extract / progress / result */}
              <div className="space-y-3">
                {loading ? (
                  <>
                    <Button
                      variant="danger"
                      block
                      icon={<X className="h-4 w-4" />}
                      onClick={handleCancel}
                    >
                      {t('common.cancel', 'Cancel')}
                    </Button>
                    <div className="space-y-1.5">
                      <div className="text-xs text-text-muted text-center">
                        {t('datamanagement.extracting', 'Extracting dataset...')}
                      </div>
                      {progressTotal > 0 && (
                        <>
                          <Progress percent={progressPct} size="small" strokeColor="#10B981" />
                          <div className="text-[11px] text-text-dim text-center">
                            {currentStep} ({progressCompleted}/{progressTotal})
                          </div>
                        </>
                      )}
                    </div>
                  </>
                ) : (
                  <Button
                    block
                    onClick={handleExtract}
                    disabled={!canExtract}
                    icon={<FileArchive className="h-4 w-4" />}
                    className="!bg-emerald-600 hover:!bg-emerald-500"
                  >
                    {t('datamanagement.extract_zip', 'Extract ZIP')}
                  </Button>
                )}

                {completedTaskId && !loading && (
                  <Button
                    variant="primary"
                    block
                    onClick={handleDownload}
                    icon={<Download className="h-4 w-4" />}
                    className="!bg-emerald-600 hover:!bg-emerald-500"
                  >
                    {t('datamanagement.download_zip', 'Download ZIP')}
                  </Button>
                )}

                {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

                {extractionResult && !loading && (
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Tag color="green">
                        {extractionResult.total_rows.toLocaleString()} {t('datamanagement.rows', 'rows')}
                      </Tag>
                      <Tag color="blue">{extractionResult.num_tables} tables</Tag>
                    </div>
                    <div className="space-y-0.5 max-h-[180px] overflow-y-auto">
                      {Object.entries(extractionResult.table_row_counts).map(([tbl, count]) => (
                        <div
                          key={tbl}
                          className="flex items-center justify-between gap-2 px-2 py-1 rounded-md bg-surface-dark border border-glass-border"
                        >
                          <span className="text-xs font-medium text-text-bright truncate">{tbl}</span>
                          <span className="text-xs text-text-dim shrink-0">{count.toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Relational schema modal */}
      <Modal
        open={schemaOpen}
        onClose={() => setSchemaOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-emerald-400" />
            <span>{t('datamanagement.schema_title', 'Relational Schema')}</span>
            {schemaData && (
              <Tag color="blue">
                {schemaData.tables.length} tables · {schemaData.relationships.length} relations
              </Tag>
            )}
          </div>
        }
        width="max-w-6xl"
      >
        {schemaLoading ? (
          <div className="text-center py-10">
            <Spinner size="large" tip="Loading schema..." />
          </div>
        ) : schemaData ? (
          <BdrDiagram schema={schemaData} />
        ) : (
          <Empty description={t('datamanagement.hint_select_tables', 'Select at least one table with columns to extract.')} />
        )}
      </Modal>
    </div>
  );
}

// ---------- BDR Diagram sub-component ----------

function BdrDiagram({ schema }: { schema: SchemaData }) {
  const TABLE_W = 220;
  const COL_H = 18;
  const HEADER_H = 32;
  const PAD = 10;
  const MARGIN = 40;

  // Track which tables are expanded (show all columns)
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  // Determine which columns are "key" columns (PK or FK) per table
  const keyColumns = useMemo(() => {
    const map: Record<string, Set<string>> = {};
    for (const tbl of schema.tables) {
      const keys = new Set<string>();
      keys.add(tbl.pk);
      for (const r of schema.relationships) {
        if (r.from_table === tbl.name) keys.add(r.from_column);
        if (r.to_table === tbl.name) keys.add(r.to_column);
      }
      map[tbl.name] = keys;
    }
    return map;
  }, [schema]);

  // Visible columns per table: keys only when collapsed, all when expanded
  const visibleColumns = useMemo(() => {
    return schema.tables.map((tbl) => {
      if (expanded.has(tbl.name)) return tbl.columns;
      const keys = keyColumns[tbl.name] || new Set();
      return tbl.columns.filter((c) => keys.has(c.name));
    });
  }, [schema.tables, expanded, keyColumns]);

  // Heights depend on visible columns
  const tableHeights = useMemo(
    () => visibleColumns.map((cols) => HEADER_H + cols.length * COL_H + PAD * 2),
    [visibleColumns],
  );

  // ── Radial hub layout ──
  const tablePositions = useMemo(() => {
    const n = schema.tables.length;
    if (n === 0) return [];

    // Hub priority: person is always #1 hub, visit_occurrence #2.
    // After that, sort by actual degree.
    const HUB_PRIORITY: Record<string, number> = {
      person: 10000,
      visit_occurrence: 5000,
    };

    const degree: Record<string, number> = {};
    for (const t of schema.tables) degree[t.name] = 0;
    for (const r of schema.relationships) {
      degree[r.from_table] = (degree[r.from_table] || 0) + 1;
      degree[r.to_table] = (degree[r.to_table] || 0) + 1;
    }

    const sorted = schema.tables
      .map((t, i) => ({
        name: t.name,
        idx: i,
        deg: (HUB_PRIORITY[t.name] || 0) + (degree[t.name] || 0),
      }))
      .sort((a, b) => b.deg - a.deg);

    if (n === 1) {
      return [{ x: MARGIN, y: MARGIN, w: TABLE_W, h: tableHeights[0] }];
    }
    if (n === 2) {
      const gap = 120;
      return schema.tables.map((_, i) => ({
        x: MARGIN + i * (TABLE_W + gap),
        y: MARGIN,
        w: TABLE_W,
        h: tableHeights[i],
      }));
    }

    const hubs = sorted.filter((s) => s.deg > 0).slice(0, Math.min(2, n));
    const satellites = sorted.filter((s) => !hubs.some((h) => h.idx === s.idx));

    const maxH = Math.max(...tableHeights);
    const ringRadius = Math.max(
      (satellites.length * (TABLE_W + 30)) / (2 * Math.PI),
      maxH + 60,
      200,
    );

    const cx = ringRadius + TABLE_W / 2 + MARGIN;
    const cy = ringRadius + maxH / 2 + MARGIN;

    const positions: { x: number; y: number; w: number; h: number }[] = new Array(n);

    if (hubs.length === 1) {
      positions[hubs[0].idx] = {
        x: cx - TABLE_W / 2,
        y: cy - tableHeights[hubs[0].idx] / 2,
        w: TABLE_W,
        h: tableHeights[hubs[0].idx],
      };
    } else if (hubs.length >= 2) {
      const gap = 80;
      positions[hubs[0].idx] = {
        x: cx - TABLE_W - gap / 2,
        y: cy - tableHeights[hubs[0].idx] / 2,
        w: TABLE_W,
        h: tableHeights[hubs[0].idx],
      };
      positions[hubs[1].idx] = {
        x: cx + gap / 2,
        y: cy - tableHeights[hubs[1].idx] / 2,
        w: TABLE_W,
        h: tableHeights[hubs[1].idx],
      };
    }

    if (satellites.length > 0) {
      const startAngle = -Math.PI / 2;
      satellites.forEach((sat, i) => {
        const angle = startAngle + (2 * Math.PI * i) / satellites.length;
        positions[sat.idx] = {
          x: cx + ringRadius * Math.cos(angle) - TABLE_W / 2,
          y: cy + ringRadius * Math.sin(angle) - tableHeights[sat.idx] / 2,
          w: TABLE_W,
          h: tableHeights[sat.idx],
        };
      });
    }

    let minX = Infinity, minY = Infinity;
    for (const p of positions) {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
    }
    const dx = MARGIN - minX;
    const dy = MARGIN - minY;
    for (const p of positions) { p.x += dx; p.y += dy; }

    return positions;
  }, [schema.tables, schema.relationships, tableHeights]);

  const totalW = useMemo(() => {
    if (tablePositions.length === 0) return 400;
    return Math.max(...tablePositions.map((p) => p.x + p.w)) + MARGIN;
  }, [tablePositions]);

  const totalH = useMemo(() => {
    if (tablePositions.length === 0) return 200;
    return Math.max(...tablePositions.map((p) => p.y + p.h)) + MARGIN;
  }, [tablePositions]);

  const tableIdx = useMemo(() => {
    const m: Record<string, number> = {};
    schema.tables.forEach((t, i) => (m[t.name] = i));
    return m;
  }, [schema.tables]);

  // ── Edges: FK row → FK row ──
  const lines = useMemo(() => {
    const portCounts: Record<string, number> = {};
    const getPort = (key: string): number => {
      const n = portCounts[key] || 0;
      portCounts[key] = n + 1;
      return n;
    };

    return schema.relationships
      .map((rel) => {
        const fromI = tableIdx[rel.from_table];
        const toI = tableIdx[rel.to_table];
        if (fromI == null || toI == null) return null;
        const from = tablePositions[fromI];
        const to = tablePositions[toI];

        // Find column index in the *visible* list
        const fromColIdx = visibleColumns[fromI].findIndex((c) => c.name === rel.from_column);
        const toColIdx = visibleColumns[toI].findIndex((c) => c.name === rel.to_column);

        const fromRowY =
          from.y + HEADER_H + PAD + Math.max(0, fromColIdx) * COL_H + COL_H / 2;
        const toRowY =
          to.y + HEADER_H + PAD + Math.max(0, toColIdx) * COL_H + COL_H / 2;

        const goRight = (from.x + from.w / 2) <= (to.x + to.w / 2);
        const exitX = goRight ? from.x + from.w : from.x;
        const enterX = goRight ? to.x : to.x + to.w;

        const portKey = `${fromI}:${goRight ? 'R' : 'L'}:${rel.from_column}`;
        const portKey2 = `${toI}:${goRight ? 'L' : 'R'}:${rel.to_column}`;
        const pOff1 = getPort(portKey) * 4;
        const pOff2 = getPort(portKey2) * 4;

        const fy = fromRowY + pOff1;
        const ty = toRowY + pOff2;

        const cpLen = Math.min(Math.max(Math.abs(enterX - exitX) * 0.4, 40), 100);
        const cp1x = exitX + (goRight ? cpLen : -cpLen);
        const cp2x = enterX + (goRight ? -cpLen : cpLen);

        const path = `M${exitX},${fy} C${cp1x},${fy} ${cp2x},${ty} ${enterX},${ty}`;
        return { path, rel };
      })
      .filter(Boolean) as { path: string; rel: SchemaRelationship }[];
  }, [schema, tablePositions, tableIdx, visibleColumns]);

  return (
    <div className="overflow-auto max-h-[70vh] rounded-xl border border-glass-border bg-[#0a1628]">
      <svg
        width={totalW}
        height={totalH}
        viewBox={`0 0 ${totalW} ${totalH}`}
        className="min-w-full"
      >
        <defs>
          <marker id="bdr-dot" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6">
            <circle cx="5" cy="5" r="3" fill="#10B981" opacity="0.8" />
          </marker>
          <marker id="bdr-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#10B981" opacity="0.7" />
          </marker>
        </defs>

        {/* Edges (behind) */}
        {lines.map((l, i) => (
          <path
            key={i}
            d={l.path}
            fill="none"
            stroke="#10B981"
            strokeWidth="1.5"
            strokeOpacity="0.45"
            strokeLinejoin="round"
            markerStart="url(#bdr-dot)"
            markerEnd="url(#bdr-arrow)"
          />
        ))}

        {/* Tables (on top) */}
        {schema.tables.map((tbl, i) => {
          const pos = tablePositions[i];
          const isOpen = expanded.has(tbl.name);
          const visCols = visibleColumns[i];
          const totalCols = tbl.columns.length;
          const hiddenCount = totalCols - visCols.length;

          return (
            <g key={tbl.name} transform={`translate(${pos.x},${pos.y})`}>
              {/* Background */}
              <rect
                width={pos.w}
                height={pos.h}
                rx="8"
                fill="#0d1f3c"
                stroke="#1e3a5f"
                strokeWidth="1"
              />
              {/* Header — clickable to toggle expand */}
              <rect
                width={pos.w}
                height={HEADER_H}
                rx="8"
                fill="#10B981"
                fillOpacity={0.12}
                className="cursor-pointer"
                onClick={() => toggleExpand(tbl.name)}
              />
              <rect
                y={HEADER_H - 8}
                width={pos.w}
                height={8}
                fill="#10B981"
                fillOpacity={0.12}
                className="cursor-pointer"
                onClick={() => toggleExpand(tbl.name)}
              />
              <text
                x={PAD}
                y={HEADER_H / 2 + 1}
                dominantBaseline="middle"
                className="text-[12px] font-bold cursor-pointer"
                fill="#10B981"
                onClick={() => toggleExpand(tbl.name)}
              >
                {tbl.name}
              </text>
              {/* Expand/collapse chevron */}
              <text
                x={pos.w - PAD}
                y={HEADER_H / 2 + 1}
                dominantBaseline="middle"
                textAnchor="end"
                fill="#64748b"
                className="text-[10px] cursor-pointer select-none"
                onClick={() => toggleExpand(tbl.name)}
              >
                {isOpen ? '▾' : `▸ +${hiddenCount}`}
              </text>

              {/* Columns */}
              {visCols.map((col, ci) => {
                const cy = HEADER_H + PAD + ci * COL_H;
                const isPk = col.name === tbl.pk;
                const isSelected = col.selected;
                const isFk = schema.relationships.some(
                  (r) =>
                    (r.from_table === tbl.name && r.from_column === col.name) ||
                    (r.to_table === tbl.name && r.to_column === col.name),
                );
                return (
                  <g key={col.name}>
                    {isSelected && (
                      <rect
                        x={2}
                        y={cy - 1}
                        width={pos.w - 4}
                        height={COL_H}
                        rx="3"
                        fill="#10B981"
                        fillOpacity="0.06"
                      />
                    )}
                    {isPk && (
                      <text x={PAD} y={cy + COL_H / 2} dominantBaseline="middle" fill="#f59e0b" className="text-[9px]">
                        PK
                      </text>
                    )}
                    {!isPk && isFk && (
                      <text x={PAD} y={cy + COL_H / 2} dominantBaseline="middle" fill="#38bdf8" className="text-[9px]">
                        FK
                      </text>
                    )}
                    <text
                      x={isPk || isFk ? PAD + 20 : PAD}
                      y={cy + COL_H / 2}
                      dominantBaseline="middle"
                      fill={isSelected ? '#e2e8f0' : '#64748b'}
                      className="text-[11px]"
                    >
                      {col.name}
                    </text>
                    {col.data_type && (
                      <text
                        x={pos.w - PAD}
                        y={cy + COL_H / 2}
                        dominantBaseline="middle"
                        textAnchor="end"
                        fill="#475569"
                        className="text-[9px]"
                      >
                        {col.data_type}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
