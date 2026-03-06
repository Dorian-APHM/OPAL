import { useState, useEffect } from 'react';
import { Card, Select, Typography, Empty, Spin, Row, Col, Statistic, Tag } from 'antd';
import { LineChartOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { useTranslation } from 'react-i18next';
import { qualityApi } from '../../api/client';
import useIsMobile from '../../hooks/useIsMobile';

const { Text, Title } = Typography;

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

const COLORS = ['#1f77b4', '#ff7f0e', '#2bc459', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f'];

export default function SnapshotTimeline({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [timelines, setTimelines] = useState<Record<string, TimelinePoint[]>>({});
  const [loading, setLoading] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedCdm) return;
    setLoading(true);
    qualityApi.timeline(selectedCdm)
      .then((res) => {
        setTimelines(res.data.timelines || {});
        const keys = Object.keys(res.data.timelines || {});
        if (keys.length > 0 && !selectedDomain) {
          setSelectedDomain(keys[0]);
        }
      })
      .catch(() => setTimelines({}))
      .finally(() => setLoading(false));
  }, [selectedCdm]);

  if (loading) {
    return <Card><div style={{ textAlign: 'center', padding: 40 }}><Spin /></div></Card>;
  }

  const domainKeys = Object.keys(timelines);
  if (domainKeys.length === 0) {
    return (
      <Card title={<><LineChartOutlined /> {t('quality.timeline_title')}</>}>
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
      title={<><LineChartOutlined /> {t('quality.timeline_title')}</>}
      extra={
        <Select
          value={selectedDomain}
          onChange={setSelectedDomain}
          style={{ width: 200 }}
          options={domainKeys.map((d) => ({ value: d, label: t(`domains.${d}`, d) }))}
        />
      }
    >
      {/* KPI delta cards */}
      {latest && (
        <Row gutter={[16, 12]} style={{ marginBottom: 16 }}>
          {latest.total_persons != null && (
            <Col xs={12} sm={12} md={6}>
              <Statistic
                title={t('quality.total_persons')}
                value={latest.total_persons}
                suffix={previous ? <DeltaTag value={delta(latest.total_persons, previous.total_persons)} /> : null}
              />
            </Col>
          )}
          {latest.total_records != null && (
            <Col xs={12} sm={12} md={6}>
              <Statistic
                title={t('quality.total_records')}
                value={latest.total_records}
                suffix={previous ? <DeltaTag value={delta(latest.total_records, previous.total_records)} /> : null}
              />
            </Col>
          )}
          {isClinical && latest.pct_terms_mapped != null && (
            <Col xs={12} sm={12} md={6}>
              <Statistic
                title={t('quality.pct_mapped')}
                value={latest.pct_terms_mapped}
                precision={1}
                suffix={<>%{previous ? <DeltaTag value={delta(latest.pct_terms_mapped, previous?.pct_terms_mapped)} /> : null}</>}
              />
            </Col>
          )}
          {isClinical && latest.pct_rows_mapped != null && (
            <Col xs={12} sm={12} md={6}>
              <Statistic
                title={t('quality.rows') + ' ' + t('quality.pct_mapped')}
                value={latest.pct_rows_mapped}
                precision={1}
                suffix={<>%{previous ? <DeltaTag value={delta(latest.pct_rows_mapped, previous?.pct_rows_mapped)} /> : null}</>}
              />
            </Col>
          )}
          {isDashboard && latest.avg_pct_terms_mapped != null && (
            <Col xs={12} sm={12} md={6}>
              <Statistic
                title={t('quality.pct_mapped') + ' (avg)'}
                value={latest.avg_pct_terms_mapped}
                precision={1}
                suffix={<>%{previous ? <DeltaTag value={delta(latest.avg_pct_terms_mapped, previous?.avg_pct_terms_mapped)} /> : null}</>}
              />
            </Col>
          )}
        </Row>
      )}

      {/* Chart */}
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={isMobile ? 200 : 300}>
          <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]} />
            <Tooltip />
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
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Text type="secondary">{t('quality.timeline_need_more')}</Text>
        </div>
      )}

      {/* Mini sparklines for all domains overview */}
      {domainKeys.length > 1 && (
        <>
          <Title level={5} style={{ marginTop: 16 }}>{t('quality.timeline_overview')}</Title>
          <Row gutter={[8, 8]}>
            {domainKeys.map((dom) => {
              const data = timelines[dom];
              if (data.length < 2) return null;
              const mainMetric = dom === 'Dashboard' || dom === 'Person' ? 'total_persons' : 'total_records';
              return (
                <Col xs={12} sm={8} md={6} key={dom}>
                  <Card
                    size="small"
                    hoverable
                    onClick={() => setSelectedDomain(dom)}
                    style={{ borderColor: dom === selectedDomain ? '#2bc459' : undefined }}
                  >
                    <Text strong style={{ fontSize: 12 }}>{t(`domains.${dom}`, dom)}</Text>
                    <ResponsiveContainer width="100%" height={40}>
                      <LineChart data={data}>
                        <Line type="monotone" dataKey={mainMetric} stroke="#1f77b4" strokeWidth={1.5} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </Card>
                </Col>
              );
            })}
          </Row>
        </>
      )}
    </Card>
  );
}

function DeltaTag({ value }: { value: number | null }) {
  if (value == null) return null;
  const color = value > 0 ? 'green' : value < 0 ? 'red' : 'default';
  const icon = value > 0 ? <RiseOutlined /> : value < 0 ? <FallOutlined /> : null;
  return (
    <Tag color={color} style={{ marginLeft: 4 }}>
      {icon} {value > 0 ? '+' : ''}{value.toFixed(1)}%
    </Tag>
  );
}
