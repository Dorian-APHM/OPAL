import { useState } from 'react';
import { useSessionState } from '../../hooks/useSessionState';
import {
  Card, Button, Select, Alert, Empty, Tooltip, Switch, Statistic,
  Collapse, Table, Tag, Spinner,
} from '../../components/ui';
import { ArrowLeftRight, Download, Users } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine,
  Tooltip as RechartsTooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { useChartTheme } from '../../hooks/useChartTheme';
import { cohortApi } from '../../api/client';
import type { CohortSummary, CohortComparisonResult, CohortComparisonVariable } from '../../types';

const DOMAIN_TAG_COLORS: Record<string, 'red' | 'blue' | 'green' | 'orange' | 'purple' | 'cyan' | 'magenta' | 'default'> = {
  Condition: 'red',
  Drug: 'blue',
  Procedure: 'green',
  Measurement: 'orange',
  Observation: 'purple',
  Device: 'cyan',
  Visit: 'magenta',
};

interface Props {
  cdmName: string;
  cohorts: CohortSummary[];
}

function smdColor(smd: number | null): string {
  if (smd === null) return '#999';
  const abs = Math.abs(smd);
  if (abs < 0.1) return '#52c41a';
  if (abs < 0.2) return '#faad14';
  return '#f5222d';
}

function SmdTag({ smd }: { smd: number | null }) {
  if (smd === null) return <Tag color="default">N/A</Tag>;
  const abs = Math.abs(smd);
  const color: 'green' | 'orange' | 'red' = abs < 0.1 ? 'green' : abs < 0.2 ? 'orange' : 'red';
  return <Tag color={color}>{smd.toFixed(3)}</Tag>;
}

export default function CohortComparisonPanel({ cdmName, cohorts }: Props) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const [cohortIdA, setCohortIdA] = useSessionState<string | undefined>('cohort:cmp:idA', undefined);
  const [cohortIdB, setCohortIdB] = useSessionState<string | undefined>('cohort:cmp:idB', undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useSessionState<CohortComparisonResult | null>('cohort:cmp:result', null);
  const [visitLevel, setVisitLevel] = useSessionState('cohort:cmp:visitLevel', false);

  const runCompare = async () => {
    if (!cdmName || !cohortIdA || !cohortIdB) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await cohortApi.compare(cdmName, Number(cohortIdA), Number(cohortIdB), visitLevel);
      setResult(resp.data);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Comparison failed');
    } finally {
      setLoading(false);
    }
  };

  const exportCsv = () => {
    if (!result) return;
    const lines: string[] = ['Category,Variable,Cohort A,Cohort B,SMD'];
    for (const v of result.all_variables) {
      lines.push(`"${v.category}","${v.variable}","","",${v.smd ?? ''}`);
    }
    const d = result.demographics;
    lines.push(`Demographics,Age (mean),${d.age.mean_a ?? ''},${d.age.mean_b ?? ''},${d.age.smd ?? ''}`);
    for (const g of d.gender) lines.push(`Demographics,"Gender: ${g.label}",${g.pct_a}%,${g.pct_b}%,${g.smd ?? ''}`);
    for (const r of d.race) lines.push(`Demographics,"Race: ${r.label}",${r.pct_a}%,${r.pct_b}%,${r.smd ?? ''}`);
    for (const dp of result.domain_prevalence) {
      for (const c of dp.concepts) {
        lines.push(`"${dp.domain}","${c.concept_name}",${c.pct_persons_a}%,${c.pct_persons_b}%,${c.smd ?? ''}`);
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cohort_comparison.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const cohortOptions = cohorts.map(c => ({
    value: String(c.id),
    label: `${c.name}${c.patient_count != null ? ` (${c.patient_count.toLocaleString()} pts)` : ''}`,
  }));

  // Love plot data: top 50 by |SMD|, exclude nulls
  const lovePlotData: (CohortComparisonVariable & { absSmd: number })[] = result
    ? result.all_variables
        .filter(v => v.smd !== null)
        .map(v => ({ ...v, absSmd: Math.abs(v.smd!) }))
        .sort((a, b) => b.absSmd - a.absSmd)
        .slice(0, 50)
    : [];

  return (
    <div className="flex flex-col gap-3">
      {/* Selection */}
      <Card size="small">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-[18px] w-[18px] text-text-muted" />
            <h5 className="text-sm font-semibold text-text-bright m-0">
              {t('cohort.compare_cohorts', 'Compare Cohorts')}
            </h5>
          </div>
          <div className="flex items-center gap-2">
            {result && (
              <Button size="small" icon={<Download className="h-3.5 w-3.5" />} onClick={exportCsv}>
                CSV
              </Button>
            )}
          </div>
        </div>
        <div className="grid grid-cols-[5fr_5fr_2fr] gap-2 mt-3">
          <Select
            placeholder={t('cohort.select_cohort_a', 'Cohort A')}
            options={cohortOptions}
            value={cohortIdA}
            onChange={(v) => setCohortIdA(v || undefined)}
            size="small"
          />
          <Select
            placeholder={t('cohort.select_cohort_b', 'Cohort B')}
            options={cohortOptions}
            value={cohortIdB}
            onChange={(v) => setCohortIdB(v || undefined)}
            size="small"
          />
          <Button
            variant="primary"
            size="small"
            block
            onClick={runCompare}
            loading={loading}
            disabled={!cohortIdA || !cohortIdB || cohortIdA === cohortIdB}
          >
            {t('cohort.compare', 'Compare')}
          </Button>
        </div>
        <div className="mt-2 flex justify-end">
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
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {loading && (
        <Card size="small">
          <div className="text-center py-10">
            <Spinner size="large" />
            <div className="mt-4">
              <span className="text-text-muted text-sm">{t('cohort.comparing', 'Comparing cohorts...')}</span>
            </div>
          </div>
        </Card>
      )}

      {!result && !loading && !error && (
        <Card size="small">
          <Empty
            description={t('cohort.select_two_cohorts', 'Select two cohorts to compare')}
          />
        </Card>
      )}

      {result && !loading && (
        <>
          {/* Cohort sizes */}
          <div className="grid grid-cols-2 gap-2">
            <Card size="small">
              <Statistic
                title={<div className="flex items-center gap-1"><Users className="h-3.5 w-3.5" /><span className="font-semibold">{result.cohort_a_name}</span></div>}
                value={result.cohort_a_size}
                suffix="patients"
                valueStyle={{ color: ct.blue, fontSize: 22 }}
              />
            </Card>
            <Card size="small">
              <Statistic
                title={<div className="flex items-center gap-1"><Users className="h-3.5 w-3.5" /><span className="font-semibold">{result.cohort_b_name}</span></div>}
                value={result.cohort_b_size}
                suffix="patients"
                valueStyle={{ color: ct.purple, fontSize: 22 }}
              />
            </Card>
          </div>

          {/* SMD Legend */}
          <Card size="small">
            <div className="flex items-center gap-2 py-0.5">
              <span className="text-text-muted text-[11px]">SMD:</span>
              <Tag color="green">&lt; 0.1 balanced</Tag>
              <Tag color="orange">0.1–0.2 small imbalance</Tag>
              <Tag color="red">&gt; 0.2 imbalanced</Tag>
            </div>
          </Card>

          {/* Demographics */}
          <Card size="small" title={t('cohort.demographics', 'Demographics')}>
            <Table
              size="small"
              pagination={false}
              dataSource={[
                {
                  key: 'age',
                  variable: 'Age (mean \u00B1 SD)',
                  cohort_a: `${result.demographics.age.mean_a ?? '—'} \u00B1 ${result.demographics.age.std_a ?? '—'}`,
                  cohort_b: `${result.demographics.age.mean_b ?? '—'} \u00B1 ${result.demographics.age.std_b ?? '—'}`,
                  smd: result.demographics.age.smd,
                },
                ...result.demographics.gender.map((g, i) => ({
                  key: `gender_${i}`,
                  variable: `Gender: ${g.label}`,
                  cohort_a: `${g.pct_a}%`,
                  cohort_b: `${g.pct_b}%`,
                  smd: g.smd,
                })),
                ...result.demographics.race.map((r, i) => ({
                  key: `race_${i}`,
                  variable: `Race: ${r.label}`,
                  cohort_a: `${r.pct_a}%`,
                  cohort_b: `${r.pct_b}%`,
                  smd: r.smd,
                })),
                ...result.demographics.ethnicity.map((e, i) => ({
                  key: `eth_${i}`,
                  variable: `Ethnicity: ${e.label}`,
                  cohort_a: `${e.pct_a}%`,
                  cohort_b: `${e.pct_b}%`,
                  smd: e.smd,
                })),
                ...result.demographics.age_groups.map((ag, i) => ({
                  key: `ag_${i}`,
                  variable: `Age: ${ag.age_group}`,
                  cohort_a: `${ag.pct_a}%`,
                  cohort_b: `${ag.pct_b}%`,
                  smd: ag.smd,
                })),
              ]}
              rowKey="key"
              columns={[
                { title: 'Variable', dataIndex: 'variable', key: 'var', ellipsis: true },
                { title: result.cohort_a_name, dataIndex: 'cohort_a', key: 'a', width: 120, align: 'right' as const },
                { title: result.cohort_b_name, dataIndex: 'cohort_b', key: 'b', width: 120, align: 'right' as const },
                {
                  title: 'SMD', dataIndex: 'smd', key: 'smd', width: 90, align: 'center' as const,
                  render: (smd: number | null) => <SmdTag smd={smd} />,
                  sorter: (a: any, b: any) => Math.abs(a.smd ?? 0) - Math.abs(b.smd ?? 0),
                },
              ]}
            />
          </Card>

          {/* Domain Prevalence */}
          {result.domain_prevalence.length > 0 && (
            <Card size="small" title={t('cohort.domain_prevalence', 'Clinical Domain Prevalence')}>
              {/* Domain-level summary */}
              <Table
                size="small"
                pagination={false}
                dataSource={result.domain_prevalence.map(dp => ({
                  key: dp.domain,
                  domain: dp.domain,
                  pct_a: `${dp.pct_with_data_a}%`,
                  pct_b: `${dp.pct_with_data_b}%`,
                  smd: dp.smd,
                }))}
                rowKey="key"
                className="mb-3"
                columns={[
                  {
                    title: 'Domain', dataIndex: 'domain', key: 'd',
                    render: (d: string) => <Tag color={DOMAIN_TAG_COLORS[d] || 'default'}>{d}</Tag>,
                  },
                  { title: result.cohort_a_name, dataIndex: 'pct_a', key: 'a', width: 120, align: 'right' as const },
                  { title: result.cohort_b_name, dataIndex: 'pct_b', key: 'b', width: 120, align: 'right' as const },
                  {
                    title: 'SMD', dataIndex: 'smd', key: 'smd', width: 90, align: 'center' as const,
                    render: (smd: number | null) => <SmdTag smd={smd} />,
                  },
                ]}
              />

              {/* Per-domain concept details */}
              <Collapse
                items={result.domain_prevalence
                  .filter(dp => dp.concepts.length > 0)
                  .map(dp => ({
                    key: dp.domain,
                    label: (
                      <div className="flex items-center gap-2">
                        <Tag color={DOMAIN_TAG_COLORS[dp.domain] || 'default'}>{t(`domains.${dp.domain}`, dp.domain)}</Tag>
                        <span className="text-text-muted text-[11px]">
                          {dp.concepts.length} concepts
                        </span>
                      </div>
                    ),
                    children: (
                      <Table
                        size="small"
                        dataSource={dp.concepts}
                        rowKey="concept_id"
                        pagination={false}
                        columns={[
                          { title: 'Concept', dataIndex: 'concept_name', key: 'name', ellipsis: true },
                          { title: result.cohort_a_name, key: 'a', width: 100, align: 'right' as const, render: (_: any, r: any) => `${r.pct_persons_a}%` },
                          { title: result.cohort_b_name, key: 'b', width: 100, align: 'right' as const, render: (_: any, r: any) => `${r.pct_persons_b}%` },
                          {
                            title: 'SMD', dataIndex: 'smd', key: 'smd', width: 90, align: 'center' as const,
                            render: (smd: number | null) => <SmdTag smd={smd} />,
                            sorter: (a: any, b: any) => Math.abs(a.smd ?? 0) - Math.abs(b.smd ?? 0),
                          },
                        ]}
                      />
                    ),
                  }))}
              />
            </Card>
          )}

          {/* Measurement Stats */}
          {result.measurement_stats.length > 0 && (
            <Card size="small" title={t('cohort.measurement_stats', 'Measurement Value Statistics')}>
              <Table
                size="small"
                dataSource={result.measurement_stats}
                rowKey="concept_id"
                pagination={false}
                columns={[
                  { title: 'Measurement', dataIndex: 'concept_name', key: 'name', ellipsis: true, width: 160 },
                  {
                    title: `Mean (${result.cohort_a_name})`, key: 'mean_a', width: 100, align: 'right' as const,
                    render: (_: any, r: any) => r.mean_a != null ? r.mean_a.toFixed(1) : '—',
                  },
                  {
                    title: `Mean (${result.cohort_b_name})`, key: 'mean_b', width: 100, align: 'right' as const,
                    render: (_: any, r: any) => r.mean_b != null ? r.mean_b.toFixed(1) : '—',
                  },
                  {
                    title: 'SMD (value)', dataIndex: 'smd', key: 'smd', width: 100, align: 'center' as const,
                    render: (smd: number | null) => <SmdTag smd={smd} />,
                    sorter: (a: any, b: any) => Math.abs(a.smd ?? 0) - Math.abs(b.smd ?? 0),
                  },
                  { title: 'Unit', dataIndex: 'unit', key: 'unit', width: 60 },
                ]}
              />
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
                  { title: result.cohort_a_name, key: 'a', width: 100, align: 'right' as const, render: (_: any, r: any) => `${r.pct_persons_a}%` },
                  { title: result.cohort_b_name, key: 'b', width: 100, align: 'right' as const, render: (_: any, r: any) => `${r.pct_persons_b}%` },
                  {
                    title: 'SMD', dataIndex: 'smd', key: 'smd', width: 90, align: 'center' as const,
                    render: (smd: number | null) => <SmdTag smd={smd} />,
                  },
                ]}
              />
            </Card>
          )}

          {/* Observation Period */}
          <Card size="small" title={t('cohort.observation_period', 'Observation Period')}>
            <div className="grid grid-cols-3 gap-2 bg-surface-dark rounded-xl p-3">
              <div>
                <span className="text-xs text-text-dim">Mean Duration (A)</span>
                <p className="text-sm font-semibold text-text-bright">
                  {result.observation_period.mean_days_a != null
                    ? `${Math.round(result.observation_period.mean_days_a)} days`
                    : '—'}
                </p>
              </div>
              <div>
                <span className="text-xs text-text-dim">Mean Duration (B)</span>
                <p className="text-sm font-semibold text-text-bright">
                  {result.observation_period.mean_days_b != null
                    ? `${Math.round(result.observation_period.mean_days_b)} days`
                    : '—'}
                </p>
              </div>
              <div>
                <span className="text-xs text-text-dim">SMD</span>
                <div className="mt-1"><SmdTag smd={result.observation_period.smd} /></div>
              </div>
            </div>
          </Card>

          {/* Love Plot */}
          {lovePlotData.length > 0 && (
            <Card size="small" title="Love Plot — Top 50 Variables by |SMD|">
              <ResponsiveContainer width="100%" height={Math.max(300, lovePlotData.length * 22 + 40)}>
                <BarChart
                  layout="vertical"
                  data={lovePlotData}
                  margin={{ left: 10, right: 30, top: 5, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis type="number" domain={[0, 'auto']} tick={{ fontSize: 10, fill: ct.axis }} stroke={ct.axis} />
                  <YAxis
                    type="category"
                    dataKey="variable"
                    width={200}
                    tick={{ fontSize: 9, fill: ct.axis }}
                    stroke={ct.axis}
                  />
                  <RechartsTooltip
                    formatter={(value: number) => value.toFixed(3)}
                    labelFormatter={(label: string) => label}
                    contentStyle={ct.tooltipStyle}
                  />
                  <ReferenceLine x={0.1} stroke={ct.yellow} strokeDasharray="5 5" label={{ value: '0.1', fontSize: 10, fill: ct.label }} />
                  <Bar dataKey="absSmd" name="|SMD|" radius={[0, 2, 2, 0]}>
                    {lovePlotData.map((entry, i) => (
                      <Cell key={i} fill={smdColor(entry.smd)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
