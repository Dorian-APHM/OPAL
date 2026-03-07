import { useState, useRef } from 'react';
import { Card, Statistic, Button, Typography, Space, Tooltip, Spin, Alert } from 'antd';
import {
  PlayCircleOutlined, TeamOutlined, BarChartOutlined,
  DownloadOutlined, ThunderboltOutlined, StopOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, Cell,
} from 'recharts';
import { cohortApi, authDownload } from '../../api/client';
import type { CohortCriteria, AttritionStep } from '../../types';

const { Text } = Typography;

interface Props {
  cdmName: string;
  criteria: CohortCriteria;
  savedCohortId?: number;
}

export default function ResultsPanel({ cdmName, criteria, savedCohortId }: Props) {
  const { t } = useTranslation();
  const [patientCount, setPatientCount] = useState<number | null>(null);
  const [countLoading, setCountLoading] = useState(false);
  const [attrition, setAttrition] = useState<AttritionStep[]>([]);
  const [attritionLoading, setAttritionLoading] = useState(false);
  const [generatedSql, setGeneratedSql] = useState<string>('');
  const [error, setError] = useState<string>('');
  const abortRef = useRef<AbortController | null>(null);

  const anyLoading = countLoading || attritionLoading;

  const cancelOperation = () => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setCountLoading(false);
    setAttritionLoading(false);
  };

  const hasCriteria = criteria.inclusion.criteria.length > 0 || criteria.demographics?.age || criteria.demographics?.gender;

  const runCount = async () => {
    if (!cdmName || !hasCriteria) return;
    setCountLoading(true);
    setError('');
    try {
      const resp = await cohortApi.count(cdmName, criteria);
      setPatientCount(resp.data.patient_count);
      setGeneratedSql(resp.data.sql);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Count failed');
    } finally {
      setCountLoading(false);
    }
  };

  const runAttrition = async () => {
    if (!cdmName || !hasCriteria) return;
    setAttritionLoading(true);
    setError('');
    try {
      const resp = await cohortApi.attrition(cdmName, criteria);
      setAttrition(resp.data.steps);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Attrition failed');
    } finally {
      setAttritionLoading(false);
    }
  };

  const attritionChartData = attrition.map(s => ({
    ...s,
    fill: s.label.startsWith('-') ? '#ff4d4f' : '#2bc459',
  }));

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12, overflow: 'auto' }}>
      {/* Patient count */}
      <Card size="small">
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <Statistic
            title={
              <Space>
                <TeamOutlined />
                {t('cohort.patient_count', 'Patient Count')}
              </Space>
            }
            value={patientCount ?? '—'}
            loading={countLoading}
            valueStyle={{ fontSize: 32, color: patientCount != null ? '#1f77b4' : '#ccc' }}
          />
        </div>
        <Space style={{ width: '100%', justifyContent: 'center' }}>
          {anyLoading ? (
            <Button danger icon={<StopOutlined />} onClick={cancelOperation} size="small">
              {t('common.cancel')}
            </Button>
          ) : (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={runCount}
              disabled={!hasCriteria || !cdmName}
              size="small"
            >
              {t('cohort.run_count', 'Count')}
            </Button>
          )}
          <Tooltip title={t('cohort.approximate_tooltip', 'Quick approximate count')}>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={async () => {
                setCountLoading(true);
                try {
                  const resp = await cohortApi.countApprox(cdmName, criteria);
                  setPatientCount(resp.data.patient_count);
                } catch (e: any) {
                  setError(e.response?.data?.detail || 'Error');
                } finally {
                  setCountLoading(false);
                }
              }}
              disabled={!hasCriteria || !cdmName}
              size="small"
            >
              ~
            </Button>
          </Tooltip>
        </Space>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {/* Attrition */}
      <Card
        size="small"
        title={
          <Space>
            <BarChartOutlined />
            {t('cohort.attrition', 'Attrition Diagram')}
          </Space>
        }
        extra={
          <Button
            size="small"
            onClick={runAttrition}
            loading={attritionLoading}
            disabled={!hasCriteria || !cdmName}
          >
            {t('cohort.run', 'Run')}
          </Button>
        }
      >
        {attritionLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
        ) : attrition.length > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(150, attrition.length * 30)}>
            <BarChart data={attritionChartData} layout="vertical" margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis
                type="category"
                dataKey="label"
                width={150}
                tick={{ fontSize: 10 }}
              />
              <RechartsTooltip formatter={(v: number) => v?.toLocaleString()} />
              <Bar dataKey="count">
                {attritionChartData.map((entry, idx) => (
                  <Cell key={idx} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('cohort.click_run_attrition', 'Click Run to see attrition diagram')}
          </Text>
        )}
      </Card>

      {/* Export */}
      <Card size="small" title={<Space><DownloadOutlined />{t('cohort.export', 'Export')}</Space>}>
        <Space wrap>
          {savedCohortId && (
            <>
              <Button
                size="small"
                type="primary"
                icon={<DownloadOutlined />}
                onClick={() => authDownload(cohortApi.exportUrl(savedCohortId, 'csv'))}
              >
                {criteria.inclusion.sameVisit
                  ? 'CSV (Patient + Visit IDs)'
                  : 'CSV (Patient IDs)'}
              </Button>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => authDownload(cohortApi.exportUrl(savedCohortId, 'sql'))}
              >
                SQL
              </Button>
            </>
          )}
        </Space>
      </Card>

      {/* Generated SQL preview */}
      {generatedSql && (
        <Card size="small" title={t('cohort.generated_sql', 'Generated SQL')}>
          <pre style={{ fontSize: 10, maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {generatedSql}
          </pre>
        </Card>
      )}
    </div>
  );
}
