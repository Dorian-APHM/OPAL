import { useTranslation } from 'react-i18next';
import { Download } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
  LineChart, Line, Area, AreaChart,
} from 'recharts';
import type {
  DashboardResults,
  PersonResults,
  ObsPeriodResults,
  ClinicalResults,
} from '../../types';
import { qualityApi, authDownload } from '../../api/client';
import { Card, Table, Tag, Button, Statistic } from '../ui';
import type { Column } from '../ui';

const COLORS = {
  primary: '#3B82F6',
  green: '#10B981',
  orange: '#ff7f0e',
  purple: '#9467bd',
  areaFill: 'rgba(31, 119, 180, 0.1)',
  gender: {
    FEMALE: '#e74c3c',
    MALE: '#3498db',
    UNKNOWN: '#95a5a6',
    OTHER: '#f39c12',
  } as Record<string, string>,
};

const RACE_COLORS = ['#10B981', '#14b8a6', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#6366F1'];

function getGenderColor(name: string): string {
  const upper = name.toUpperCase();
  return COLORS.gender[upper] || COLORS.gender.OTHER;
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString();
}

function ExportButton({ snapshotId, tableType }: { snapshotId?: number; tableType: string }) {
  const { t } = useTranslation();
  if (!snapshotId) return null;
  return (
    <Button
      size="small"
      icon={<Download className="h-3.5 w-3.5" />}
      onClick={() => authDownload(qualityApi.exportCsv(snapshotId, tableType))}
    >
      {t('common.export_csv')}
    </Button>
  );
}

interface Props {
  results: any;
  snapshotId?: number;
}

export default function AnalysisResults({ results, snapshotId }: Props) {
  if (!results) return null;
  const domain = results.domain;

  if (domain === 'Dashboard') return <DashboardView data={results} snapshotId={snapshotId} />;
  if (domain === 'Person') return <PersonView data={results} />;
  if (domain === 'ObservationPeriod') return <ObsPeriodView data={results} snapshotId={snapshotId} />;
  return <ClinicalView data={results} snapshotId={snapshotId} />;
}

// ============ SPARKLINE MINI CHART ============
function MiniSparkline({ data }: { data?: number[] }) {
  if (!data || data.length === 0) return <span>-</span>;
  const chartData = data.map((v) => ({ v }));
  return (
    <ResponsiveContainer width={80} height={24}>
      <AreaChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <Area type="monotone" dataKey="v" stroke={COLORS.primary} fill={COLORS.areaFill} strokeWidth={1} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ============ DASHBOARD ============
function DashboardView({ data, snapshotId }: { data: DashboardResults; snapshotId?: number }) {
  const { t } = useTranslation();
  const summary = data.summary;

  const statsColumns: Column<any>[] = [
    { title: t('quality.domain'), dataIndex: 'domain', key: 'domain',
      render: (d: string) => t(`domains.${d}`, d) },
    { title: t('quality.total_records'), dataIndex: 'total_records', key: 'total_records',
      render: formatNumber, sorter: (a: any, b: any) => a.total_records - b.total_records },
    { title: t('quality.distinct_persons'), dataIndex: 'distinct_persons', key: 'distinct_persons',
      render: formatNumber },
    { title: t('quality.pct_persons'), dataIndex: 'pct_persons', key: 'pct_persons',
      render: (v: number) => `${v.toFixed(1)}%` },
    { title: 'Trend', dataIndex: 'sparkline', key: 'sparkline',
      render: (sparkline: number[]) => <MiniSparkline data={sparkline} />,
      width: 100 },
  ];

  const mappingColumns: Column<any>[] = [
    { title: t('quality.domain'), dataIndex: 'domain', key: 'domain',
      render: (d: string) => t(`domains.${d}`, d) },
    { title: t('quality.total') + ' ' + t('quality.terms'), dataIndex: 'total_terms', key: 'total_terms',
      render: formatNumber },
    { title: t('quality.mapped'), dataIndex: 'mapped_terms', key: 'mapped_terms',
      render: formatNumber },
    { title: t('quality.unmapped'), dataIndex: 'unmapped_terms', key: 'unmapped_terms',
      render: formatNumber },
    { title: t('quality.pct_mapped'), dataIndex: 'pct_terms_mapped', key: 'pct_terms_mapped',
      render: (v: number) => {
        const color = v >= 80 ? 'green' : v >= 50 ? 'orange' : 'red';
        return <Tag color={color}>{v.toFixed(1)}%</Tag>;
      }},
  ];

  return (
    <div>
      <Card className="mb-4 text-center">
        <Statistic title={t('quality.total_persons')} value={formatNumber(summary.total_persons)} />
      </Card>
      <Card
        title={t('quality.domain_stats')}
        className="mb-4"
        extra={<ExportButton snapshotId={snapshotId} tableType="domain_stats" />}
      >
        <Table
          dataSource={summary.domains.filter((d: any) => !d.error)}
          columns={statsColumns}
          rowKey="domain"
          pagination={false}
          size="small"
        />
      </Card>
      <Card title={t('quality.mapping_by_domain')}>
        <Table
          dataSource={summary.domains.filter((d: any) => !d.error)}
          columns={mappingColumns}
          rowKey="domain"
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  );
}

// ============ PERSON ============
function PersonView({ data }: { data: PersonResults }) {
  const { t } = useTranslation();
  const ps = data.achilles_like.person_summary;

  const genderData = ps.gender_distribution.gender_name.map((name, i) => ({
    name,
    value: ps.gender_distribution.count[i],
    color: getGenderColor(name),
  }));

  const birthData = ps.birth_year_distribution.year_of_birth.map((year, i) => ({
    year,
    count: ps.birth_year_distribution.count[i],
  }));

  const raceData = ps.race_distribution?.race_name?.map((name, i) => ({
    name: name || 'N/A',
    value: ps.race_distribution!.count[i],
  })).filter(d => d.value > 0) || [];

  const ethData = ps.ethnicity_distribution?.ethnicity_name?.map((name, i) => ({
    name: name || 'N/A',
    value: ps.ethnicity_distribution!.count[i],
  })).filter(d => d.value > 0) || [];

  return (
    <div>
      <Card className="mb-4 text-center">
        <Statistic title={t('quality.total_persons')} value={formatNumber(ps.total_persons)} />
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title={t('quality.gender_distribution')} className="mb-4">
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={genderData}
                cx="50%" cy="50%"
                innerRadius={60} outerRadius={100}
                dataKey="value"
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(1)}%`}
              >
                {genderData.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </Card>
        <Card title={t('quality.birth_year')} className="mb-4">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={birthData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" />
              <YAxis />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Bar dataKey="count" fill={COLORS.green} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* Race & Ethnicity */}
      {(raceData.length > 0 || ethData.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {raceData.length > 0 && (
            <div className={ethData.length > 0 ? '' : 'md:col-span-2'}>
              <Card title={t('quality.race_distribution', 'Race Distribution')} className="mb-4">
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie
                      data={raceData}
                      cx="50%" cy="50%"
                      outerRadius={100}
                      dataKey="value"
                      label={({ name, percent }) => percent > 0.02 ? `${name} ${(percent * 100).toFixed(1)}%` : ''}
                    >
                      {raceData.map((_, i) => (
                        <Cell key={i} fill={RACE_COLORS[i % RACE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number) => formatNumber(v)} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </Card>
            </div>
          )}
          {ethData.length > 0 && (
            <div className={raceData.length > 0 ? '' : 'md:col-span-2'}>
              <Card title={t('quality.ethnicity_distribution', 'Ethnicity Distribution')} className="mb-4">
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie
                      data={ethData}
                      cx="50%" cy="50%"
                      outerRadius={100}
                      dataKey="value"
                      label={({ name, percent }) => percent > 0.02 ? `${name} ${(percent * 100).toFixed(1)}%` : ''}
                    >
                      {ethData.map((_, i) => (
                        <Cell key={i} fill={RACE_COLORS[(i + 3) % RACE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number) => formatNumber(v)} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============ OBSERVATION PERIOD ============
function ObsPeriodView({ data, snapshotId }: { data: ObsPeriodResults; snapshotId?: number }) {
  const { t } = useTranslation();
  const al = data.achilles_like;

  const ageData = al.age_at_first_observation.age.map((age, i) => ({
    age, count: al.age_at_first_observation.count[i],
  }));

  const obsLengthData = al.observation_length_months.months.map((m, i) => ({
    months: m, n_persons: al.observation_length_months.n_persons[i],
  }));

  const cumulData = al.cumulative_observation.months_threshold.map((m, i) => ({
    months: m, pct: al.cumulative_observation.pct_persons[i],
  }));

  const contData = al.continuous_observation_by_year.year.map((y, i) => ({
    year: y, n_persons: al.continuous_observation_by_year.n_persons[i],
  }));

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title={t('quality.age_first_obs')} className="mb-4">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={ageData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="age" />
              <YAxis />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Bar dataKey="count" fill={COLORS.primary} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card
          title={t('quality.age_by_gender')}
          className="mb-4"
          extra={<ExportButton snapshotId={snapshotId} tableType="age_by_gender" />}
        >
          <Table
            dataSource={al.age_by_gender.rows}
            columns={[
              { title: 'Gender', dataIndex: 'gender_name', key: 'gender_name' },
              { title: 'N', dataIndex: 'n', key: 'n', render: formatNumber },
              { title: 'P10', dataIndex: 'p10', key: 'p10', render: (v: number) => v?.toFixed(1) },
              { title: 'P25', dataIndex: 'p25', key: 'p25', render: (v: number) => v?.toFixed(1) },
              { title: 'Median', dataIndex: 'median_age', key: 'median', render: (v: number) => v?.toFixed(1) },
              { title: 'P75', dataIndex: 'p75', key: 'p75', render: (v: number) => v?.toFixed(1) },
              { title: 'P90', dataIndex: 'p90', key: 'p90', render: (v: number) => v?.toFixed(1) },
            ]}
            rowKey="gender_name"
            pagination={false}
            size="small"
          />
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title={t('quality.obs_length')} className="mb-4">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={obsLengthData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="months" />
              <YAxis />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Bar dataKey="n_persons" fill={COLORS.primary} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card
          title={t('quality.duration_by_gender')}
          className="mb-4"
          extra={<ExportButton snapshotId={snapshotId} tableType="duration_by_gender" />}
        >
          <Table
            dataSource={al.duration_by_gender.rows}
            columns={[
              { title: 'Gender', dataIndex: 'gender_name', key: 'gender_name' },
              { title: 'N', dataIndex: 'n', key: 'n', render: formatNumber },
              { title: 'P10', dataIndex: 'p10', key: 'p10', render: (v: number) => v?.toFixed(1) },
              { title: 'P25', dataIndex: 'p25', key: 'p25', render: (v: number) => v?.toFixed(1) },
              { title: 'Median', dataIndex: 'median_months', key: 'median', render: (v: number) => v?.toFixed(1) },
              { title: 'P75', dataIndex: 'p75', key: 'p75', render: (v: number) => v?.toFixed(1) },
              { title: 'P90', dataIndex: 'p90', key: 'p90', render: (v: number) => v?.toFixed(1) },
            ]}
            rowKey="gender_name"
            pagination={false}
            size="small"
          />
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title={t('quality.cumulative_obs')} className="mb-4">
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={cumulData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="months" />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
              <Area type="monotone" dataKey="pct" stroke={COLORS.primary} fill={COLORS.areaFill} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card title={t('quality.continuous_obs')} className="mb-4">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={contData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" />
              <YAxis />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Line type="monotone" dataKey="n_persons" stroke={COLORS.primary} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

// ============ CLINICAL DOMAINS ============
function ClinicalView({ data, snapshotId }: { data: ClinicalResults; snapshotId?: number }) {
  const { t } = useTranslation();
  const al = data.achilles_like;
  const mapping = data.mapping;
  const avgPerPerson = al.global.distinct_persons > 0
    ? (al.global.total_rows / al.global.distinct_persons).toFixed(1)
    : '-';

  const monthlyData = al.by_month.month_start.map((m, i) => ({
    month: m, count: al.by_month.count[i],
  }));

  const rppData = al.records_per_person.records_per_person.map((r, i) => ({
    records: r, n_persons: al.records_per_person.n_persons[i],
  }));

  const conceptColumns: Column<any>[] = [
    { title: t('quality.concept_id'), dataIndex: 'concept_id', key: 'concept_id', width: 100 },
    { title: t('quality.concept_name'), dataIndex: 'concept_name', key: 'concept_name' },
    { title: t('quality.source_value'), dataIndex: 'source_value', key: 'source_value', ellipsis: true },
    { title: t('quality.n_records'), dataIndex: 'n_records', key: 'n_records',
      render: formatNumber, sorter: (a: any, b: any) => a.n_records - b.n_records },
    { title: t('quality.n_persons'), dataIndex: 'n_persons', key: 'n_persons', render: formatNumber },
  ];

  const unmappedColumns: Column<any>[] = [
    { title: t('quality.source_value'), dataIndex: 'source_value', key: 'source_value' },
    ...(mapping.top_unmapped_terms?.[0]?.source_name !== undefined
      ? [{ title: t('quality.source_name'), dataIndex: 'source_name', key: 'source_name' }]
      : []),
    { title: t('quality.occurrences'), dataIndex: 'count', key: 'count', render: formatNumber,
      sorter: (a: any, b: any) => a.count - b.count },
  ];

  return (
    <div>
      {/* Global stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <Card><Statistic title={t('quality.total_records')} value={formatNumber(al.global.total_rows)} /></Card>
        <Card><Statistic title={t('quality.distinct_persons')} value={formatNumber(al.global.distinct_persons)} /></Card>
        <Card><Statistic title={t('quality.avg_per_person')} value={avgPerPerson} /></Card>
      </div>

      {/* Monthly evolution */}
      <Card title={t('quality.monthly_evolution')} className="mb-4">
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart data={monthlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tickFormatter={(v) => v.substring(0, 7)} />
            <YAxis />
            <Tooltip labelFormatter={(v) => v} formatter={(v: number) => formatNumber(v)} />
            <Area type="monotone" dataKey="count" stroke={COLORS.primary} fill={COLORS.areaFill} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* Records per person */}
      <Card title={t('quality.records_per_person')} className="mb-4">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={rppData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="records" />
            <YAxis />
            <Tooltip formatter={(v: number) => formatNumber(v)} />
            <Bar dataKey="n_persons" fill={COLORS.primary} />
          </BarChart>
        </ResponsiveContainer>
        <span className="text-xs text-text-muted">Cap: {al.records_per_person.max_bin}</span>
      </Card>

      {/* Top concepts */}
      <Card
        title={t('quality.top_concepts')}
        className="mb-4"
        extra={<ExportButton snapshotId={snapshotId} tableType="top_concepts" />}
      >
        <Table dataSource={al.top_concepts} columns={conceptColumns} rowKey="concept_id" pagination={{ pageSize: 20 }} size="small" scroll={{ x: true }} />
      </Card>

      {/* Mapping quality */}
      <Card title={t('quality.mapping_quality')} className="mb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div>
            <h5 className="text-sm font-semibold text-text-bright mb-3">{t('quality.terms')}</h5>
            <div className="grid grid-cols-2 gap-4">
              <Statistic title={t('quality.total')} value={formatNumber(mapping.terms.total_terms)} />
              <Statistic title={t('quality.mapped')} value={formatNumber(mapping.terms.mapped_terms)} />
              <Statistic title={t('quality.unmapped')} value={formatNumber(mapping.terms.unmapped_terms)} />
              <Statistic title={t('quality.pct_mapped')} value={mapping.terms.pct_terms_mapped?.toFixed(1) || '-'} suffix="%" />
            </div>
          </div>
          <div>
            <h5 className="text-sm font-semibold text-text-bright mb-3">{t('quality.rows')}</h5>
            <div className="grid grid-cols-2 gap-4">
              <Statistic title={t('quality.total')} value={formatNumber(mapping.rows.total_rows)} />
              <Statistic title={t('quality.mapped')} value={formatNumber(mapping.rows.mapped_rows)} />
              <Statistic title={t('quality.unmapped')} value={formatNumber(mapping.rows.unmapped_rows)} />
              <Statistic title={t('quality.pct_mapped')} value={mapping.rows.pct_rows_mapped?.toFixed(1) || '-'} suffix="%" />
            </div>
          </div>
        </div>
      </Card>

      {/* Top unmapped terms */}
      {mapping.top_unmapped_terms && mapping.top_unmapped_terms.length > 0 && (
        <Card
          title={t('quality.top_unmapped')}
          extra={<ExportButton snapshotId={snapshotId} tableType="top_unmapped" />}
        >
          <Table dataSource={mapping.top_unmapped_terms} columns={unmappedColumns} rowKey="source_value" pagination={{ pageSize: 20 }} size="small" />
        </Card>
      )}
    </div>
  );
}
