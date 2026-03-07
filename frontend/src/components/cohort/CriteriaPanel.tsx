import { useState, useEffect } from 'react';
import { Card, Input, Select, Tag, List, Typography, Spin, Empty, Space } from 'antd';
import { SearchOutlined, PlusOutlined, CodeOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cohortApi, conceptApi } from '../../api/client';
import type { OmopConcept, CohortCriterion } from '../../types';

const { Text } = Typography;
const { Option } = Select;

interface Props {
  cdmName: string;
  onAddCriterion: (criterion: CohortCriterion) => void;
}

export default function CriteriaPanel({ cdmName, onAddCriterion }: Props) {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDomain, setSearchDomain] = useState<string | undefined>();
  const [searchVocab, setSearchVocab] = useState<string | undefined>();
  const [concepts, setConcepts] = useState<OmopConcept[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);
  const [vocabularies, setVocabularies] = useState<{ vocabulary_id: string; vocabulary_name: string }[]>([]);
  const [domains, setDomains] = useState<{ name: string; table: string }[]>([]);

  useEffect(() => {
    cohortApi.listDomains().then(r => setDomains(r.data.domains));
    if (cdmName) {
      cohortApi.listVocabularies(cdmName).then(r => setVocabularies(r.data.vocabularies)).catch(() => {});
    }
  }, [cdmName]);

  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2 || !cdmName) {
      setConcepts([]);
      return;
    }
    const timer = setTimeout(() => {
      setLoading(true);
      cohortApi.searchConcepts(cdmName, searchQuery, searchDomain, searchVocab)
        .then(r => setConcepts(r.data.concepts))
        .catch(() => setConcepts([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchDomain, searchVocab, cdmName]);

  const toggleConcept = (concept: OmopConcept) => {
    setSelectedConcepts(prev => {
      const exists = prev.find(c => c.concept_id === concept.concept_id);
      if (exists) return prev.filter(c => c.concept_id !== concept.concept_id);
      return [...prev, concept];
    });
  };

  const addAsCriterion = (domain?: string) => {
    if (selectedConcepts.length === 0) return;
    const inferredDomain = domain || selectedConcepts[0].domain_id;
    const criterion: CohortCriterion = {
      id: Math.random().toString(36).slice(2) + Date.now().toString(36),
      domain: inferredDomain,
      concepts: selectedConcepts,
      include_descendants: true,
      source_codes: [],
      temporal: { type: 'any_time' },
      occurrence: { type: 'any', count: 1 },
    };
    onAddCriterion(criterion);
    setSelectedConcepts([]);
  };

  const [sourceCodeDomain, setSourceCodeDomain] = useState<string>('Procedure');
  const [sourceSearchQuery, setSourceSearchQuery] = useState('');
  const [sourceSearchResults, setSourceSearchResults] = useState<{ source_value: string; source_name?: string; domain: string; n_records: number; n_persons: number }[]>([]);
  const [sourceSearchLoading, setSourceSearchLoading] = useState(false);
  const [selectedSourceCodes, setSelectedSourceCodes] = useState<string[]>([]);

  // Source code keyword search
  useEffect(() => {
    if (!sourceSearchQuery || sourceSearchQuery.length < 2 || !cdmName) {
      setSourceSearchResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setSourceSearchLoading(true);
      conceptApi.searchSourceValue(cdmName, { q: sourceSearchQuery, domain: sourceCodeDomain, limit: 20 })
        .then(r => setSourceSearchResults(r.data.results))
        .catch(() => setSourceSearchResults([]))
        .finally(() => setSourceSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [sourceSearchQuery, sourceCodeDomain, cdmName]);

  const toggleSourceCode = (code: string) => {
    setSelectedSourceCodes(prev =>
      prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
    );
  };

  const addSelectedSourceCodes = () => {
    const codes = selectedSourceCodes.length > 0 ? selectedSourceCodes : [];
    if (codes.length === 0) return;
    const criterion: CohortCriterion = {
      id: Math.random().toString(36).slice(2) + Date.now().toString(36),
      domain: sourceCodeDomain,
      concepts: [],
      include_descendants: false,
      source_codes: codes,
      temporal: { type: 'any_time' },
      occurrence: { type: 'any', count: 1 },
    };
    onAddCriterion(criterion);
    setSelectedSourceCodes([]);
  };


  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Source code input */}
      <Card size="small" title={<><CodeOutlined /> {t('cohort.source_code_search', 'Source Code')}</>} bodyStyle={{ padding: 8 }}>
        <Space size={4} style={{ width: '100%' }} direction="vertical">
          <Select
            size="small"
            value={sourceCodeDomain}
            onChange={setSourceCodeDomain}
            style={{ width: '100%' }}
          >
            {domains.map(d => (
              <Option key={d.name} value={d.name}>{d.name}</Option>
            ))}
          </Select>
          <Input
            size="small"
            prefix={<SearchOutlined />}
            placeholder={t('cohort.search_source_placeholder', 'Search by keyword...')}
            value={sourceSearchQuery}
            onChange={e => setSourceSearchQuery(e.target.value)}
            allowClear
          />
          {/* Selected source codes */}
          {selectedSourceCodes.length > 0 && (
            <div style={{ padding: 4, background: '#f0f5ff', borderRadius: 4 }}>
              <Space size={[4, 4]} wrap>
                {selectedSourceCodes.map(code => (
                  <Tag key={code} closable onClose={() => toggleSourceCode(code)} color="blue">{code}</Tag>
                ))}
                <Tag color="green" style={{ cursor: 'pointer' }} onClick={addSelectedSourceCodes}>
                  <PlusOutlined /> {t('cohort.add_criterion', 'Add as criterion')}
                </Tag>
              </Space>
            </div>
          )}

          {/* Source search results */}
          {sourceSearchLoading ? (
            <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /></div>
          ) : sourceSearchResults.length > 0 ? (
            <List
              size="small"
              dataSource={sourceSearchResults}
              style={{ maxHeight: 200, overflow: 'auto' }}
              renderItem={r => {
                const isSelected = selectedSourceCodes.includes(r.source_value);
                return (
                  <List.Item
                    style={{ cursor: 'pointer', background: isSelected ? '#e6f7ff' : undefined, padding: '4px 8px' }}
                    onClick={() => toggleSourceCode(r.source_value)}
                  >
                    <div style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <Text strong style={{ fontSize: 12 }}>{r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value}</Text>
                        <Text type="secondary" style={{ fontSize: 10 }}>{r.n_records.toLocaleString()} rec</Text>
                      </div>
                      <div style={{ fontSize: 11, color: '#999' }}>{r.domain} · {r.n_persons.toLocaleString()} pers</div>
                    </div>
                  </List.Item>
                );
              }}
            />
          ) : sourceSearchQuery.length >= 2 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('cohort.no_source_codes', 'No source codes found')} style={{ margin: 8 }} />
          ) : null}
        </Space>
      </Card>

      {/* Concept search */}
      <Card size="small" title={t('cohort.concept_search', 'Concept Search')} bodyStyle={{ padding: 8 }} style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('cohort.search_placeholder', 'Search by name or code...')}
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          allowClear
          size="small"
          style={{ marginBottom: 8 }}
        />
        <Space size={4} style={{ marginBottom: 8 }}>
          <Select
            size="small"
            placeholder={t('cohort.domain', 'Domain')}
            value={searchDomain}
            onChange={v => setSearchDomain(v)}
            allowClear
            style={{ width: 120 }}
          >
            {domains.map(d => (
              <Option key={d.name} value={d.name}>{d.name}</Option>
            ))}
          </Select>
          <Select
            size="small"
            placeholder={t('cohort.vocabulary', 'Vocabulary')}
            value={searchVocab}
            onChange={v => setSearchVocab(v)}
            allowClear
            style={{ width: 120 }}
            showSearch
            filterOption={(input, option) =>
              (option?.children as unknown as string)?.toLowerCase().includes(input.toLowerCase()) ?? false
            }
          >
            {vocabularies.map(v => (
              <Option key={v.vocabulary_id} value={v.vocabulary_id}>{v.vocabulary_id}</Option>
            ))}
          </Select>
        </Space>

        {/* Selected concepts */}
        {selectedConcepts.length > 0 && (
          <div style={{ marginBottom: 8, padding: 4, background: '#f0f5ff', borderRadius: 4 }}>
            <Space size={[4, 4]} wrap>
              {selectedConcepts.map(c => (
                <Tag
                  key={c.concept_id}
                  closable
                  onClose={() => toggleConcept(c)}
                  color="blue"
                >
                  {c.concept_name}
                </Tag>
              ))}
              <Tag
                color="green"
                style={{ cursor: 'pointer' }}
                onClick={() => addAsCriterion()}
              >
                <PlusOutlined /> {t('cohort.add_criterion', 'Add as criterion')}
              </Tag>
            </Space>
          </div>
        )}

        {/* Search results */}
        <div style={{ maxHeight: 300, overflow: 'auto' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
          ) : concepts.length > 0 ? (
            <List
              size="small"
              dataSource={concepts}
              renderItem={c => {
                const isSelected = selectedConcepts.some(s => s.concept_id === c.concept_id);
                return (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      background: isSelected ? '#e6f7ff' : undefined,
                      padding: '4px 8px',
                    }}
                    onClick={() => toggleConcept(c)}
                  >
                    <div style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <Text strong style={{ fontSize: 12 }}>{c.concept_name}</Text>
                        {c.standard_concept === 'S' && <Tag color="green" style={{ fontSize: 10 }}>S</Tag>}
                      </div>
                      <div style={{ fontSize: 11, color: '#999' }}>
                        {c.concept_code} · {c.vocabulary_id} · {c.domain_id}
                      </div>
                    </div>
                  </List.Item>
                );
              }}
            />
          ) : searchQuery.length >= 2 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('cohort.no_concepts', 'No concepts found')} />
          ) : null}
        </div>
      </Card>
    </div>
  );
}
