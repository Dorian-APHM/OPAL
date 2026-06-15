import { useState, useEffect } from 'react';
import { Search, Eye, Trash2, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { conceptSetApi, cohortApi, conceptApi } from '../api/client';
import type { ConceptSetSummary, ConceptSetDetail, OmopConcept } from '../types';
import {
  Card, Table, Button, Input, Select, TextArea, Modal, Tag, Empty, Spinner, Confirm,
} from '../components/ui';
import { useToast } from '../components/ui';
import type { Column } from '../components/ui';

const DOMAIN_NOMENCLATURE: Record<string, string> = {
  Condition: 'CIM-10',
  Procedure: 'CCAM',
  Drug: 'ATC / UCD',
};

export default function ConceptSetPage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [sets, setSets] = useState<ConceptSetSummary[]>([]);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<ConceptSetDetail | null>(null);

  // Form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');

  // Search mode: 'source' or 'concept'
  const [searchMode, setSearchMode] = useState<'source' | 'concept'>('source');

  // Domain list
  const [domains, setDomains] = useState<{ name: string; table: string }[]>([]);
  const [searchDomain, setSearchDomain] = useState<string>('Condition');

  // Concept search state (OMOP)
  const [conceptQuery, setConceptQuery] = useState('');
  const [conceptResults, setConceptResults] = useState<OmopConcept[]>([]);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [standardOnly, setStandardOnly] = useState(false);

  // Source code search state
  const [sourceQuery, setSourceQuery] = useState('');
  const [sourceResults, setSourceResults] = useState<any[]>([]);
  const [sourceLoading, setSourceLoading] = useState(false);

  // Selected concepts for creation (OMOP mode)
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);
  // Selected source codes for creation (source mode)
  const [selectedSourceCodes, setSelectedSourceCodes] = useState<{ source_value: string; source_name: string; domain: string }[]>([]);

  const resetForm = () => {
    setFormName('');
    setFormDescription('');
    setConceptQuery('');
    setConceptResults([]);
    setSourceQuery('');
    setSourceResults([]);
    setSelectedConcepts([]);
    setSelectedSourceCodes([]);
  };

  const load = () => {
    if (!selectedCdm) return;
    setLoading(true);
    conceptSetApi.list(selectedCdm)
      .then(r => setSets(r.data.concept_sets))
      .catch(() => toast.error('Failed to load concept sets'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [selectedCdm]);

  // Load domains
  useEffect(() => {
    cohortApi.listDomains().then(r => setDomains(r.data.domains));
  }, [selectedCdm]);

  const domainOptions = domains.map(d => ({
    value: d.name,
    label: DOMAIN_NOMENCLATURE[d.name] ? `${t(`domains.${d.name}`, d.name)} (${DOMAIN_NOMENCLATURE[d.name]})` : t(`domains.${d.name}`, d.name),
  }));

  // Concept search (OMOP vocabulary)
  useEffect(() => {
    if (searchMode !== 'concept' || !conceptQuery || conceptQuery.length < 2 || !selectedCdm) {
      setConceptResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setConceptLoading(true);
      cohortApi.searchConcepts(selectedCdm, conceptQuery, searchDomain, undefined, standardOnly)
        .then(r => setConceptResults(r.data.concepts))
        .catch(() => setConceptResults([]))
        .finally(() => setConceptLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [conceptQuery, searchDomain, standardOnly, selectedCdm, searchMode]);

  // Source code search (cache / CDM)
  useEffect(() => {
    if (searchMode !== 'source' || !sourceQuery || sourceQuery.length < 2 || !selectedCdm) {
      setSourceResults([]);
      return;
    }
    const abort = new AbortController();
    const timer = setTimeout(() => {
      setSourceLoading(true);
      conceptApi.searchSourceValue(selectedCdm, { q: sourceQuery, domain: searchDomain, limit: 30 })
        .then(r => { if (!abort.signal.aborted) setSourceResults(r.data.results); })
        .catch((err: any) => {
          if (abort.signal.aborted) return;
          setSourceResults([]);
          if (err?.response?.status === 409 && err?.response?.data?.detail?.code === 'source_value_cache_missing') {
            toast.error(err.response.data.detail.message
              || t('concepts.cache_missing', 'Source value cache not built for this CDM yet. Build it from Data Management.'));
          }
        })
        .finally(() => { if (!abort.signal.aborted) setSourceLoading(false); });
    }, 300);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [sourceQuery, searchDomain, selectedCdm, searchMode]);

  const toggleConcept = (c: OmopConcept) => {
    setSelectedConcepts(prev =>
      prev.some(x => x.concept_id === c.concept_id)
        ? prev.filter(x => x.concept_id !== c.concept_id)
        : [...prev, c]
    );
  };

  const toggleSourceResult = (r: any) => {
    setSelectedSourceCodes(prev => {
      const exists = prev.some(s => s.source_value === r.source_value);
      if (exists) return prev.filter(s => s.source_value !== r.source_value);
      return [...prev, {
        source_value: r.source_value,
        source_name: r.source_name || '',
        domain: r.domain,
      }];
    });
  };

  const handleCreate = async () => {
    if (!selectedCdm) return;
    if (!formName.trim()) {
      toast.error('Name is required');
      return;
    }
    try {
      const concepts = selectedConcepts.map(c => ({
        concept_id: c.concept_id,
        concept_name: c.concept_name,
        concept_code: c.concept_code,
        vocabulary_id: c.vocabulary_id,
        include_descendants: true,
      }));
      const source_codes = selectedSourceCodes.map(s => ({
        source_value: s.source_value,
        source_name: s.source_name,
        domain: s.domain,
      }));
      await conceptSetApi.create({
        name: formName,
        cdm_name: selectedCdm,
        domain: searchDomain || undefined,
        description: formDescription || '',
        concepts,
        source_codes,
      });
      toast.success('Concept set created');
      setCreateOpen(false);
      resetForm();
      load();
      window.dispatchEvent(new Event('opal:concept-sets-changed'));
    } catch {
      toast.error('Failed to create concept set');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await conceptSetApi.delete(id);
      toast.success('Deleted');
      load();
      window.dispatchEvent(new Event('opal:concept-sets-changed'));
    } catch {
      toast.error('Failed to delete');
    }
  };

  const openDetail = async (id: number) => {
    const r = await conceptSetApi.get(id);
    setDetail(r.data);
    setDetailOpen(true);
  };

  if (!selectedCdm) {
    return <Card><Empty description="Select a CDM first" /></Card>;
  }

  const columns: Column<ConceptSetSummary>[] = [
    { key: 'name', title: t('concept_sets.name', 'Name'), dataIndex: 'name' },
    { key: 'description', title: t('concept_sets.description', 'Description'), dataIndex: 'description', ellipsis: true, render: (v: string) => v || '—' },
    { key: 'domain', title: 'Domain', dataIndex: 'domain', render: (v: string) => v || '—' },
    { key: 'count', title: t('concept_sets.concepts', 'Concepts'), dataIndex: 'concept_count' },
    { key: 'created_by', title: 'Created by', dataIndex: 'created_by' },
    {
      key: 'actions', title: '', width: 100,
      render: (_: any, record: ConceptSetSummary) => (
        <div className="flex items-center gap-1">
          <Button size="small" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => openDetail(record.id)} />
          <Button size="small" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDeleteId(record.id)} />
        </div>
      ),
    },
  ];

  const detailColumns: Column<any>[] = [
    { key: 'concept_id', title: 'ID', dataIndex: 'concept_id', width: 80 },
    { key: 'concept_name', title: 'Name', dataIndex: 'concept_name' },
    { key: 'concept_code', title: 'Code', dataIndex: 'concept_code', width: 100 },
    { key: 'vocabulary_id', title: 'Vocabulary', dataIndex: 'vocabulary_id', width: 100 },
  ];

  return (
    <div className="max-w-[1000px] mx-auto">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-lg font-semibold text-text-bright">{t('concept_sets.title', 'Concept Sets')}</h4>
        <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>
          {t('concept_sets.create', 'Create')}
        </Button>
      </div>

      <Table<ConceptSetSummary>
        dataSource={sets}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
        emptyText={t('concept_sets.no_sets', 'No concept sets yet')}
      />

      {/* Create Modal */}
      <Modal
        title={t('concept_sets.create', 'Create Concept Set')}
        open={createOpen}
        onClose={() => { setCreateOpen(false); resetForm(); }}
        width="max-w-2xl"
        footer={
          <>
            <Button onClick={() => { setCreateOpen(false); resetForm(); }}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleCreate} disabled={selectedConcepts.length === 0 && selectedSourceCodes.length === 0}>
              Create ({selectedConcepts.length + selectedSourceCodes.length})
            </Button>
          </>
        }
      >
        <div className="space-y-3 mb-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">{t('concept_sets.name', 'Name')} <span className="text-red-400">*</span></label>
            <Input value={formName} onChange={(e) => setFormName(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">{t('concept_sets.description', 'Description')}</label>
            <TextArea value={formDescription} onChange={(e) => setFormDescription(e.target.value)} rows={2} />
          </div>
        </div>

        {/* Domain selector */}
        <div className="flex items-center gap-2 mb-3">
          <Select
            size="small"
            value={searchDomain}
            onChange={v => setSearchDomain(v)}
            options={domainOptions}
            className="w-[180px]"
          />
          {/* Search mode toggle */}
          <div className="flex rounded-lg border border-glass-border overflow-hidden">
            <button
              type="button"
              onClick={() => setSearchMode('source')}
              className={`px-3 py-1.5 text-xs transition-all ${
                searchMode === 'source'
                  ? 'bg-emerald-accent/20 text-emerald-accent font-medium'
                  : 'bg-deep-base text-text-dim hover:text-text-muted'
              }`}
            >
              Source Code
            </button>
            <button
              type="button"
              onClick={() => setSearchMode('concept')}
              className={`px-3 py-1.5 text-xs transition-all ${
                searchMode === 'concept'
                  ? 'bg-emerald-accent/20 text-emerald-accent font-medium'
                  : 'bg-deep-base text-text-dim hover:text-text-muted'
              }`}
            >
              Concept OMOP
            </button>
          </div>
          {searchMode === 'concept' && (
            <button
              type="button"
              onClick={() => setStandardOnly(prev => !prev)}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-all duration-200 whitespace-nowrap ${
                standardOnly
                  ? 'bg-emerald-accent/20 border-emerald-accent/40 text-emerald-accent font-medium'
                  : 'bg-deep-base border-glass-border text-text-dim hover:text-text-muted'
              }`}
            >
              Standard
            </button>
          )}
        </div>

        {/* Search input */}
        <div className="mb-2">
          {searchMode === 'source' ? (
            <Input
              prefix={<Search className="h-4 w-4" />}
              placeholder={`Search by source code in ${searchDomain}...`}
              value={sourceQuery}
              onChange={(e) => setSourceQuery(e.target.value)}
            />
          ) : (
            <Input
              prefix={<Search className="h-4 w-4" />}
              placeholder="Search concepts by name or code..."
              value={conceptQuery}
              onChange={(e) => setConceptQuery(e.target.value)}
            />
          )}
        </div>

        {/* Selected items */}
        {(selectedConcepts.length > 0 || selectedSourceCodes.length > 0) && (
          <div className="mb-2 p-2 bg-emerald-accent/5 border border-emerald-accent/20 rounded-lg">
            <div className="flex flex-wrap gap-1">
              {selectedSourceCodes.map(s => (
                <Tag key={s.source_value} closable onClose={() => toggleSourceResult(s)} color="green">
                  {s.source_name ? `${s.source_value} — ${s.source_name}` : s.source_value}
                </Tag>
              ))}
              {selectedConcepts.map(c => (
                <Tag key={c.concept_id} closable onClose={() => toggleConcept(c)} color="blue">
                  {c.concept_name} ({c.concept_id})
                </Tag>
              ))}
            </div>
          </div>
        )}

        {/* Search results */}
        {searchMode === 'source' ? (
          // Source code results
          sourceLoading ? (
            <Spinner size="small" />
          ) : sourceResults.length > 0 ? (
            <div className="max-h-[250px] overflow-auto">
              {sourceResults.map((r, i) => {
                const isSelected = selectedSourceCodes.some(s => s.source_value === r.source_value);
                return (
                <div
                  key={`${r.source_value}-${r.domain}-${i}`}
                  className={`px-2 py-1.5 cursor-pointer border-b border-glass-border transition-colors ${isSelected ? 'bg-emerald-accent/10' : 'hover:bg-emerald-accent/5'}`}
                  onClick={() => toggleSourceResult(r)}
                >
                  <div className="flex justify-between">
                    <span className="text-xs font-semibold text-text-bright">
                      {r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value}
                      {r.source_atc ? <span className="text-blue-400 ml-1">[{r.source_atc}]</span> : null}
                    </span>
                    <span className="text-text-dim text-[10px]">{r.n_records?.toLocaleString()} rec</span>
                  </div>
                  <div className="text-[11px] text-text-dim">
                    {t(`domains.${r.domain}`, r.domain)}
                    {DOMAIN_NOMENCLATURE[r.domain] ? ` (${DOMAIN_NOMENCLATURE[r.domain]})` : ''}
                    {' · '}{r.n_persons?.toLocaleString()} pers
                    {r.mapped_concept_name && <span className="text-emerald-accent ml-1">→ {r.mapped_concept_name}</span>}
                  </div>
                </div>
                );
              })}
            </div>
          ) : sourceQuery.length >= 2 ? (
            <Empty description="No source codes found" className="!py-2" />
          ) : null
        ) : (
          // Concept OMOP results
          conceptLoading ? (
            <Spinner size="small" />
          ) : (
            <div className="max-h-[250px] overflow-auto">
              {conceptResults.map(c => (
                <div
                  key={c.concept_id}
                  className={`px-2 py-1 cursor-pointer border-b border-glass-border transition-colors ${
                    selectedConcepts.some(s => s.concept_id === c.concept_id)
                      ? 'bg-emerald-accent/10'
                      : 'hover:bg-surface-light'
                  }`}
                  onClick={() => toggleConcept(c)}
                >
                  <span className="font-semibold text-text-bright text-xs">{c.concept_name}</span>
                  <span className="text-text-dim text-[11px] ml-2">
                    {c.concept_code} · {c.vocabulary_id} · {c.domain_id}
                  </span>
                  {c.standard_concept === 'S' && <Tag color="green" className="ml-1 text-[10px]">S</Tag>}
                </div>
              ))}
            </div>
          )
        )}
      </Modal>

      {/* Detail Modal */}
      <Modal
        title={detail?.name || 'Concept Set'}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width="max-w-xl"
      >
        {detail && (
          <>
            <p className="text-sm text-text-muted mb-3">{detail.description}</p>
            {detail.source_codes && detail.source_codes.length > 0 && (
              <div className="mb-3">
                <h5 className="text-xs font-semibold text-text-muted mb-1">Source Codes ({detail.source_codes.length})</h5>
                <div className="max-h-[200px] overflow-auto">
                  <Table
                    dataSource={detail.source_codes}
                    columns={[
                      { key: 'source_value', title: 'Code', dataIndex: 'source_value', width: 150 },
                      { key: 'source_name', title: 'Name', dataIndex: 'source_name', render: (v: string) => v || '—' },
                      { key: 'domain', title: 'Domain', dataIndex: 'domain', width: 120 },
                    ] as Column<any>[]}
                    rowKey="source_value"
                    size="small"
                    pagination={false}
                  />
                </div>
              </div>
            )}
            {detail.concepts && detail.concepts.length > 0 && (
              <div>
                <h5 className="text-xs font-semibold text-text-muted mb-1">Concepts ({detail.concepts.length})</h5>
                <div className="max-h-[200px] overflow-auto">
                  <Table
                    dataSource={detail.concepts}
                    columns={detailColumns}
                    rowKey="concept_id"
                    size="small"
                    pagination={false}
                  />
                </div>
              </div>
            )}
          </>
        )}
      </Modal>

      <Confirm
        open={deleteId !== null}
        onClose={() => setDeleteId(null)}
        onConfirm={() => { if (deleteId !== null) handleDelete(deleteId); }}
        title="Delete concept set"
        description="Delete this concept set?"
        confirmText="Delete"
        danger
      />
    </div>
  );
}
