import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Tabs, Badge,
  Select, Modal, Descriptions, Switch, Empty, Popconfirm, Result,
} from 'antd';
import {
  UserOutlined, ReloadOutlined, CheckCircleOutlined,
  StopOutlined, PlusOutlined, CloseCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '../api/client';
import type { AdminUser, AccessRequest } from '../types';

const { Text } = Typography;

const OPAL_ROLES = ['admin', 'omop-dim', 'chercheur', 'medecin'];

const ROLE_COLORS: Record<string, string> = {
  admin: 'red',
  'omop-dim': 'purple',
  chercheur: 'blue',
  medecin: 'green',
};

export default function UserManagementPage() {
  const { t } = useTranslation();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

  // Access requests
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('users');

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await adminApi.users();
      if (resp.data.error) {
        setError(resp.data.error);
      }
      setUsers(resp.data.users);
    } catch (e: any) {
      setError(e.message || 'Failed to fetch users');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchRequests = useCallback(async () => {
    setRequestsLoading(true);
    try {
      const resp = await adminApi.accessRequests('pending');
      setRequests(resp.data.requests);
    } catch {
      // silently fail
    } finally {
      setRequestsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
    fetchRequests();
  }, [fetchUsers, fetchRequests]);

  const handleAssignRole = async (userId: string, role: string) => {
    try {
      await adminApi.assignRole(userId, role);
      message.success(t('admin.role_assigned', 'Role assigned'));
      fetchUsers();
    } catch (e: any) {
      message.error(e.message || 'Failed to assign role');
    }
  };

  const handleRemoveRole = async (userId: string, role: string) => {
    try {
      await adminApi.removeRole(userId, role);
      message.success(t('admin.role_removed', 'Role removed'));
      fetchUsers();
    } catch (e: any) {
      message.error(e.message || 'Failed to remove role');
    }
  };

  const handleToggleUser = async (userId: string, enabled: boolean) => {
    try {
      await adminApi.toggleUser(userId, enabled);
      message.success(enabled
        ? t('admin.user_enabled', 'User enabled')
        : t('admin.user_disabled', 'User disabled'));
      fetchUsers();
    } catch (e: any) {
      message.error(e.message || 'Failed to update user');
    }
  };

  const handleApproveRequest = async (id: number) => {
    try {
      const resp = await adminApi.approveRequest(id);
      const data = resp.data as any;
      message.success(
        t('admin.request_approved', 'Request approved. Temporary password: {{password}}', {
          password: data.temporary_password,
        })
      );
      Modal.info({
        title: t('admin.account_created', 'Account Created'),
        content: (
          <Descriptions column={1} size="small">
            <Descriptions.Item label={t('admin.username', 'Username')}>
              <Text copyable strong>{data.username}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.temp_password', 'Temporary Password')}>
              <Text copyable strong code>{data.temporary_password}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Info">
              <Text type="secondary">
                {t('admin.password_change_required', 'The user will be asked to change their password on first login.')}
              </Text>
            </Descriptions.Item>
          </Descriptions>
        ),
      });
      fetchRequests();
      fetchUsers();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || 'Failed to approve';
      message.error(detail);
    }
  };

  const handleRejectRequest = async (id: number) => {
    try {
      await adminApi.rejectRequest(id);
      message.success(t('admin.request_rejected', 'Request rejected'));
      fetchRequests();
    } catch (e: any) {
      message.error(e.message || 'Failed to reject');
    }
  };

  const userColumns = [
    {
      title: t('admin.username', 'Username'),
      dataIndex: 'username',
      key: 'username',
      width: 150,
      render: (u: string, record: AdminUser) => (
        <a onClick={() => setSelectedUser(record)}>
          <Space>
            <UserOutlined />
            {u}
          </Space>
        </a>
      ),
    },
    {
      title: t('admin.name', 'Name'),
      key: 'name',
      width: 180,
      render: (_: any, record: AdminUser) =>
        `${record.first_name || ''} ${record.last_name || ''}`.trim() || '\u2014',
    },
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      width: 220,
      ellipsis: true,
      render: (e: string) => e || '\u2014',
    },
    {
      title: t('admin.roles', 'Roles'),
      dataIndex: 'roles',
      key: 'roles',
      width: 280,
      render: (roles: string[], record: AdminUser) => (
        <Space wrap size={4}>
          {roles
            .filter(r => OPAL_ROLES.includes(r))
            .map(r => (
              <Tag
                key={r}
                color={ROLE_COLORS[r] || 'default'}
                closable
                onClose={(e) => {
                  e.preventDefault();
                  handleRemoveRole(record.id, r);
                }}
              >
                {r}
              </Tag>
            ))}
          <Select
            size="small"
            placeholder={<PlusOutlined />}
            style={{ width: 100 }}
            value={undefined}
            onChange={(v) => { if (v) handleAssignRole(record.id, v); }}
            options={OPAL_ROLES
              .filter(r => !roles.includes(r))
              .map(r => ({ value: r, label: r }))}
          />
        </Space>
      ),
    },
    {
      title: t('admin.status', 'Status'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled: boolean, record: AdminUser) => (
        <Switch
          checked={enabled}
          checkedChildren={<CheckCircleOutlined />}
          unCheckedChildren={<StopOutlined />}
          onChange={(checked) => handleToggleUser(record.id, checked)}
          size="small"
        />
      ),
    },
    {
      title: t('admin.created', 'Created'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (ts: number | null) =>
        ts ? new Date(ts).toLocaleDateString() : '\u2014',
    },
  ];

  const requestColumns = [
    {
      title: t('admin.username', 'Username'),
      dataIndex: 'username',
      key: 'username',
      width: 150,
      render: (u: string) => <Space><UserOutlined />{u}</Space>,
    },
    {
      title: t('admin.name', 'Name'),
      key: 'name',
      width: 180,
      render: (_: any, r: AccessRequest) => `${r.first_name} ${r.last_name}`,
    },
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      width: 220,
      ellipsis: true,
    },
    {
      title: t('admin.requested_role', 'Requested Role'),
      dataIndex: 'requested_role',
      key: 'requested_role',
      width: 130,
      render: (role: string) => (
        <Tag color={ROLE_COLORS[role] || 'default'}>{role}</Tag>
      ),
    },
    {
      title: t('admin.requested_at', 'Requested'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (ts: string | null) =>
        ts ? new Date(ts).toLocaleString() : '\u2014',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 200,
      render: (_: any, record: AccessRequest) => (
        <Space>
          <Popconfirm
            title={t('admin.confirm_approve', 'Approve this access request?')}
            description={t('admin.approve_description',
              'A Keycloak account will be created with username as temporary password.'
            )}
            onConfirm={() => handleApproveRequest(record.id)}
            okText={t('admin.approve', 'Approve')}
          >
            <Button type="primary" size="small" icon={<CheckCircleOutlined />}>
              {t('admin.approve', 'Approve')}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t('admin.confirm_reject', 'Reject this request?')}
            onConfirm={() => handleRejectRequest(record.id)}
            okText={t('admin.reject', 'Reject')}
            okButtonProps={{ danger: true }}
          >
            <Button danger size="small" icon={<CloseCircleOutlined />}>
              {t('admin.reject', 'Reject')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const pendingCount = requests.length;

  return (
    <div>
      <Card size="small">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'users',
              label: (
                <Space>
                  <UserOutlined />
                  {t('admin.user_management', 'User Management')}
                  <Tag>{users.length}</Tag>
                </Space>
              ),
              children: (
                <>
                  {error && (
                    <div style={{ marginBottom: 12 }}>
                      <Tag color="orange">{t('admin.keycloak_warning', 'Keycloak connection issue')}: {error}</Tag>
                    </div>
                  )}
                  <Table
                    dataSource={users}
                    columns={userColumns}
                    rowKey="id"
                    loading={loading}
                    size="small"
                    pagination={{ pageSize: 25, size: 'small', showSizeChanger: true }}
                    scroll={{ x: true }}
                    locale={{ emptyText: <Empty description={t('admin.no_users', 'No users found')} /> }}
                  />
                </>
              ),
            },
            {
              key: 'requests',
              label: (
                <Badge count={pendingCount} offset={[10, 0]} size="small">
                  <Space>
                    <PlusOutlined />
                    {t('admin.access_requests', 'Access Requests')}
                  </Space>
                </Badge>
              ),
              children: (
                <Table
                  dataSource={requests}
                  columns={requestColumns}
                  rowKey="id"
                  loading={requestsLoading}
                  size="small"
                  pagination={false}
                  scroll={{ x: true }}
                  locale={{
                    emptyText: (
                      <Result
                        status="success"
                        title={t('admin.no_pending', 'No pending requests')}
                        subTitle={t('admin.all_clear', 'All access requests have been processed.')}
                      />
                    ),
                  }}
                />
              ),
            },
          ]}
          tabBarExtraContent={
            <Button icon={<ReloadOutlined />} size="small" onClick={() => {
              fetchUsers();
              fetchRequests();
            }}>
              {t('audit.refresh', 'Refresh')}
            </Button>
          }
        />
      </Card>

      {/* User detail modal */}
      <Modal
        title={
          <Space>
            <UserOutlined />
            {selectedUser?.username}
          </Space>
        }
        open={!!selectedUser}
        onCancel={() => setSelectedUser(null)}
        footer={null}
        width={500}
      >
        {selectedUser && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label={t('admin.username', 'Username')}>
              {selectedUser.username}
            </Descriptions.Item>
            <Descriptions.Item label="Email">
              {selectedUser.email || '\u2014'}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.name', 'Name')}>
              {`${selectedUser.first_name || ''} ${selectedUser.last_name || ''}`.trim() || '\u2014'}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.status', 'Status')}>
              <Tag color={selectedUser.enabled ? 'green' : 'red'}>
                {selectedUser.enabled
                  ? t('admin.enabled', 'Enabled')
                  : t('admin.disabled', 'Disabled')}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.roles', 'Roles')}>
              <Space wrap>
                {selectedUser.roles
                  .filter(r => OPAL_ROLES.includes(r))
                  .map(r => (
                    <Tag key={r} color={ROLE_COLORS[r]}>{r}</Tag>
                  ))}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.created', 'Created')}>
              {selectedUser.created_at
                ? new Date(selectedUser.created_at).toLocaleString()
                : '\u2014'}
            </Descriptions.Item>
            <Descriptions.Item label="ID">
              <Text copyable style={{ fontSize: 11, fontFamily: 'monospace' }}>
                {selectedUser.id}
              </Text>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
