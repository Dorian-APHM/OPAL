import { useState, useEffect, useRef } from 'react';
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
}

export default function CharacterizationPanel({ cdmName, criteria, cohortId }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const [result, setResult] = useState<CharacterizationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [error, setError] = useState('');
  const [characterizedAt, setCharacterizedAt] = useState<string | null>(null);
  const [visitLevel, setVisitLevel] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const hasCriteria =
    criteria.inclusion.criteria.length > 0 ||
    criteria.demographics?.age ||
    criteria.demographics?.gender;

  const hasSameVisit = !!criteria.inclusion.sameVisit;

  // Stable key for criteria to avoid spurious resets on every render
  const criteriaKey = JSON.stringify(criteria);

  // Clear results and cancel in-flight request when criteria or cohortId change
  useEffect(() => {
    // Abort any running characterization
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setResult(null);
    setCharacterizedAt(null);
    setError('');
    setLoading(false);

    // Load saved characterization if we have a cohortId
    if (!cohortId) return;
    let cancelled = false;
    setLoadingSaved(true);
    cohortApi.getCharacterization(cohortId).then(resp => {
      if (cancelled) return;
      if (resp.data.characterization) {
        setResult(resp.data.characterization);
        setCharacterizedAt(resp.data.characterized_at);
      }
    }).catch(() => {
      // no saved characterization, that's fine
    }).finally(() => {
      if (!cancelled) setLoadingSaved(false);
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cohortId, criteriaKey]);

  const runCharacterization = async () => {
    if (!cdmName || !hasCriteria) return;
    // Abort previous request if any
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError('');
    try {
      const resp = await cohortApi.characterize(cdmName, criteria, 25, controller.signal, visitLevel);
      if (controller.signal.aborted) return;
      setResult(resp.data);
      setCharacterizedAt(new Date().toISOString());

      // Auto-save if cohort is saved
      if (cohortId) {
        try {
          await cohortApi.saveCharacterization(cohortId, resp.data);
          toast.success(t('cohort.characterization_saved', 'Characterization saved'));
        } catch {
          // non-blocking — results are still displayed
        }
      }
    } catch (e: any) {
      if (controller.signal.aborted) return;
      setError(e.response?.data?.detail || 'Characterization failed');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const stopCharacterization = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
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
            <Button
              variant="primary"
              size="small"
              onClick={runCharacterization}
              loading={loading}
              disabled={!hasCriteria || !cdmName}
            >
              {result ? t('cohort.refresh', 'Refresh') : t('cohort.run_characterization', 'Run Characterization')}
            </Button>
          </div>
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {(loading || loadingSaved) && (
        <Card size="small">
          <div className="text-center py-10">
            <Spinner size="large" />
            <div className="mt-4">
              <span className="text-text-muted text-sm">
                {loadingSaved ? t('cohort.loading_saved', 'Loading saved results...') : 'Running characterization queries...'}
              </span>
            </div>
            {loading && (
              <Button
                variant="danger"
                size="small"
                icon={<X className="h-3.5 w-3.5" />}
                onClick={stopCharacterization}
                className="mt-3"
              >
                {t('common.stop', 'Stop')}
              </Button>
            )}
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
              value={result.cohort_size}
              valueStyle={{ color: '#1890ff', fontSize: 28 }}
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
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="age_group" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} />
                        <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} />
                        <Bar dataKey="count" fill="#1890ff" />
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
                          <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} />
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

          {/* Domain Prevalence */}
          <Card size="small" title={t('cohort.domain_prevalence', 'Clinical Domain Prevalence')}>
            {/* Domain summary bar */}
            <div className="mb-3">
              {result.domain_prevalence.map(dp => (
                <div key={dp.domain} className="flex items-center gap-2 mb-1">
                  <Tag color={DOMAIN_TAG_COLORS[dp.domain] || 'default'} className="w-[100px] text-center justify-center">
                    {dp.domain}
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
                      <Tag color={DOMAIN_TAG_COLORS[dp.domain] || 'default'}>{dp.domain}</Tag>
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
