import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message,
  Popconfirm, Select, Modal, Descriptions, Switch, Empty,
} from 'antd';
import {
  UserOutlined, ReloadOutlined, CheckCircleOutlined,
  StopOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { adminApi } from '../api/client';
import type { AdminUser } from '../types';

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
  const [roleToAdd, setRoleToAdd] = useState<string | undefined>();

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

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

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

  const columns = [
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
        `${record.first_name || ''} ${record.last_name || ''}`.trim() || '—',
    },
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      width: 220,
      ellipsis: true,
      render: (e: string) => e || '—',
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
        ts ? new Date(ts).toLocaleDateString() : '—',
    },
  ];

  return (
    <div>
      <Card
        size="small"
        title={
          <Space>
            <UserOutlined />
            {t('admin.user_management', 'User Management')}
            <Tag>{users.length} {t('admin.users', 'users')}</Tag>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} size="small" onClick={fetchUsers}>
            {t('audit.refresh', 'Refresh')}
          </Button>
        }
      >
        {error && (
          <div style={{ marginBottom: 12 }}>
            <Tag color="orange">{t('admin.keycloak_warning', 'Keycloak connection issue')}: {error}</Tag>
          </div>
        )}

        <Table
          dataSource={users}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 25, size: 'small', showSizeChanger: true }}
          scroll={{ x: true }}
          locale={{ emptyText: <Empty description={t('admin.no_users', 'No users found')} /> }}
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
              {selectedUser.email || '—'}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.name', 'Name')}>
              {`${selectedUser.first_name || ''} ${selectedUser.last_name || ''}`.trim() || '—'}
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
                : '—'}
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
