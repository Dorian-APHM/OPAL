import { useState, useEffect } from 'react';
import { TrendingUp, Calculator } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, AreaChart, Legend, ReferenceLine,
} from 'recharts';
import { cohortApi, estimationApi } from '../api/client';
import { useChartTheme } from '../hooks/useChartTheme';
import type { CohortSummary, KaplanMeierResult, KMPoint } from '../types';
import {
  Card, Button, Select, Statistic, Empty, Spinner, Tag, Checkbox, useToast,
} from '../components/ui';
import type { Column } from '../components/ui';

const STRATA_COLORS = ['#10B981', '#14b8a6', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444'];

export default function EstimationPage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const ct = useChartTheme();
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [targetId, setTargetId] = useState<number | null>(null);
  const [outcomeId, setOutcomeId] = useState<number | null>(null);
  const [timeUnit, setTimeUnit] = useState<string>('days');
  const [strata, setStrata] = useState<string[]>([]);
  const [computing, setComputing] = useState(false);
  const [result, setResult] = useState<KaplanMeierResult | null>(null);

  useEffect(() => {
    if (!selectedCdm) return;
    cohortApi.list(selectedCdm).then(r => setCohorts(r.data.cohorts)).catch(() => {});
  }, [selectedCdm]);

  const compute = async () => {
    if (!selectedCdm || !targetId || !outcomeId) return;
    setComputing(true);
    try {
      const r = await estimationApi.kaplanMeier({
        cdm_name: selectedCdm,
        target_cohort_id: targetId,
        outcome_cohort_id: outcomeId,
        time_unit: timeUnit,
        strata,
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

  // Prepare chart data
  const chartData = result ? prepareChartData(result) : [];
  const strataNames = result ? Object.keys(result.strata) : [];
  const hasStrata = strataNames.length > 0;

  return (
    <div className="max-w-[1100px] mx-auto">
      <h4 className="text-lg font-semibold text-text-bright mb-4 flex items-center gap-2">
        <TrendingUp className="h-5 w-5" />
        {t('estimation.kaplan_meier', 'Kaplan-Meier Survival')}
      </h4>

      <Card size="small" className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('estimation.target_cohort', 'Target Cohort')}
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
                {t('estimation.outcome_cohort', 'Outcome Event')}
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
                {t('estimation.time_unit', 'Time Unit')}
              </span>
              <div className="flex rounded-[10px] border border-glass-border overflow-hidden mt-1">
                {(['days', 'months', 'years'] as const).map((unit) => (
                  <button
                    key={unit}
                    onClick={() => setTimeUnit(unit)}
                    className={`flex-1 px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer border-none ${
                      timeUnit === unit
                        ? 'bg-emerald-accent/15 text-emerald-400'
                        : 'bg-deep-base text-text-muted hover:text-text-bright'
                    }`}
                  >
                    {t(`estimation.${unit}`, unit.charAt(0).toUpperCase() + unit.slice(1))}
                  </button>
                ))}
              </div>
            </div>
            <div className="col-span-2">
              <span className="text-sm font-semibold text-text-bright block mb-1">
                {t('estimation.strata', 'Stratify by')}
              </span>
              <div className="flex items-center gap-4 mt-1">
                <Checkbox
                  checked={strata.includes('gender')}
                  onChange={() => toggleStratum('gender')}
                >
                  Gender
                </Checkbox>
                <Checkbox
                  checked={strata.includes('age_group')}
                  onChange={() => toggleStratum('age_group')}
                >
                  Age Group
                </Checkbox>
              </div>
            </div>
          </div>

          <Button
            variant="primary"
            icon={<Calculator className="h-4 w-4" />}
            onClick={compute}
            loading={computing}
            disabled={!targetId || !outcomeId}
          >
            {t('estimation.compute', 'Compute')}
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
          {/* Summary stats */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <Card size="small">
              <Statistic title="N" value={result.summary.n} />
            </Card>
            <Card size="small">
              <Statistic title={t('estimation.events', 'Events')} value={result.summary.events} />
            </Card>
            <Card size="small">
              <Statistic title={t('estimation.censored', 'Censored')} value={result.summary.censored} />
            </Card>
            <Card size="small">
              <Statistic
                title={t('estimation.median_survival', 'Median Survival')}
                value={result.median_survival ?? '\u2014'}
                suffix={result.median_survival != null ? timeUnit : ''}
              />
            </Card>
          </div>

          {/* Log-rank test */}
          {result.log_rank && (
            <Card size="small" className="mb-4">
              <div className="flex items-center gap-3">
                <Tag color={result.log_rank.p_value < 0.05 ? 'red' : 'green'}>
                  {t('estimation.log_rank', 'Log-Rank Test')}
                </Tag>
                <span className="text-sm text-text-bright">Chi² = {result.log_rank.chi_square}</span>
                <span className="text-sm font-semibold text-text-bright">
                  {t('estimation.p_value', 'p-value')} = {result.log_rank.p_value < 0.001 ? '< 0.001' : result.log_rank.p_value.toFixed(4)}
                </span>
                <span className="text-sm text-text-dim">(df = {result.log_rank.df})</span>
              </div>
            </Card>
          )}

          {/* Kaplan-Meier Chart */}
          <Card size="small" title={t('estimation.survival_curve', 'Survival Curve')}>
            <ResponsiveContainer width="100%" height={400}>
              {hasStrata ? (
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="time" stroke={ct.axis} label={{ value: timeUnit, position: 'bottom' }} />
                  <YAxis domain={[0, 1]} stroke={ct.axis} label={{ value: 'Survival', angle: -90, position: 'insideLeft' }} />
                  <Tooltip formatter={(value: number) => value.toFixed(4)} contentStyle={ct.tooltipStyle} />
                  <Legend />
                  {result.median_survival != null && (
                    <ReferenceLine y={0.5} stroke={ct.reference} strokeDasharray="5 5" label="Median" />
                  )}
                  {strataNames.map((name, i) => (
                    <Line
                      key={name}
                      type="stepAfter"
                      dataKey={`survival_${name}`}
                      name={name}
                      stroke={STRATA_COLORS[i % STRATA_COLORS.length]}
                      dot={false}
                      strokeWidth={2}
                    />
                  ))}
                </LineChart>
              ) : (
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="time" stroke={ct.axis} label={{ value: timeUnit, position: 'bottom' }} />
                  <YAxis domain={[0, 1]} stroke={ct.axis} label={{ value: 'Survival', angle: -90, position: 'insideLeft' }} />
                  <Tooltip formatter={(value: number) => value.toFixed(4)} contentStyle={ct.tooltipStyle} />
                  {result.median_survival != null && (
                    <ReferenceLine y={0.5} stroke={ct.reference} strokeDasharray="5 5" label="Median" />
                  )}
                  <Area
                    type="stepAfter"
                    dataKey="ci_upper"
                    stroke="none"
                    fill={ct.blue}
                    fillOpacity={0.1}
                  />
                  <Area
                    type="stepAfter"
                    dataKey="ci_lower"
                    stroke="none"
                    fill={ct.label}
                    fillOpacity={1}
                  />
                  <Line type="stepAfter" dataKey="survival" stroke={ct.blue} dot={false} strokeWidth={2} />
                </AreaChart>
              )}
            </ResponsiveContainer>
          </Card>

          {/* Number at risk table */}
          <div className="my-4">
            <div className="flex items-center gap-2 mb-3">
              <div className="h-px flex-1 bg-glass-border" />
              <span className="text-sm text-text-muted font-medium">{t('estimation.at_risk', 'Number at Risk')}</span>
              <div className="h-px flex-1 bg-glass-border" />
            </div>
          </div>
          <AtRiskTable
            overall={result.overall}
            strata={result.strata}
            timeUnit={timeUnit}
          />
        </>
      )}
    </div>
  );
}

function prepareChartData(result: KaplanMeierResult): any[] {
  const strataNames = Object.keys(result.strata);
  if (strataNames.length === 0) {
    return result.overall.map(p => ({
      time: Math.round(p.time * 100) / 100,
      survival: p.survival,
      ci_lower: p.ci_lower,
      ci_upper: p.ci_upper,
    }));
  }

  // Merge all strata time points
  const allTimes = new Set<number>();
  for (const curve of Object.values(result.strata)) {
    for (const p of curve) allTimes.add(p.time);
  }

  const sortedTimes = [...allTimes].sort((a, b) => a - b);
  return sortedTimes.map(time => {
    const row: any = { time: Math.round(time * 100) / 100 };
    for (const name of strataNames) {
      const curve = result.strata[name];
      // Find the last point <= time
      let lastPoint: KMPoint | null = null;
      for (const p of curve) {
        if (p.time <= time) lastPoint = p;
        else break;
      }
      row[`survival_${name}`] = lastPoint?.survival ?? 1;
    }
    return row;
  });
}

function AtRiskTable({ overall, strata, timeUnit }: {
  overall: KMPoint[];
  strata: Record<string, KMPoint[]>;
  timeUnit: string;
}) {
  const strataNames = Object.keys(strata);
  const hasStrata = strataNames.length > 0;

  // Pick ~8 time points
  const source = hasStrata ? Object.values(strata)[0] : overall;
  const step = Math.max(1, Math.floor(source.length / 8));
  const timePoints = source.filter((_, i) => i % step === 0 || i === source.length - 1);

  const data = hasStrata
    ? strataNames.map(name => {
        const row: Record<string, any> = { label: name, key: name };
        timePoints.forEach((tp, i) => {
          const curve = strata[name];
          let last: KMPoint | null = null;
          for (const p of curve) {
            if (p.time <= tp.time) last = p;
            else break;
          }
          row[`t${i}`] = last?.at_risk ?? '\u2014';
        });
        return row;
      })
    : [{
        label: 'Overall',
        key: 'overall',
        ...Object.fromEntries(timePoints.map((p, i) => [`t${i}`, p.at_risk])),
      }];

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-muted bg-surface-dark border-b border-glass-border sticky left-0">
              &nbsp;
            </th>
            {timePoints.map((p, i) => (
              <th key={i} className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-muted bg-surface-dark border-b border-glass-border">
                {Math.round(p.time)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.key} className="border-b border-border-subtle hover:bg-emerald-accent/4 transition-colors">
              <td className="px-3 py-2 text-sm text-text-bright font-medium sticky left-0 bg-surface">{row.label}</td>
              {timePoints.map((_, i) => (
                <td key={i} className="px-3 py-2 text-sm text-text-bright">{row[`t${i}`]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
