import { useState, useEffect } from 'react';
import {
  Card, Select, Button, InputNumber, Space, Typography, Table, Statistic,
  Row, Col, Empty, message, Spin, Checkbox, Divider,
} from 'antd';
import { BarChartOutlined, CalculatorOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { cohortApi, incidenceApi } from '../api/client';
import type { CohortSummary, IncidenceResult } from '../types';

const { Title, Text } = Typography;
const { Option } = Select;

export default function IncidencePage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [targetId, setTargetId] = useState<number | null>(null);
  const [outcomeId, setOutcomeId] = useState<number | null>(null);
  const [tarStart, setTarStart] = useState(0);
  const [tarEnd, setTarEnd] = useState<string | number>('observation_end');
  const [tarEndDays, setTarEndDays] = useState(365);
  const [strata, setStrata] = useState<string[]>([]);
  const [computing, setComputing] = useState(false);
  const [result, setResult] = useState<IncidenceResult | null>(null);

  useEffect(() => {
    if (!selectedCdm) return;
    cohortApi.list(selectedCdm).then(r => setCohorts(r.data.cohorts)).catch(() => {});
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
      message.error(e.message || 'Computation failed');
    } finally {
      setComputing(false);
    }
  };

  if (!selectedCdm) return <Card><Empty description="Select a CDM first" /></Card>;

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Title level={4}><BarChartOutlined /> {t('incidence.title', 'Incidence Rates')}</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Row gutter={16}>
            <Col span={12}>
              <Text strong>{t('incidence.target_cohort', 'Target Cohort')}</Text>
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
              <Text strong>{t('incidence.outcome_cohort', 'Outcome Cohort')}</Text>
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
              <Text strong>{t('incidence.tar_start', 'TAR Start (days)')}</Text>
              <InputNumber value={tarStart} onChange={v => setTarStart(v ?? 0)} min={0} style={{ width: '100%', marginTop: 4 }} />
            </Col>
            <Col span={8}>
              <Text strong>{t('incidence.tar_end', 'TAR End')}</Text>
              <Select value={tarEnd as string} onChange={v => setTarEnd(v)} style={{ width: '100%', marginTop: 4 }}>
                <Option value="observation_end">{t('incidence.observation_end', 'End of observation')}</Option>
                <Option value="fixed">{t('incidence.fixed_days', 'Fixed duration')}</Option>
              </Select>
            </Col>
            {tarEnd === 'fixed' && (
              <Col span={8}>
                <Text strong>{t('incidence.fixed_days', 'Days')}</Text>
                <InputNumber value={tarEndDays} onChange={v => setTarEndDays(v ?? 365)} min={1} style={{ width: '100%', marginTop: 4 }} />
              </Col>
            )}
          </Row>

          <div>
            <Text strong>{t('incidence.strata', 'Stratification')}</Text>
            <div style={{ marginTop: 4 }}>
              <Checkbox.Group value={strata} onChange={v => setStrata(v as string[])}>
                <Checkbox value="gender">{t('incidence.gender', 'Gender')}</Checkbox>
                <Checkbox value="age_group">{t('incidence.age_group', 'Age Group')}</Checkbox>
                <Checkbox value="calendar_year">{t('incidence.calendar_year', 'Calendar Year')}</Checkbox>
              </Checkbox.Group>
            </div>
          </div>

          <Button type="primary" icon={<CalculatorOutlined />} onClick={compute}
            loading={computing} disabled={!targetId || !outcomeId}>
            {t('incidence.compute', 'Compute')}
          </Button>
        </Space>
      </Card>

      {computing && <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>}

      {result && !computing && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Card size="small"><Statistic title={t('incidence.persons_at_risk', 'At Risk')} value={result.target_count} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title={t('incidence.persons_with_outcome', 'With Outcome')} value={result.outcome_count} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title={t('incidence.person_years', 'Person-Years')} value={result.person_years} precision={1} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="IR / 1000 PY" value={result.incidence_rate * 1000} precision={2} suffix={`[${(result.ci_lower * 1000).toFixed(1)}-${(result.ci_upper * 1000).toFixed(1)}]`} /></Card></Col>
          </Row>

          {result.strata.length > 0 && (
            <>
              <Divider orientation="left">{t('incidence.strata', 'By Strata')}</Divider>
              <Table
                dataSource={result.strata}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                columns={[
                  ...strata.map(s => ({
                    title: s,
                    key: s,
                    render: (_: any, row: any) => row.strata_values?.[s] || '—',
                  })),
                  { title: 'At Risk', dataIndex: 'target_count' },
                  { title: 'Events', dataIndex: 'outcome_count' },
                  { title: 'PY', dataIndex: 'person_years', render: (v: number) => v?.toFixed(1) },
                  { title: 'IR/1000 PY', key: 'rate', render: (_: any, r: any) => ((r.incidence_rate || 0) * 1000).toFixed(2) },
                  { title: '95% CI', key: 'ci', render: (_: any, r: any) => `[${((r.ci_lower || 0) * 1000).toFixed(1)} - ${((r.ci_upper || 0) * 1000).toFixed(1)}]` },
                ]}
              />

              <Card size="small" style={{ marginTop: 16 }}>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={result.strata.map((s, i) => ({
                    label: Object.values(s.strata_values || {}).join(' / '),
                    rate: (s.incidence_rate || 0) * 1000,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="label" />
                    <YAxis label={{ value: 'IR / 1000 PY', angle: -90, position: 'insideLeft' }} />
                    <Tooltip />
                    <Bar dataKey="rate" fill="#1f77b4" />
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
