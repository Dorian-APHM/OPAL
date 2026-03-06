import { useState, useEffect } from 'react';
import { Card, Form, InputNumber, Input, Button, Typography, message, Alert } from 'antd';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../api/client';

const { Title } = Typography;

interface Props {
  selectedCdm: string | null;
}

export default function SettingsPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (selectedCdm) {
      cdmApi.getSettings(selectedCdm).then((res) => {
        form.setFieldsValue(res.data);
      });
    }
  }, [selectedCdm]);

  const handleSave = async () => {
    if (!selectedCdm) return;
    try {
      const values = await form.validateFields();
      setLoading(true);
      await cdmApi.updateSettings(selectedCdm, values);
      message.success(t('settings.saved'));
    } catch {
      message.error(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  if (!selectedCdm) {
    return (
      <div>
        <Title level={3}>{t('settings.title')}</Title>
        <Alert message={t('cdm.select_cdm')} type="info" showIcon />
      </div>
    );
  }

  return (
    <div>
      <Title level={3}>
        {t('settings.title')} — {selectedCdm}
      </Title>
      <Card style={{ maxWidth: 500 }}>
        <Form form={form} layout="vertical">
          <Form.Item label={t('settings.omop_schema')} name="omop_schema">
            <Input />
          </Form.Item>
          <Form.Item label={t('settings.top_unmapped_terms')} name="top_unmapped_terms">
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label={t('settings.top_concepts')} name="top_concepts">
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label={t('settings.max_records_per_person')} name="max_records_per_person">
            <InputNumber min={10} max={1000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label={t('settings.max_observation_months')} name="max_observation_months">
            <InputNumber min={12} max={600} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label={t('settings.comparison_threshold')} name="comparison_alert_threshold">
            <InputNumber min={0.1} max={50} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Button type="primary" onClick={handleSave} loading={loading}>
            {t('common.save')}
          </Button>
        </Form>
      </Card>
    </div>
  );
}
