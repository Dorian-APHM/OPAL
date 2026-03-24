import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Select, Button, Input, Statistic, useToast,
} from '../components/ui';
import type { Column } from '../components/ui';
import {
  Download, RefreshCw, Search,
  Clock, User, Zap,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { auditApi, authDownload } from '../api/client';
import type { AuditEntry, AuditStats } from '../types';

const ACTION_COLORS: Record<string, string> = {
  'quality': 'blue',
  'cohort': 'green',
  'mapping': 'purple',
  'cdm': 'orange',
  'concept': 'cyan',
  'ohdsi': 'magenta',
};

function actionColor(action: string): string {
  const prefix = action.split('.')[0];
  return ACTION_COLORS[prefix] || 'default';
}

function statusColor(status: number): string {
  if (status < 300) return 'green';
  if (status < 400) return 'blue';
  if (status < 500) return 'orange';
  return 'red';
}

export default function AuditPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Filters
  const [dateFrom, setDateFrom] = useState(() => new Date().toISOString().slice(0, 10));
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [userFilter, setUserFilter] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<string>('');

  const fetchLogs = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        date_from: dateFrom,
        date_to: dateTo,
        page: p,
        page_size: pageSize,
      };
      if (userFilter) params.user = userFilter;
      if (actionFilter) params.action = actionFilter;

      const resp = await auditApi.logs(params);
      setEntries(resp.data.entries);
      setTotal(resp.data.total);
    } catch {
      toast.error(t('audit.load_error', 'Failed to load audit logs'));
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, userFilter, actionFilter, page, pageSize, t, toast]);

  const fetchStats = useCallback(async () => {
    try {
      const resp = await auditApi.stats({
        date_from: dateFrom,
        date_to: dateTo,
      });
      setStats(resp.data);
    } catch {
      // stats are optional
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    fetchLogs(page);
    fetchStats();
  }, [dateFrom, dateTo, userFilter, actionFilter, page, pageSize]);

  const handleExport = () => {
    const params: Record<string, string> = {
      date_from: dateFrom,
      date_to: dateTo,
    };
    if (userFilter) params.user = userFilter;
    if (actionFilter) params.action = actionFilter;
    authDownload(auditApi.exportUrl(params), 'audit_logs.csv');
  };

  const columns: Column<AuditEntry>[] = [
    {
      title: t('audit.time', 'Time'),
      dataIndex: 'ts',
      key: 'ts',
      width: 170,
      render: (ts: string) => (
        <span className="text-xs font-mono text-text-muted">
          {ts ? new Date(ts).toLocaleString() : '\u2014'}
        </span>
      ),
    },
    {
      title: t('audit.user', 'User'),
      dataIndex: 'user',
      key: 'user',
      width: 120,
      render: (u: string) => (
        <Tag>
          <User className="h-3 w-3" />
          {u}
        </Tag>
      ),
    },
    {
      title: t('audit.action', 'Action'),
      dataIndex: 'action',
      key: 'action',
      width: 180,
      render: (a: string) => <Tag color={actionColor(a) as any}>{a}</Tag>,
    },
    {
      title: t('audit.method', 'Method'),
      dataIndex: 'method',
      key: 'method',
      width: 70,
      render: (m: string) => <Tag>{m}</Tag>,
    },
    {
      title: t('audit.path', 'Path'),
      dataIndex: 'path',
      key: 'path',
      ellipsis: true,
      render: (p: string) => <span className="text-xs font-mono text-text-muted">{p}</span>,
    },
    {
      title: t('audit.status', 'Status'),
      dataIndex: 'status',
      key: 'status',
      width: 70,
      render: (s: number) => <Tag color={statusColor(s) as any}>{s}</Tag>,
    },
    {
      title: t('audit.duration', 'Duration'),
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      width: 90,
      render: (ms: number) => <span className="text-xs text-text-dim">{ms}ms</span>,
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      key: 'ip',
      width: 120,
      render: (ip: string) => <span className="text-[11px] text-text-dim">{ip}</span>,
    },
  ];

  return (
    <div>
      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          <Card size="small">
            <Statistic
              title={t('audit.total_events', 'Total Events')}
              value={stats.total_events}
              prefix={<Zap className="h-5 w-5" />}
            />
          </Card>
          <Card size="small">
            <Statistic
              title={t('audit.active_users', 'Active Users')}
              value={stats.by_user.length}
              prefix={<User className="h-5 w-5" />}
            />
          </Card>
          <Card size="small">
            <Statistic
              title={t('audit.action_types', 'Action Types')}
              value={stats.by_action.length}
              prefix={<Clock className="h-5 w-5" />}
            />
          </Card>
        </div>
      )}

      {/* Filters */}
      <Card size="small" className="mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
            className="bg-deep-base border border-glass-border rounded-[10px] px-3 py-1.5 text-sm text-text-bright outline-none focus:border-emerald-accent/40 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.1)] transition-all duration-200"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
            className="bg-deep-base border border-glass-border rounded-[10px] px-3 py-1.5 text-sm text-text-bright outline-none focus:border-emerald-accent/40 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.1)] transition-all duration-200"
          />
          <Input
            placeholder={t('audit.filter_user', 'Filter by user')}
            prefix={<User className="h-3.5 w-3.5" />}
            value={userFilter}
            onChange={e => { setUserFilter(e.target.value); setPage(1); }}
            className="!w-40"
          />
          <Select
            placeholder={t('audit.filter_action', 'Filter by action')}
            value={actionFilter || null}
            onChange={v => { setActionFilter(v || ''); setPage(1); }}
            allowClear
            size="small"
            className="w-44"
            options={[
              { value: 'quality', label: 'Quality' },
              { value: 'cohort', label: 'Cohort' },
              { value: 'mapping', label: 'Mapping' },
              { value: 'cdm', label: 'CDM' },
              { value: 'concept', label: 'Concept' },
              { value: 'ohdsi', label: 'OHDSI' },
            ]}
          />
          <Button icon={<RefreshCw className="h-3.5 w-3.5" />} size="small" onClick={() => fetchLogs(page)}>
            {t('audit.refresh', 'Refresh')}
          </Button>
          <Button icon={<Download className="h-3.5 w-3.5" />} size="small" onClick={handleExport}>
            CSV
          </Button>
        </div>
      </Card>

      {/* Table */}
      <Card size="small">
        <Table
          dataSource={entries}
          columns={columns}
          rowKey={(_: any, idx?: number) => String(idx)}
          loading={loading}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (p) => { setPage(p); },
          }}
          scroll={{ x: true }}
          emptyText={
            <span className="text-sm text-text-dim">
              {total === 0 ? t('audit.no_entries', 'No audit entries found') : ''}
            </span>
          }
        />
      </Card>
    </div>
  );
}
