import { useState, useEffect } from 'react';
import {
  Card,
  Form,
  Input,
  InputNumber,
  Button,
  Table,
  Space,
  message,
  Popconfirm,
  Typography,
} from 'antd';
import {
  PlusOutlined,
  ApiOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../api/client';
import type { CdmConfig } from '../types';

const { Title } = Typography;

export default function CdmManagementPage() {
  const { t } = useTranslation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const loadCdms = async () => {
    try {
      const res = await cdmApi.list();
      setCdms(res.data.cdms);
    } catch {
      message.error(t('common.error'));
    }
  };

  useEffect(() => {
    loadCdms();
  }, []);

  const handleTestConnection = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await cdmApi.test(values);
      message.success(t('cdm.connection_success'));
    } catch {
      message.error(t('cdm.connection_failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await cdmApi.create({ ...values, omop_schema: values.omop_schema || 'omop_cdm' });
      message.success(t('common.success'));
      form.resetFields();
      await loadCdms();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await cdmApi.delete(name);
      message.success(t('common.success'));
      await loadCdms();
    } catch {
      message.error(t('common.error'));
    }
  };

  const handleTestSaved = async (name: string) => {
    try {
      const res = await cdmApi.testSaved(name);
      if (res.data.success) {
        message.success(t('cdm.connection_success'));
      } else {
        message.error(t('cdm.connection_failed'));
      }
    } catch {
      message.error(t('cdm.connection_failed'));
    }
  };

  const columns = [
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
        <Space>
          <Button
            size="small"
            icon={<ApiOutlined />}
            onClick={() => handleTestSaved(r.name)}
          >
            {t('cdm.test_connection')}
          </Button>
          <Popconfirm
            title={t('cdm.delete_confirm')}
            onConfirm={() => handleDelete(r.name)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              {t('cdm.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>{t('cdm.title')}</Title>

      <Card title={t('cdm.register')} style={{ marginBottom: 24 }}>
        <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
          <Form.Item
            label={t('cdm.name')}
            name="name"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Space style={{ width: '100%' }} size="large">
            <Form.Item
              label={t('cdm.host')}
              name="db_host"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item
              label={t('cdm.port')}
              name="db_port"
              initialValue={5432}
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={65535} />
            </Form.Item>
          </Space>
          <Form.Item
            label={t('cdm.database')}
            name="db_name"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('cdm.user')}
            name="db_user"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('cdm.password')}
            name="db_password"
            rules={[{ required: true }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item label={t('cdm.schema')} name="omop_schema" initialValue="omop_cdm">
            <Input />
          </Form.Item>
          <Space>
            <Button onClick={handleTestConnection} loading={loading} icon={<ApiOutlined />}>
              {t('cdm.test_connection')}
            </Button>
            <Button type="primary" onClick={handleRegister} loading={loading} icon={<PlusOutlined />}>
              {t('cdm.save')}
            </Button>
          </Space>
        </Form>
      </Card>

      <Card title={t('cdm.registered_cdms')}>
        <Table
          dataSource={cdms}
          columns={columns}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: t('cdm.no_cdms') }}
        />
      </Card>
    </div>
  );
}
