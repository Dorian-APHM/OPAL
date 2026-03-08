import { useState, useEffect } from 'react';
import {
  Card, Select, Button, Space, Typography, Row, Col, Statistic,
  Empty, message, Spin, Radio, Checkbox, Tag, Divider, Table,
} from 'antd';
import { LineChartOutlined, CalculatorOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, AreaChart, Legend, ReferenceLine,
} from 'recharts';
import { cohortApi, estimationApi } from '../api/client';
import type { CohortSummary, KaplanMeierResult, KMPoint } from '../types';

const { Title, Text } = Typography;
const { Option } = Select;

const STRATA_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b'];

export default function EstimationPage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
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
      message.error(e.message || 'Computation failed');
    } finally {
      setComputing(false);
    }
  };

  if (!selectedCdm) return <Card><Empty description="Select a CDM first" /></Card>;

  // Prepare chart data
  const chartData = result ? prepareChartData(result) : [];
  const strataNames = result ? Object.keys(result.strata) : [];
  const hasStrata = strataNames.length > 0;

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Title level={4}><LineChartOutlined /> {t('estimation.kaplan_meier', 'Kaplan-Meier Survival')}</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Row gutter={16}>
            <Col span={12}>
              <Text strong>{t('estimation.target_cohort', 'Target Cohort')}</Text>
              <Select
                placeholder="Select target cohort..."
                value={targetId}
                onChange={setTargetId}
                style={{ width: '100%', marginTop: 4 }}
              >
                {cohorts.map(c => <Option key={c.id} value={c.id}>{c.name} ({c.patient_count ?? '?'})</Option>)}
              </Select>
            </Col>
            <Col span={12}>
              <Text strong>{t('estimation.outcome_cohort', 'Outcome Event')}</Text>
              <Select
                placeholder="Select outcome cohort..."
                value={outcomeId}
                onChange={setOutcomeId}
                style={{ width: '100%', marginTop: 4 }}
              >
                {cohorts.map(c => <Option key={c.id} value={c.id}>{c.name} ({c.patient_count ?? '?'})</Option>)}
              </Select>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={8}>
              <Text strong>{t('estimation.time_unit', 'Time Unit')}</Text>
              <div style={{ marginTop: 4 }}>
                <Radio.Group value={timeUnit} onChange={e => setTimeUnit(e.target.value)}>
                  <Radio.Button value="days">{t('estimation.days', 'Days')}</Radio.Button>
                  <Radio.Button value="months">{t('estimation.months', 'Months')}</Radio.Button>
                  <Radio.Button value="years">{t('estimation.years', 'Years')}</Radio.Button>
                </Radio.Group>
              </div>
            </Col>
            <Col span={16}>
              <Text strong>{t('estimation.strata', 'Stratify by')}</Text>
              <div style={{ marginTop: 4 }}>
                <Checkbox.Group value={strata} onChange={v => setStrata(v as string[])}>
                  <Checkbox value="gender">Gender</Checkbox>
                  <Checkbox value="age_group">Age Group</Checkbox>
                </Checkbox.Group>
              </div>
            </Col>
          </Row>

          <Button type="primary" icon={<CalculatorOutlined />} onClick={compute}
            loading={computing} disabled={!targetId || !outcomeId}>
            {t('estimation.compute', 'Compute')}
          </Button>
        </Space>
      </Card>

      {computing && <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>}

      {result && !computing && (
        <>
          {/* Summary stats */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="N" value={result.summary.n} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title={t('estimation.events', 'Events')} value={result.summary.events} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title={t('estimation.censored', 'Censored')} value={result.summary.censored} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title={t('estimation.median_survival', 'Median Survival')}
                  value={result.median_survival ?? '—'}
                  suffix={result.median_survival != null ? timeUnit : ''}
                />
              </Card>
            </Col>
          </Row>

          {/* Log-rank test */}
          {result.log_rank && (
            <Card size="small" style={{ marginBottom: 16 }}>
              <Space>
                <Tag color={result.log_rank.p_value < 0.05 ? 'red' : 'green'}>
                  {t('estimation.log_rank', 'Log-Rank Test')}
                </Tag>
                <Text>Chi² = {result.log_rank.chi_square}</Text>
                <Text strong>{t('estimation.p_value', 'p-value')} = {result.log_rank.p_value < 0.001 ? '< 0.001' : result.log_rank.p_value.toFixed(4)}</Text>
                <Text type="secondary">(df = {result.log_rank.df})</Text>
              </Space>
            </Card>
          )}

          {/* Kaplan-Meier Chart */}
          <Card size="small" title={t('estimation.survival_curve', 'Survival Curve')}>
            <ResponsiveContainer width="100%" height={400}>
              {hasStrata ? (
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" label={{ value: timeUnit, position: 'bottom' }} />
                  <YAxis domain={[0, 1]} label={{ value: 'Survival', angle: -90, position: 'insideLeft' }} />
                  <Tooltip formatter={(value: number) => value.toFixed(4)} />
                  <Legend />
                  {result.median_survival != null && (
                    <ReferenceLine y={0.5} stroke="#999" strokeDasharray="5 5" label="Median" />
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
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" label={{ value: timeUnit, position: 'bottom' }} />
                  <YAxis domain={[0, 1]} label={{ value: 'Survival', angle: -90, position: 'insideLeft' }} />
                  <Tooltip formatter={(value: number) => value.toFixed(4)} />
                  {result.median_survival != null && (
                    <ReferenceLine y={0.5} stroke="#999" strokeDasharray="5 5" label="Median" />
                  )}
                  <Area
                    type="stepAfter"
                    dataKey="ci_upper"
                    stroke="none"
                    fill="#1f77b4"
                    fillOpacity={0.1}
                  />
                  <Area
                    type="stepAfter"
                    dataKey="ci_lower"
                    stroke="none"
                    fill="#ffffff"
                    fillOpacity={1}
                  />
                  <Line type="stepAfter" dataKey="survival" stroke="#1f77b4" dot={false} strokeWidth={2} />
                </AreaChart>
              )}
            </ResponsiveContainer>
          </Card>

          {/* Number at risk table */}
          <Divider orientation="left">{t('estimation.at_risk', 'Number at Risk')}</Divider>
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

  const columns = [
    { title: '', dataIndex: 'label', key: 'label', fixed: 'left' as const },
    ...timePoints.map((p, i) => ({
      title: `${Math.round(p.time)}`,
      key: `t${i}`,
      render: (_: any, row: any) => row[`t${i}`],
    })),
  ];

  const data = hasStrata
    ? strataNames.map(name => {
        const row: any = { label: name, key: name };
        timePoints.forEach((tp, i) => {
          const curve = strata[name];
          let last: KMPoint | null = null;
          for (const p of curve) {
            if (p.time <= tp.time) last = p;
            else break;
          }
          row[`t${i}`] = last?.at_risk ?? '—';
        });
        return row;
      })
    : [{
        label: 'Overall',
        key: 'overall',
        ...Object.fromEntries(timePoints.map((p, i) => [`t${i}`, p.at_risk])),
      }];

  return (
    <Table
      dataSource={data}
      columns={columns}
      size="small"
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  );
}
