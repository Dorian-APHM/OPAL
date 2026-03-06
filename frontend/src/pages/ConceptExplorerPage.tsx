import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Input, Select, Button, Table, Space, Typography, Tag, Switch,
  Tabs, Descriptions, List, Alert, Row, Col, Spin, Empty, Drawer, Radio,
} from 'antd';
import {
  SearchOutlined, ApartmentOutlined, LinkOutlined, FileTextOutlined, DatabaseOutlined, DownloadOutlined, StopOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { conceptApi, authDownload } from '../api/client';
import useIsMobile from '../hooks/useIsMobile';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

interface Props {
  selectedCdm: string | null;
}

interface ConceptItem {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  domain_id: string;
  vocabulary_id: string;
  concept_class_id: string;
  standard_concept: string | null;
  valid_start_date?: string;
  valid_end_date?: string;
  invalid_reason?: string | null;
}

interface RelationshipItem {
  relationship_id: string;
  related_concept_id: number;
  related_concept_name: string;
  related_vocabulary_id: string;
  related_concept_class_id: string;
  related_standard_concept: string | null;
}

interface HierarchyItem {
  concept_id: number;
  concept_name: string;
  concept_code: string;
  vocabulary_id: string;
  concept_class_id: string;
  standard_concept: string | null;
  min_levels_of_separation: number;
  max_levels_of_separation: number;
}

interface SourceValueItem {
  domain: string;
  source_value: string;
  n_records: number;
  n_persons: number;
}

interface SourceValueSearchResult {
  domain: string;
  source_value: string;
  source_name: string | null;
  n_records: number;
  n_persons: number;
  mapped_concept_id: number | null;
  mapped_concept_name: string | null;
  mapped_vocabulary_id: string | null;
  mapped_standard_concept: string | null;
}

export default function ConceptExplorerPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [query, setQuery] = useState('');
  const [domainFilter, setDomainFilter] = useState<string | undefined>();
  const [vocabFilter, setVocabFilter] = useState<string | undefined>();
  const [standardOnly, setStandardOnly] = useState(false);
  const [concepts, setConcepts] = useState<ConceptItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [domains, setDomains] = useState<{ domain_id: string; count: number }[]>([]);
  const [vocabs, setVocabs] = useState<{ vocabulary_id: string; count: number }[]>([]);
  const [searchMode, setSearchMode] = useState<'concept' | 'source'>('concept');
  const [sourceResults, setSourceResults] = useState<SourceValueSearchResult[]>([]);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourcePage, setSourcePage] = useState(1);
  const [conceptCounts, setConceptCounts] = useState<Record<number, { n_records: number; n_persons: number }>>({});
  const [countsLoading, setCountsLoading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const cancelSearch = () => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setLoading(false);
    setSourceLoading(false);
  };

  // Detail panel
  const [selectedConcept, setSelectedConcept] = useState<ConceptItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [relationships, setRelationships] = useState<RelationshipItem[]>([]);
  const [synonyms, setSynonyms] = useState<{ concept_synonym_name: string }[]>([]);
  const [ancestors, setAncestors] = useState<HierarchyItem[]>([]);
  const [descendants, setDescendants] = useState<HierarchyItem[]>([]);
  const [sourceValues, setSourceValues] = useState<SourceValueItem[]>([]);

  useEffect(() => {
    if (!selectedCdm) return;
    conceptApi.domains(selectedCdm).then((res) => setDomains(res.data.domains)).catch(() => {});
    conceptApi.vocabularies(selectedCdm).then((res) => setVocabs(res.data.vocabularies)).catch(() => {});
  }, [selectedCdm]);

  const doSearch = useCallback(async (p: number = 1) => {
    if (!selectedCdm) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      const res = await conceptApi.search(selectedCdm, {
        q: query, domain: domainFilter, vocabulary: vocabFilter,
        standard_only: standardOnly, limit: 50, offset: (p - 1) * 50,
      });
      if (ctrl.signal.aborted) return;
      setConcepts(res.data.concepts);
      setTotal(res.data.total);
      setPage(p);
      // Fetch record/person counts for returned concepts
      const ids = res.data.concepts.map((c: ConceptItem) => c.concept_id);
      if (ids.length > 0 && selectedCdm) {
        setCountsLoading(true);
        conceptApi.counts(selectedCdm, ids)
          .then(cRes => { if (!ctrl.signal.aborted) setConceptCounts(cRes.data.counts); })
          .catch(() => {})
          .finally(() => { if (!ctrl.signal.aborted) setCountsLoading(false); });
      } else {
        setConceptCounts({});
      }
    } catch {
      if (ctrl.signal.aborted) return;
      setConcepts([]);
      setTotal(0);
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  }, [selectedCdm, query, domainFilter, vocabFilter, standardOnly]);

  const doSourceSearch = useCallback(async (p: number = 1) => {
    if (!selectedCdm || !query) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSourceLoading(true);
    try {
      const res = await conceptApi.searchSourceValue(selectedCdm, {
        q: query, domain: domainFilter, limit: 50, offset: (p - 1) * 50,
      });
      if (ctrl.signal.aborted) return;
      setSourceResults(res.data.results);
      setSourceTotal(res.data.total);
      setSourcePage(p);
    } catch {
      if (ctrl.signal.aborted) return;
      setSourceResults([]);
      setSourceTotal(0);
    } finally {
      if (!ctrl.signal.aborted) setSourceLoading(false);
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  }, [selectedCdm, query, domainFilter]);

  const handleSearch = useCallback((p: number = 1) => {
    if (searchMode === 'concept') {
      doSearch(p);
    } else {
      doSourceSearch(p);
    }
  }, [searchMode, doSearch, doSourceSearch]);

  const openDetail = async (concept: ConceptItem) => {
    if (!selectedCdm) return;
    setSelectedConcept(concept);
    setDetailLoading(true);
    setRelationships([]);
    setSynonyms([]);
    setAncestors([]);
    setDescendants([]);
    setSourceValues([]);

    try {
      const [detailRes, hierRes, svRes] = await Promise.all([
        conceptApi.details(selectedCdm, concept.concept_id),
        conceptApi.hierarchy(selectedCdm, concept.concept_id),
        conceptApi.sourceValues(selectedCdm, concept.concept_id),
      ]);
      setRelationships(detailRes.data.relationships || []);
      setSynonyms(detailRes.data.synonyms || []);
      setAncestors(hierRes.data.ancestors || []);
      setDescendants(hierRes.data.descendants || []);
      setSourceValues(svRes.data.source_values || []);
    } catch { /* ignore */ }
    finally { setDetailLoading(false); }
  };

  if (!selectedCdm) {
    return (
      <div>
        <Title level={3}>{t('concept.title')}</Title>
        <Alert message={t('cdm.select_cdm')} type="info" showIcon />
      </div>
    );
  }

  const baseColumns = [
    {
      title: 'ID', dataIndex: 'concept_id', width: 90,
      render: (id: number) => <a onClick={() => { const c = concepts.find(x => x.concept_id === id); if (c) openDetail(c); }}>{id}</a>,
    },
    { title: t('concept.concept_name'), dataIndex: 'concept_name', ellipsis: true },
    { title: 'Code', dataIndex: 'concept_code', width: 120 },
    { title: t('concept.domain'), dataIndex: 'domain_id', width: 120 },
    { title: t('concept.vocabulary'), dataIndex: 'vocabulary_id', width: 120 },
    { title: 'Class', dataIndex: 'concept_class_id', width: 120 },
    {
      title: 'Std', dataIndex: 'standard_concept', width: 60,
      render: (v: string | null) => v === 'S' ? <Tag color="green">S</Tag> : v === 'C' ? <Tag color="blue">C</Tag> : <Tag>-</Tag>,
    },
    {
      title: t('quality.n_records'), dataIndex: 'concept_id', key: 'n_records', width: 100,
      render: (id: number) => {
        const c = conceptCounts[id];
        return c ? c.n_records.toLocaleString() : countsLoading ? <Spin size="small" /> : '—';
      },
    },
    {
      title: t('quality.n_persons'), dataIndex: 'concept_id', key: 'n_persons', width: 100,
      render: (id: number) => {
        const c = conceptCounts[id];
        return c ? c.n_persons.toLocaleString() : countsLoading ? <Spin size="small" /> : '—';
      },
    },
  ];

  // On mobile, only show essential columns
  const columns = isMobile
    ? baseColumns.filter((c) => ['concept_id', 'concept_name', 'standard_concept'].includes(c.dataIndex as string))
    : baseColumns;

  const sourceColumns = [
    { title: t('concept.source_value'), dataIndex: 'source_value', ellipsis: true, render: (_: string, r: SourceValueSearchResult) => r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value },
    { title: t('concept.domain'), dataIndex: 'domain', width: 110 },
    { title: t('quality.n_records'), dataIndex: 'n_records', width: 90, render: (v: number) => v?.toLocaleString() },
    ...(!isMobile ? [{ title: t('quality.n_persons'), dataIndex: 'n_persons', width: 90, render: (v: number) => v?.toLocaleString() }] : []),
    {
      title: t('concept.mapped_concept'), dataIndex: 'mapped_concept_name', ellipsis: true,
      render: (name: string | null, r: SourceValueSearchResult) => {
        if (!r.mapped_concept_id || r.mapped_concept_id === 0) return <Tag>—</Tag>;
        return (
          <a onClick={() => openDetail({
            concept_id: r.mapped_concept_id!,
            concept_name: r.mapped_concept_name || '',
            concept_code: '',
            domain_id: r.domain,
            vocabulary_id: r.mapped_vocabulary_id || '',
            concept_class_id: '',
            standard_concept: r.mapped_standard_concept,
          })}>
            {name} {r.mapped_standard_concept === 'S' && <Tag color="green" style={{ marginLeft: 4 }}>S</Tag>}
          </a>
        );
      },
    },
  ];

  const detailContent = selectedConcept ? (
    detailLoading ? (
      <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
    ) : (
      <Tabs defaultActiveKey="info" size="small">
        <TabPane tab={t('concept.info')} key="info">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="Concept ID">{selectedConcept.concept_id}</Descriptions.Item>
            <Descriptions.Item label={t('concept.concept_name')}>{selectedConcept.concept_name}</Descriptions.Item>
            <Descriptions.Item label="Code">{selectedConcept.concept_code}</Descriptions.Item>
            <Descriptions.Item label={t('concept.domain')}>{selectedConcept.domain_id}</Descriptions.Item>
            <Descriptions.Item label={t('concept.vocabulary')}>{selectedConcept.vocabulary_id}</Descriptions.Item>
            <Descriptions.Item label="Class">{selectedConcept.concept_class_id}</Descriptions.Item>
            <Descriptions.Item label="Standard">
              {selectedConcept.standard_concept === 'S' ? <Tag color="green">Standard</Tag> :
               selectedConcept.standard_concept === 'C' ? <Tag color="blue">Classification</Tag> :
               <Tag>Non-standard</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Valid">{selectedConcept.valid_start_date} — {selectedConcept.valid_end_date}</Descriptions.Item>
          </Descriptions>
          {synonyms.length > 0 && (
            <>
              <Text strong style={{ display: 'block', marginTop: 12, marginBottom: 4 }}>{t('concept.synonyms')}</Text>
              {synonyms.map((s, i) => <Tag key={i}>{s.concept_synonym_name}</Tag>)}
            </>
          )}
        </TabPane>

        <TabPane tab={<><LinkOutlined /> {t('concept.relationships')} ({relationships.length})</>} key="rels">
          {relationships.length === 0 ? <Empty description={t('concept.no_relationships')} /> : (
            <Table
              dataSource={relationships}
              rowKey={(r, i) => `${r.relationship_id}-${r.related_concept_id}-${i}`}
              size="small"
              pagination={{ pageSize: 10, size: 'small' }}
              columns={[
                { title: t('concept.relationship'), dataIndex: 'relationship_id', width: 140 },
                {
                  title: 'Concept', dataIndex: 'related_concept_name', ellipsis: true,
                  render: (name: string, r: RelationshipItem) => (
                    <a onClick={() => {
                      const fake: ConceptItem = {
                        concept_id: r.related_concept_id,
                        concept_name: r.related_concept_name,
                        concept_code: '',
                        domain_id: '',
                        vocabulary_id: r.related_vocabulary_id,
                        concept_class_id: r.related_concept_class_id,
                        standard_concept: r.related_standard_concept,
                      };
                      openDetail(fake);
                    }}>{name}</a>
                  ),
                },
                ...(!isMobile ? [
                  { title: t('concept.vocabulary'), dataIndex: 'related_vocabulary_id', width: 100 },
                  {
                    title: 'Std', dataIndex: 'related_standard_concept', width: 50,
                    render: (v: string | null) => v === 'S' ? <Tag color="green">S</Tag> : v ? <Tag>{v}</Tag> : '-',
                  },
                ] : []),
              ]}
            />
          )}
        </TabPane>

        <TabPane tab={<><ApartmentOutlined /> {t('concept.hierarchy')}</>} key="hier">
          {ancestors.length > 0 && (
            <>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>{t('concept.ancestors')} ({ancestors.length})</Text>
              <List
                size="small"
                dataSource={ancestors}
                style={{ marginBottom: 16, maxHeight: 200, overflowY: 'auto' }}
                renderItem={(a) => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <Space>
                      <Tag color="orange">L{a.min_levels_of_separation}</Tag>
                      <a onClick={() => openDetail({ ...a, domain_id: '', concept_class_id: a.concept_class_id } as any)}>
                        {a.concept_name}
                      </a>
                      <Text type="secondary">{a.vocabulary_id}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </>
          )}
          {descendants.length > 0 && (
            <>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>{t('concept.descendants')} ({descendants.length})</Text>
              <List
                size="small"
                dataSource={descendants}
                style={{ maxHeight: 300, overflowY: 'auto' }}
                renderItem={(d) => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <Space>
                      <Tag color="cyan">L{d.min_levels_of_separation}</Tag>
                      <a onClick={() => openDetail({ ...d, domain_id: '', concept_class_id: d.concept_class_id } as any)}>
                        {d.concept_name}
                      </a>
                      <Text type="secondary">{d.vocabulary_id}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </>
          )}
          {ancestors.length === 0 && descendants.length === 0 && (
            <Empty description={t('concept.no_hierarchy')} />
          )}
        </TabPane>

        <TabPane tab={<><FileTextOutlined /> {t('concept.source_values')} ({sourceValues.length})</>} key="sv">
          {sourceValues.length === 0 ? <Empty description={t('concept.no_source_values')} /> : (
            <Table
              dataSource={sourceValues}
              rowKey={(r, i) => `${r.domain}-${r.source_value}-${i}`}
              size="small"
              pagination={{ pageSize: 10, size: 'small' }}
              columns={[
                { title: t('concept.domain'), dataIndex: 'domain', width: 120 },
                { title: t('concept.source_value'), dataIndex: 'source_value', ellipsis: true },
                { title: t('quality.n_records'), dataIndex: 'n_records', width: 90, render: (v: number) => v.toLocaleString() },
                { title: t('quality.n_persons'), dataIndex: 'n_persons', width: 90, render: (v: number) => v.toLocaleString() },
              ]}
            />
          )}
        </TabPane>
      </Tabs>
    )
  ) : null;

  return (
    <div>
      <Title level={3} style={{ marginBottom: 16, fontSize: isMobile ? 18 : undefined }}>
        {t('concept.title')} — {selectedCdm}
      </Title>

      <Row gutter={16}>
        {/* Search panel */}
        <Col xs={24} md={selectedConcept && !isMobile ? 14 : 24}>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Radio.Group
              value={searchMode}
              onChange={(e) => setSearchMode(e.target.value)}
              style={{ marginBottom: 12 }}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="concept"><SearchOutlined /> {t('concept.by_concept')}</Radio.Button>
              <Radio.Button value="source"><DatabaseOutlined /> {t('concept.by_source_code')}</Radio.Button>
            </Radio.Group>
            <Space wrap style={{ width: '100%' }}>
              <Input
                placeholder={searchMode === 'concept' ? t('concept.search_placeholder') : t('concept.search_source_placeholder')}
                prefix={<SearchOutlined />}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onPressEnter={() => handleSearch(1)}
                style={{ width: isMobile ? '100%' : 280 }}
                allowClear
              />
              <Select
                placeholder={t('concept.domain')}
                value={domainFilter}
                onChange={setDomainFilter}
                style={{ width: isMobile ? '100%' : 160 }}
                allowClear
                options={domains.map((d) => ({ value: d.domain_id, label: `${d.domain_id} (${d.count.toLocaleString()})` }))}
              />
              {searchMode === 'concept' && (
                <>
                  <Select
                    placeholder={t('concept.vocabulary')}
                    value={vocabFilter}
                    onChange={setVocabFilter}
                    style={{ width: isMobile ? '100%' : 180 }}
                    allowClear
                    showSearch
                    filterOption={(input, option) =>
                      (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                    options={vocabs.map((v) => ({ value: v.vocabulary_id, label: `${v.vocabulary_id} (${v.count.toLocaleString()})` }))}
                  />
                  <Switch
                    checked={standardOnly}
                    onChange={setStandardOnly}
                    checkedChildren={t('concept.standard_only')}
                    unCheckedChildren={t('concept.standard_only')}
                  />
                </>
              )}
              {(loading || sourceLoading) ? (
                <Button danger icon={<StopOutlined />} onClick={cancelSearch} block={isMobile}>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button type="primary" icon={<SearchOutlined />} onClick={() => handleSearch(1)} block={isMobile}>
                  {t('concept.search')}
                </Button>
              )}
              {searchMode === 'source' && sourceResults.length > 0 && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => authDownload(conceptApi.exportSourceValueUrl(selectedCdm!, query, domainFilter))}
                >
                  CSV
                </Button>
              )}
            </Space>
          </Card>

          {searchMode === 'concept' ? (
            <Table
              dataSource={concepts}
              columns={columns}
              rowKey="concept_id"
              loading={loading}
              size="small"
              scroll={isMobile ? { x: 400 } : undefined}
              pagination={{
                current: page,
                total,
                pageSize: 50,
                showTotal: isMobile ? undefined : (t) => `${t.toLocaleString()} concepts`,
                onChange: (p) => doSearch(p),
                size: 'small',
              }}
              onRow={(record) => ({
                onClick: () => openDetail(record),
                style: { cursor: 'pointer' },
              })}
            />
          ) : (
            <Table
              dataSource={sourceResults}
              columns={sourceColumns}
              rowKey={(r, i) => `${r.domain}-${r.source_value}-${r.mapped_concept_id}-${i}`}
              loading={sourceLoading}
              size="small"
              scroll={isMobile ? { x: 400 } : undefined}
              pagination={{
                current: sourcePage,
                total: sourceTotal,
                pageSize: 50,
                showTotal: isMobile ? undefined : (total) => `${total.toLocaleString()} results`,
                onChange: (p) => doSourceSearch(p),
                size: 'small',
              }}
            />
          )}
        </Col>

        {/* Detail panel — desktop: inline side panel */}
        {selectedConcept && !isMobile && (
          <Col md={10}>
            <Card
              size="small"
              title={
                <Space>
                  <Tag color="blue">{selectedConcept.concept_id}</Tag>
                  <Text strong ellipsis>{selectedConcept.concept_name}</Text>
                </Space>
              }
              extra={<Button type="text" size="small" onClick={() => setSelectedConcept(null)}>{t('common.close')}</Button>}
            >
              {detailContent}
            </Card>
          </Col>
        )}
      </Row>

      {/* Detail panel — mobile: bottom drawer */}
      {isMobile && (
        <Drawer
          open={!!selectedConcept}
          onClose={() => setSelectedConcept(null)}
          placement="bottom"
          height="85vh"
          title={
            selectedConcept ? (
              <Space>
                <Tag color="blue">{selectedConcept.concept_id}</Tag>
                <Text strong ellipsis>{selectedConcept.concept_name}</Text>
              </Space>
            ) : null
          }
        >
          {detailContent}
        </Drawer>
      )}
    </div>
  );
}
