import { useState, useEffect, useCallback, useRef } from 'react';
import { useSessionState } from '../hooks/useSessionState';
import {
  Card, Input, Select, Button, Table, Tag, Switch, Tabs, Drawer, Alert, Empty, Spinner, Tooltip, useToast,
} from '../components/ui';
import type { Column, TabItem } from '../components/ui';
import {
  Search, GitBranch, Link, FileText, Database, Download, StopCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { conceptApi } from '../api/client';
import useIsMobile from '../hooks/useIsMobile';

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
  pending?: boolean;
}

const DOMAIN_NOMENCLATURE: Record<string, string> = {
  Condition: 'CIM-10',
  Procedure: 'CCAM',
  Drug: 'ATC / UCD',
};

export default function ConceptExplorerPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const isMobile = useIsMobile();
  const [query, setQuery] = useSessionState('concepts:query', '');
  const [domainFilter, setDomainFilter] = useSessionState('concepts:domainFilter', undefined as string | undefined);
  const [vocabFilter, setVocabFilter] = useSessionState('concepts:vocabFilter', undefined as string | undefined);
  const [standardOnly, setStandardOnly] = useSessionState('concepts:standardOnly', false);
  const [concepts, setConcepts] = useSessionState('concepts:results', [] as ConceptItem[]);
  const [total, setTotal] = useSessionState('concepts:total', 0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useSessionState('concepts:page', 1);
  const [domains, setDomains] = useSessionState<{ domain_id: string; count: number }[]>('concepts:domains', []);
  const [vocabs, setVocabs] = useSessionState<{ vocabulary_id: string; count: number }[]>('concepts:vocabs', []);
  const [searchMode, setSearchMode] = useSessionState('concepts:searchMode', 'concept' as 'concept' | 'source');
  const [sourceResults, setSourceResults] = useState<SourceValueSearchResult[]>([]);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourcePage, setSourcePage] = useState(1);
  const [sourceSearchKey, setSourceSearchKey] = useState(0);
  const [conceptCounts, setConceptCounts] = useSessionState<Record<number, { n_records: number; n_persons: number }>>('concepts:counts', {});
  const [countsLoading, setCountsLoading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const cancelSearch = () => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setLoading(false);
    setSourceLoading(false);
  };

  // Detail panel
  const [selectedConcept, setSelectedConcept] = useSessionState('concepts:selectedConcept', null as ConceptItem | null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [relationships, setRelationships] = useState<RelationshipItem[]>([]);
  const [synonyms, setSynonyms] = useState<{ concept_synonym_name: string }[]>([]);
  const [ancestors, setAncestors] = useState<HierarchyItem[]>([]);
  const [descendants, setDescendants] = useState<HierarchyItem[]>([]);
  const [sourceValues, setSourceValues] = useState<SourceValueItem[]>([]);

  useEffect(() => {
    if (!selectedCdm) return;
    conceptApi.domains(selectedCdm).then((res) => setDomains(res.data.domains ?? [])).catch(() => toast.error(t('concepts.load_failed', 'Failed to load domains')));
    conceptApi.vocabularies(selectedCdm).then((res) => setVocabs(res.data.vocabularies ?? [])).catch(() => toast.error(t('concepts.load_failed', 'Failed to load vocabularies')));
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
      const concepts = res.data.concepts ?? [];
      setConcepts(concepts);
      setTotal(res.data.total ?? 0);
      setPage(p);
      // Fetch record/person counts for returned concepts
      const ids = concepts.map((c: ConceptItem) => c.concept_id);
      if (ids.length > 0 && selectedCdm) {
        setCountsLoading(true);
        conceptApi.counts(selectedCdm, ids)
          .then(cRes => { if (!ctrl.signal.aborted) setConceptCounts(cRes.data.counts); })
          .catch(() => toast.error(t('concepts.counts_failed', 'Failed to load concept counts')))
          .finally(() => { if (!ctrl.signal.aborted) setCountsLoading(false); });
      } else {
        setConceptCounts({});
      }
    } catch {
      if (ctrl.signal.aborted) return;
      setConcepts([]);
      setTotal(0);
      toast.error(t('common.error', 'An error occurred'));
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
    setSourceResults([]);
    setSourceTotal(0);
    setSourcePage(1);
    setSourceSearchKey(k => k + 1);
    try {
      const res = await conceptApi.searchSourceValue(selectedCdm, {
        q: query, domain: domainFilter, limit: 50, offset: (p - 1) * 50,
      });
      if (ctrl.signal.aborted) return;
      setSourceResults(res.data.results ?? []);
      setSourceTotal(res.data.total ?? 0);
      setSourcePage(p);
    } catch {
      if (ctrl.signal.aborted) return;
      setSourceResults([]);
      setSourceTotal(0);
      toast.error(t('common.error', 'An error occurred'));
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

    const results = await Promise.allSettled([
      conceptApi.details(selectedCdm, concept.concept_id),
      conceptApi.hierarchy(selectedCdm, concept.concept_id),
      conceptApi.sourceValues(selectedCdm, concept.concept_id),
    ]);
    const [detailRes, hierRes, svRes] = results;
    if (detailRes.status === 'fulfilled') {
      setRelationships(detailRes.value.data.relationships || []);
      setSynonyms(detailRes.value.data.synonyms || []);
    }
    if (hierRes.status === 'fulfilled') {
      setAncestors(hierRes.value.data.ancestors || []);
      setDescendants(hierRes.value.data.descendants || []);
    }
    if (svRes.status === 'fulfilled') {
      setSourceValues(svRes.value.data.source_values || []);
    }
    if (results.some(r => r.status === 'rejected')) {
      toast.error(t('common.error', 'An error occurred'));
    }
    setDetailLoading(false);
  };

  if (!selectedCdm) {
    return (
      <div>
        <h3 className="text-lg font-semibold text-text-bright mb-4">{t('concept.title')}</h3>
        <Alert type="info" message={t('cdm.select_cdm')} />
      </div>
    );
  }

  const baseColumns: Column<ConceptItem>[] = [
    {
      key: 'concept_id', title: 'ID', dataIndex: 'concept_id', width: 90,
      render: (id: number) => (
        <a
          className="text-emerald-accent hover:underline cursor-pointer"
          onClick={() => { const c = concepts.find(x => x.concept_id === id); if (c) openDetail(c); }}
        >
          {id}
        </a>
      ),
    },
    { key: 'concept_name', title: t('concept.concept_name'), dataIndex: 'concept_name', ellipsis: true },
    { key: 'concept_code', title: 'Code', dataIndex: 'concept_code', width: 120 },
    { key: 'domain_id', title: t('concept.domain'), dataIndex: 'domain_id', width: 150, render: (v: string) => DOMAIN_NOMENCLATURE[v] ? `${t(`domains.${v}`, v)} (${DOMAIN_NOMENCLATURE[v]})` : t(`domains.${v}`, v) },
    { key: 'vocabulary_id', title: t('concept.vocabulary'), dataIndex: 'vocabulary_id', width: 120 },
    { key: 'concept_class_id', title: 'Class', dataIndex: 'concept_class_id', width: 120 },
    {
      key: 'standard_concept', title: 'Std', dataIndex: 'standard_concept', width: 60,
      render: (v: string | null) => v === 'S' ? <Tag color="green">S</Tag> : v === 'C' ? <Tag color="blue">C</Tag> : <Tag>-</Tag>,
    },
    {
      key: 'n_records', title: t('quality.n_records'), dataIndex: 'concept_id', width: 100,
      render: (id: number) => {
        const c = conceptCounts[id];
        return c ? c.n_records.toLocaleString() : countsLoading ? <Spinner className="h-4 w-4" /> : '—';
      },
    },
    {
      key: 'n_persons', title: t('quality.n_persons'), dataIndex: 'concept_id', width: 100,
      render: (id: number) => {
        const c = conceptCounts[id];
        return c ? c.n_persons.toLocaleString() : countsLoading ? <Spinner className="h-4 w-4" /> : '—';
      },
    },
  ];

  // On mobile, only show essential columns
  const columns = isMobile
    ? baseColumns.filter((c) => ['concept_id', 'concept_name', 'standard_concept'].includes(c.dataIndex as string))
    : baseColumns;

  const sourceColumns: Column<SourceValueSearchResult>[] = [
    {
      key: 'source_value', title: t('concept.source_value'), dataIndex: 'source_value', ellipsis: true,
      render: (_: string, r: SourceValueSearchResult) => {
        let label = r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value;
        if ((r as any).source_atc) label += ` [ATC: ${(r as any).source_atc}]`;
        return label;
      },
    },
    { key: 'domain', title: t('concept.domain'), dataIndex: 'domain', width: 150, render: (v: string) => DOMAIN_NOMENCLATURE[v] ? `${t(`domains.${v}`, v)} (${DOMAIN_NOMENCLATURE[v]})` : t(`domains.${v}`, v) },
    { key: 'n_records', title: t('quality.n_records'), dataIndex: 'n_records', width: 90, render: (v: number) => v?.toLocaleString() },
    ...(!isMobile ? [{
      key: 'n_persons', title: t('quality.n_persons'), dataIndex: 'n_persons', width: 90,
      render: (v: number) => v?.toLocaleString(),
    } as Column<SourceValueSearchResult>] : []),
    {
      key: 'mapped_concept_name', title: t('concept.mapped_concept'), dataIndex: 'mapped_concept_name', ellipsis: true,
      render: (name: string | null, r: SourceValueSearchResult) => {
        if (!r.mapped_concept_id || r.mapped_concept_id === 0) return <Tag>—</Tag>;
        return (
          <a
            className="text-emerald-accent hover:underline cursor-pointer"
            onClick={() => openDetail({
              concept_id: r.mapped_concept_id!,
              concept_name: r.mapped_concept_name || '',
              concept_code: '',
              domain_id: r.domain,
              vocabulary_id: r.mapped_vocabulary_id || '',
              concept_class_id: '',
              standard_concept: r.mapped_standard_concept,
            })}
          >
            <span className="text-xs opacity-70 mr-1">#{r.mapped_concept_id}</span>
            {name}
            {r.mapped_standard_concept === 'S' && <Tag color="green" className="ml-1">S</Tag>}
            {r.pending && (
              <Tooltip title={t('concept.pending_mapping_tooltip')}>
                <Tag color="orange" className="ml-1">
                  {t('concept.pending_mapping')}
                </Tag>
              </Tooltip>
            )}
          </a>
        );
      },
    },
  ];

  const relColumns: Column<RelationshipItem>[] = [
    { key: 'relationship_id', title: t('concept.relationship'), dataIndex: 'relationship_id', width: 140 },
    {
      key: 'related_concept_name', title: 'Concept', dataIndex: 'related_concept_name', ellipsis: true,
      render: (name: string, r: RelationshipItem) => (
        <a
          className="text-emerald-accent hover:underline cursor-pointer"
          onClick={() => {
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
          }}
        >
          {name}
        </a>
      ),
    },
    ...(!isMobile ? [
      { key: 'related_vocabulary_id', title: t('concept.vocabulary'), dataIndex: 'related_vocabulary_id', width: 100 } as Column<RelationshipItem>,
      {
        key: 'related_standard_concept', title: 'Std', dataIndex: 'related_standard_concept', width: 50,
        render: (v: string | null) => v === 'S' ? <Tag color="green">S</Tag> : v ? <Tag>{v}</Tag> : <span>-</span>,
      } as Column<RelationshipItem>,
    ] : []),
  ];

  const svColumns: Column<SourceValueItem>[] = [
    { key: 'domain', title: t('concept.domain'), dataIndex: 'domain', width: 150, render: (v: string) => DOMAIN_NOMENCLATURE[v] ? `${t(`domains.${v}`, v)} (${DOMAIN_NOMENCLATURE[v]})` : t(`domains.${v}`, v) },
    { key: 'source_value', title: t('concept.source_value'), dataIndex: 'source_value', ellipsis: true },
    { key: 'n_records', title: t('quality.n_records'), dataIndex: 'n_records', width: 90, render: (v: number) => v.toLocaleString() },
    { key: 'n_persons', title: t('quality.n_persons'), dataIndex: 'n_persons', width: 90, render: (v: number) => v.toLocaleString() },
  ];

  const detailTabItems: TabItem[] = selectedConcept ? [
    {
      key: 'info',
      label: t('concept.info'),
      children: (
        <div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-muted font-medium">Concept ID</dt>
            <dd className="text-text-bright font-mono">{selectedConcept.concept_id}</dd>
            <dt className="text-text-muted font-medium">{t('concept.concept_name')}</dt>
            <dd className="text-text-bright">{selectedConcept.concept_name}</dd>
            <dt className="text-text-muted font-medium">Code</dt>
            <dd className="text-text-bright font-mono">{selectedConcept.concept_code}</dd>
            <dt className="text-text-muted font-medium">{t('concept.domain')}</dt>
            <dd className="text-text-bright">{t(`domains.${selectedConcept.domain_id}`, selectedConcept.domain_id)}</dd>
            <dt className="text-text-muted font-medium">{t('concept.vocabulary')}</dt>
            <dd className="text-text-bright">{selectedConcept.vocabulary_id}</dd>
            <dt className="text-text-muted font-medium">Class</dt>
            <dd className="text-text-bright">{selectedConcept.concept_class_id}</dd>
            <dt className="text-text-muted font-medium">Standard</dt>
            <dd>
              {selectedConcept.standard_concept === 'S' ? <Tag color="green">Standard</Tag> :
               selectedConcept.standard_concept === 'C' ? <Tag color="blue">Classification</Tag> :
               <Tag>Non-standard</Tag>}
            </dd>
            <dt className="text-text-muted font-medium">Valid</dt>
            <dd className="text-text-bright">{selectedConcept.valid_start_date} — {selectedConcept.valid_end_date}</dd>
          </dl>
          {synonyms.length > 0 && (
            <div className="mt-3">
              <span className="block text-sm font-semibold text-text-bright mb-1">{t('concept.synonyms')}</span>
              <div className="flex flex-wrap gap-1">
                {synonyms.map((s, i) => <Tag key={i}>{s.concept_synonym_name}</Tag>)}
              </div>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'rels',
      label: (
        <span className="inline-flex items-center gap-1">
          <Link className="h-3.5 w-3.5" /> {t('concept.relationships')} ({relationships.length})
        </span>
      ),
      children: relationships.length === 0 ? (
        <Empty description={t('concept.no_relationships')} />
      ) : (
        <Table<RelationshipItem>
          dataSource={relationships}
          rowKey={(r: RelationshipItem, i?: number) => `${r.relationship_id}-${r.related_concept_id}-${i}`}
          columns={relColumns}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      ),
    },
    {
      key: 'hier',
      label: (
        <span className="inline-flex items-center gap-1">
          <GitBranch className="h-3.5 w-3.5" /> {t('concept.hierarchy')}
        </span>
      ),
      children: (
        <div>
          {ancestors.length > 0 && (
            <div className="mb-4">
              <span className="block text-sm font-semibold text-text-bright mb-1">{t('concept.ancestors')} ({ancestors.length})</span>
              <ul className="max-h-[200px] overflow-y-auto space-y-1">
                {ancestors.map((a, i) => (
                  <li key={`anc-${a.concept_id}-${i}`} className="flex items-center gap-2 py-1">
                    <Tag color="orange">L{a.min_levels_of_separation}</Tag>
                    <a
                      className="text-emerald-accent hover:underline cursor-pointer text-sm"
                      onClick={() => openDetail({ ...a, domain_id: '', concept_class_id: a.concept_class_id } as any)}
                    >
                      {a.concept_name}
                    </a>
                    <span className="text-text-dim text-xs">{a.vocabulary_id}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {descendants.length > 0 && (
            <div>
              <span className="block text-sm font-semibold text-text-bright mb-1">{t('concept.descendants')} ({descendants.length})</span>
              <ul className="max-h-[300px] overflow-y-auto space-y-1">
                {descendants.map((d, i) => (
                  <li key={`desc-${d.concept_id}-${i}`} className="flex items-center gap-2 py-1">
                    <Tag color="cyan">L{d.min_levels_of_separation}</Tag>
                    <a
                      className="text-emerald-accent hover:underline cursor-pointer text-sm"
                      onClick={() => openDetail({ ...d, domain_id: '', concept_class_id: d.concept_class_id } as any)}
                    >
                      {d.concept_name}
                    </a>
                    <span className="text-text-dim text-xs">{d.vocabulary_id}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {ancestors.length === 0 && descendants.length === 0 && (
            <Empty description={t('concept.no_hierarchy')} />
          )}
        </div>
      ),
    },
    {
      key: 'sv',
      label: (
        <span className="inline-flex items-center gap-1">
          <FileText className="h-3.5 w-3.5" /> {t('concept.source_values')} ({sourceValues.length})
        </span>
      ),
      children: sourceValues.length === 0 ? (
        <Empty description={t('concept.no_source_values')} />
      ) : (
        <Table<SourceValueItem>
          dataSource={sourceValues}
          rowKey={(r: SourceValueItem, i?: number) => `${r.domain}-${r.source_value}-${i}`}
          columns={svColumns}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      ),
    },
  ] : [];

  const detailContent = selectedConcept ? (
    detailLoading ? (
      <div className="text-center py-10">
        <Spinner size="large" />
        <p className="text-sm text-text-muted mt-4">{t('concept.loading_details', 'Loading concept details...')}</p>
      </div>
    ) : (
      <Tabs items={detailTabItems} />
    )
  ) : null;

  return (
    <div>
      <h3 className={`font-semibold text-text-bright mb-4 ${isMobile ? 'text-lg' : 'text-xl'}`}>
        {t('concept.title')} — {selectedCdm}
      </h3>

      <div className="flex flex-col lg:flex-row gap-4">
        {/* Search panel */}
        <div className={selectedConcept && !isMobile ? 'lg:w-[58%]' : 'w-full'}>
          <Card size="small" className="mb-4">
            {/* Search mode toggle */}
            <div className="flex mb-3">
              <button
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-l-lg border cursor-pointer transition-colors ${
                  searchMode === 'concept'
                    ? 'bg-emerald-accent/20 border-emerald-accent/40 text-emerald-accent'
                    : 'bg-surface-light border-glass-border text-text-muted hover:text-text-bright'
                }`}
                onClick={() => setSearchMode('concept')}
              >
                <Search className="h-3.5 w-3.5" /> {t('concept.by_concept')}
              </button>
              <button
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-r-lg border border-l-0 cursor-pointer transition-colors ${
                  searchMode === 'source'
                    ? 'bg-emerald-accent/20 border-emerald-accent/40 text-emerald-accent'
                    : 'bg-surface-light border-glass-border text-text-muted hover:text-text-bright'
                }`}
                onClick={() => setSearchMode('source')}
              >
                <Database className="h-3.5 w-3.5" /> {t('concept.by_source_code')}
              </button>
            </div>

            <div className="flex flex-wrap gap-3 items-center">
              <div className={isMobile ? 'w-full' : 'w-[280px]'}>
                <Input
                  placeholder={searchMode === 'concept' ? t('concept.search_placeholder') : t('concept.search_source_placeholder')}
                  prefix={<Search className="h-4 w-4" />}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(1); }}
                />
              </div>
              <div className={isMobile ? 'w-full' : 'w-[160px]'}>
                <Select
                  placeholder={t('concept.domain')}
                  value={domainFilter}
                  onChange={(v) => setDomainFilter(v || undefined)}
                  allowClear
                  options={domains.map((d) => ({ value: d.domain_id, label: DOMAIN_NOMENCLATURE[d.domain_id] ? `${t(`domains.${d.domain_id}`, d.domain_id)} (${DOMAIN_NOMENCLATURE[d.domain_id]})` : t(`domains.${d.domain_id}`, d.domain_id) }))}
                />
              </div>
              {searchMode === 'concept' && (
                <>
                  <div className={isMobile ? 'w-full' : 'w-[180px]'}>
                    <Select
                      placeholder={t('concept.vocabulary')}
                      value={vocabFilter}
                      onChange={(v) => setVocabFilter(v || undefined)}
                      allowClear
                      options={vocabs.map((v) => ({ value: v.vocabulary_id, label: v.vocabulary_id }))}
                    />
                  </div>
                  <Switch
                    checked={standardOnly}
                    onChange={setStandardOnly}
                    label={t('concept.standard_only')}
                  />
                </>
              )}
              {(loading || sourceLoading) ? (
                <Button variant="danger" icon={<StopCircle className="h-4 w-4" />} onClick={cancelSearch} block={isMobile}>
                  {t('common.cancel')}
                </Button>
              ) : (
                <Button variant="primary" icon={<Search className="h-4 w-4" />} onClick={() => handleSearch(1)} block={isMobile}>
                  {t('concept.search')}
                </Button>
              )}
              {searchMode === 'source' && sourceResults.length > 0 && (
                <Button
                  icon={<Download className="h-4 w-4" />}
                  onClick={() => {
                    const header = ['source_value', 'source_name', 'source_atc', 'domain', 'n_records', 'n_persons', 'mapped_concept_id', 'mapped_concept_name', 'mapped_vocabulary_id', 'mapped_standard_concept'];
                    const csvRows = [header.join(',')];
                    for (const r of sourceResults) {
                      csvRows.push([
                        r.source_value, r.source_name || '', (r as any).source_atc || '', r.domain,
                        r.n_records, r.n_persons, r.mapped_concept_id ?? '', r.mapped_concept_name || '',
                        r.mapped_vocabulary_id || '', r.mapped_standard_concept || '',
                      ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));
                    }
                    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = `source_value_search_${query}_${selectedCdm}.csv`;
                    a.click();
                    URL.revokeObjectURL(a.href);
                  }}
                >
                  CSV
                </Button>
              )}
            </div>
          </Card>

          {searchMode === 'concept' ? (
            <Table<ConceptItem>
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
                onChange: (p) => doSearch(p),
              }}
              onRow={(record) => ({
                onClick: () => openDetail(record),
                className: 'cursor-pointer',
              })}
            />
          ) : (
            <Table<SourceValueSearchResult>
              key={sourceSearchKey}
              dataSource={sourceResults}
              columns={sourceColumns}
              rowKey={(r: SourceValueSearchResult) => `${r.domain}-${r.source_value}-${r.mapped_concept_id}`}
              loading={sourceLoading}
              size="small"
              scroll={isMobile ? { x: 400 } : undefined}
              onRow={(r: SourceValueSearchResult) => ({
                className: r.pending ? 'bg-orange-500/8 hover:bg-orange-500/12' : '',
              })}
              pagination={{
                current: sourcePage,
                total: sourceTotal,
                pageSize: 50,
                onChange: (p) => doSourceSearch(p),
              }}
            />
          )}
        </div>

        {/* Detail panel -- desktop: inline side panel */}
        {selectedConcept && !isMobile && (
          <div className="lg:w-[42%]">
            <Card
              size="small"
              title={
                <div className="flex items-center gap-2">
                  <Tag color="blue">{selectedConcept.concept_id}</Tag>
                  <span className="font-semibold text-text-bright truncate">{selectedConcept.concept_name}</span>
                </div>
              }
              extra={
                <Button variant="text" size="small" onClick={() => setSelectedConcept(null)}>
                  {t('common.close')}
                </Button>
              }
            >
              {detailContent}
            </Card>
          </div>
        )}
      </div>

      {/* Detail panel -- mobile: drawer */}
      {isMobile && (
        <Drawer
          open={!!selectedConcept}
          onClose={() => setSelectedConcept(null)}
          title={
            selectedConcept ? (
              <div className="flex items-center gap-2">
                <Tag color="blue">{selectedConcept.concept_id}</Tag>
                <span className="font-semibold text-text-bright truncate">{selectedConcept.concept_name}</span>
              </div>
            ) : undefined
          }
          width="max-w-full"
        >
          {detailContent}
        </Drawer>
      )}
    </div>
  );
}
