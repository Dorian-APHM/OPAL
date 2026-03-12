import { useState, useEffect } from 'react';
import { Card, Input, Select, Tag, Empty, Spinner } from '../../components/ui';
import { Search, Plus, Layers } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cohortApi, conceptApi, conceptSetApi } from '../../api/client';
import type { OmopConcept, CohortCriterion, ConceptSetSummary, ConceptSetDetail } from '../../types';

interface Props {
  cdmName: string;
  onAddCriterion: (criterion: CohortCriterion) => void;
}

export default function CriteriaPanel({ cdmName, onAddCriterion }: Props) {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDomain, setSearchDomain] = useState<string | undefined>();
  const [standardOnly, setStandardOnly] = useState(false);
  const [concepts, setConcepts] = useState<OmopConcept[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);
  const [domains, setDomains] = useState<{ name: string; table: string }[]>([]);

  useEffect(() => {
    cohortApi.listDomains().then(r => setDomains(r.data.domains));
  }, [cdmName]);

  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2 || !cdmName) {
      setConcepts([]);
      return;
    }
    const timer = setTimeout(() => {
      setLoading(true);
      cohortApi.searchConcepts(cdmName, searchQuery, searchDomain, undefined, standardOnly)
        .then(r => setConcepts(r.data.concepts))
        .catch(() => setConcepts([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchDomain, standardOnly, cdmName]);

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

  // -- Concept Sets integration --
  const [conceptSets, setConceptSets] = useState<ConceptSetSummary[]>([]);
  const [conceptSetsLoading, setConceptSetsLoading] = useState(false);

  useEffect(() => {
    if (!cdmName) return;
    setConceptSetsLoading(true);
    conceptSetApi.list(cdmName)
      .then(r => setConceptSets(r.data.concept_sets || []))
      .catch(() => setConceptSets([]))
      .finally(() => setConceptSetsLoading(false));
  }, [cdmName]);

  const addConceptSetAsCriterion = async (cs: ConceptSetSummary) => {
    try {
      const resp = await conceptSetApi.get(cs.id);
      const detail: ConceptSetDetail = resp.data;
      if (!detail.concepts || detail.concepts.length === 0) return;
      const concepts: OmopConcept[] = detail.concepts.map(c => ({
        concept_id: c.concept_id,
        concept_name: c.concept_name,
        concept_code: c.concept_code,
        domain_id: cs.domain || detail.concepts[0]?.vocabulary_id || '',
        vocabulary_id: c.vocabulary_id,
        concept_class_id: '',
        standard_concept: null,
      }));
      const criterion: CohortCriterion = {
        id: Math.random().toString(36).slice(2) + Date.now().toString(36),
        domain: cs.domain || concepts[0]?.domain_id || 'Condition',
        concepts,
        include_descendants: detail.concepts.some(c => c.include_descendants),
        source_codes: [],
        temporal: { type: 'any_time' },
        occurrence: { type: 'any', count: 1 },
      };
      onAddCriterion(criterion);
    } catch {
      // ignore
    }
  };

  // Map domains to their source nomenclature names
  const DOMAIN_NOMENCLATURE: Record<string, string> = {
    Condition: 'CIM-10',
    Procedure: 'CCAM',
    Drug: 'ATC / UCD',
    Measurement: 'NABM / LOINC',
    Observation: 'Source',
    Device: 'LPP',
  };
  const domainOptions = domains.map(d => ({
    value: d.name,
    label: DOMAIN_NOMENCLATURE[d.name] ? `${t(`domains.${d.name}`, d.name)} (${DOMAIN_NOMENCLATURE[d.name]})` : t(`domains.${d.name}`, d.name),
  }));

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Concept Sets */}
      {conceptSets.length > 0 && (
        <Card
          size="small"
          title={<span className="flex items-center gap-1"><Layers className="h-4 w-4" /> {t('cohort.concept_sets', 'Concept Sets')}</span>}
        >
          {conceptSetsLoading ? (
            <div className="text-center p-3"><Spinner size="small" /></div>
          ) : (
            <div className="max-h-[180px] overflow-auto">
              {conceptSets.map(cs => (
                <div
                  key={cs.id}
                  className="cursor-pointer px-3 py-1.5 hover:bg-emerald-accent/5 border-b border-border-subtle last:border-b-0 transition-colors"
                  onClick={() => addConceptSetAsCriterion(cs)}
                >
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-1">
                      <Plus className="h-2.5 w-2.5 text-emerald-400" />
                      <span className="text-xs font-semibold text-text-bright">{cs.name}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      {cs.domain && <Tag className="text-[10px]">{t(`domains.${cs.domain}`, cs.domain)}</Tag>}
                      <Tag color="blue" className="text-[10px]">{cs.concept_count} concepts</Tag>
                    </div>
                  </div>
                  {cs.description && (
                    <div className="text-[11px] text-text-dim mt-0.5">{cs.description}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Source code input */}
      <Card size="small" title={t('cohort.source_code_search', 'Source Code')}>
        <div className="flex flex-col gap-1 w-full">
          <Select
            size="small"
            value={sourceCodeDomain}
            onChange={v => setSourceCodeDomain(v)}
            options={domainOptions}
          />
          <Input
            prefix={<Search className="h-3.5 w-3.5" />}
            placeholder={t('cohort.search_source_placeholder', 'Search by keyword...')}
            value={sourceSearchQuery}
            onChange={e => setSourceSearchQuery(e.target.value)}
          />
          {/* Selected source codes */}
          {selectedSourceCodes.length > 0 && (
            <div className="p-1 bg-surface-dark rounded">
              <div className="flex flex-wrap gap-1">
                {selectedSourceCodes.map(code => (
                  <Tag key={code} closable onClose={() => toggleSourceCode(code)} color="blue">{code}</Tag>
                ))}
                <Tag color="green" className="cursor-pointer" style={{ cursor: 'pointer' }}>
                  <span onClick={addSelectedSourceCodes} className="flex items-center gap-0.5">
                    <Plus className="h-2.5 w-2.5" /> {t('cohort.add_criterion', 'Add as criterion')}
                  </span>
                </Tag>
              </div>
            </div>
          )}

          {/* Source search results */}
          {sourceSearchLoading ? (
            <div className="text-center p-2"><Spinner size="small" /></div>
          ) : sourceSearchResults.length > 0 ? (
            <div className="max-h-[200px] overflow-auto">
              {sourceSearchResults.map(r => {
                const isSelected = selectedSourceCodes.includes(r.source_value);
                return (
                  <div
                    key={r.source_value}
                    className={`cursor-pointer px-2 py-1 border-b border-border-subtle last:border-b-0 transition-colors ${isSelected ? 'bg-blue-500/10' : 'hover:bg-emerald-accent/5'}`}
                    onClick={() => toggleSourceCode(r.source_value)}
                  >
                    <div className="flex justify-between">
                      <span className="text-xs font-semibold text-text-bright">{r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value}</span>
                      <span className="text-text-dim text-[10px]">{r.n_records.toLocaleString()} rec</span>
                    </div>
                    <div className="text-[11px] text-text-dim">{t(`domains.${r.domain}`, r.domain)}{DOMAIN_NOMENCLATURE[r.domain] ? ` (${DOMAIN_NOMENCLATURE[r.domain]})` : ''} · {r.n_persons.toLocaleString()} pers</div>
                  </div>
                );
              })}
            </div>
          ) : sourceSearchQuery.length >= 2 ? (
            <Empty description={t('cohort.no_source_codes', 'No source codes found')} className="!py-2" />
          ) : null}
        </div>
      </Card>

      {/* Concept search */}
      <Card size="small" title={t('cohort.concept_search', 'Concept Search (OMOP)')} className="flex-1 overflow-hidden flex flex-col">
        <Input
          prefix={<Search className="h-3.5 w-3.5" />}
          placeholder={t('cohort.search_placeholder', 'Search by name or code...')}
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="mb-2"
        />
        <div className="flex items-center gap-1 mb-2">
          <Select
            size="small"
            placeholder={t('cohort.domain', 'Domain')}
            value={searchDomain || ''}
            onChange={v => setSearchDomain(v || undefined)}
            allowClear
            className="flex-1 min-w-0"
            options={domainOptions}
          />
          <button
            type="button"
            onClick={() => setStandardOnly(prev => !prev)}
            className={`px-2.5 py-1.5 text-xs rounded-lg border transition-all duration-200 whitespace-nowrap ${
              standardOnly
                ? 'bg-emerald-accent/20 border-emerald-accent/40 text-emerald-accent font-medium'
                : 'bg-deep-base border-glass-border text-text-dim hover:text-text-muted hover:border-glass-border/60'
            }`}
          >
            Standard
          </button>
        </div>

        {/* Selected concepts */}
        {selectedConcepts.length > 0 && (
          <div className="mb-2 p-1 bg-surface-dark rounded">
            <div className="flex flex-wrap gap-1">
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
                className="cursor-pointer"
                style={{ cursor: 'pointer' }}
              >
                <span onClick={() => addAsCriterion()} className="flex items-center gap-0.5">
                  <Plus className="h-2.5 w-2.5" /> {t('cohort.add_criterion', 'Add as criterion')}
                </span>
              </Tag>
            </div>
          </div>
        )}

        {/* Search results */}
        <div className="max-h-[300px] overflow-auto">
          {loading ? (
            <div className="text-center p-4"><Spinner size="small" /></div>
          ) : concepts.length > 0 ? (
            concepts.map(c => {
              const isSelected = selectedConcepts.some(s => s.concept_id === c.concept_id);
              return (
                <div
                  key={c.concept_id}
                  className={`cursor-pointer px-2 py-1 border-b border-border-subtle last:border-b-0 transition-colors ${isSelected ? 'bg-blue-500/10' : 'hover:bg-emerald-accent/5'}`}
                  onClick={() => toggleConcept(c)}
                >
                  <div className="flex justify-between">
                    <span className="text-xs font-semibold text-text-bright">{c.concept_name}</span>
                    {c.standard_concept === 'S' && <Tag color="green" className="text-[10px]">S</Tag>}
                  </div>
                  <div className="text-[11px] text-text-dim">
                    {c.concept_code} · {c.vocabulary_id} · {t(`domains.${c.domain_id}`, c.domain_id)}{DOMAIN_NOMENCLATURE[c.domain_id] ? ` (${DOMAIN_NOMENCLATURE[c.domain_id]})` : ''}
                  </div>
                </div>
              );
            })
          ) : searchQuery.length >= 2 ? (
            <Empty description={t('cohort.no_concepts', 'No concepts found')} />
          ) : null}
        </div>
      </Card>
    </div>
  );
}
