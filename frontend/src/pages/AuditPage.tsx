import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, DatePicker, Select, Button, Space, Typography,
  Row, Col, Statistic, Input, message,
} from 'antd';
import {
  DownloadOutlined, ReloadOutlined, SearchOutlined,
  FieldTimeOutlined, UserOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { auditApi, authDownload } from '../api/client';
import type { AuditEntry, AuditStats } from '../types';

const { RangePicker } = DatePicker;
const { Text } = Typography;

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
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Filters
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs(), dayjs(),
  ]);
  const [userFilter, setUserFilter] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<string>('');

  const fetchLogs = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const params: Record<string, any> = {
        date_from: dateRange[0].format('YYYY-MM-DD'),
        date_to: dateRange[1].format('YYYY-MM-DD'),
        page: p,
        page_size: pageSize,
      };
      if (userFilter) params.user = userFilter;
      if (actionFilter) params.action = actionFilter;

      const resp = await auditApi.logs(params);
      setEntries(resp.data.entries);
      setTotal(resp.data.total);
    } catch {
      message.error(t('audit.load_error', 'Failed to load audit logs'));
    } finally {
      setLoading(false);
    }
  }, [dateRange, userFilter, actionFilter, page, pageSize, t]);

  const fetchStats = useCallback(async () => {
    try {
      const resp = await auditApi.stats({
        date_from: dateRange[0].format('YYYY-MM-DD'),
        date_to: dateRange[1].format('YYYY-MM-DD'),
      });
      setStats(resp.data);
    } catch {
      // stats are optional
    }
  }, [dateRange]);

  useEffect(() => {
    fetchLogs(page);
    fetchStats();
  }, [dateRange, userFilter, actionFilter, page, pageSize]);

  const handleExport = () => {
    const params: Record<string, string> = {
      date_from: dateRange[0].format('YYYY-MM-DD'),
      date_to: dateRange[1].format('YYYY-MM-DD'),
    };
    if (userFilter) params.user = userFilter;
    if (actionFilter) params.action = actionFilter;
    authDownload(auditApi.exportUrl(params), 'audit_logs.csv');
  };

  const columns = [
    {
      title: t('audit.time', 'Time'),
      dataIndex: 'ts',
      key: 'ts',
      width: 170,
      render: (ts: string) => (
        <Text style={{ fontSize: 12, fontFamily: 'monospace' }}>
          {ts ? new Date(ts).toLocaleString() : '—'}
        </Text>
      ),
    },
    {
      title: t('audit.user', 'User'),
      dataIndex: 'user',
      key: 'user',
      width: 120,
      render: (u: string) => <Tag icon={<UserOutlined />}>{u}</Tag>,
    },
    {
      title: t('audit.action', 'Action'),
      dataIndex: 'action',
      key: 'action',
      width: 180,
      render: (a: string) => <Tag color={actionColor(a)}>{a}</Tag>,
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
      render: (p: string) => <Text style={{ fontSize: 12, fontFamily: 'monospace' }}>{p}</Text>,
    },
    {
      title: t('audit.status', 'Status'),
      dataIndex: 'status',
      key: 'status',
      width: 70,
      render: (s: number) => <Tag color={statusColor(s)}>{s}</Tag>,
    },
    {
      title: t('audit.duration', 'Duration'),
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      width: 90,
      render: (ms: number) => <Text type="secondary" style={{ fontSize: 12 }}>{ms}ms</Text>,
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      key: 'ip',
      width: 120,
      render: (ip: string) => <Text type="secondary" style={{ fontSize: 11 }}>{ip}</Text>,
    },
  ];

  return (
    <div>
      {/* Stats row */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title={t('audit.total_events', 'Total Events')}
                value={stats.total_events}
                prefix={<ThunderboltOutlined />}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title={t('audit.active_users', 'Active Users')}
                value={stats.by_user.length}
                prefix={<UserOutlined />}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title={t('audit.action_types', 'Action Types')}
                value={stats.by_action.length}
                prefix={<FieldTimeOutlined />}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Filters */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <RangePicker
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0], dates[1]]);
                setPage(1);
              }
            }}
            size="small"
          />
          <Input
            placeholder={t('audit.filter_user', 'Filter by user')}
            prefix={<UserOutlined />}
            value={userFilter}
            onChange={e => { setUserFilter(e.target.value); setPage(1); }}
            allowClear
            size="small"
            style={{ width: 160 }}
          />
          <Select
            placeholder={t('audit.filter_action', 'Filter by action')}
            value={actionFilter || undefined}
            onChange={v => { setActionFilter(v || ''); setPage(1); }}
            allowClear
            size="small"
            style={{ width: 180 }}
            options={[
              { value: 'quality', label: 'Quality' },
              { value: 'cohort', label: 'Cohort' },
              { value: 'mapping', label: 'Mapping' },
              { value: 'cdm', label: 'CDM' },
              { value: 'concept', label: 'Concept' },
              { value: 'ohdsi', label: 'OHDSI' },
            ]}
          />
          <Button icon={<ReloadOutlined />} size="small" onClick={() => fetchLogs(page)}>
            {t('audit.refresh', 'Refresh')}
          </Button>
          <Button icon={<DownloadOutlined />} size="small" onClick={handleExport}>
            CSV
          </Button>
        </Space>
      </Card>

      {/* Table */}
      <Card size="small">
        <Table
          dataSource={entries}
          columns={columns}
          rowKey={(_, idx) => String(idx)}
          loading={loading}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['25', '50', '100'],
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
            showTotal: (total) => `${total} ${t('audit.entries', 'entries')}`,
            size: 'small',
          }}
          scroll={{ x: true }}
        />
      </Card>
    </div>
  );
}
