import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Tabs, Badge, Select, Modal, Switch, Empty, Confirm, Input, useToast,
} from '../components/ui';
import type { Column } from '../components/ui';
import {
  User, RefreshCw, CheckCircle, Ban, Plus, XCircle, UserPlus,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { adminApi } from '../api/client';
import type { AdminUser, AccessRequest } from '../types';

const OPAL_ROLES = ['admin', 'omop-dim', 'chercheur', 'medecin'];

const ROLE_COLORS: Record<string, string> = {
  admin: 'red',
  'omop-dim': 'purple',
  chercheur: 'blue',
  medecin: 'green',
};

export default function UserManagementPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

  // Access requests
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('users');

  // Add user modal
  const [addUserOpen, setAddUserOpen] = useState(false);
  const [addUserLoading, setAddUserLoading] = useState(false);
  const [addUsername, setAddUsername] = useState('');
  const [addRole, setAddRole] = useState('');
  const [addErrors, setAddErrors] = useState<{ username?: string; role?: string }>({});

  // Confirm dialogs
  const [approveConfirm, setApproveConfirm] = useState<number | null>(null);
  const [rejectConfirm, setRejectConfirm] = useState<number | null>(null);

  const resetAddForm = () => {
    setAddUsername('');
    setAddRole('');
    setAddErrors({});
  };

  const handleAddUser = async () => {
    const errors: { username?: string; role?: string } = {};
    if (!addUsername) errors.username = 'Matricule requis';
    else if (!/^[a-zA-Z0-9._-]+$/.test(addUsername)) errors.username = 'Lettres, chiffres, . - _ uniquement';
    if (!addRole) errors.role = 'Choisissez un role';
    if (Object.keys(errors).length > 0) {
      setAddErrors(errors);
      return;
    }
    setAddUserLoading(true);
    try {
      await adminApi.addUser(addUsername, addRole);
      toast.success(`Utilisateur ${addUsername} ajoute avec le role ${addRole}`);
      setAddUserOpen(false);
      resetAddForm();
      fetchUsers();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || 'Echec';
      toast.error(detail);
    } finally {
      setAddUserLoading(false);
    }
  };

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
      toast.success(t('admin.role_assigned', 'Role assigned'));
      fetchUsers();
    } catch (e: any) {
      toast.error(e.message || 'Failed to assign role');
    }
  };

  const handleRemoveRole = async (userId: string, role: string) => {
    try {
      await adminApi.removeRole(userId, role);
      toast.success(t('admin.role_removed', 'Role removed'));
      fetchUsers();
    } catch (e: any) {
      toast.error(e.message || 'Failed to remove role');
    }
  };

  const handleToggleUser = async (userId: string, enabled: boolean) => {
    try {
      await adminApi.toggleUser(userId, enabled);
      toast.success(enabled
        ? t('admin.user_enabled', 'User enabled')
        : t('admin.user_disabled', 'User disabled'));
      fetchUsers();
    } catch (e: any) {
      toast.error(e.message || 'Failed to update user');
    }
  };

  const handleApproveRequest = async (id: number) => {
    try {
      await adminApi.approveRequest(id);
      toast.success("Demande approuvee. L'utilisateur peut se connecter avec ses identifiants APHM.");
      fetchRequests();
      fetchUsers();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || 'Failed to approve';
      toast.error(detail);
    }
  };

  const handleRejectRequest = async (id: number) => {
    try {
      await adminApi.rejectRequest(id);
      toast.success(t('admin.request_rejected', 'Request rejected'));
      fetchRequests();
    } catch (e: any) {
      toast.error(e.message || 'Failed to reject');
    }
  };

  const userColumns: Column<AdminUser>[] = [
    {
      title: t('admin.username', 'Username'),
      dataIndex: 'username',
      key: 'username',
      width: 150,
      render: (u: string, record: AdminUser) => (
        <button
          onClick={() => setSelectedUser(record)}
          className="flex items-center gap-2 text-emerald-accent hover:text-emerald-light bg-transparent border-none cursor-pointer text-sm"
        >
          <User className="h-3.5 w-3.5" />
          {u}
        </button>
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
      render: (e: string) => (
        <span className="text-sm text-text-muted truncate block max-w-[200px]">{e || '\u2014'}</span>
      ),
    },
    {
      title: t('admin.roles', 'Roles'),
      dataIndex: 'roles',
      key: 'roles',
      width: 280,
      render: (roles: string[], record: AdminUser) => (
        <div className="flex items-center gap-1 flex-wrap">
          {roles
            .filter(r => OPAL_ROLES.includes(r))
            .map(r => (
              <Tag
                key={r}
                color={(ROLE_COLORS[r] || 'default') as any}
                closable
                onClose={() => handleRemoveRole(record.id, r)}
              >
                {r}
              </Tag>
            ))}
          <Select
            size="small"
            placeholder="+"
            className="w-24"
            value={undefined as any}
            onChange={(v) => { if (v) handleAssignRole(record.id, v); }}
            options={OPAL_ROLES
              .filter(r => !roles.includes(r))
              .map(r => ({ value: r, label: r }))}
          />
        </div>
      ),
    },
    {
      title: t('admin.status', 'Status'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled: boolean, record: AdminUser) => (
        <div className="flex items-center gap-2">
          <Switch
            checked={enabled}
            onChange={(checked) => handleToggleUser(record.id, checked)}
            size="small"
          />
          {enabled
            ? <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
            : <Ban className="h-3.5 w-3.5 text-red-400" />}
        </div>
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

  const requestColumns: Column<AccessRequest>[] = [
    {
      title: t('admin.username', 'Username'),
      dataIndex: 'username',
      key: 'username',
      width: 150,
      render: (u: string) => (
        <div className="flex items-center gap-2">
          <User className="h-3.5 w-3.5 text-text-dim" />
          {u}
        </div>
      ),
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
      render: (e: string) => (
        <span className="text-sm text-text-muted truncate block max-w-[200px]">{e || '\u2014'}</span>
      ),
    },
    {
      title: t('admin.requested_role', 'Requested Role'),
      dataIndex: 'requested_role',
      key: 'requested_role',
      width: 130,
      render: (role: string) => (
        <Tag color={(ROLE_COLORS[role] || 'default') as any}>{role}</Tag>
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
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="small"
            icon={<CheckCircle className="h-3.5 w-3.5" />}
            onClick={() => setApproveConfirm(record.id)}
          >
            {t('admin.approve', 'Approve')}
          </Button>
          <Button
            variant="danger"
            size="small"
            icon={<XCircle className="h-3.5 w-3.5" />}
            onClick={() => setRejectConfirm(record.id)}
          >
            {t('admin.reject', 'Reject')}
          </Button>
        </div>
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
                <div className="flex items-center gap-2">
                  <User className="h-4 w-4" />
                  {t('admin.user_management', 'User Management')}
                  <Tag>{users.length}</Tag>
                </div>
              ),
              children: (
                <>
                  {error && (
                    <div className="mb-3">
                      <Tag color="orange">{t('admin.keycloak_warning', 'Keycloak connection issue')}: {error}</Tag>
                    </div>
                  )}
                  <Table
                    dataSource={users}
                    columns={userColumns}
                    rowKey="id"
                    loading={loading}
                    size="small"
                    pagination={{ current: 1, pageSize: 25, total: users.length }}
                    scroll={{ x: true }}
                    emptyText={<Empty description={t('admin.no_users', 'No users found')} />}
                  />
                </>
              ),
            },
            {
              key: 'requests',
              label: (
                <Badge count={pendingCount}>
                  <div className="flex items-center gap-2">
                    <Plus className="h-4 w-4" />
                    {t('admin.access_requests', 'Access Requests')}
                  </div>
                </Badge>
              ),
              children: (
                <Table
                  dataSource={requests}
                  columns={requestColumns}
                  rowKey="id"
                  loading={requestsLoading}
                  size="small"
                  scroll={{ x: true }}
                  emptyText={
                    <div className="py-12 text-center">
                      <CheckCircle className="h-12 w-12 text-emerald-accent mx-auto mb-3" />
                      <h3 className="text-lg font-semibold text-text-bright mb-1">
                        {t('admin.no_pending', 'No pending requests')}
                      </h3>
                      <span className="text-sm text-text-muted">
                        {t('admin.all_clear', 'All access requests have been processed.')}
                      </span>
                    </div>
                  }
                />
              ),
            },
          ]}
          extra={
            <div className="flex items-center gap-2">
              <Button
                icon={<UserPlus className="h-3.5 w-3.5" />}
                size="small"
                variant="primary"
                onClick={() => setAddUserOpen(true)}
              >
                Ajouter un utilisateur
              </Button>
              <Button
                icon={<RefreshCw className="h-3.5 w-3.5" />}
                size="small"
                onClick={() => {
                  fetchUsers();
                  fetchRequests();
                }}
              >
                {t('audit.refresh', 'Refresh')}
              </Button>
            </div>
          }
        />
      </Card>

      {/* Approve confirm */}
      <Confirm
        open={approveConfirm !== null}
        onClose={() => setApproveConfirm(null)}
        onConfirm={() => {
          if (approveConfirm !== null) handleApproveRequest(approveConfirm);
        }}
        title={t('admin.confirm_approve', 'Approve this access request?')}
        description="Le role sera assigne et l'utilisateur pourra se connecter avec ses identifiants APHM."
        confirmText={t('admin.approve', 'Approve')}
      />

      {/* Reject confirm */}
      <Confirm
        open={rejectConfirm !== null}
        onClose={() => setRejectConfirm(null)}
        onConfirm={() => {
          if (rejectConfirm !== null) handleRejectRequest(rejectConfirm);
        }}
        title={t('admin.confirm_reject', 'Reject this request?')}
        confirmText={t('admin.reject', 'Reject')}
        danger
      />

      {/* User detail modal */}
      <Modal
        open={!!selectedUser}
        onClose={() => setSelectedUser(null)}
        title={
          <div className="flex items-center gap-2">
            <User className="h-4 w-4" />
            {selectedUser?.username}
          </div>
        }
        width="max-w-md"
      >
        {selectedUser && (
          <dl className="divide-y divide-glass-border">
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">{t('admin.username', 'Username')}</dt>
              <dd className="text-sm text-text-bright">{selectedUser.username}</dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">Email</dt>
              <dd className="text-sm text-text-bright">{selectedUser.email || '\u2014'}</dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">{t('admin.name', 'Name')}</dt>
              <dd className="text-sm text-text-bright">
                {`${selectedUser.first_name || ''} ${selectedUser.last_name || ''}`.trim() || '\u2014'}
              </dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">{t('admin.status', 'Status')}</dt>
              <dd>
                <Tag color={selectedUser.enabled ? 'green' : 'red'}>
                  {selectedUser.enabled
                    ? t('admin.enabled', 'Enabled')
                    : t('admin.disabled', 'Disabled')}
                </Tag>
              </dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">{t('admin.roles', 'Roles')}</dt>
              <dd className="flex flex-wrap gap-1">
                {selectedUser.roles
                  .filter(r => OPAL_ROLES.includes(r))
                  .map(r => (
                    <Tag key={r} color={(ROLE_COLORS[r] || 'default') as any}>{r}</Tag>
                  ))}
              </dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">{t('admin.created', 'Created')}</dt>
              <dd className="text-sm text-text-bright">
                {selectedUser.created_at
                  ? new Date(selectedUser.created_at).toLocaleString()
                  : '\u2014'}
              </dd>
            </div>
            <div className="flex py-2.5">
              <dt className="w-28 text-xs font-medium text-text-dim shrink-0">ID</dt>
              <dd className="text-[11px] font-mono text-text-muted">{selectedUser.id}</dd>
            </div>
          </dl>
        )}
      </Modal>

      {/* Add user modal */}
      <Modal
        open={addUserOpen}
        onClose={() => { setAddUserOpen(false); resetAddForm(); }}
        title={
          <div className="flex items-center gap-2">
            <UserPlus className="h-4 w-4" />
            Ajouter un utilisateur
          </div>
        }
        width="max-w-sm"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">Matricule APHM</label>
            <Input
              placeholder="ex: a159230"
              prefix={<User className="h-3.5 w-3.5" />}
              value={addUsername}
              onChange={e => { setAddUsername(e.target.value); setAddErrors(prev => ({ ...prev, username: undefined })); }}
              error={addErrors.username}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">Role</label>
            <Select
              placeholder="Choisir un role"
              value={addRole || null}
              onChange={v => { setAddRole(v); setAddErrors(prev => ({ ...prev, role: undefined })); }}
              options={OPAL_ROLES.map(r => ({
                value: r,
                label: r,
              }))}
            />
            {addErrors.role && (
              <span className="text-xs text-red-400 mt-1 block">{addErrors.role}</span>
            )}
          </div>
          <Button
            variant="primary"
            block
            loading={addUserLoading}
            icon={<UserPlus className="h-3.5 w-3.5" />}
            onClick={handleAddUser}
          >
            Ajouter
          </Button>
        </div>
      </Modal>
    </div>
  );
}
