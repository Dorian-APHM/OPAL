import { useState, useEffect } from 'react';
import { Search, Eye, Trash2, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { conceptSetApi, cohortApi } from '../api/client';
import type { ConceptSetSummary, ConceptSetDetail, OmopConcept } from '../types';
import {
  Card, Table, Button, Input, TextArea, Modal, Tag, Empty, Spinner,
} from '../components/ui';
import { useToast } from '../components/ui';
import type { Column } from '../components/ui';

export default function ConceptSetPage({ selectedCdm }: { selectedCdm: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [sets, setSets] = useState<ConceptSetSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<ConceptSetDetail | null>(null);

  // Form state (replacing antd Form)
  const [formName, setFormName] = useState('');
  const [formDomain, setFormDomain] = useState('');
  const [formDescription, setFormDescription] = useState('');

  // Concept search state for creation modal
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<OmopConcept[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);

  const resetForm = () => {
    setFormName('');
    setFormDomain('');
    setFormDescription('');
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
    if (!formName.trim()) {
      toast.error('Name is required');
      return;
    }
    try {
      await conceptSetApi.create({
        name: formName,
        cdm_name: selectedCdm,
        domain: formDomain || undefined,
        description: formDescription || '',
        concepts: selectedConcepts.map(c => ({
          concept_id: c.concept_id,
          concept_name: c.concept_name,
          concept_code: c.concept_code,
          vocabulary_id: c.vocabulary_id,
          include_descendants: true,
        })),
      });
      toast.success('Concept set created');
      setCreateOpen(false);
      setSelectedConcepts([]);
      setSearchQuery('');
      resetForm();
      load();
    } catch {
      toast.error('Failed to create concept set');
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this concept set?')) return;
    try {
      await conceptSetApi.delete(id);
      toast.success('Deleted');
      load();
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
    { key: 'domain', title: 'Domain', dataIndex: 'domain', render: (v: string) => v || '—' },
    { key: 'count', title: t('concept_sets.concepts', 'Concepts'), dataIndex: 'concept_count' },
    { key: 'created_by', title: 'Created by', dataIndex: 'created_by' },
    {
      key: 'actions', title: '', width: 100,
      render: (_: any, record: ConceptSetSummary) => (
        <div className="flex items-center gap-1">
          <Button size="small" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => openDetail(record.id)} />
          <Button size="small" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => handleDelete(record.id)} />
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
        onClose={() => { setCreateOpen(false); setSelectedConcepts([]); setSearchQuery(''); resetForm(); }}
        width="max-w-2xl"
        footer={
          <>
            <Button onClick={() => { setCreateOpen(false); setSelectedConcepts([]); setSearchQuery(''); resetForm(); }}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleCreate} disabled={selectedConcepts.length === 0}>
              Create
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
            <label className="block text-xs font-medium text-text-muted mb-1">Domain</label>
            <Input value={formDomain} onChange={(e) => setFormDomain(e.target.value)} placeholder="e.g. Condition, Drug (optional)" />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">{t('concept_sets.description', 'Description')}</label>
            <TextArea value={formDescription} onChange={(e) => setFormDescription(e.target.value)} rows={2} />
          </div>
        </div>

        <div className="mb-2">
          <Input
            prefix={<Search className="h-4 w-4" />}
            placeholder="Search concepts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {selectedConcepts.length > 0 && (
          <div className="mb-2 p-2 bg-emerald-accent/5 border border-emerald-accent/20 rounded-lg">
            <div className="flex flex-wrap gap-1">
              {selectedConcepts.map(c => (
                <Tag key={c.concept_id} closable onClose={() => toggleConcept(c)} color="blue">
                  {c.concept_name}
                </Tag>
              ))}
            </div>
          </div>
        )}

        {searchLoading ? (
          <Spinner size="small" />
        ) : (
          <div className="max-h-[250px] overflow-auto">
            {searchResults.map(c => (
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
            <div className="max-h-[400px] overflow-auto">
              <Table
                dataSource={detail.concepts}
                columns={detailColumns}
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
