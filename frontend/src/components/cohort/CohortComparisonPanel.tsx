import { useState } from 'react';
import {
  Card, Button, Select, Spin, Typography, Table, Tag, Space, Statistic,
  Row, Col, Collapse, Descriptions, Alert, Empty, Tooltip, Switch, message,
} from 'antd';
import {
  SwapOutlined, DownloadOutlined, TeamOutlined,
} from '@ant-design/icons';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine,
  Tooltip as RechartsTooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { cohortApi } from '../../api/client';
import type { CohortSummary, CohortComparisonResult, CohortComparisonVariable } from '../../types';

const { Text, Title } = Typography;

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
  const color = abs < 0.1 ? 'green' : abs < 0.2 ? 'orange' : 'red';
  return <Tag color={color}>{smd.toFixed(3)}</Tag>;
}

const DOMAIN_COLORS: Record<string, string> = {
  Condition: '#f5222d',
  Drug: '#1890ff',
  Procedure: '#52c41a',
  Measurement: '#fa8c16',
  Observation: '#722ed1',
  Device: '#13c2c2',
  Visit: '#eb2f96',
};

export default function CohortComparisonPanel({ cdmName, cohorts }: Props) {
  const { t } = useTranslation();
  const [cohortIdA, setCohortIdA] = useState<number | undefined>();
  const [cohortIdB, setCohortIdB] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CohortComparisonResult | null>(null);
  const [visitLevel, setVisitLevel] = useState(false);

  const runCompare = async () => {
    if (!cdmName || !cohortIdA || !cohortIdB) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const resp = await cohortApi.compare(cdmName, cohortIdA, cohortIdB, visitLevel);
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
    // Demographics details
    const d = result.demographics;
    lines.push(`Demographics,Age (mean),${d.age.mean_a ?? ''},${d.age.mean_b ?? ''},${d.age.smd ?? ''}`);
    for (const g of d.gender) lines.push(`Demographics,"Gender: ${g.label}",${g.pct_a}%,${g.pct_b}%,${g.smd ?? ''}`);
    for (const r of d.race) lines.push(`Demographics,"Race: ${r.label}",${r.pct_a}%,${r.pct_b}%,${r.smd ?? ''}`);
    // Domain concepts
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
    value: c.id,
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Selection */}
      <Card size="small">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space>
            <SwapOutlined style={{ fontSize: 18 }} />
            <Title level={5} style={{ margin: 0 }}>
              {t('cohort.compare_cohorts', 'Compare Cohorts')}
            </Title>
          </Space>
          <Space>
            {result && (
              <Button size="small" icon={<DownloadOutlined />} onClick={exportCsv}>
                CSV
              </Button>
            )}
          </Space>
        </div>
        <Row gutter={8} style={{ marginTop: 12 }}>
          <Col span={10}>
            <Select
              placeholder={t('cohort.select_cohort_a', 'Cohort A')}
              options={cohortOptions}
              value={cohortIdA}
              onChange={setCohortIdA}
              style={{ width: '100%' }}
              size="small"
              showSearch
              optionFilterProp="label"
            />
          </Col>
          <Col span={10}>
            <Select
              placeholder={t('cohort.select_cohort_b', 'Cohort B')}
              options={cohortOptions}
              value={cohortIdB}
              onChange={setCohortIdB}
              style={{ width: '100%' }}
              size="small"
              showSearch
              optionFilterProp="label"
            />
          </Col>
          <Col span={4}>
            <Button
              type="primary"
              size="small"
              block
              onClick={runCompare}
              loading={loading}
              disabled={!cohortIdA || !cohortIdB || cohortIdA === cohortIdB}
            >
              {t('cohort.compare', 'Compare')}
            </Button>
          </Col>
        </Row>
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
          <Tooltip title={
            visitLevel
              ? t('cohort.visit_level_on', 'Clinical data restricted to the qualifying visit only')
              : t('cohort.visit_level_off', 'All patient data across all visits (standard)')
          }>
            <Space size={4}>
              <Switch
                size="small"
                checked={visitLevel}
                onChange={setVisitLevel}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('cohort.visit_level', 'Visit-level')}
              </Text>
            </Space>
          </Tooltip>
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {loading && (
        <Card size="small">
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16 }}>
              <Text type="secondary">{t('cohort.comparing', 'Comparing cohorts...')}</Text>
            </div>
          </div>
        </Card>
      )}

      {!result && !loading && !error && (
        <Card size="small">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t('cohort.select_two_cohorts', 'Select two cohorts to compare')}
          />
        </Card>
      )}

      {result && !loading && (
        <>
          {/* Cohort sizes */}
          <Row gutter={8}>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title={<Space><TeamOutlined /><Text strong>{result.cohort_a_name}</Text></Space>}
                  value={result.cohort_a_size}
                  suffix="patients"
                  valueStyle={{ color: '#1890ff', fontSize: 22 }}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small">
                <Statistic
                  title={<Space><TeamOutlined /><Text strong>{result.cohort_b_name}</Text></Space>}
                  value={result.cohort_b_size}
                  suffix="patients"
                  valueStyle={{ color: '#722ed1', fontSize: 22 }}
                />
              </Card>
            </Col>
          </Row>

          {/* SMD Legend */}
          <Card size="small" bodyStyle={{ padding: '6px 12px' }}>
            <Space>
              <Text type="secondary" style={{ fontSize: 11 }}>SMD:</Text>
              <Tag color="green">&lt; 0.1 balanced</Tag>
              <Tag color="orange">0.1–0.2 small imbalance</Tag>
              <Tag color="red">&gt; 0.2 imbalanced</Tag>
            </Space>
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
                columns={[
                  {
                    title: 'Domain', dataIndex: 'domain', key: 'd',
                    render: (d: string) => <Tag color={DOMAIN_COLORS[d] || '#999'}>{d}</Tag>,
                  },
                  { title: result.cohort_a_name, dataIndex: 'pct_a', key: 'a', width: 120, align: 'right' as const },
                  { title: result.cohort_b_name, dataIndex: 'pct_b', key: 'b', width: 120, align: 'right' as const },
                  {
                    title: 'SMD', dataIndex: 'smd', key: 'smd', width: 90, align: 'center' as const,
                    render: (smd: number | null) => <SmdTag smd={smd} />,
                  },
                ]}
                style={{ marginBottom: 12 }}
              />

              {/* Per-domain concept details */}
              <Collapse
                size="small"
                items={result.domain_prevalence
                  .filter(dp => dp.concepts.length > 0)
                  .map(dp => ({
                    key: dp.domain,
                    label: (
                      <Space>
                        <Tag color={DOMAIN_COLORS[dp.domain] || '#999'}>{dp.domain}</Tag>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {dp.concepts.length} concepts
                        </Text>
                      </Space>
                    ),
                    children: (
                      <Table
                        size="small"
                        dataSource={dp.concepts}
                        rowKey="concept_id"
                        pagination={false}
                        scroll={{ x: true }}
                        columns={[
                          { title: 'Concept', dataIndex: 'concept_name', key: 'name', ellipsis: true },
                          { title: result.cohort_a_name, key: 'a', width: 100, align: 'right' as const, render: (_, r) => `${r.pct_persons_a}%` },
                          { title: result.cohort_b_name, key: 'b', width: 100, align: 'right' as const, render: (_, r) => `${r.pct_persons_b}%` },
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
                scroll={{ x: true }}
                columns={[
                  { title: 'Measurement', dataIndex: 'concept_name', key: 'name', ellipsis: true, width: 160 },
                  {
                    title: `Mean (${result.cohort_a_name})`, key: 'mean_a', width: 100, align: 'right' as const,
                    render: (_, r) => r.mean_a != null ? r.mean_a.toFixed(1) : '—',
                  },
                  {
                    title: `Mean (${result.cohort_b_name})`, key: 'mean_b', width: 100, align: 'right' as const,
                    render: (_, r) => r.mean_b != null ? r.mean_b.toFixed(1) : '—',
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
                  { title: result.cohort_a_name, key: 'a', width: 100, align: 'right' as const, render: (_, r) => `${r.pct_persons_a}%` },
                  { title: result.cohort_b_name, key: 'b', width: 100, align: 'right' as const, render: (_, r) => `${r.pct_persons_b}%` },
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
            <Descriptions size="small" bordered column={3}>
              <Descriptions.Item label="Mean Duration (A)">
                {result.observation_period.mean_days_a != null
                  ? `${Math.round(result.observation_period.mean_days_a)} days`
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="Mean Duration (B)">
                {result.observation_period.mean_days_b != null
                  ? `${Math.round(result.observation_period.mean_days_b)} days`
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="SMD">
                <SmdTag smd={result.observation_period.smd} />
              </Descriptions.Item>
            </Descriptions>
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
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" domain={[0, 'auto']} tick={{ fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="variable"
                    width={200}
                    tick={{ fontSize: 9 }}
                  />
                  <RechartsTooltip
                    formatter={(value: number) => value.toFixed(3)}
                    labelFormatter={(label: string) => label}
                  />
                  <ReferenceLine x={0.1} stroke="#faad14" strokeDasharray="5 5" label={{ value: '0.1', fontSize: 10 }} />
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
