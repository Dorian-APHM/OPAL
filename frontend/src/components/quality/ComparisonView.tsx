import { useState, useEffect } from 'react';
import { Row, Col, Select, Button, Card, Alert, Tag, Table, Typography, message } from 'antd';
import { SwapOutlined, WarningOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cdmApi, qualityApi } from '../../api/client';
import AnalysisResults from './AnalysisResults';
import type { CdmConfig, ComparisonResult } from '../../types';

const { Title, Text } = Typography;

interface Props {
  cdmNameA: string;
  cdmNameB: string | null;
  domain: string;
  onCdmBChange: (cdm: string) => void;
}

export default function ComparisonView({ cdmNameA, cdmNameB, domain, onCdmBChange }: Props) {
  const { t } = useTranslation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    cdmApi.list().then((res) => setCdms(res.data.cdms));
  }, []);

  const runComparison = async () => {
    if (!cdmNameB) return;
    setLoading(true);
    try {
      const res = await qualityApi.compare({
        cdm_name_a: cdmNameA,
        cdm_name_b: cdmNameB,
        domain,
      });
      setComparison(res.data);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  const alertColumns = [
    { title: 'Metric', dataIndex: 'metric', key: 'metric',
      render: (v: string) => <Text strong>{v}</Text> },
    { title: cdmNameA, dataIndex: 'value_a', key: 'value_a',
      render: (v: any) => typeof v === 'number' ? v.toLocaleString() : String(v ?? '-') },
    { title: cdmNameB || 'CDM B', dataIndex: 'value_b', key: 'value_b',
      render: (v: any) => typeof v === 'number' ? v.toLocaleString() : String(v ?? '-') },
    { title: 'Change', dataIndex: 'pct_change', key: 'pct_change',
      render: (v: number) => {
        const color = Math.abs(v) > 10 ? 'red' : 'orange';
        const icon = v > 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />;
        return <Tag color={color} icon={icon}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</Tag>;
      }},
    { title: 'Severity', dataIndex: 'severity', key: 'severity',
      render: (v: string) => (
        <Tag color={v === 'critical' ? 'red' : 'orange'}>{v.toUpperCase()}</Tag>
      )},
  ];

  // Build diff summary cards from comparison.diffs
  const diffCards = comparison ? Object.entries(comparison.diffs).map(([metric, diff]) => {
    const pct = diff.pct_change;
    const isAlert = comparison.alerts.some(a => a.metric === metric);
    const borderColor = isAlert ? (pct && Math.abs(pct) > 10 ? '#ff4d4f' : '#faad14') : '#d9d9d9';
    return (
      <Col span={6} key={metric}>
        <Card
          size="small"
          style={{ borderColor, marginBottom: 8 }}
          bodyStyle={{ padding: '8px 12px' }}
        >
          <Text type="secondary" style={{ fontSize: 11 }}>{metric}</Text>
          <Row justify="space-between" align="middle">
            <Col>
              <Text>{typeof diff.a === 'number' ? diff.a.toLocaleString() : String(diff.a ?? '-')}</Text>
              <Text type="secondary"> → </Text>
              <Text>{typeof diff.b === 'number' ? diff.b.toLocaleString() : String(diff.b ?? '-')}</Text>
            </Col>
            <Col>
              {pct != null && (
                <Tag color={Math.abs(pct) > comparison.threshold ? (pct > 0 ? 'orange' : 'red') : 'default'}>
                  {pct > 0 ? '+' : ''}{pct.toFixed(1)}%
                </Tag>
              )}
            </Col>
          </Row>
        </Card>
      </Col>
    );
  }) : [];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>{cdmNameA}</Text>
          </Col>
          <Col>
            <SwapOutlined style={{ fontSize: 18 }} />
          </Col>
          <Col>
            <Select
              placeholder="CDM B"
              value={cdmNameB || undefined}
              onChange={onCdmBChange}
              style={{ width: 200 }}
              options={cdms
                .filter((c) => c.name !== cdmNameA)
                .map((c) => ({ value: c.name, label: c.name }))}
            />
          </Col>
          <Col>
            <Button type="primary" onClick={runComparison} loading={loading} disabled={!cdmNameB}>
              {t('quality.compare')}
            </Button>
          </Col>
        </Row>
      </Card>

      {comparison && (
        <>
          {/* Diff summary cards */}
          {diffCards.length > 0 && (
            <Row gutter={8} style={{ marginBottom: 16 }}>
              {diffCards}
            </Row>
          )}

          {/* Alerts */}
          {comparison.alerts.length > 0 ? (
            <Card
              title={
                <span>
                  <WarningOutlined style={{ color: '#faad14', marginRight: 8 }} />
                  {t('quality.alerts')} ({comparison.alerts.length})
                </span>
              }
              style={{ marginBottom: 16 }}
            >
              <Table
                dataSource={comparison.alerts}
                columns={alertColumns}
                rowKey="metric"
                pagination={false}
                size="small"
              />
            </Card>
          ) : (
            <Alert message={t('quality.no_alerts')} type="success" showIcon style={{ marginBottom: 16 }} />
          )}

          {/* Side by side results */}
          <Row gutter={16}>
            <Col span={12}>
              <Title level={5}>{comparison.snapshot_a.cdm_name} (v{comparison.snapshot_a.version})</Title>
              <AnalysisResults results={comparison.results_a} />
            </Col>
            <Col span={12}>
              <Title level={5}>{comparison.snapshot_b.cdm_name} (v{comparison.snapshot_b.version})</Title>
              <AnalysisResults results={comparison.results_b} />
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}
