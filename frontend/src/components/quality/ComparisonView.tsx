import { useState, useEffect } from 'react';
import { useSessionState } from '../../hooks/useSessionState';
import { ArrowLeftRight, AlertTriangle, TrendingUp, TrendingDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi, cdmAccessApi, qualityApi } from '../../api/client';
import AnalysisResults from './AnalysisResults';
import type { CdmConfig, ComparisonResult } from '../../types';
import { Card, Select, Button, Alert, Tag, Table, useToast } from '../ui';
import type { Column } from '../ui';

interface Props {
  cdmNameA: string;
  cdmNameB: string | null;
  domain: string;
  onCdmBChange: (cdm: string) => void;
}

export default function ComparisonView({ cdmNameA, cdmNameB, domain, onCdmBChange }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [comparison, setComparison] = useSessionState<ComparisonResult | null>('quality:comparison:result', null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    cdmAccessApi.getAccessibleCdms()
      .then((res) => setCdms(res.data.cdms.map((name: string) => ({ name } as CdmConfig))))
      .catch(() => cdmApi.list().then((r) => setCdms(r.data.cdms)).catch(() => {}));
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
      toast.error(err?.response?.data?.detail || t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  const alertColumns: Column<any>[] = [
    { title: 'Metric', dataIndex: 'metric', key: 'metric',
      render: (v: string) => <span className="font-semibold text-text-bright">{v}</span> },
    { title: cdmNameA, dataIndex: 'value_a', key: 'value_a',
      render: (v: any) => typeof v === 'number' ? v.toLocaleString() : String(v ?? '-') },
    { title: cdmNameB || 'CDM B', dataIndex: 'value_b', key: 'value_b',
      render: (v: any) => typeof v === 'number' ? v.toLocaleString() : String(v ?? '-') },
    { title: 'Change', dataIndex: 'pct_change', key: 'pct_change',
      render: (v: number) => {
        if (v == null || Number.isNaN(v)) return <Tag>—</Tag>;
        const color = Math.abs(v) > 10 ? 'red' : 'orange';
        const icon = v > 0
          ? <TrendingUp className="h-3 w-3 inline mr-1" />
          : <TrendingDown className="h-3 w-3 inline mr-1" />;
        return <Tag color={color}>{icon}{v > 0 ? '+' : ''}{v.toFixed(1)}%</Tag>;
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
    const borderClass = isAlert
      ? (pct && Math.abs(pct) > 10 ? 'border-red-500/50' : 'border-yellow-500/50')
      : 'border-glass-border';
    return (
      <div key={metric}>
        <Card size="small" className={`${borderClass}`}>
          <span className="text-xs text-text-dim">{metric}</span>
          <div className="flex items-center justify-between mt-1">
            <div>
              <span className="text-sm text-text-bright">{typeof diff.a === 'number' ? diff.a.toLocaleString() : String(diff.a ?? '-')}</span>
              <span className="text-text-dim mx-1">&rarr;</span>
              <span className="text-sm text-text-bright">{typeof diff.b === 'number' ? diff.b.toLocaleString() : String(diff.b ?? '-')}</span>
            </div>
            <div>
              {pct != null && (
                <Tag color={Math.abs(pct) > comparison.threshold ? (pct > 0 ? 'orange' : 'red') : 'default'}>
                  {pct > 0 ? '+' : ''}{pct.toFixed(1)}%
                </Tag>
              )}
            </div>
          </div>
        </Card>
      </div>
    );
  }) : [];

  return (
    <div>
      <Card size="small" className="mb-4">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="font-semibold text-text-bright">{cdmNameA}</span>
          <ArrowLeftRight className="h-5 w-5 text-text-muted" />
          <Select
            placeholder="CDM B"
            value={cdmNameB || undefined}
            onChange={onCdmBChange}
            className="w-52"
            options={cdms
              .filter((c) => c.name !== cdmNameA)
              .map((c) => ({ value: c.name, label: c.name }))}
          />
          <Button variant="primary" onClick={runComparison} loading={loading} disabled={!cdmNameB}>
            {t('quality.compare')}
          </Button>
        </div>
      </Card>

      {comparison && (
        <>
          {/* Diff summary cards */}
          {diffCards.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
              {diffCards}
            </div>
          )}

          {/* Alerts */}
          {comparison.alerts.length > 0 ? (
            <Card
              title={
                <span className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-yellow-400" />
                  {t('quality.alerts')} ({comparison.alerts.length})
                </span>
              }
              className="mb-4"
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
            <Alert message={t('quality.no_alerts')} type="success" showIcon className="mb-4" />
          )}

          {/* Side by side results */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="min-w-0">
              <h5 className="text-sm font-semibold text-text-bright mb-2">{comparison.snapshot_a.cdm_name} (v{comparison.snapshot_a.version})</h5>
              <AnalysisResults results={comparison.results_a} compact />
            </div>
            <div className="min-w-0">
              <h5 className="text-sm font-semibold text-text-bright mb-2">{comparison.snapshot_b.cdm_name} (v{comparison.snapshot_b.version})</h5>
              <AnalysisResults results={comparison.results_b} compact />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
