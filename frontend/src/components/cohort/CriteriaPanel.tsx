import { useState, useEffect } from 'react';
import {
  useFloating, autoUpdate, offset, flip, shift, size,
  useDismiss, useInteractions, FloatingPortal,
} from '@floating-ui/react';
import { Card, Input, Select, Tag, Empty, Spinner } from '../../components/ui';
import { Search, Plus, Layers } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cohortApi, conceptApi, conceptSetApi } from '../../api/client';
import type { OmopConcept, CohortCriterion, ConceptSetSummary } from '../../types';

interface Props {
  cdmName: string;
  onAddCriterion: (criterion: CohortCriterion) => void;
}

// A floating, portalled result list anchored to a search input: flips up near the
// viewport bottom, caps its height to the available space (scrolls internally), and
// closes on outside click / Escape. Lets the cramped left panel host full result lists.
function useResultsDropdown(open: boolean, onOpenChange: (v: boolean) => void) {
  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange,
    placement: 'bottom-start',
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(4),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
      size({
        padding: 8,
        apply({ availableHeight, rects, elements }) {
          Object.assign(elements.floating.style, {
            maxHeight: `${Math.max(140, Math.min(availableHeight, 360))}px`,
            minWidth: `${rects.reference.width}px`,
          });
        },
      }),
    ],
  });
  const dismiss = useDismiss(context);
  const { getReferenceProps, getFloatingProps } = useInteractions([dismiss]);
  return { refs, floatingStyles, getReferenceProps, getFloatingProps };
}

const RESULTS_PANEL_CLASS =
  'z-[9999] overflow-auto rounded-xl bg-surface border border-glass-border shadow-[0_8px_32px_rgba(0,0,0,0.4)]';

export default function CriteriaPanel({ cdmName, onAddCriterion }: Props) {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDomain, setSearchDomain] = useState<string | undefined>();
  const [standardOnly, setStandardOnly] = useState(false);
  const [concepts, setConcepts] = useState<OmopConcept[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);
  const [domains, setDomains] = useState<{ name: string; table: string }[]>([]);

  // Inline result lists behave like dropdowns: open while searching, close on outside click.
  const [conceptResultsOpen, setConceptResultsOpen] = useState(false);
  const [sourceResultsOpen, setSourceResultsOpen] = useState(false);
  const conceptDd = useResultsDropdown(conceptResultsOpen, setConceptResultsOpen);
  const sourceDd = useResultsDropdown(sourceResultsOpen, setSourceResultsOpen);

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
    const abort = new AbortController();
    const timer = setTimeout(() => {
      setSourceSearchLoading(true);
      conceptApi.searchSourceValue(cdmName, { q: sourceSearchQuery, domain: sourceCodeDomain, limit: 20 })
        .then(r => { if (!abort.signal.aborted) setSourceSearchResults(r.data.results); })
        .catch(() => { if (!abort.signal.aborted) setSourceSearchResults([]); })
        .finally(() => { if (!abort.signal.aborted) setSourceSearchLoading(false); });
    }, 300);
    return () => { clearTimeout(timer); abort.abort(); };
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

  const loadConceptSets = () => {
    if (!cdmName) return;
    setConceptSetsLoading(true);
    conceptSetApi.list(cdmName)
      .then(r => setConceptSets(r.data.concept_sets || []))
      .catch(() => setConceptSets([]))
      .finally(() => setConceptSetsLoading(false));
  };

  useEffect(() => { loadConceptSets(); }, [cdmName]);

  // Reload when concept sets change or tab becomes visible
  useEffect(() => {
    const handler = () => loadConceptSets();
    window.addEventListener('focus', handler);
    window.addEventListener('opal:concept-sets-changed', handler);
    return () => {
      window.removeEventListener('focus', handler);
      window.removeEventListener('opal:concept-sets-changed', handler);
    };
  }, [cdmName]);

  const addConceptSetAsCriterion = async (cs: ConceptSetSummary) => {
    try {
      const resp = await conceptSetApi.get(cs.id);
      const detail = resp.data;
      const sourceCodes: string[] = (detail.source_codes || []).map((s: any) => s.source_value);
      const concepts: OmopConcept[] = (detail.concepts || []).map((c: any) => ({
        concept_id: c.concept_id,
        concept_name: c.concept_name,
        concept_code: c.concept_code,
        domain_id: cs.domain || '',
        vocabulary_id: c.vocabulary_id,
        concept_class_id: '',
        standard_concept: null,
      }));

      if (sourceCodes.length > 0) {
        // Source code based criterion
        const domain = detail.source_codes?.[0]?.domain || cs.domain || 'Condition';
        const criterion: CohortCriterion = {
          id: Math.random().toString(36).slice(2) + Date.now().toString(36),
          domain,
          concepts: [],
          include_descendants: false,
          source_codes: sourceCodes,
          temporal: { type: 'any_time' },
          occurrence: { type: 'any', count: 1 },
        };
        onAddCriterion(criterion);
      }
      if (concepts.length > 0) {
        // Concept based criterion
        const criterion: CohortCriterion = {
          id: Math.random().toString(36).slice(2) + Date.now().toString(36),
          domain: cs.domain || concepts[0]?.domain_id || 'Condition',
          concepts,
          include_descendants: detail.concepts.some((c: any) => c.include_descendants),
          source_codes: [],
          temporal: { type: 'any_time' },
          occurrence: { type: 'any', count: 1 },
        };
        onAddCriterion(criterion);
      }
    } catch {
      // ignore
    }
  };

  // Map domains to their source nomenclature names
  const DOMAIN_NOMENCLATURE: Record<string, string> = {
    Condition: 'CIM-10',
    Procedure: 'CCAM',
    Drug: 'ATC / UCD',
  };
  const domainOptions = domains.map(d => ({
    value: d.name,
    label: DOMAIN_NOMENCLATURE[d.name] ? `${t(`domains.${d.name}`, d.name)} (${DOMAIN_NOMENCLATURE[d.name]})` : t(`domains.${d.name}`, d.name),
  }));

  return (
    <div className="flex flex-col gap-2">
      {/* Concept Sets */}
        <Card
          size="small"
          title={<span className="flex items-center gap-1"><Layers className="h-4 w-4" /> {t('cohort.concept_sets', 'Concept Sets')}</span>}
        >
          {conceptSetsLoading ? (
            <div className="text-center p-2"><Spinner size="small" /></div>
          ) : (
            <div className="max-h-[140px] overflow-auto">
              {conceptSets.map(cs => (
                <div
                  key={cs.id}
                  className="cursor-pointer px-2 py-1 hover:bg-emerald-accent/5 border-b border-border-subtle last:border-b-0 transition-colors"
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
          {!conceptSetsLoading && conceptSets.length === 0 && (
            <Empty description={t('concept_sets.no_sets', 'No concept sets yet')} className="!py-2" />
          )}
        </Card>

      {/* Source code input */}
      <Card size="small" title={t('cohort.source_code_search', 'Source Code')}>
        <div className="flex flex-col gap-1 w-full">
          <Select
            size="small"
            value={sourceCodeDomain}
            onChange={v => setSourceCodeDomain(v)}
            options={domainOptions}
          />
          <div ref={sourceDd.refs.setReference} {...sourceDd.getReferenceProps()}>
            <Input
              prefix={<Search className="h-3.5 w-3.5" />}
              placeholder={t('cohort.search_source_placeholder', 'Search by keyword...')}
              value={sourceSearchQuery}
              onChange={e => { setSourceSearchQuery(e.target.value); setSourceResultsOpen(true); }}
              onFocus={() => setSourceResultsOpen(true)}
            />
          </div>
          {/* Selected source codes */}
          {selectedSourceCodes.length > 0 && (
            <div className="p-1 bg-surface-dark rounded">
              <div className="flex flex-wrap gap-1">
                {selectedSourceCodes.map(code => (
                  <Tag key={code} closable onClose={() => toggleSourceCode(code)} color="blue">{code}</Tag>
                ))}
                <Tag color="green" className="cursor-pointer" style={{ cursor: 'pointer' }}>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={addSelectedSourceCodes}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); addSelectedSourceCodes(); } }}
                    className="flex items-center gap-0.5"
                  >
                    <Plus className="h-2.5 w-2.5" /> {t('cohort.add_criterion', 'Add as criterion')}
                  </span>
                </Tag>
              </div>
            </div>
          )}

          {/* Source search results — floating dropdown */}
          {sourceResultsOpen && sourceSearchQuery.length >= 2 && (
            <FloatingPortal>
              <div
                ref={sourceDd.refs.setFloating}
                style={sourceDd.floatingStyles}
                {...sourceDd.getFloatingProps()}
                className={RESULTS_PANEL_CLASS}
              >
                {sourceSearchLoading ? (
                  <div className="p-2 space-y-1.5">
                    <div className="text-xs text-text-dim text-center">{t('cohort.searching_source_codes', 'Searching source codes...')}</div>
                    <div className="h-1.5 w-full bg-surface-dark rounded-full overflow-hidden">
                      <div className="h-full bg-emerald-accent rounded-full animate-[progress_2s_ease-in-out_infinite]"
                        style={{ width: '60%', animation: 'progress 2s ease-in-out infinite' }} />
                    </div>
                    <style>{`@keyframes progress { 0% { width: 5%; margin-left: 0; } 50% { width: 60%; margin-left: 20%; } 100% { width: 5%; margin-left: 95%; } }`}</style>
                  </div>
                ) : sourceSearchResults.length > 0 ? (
                  sourceSearchResults.map(r => {
                    const isSelected = selectedSourceCodes.includes(r.source_value);
                    return (
                      <div
                        key={r.source_value}
                        className={`cursor-pointer px-2 py-1 border-b border-border-subtle last:border-b-0 transition-colors ${isSelected ? 'bg-blue-500/10' : 'hover:bg-emerald-accent/5'}`}
                        onClick={() => toggleSourceCode(r.source_value)}
                      >
                        <div className="flex justify-between">
                          <span className="text-xs font-semibold text-text-bright">{r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value}{(r as any).source_atc ? <span className="text-blue-400 ml-1">[{(r as any).source_atc}]</span> : null}</span>
                          <span className="text-text-dim text-[10px]">{r.n_records.toLocaleString()} rec</span>
                        </div>
                        <div className="text-[11px] text-text-dim">{t(`domains.${r.domain}`, r.domain)}{DOMAIN_NOMENCLATURE[r.domain] ? ` (${DOMAIN_NOMENCLATURE[r.domain]})` : ''} · {r.n_persons.toLocaleString()} pers</div>
                      </div>
                    );
                  })
                ) : (
                  <Empty description={t('cohort.no_source_codes', 'No source codes found')} className="!py-2" />
                )}
              </div>
            </FloatingPortal>
          )}
        </div>
      </Card>

      {/* Concept search */}
      <Card size="small" title={t('cohort.concept_search', 'Concept Search (OMOP)')}>
        <div ref={conceptDd.refs.setReference} {...conceptDd.getReferenceProps()}>
          <Input
            prefix={<Search className="h-3.5 w-3.5" />}
            placeholder={t('cohort.search_placeholder', 'Search by name or code...')}
            value={searchQuery}
            onChange={e => { setSearchQuery(e.target.value); setConceptResultsOpen(true); }}
            onFocus={() => setConceptResultsOpen(true)}
            className="mb-2"
          />
        </div>
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
                <span
                  role="button"
                  tabIndex={0}
                  onClick={() => addAsCriterion()}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); addAsCriterion(); } }}
                  className="flex items-center gap-0.5"
                >
                  <Plus className="h-2.5 w-2.5" /> {t('cohort.add_criterion', 'Add as criterion')}
                </span>
              </Tag>
            </div>
          </div>
        )}

        {/* Search results — floating dropdown */}
        {conceptResultsOpen && searchQuery.length >= 2 && (
          <FloatingPortal>
            <div
              ref={conceptDd.refs.setFloating}
              style={conceptDd.floatingStyles}
              {...conceptDd.getFloatingProps()}
              className={RESULTS_PANEL_CLASS}
            >
              {loading ? (
                <div className="text-center p-3"><Spinner size="small" /></div>
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
              ) : (
                <Empty description={t('cohort.no_concepts', 'No concepts found')} />
              )}
            </div>
          </FloatingPortal>
        )}
      </Card>
    </div>
  );
}
