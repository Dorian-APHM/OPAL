import { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { useTranslation } from 'react-i18next';
import { qualityApi } from '../../api/client';
import useIsMobile from '../../hooks/useIsMobile';
import { useChartTheme } from '../../hooks/useChartTheme';
import { Card, Select, Empty, Spinner, Statistic, Tag } from '../ui';

interface TimelinePoint {
  snapshot_id: number;
  version: number;
  created_at: string | null;
  total_persons?: number;
  total_records?: number;
  distinct_persons?: number;
  pct_terms_mapped?: number | null;
  pct_rows_mapped?: number | null;
  avg_pct_terms_mapped?: number | null;
}

interface Props {
  selectedCdm: string;
}

const COLORS = ['#10B981', '#14b8a6', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#6366F1'];

export default function SnapshotTimeline({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const isMobile = useIsMobile();
  const [timelines, setTimelines] = useState<Record<string, TimelinePoint[]>>({});
  const [loading, setLoading] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedCdm) return;
    setLoading(true);
    qualityApi.timeline(selectedCdm)
      .then((res) => {
        const tl = res.data.timelines || {};
        setTimelines(tl);
        const keys = Object.keys(tl);
        // Keep the current domain only if it still exists for this CDM, else
        // fall back to the first available one (avoids a blank chart on CDM switch).
        setSelectedDomain((prev) => (prev && keys.includes(prev) ? prev : keys[0] ?? null));
      })
      .catch(() => setTimelines({}))
      .finally(() => setLoading(false));
  }, [selectedCdm]);

  if (loading) {
    return (
      <Card>
        <div className="text-center py-10">
          <Spinner size="large" />
          <p className="text-sm text-text-muted mt-4">{t('quality.loading_timeline', 'Loading snapshot timeline...')}</p>
        </div>
      </Card>
    );
  }

  const domainKeys = Object.keys(timelines);
  if (domainKeys.length === 0) {
    return (
      <Card title={<span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> {t('quality.timeline_title')}</span>}>
        <Empty description={t('quality.timeline_empty')} />
      </Card>
    );
  }

  const currentData = selectedDomain ? timelines[selectedDomain] || [] : [];
  const chartData = currentData.map((p) => ({
    ...p,
    label: `v${p.version}`,
    date: p.created_at ? new Date(p.created_at).toLocaleDateString() : `v${p.version}`,
  }));

  // Compute deltas for latest vs previous
  const latest = currentData.length > 0 ? currentData[currentData.length - 1] : null;
  const previous = currentData.length > 1 ? currentData[currentData.length - 2] : null;

  const delta = (curr: number | null | undefined, prev: number | null | undefined) => {
    if (curr == null || prev == null || prev === 0) return null;
    return ((curr - prev) / Math.abs(prev)) * 100;
  };

  // Determine which metrics to show based on domain
  const isDashboard = selectedDomain === 'Dashboard';
  const isPerson = selectedDomain === 'Person';
  const isObsPeriod = selectedDomain === 'ObservationPeriod';
  const isClinical = !isDashboard && !isPerson && !isObsPeriod;

  return (
    <Card
      title={<span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> {t('quality.timeline_title')}</span>}
      extra={
        <Select
          value={selectedDomain}
          onChange={(val) => setSelectedDomain(val)}
          className="w-52"
          options={domainKeys.map((d) => ({ value: d, label: t(`domains.${d}`, d) }))}
        />
      }
    >
      {/* KPI delta cards */}
      {latest && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          {latest.total_persons != null && (
            <Statistic
              title={t('quality.total_persons')}
              value={latest.total_persons.toLocaleString()}
              suffix={previous ? <DeltaTag value={delta(latest.total_persons, previous.total_persons)} /> : undefined}
            />
          )}
          {latest.total_records != null && (
            <Statistic
              title={t('quality.total_records')}
              value={latest.total_records.toLocaleString()}
              suffix={previous ? <DeltaTag value={delta(latest.total_records, previous.total_records)} /> : undefined}
            />
          )}
          {isClinical && latest.pct_terms_mapped != null && (
            <Statistic
              title={t('quality.pct_mapped')}
              value={latest.pct_terms_mapped.toFixed(1)}
              suffix={<>%{previous ? <DeltaTag value={delta(latest.pct_terms_mapped, previous?.pct_terms_mapped)} /> : null}</>}
            />
          )}
          {isClinical && latest.pct_rows_mapped != null && (
            <Statistic
              title={t('quality.rows') + ' ' + t('quality.pct_mapped')}
              value={latest.pct_rows_mapped.toFixed(1)}
              suffix={<>%{previous ? <DeltaTag value={delta(latest.pct_rows_mapped, previous?.pct_rows_mapped)} /> : null}</>}
            />
          )}
          {isDashboard && latest.avg_pct_terms_mapped != null && (
            <Statistic
              title={t('quality.pct_mapped') + ' (avg)'}
              value={latest.avg_pct_terms_mapped.toFixed(1)}
              suffix={<>%{previous ? <DeltaTag value={delta(latest.avg_pct_terms_mapped, previous?.avg_pct_terms_mapped)} /> : null}</>}
            />
          )}
        </div>
      )}

      {/* Chart */}
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={isMobile ? 200 : 300}>
          <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
            <XAxis dataKey="date" tick={{ fill: ct.axis }} stroke={ct.axis} />
            <YAxis yAxisId="left" tick={{ fill: ct.axis }} stroke={ct.axis} />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tick={{ fill: ct.axis }} stroke={ct.axis} />
            <Tooltip contentStyle={ct.tooltipStyle} />
            <Legend />
            {(isDashboard || isPerson) && (
              <Line yAxisId="left" type="monotone" dataKey="total_persons" name={t('quality.total_persons')} stroke={COLORS[0]} strokeWidth={2} dot />
            )}
            {(isDashboard || isClinical) && chartData.some(d => d.total_records != null) && (
              <Line yAxisId="left" type="monotone" dataKey="total_records" name={t('quality.total_records')} stroke={COLORS[1]} strokeWidth={2} dot />
            )}
            {isClinical && chartData.some(d => d.pct_terms_mapped != null) && (
              <Line yAxisId="right" type="monotone" dataKey="pct_terms_mapped" name={t('quality.pct_mapped')} stroke={COLORS[2]} strokeWidth={2} dot />
            )}
            {isClinical && chartData.some(d => d.pct_rows_mapped != null) && (
              <Line yAxisId="right" type="monotone" dataKey="pct_rows_mapped" name={t('quality.rows') + ' %'} stroke={COLORS[3]} strokeWidth={2} dot />
            )}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="text-center py-5">
          <span className="text-sm text-text-muted">{t('quality.timeline_need_more')}</span>
        </div>
      )}

      {/* Mini sparklines for all domains overview */}
      {domainKeys.length > 1 && (
        <>
          <h5 className="text-sm font-semibold text-text-bright mt-4 mb-2">{t('quality.timeline_overview')}</h5>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {domainKeys.map((dom) => {
              const data = timelines[dom];
              if (data.length < 2) return null;
              const mainMetric = dom === 'Dashboard' || dom === 'Person' ? 'total_persons' : 'total_records';
              return (
                <Card
                  size="small"
                  key={dom}
                  hoverable
                  onClick={() => setSelectedDomain(dom)}
                  className={`cursor-pointer ${dom === selectedDomain ? 'border-emerald-accent' : ''}`}
                >
                  <span className="font-semibold text-xs text-text-bright">{t(`domains.${dom}`, dom)}</span>
                  <ResponsiveContainer width="100%" height={40}>
                    <LineChart data={data}>
                      <Line type="monotone" dataKey={mainMetric} stroke={ct.blue} strokeWidth={1.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

function DeltaTag({ value }: { value: number | null }) {
  if (value == null) return null;
  const color = value > 0 ? 'green' : value < 0 ? 'red' : 'default';
  const icon = value > 0
    ? <TrendingUp className="h-3 w-3 inline mr-0.5" />
    : value < 0
      ? <TrendingDown className="h-3 w-3 inline mr-0.5" />
      : null;
  return (
    <Tag color={color} className="ml-1">
      {icon}{value > 0 ? '+' : ''}{value.toFixed(1)}%
    </Tag>
  );
}
