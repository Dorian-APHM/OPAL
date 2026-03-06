import { useState, useEffect } from 'react';
import {
  Card, Button, Spin, Typography, Table, Tag, Space, Statistic,
  Row, Col, Progress, Collapse, Descriptions, Alert, Empty, Tooltip,
  message,
} from 'antd';
import {
  TableOutlined, TeamOutlined, MedicineBoxOutlined, ExperimentOutlined,
  HeartOutlined, EyeOutlined, ScheduleOutlined, DownloadOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { cohortApi } from '../../api/client';
import type { CohortCriteria, CharacterizationResult } from '../../types';

const { Text, Title } = Typography;

const DOMAIN_COLORS: Record<string, string> = {
  Condition: '#f5222d',
  Drug: '#1890ff',
  Procedure: '#52c41a',
  Measurement: '#fa8c16',
  Observation: '#722ed1',
  Device: '#13c2c2',
  Visit: '#eb2f96',
};

const DOMAIN_ICONS: Record<string, React.ReactNode> = {
  Condition: <HeartOutlined />,
  Drug: <MedicineBoxOutlined />,
  Procedure: <ScheduleOutlined />,
  Measurement: <ExperimentOutlined />,
  Observation: <EyeOutlined />,
  Device: <MedicineBoxOutlined />,
};

const PIE_COLORS = ['#1890ff', '#f5222d', '#52c41a', '#fa8c16', '#722ed1', '#13c2c2', '#eb2f96', '#aaa'];

interface Props {
  cdmName: string;
  criteria: CohortCriteria;
  cohortId?: number;
}

export default function CharacterizationPanel({ cdmName, criteria, cohortId }: Props) {
  const { t } = useTranslation();
  const [result, setResult] = useState<CharacterizationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [error, setError] = useState('');
  const [characterizedAt, setCharacterizedAt] = useState<string | null>(null);

  const hasCriteria =
    criteria.inclusion.criteria.length > 0 ||
    criteria.demographics?.age ||
    criteria.demographics?.gender;

  // Load saved characterization when cohortId changes
  useEffect(() => {
    if (!cohortId) {
      setResult(null);
      setCharacterizedAt(null);
      return;
    }
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
  }, [cohortId]);

  const runCharacterization = async () => {
    if (!cdmName || !hasCriteria) return;
    setLoading(true);
    setError('');
    try {
      const resp = await cohortApi.characterize(cdmName, criteria);
      setResult(resp.data);
      setCharacterizedAt(new Date().toISOString());

      // Auto-save if cohort is saved
      if (cohortId) {
        try {
          await cohortApi.saveCharacterization(cohortId, resp.data);
          message.success(t('cohort.characterization_saved', 'Characterization saved'));
        } catch {
          // non-blocking — results are still displayed
        }
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Characterization failed');
    } finally {
      setLoading(false);
    }
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
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('cohort.define_criteria_first', 'Define cohort criteria to run characterization')}
        />
      </Card>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header */}
      <Card size="small">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space>
            <TableOutlined style={{ fontSize: 18 }} />
            <Title level={5} style={{ margin: 0 }}>Table 1 — Cohort Characterization</Title>
          </Space>
          <Space>
            {characterizedAt && (
              <Tooltip title={`Last run: ${new Date(characterizedAt).toLocaleString()}`}>
                <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 14 }} />
              </Tooltip>
            )}
            {result && (
              <Button size="small" icon={<DownloadOutlined />} onClick={exportCsv}>
                CSV
              </Button>
            )}
            <Button
              type="primary"
              size="small"
              onClick={runCharacterization}
              loading={loading}
              disabled={!hasCriteria || !cdmName}
            >
              {result ? t('cohort.refresh', 'Refresh') : t('cohort.run_characterization', 'Run Characterization')}
            </Button>
          </Space>
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {(loading || loadingSaved) && (
        <Card size="small">
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16 }}>
              <Text type="secondary">
                {loadingSaved ? t('cohort.loading_saved', 'Loading saved results...') : 'Running characterization queries...'}
              </Text>
            </div>
          </div>
        </Card>
      )}

      {result && !loading && (
        <>
          {/* Cohort Size */}
          <Card size="small">
            <Statistic
              title={<Space><TeamOutlined />{t('cohort.cohort_size', 'Cohort Size')}</Space>}
              value={result.cohort_size}
              valueStyle={{ color: '#1890ff', fontSize: 28 }}
              suffix="patients"
            />
          </Card>

          {/* Demographics */}
          <Card size="small" title={t('cohort.demographics', 'Demographics')}>
            <Row gutter={[16, 16]}>
              {/* Age Stats */}
              <Col span={24}>
                <Descriptions size="small" bordered column={{ xs: 2, sm: 3, md: 4 }}>
                  <Descriptions.Item label="Mean Age">
                    {result.demographics.age.mean_age ?? '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="SD">
                    {result.demographics.age.std_age ?? '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="Median">
                    {result.demographics.age.median_age ?? '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="Range">
                    {result.demographics.age.min_age ?? '?'}–{result.demographics.age.max_age ?? '?'}
                  </Descriptions.Item>
                  <Descriptions.Item label="IQR">
                    {result.demographics.age.q1_age ?? '?'}–{result.demographics.age.q3_age ?? '?'}
                  </Descriptions.Item>
                </Descriptions>
              </Col>

              {/* Age Distribution Bar Chart */}
              {result.demographics.age_groups.length > 0 && (
                <Col xs={24} md={12}>
                  <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Age Distribution
                  </Text>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={result.demographics.age_groups} margin={{ left: -10 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="age_group" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} />
                      <Bar dataKey="count" fill="#1890ff" />
                    </BarChart>
                  </ResponsiveContainer>
                </Col>
              )}

              {/* Gender Pie */}
              {result.demographics.gender.length > 0 && (
                <Col xs={24} md={12}>
                  <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Gender
                  </Text>
                  <div style={{ display: 'flex', alignItems: 'center' }}>
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
                    <div style={{ flex: 1 }}>
                      {result.demographics.gender.map((g, i) => (
                        <div key={i} style={{ fontSize: 11, marginBottom: 2 }}>
                          <span style={{
                            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                            backgroundColor: PIE_COLORS[i % PIE_COLORS.length], marginRight: 4,
                          }} />
                          {g.label}: <strong>{g.count.toLocaleString()}</strong>
                          {' '}({result.cohort_size > 0 ? ((g.count / result.cohort_size) * 100).toFixed(1) : 0}%)
                        </div>
                      ))}
                    </div>
                  </div>
                </Col>
              )}

              {/* Race */}
              {result.demographics.race.length > 1 && (
                <Col xs={24} md={12}>
                  <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Race
                  </Text>
                  <Table
                    size="small"
                    dataSource={result.demographics.race}
                    rowKey={(_, i) => String(i)}
                    pagination={false}
                    showHeader={false}
                    columns={[
                      { dataIndex: 'label', key: 'label', ellipsis: true },
                      {
                        dataIndex: 'count', key: 'count', width: 80, align: 'right' as const,
                        render: (v: number) => v?.toLocaleString(),
                      },
                      {
                        key: 'pct', width: 60, align: 'right' as const,
                        render: (_, r: any) =>
                          result.cohort_size > 0
                            ? `${((r.count / result.cohort_size) * 100).toFixed(1)}%`
                            : '—',
                      },
                    ]}
                  />
                </Col>
              )}

              {/* Ethnicity */}
              {result.demographics.ethnicity.length > 1 && (
                <Col xs={24} md={12}>
                  <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                    Ethnicity
                  </Text>
                  <Table
                    size="small"
                    dataSource={result.demographics.ethnicity}
                    rowKey={(_, i) => String(i)}
                    pagination={false}
                    showHeader={false}
                    columns={[
                      { dataIndex: 'label', key: 'label', ellipsis: true },
                      {
                        dataIndex: 'count', key: 'count', width: 80, align: 'right' as const,
                        render: (v: number) => v?.toLocaleString(),
                      },
                      {
                        key: 'pct', width: 60, align: 'right' as const,
                        render: (_, r: any) =>
                          result.cohort_size > 0
                            ? `${((r.count / result.cohort_size) * 100).toFixed(1)}%`
                            : '—',
                      },
                    ]}
                  />
                </Col>
              )}
            </Row>
          </Card>

          {/* Observation Period */}
          {result.observation_period && result.observation_period.n_persons > 0 && (
            <Card size="small" title={t('cohort.observation_period', 'Observation Period')}>
              <Descriptions size="small" bordered column={{ xs: 2, sm: 3, md: 4 }}>
                <Descriptions.Item label="Persons">
                  {result.observation_period.n_persons?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="Mean Duration">
                  {result.observation_period.mean_days != null
                    ? `${Math.round(result.observation_period.mean_days / 365.25 * 10) / 10} yrs`
                    : '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Median Duration">
                  {result.observation_period.median_days != null
                    ? `${Math.round(result.observation_period.median_days / 365.25 * 10) / 10} yrs`
                    : '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Range">
                  {result.observation_period.earliest_start?.substring(0, 10) ?? '?'} — {result.observation_period.latest_end?.substring(0, 10) ?? '?'}
                </Descriptions.Item>
              </Descriptions>
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
            <div style={{ marginBottom: 12 }}>
              {result.domain_prevalence.map(dp => (
                <div key={dp.domain} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <Tag color={DOMAIN_COLORS[dp.domain] || '#999'} style={{ width: 100, textAlign: 'center' }}>
                    {DOMAIN_ICONS[dp.domain]} {dp.domain}
                  </Tag>
                  <Progress
                    percent={dp.pct_with_data}
                    size="small"
                    style={{ flex: 1, margin: 0 }}
                    strokeColor={DOMAIN_COLORS[dp.domain] || '#999'}
                    format={pct => `${dp.patients_with_data.toLocaleString()} (${pct}%)`}
                  />
                </div>
              ))}
            </div>

            {/* Top concepts per domain */}
            <Collapse
              size="small"
              items={result.domain_prevalence
                .filter(dp => dp.top_concepts.length > 0)
                .map(dp => ({
                  key: dp.domain,
                  label: (
                    <Space>
                      <Tag color={DOMAIN_COLORS[dp.domain] || '#999'}>{dp.domain}</Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Top {dp.top_concepts.length} concepts
                      </Text>
                    </Space>
                  ),
                  children: (
                    <Table
                      size="small"
                      dataSource={dp.top_concepts}
                      rowKey="concept_id"
                      pagination={false}
                      scroll={{ x: true }}
                      columns={[
                        {
                          title: 'Concept', dataIndex: 'concept_name', key: 'name', ellipsis: true,
                          render: (name: string, rec: any) => (
                            <Tooltip title={`${rec.concept_code} · ${rec.vocabulary_id} · ID: ${rec.concept_id}`}>
                              <span style={{ fontSize: 11 }}>{name}</span>
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
                            <Text style={{ fontSize: 11 }}>{v}%</Text>
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
              <Space>
                <ExperimentOutlined />
                {t('cohort.measurement_stats', 'Measurement Value Statistics')}
              </Space>
            }>
              <Table
                size="small"
                dataSource={result.measurement_stats}
                rowKey="concept_id"
                pagination={false}
                scroll={{ x: true }}
                columns={[
                  {
                    title: 'Measurement', dataIndex: 'concept_name', key: 'name',
                    ellipsis: true, width: 180,
                    render: (name: string, rec: any) => (
                      <Tooltip title={`${rec.concept_code} · ID: ${rec.concept_id}`}>
                        <span style={{ fontSize: 11 }}>{name}</span>
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
                    render: (v: string) => <Text type="secondary" style={{ fontSize: 10 }}>{v || '—'}</Text>,
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
