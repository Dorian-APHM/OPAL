import { useState, useEffect } from 'react';
import {
  Card, Table, Button, Input, Modal, Form, Select, Tag, Space, Typography,
  Empty, message, Popconfirm, Spin,
} from 'antd';
import { PlusOutlined, DeleteOutlined, SearchOutlined, EyeOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { conceptSetApi, cohortApi } from '../api/client';
import type { ConceptSetSummary, ConceptSetDetail, OmopConcept } from '../types';

const { Text, Title } = Typography;

export default function ConceptSetPage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const [sets, setSets] = useState<ConceptSetSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<ConceptSetDetail | null>(null);
  const [form] = Form.useForm();

  // Concept search state for creation modal
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<OmopConcept[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);

  const load = () => {
    if (!selectedCdm) return;
    setLoading(true);
    conceptSetApi.list(selectedCdm)
      .then(r => setSets(r.data.concept_sets))
      .catch(() => message.error('Failed to load concept sets'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [selectedCdm]);

  // Concept search
  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2 || !selectedCdm) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setSearchLoading(true);
      cohortApi.searchConcepts(selectedCdm, searchQuery)
        .then(r => setSearchResults(r.data.concepts))
        .catch(() => setSearchResults([]))
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, selectedCdm]);

  const toggleConcept = (c: OmopConcept) => {
    setSelectedConcepts(prev =>
      prev.some(x => x.concept_id === c.concept_id)
        ? prev.filter(x => x.concept_id !== c.concept_id)
        : [...prev, c]
    );
  };

  const handleCreate = async () => {
    if (!selectedCdm) return;
    const values = await form.validateFields();
    await conceptSetApi.create({
      name: values.name,
      cdm_name: selectedCdm,
      domain: values.domain || undefined,
      description: values.description || '',
      concepts: selectedConcepts.map(c => ({
        concept_id: c.concept_id,
        concept_name: c.concept_name,
        concept_code: c.concept_code,
        vocabulary_id: c.vocabulary_id,
        include_descendants: true,
      })),
    });
    message.success('Concept set created');
    setCreateOpen(false);
    setSelectedConcepts([]);
    setSearchQuery('');
    form.resetFields();
    load();
  };

  const handleDelete = async (id: number) => {
    await conceptSetApi.delete(id);
    message.success('Deleted');
    load();
  };

  const openDetail = async (id: number) => {
    const r = await conceptSetApi.get(id);
    setDetail(r.data);
    setDetailOpen(true);
  };

  if (!selectedCdm) {
    return <Card><Empty description="Select a CDM first" /></Card>;
  }

  const columns = [
    { title: t('concept_sets.name', 'Name'), dataIndex: 'name', key: 'name' },
    { title: 'Domain', dataIndex: 'domain', key: 'domain', render: (v: string) => v || '—' },
    { title: t('concept_sets.concepts', 'Concepts'), dataIndex: 'concept_count', key: 'count' },
    { title: 'Created by', dataIndex: 'created_by', key: 'created_by' },
    {
      title: '', key: 'actions', width: 100,
      render: (_: any, record: ConceptSetSummary) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(record.id)} />
          <Popconfirm title="Delete?" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>{t('concept_sets.title', 'Concept Sets')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          {t('concept_sets.create', 'Create')}
        </Button>
      </div>

      <Table
        dataSource={sets}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
        locale={{ emptyText: t('concept_sets.no_sets', 'No concept sets yet') }}
      />

      {/* Create Modal */}
      <Modal
        title={t('concept_sets.create', 'Create Concept Set')}
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); setSelectedConcepts([]); setSearchQuery(''); form.resetFields(); }}
        width={700}
        okButtonProps={{ disabled: selectedConcepts.length === 0 }}
      >
        <Form form={form} layout="vertical" size="small">
          <Form.Item name="name" label={t('concept_sets.name', 'Name')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="domain" label="Domain">
            <Input placeholder="e.g. Condition, Drug (optional)" />
          </Form.Item>
          <Form.Item name="description" label={t('concept_sets.description', 'Description')}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <Input
          prefix={<SearchOutlined />}
          placeholder="Search concepts..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          allowClear
          style={{ marginBottom: 8 }}
        />

        {selectedConcepts.length > 0 && (
          <div style={{ marginBottom: 8, padding: 4, background: '#f0f5ff', borderRadius: 4 }}>
            <Space size={[4, 4]} wrap>
              {selectedConcepts.map(c => (
                <Tag key={c.concept_id} closable onClose={() => toggleConcept(c)} color="blue">
                  {c.concept_name}
                </Tag>
              ))}
            </Space>
          </div>
        )}

        {searchLoading ? (
          <Spin size="small" />
        ) : (
          <div style={{ maxHeight: 250, overflow: 'auto' }}>
            {searchResults.map(c => (
              <div
                key={c.concept_id}
                style={{
                  padding: '4px 8px', cursor: 'pointer', borderBottom: '1px solid #f0f0f0',
                  background: selectedConcepts.some(s => s.concept_id === c.concept_id) ? '#e6f7ff' : undefined,
                }}
                onClick={() => toggleConcept(c)}
              >
                <Text strong style={{ fontSize: 12 }}>{c.concept_name}</Text>
                <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                  {c.concept_code} · {c.vocabulary_id} · {c.domain_id}
                </Text>
                {c.standard_concept === 'S' && <Tag color="green" style={{ fontSize: 10, marginLeft: 4 }}>S</Tag>}
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* Detail Modal */}
      <Modal
        title={detail?.name || 'Concept Set'}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={600}
      >
        {detail && (
          <>
            <Text type="secondary">{detail.description}</Text>
            <div style={{ marginTop: 12, maxHeight: 400, overflow: 'auto' }}>
              <Table
                dataSource={detail.concepts}
                columns={[
                  { title: 'ID', dataIndex: 'concept_id', width: 80 },
                  { title: 'Name', dataIndex: 'concept_name' },
                  { title: 'Code', dataIndex: 'concept_code', width: 100 },
                  { title: 'Vocabulary', dataIndex: 'vocabulary_id', width: 100 },
                ]}
                rowKey="concept_id"
                size="small"
                pagination={false}
              />
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
