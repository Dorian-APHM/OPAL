import { useState, useRef } from 'react';
import { useSessionState } from '../../hooks/useSessionState';
import { Card, Statistic, Button, Tooltip, Alert, Spinner } from '../../components/ui';
import { Play, Users, BarChart3, Download, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, Cell,
} from 'recharts';
import { cohortApi, authDownload } from '../../api/client';
import type { CohortCriteria, AttritionStep } from '../../types';

interface Props {
  cdmName: string;
  criteria: CohortCriteria;
  savedCohortId?: number;
}

export default function ResultsPanel({ cdmName, criteria, savedCohortId }: Props) {
  const { t } = useTranslation();
  const [patientCount, setPatientCount] = useSessionState<number | null>('cohort:results:count', null);
  const [countLoading, setCountLoading] = useState(false);
  const [attrition, setAttrition] = useSessionState<AttritionStep[]>('cohort:results:attrition', []);
  const [attritionLoading, setAttritionLoading] = useState(false);
  const [generatedSql, setGeneratedSql] = useSessionState<string>('cohort:results:sql', '');
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
    fill: s.label.startsWith('-') ? '#ff4d4f' : '#10B981',
  }));

  return (
    <div className="h-full flex flex-col gap-3 overflow-auto">
      {/* Patient count */}
      <Card size="small">
        <div className="text-center mb-2">
          <Statistic
            title={
              <div className="flex items-center gap-1 justify-center">
                <Users className="h-3.5 w-3.5" />
                {t('cohort.patient_count', 'Patient Count')}
              </div>
            }
            value={countLoading ? '...' : (patientCount != null ? patientCount.toLocaleString() : '—')}
            valueStyle={{ fontSize: 32, color: patientCount != null ? '#3B82F6' : '#475569' }}
          />
        </div>
        <div className="flex items-center justify-center gap-2">
          {anyLoading ? (
            <Button variant="danger" icon={<X className="h-3.5 w-3.5" />} onClick={cancelOperation} size="small">
              {t('common.cancel')}
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Play className="h-3.5 w-3.5" />}
              onClick={runCount}
              disabled={!hasCriteria || !cdmName}
              size="small"
            >
              {t('cohort.run_count', 'Count')}
            </Button>
          )}
          <Tooltip title={t('cohort.approximate_tooltip', 'Quick approximate count')}>
            <span>
              <Button
                icon={<Play className="h-3.5 w-3.5" />}
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
            </span>
          </Tooltip>
        </div>
      </Card>

      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {/* Attrition */}
      <Card
        size="small"
        title={
          <div className="flex items-center gap-1">
            <BarChart3 className="h-4 w-4" />
            {t('cohort.attrition', 'Attrition Diagram')}
          </div>
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
          <div className="text-center py-5"><Spinner /></div>
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
          <span className="text-text-muted text-xs">
            {t('cohort.click_run_attrition', 'Click Run to see attrition diagram')}
          </span>
        )}
      </Card>

      {/* Export */}
      <Card size="small" title={<div className="flex items-center gap-1"><Download className="h-4 w-4" />{t('cohort.export', 'Export')}</div>}>
        <div className="flex flex-wrap gap-2">
          {savedCohortId && (
            <>
              <Button
                size="small"
                variant="primary"
                icon={<Download className="h-3.5 w-3.5" />}
                onClick={() => authDownload(cohortApi.exportUrl(savedCohortId, 'csv'))}
              >
                {criteria.inclusion.sameVisit
                  ? 'CSV (Patient + Visit IDs)'
                  : 'CSV (Patient IDs)'}
              </Button>
              <Button
                size="small"
                icon={<Download className="h-3.5 w-3.5" />}
                onClick={() => authDownload(cohortApi.exportUrl(savedCohortId, 'sql'))}
              >
                SQL
              </Button>
            </>
          )}
        </div>
      </Card>

      {/* Generated SQL preview */}
      {generatedSql && (
        <Card size="small" title={t('cohort.generated_sql', 'Generated SQL')}>
          <pre className="text-[10px] max-h-[200px] overflow-auto whitespace-pre-wrap break-all text-text-muted bg-deep-base p-2 rounded">
            {generatedSql}
          </pre>
        </Card>
      )}
    </div>
  );
}
