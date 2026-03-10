import { useState, useEffect } from 'react';
import { Plus, Plug, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../api/client';
import { Card, Button, Input, NumberInput, Table, Confirm, useToast } from '../components/ui';
import type { Column } from '../components/ui';
import type { CdmConfig } from '../types';

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

  // Confirm dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const loadCdms = async () => {
    try {
      const res = await cdmApi.list();
      setCdms(res.data.cdms);
    } catch {
      toast.error(t('common.error'));
    }
  };

  useEffect(() => {
    loadCdms();
  }, []);

  const getFormValues = () => ({
    name,
    db_host: dbHost,
    db_port: dbPort ?? 5432,
    db_name: dbName,
    db_user: dbUser,
    db_password: dbPassword,
    omop_schema: omopSchema || 'omop_cdm',
  });

  const resetForm = () => {
    setName('');
    setDbHost('');
    setDbPort(5432);
    setDbName('');
    setDbUser('');
    setDbPassword('');
    setOmopSchema('omop_cdm');
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

  return (
    <div>
      <h3 className="text-2xl font-bold text-text-bright mb-4">{t('cdm.title')}</h3>

      <Card title={t('cdm.register')} className="mb-6">
        <div className="max-w-xl space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.name')}</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.host')}</label>
              <Input value={dbHost} onChange={(e) => setDbHost(e.target.value)} />
            </div>
            <div className="w-32">
              <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.port')}</label>
              <NumberInput value={dbPort ?? undefined} onChange={(v) => setDbPort(v)} min={1} max={65535} />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.database')}</label>
            <Input value={dbName} onChange={(e) => setDbName(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.user')}</label>
            <Input value={dbUser} onChange={(e) => setDbUser(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.password')}</label>
            <Input type="password" value={dbPassword} onChange={(e) => setDbPassword(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('cdm.schema')}</label>
            <Input value={omopSchema} onChange={(e) => setOmopSchema(e.target.value)} />
          </div>
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
    </div>
  );
}
