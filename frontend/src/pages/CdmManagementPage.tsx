import { useState, useEffect } from 'react';
import { Plus, Plug, Trash2, Lock, Shield, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi, cdmAccessApi, usersApi, groupApi } from '../api/client';
import { Card, Button, Input, NumberInput, Table, Confirm, Select, Tabs, Tag, Alert, useToast } from '../components/ui';
import SchemaCategoriesEditor from '../components/SchemaCategoriesEditor';
import type { Column } from '../components/ui';
import type { TabItem } from '../components/ui';
import type { CdmConfig, GroupSummary } from '../types';

interface AccessGrant {
  cdm_name: string;
  username: string;
  grant_type: 'user';
  granted_by: string;
  created_at: string;
}

interface GroupAccessGrant {
  cdm_name: string;
  group_name: string;
  grant_type: 'group';
  granted_by: string;
  created_at: string;
}

export default function CdmManagementPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [loading, setLoading] = useState(false);

  // Form state
  const [name, setName] = useState('');
  const [dbHost, setDbHost] = useState('');
  const [dbPort, setDbPort] = useState<number | null>(5432);
  const [dbName, setDbName] = useState('');
  const [dbUser, setDbUser] = useState('');
  const [dbPassword, setDbPassword] = useState('');
  const [omopSchema, setOmopSchema] = useState('omop_cdm');
  const [schemaCategories, setSchemaCategories] = useState<Record<string, string>>({});

  // Confirm dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // Access Control state
  const [accessGrants, setAccessGrants] = useState<AccessGrant[]>([]);
  const [groupAccessGrants, setGroupAccessGrants] = useState<GroupAccessGrant[]>([]);
  const [opalUsers, setOpalUsers] = useState<string[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [accessCdm, setAccessCdm] = useState<string | null>(null);
  const [accessUser, setAccessUser] = useState<string | null>(null);
  const [accessGroup, setAccessGroup] = useState<string | null>(null);
  const [grantMode, setGrantMode] = useState<'user' | 'group'>('user');
  const [accessLoading, setAccessLoading] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [clearTarget, setClearTarget] = useState<string | null>(null);

  const loadCdms = async () => {
    try {
      const res = await cdmApi.list();
      setCdms(res.data.cdms);
    } catch {
      toast.error(t('common.error'));
    }
  };

  const loadAccessGrants = async () => {
    try {
      const res = await cdmAccessApi.list();
      setAccessGrants(res.data.grants || []);
      setGroupAccessGrants(res.data.group_grants || []);
    } catch {
      // silently fail if endpoint not available
    }
  };

  const loadOpalUsers = async () => {
    try {
      const res = await usersApi.listOpalUsers();
      setOpalUsers(res.data.users || []);
    } catch {
      // silently fail
    }
  };

  const loadGroups = async () => {
    try {
      const res = await groupApi.list();
      setGroups(res.data.groups || []);
    } catch {
      // silently fail
    }
  };

  useEffect(() => {
    loadCdms();
    loadAccessGrants();
    loadOpalUsers();
    loadGroups();
  }, []);

  const getFormValues = () => ({
    name,
    db_host: dbHost,
    db_port: dbPort ?? 5432,
    db_name: dbName,
    db_user: dbUser,
    db_password: dbPassword,
    omop_schema: omopSchema || 'omop_cdm',
    schema_categories: Object.keys(schemaCategories).length ? schemaCategories : null,
  });

  const resetForm = () => {
    setName('');
    setDbHost('');
    setDbPort(5432);
    setDbName('');
    setDbUser('');
    setDbPassword('');
    setOmopSchema('omop_cdm');
    setSchemaCategories({});
  };

  const handleTestConnection = async () => {
    try {
      setLoading(true);
      await cdmApi.test(getFormValues());
      toast.success(t('cdm.connection_success'));
    } catch {
      toast.error(t('cdm.connection_failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    try {
      setLoading(true);
      await cdmApi.create(getFormValues());
      toast.success(t('common.success'));
      resetForm();
      await loadCdms();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (cdmName: string) => {
    try {
      await cdmApi.delete(cdmName);
      toast.success(t('common.success'));
      await loadCdms();
    } catch {
      toast.error(t('common.error'));
    }
  };

  const handleTestSaved = async (cdmName: string) => {
    try {
      const res = await cdmApi.testSaved(cdmName);
      if (res.data.success) {
        toast.success(t('cdm.connection_success'));
      } else {
        toast.error(t('cdm.connection_failed'));
      }
    } catch {
      toast.error(t('cdm.connection_failed'));
    }
  };

  // Access Control handlers
  const handleGrantAccess = async () => {
    if (!accessCdm) return;
    try {
      setAccessLoading(true);
      if (grantMode === 'user') {
        if (!accessUser) return;
        await cdmAccessApi.grant(accessCdm, accessUser);
        toast.success(`Access granted to ${accessUser}`);
        setAccessUser(null);
      } else {
        if (!accessGroup) return;
        await cdmAccessApi.grantGroup(accessCdm, accessGroup);
        toast.success(`Access granted to group "${accessGroup}"`);
        setAccessGroup(null);
      }
      setAccessCdm(null);
      await loadAccessGrants();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || err?.message || 'Failed to grant access');
    } finally {
      setAccessLoading(false);
    }
  };

  const handleRevokeAccess = async (cdmName: string, username: string) => {
    try {
      await cdmAccessApi.revoke(cdmName, username);
      toast.success('Access revoked');
      await loadAccessGrants();
    } catch (err: any) {
      toast.error(err?.message || 'Failed to revoke access');
    }
  };

  const handleRevokeGroupAccess = async (cdmName: string, groupName: string) => {
    try {
      await cdmAccessApi.revokeGroup(cdmName, groupName);
      toast.success(`Group "${groupName}" access revoked`);
      await loadAccessGrants();
    } catch (err: any) {
      toast.error(err?.message || 'Failed to revoke group access');
    }
  };

  const handleClearCdmAccess = async (cdmName: string) => {
    try {
      await cdmAccessApi.clearCdm(cdmName);
      toast.success(`All access grants cleared for ${cdmName}`);
      await loadAccessGrants();
    } catch (err: any) {
      toast.error(err?.message || 'Failed to clear access grants');
    }
  };

  const columns: Column<CdmConfig>[] = [
    { title: t('cdm.name'), dataIndex: 'name', key: 'name' },
    {
      title: t('cdm.host'),
      key: 'host',
      render: (_: unknown, r: CdmConfig) => `${r.db_host}:${r.db_port}`,
    },
    { title: t('cdm.database'), dataIndex: 'db_name', key: 'db_name' },
    { title: t('cdm.user'), dataIndex: 'db_user', key: 'db_user' },
    { title: t('cdm.schema'), dataIndex: 'omop_schema', key: 'omop_schema' },
    {
      title: '',
      key: 'actions',
      render: (_: unknown, r: CdmConfig) => (
        <div className="flex items-center gap-2">
          <Button
            size="small"
            icon={<Plug className="h-3.5 w-3.5" />}
            onClick={() => handleTestSaved(r.name)}
          >
            {t('cdm.test_connection')}
          </Button>
          <Button
            size="small"
            variant="danger"
            icon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => {
              setDeleteTarget(r.name);
              setConfirmOpen(true);
            }}
          >
            {t('cdm.delete')}
          </Button>
        </div>
      ),
    },
  ];

  const accessColumns: Column<AccessGrant>[] = [
    {
      title: 'CDM',
      dataIndex: 'cdm_name',
      key: 'cdm_name',
      render: (_: unknown, r: AccessGrant) => (
        <span className="font-medium text-text-bright">{r.cdm_name}</span>
      ),
    },
    {
      title: 'Username',
      dataIndex: 'username',
      key: 'username',
      render: (_: unknown, r: AccessGrant) => (
        <Tag color="blue">{r.username}</Tag>
      ),
    },
    {
      title: 'Granted By',
      dataIndex: 'granted_by',
      key: 'granted_by',
      render: (_: unknown, r: AccessGrant) => (
        <span className="text-text-muted">{r.granted_by}</span>
      ),
    },
    {
      title: 'Date',
      key: 'created_at',
      render: (_: unknown, r: AccessGrant) => (
        <span className="text-text-dim text-xs">
          {r.created_at ? new Date(r.created_at).toLocaleString() : '-'}
        </span>
      ),
    },
    {
      title: '',
      key: 'actions',
      render: (_: unknown, r: AccessGrant) => (
        <Button
          size="small"
          variant="danger"
          icon={<Trash2 className="h-3.5 w-3.5" />}
          onClick={() => handleRevokeAccess(r.cdm_name, r.username)}
        >
          Revoke
        </Button>
      ),
    },
  ];

  const groupAccessColumns: Column<GroupAccessGrant>[] = [
    {
      title: 'CDM',
      dataIndex: 'cdm_name',
      key: 'cdm_name',
      render: (_: unknown, r: GroupAccessGrant) => (
        <span className="font-medium text-text-bright">{r.cdm_name}</span>
      ),
    },
    {
      title: 'Group',
      dataIndex: 'group_name',
      key: 'group_name',
      render: (_: unknown, r: GroupAccessGrant) => (
        <span className="inline-flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5 text-purple-400" />
          <Tag color="purple">{r.group_name}</Tag>
        </span>
      ),
    },
    {
      title: 'Granted By',
      dataIndex: 'granted_by',
      key: 'granted_by',
      render: (_: unknown, r: GroupAccessGrant) => (
        <span className="text-text-muted">{r.granted_by}</span>
      ),
    },
    {
      title: 'Date',
      key: 'created_at',
      render: (_: unknown, r: GroupAccessGrant) => (
        <span className="text-text-dim text-xs">
          {r.created_at ? new Date(r.created_at).toLocaleString() : '-'}
        </span>
      ),
    },
    {
      title: '',
      key: 'actions',
      render: (_: unknown, r: GroupAccessGrant) => (
        <Button
          size="small"
          variant="danger"
          icon={<Trash2 className="h-3.5 w-3.5" />}
          onClick={() => handleRevokeGroupAccess(r.cdm_name, r.group_name)}
        >
          Revoke
        </Button>
      ),
    },
  ];

  // Get unique CDM names that have any grants (user or group)
  const cdmsWithGrants = [...new Set([
    ...accessGrants.map((g) => g.cdm_name),
    ...groupAccessGrants.map((g) => g.cdm_name),
  ])];

  const isGrantDisabled = grantMode === 'user'
    ? !accessCdm || !accessUser
    : !accessCdm || !accessGroup;

  const connectionsTab = (
    <div>
      <Card title={t('cdm.register')} className="mb-6">
        <div className="max-w-xl space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.name')} <span className="text-red-400">*</span></label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.host')} <span className="text-red-400">*</span></label>
              <Input value={dbHost} onChange={(e) => setDbHost(e.target.value)} required />
            </div>
            <div className="w-full md:w-32">
              <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.port')} <span className="text-red-400">*</span></label>
              <NumberInput value={dbPort ?? undefined} onChange={(v) => setDbPort(v)} min={1} max={65535} />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.database')} <span className="text-red-400">*</span></label>
            <Input value={dbName} onChange={(e) => setDbName(e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.user')} <span className="text-red-400">*</span></label>
            <Input value={dbUser} onChange={(e) => setDbUser(e.target.value)} required />
          </div>
          <div>
            <Input label={t('cdm.password')} type="password" value={dbPassword} onChange={(e) => setDbPassword(e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.schema')} <span className="text-red-400">*</span></label>
            <Input value={omopSchema} onChange={(e) => setOmopSchema(e.target.value)} />
          </div>
          <SchemaCategoriesEditor
            value={schemaCategories}
            onChange={setSchemaCategories}
            defaultSchema={omopSchema}
          />
          <div className="flex items-center gap-2">
            <Button onClick={handleTestConnection} loading={loading} icon={<Plug className="h-4 w-4" />}>
              {t('cdm.test_connection')}
            </Button>
            <Button variant="primary" onClick={handleRegister} loading={loading} icon={<Plus className="h-4 w-4" />}>
              {t('cdm.save')}
            </Button>
          </div>
        </div>
      </Card>

      <Card title={t('cdm.registered_cdms')}>
        <Table
          dataSource={cdms}
          columns={columns}
          rowKey="id"
          pagination={false}
          emptyText={t('cdm.no_cdms')}
        />
      </Card>
    </div>
  );

  const accessControlTab = (
    <div>
      <Alert
        type="info"
        message="CDM Access Control"
        description="When no access grants exist for a CDM, it is open to all users. Adding grants (user or group) restricts access to only the specified users and group members."
        className="mb-6"
      />

      <Card
        title={
          <span className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-emerald-400" />
            Grant Access
          </span>
        }
        className="mb-6"
      >
        {/* Toggle: User / Group */}
        <div className="flex items-center gap-1 mb-4 p-0.5 bg-deep-base rounded-lg w-fit border border-glass-border">
          <button
            onClick={() => { setGrantMode('user'); setAccessGroup(null); }}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all cursor-pointer border-none ${
              grantMode === 'user'
                ? 'bg-emerald-accent/15 text-emerald-accent'
                : 'bg-transparent text-text-dim hover:text-text-muted'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5" />
              User
            </span>
          </button>
          <button
            onClick={() => { setGrantMode('group'); setAccessUser(null); }}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all cursor-pointer border-none ${
              grantMode === 'group'
                ? 'bg-purple-500/15 text-purple-400'
                : 'bg-transparent text-text-dim hover:text-text-muted'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5" />
              Group
            </span>
          </button>
        </div>

        <div className="flex items-end gap-4 flex-wrap">
          <Select
            label="CDM"
            options={cdms.map((c) => ({ value: c.name, label: c.name }))}
            value={accessCdm}
            onChange={(v) => setAccessCdm(v || null)}
            placeholder="Select CDM..."
            className="w-full md:w-64"
          />

          {grantMode === 'user' ? (
            <Select
              label="User"
              options={opalUsers.map((u) => ({ value: u, label: u }))}
              value={accessUser}
              onChange={(v) => setAccessUser(v || null)}
              placeholder="Select user..."
              className="w-full md:w-64"
            />
          ) : (
            <Select
              label="Group"
              options={groups.map((g) => ({
                value: g.name,
                label: g.name,
                description: `${g.member_count} member${g.member_count !== 1 ? 's' : ''}`,
              }))}
              value={accessGroup}
              onChange={(v) => setAccessGroup(v || null)}
              placeholder="Select group..."
              className="w-full md:w-64"
            />
          )}

          <Button
            variant="primary"
            icon={grantMode === 'user' ? <Lock className="h-4 w-4" /> : <Users className="h-4 w-4" />}
            onClick={handleGrantAccess}
            loading={accessLoading}
            disabled={isGrantDisabled}
          >
            {grantMode === 'user' ? 'Grant to User' : 'Grant to Group'}
          </Button>
        </div>
      </Card>

      {/* Group Grants table */}
      {groupAccessGrants.length > 0 && (
        <Card
          title={
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 text-purple-400" />
              Group Grants
            </span>
          }
          className="mb-6"
        >
          <Table
            dataSource={groupAccessGrants}
            columns={groupAccessColumns}
            rowKey={(r: GroupAccessGrant) => `${r.cdm_name}-${r.group_name}`}
            pagination={false}
            emptyText="No group grants."
          />
        </Card>
      )}

      {/* User Grants table */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-emerald-400" />
            User Grants
          </span>
        }
      >
        {cdmsWithGrants.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {cdmsWithGrants.map((cdmName) => (
              <Button
                key={cdmName}
                size="small"
                variant="danger"
                icon={<Trash2 className="h-3.5 w-3.5" />}
                onClick={() => {
                  setClearTarget(cdmName);
                  setClearConfirmOpen(true);
                }}
              >
                Clear all grants for {cdmName}
              </Button>
            ))}
          </div>
        )}

        <Table
          dataSource={accessGrants}
          columns={accessColumns}
          rowKey={(r: AccessGrant) => `${r.cdm_name}-${r.username}`}
          pagination={false}
          emptyText="No user access grants configured. All CDMs are open to all users."
        />
      </Card>
    </div>
  );

  const tabItems: TabItem[] = [
    {
      key: 'connections',
      label: (
        <span className="flex items-center gap-2">
          <Plug className="h-4 w-4" />
          Connections
        </span>
      ),
      children: connectionsTab,
    },
    {
      key: 'access-control',
      label: (
        <span className="flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Access Control
        </span>
      ),
      children: accessControlTab,
    },
  ];

  return (
    <div>
      <h3 className="text-2xl font-bold text-text-bright mb-4">{t('cdm.title')}</h3>

      <Tabs items={tabItems} />

      <Confirm
        open={confirmOpen}
        onClose={() => {
          setConfirmOpen(false);
          setDeleteTarget(null);
        }}
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget);
          setDeleteTarget(null);
        }}
        title={t('cdm.delete_confirm')}
        confirmText={t('cdm.delete')}
        danger
      />

      <Confirm
        open={clearConfirmOpen}
        onClose={() => {
          setClearConfirmOpen(false);
          setClearTarget(null);
        }}
        onConfirm={() => {
          if (clearTarget) handleClearCdmAccess(clearTarget);
          setClearTarget(null);
        }}
        title={`Clear all access grants (user + group) for "${clearTarget}"? This will make the CDM open to all users.`}
        confirmText="Clear All"
        danger
      />
    </div>
  );
}
