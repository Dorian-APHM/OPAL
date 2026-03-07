import { useState, useEffect, useCallback } from 'react';
import {
  Card, Button, Input, Typography, Space, Modal, List, Tag, message,
  Popconfirm, Row, Col, Empty, Table, Spin, Tabs, Alert,
} from 'antd';
import {
  SaveOutlined, FolderOpenOutlined, DeleteOutlined,
  PlusOutlined, PlayCircleOutlined, UserOutlined,
  TableOutlined, SwapOutlined, CodeOutlined, DownloadOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/KeycloakContext';
import CriteriaPanel from '../components/cohort/CriteriaPanel';
import QueryCanvas from '../components/cohort/QueryCanvas';
import ResultsPanel from '../components/cohort/ResultsPanel';
import CharacterizationPanel from '../components/cohort/CharacterizationPanel';
import CohortComparisonPanel from '../components/cohort/CohortComparisonPanel';
import PatientJourney from '../components/cohort/PatientJourney';
import { cohortApi } from '../api/client';
import type {
  CohortCriterion,
  CohortCriteria, CohortSummary,
} from '../types';

const { Text } = Typography;

function emptyCriteria(): CohortCriteria {
  return {
    inclusion: { operator: 'AND', criteria: [], groups: [] },
    exclusion: { operator: 'OR', criteria: [], groups: [] },
    demographics: {},
  };
}

interface Props {
  selectedCdm: string | null;
}

export default function CohortPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const { roles } = useAuth();
  const canDelete = roles.includes('admin') || roles.includes('omop-dim');

  // Cohort state
  const [cohortName, setCohortName] = useState('');
  const [cohortDesc, setCohortDesc] = useState('');
  const [criteria, setCriteria] = useState<CohortCriteria>(emptyCriteria());
  const [savedCohortId, setSavedCohortId] = useState<number | undefined>();

  // Saved cohorts list
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [showList, setShowList] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadCohorts = useCallback(async () => {
    if (!selectedCdm) return;
    try {
      const resp = await cohortApi.list(selectedCdm);
      setCohorts(resp.data.cohorts);
    } catch {
      // ignore
    }
  }, [selectedCdm]);

  useEffect(() => {
    loadCohorts();
  }, [loadCohorts]);

  // Reset when CDM changes
  useEffect(() => {
    setCriteria(emptyCriteria());
    setSavedCohortId(undefined);
    setCohortName('');
    setCohortDesc('');
  }, [selectedCdm]);

  const handleAddCriterion = (criterion: CohortCriterion) => {
    setCriteria(prev => ({
      ...prev,
      inclusion: {
        ...prev.inclusion,
        criteria: [...prev.inclusion.criteria, criterion],
      },
    }));
  };

  const handleSave = async () => {
    if (!selectedCdm || !cohortName.trim()) {
      message.warning(t('cohort.enter_name', 'Please enter a cohort name'));
      return;
    }
    setSaving(true);
    try {
      // Prepare criteria for backend (strip client-side fields)
      const backendCriteria = toBackendCriteria(criteria);

      if (savedCohortId) {
        await cohortApi.update(savedCohortId, {
          name: cohortName,
          description: cohortDesc,
          criteria: backendCriteria,
        });
        message.success(t('cohort.saved', 'Cohort saved (new version)'));
      } else {
        const resp = await cohortApi.create({
          cdm_name: selectedCdm,
          name: cohortName,
          description: cohortDesc,
          criteria: backendCriteria,
        });
        setSavedCohortId(resp.data.id);
        message.success(t('cohort.created', 'Cohort created'));
      }
      loadCohorts();
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleLoad = async (cohortId: number) => {
    try {
      const resp = await cohortApi.get(cohortId);
      const detail = resp.data;
      setCohortName(detail.name);
      setCohortDesc(detail.description);
      setSavedCohortId(detail.id);

      const latestVersion = detail.versions[0];
      if (latestVersion) {
        const loaded = fromBackendCriteria(latestVersion.criteria_json);
        setCriteria(loaded);
      }
      setShowList(false);
    } catch (e: any) {
      message.error('Failed to load cohort');
    }
  };

  const handleDelete = async (cohortId: number) => {
    try {
      await cohortApi.delete(cohortId);
      message.success(t('common.deleted', 'Deleted'));
      if (savedCohortId === cohortId) {
        setSavedCohortId(undefined);
        setCohortName('');
        setCriteria(emptyCriteria());
      }
      loadCohorts();
    } catch {
      message.error('Delete failed');
    }
  };

  const handleNew = () => {
    setCriteria(emptyCriteria());
    setSavedCohortId(undefined);
    setCohortName('');
    setCohortDesc('');
    setSamplePatients([]);
    setSampleColumns([]);
  };

  // Active tab (builder vs characterization)
  const [activeTab, setActiveTab] = useState<string>('builder');

  // Detailed sample state
  const [samplePatients, setSamplePatients] = useState<Record<string, any>[]>([]);
  const [sampleColumns, setSampleColumns] = useState<{ key: string; label: string; domain: string }[]>([]);
  const [sampleLoading, setSampleLoading] = useState(false);

  // Patient journey state
  const [journeyPersonId, setJourneyPersonId] = useState<number | null>(null);

  const runDetailedSample = async () => {
    if (!selectedCdm) return;
    const backendCriteria = toBackendCriteria(criteria);
    setSampleLoading(true);
    try {
      const resp = await cohortApi.sampleDetailed(selectedCdm, backendCriteria, 10);
      setSamplePatients(resp.data.patients);
      setSampleColumns(resp.data.columns);
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Sampling failed');
    } finally {
      setSampleLoading(false);
    }
  };

  if (!selectedCdm) {
    return (
      <Empty description={t('cohort.select_cdm', 'Select a CDM connection to start building cohorts')} />
    );
  }

  return (
    <div style={{ height: 'calc(100vh - 72px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Card size="small" style={{ marginBottom: 8 }} bodyStyle={{ padding: '8px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Input
            placeholder={t('cohort.cohort_name', 'Cohort name...')}
            value={cohortName}
            onChange={e => setCohortName(e.target.value)}
            style={{ width: 250 }}
            size="small"
          />
          <Input
            placeholder={t('cohort.description', 'Description (optional)')}
            value={cohortDesc}
            onChange={e => setCohortDesc(e.target.value)}
            style={{ flex: 1 }}
            size="small"
          />
          <Button icon={<PlusOutlined />} size="small" onClick={handleNew}>
            {t('cohort.new', 'New')}
          </Button>
          <Button
            icon={<SaveOutlined />}
            type="primary"
            size="small"
            onClick={handleSave}
            loading={saving}
          >
            {t('common.save', 'Save')}
          </Button>
          <Button icon={<FolderOpenOutlined />} size="small" onClick={() => setShowList(true)}>
            {t('cohort.load', 'Load')} ({cohorts.length})
          </Button>
        </div>
      </Card>

      {/* Three-panel layout */}
      <Row gutter={8} style={{ flex: 1, overflow: 'hidden' }}>
        {/* Left: Criteria Panel */}
        <Col span={6} style={{ height: '100%', overflow: 'auto' }}>
          <CriteriaPanel
            cdmName={selectedCdm}
            onAddCriterion={handleAddCriterion}
          />
        </Col>

        {/* Center: Tabs — Builder / Characterization */}
        <Col span={12} style={{ height: '100%', overflow: 'auto' }}>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
            style={{ marginBottom: 0 }}
            items={[
              {
                key: 'builder',
                label: t('cohort.query_builder', 'Query Builder'),
                children: (
                  <>
                    <QueryCanvas
                      inclusion={criteria.inclusion}
                      exclusion={criteria.exclusion}
                      demographics={criteria.demographics || {}}
                      cdmName={selectedCdm || ''}
                      onUpdateInclusion={inc => setCriteria(prev => ({ ...prev, inclusion: inc }))}
                      onUpdateExclusion={exc => setCriteria(prev => ({ ...prev, exclusion: exc }))}
                      onUpdateDemographics={demo => setCriteria(prev => ({ ...prev, demographics: demo }))}
                    />

                    {/* Detailed Sample */}
                    <Card
                      size="small"
                      style={{ marginTop: 8 }}
                      title={<Space><UserOutlined />{t('cohort.sample_patients', 'Sample Patients')}</Space>}
                      extra={
                        <Button
                          size="small"
                          onClick={runDetailedSample}
                          loading={sampleLoading}
                          disabled={criteria.inclusion.criteria.length === 0}
                        >
                          {t('cohort.sample', 'Sample')}
                        </Button>
                      }
                    >
                      {sampleLoading ? (
                        <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
                      ) : samplePatients.length > 0 ? (
                        <Table
                          size="small"
                          dataSource={samplePatients}
                          rowKey={(_, idx) => String(idx)}
                          pagination={false}
                          scroll={{ x: true }}
                          columns={[
                            {
                              title: 'Person ID', dataIndex: 'person_id', key: 'pid', width: 90, fixed: 'left' as const,
                              render: (v: number) => (
                                <a onClick={() => setJourneyPersonId(v)} title={t('cohort.view_journey', 'View patient journey')}>
                                  {v}
                                </a>
                              ),
                            },
                            { title: t('cohort.birth_year', 'Birth Year'), dataIndex: 'year_of_birth', key: 'yob', width: 80 },
                            ...sampleColumns.map(col => ({
                              title: col.label,
                              dataIndex: col.key,
                              key: col.key,
                              width: col.key === 'visit_occurrence_id' ? 90 : 150,
                              ellipsis: true,
                              render: (v: any) => v != null ? String(v) : '—',
                            })),
                          ]}
                        />
                      ) : (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {t('cohort.click_sample', 'Click Sample to see random patients')}
                        </Typography.Text>
                      )}
                    </Card>
                  </>
                ),
              },
              {
                key: 'characterization',
                label: (
                  <Space size={4}>
                    <TableOutlined />
                    Table 1
                  </Space>
                ),
                children: (
                  <CharacterizationPanel
                    cdmName={selectedCdm || ''}
                    criteria={toBackendCriteria(criteria)}
                    cohortId={savedCohortId}
                  />
                ),
              },
              {
                key: 'comparison',
                label: (
                  <Space size={4}>
                    <SwapOutlined />
                    {t('cohort.compare', 'Compare')}
                  </Space>
                ),
                children: (
                  <CohortComparisonPanel
                    cdmName={selectedCdm || ''}
                    cohorts={cohorts}
                  />
                ),
              },
              {
                key: 'sql',
                label: (
                  <Space size={4}>
                    <CodeOutlined />
                    SQL
                  </Space>
                ),
                children: (
                  <SqlEditorPanel cdmName={selectedCdm || ''} />
                ),
              },
            ]}
          />
        </Col>

        {/* Right: Results Panel */}
        <Col span={6} style={{ height: '100%', overflow: 'auto' }}>
          <ResultsPanel
            cdmName={selectedCdm}
            criteria={toBackendCriteria(criteria)}
            savedCohortId={savedCohortId}
          />
        </Col>
      </Row>

      {/* Patient Journey modal */}
      <PatientJourney
        cdmName={selectedCdm || ''}
        personId={journeyPersonId}
        open={journeyPersonId !== null}
        onClose={() => setJourneyPersonId(null)}
      />

      {/* Load modal */}
      <Modal
        title={t('cohort.saved_cohorts', 'Saved Cohorts')}
        open={showList}
        onCancel={() => setShowList(false)}
        footer={null}
        width={600}
      >
        <List
          dataSource={cohorts}
          locale={{ emptyText: t('cohort.no_cohorts', 'No saved cohorts') }}
          renderItem={c => (
            <List.Item
              actions={[
                <Button size="small" type="link" onClick={() => handleLoad(c.id)}>
                  {t('cohort.load', 'Load')}
                </Button>,
                <Button size="small" type="link" onClick={() => {
                  if (c.id) {
                    cohortApi.execute(c.id).then(resp => {
                      message.success(`Count: ${resp.data.patient_count}`);
                      loadCohorts();
                    }).catch(() => message.error('Execution failed'));
                  }
                }}>
                  <PlayCircleOutlined />
                </Button>,
                ...(canDelete ? [<Popconfirm
                  title={t('common.confirm_delete', 'Delete?')}
                  onConfirm={() => handleDelete(c.id)}
                >
                  <Button size="small" type="link" danger>
                    <DeleteOutlined />
                  </Button>
                </Popconfirm>] : []),
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    {c.name}
                    <Tag>v{c.latest_version}</Tag>
                    {c.patient_count != null && (
                      <Tag color="green">{c.patient_count.toLocaleString()} patients</Tag>
                    )}
                  </Space>
                }
                description={
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {c.description || '—'} · {c.updated_at?.substring(0, 10)}
                  </Text>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    </div>
  );
}

// ──── SQL Editor Panel ────

function SqlEditorPanel({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const [sql, setSql] = useState('SELECT * FROM omop_cdm.person LIMIT 10');
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowCount, setRowCount] = useState(0);
  const [truncated, setTruncated] = useState(false);

  const handleExecute = async () => {
    if (!sql.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await cohortApi.executeSql(cdmName, sql);
      setColumns(resp.data.columns);
      setRows(resp.data.rows);
      setRowCount(resp.data.row_count);
      setTruncated(resp.data.truncated);
    } catch (e: any) {
      setError(e.message || 'Query failed');
      setColumns([]);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!sql.trim()) return;
    try {
      const resp = await cohortApi.exportSql(cdmName, sql);
      const blob = new Blob([resp.data], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'sql_export.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    } catch (e: any) {
      message.error(e.message || 'Export failed');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleExecute();
    }
  };

  return (
    <div>
      <Card size="small" style={{ marginBottom: 8 }}>
        <Input.TextArea
          value={sql}
          onChange={e => setSql(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="SELECT * FROM omop_cdm.person LIMIT 10"
          autoSize={{ minRows: 4, maxRows: 12 }}
          style={{ fontFamily: 'monospace', fontSize: 13 }}
        />
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleExecute}
            loading={loading}
          >
            {t('cohort.run_sql', 'Execute')} (Ctrl+Enter)
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={handleExport}
            disabled={!sql.trim()}
          >
            CSV
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {t('cohort.sql_readonly', 'Read-only queries only (SELECT/WITH)')}
          </Typography.Text>
        </div>
      </Card>

      {error && (
        <Alert message={error} type="error" showIcon closable onClose={() => setError(null)} style={{ marginBottom: 8 }} />
      )}

      {rows.length > 0 && (
        <Card size="small">
          <div style={{ marginBottom: 8 }}>
            <Tag color="blue">{rowCount} {t('cohort.sql_rows', 'rows')}</Tag>
            {truncated && <Tag color="orange">{t('cohort.sql_truncated', 'Truncated (add LIMIT to control)')}</Tag>}
          </div>
          <Table
            size="small"
            dataSource={rows}
            rowKey={(_, idx) => String(idx)}
            pagination={{ pageSize: 50, size: 'small', showSizeChanger: true }}
            scroll={{ x: true }}
            columns={columns.map(col => ({
              title: col,
              dataIndex: col,
              key: col,
              ellipsis: true,
              width: 150,
              render: (v: any) => v != null ? String(v) : <Typography.Text type="secondary">NULL</Typography.Text>,
            }))}
          />
        </Card>
      )}
    </div>
  );
}

// ──── Helpers to convert between frontend and backend criteria ────

function toBackendCriteria(criteria: CohortCriteria): CohortCriteria {
  const mapCriterion = (c: CohortCriterion) => ({
    ...c,
    concepts: c.concepts.map(con => ({
      concept_id: con.concept_id,
      concept_name: con.concept_name,
      concept_code: con.concept_code,
      domain_id: con.domain_id,
      vocabulary_id: con.vocabulary_id,
      concept_class_id: con.concept_class_id,
      standard_concept: con.standard_concept,
    })),
  });
  return {
    inclusion: {
      operator: criteria.inclusion.operator,
      criteria: criteria.inclusion.criteria.map(mapCriterion),
      sameVisit: criteria.inclusion.sameVisit,
    },
    exclusion: {
      operator: criteria.exclusion.operator,
      criteria: criteria.exclusion.criteria.map(mapCriterion),
      sameVisit: criteria.exclusion.sameVisit,
    },
    demographics: criteria.demographics,
  };
}

function fromBackendCriteria(backendCriteria: any): CohortCriteria {
  const mapCriteria = (criteria: any[]) =>
    (criteria || []).map((c: any) => ({
      id: c.id || Math.random().toString(36).slice(2) + Date.now().toString(36),
      domain: c.domain,
      concepts: (c.concepts || []).map((cid: any) =>
        typeof cid === 'object' && cid !== null
          ? { concept_id: cid.concept_id, concept_name: cid.concept_name || `Concept ${cid.concept_id}`, concept_code: cid.concept_code || '', domain_id: cid.domain_id || c.domain, vocabulary_id: cid.vocabulary_id || '', concept_class_id: cid.concept_class_id || '', standard_concept: cid.standard_concept ?? null }
          : { concept_id: cid, concept_name: `Concept ${cid}`, concept_code: '', domain_id: c.domain, vocabulary_id: '', concept_class_id: '', standard_concept: null }
      ),
      include_descendants: c.include_descendants ?? true,
      source_codes: c.source_codes || [],
      operatorWithNext: c.operatorWithNext,
      temporal: c.temporal || { type: 'any_time' },
      occurrence: c.occurrence || { type: 'any', count: 1 },
      value: c.value,
    }));

  return {
    inclusion: {
      operator: backendCriteria.inclusion?.operator || 'AND',
      criteria: mapCriteria(backendCriteria.inclusion?.criteria),
    },
    exclusion: {
      operator: backendCriteria.exclusion?.operator || 'OR',
      criteria: mapCriteria(backendCriteria.exclusion?.criteria),
    },
    demographics: backendCriteria.demographics || {},
  };
}
