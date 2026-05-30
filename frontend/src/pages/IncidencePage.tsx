import { useState, useEffect } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import { useChartTheme } from '../hooks/useChartTheme';
import { BarChart3, Calculator } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { cohortApi, incidenceApi } from '../api/client';
import type { CohortSummary, IncidenceResult } from '../types';
import {
  Card, Button, Select, NumberInput, Statistic, Empty, Spinner, Checkbox, Table, useToast,
} from '../components/ui';
import type { Column } from '../components/ui';

export default function IncidencePage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const ct = useChartTheme();
  const [cohorts, setCohorts] = useSessionState<CohortSummary[]>('incidence:cohorts', []);
  const [targetId, setTargetId] = useSessionState<number | null>('incidence:targetId', null);
  const [outcomeId, setOutcomeId] = useSessionState<number | null>('incidence:outcomeId', null);
  const [tarStart, setTarStart] = useSessionState('incidence:tarStart', 0);
  const [tarEnd, setTarEnd] = useSessionState<string | number>('incidence:tarEnd', 'observation_end');
  const [tarEndDays, setTarEndDays] = useSessionState('incidence:tarEndDays', 365);
  const [strata, setStrata] = useSessionState<string[]>('incidence:strata', []);
  const [computing, setComputing] = useState(false);
  const [result, setResult] = useSessionState<IncidenceResult | null>('incidence:result', null);

  useEffect(() => {
    if (!selectedCdm) return;
    cohortApi.list(selectedCdm).then(r => setCohorts(r.data.cohorts)).catch(() => toast.error(t('common.error', 'Failed to load cohorts')));
  }, [selectedCdm]);

  const compute = async () => {
    if (!selectedCdm || !targetId || !outcomeId) return;
    setComputing(true);
    try {
      const r = await incidenceApi.compute({
        cdm_name: selectedCdm,
        target_cohort_id: targetId,
        outcome_cohort_id: outcomeId,
        time_at_risk_start: tarStart,
        time_at_risk_end: tarEnd === 'observation_end' ? 'observation_end' : tarEndDays,
        strata,
        age_groups: strata.includes('age_group') ? [
          { min: 0, max: 17, label: '0-17' },
          { min: 18, max: 39, label: '18-39' },
          { min: 40, max: 64, label: '40-64' },
          { min: 65, max: 999, label: '65+' },
        ] : [],
      });
      setResult(r.data);
    } catch (e: any) {
      toast.error(e.message || 'Computation failed');
    } finally {
      setComputing(false);
    }
  };

  const toggleStratum = (value: string) => {
    setStrata(prev =>
      prev.includes(value) ? prev.filter(s => s !== value) : [...prev, value]
    );
  };

  if (!selectedCdm) return <Card><Empty description="Select a CDM first" /></Card>;

  const cohortOptions = cohorts.map(c => ({
    value: String(c.id),
    label: `${c.name} (${c.patient_count ?? '?'})`,
  }));

  const tarEndOptions = [
    { value: 'observation_end', label: t('incidence.observation_end', 'End of observation') },
    { value: 'fixed', label: t('incidence.fixed_days', 'Fixed duration') },
  ];

  const strataColumns: Column<any>[] = [
    ...strata.map(s => ({
      key: s,
      title: s,
      render: (_: any, row: any) => row.strata_values?.[s] || '\u2014',
    })),
    { key: 'target_count', title: 'At Risk', dataIndex: 'target_count' },
    { key: 'outcome_count', title: 'Events', dataIndex: 'outcome_count' },
    { key: 'person_years', title: 'PY', dataIndex: 'person_years', render: (v: number) => v?.toFixed(1) },
    { key: 'rate', title: 'IR/1000 PY', render: (_: any, r: any) => ((r.incidence_rate || 0) * 1000).toFixed(2) },
    { key: 'ci', title: '95% CI', render: (_: any, r: any) => `[${((r.ci_lower || 0) * 1000).toFixed(1)} - ${((r.ci_upper || 0) * 1000).toFixed(1)}]` },
  ];

  return (
    <div className="max-w-[1100px] mx-auto">
      <h4 className="text-lg font-semibold text-text-bright mb-4 flex items-center gap-2">
        <BarChart3 className="h-5 w-5" />
        {t('incidence.title', 'Incidence Rates')}
      </h4>

      <Card size="small" className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('incidence.target_cohort', 'Target Cohort')}
              </span>
              <Select
                placeholder="Select target cohort..."
                value={targetId != null ? String(targetId) : null}
                onChange={(v) => setTargetId(v ? Number(v) : null)}
                options={cohortOptions}
              />
            </div>
            <div>
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('incidence.outcome_cohort', 'Outcome Cohort')}
              </span>
              <Select
                placeholder="Select outcome cohort..."
                value={outcomeId != null ? String(outcomeId) : null}
                onChange={(v) => setOutcomeId(v ? Number(v) : null)}
                options={cohortOptions}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('incidence.tar_start', 'TAR Start (days)')}
              </span>
              <NumberInput
                value={tarStart}
                onChange={(v) => setTarStart(v ?? 0)}
                min={0}
              />
            </div>
            <div>
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('incidence.tar_end', 'TAR End')}
              </span>
              <Select
                value={tarEnd as string}
                onChange={(v) => setTarEnd(v)}
                options={tarEndOptions}
              />
            </div>
            {tarEnd === 'fixed' && (
              <div>
                <span className="text-sm font-semibold text-text-bright block mb-1">
                  {t('incidence.fixed_days', 'Days')}
                </span>
                <NumberInput
                  value={tarEndDays}
                  onChange={(v) => setTarEndDays(v ?? 365)}
                  min={1}
                />
              </div>
            )}
          </div>

          <div>
            <span className="text-sm font-semibold text-text-bright block mb-1">
              {t('incidence.strata', 'Stratification')}
            </span>
            <div className="flex items-center gap-4 mt-1">
              <Checkbox
                checked={strata.includes('gender')}
                onChange={() => toggleStratum('gender')}
              >
                {t('incidence.gender', 'Gender')}
              </Checkbox>
              <Checkbox
                checked={strata.includes('age_group')}
                onChange={() => toggleStratum('age_group')}
              >
                {t('incidence.age_group', 'Age Group')}
              </Checkbox>
              <Checkbox
                checked={strata.includes('calendar_year')}
                onChange={() => toggleStratum('calendar_year')}
              >
                {t('incidence.calendar_year', 'Calendar Year')}
              </Checkbox>
            </div>
          </div>

          <Button
            variant="primary"
            icon={<Calculator className="h-4 w-4" />}
            onClick={compute}
            loading={computing}
            disabled={!targetId || !outcomeId}
          >
            {t('incidence.compute', 'Compute')}
          </Button>
        </div>
      </Card>

      {computing && (
        <div className="text-center py-10">
          <Spinner size="large" />
        </div>
      )}

      {result && !computing && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <Card size="small">
              <Statistic title={t('incidence.persons_at_risk', 'At Risk')} value={result.target_count?.toLocaleString()} />
            </Card>
            <Card size="small">
              <Statistic title={t('incidence.persons_with_outcome', 'With Outcome')} value={result.outcome_count?.toLocaleString()} />
            </Card>
            <Card size="small">
              <Statistic title={t('incidence.person_years', 'Person-Years')} value={(result.person_years ?? 0).toFixed(1)} />
            </Card>
            <Card size="small">
              <Statistic
                title="IR / 1000 PY"
                value={((result.incidence_rate ?? 0) * 1000).toFixed(2)}
                suffix={`[${((result.ci_lower ?? 0) * 1000).toFixed(1)}-${((result.ci_upper ?? 0) * 1000).toFixed(1)}]`}
              />
            </Card>
          </div>

          {result.strata.length > 0 && (
            <>
              <div className="my-4">
                <div className="flex items-center gap-2 mb-3">
                  <div className="h-px flex-1 bg-glass-border" />
                  <span className="text-sm text-text-muted font-medium">{t('incidence.strata', 'By Strata')}</span>
                  <div className="h-px flex-1 bg-glass-border" />
                </div>
              </div>

              <Table
                dataSource={result.strata}
                rowKey={(r) => JSON.stringify(r.strata_values || r.target_count)}
                size="small"
                columns={strataColumns}
                pagination={false}
              />

              <Card size="small" className="mt-4">
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={result.strata.map((s) => ({
                    label: Object.values(s.strata_values || {}).join(' / '),
                    rate: (s.incidence_rate || 0) * 1000,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                    <XAxis dataKey="label" stroke={ct.axis} />
                    <YAxis label={{ value: 'IR / 1000 PY', angle: -90, position: 'insideLeft' }} stroke={ct.axis} />
                    <Tooltip contentStyle={ct.tooltipStyle} />
                    <Bar dataKey="rate" fill={ct.blue} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
