import { useState, useEffect, useRef, useCallback } from 'react';
import { useSessionState } from '../../hooks/useSessionState';
import {
  Card, Button, Alert, Empty, Tooltip, Switch, Statistic, Progress,
  Collapse, Table, Tag, Spinner, useToast,
} from '../../components/ui';
import type { Column } from '../../components/ui';
import {
  BarChart3, Users, Download, Check, X, Activity, Eye, Calendar, Hash,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { useChartTheme } from '../../hooks/useChartTheme';
import { cohortApi } from '../../api/client';
import type { CohortCriteria, CharacterizationResult } from '../../types';

const DOMAIN_COLORS: Record<string, string> = {
  Condition: '#f5222d',
  Drug: '#1890ff',
  Procedure: '#52c41a',
  Measurement: '#fa8c16',
  Observation: '#722ed1',
  Device: '#13c2c2',
  Visit: '#eb2f96',
};

const DOMAIN_TAG_COLORS: Record<string, 'red' | 'blue' | 'green' | 'orange' | 'purple' | 'cyan' | 'magenta' | 'default'> = {
  Condition: 'red',
  Drug: 'blue',
  Procedure: 'green',
  Measurement: 'orange',
  Observation: 'purple',
  Device: 'cyan',
  Visit: 'magenta',
};

const PIE_COLORS = ['#1890ff', '#f5222d', '#52c41a', '#fa8c16', '#722ed1', '#13c2c2', '#eb2f96', '#aaa'];

interface Props {
  cdmName: string;
  criteria: CohortCriteria;
  cohortId?: number;
  cohortKey?: string;
}

export default function CharacterizationPanel({ cdmName, criteria, cohortId, cohortKey = 'draft' }: Props) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const toast = useToast();
  const ck = cohortKey;
  const [result, setResult] = useSessionState<CharacterizationResult | null>(`cohort:char:result:${ck}`, null);
  const [loading, setLoading] = useSessionState(`cohort:char:loading:${ck}`, false);
  const [taskId, setTaskId] = useSessionState<string | null>(`cohort:char:taskId:${ck}`, null);
  const [progressCompleted, setProgressCompleted] = useSessionState(`cohort:char:progDone:${ck}`, 0);
  const [progressTotal, setProgressTotal] = useSessionState(`cohort:char:progTotal:${ck}`, 0);
  const [currentStep, setCurrentStep] = useSessionState(`cohort:char:step:${ck}`, '');
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [error, setError] = useState('');
  const [characterizedAt, setCharacterizedAt] = useSessionState<string | null>(`cohort:char:at:${ck}`, null);
  const [visitLevel, setVisitLevel] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasCriteria =
    criteria.inclusion.criteria.length > 0 ||
    criteria.demographics?.age ||
    criteria.demographics?.gender;

  const hasSameVisit = !!criteria.inclusion.sameVisit;

  // Stable key for criteria to avoid spurious resets on every render
  const criteriaKey = JSON.stringify(criteria);

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
        const resp = await cohortApi.characterizeStatus(tid);
        // Update progress
        if (resp.data.completed != null) setProgressCompleted(resp.data.completed);
        if (resp.data.total != null) setProgressTotal(resp.data.total);
        if (resp.data.current_step) setCurrentStep(resp.data.current_step);

        if (resp.data.status === 'completed' && resp.data.result) {
          setResult(resp.data.result);
          setCharacterizedAt(new Date().toISOString());
          setLoading(false);
          setTaskId(null);
          setProgressCompleted(0);
          setProgressTotal(0);
          setCurrentStep('');
          stopPolling();

          // Auto-save if cohort is saved
          if (cohortId) {
            try {
              await cohortApi.saveCharacterization(cohortId, resp.data.result);
            } catch { /* non-blocking */ }
          }
        } else if (resp.data.status === 'error') {
          setError(resp.data.error || 'Characterization failed');
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
  }, [stopPolling, cohortId]);

  // On mount: reconnect to running task if any
  useEffect(() => {
    if (taskId && loading) {
      startPolling(taskId);
    } else if (!taskId && loading) {
      // Check if there's a running task on the server
      cohortApi.characterizeActive().then(resp => {
        if (resp.data.task_id) {
          setTaskId(resp.data.task_id);
          startPolling(resp.data.task_id);
        } else {
          setLoading(false);
        }
      }).catch(() => setLoading(false));
    }
    return stopPolling;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear results when criteria change (but not on first mount if we have cached results)
  const prevCriteriaRef = useRef(criteriaKey);
  useEffect(() => {
    if (prevCriteriaRef.current !== criteriaKey) {
      prevCriteriaRef.current = criteriaKey;
      // Criteria changed — clear cached results
      if (!loading) {
        setResult(null);
        setCharacterizedAt(null);
      }
    }
  }, [criteriaKey]);

  // Load saved characterization if we have a cohortId and no result
  useEffect(() => {
    if (!cohortId || result || loading) return;
    let cancelled = false;
    setLoadingSaved(true);
    cohortApi.getCharacterization(cohortId).then(resp => {
      if (cancelled) return;
      if (resp.data.characterization) {
        setResult(resp.data.characterization);
        setCharacterizedAt(resp.data.characterized_at);
      }
    }).catch(() => {}).finally(() => {
      if (!cancelled) setLoadingSaved(false);
    });
    return () => { cancelled = true; };
  }, [cohortId]);

  const runCharacterization = async () => {
    if (!cdmName || !hasCriteria) return;

    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await cohortApi.characterize(cdmName, criteria, 25, undefined, visitLevel);
      const tid = resp.data.task_id;
      setTaskId(tid);
      startPolling(tid);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Characterization failed');
      setLoading(false);
    }
  };

  const stopCharacterization = () => {
    stopPolling();
    if (taskId) {
      cohortApi.characterizeCancel(taskId).catch(() => {});
    }
    setTaskId(null);
    setLoading(false);
  };

  const exportCsv = () => {
    if (!result) return;
    const lines: string[] = [];
    lines.push('Section,Variable,Value');

    // Demographics
    const demo = result.demographics;
    lines.push(`Demographics,Cohort Size,${result.cohort_size}`);
    lines.push(`Demographics,Mean Age,${demo.age.mean_age ?? ''}`);
    lines.push(`Demographics,SD Age,${demo.age.std_age ?? ''}`);
    lines.push(`Demographics,Median Age,${demo.age.median_age ?? ''}`);
    for (const g of demo.gender) lines.push(`Demographics,Gender: ${g.label},${g.count}`);
    for (const r of demo.race) lines.push(`Demographics,Race: ${r.label},${r.count}`);
    for (const e of demo.ethnicity) lines.push(`Demographics,Ethnicity: ${e.label},${e.count}`);

    // Domain prevalence
    for (const dp of result.domain_prevalence) {
      lines.push(`${dp.domain},Patients with data,${dp.patients_with_data} (${dp.pct_with_data}%)`);
      for (const c of dp.top_concepts) {
        lines.push(`${dp.domain},"${c.concept_name} [${c.concept_id}]",${c.n_persons} (${c.pct_persons}%)`);
      }
    }

    // Visit duration
    if (result.visit_duration?.n_visits) {
      const vd = result.visit_duration;
      lines.push(`Visit Duration,Overall,"mean=${vd.mean_days ?? ''} median=${vd.median_days ?? ''} SD=${vd.std_days ?? ''} range=${vd.min_days ?? ''}-${vd.max_days ?? ''} (${vd.n_visits} visits)"`);
      for (const bt of (vd.by_type || [])) {
        lines.push(`Visit Duration,"${bt.visit_type}","mean=${bt.mean_days ?? ''} median=${bt.median_days ?? ''} SD=${bt.std_days ?? ''} (${bt.n_visits} visits)"`);
      }
    }

    // Measurement stats
    for (const m of result.measurement_stats) {
      lines.push(`Measurements,"${m.concept_name}",mean=${m.mean_value ?? ''} SD=${m.std_value ?? ''} median=${m.median_value ?? ''} [${m.unit}]`);
    }

    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cohort_table1.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!hasCriteria) {
    return (
      <Card size="small">
        <Empty
          description={t('cohort.define_criteria_first', 'Define cohort criteria to run characterization')}
        />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <Card size="small">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-[18px] w-[18px] text-text-muted" />
            <h5 className="text-sm font-semibold text-text-bright m-0">Table 1 — Cohort Characterization</h5>
          </div>
          <div className="flex items-center gap-2">
            {hasSameVisit && (
              <Tooltip title={
                visitLevel
                  ? t('cohort.visit_level_on', 'Clinical data restricted to the qualifying visit only')
                  : t('cohort.visit_level_off', 'All patient data across all visits (standard)')
              }>
                <div className="flex items-center gap-1">
                  <Switch
                    size="small"
                    checked={visitLevel}
                    onChange={setVisitLevel}
                  />
                  <span className="text-text-muted text-[11px]">
                    {t('cohort.visit_level', 'Visit-level')}
                  </span>
                </div>
              </Tooltip>
            )}
            {characterizedAt && (
              <Tooltip title={`Last run: ${new Date(characterizedAt).toLocaleString()}`}>
                <span><Check className="h-3.5 w-3.5 text-emerald-400" /></span>
              </Tooltip>
            )}
            {result && (
              <Button size="small" icon={<Download className="h-3.5 w-3.5" />} onClick={exportCsv}>
                CSV
              </Button>
            )}
            {loading ? (
              <Button
                variant="danger"
                size="small"
                icon={<X className="h-3.5 w-3.5" />}
                onClick={stopCharacterization}
              >
                {t('common.stop', 'Stop')}
              </Button>
            ) : (
              <Button
                variant="primary"
                size="small"
                onClick={runCharacterization}
                disabled={!hasCriteria || !cdmName}
              >
                {result ? t('cohort.refresh', 'Refresh') : t('cohort.run_characterization', 'Run Characterization')}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {(loading || loadingSaved) && (
        <Card size="small">
          <div className="text-center py-8">
            <Spinner size="large" />
            <div className="mt-4 space-y-2">
              <span className="text-text-muted text-sm">
                {loadingSaved ? t('cohort.loading_saved', 'Loading saved results...') : 'Running characterization queries...'}
              </span>
              {loading && progressTotal > 0 && (
                <div className="max-w-xs mx-auto space-y-1">
                  <Progress
                    percent={Math.round((progressCompleted / progressTotal) * 100)}
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
        </Card>
      )}

      {result && !loading && (
        <>
          {/* Visit-level indicator */}
          {(result as any).visit_level && (
            <Alert
              type="info"
              showIcon
              message={t('cohort.visit_level_active', 'Visit-level characterization — clinical data restricted to qualifying visits only. Demographics remain patient-level.')}
              className="text-xs"
            />
          )}

          {/* Cohort Size */}
          <Card size="small">
            <Statistic
              title={<div className="flex items-center gap-1"><Users className="h-3.5 w-3.5" />{t('cohort.cohort_size', 'Cohort Size')}</div>}
              value={result.cohort_size?.toLocaleString()}
              valueStyle={{ color: ct.blue, fontSize: 28 }}
              suffix="patients"
            />
          </Card>

          {/* Demographics */}
          <Card size="small" title={t('cohort.demographics', 'Demographics')}>
            <div className="grid grid-cols-1 gap-4">
              {/* Age Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 bg-surface-dark rounded-xl p-3">
                <div>
                  <span className="text-xs text-text-dim">Mean Age</span>
                  <p className="text-sm font-semibold text-text-bright">{result.demographics.age.mean_age ?? '—'}</p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">SD</span>
                  <p className="text-sm font-semibold text-text-bright">{result.demographics.age.std_age ?? '—'}</p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">Median</span>
                  <p className="text-sm font-semibold text-text-bright">{result.demographics.age.median_age ?? '—'}</p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">Range</span>
                  <p className="text-sm font-semibold text-text-bright">{result.demographics.age.min_age ?? '?'}–{result.demographics.age.max_age ?? '?'}</p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">IQR</span>
                  <p className="text-sm font-semibold text-text-bright">{result.demographics.age.q1_age ?? '?'}–{result.demographics.age.q3_age ?? '?'}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Age Distribution Bar Chart */}
                {result.demographics.age_groups.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-text-bright block mb-1">
                      Age Distribution
                    </span>
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={result.demographics.age_groups} margin={{ left: -10 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                        <XAxis dataKey="age_group" tick={{ fontSize: 10, fill: ct.axis }} stroke={ct.axis} />
                        <YAxis tick={{ fontSize: 10, fill: ct.axis }} stroke={ct.axis} />
                        <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} contentStyle={ct.tooltipStyle} />
                        <Bar dataKey="count" fill={ct.blue} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Gender Pie */}
                {result.demographics.gender.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-text-bright block mb-1">
                      Gender
                    </span>
                    <div className="flex items-center">
                      <ResponsiveContainer width="50%" height={150}>
                        <PieChart>
                          <Pie
                            data={result.demographics.gender}
                            dataKey="count"
                            nameKey="label"
                            cx="50%"
                            cy="50%"
                            outerRadius={55}
                            innerRadius={25}
                          >
                            {result.demographics.gender.map((_, idx) => (
                              <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                            ))}
                          </Pie>
                          <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} contentStyle={ct.tooltipStyle} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="flex-1">
                        {result.demographics.gender.map((g, i) => (
                          <div key={i} className="text-[11px] mb-0.5 text-text-muted">
                            <span
                              className="inline-block w-2 h-2 rounded-full mr-1"
                              style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }}
                            />
                            {g.label}: <strong className="text-text-bright">{g.count.toLocaleString()}</strong>
                            {' '}({result.cohort_size > 0 ? ((g.count / result.cohort_size) * 100).toFixed(1) : 0}%)
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* Race */}
                {result.demographics.race.length > 1 && (
                  <div>
                    <span className="text-xs font-semibold text-text-bright block mb-1">
                      Race
                    </span>
                    <Table
                      size="small"
                      dataSource={result.demographics.race}
                      rowKey={(r: any) => String(r.label)}
                      pagination={false}
                      columns={[
                        { key: 'label', title: '', dataIndex: 'label', ellipsis: true },
                        {
                          key: 'count', title: '', dataIndex: 'count', width: 80, align: 'right' as const,
                          render: (v: number) => v?.toLocaleString(),
                        },
                        {
                          key: 'pct', title: '', width: 60, align: 'right' as const,
                          render: (_: any, r: any) =>
                            result.cohort_size > 0
                              ? `${((r.count / result.cohort_size) * 100).toFixed(1)}%`
                              : '—',
                        },
                      ]}
                    />
                  </div>
                )}

                {/* Ethnicity */}
                {result.demographics.ethnicity.length > 1 && (
                  <div>
                    <span className="text-xs font-semibold text-text-bright block mb-1">
                      Ethnicity
                    </span>
                    <Table
                      size="small"
                      dataSource={result.demographics.ethnicity}
                      rowKey={(r: any) => String(r.label)}
                      pagination={false}
                      columns={[
                        { key: 'label', title: '', dataIndex: 'label', ellipsis: true },
                        {
                          key: 'count', title: '', dataIndex: 'count', width: 80, align: 'right' as const,
                          render: (v: number) => v?.toLocaleString(),
                        },
                        {
                          key: 'pct', title: '', width: 60, align: 'right' as const,
                          render: (_: any, r: any) =>
                            result.cohort_size > 0
                              ? `${((r.count / result.cohort_size) * 100).toFixed(1)}%`
                              : '—',
                        },
                      ]}
                    />
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* Observation Period */}
          {result.observation_period && result.observation_period.n_persons > 0 && (
            <Card size="small" title={t('cohort.observation_period', 'Observation Period')}>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-surface-dark rounded-xl p-3">
                <div>
                  <span className="text-xs text-text-dim">Persons</span>
                  <p className="text-sm font-semibold text-text-bright">{result.observation_period.n_persons?.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">Mean Duration</span>
                  <p className="text-sm font-semibold text-text-bright">
                    {result.observation_period.mean_days != null
                      ? `${Math.round(result.observation_period.mean_days / 365.25 * 10) / 10} yrs`
                      : '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">Median Duration</span>
                  <p className="text-sm font-semibold text-text-bright">
                    {result.observation_period.median_days != null
                      ? `${Math.round(result.observation_period.median_days / 365.25 * 10) / 10} yrs`
                      : '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-dim">Range</span>
                  <p className="text-sm font-semibold text-text-bright">
                    {result.observation_period.earliest_start?.substring(0, 10) ?? '?'} — {result.observation_period.latest_end?.substring(0, 10) ?? '?'}
                  </p>
                </div>
              </div>
            </Card>
          )}

          {/* Visit Types */}
          {result.visit_types.length > 0 && (
            <Card size="small" title={t('cohort.visit_types', 'Visit Types')}>
              <Table
                size="small"
                dataSource={result.visit_types}
                rowKey="concept_id"
                pagination={false}
                columns={[
                  { title: 'Visit Type', dataIndex: 'concept_name', key: 'name', ellipsis: true },
                  {
                    title: 'Patients', dataIndex: 'n_persons', key: 'np', width: 90, align: 'right' as const,
                    render: (v: number) => v?.toLocaleString(),
                  },
                  {
                    title: '%', dataIndex: 'pct_persons', key: 'pct', width: 60, align: 'right' as const,
                    render: (v: number) => `${v}%`,
                  },
                  {
                    title: 'Records', dataIndex: 'n_records', key: 'nr', width: 90, align: 'right' as const,
                    render: (v: number) => v?.toLocaleString(),
                  },
                ]}
              />
            </Card>
          )}

          {/* Visit Duration */}
          {result.visit_duration && result.visit_duration.n_visits > 0 && (
            <Card size="small" title={t('cohort.visit_duration', 'Visit Duration')}>
              <div className="flex flex-wrap gap-4 mb-3">
                <div className="text-center">
                  <div className="text-lg font-bold text-text-bright">{result.visit_duration.mean_days ?? '—'}</div>
                  <div className="text-[11px] text-text-muted">{t('cohort.mean_days', 'Mean (days)')}</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-text-bright">{result.visit_duration.median_days ?? '—'}</div>
                  <div className="text-[11px] text-text-muted">{t('cohort.median_days', 'Median (days)')}</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-text-bright">{result.visit_duration.std_days ?? '—'}</div>
                  <div className="text-[11px] text-text-muted">{t('cohort.std', 'SD')}</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-text-bright">{result.visit_duration.min_days ?? '—'} — {result.visit_duration.max_days ?? '—'}</div>
                  <div className="text-[11px] text-text-muted">{t('cohort.range_days', 'Range (days)')}</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-text-bright">{result.visit_duration.n_visits?.toLocaleString() ?? '—'}</div>
                  <div className="text-[11px] text-text-muted">{t('cohort.total_visits', 'Total visits')}</div>
                </div>
              </div>
              {(result.visit_duration.by_type?.length ?? 0) > 0 && (
                <Table
                  size="small"
                  dataSource={result.visit_duration.by_type!}
                  rowKey="visit_type"
                  pagination={false}
                  columns={[
                    { title: t('cohort.visit_type', 'Visit Type'), dataIndex: 'visit_type', key: 'type', ellipsis: true },
                    { title: t('cohort.visits', 'Visits'), dataIndex: 'n_visits', key: 'nv', width: 90, align: 'right' as const, render: (v: number) => v?.toLocaleString() },
                    { title: t('cohort.mean', 'Mean (d)'), dataIndex: 'mean_days', key: 'mean', width: 80, align: 'right' as const },
                    { title: t('cohort.median', 'Median (d)'), dataIndex: 'median_days', key: 'med', width: 80, align: 'right' as const },
                    { title: t('cohort.sd', 'SD'), dataIndex: 'std_days', key: 'sd', width: 70, align: 'right' as const },
                  ]}
                />
              )}
            </Card>
          )}

          {/* Domain Prevalence */}
          <Card size="small" title={t('cohort.domain_prevalence', 'Clinical Domain Prevalence')}>
            {/* Domain summary bar */}
            <div className="mb-3">
              {result.domain_prevalence.map(dp => (
                <div key={dp.domain} className="flex items-center gap-2 mb-1">
                  <Tag color={DOMAIN_TAG_COLORS[dp.domain] || 'default'} className="w-[100px] text-center justify-center">
                    {t(`domains.${dp.domain}`, dp.domain)}
                  </Tag>
                  <div className="flex-1 flex items-center gap-2">
                    <Progress
                      percent={dp.pct_with_data}
                      size="small"
                      showLabel={false}
                      strokeColor={DOMAIN_COLORS[dp.domain] || '#64748B'}
                    />
                    <span className="text-xs text-text-muted whitespace-nowrap">
                      {dp.patients_with_data.toLocaleString()} ({dp.pct_with_data}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Top concepts per domain */}
            <Collapse
              items={result.domain_prevalence
                .filter(dp => dp.top_concepts.length > 0)
                .map(dp => ({
                  key: dp.domain,
                  label: (
                    <div className="flex items-center gap-2">
                      <Tag color={DOMAIN_TAG_COLORS[dp.domain] || 'default'}>{t(`domains.${dp.domain}`, dp.domain)}</Tag>
                      <span className="text-text-muted text-[11px]">
                        Top {dp.top_concepts.length} concepts
                      </span>
                    </div>
                  ),
                  children: (
                    <Table
                      size="small"
                      dataSource={dp.top_concepts}
                      rowKey="concept_id"
                      pagination={false}
                      columns={[
                        {
                          title: 'Concept', dataIndex: 'concept_name', key: 'name', ellipsis: true,
                          render: (name: string, rec: any) => (
                            <Tooltip title={`${rec.concept_code} · ${rec.vocabulary_id} · ID: ${rec.concept_id}`}>
                              <span className="text-[11px]">{name}</span>
                            </Tooltip>
                          ),
                        },
                        {
                          title: 'Patients', dataIndex: 'n_persons', key: 'np', width: 80, align: 'right' as const,
                          render: (v: number) => v?.toLocaleString(),
                          sorter: (a: any, b: any) => a.n_persons - b.n_persons,
                        },
                        {
                          title: '%', dataIndex: 'pct_persons', key: 'pct', width: 55, align: 'right' as const,
                          render: (v: number) => (
                            <span className="text-[11px]">{v}%</span>
                          ),
                        },
                        {
                          title: 'Records', dataIndex: 'n_records', key: 'nr', width: 80, align: 'right' as const,
                          render: (v: number) => v?.toLocaleString(),
                        },
                      ]}
                    />
                  ),
                }))}
            />
          </Card>

          {/* Measurement Stats */}
          {result.measurement_stats.length > 0 && (
            <Card size="small" title={
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                {t('cohort.measurement_stats', 'Measurement Value Statistics')}
              </div>
            }>
              <Table
                size="small"
                dataSource={result.measurement_stats}
                rowKey="concept_id"
                pagination={false}
                columns={[
                  {
                    title: 'Measurement', dataIndex: 'concept_name', key: 'name',
                    ellipsis: true, width: 180,
                    render: (name: string, rec: any) => (
                      <Tooltip title={`${rec.concept_code} · ID: ${rec.concept_id}`}>
                        <span className="text-[11px]">{name}</span>
                      </Tooltip>
                    ),
                  },
                  {
                    title: 'Patients', dataIndex: 'n_persons', key: 'np', width: 70, align: 'right' as const,
                    render: (v: number) => v?.toLocaleString(),
                    sorter: (a: any, b: any) => a.n_persons - b.n_persons,
                  },
                  {
                    title: '%', dataIndex: 'pct_persons', key: 'pct', width: 50, align: 'right' as const,
                    render: (v: number) => `${v}%`,
                  },
                  {
                    title: 'Mean', dataIndex: 'mean_value', key: 'mean', width: 70, align: 'right' as const,
                    render: (v: number | null) => v != null ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—',
                  },
                  {
                    title: 'SD', dataIndex: 'std_value', key: 'sd', width: 60, align: 'right' as const,
                    render: (v: number | null) => v != null ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—',
                  },
                  {
                    title: 'Median', dataIndex: 'median_value', key: 'med', width: 70, align: 'right' as const,
                    render: (v: number | null) => v != null ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—',
                  },
                  {
                    title: 'Range', key: 'range', width: 100, align: 'right' as const,
                    render: (_: any, rec: any) =>
                      rec.min_value != null && rec.max_value != null
                        ? `${rec.min_value.toLocaleString(undefined, { maximumFractionDigits: 1 })}–${rec.max_value.toLocaleString(undefined, { maximumFractionDigits: 1 })}`
                        : '—',
                  },
                  {
                    title: 'Unit', dataIndex: 'unit', key: 'unit', width: 60,
                    render: (v: string) => <span className="text-text-muted text-[10px]">{v || '—'}</span>,
                  },
                ]}
              />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
