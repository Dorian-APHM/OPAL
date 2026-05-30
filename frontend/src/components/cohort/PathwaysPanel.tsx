import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSessionState } from '../../hooks/useSessionState';
import {
  Card, Button, Alert, Empty, Spinner, Table, Tag, useToast,
} from '../../components/ui';
import type { Column } from '../../components/ui';
import {
  Play, Plus, Trash2, Download, GitBranch, Settings2, ChevronDown, ChevronUp,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cohortApi, conceptApi } from '../../api/client';
import type {
  CohortCriteria, PathwaysResult, PathwaysEventCohort,
  PathwaysSunburstNode, OmopConcept,
} from '../../types';

interface Props {
  cdmName: string;
  criteria: CohortCriteria;
  cohortKey?: string;
  cohortId?: number;
}

// ──── Sunburst SVG Component ────

interface SunburstArc {
  name: string;
  count: number;
  pct: number;
  depth: number;
  startAngle: number;
  endAngle: number;
  color: string;
  path: string[];
}

function buildArcs(
  node: PathwaysSunburstNode,
  eventColors: Record<string, string>,
  depth: number,
  startAngle: number,
  endAngle: number,
  parentPath: string[],
): SunburstArc[] {
  const arcs: SunburstArc[] = [];
  if (depth === 0) {
    // Root — skip, just process children
    const total = node.children.reduce((s, c) => s + c.count, 0);
    let angle = startAngle;
    for (const child of node.children) {
      const sweep = total > 0 ? ((child.count / total) * (endAngle - startAngle)) : 0;
      arcs.push(...buildArcs(child, eventColors, depth + 1, angle, angle + sweep, []));
      angle += sweep;
    }
    return arcs;
  }

  // Get colour for this event (combo events split by +)
  const parts = node.name.split('+');
  const color = parts.length === 1
    ? (eventColors[node.name] || '#999')
    : blendColors(parts.map(p => eventColors[p] || '#999'));

  const currentPath = [...parentPath, node.name];

  arcs.push({
    name: node.name,
    count: node.count,
    pct: node.pct,
    depth,
    startAngle,
    endAngle,
    color,
    path: currentPath,
  });

  // Process children
  const childTotal = node.children.reduce((s, c) => s + c.count, 0);
  if (childTotal > 0) {
    let angle = startAngle;
    for (const child of node.children) {
      const sweep = (child.count / childTotal) * (endAngle - startAngle);
      arcs.push(...buildArcs(child, eventColors, depth + 1, angle, angle + sweep, currentPath));
      angle += sweep;
    }
  }

  return arcs;
}

function blendColors(colors: string[]): string {
  if (colors.length === 0) return '#999';
  if (colors.length === 1) return colors[0];
  // Simple average of hex colours
  let r = 0, g = 0, b = 0;
  for (const c of colors) {
    const hex = c.replace('#', '');
    r += parseInt(hex.substring(0, 2), 16);
    g += parseInt(hex.substring(2, 4), 16);
    b += parseInt(hex.substring(4, 6), 16);
  }
  const n = colors.length;
  return `#${Math.round(r / n).toString(16).padStart(2, '0')}${Math.round(g / n).toString(16).padStart(2, '0')}${Math.round(b / n).toString(16).padStart(2, '0')}`;
}

function describeArc(
  cx: number, cy: number,
  innerR: number, outerR: number,
  startAngle: number, endAngle: number,
): string {
  // Convert angles to radians (0 = top, clockwise)
  const toRad = (a: number) => ((a - 90) * Math.PI) / 180;
  const s = toRad(startAngle);
  const e = toRad(endAngle);

  const x1 = cx + outerR * Math.cos(s);
  const y1 = cy + outerR * Math.sin(s);
  const x2 = cx + outerR * Math.cos(e);
  const y2 = cy + outerR * Math.sin(e);
  const x3 = cx + innerR * Math.cos(e);
  const y3 = cy + innerR * Math.sin(e);
  const x4 = cx + innerR * Math.cos(s);
  const y4 = cy + innerR * Math.sin(s);

  const largeArc = (endAngle - startAngle) > 180 ? 1 : 0;

  return [
    `M ${x1} ${y1}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4}`,
    'Z',
  ].join(' ');
}

interface SunburstProps {
  tree: PathwaysSunburstNode;
  eventColors: Record<string, string>;
  size?: number;
}

function Sunburst({ tree, eventColors, size = 420 }: SunburstProps) {
  const [hovered, setHovered] = useState<SunburstArc | null>(null);

  const arcs = useMemo(
    () => buildArcs(tree, eventColors, 0, 0, 360, []),
    [tree, eventColors],
  );

  const maxDepth = Math.max(...arcs.map(a => a.depth), 1);
  const cx = size / 2;
  const cy = size / 2;
  const ringWidth = (size / 2 - 40) / (maxDepth + 0.5);
  const innerGap = 30;

  return (
    <div className="relative inline-block">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {arcs.map((arc, i) => {
          const innerR = innerGap + (arc.depth - 1) * ringWidth;
          const outerR = innerR + ringWidth - 2;
          // Skip arcs that are too thin
          if (arc.endAngle - arc.startAngle < 0.3) return null;
          const d = describeArc(cx, cy, innerR, outerR, arc.startAngle, arc.endAngle);
          const isHovered = hovered === arc;
          return (
            <path
              key={i}
              d={d}
              fill={arc.color}
              stroke="#1e1e2e"
              strokeWidth={1}
              opacity={hovered && !isHovered ? 0.4 : 1}
              style={{ transition: 'opacity 0.15s', cursor: 'pointer' }}
              onMouseEnter={() => setHovered(arc)}
              onMouseLeave={() => setHovered(null)}
            />
          );
        })}
        {/* Centre label */}
        <text x={cx} y={cy - 8} textAnchor="middle" className="fill-text-bright text-sm font-semibold">
          {hovered ? hovered.name : `${tree.count}`}
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" className="fill-text-muted text-xs">
          {hovered ? `${hovered.count} (${hovered.pct}%)` : 'patients'}
        </text>
      </svg>
      {hovered && (
        <div className="absolute bottom-0 left-0 right-0 text-center pb-1">
          <span className="text-xs text-text-muted">
            {hovered.path.join(' → ')}
          </span>
        </div>
      )}
    </div>
  );
}

// ──── Event Cohort Builder ────

interface EventCohortBuilderProps {
  cdmName: string;
  eventCohorts: PathwaysEventCohort[];
  onChange: (ecs: PathwaysEventCohort[]) => void;
}

const DOMAIN_OPTIONS = ['Drug', 'Condition', 'Procedure', 'Measurement', 'Observation', 'Device'];

function EventCohortBuilder({ cdmName, eventCohorts, onChange }: EventCohortBuilderProps) {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDomain, setSearchDomain] = useState('Drug');
  const [searchResults, setSearchResults] = useState<OmopConcept[]>([]);
  const [searching, setSearching] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [newDomain, setNewDomain] = useState('Drug');
  const [selectedConcepts, setSelectedConcepts] = useState<OmopConcept[]>([]);
  const [includeDescendants, setIncludeDescendants] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Source code search state
  const [sourceSearchQuery, setSourceSearchQuery] = useState('');
  const [sourceSearchResults, setSourceSearchResults] = useState<{ source_value: string; source_name?: string; domain: string; n_records: number; n_persons: number }[]>([]);
  const [sourceSearchLoading, setSourceSearchLoading] = useState(false);
  const [selectedSourceCodes, setSelectedSourceCodes] = useState<string[]>([]);

  // Source code keyword search (debounced)
  useEffect(() => {
    if (!sourceSearchQuery || sourceSearchQuery.length < 2 || !cdmName) {
      setSourceSearchResults([]);
      return;
    }
    const abort = new AbortController();
    const timer = setTimeout(() => {
      setSourceSearchLoading(true);
      conceptApi.searchSourceValue(cdmName, { q: sourceSearchQuery, domain: newDomain, limit: 20 })
        .then(r => { if (!abort.signal.aborted) setSourceSearchResults(r.data.results); })
        .catch(() => { if (!abort.signal.aborted) setSourceSearchResults([]); })
        .finally(() => { if (!abort.signal.aborted) setSourceSearchLoading(false); });
    }, 300);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [sourceSearchQuery, newDomain, cdmName]);

  const toggleSourceCode = (code: string) => {
    setSelectedSourceCodes(prev =>
      prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
    );
  };

  const doSearch = useCallback(async () => {
    if (!searchQuery.trim() || !cdmName) return;
    setSearching(true);
    try {
      const resp = await cohortApi.searchConcepts(cdmName, searchQuery.trim(), searchDomain, undefined, true);
      setSearchResults(resp.data.concepts);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [cdmName, searchQuery, searchDomain]);

  const addConcept = (c: OmopConcept) => {
    if (!selectedConcepts.find(x => x.concept_id === c.concept_id)) {
      setSelectedConcepts(prev => [...prev, c]);
    }
  };

  const removeConcept = (cid: number) => {
    setSelectedConcepts(prev => prev.filter(c => c.concept_id !== cid));
  };

  const saveEventCohort = () => {
    if (!newName.trim() || (selectedConcepts.length === 0 && selectedSourceCodes.length === 0)) return;
    const ec: PathwaysEventCohort = {
      name: newName.trim(),
      domain: newDomain,
      concept_ids: selectedConcepts.map(c => c.concept_id),
      include_descendants: includeDescendants,
      source_codes: selectedSourceCodes,
    };
    if (editingIndex !== null) {
      const updated = [...eventCohorts];
      updated[editingIndex] = ec;
      onChange(updated);
      setEditingIndex(null);
    } else {
      onChange([...eventCohorts, ec]);
    }
    resetForm();
  };

  const resetForm = () => {
    setNewName('');
    setNewDomain('Drug');
    setSelectedConcepts([]);
    setIncludeDescendants(true);
    setSearchQuery('');
    setSearchResults([]);
    setSourceSearchQuery('');
    setSourceSearchResults([]);
    setSelectedSourceCodes([]);
    setShowForm(false);
    setEditingIndex(null);
  };

  const editEventCohort = (idx: number) => {
    const ec = eventCohorts[idx];
    setNewName(ec.name);
    setNewDomain(ec.domain);
    setSearchDomain(ec.domain);
    setIncludeDescendants(ec.include_descendants);
    // We don't have the full concept objects, show concept IDs
    setSelectedConcepts(ec.concept_ids.map(id => ({
      concept_id: id,
      concept_name: `Concept #${id}`,
      concept_code: '',
      domain_id: ec.domain,
      vocabulary_id: '',
      concept_class_id: '',
      standard_concept: 'S',
    })));
    setSelectedSourceCodes(ec.source_codes || []);
    setEditingIndex(idx);
    setShowForm(true);
  };

  const removeEventCohort = (idx: number) => {
    onChange(eventCohorts.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-3">
      {/* Event cohorts list */}
      {eventCohorts.length > 0 && (
        <div className="space-y-1.5">
          {eventCohorts.map((ec, i) => (
            <div
              key={`${ec.name}-${i}`}
              className="flex items-center gap-2 px-3 py-2 bg-surface-dark rounded-lg border border-border-subtle"
            >
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-text-bright">{ec.name}</span>
                <span className="text-xs text-text-muted ml-2">
                  {ec.domain}
                  {ec.concept_ids.length > 0 && <> · {ec.concept_ids.length} concept{ec.concept_ids.length > 1 ? 's' : ''}{ec.include_descendants ? ' + desc.' : ''}</>}
                  {ec.source_codes?.length > 0 && <> · {ec.source_codes.length} source code{ec.source_codes.length > 1 ? 's' : ''}</>}
                </span>
              </div>
              <button
                onClick={() => editEventCohort(i)}
                className="text-text-muted hover:text-text-bright text-xs"
              >
                {t('common.edit', 'Edit')}
              </button>
              <button
                onClick={() => removeEventCohort(i)}
                className="text-red-400 hover:text-red-300"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add new event cohort */}
      {!showForm ? (
        <Button size="small" onClick={() => setShowForm(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          {t('pathways.add_event_cohort', 'Add Event Cohort')}
        </Button>
      ) : (
        <Card size="small" className="border border-border-subtle">
          <div className="space-y-3">
            {/* Name + Domain */}
            <div className="flex gap-2">
              <input
                className="flex-1 bg-surface-dark border border-border-subtle rounded px-2 py-1.5 text-sm text-text-bright placeholder-text-dim"
                placeholder={t('pathways.event_name', 'Event name (e.g. ACE Inhibitors)')}
                value={newName}
                onChange={e => setNewName(e.target.value)}
              />
              <select
                className="bg-surface-dark border border-border-subtle rounded px-2 py-1.5 text-sm text-text-bright"
                value={newDomain}
                onChange={e => { setNewDomain(e.target.value); setSearchDomain(e.target.value); }}
              >
                {DOMAIN_OPTIONS.map(d => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>

            {/* Concept search */}
            <div className="flex gap-2">
              <input
                className="flex-1 bg-surface-dark border border-border-subtle rounded px-2 py-1.5 text-sm text-text-bright placeholder-text-dim"
                placeholder={t('pathways.search_concepts', 'Search concepts...')}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && doSearch()}
              />
              <Button size="small" onClick={doSearch} loading={searching}>
                {t('common.search', 'Search')}
              </Button>
            </div>

            {/* Search results */}
            {searchResults.length > 0 && (
              <div className="max-h-40 overflow-y-auto border border-border-subtle rounded bg-surface-darker">
                {searchResults.map(c => (
                  <button
                    key={c.concept_id}
                    className="w-full text-left px-2 py-1.5 text-xs hover:bg-surface-dark border-b border-border-subtle last:border-0 flex items-center justify-between gap-2"
                    onClick={() => addConcept(c)}
                  >
                    <span className="truncate text-text-bright">
                      {c.concept_name}
                      <span className="text-text-muted ml-1">({c.concept_code})</span>
                    </span>
                    <span className="shrink-0 text-text-dim">{c.vocabulary_id}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Selected concepts */}
            {selectedConcepts.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {selectedConcepts.map(c => (
                  <Tag key={c.concept_id} color="blue" closable onClose={() => removeConcept(c.concept_id)}>
                    {c.concept_name.length > 30
                      ? c.concept_name.substring(0, 30) + '...'
                      : c.concept_name}
                  </Tag>
                ))}
              </div>
            )}

            {/* Include descendants */}
            <label className="flex items-center gap-2 text-xs text-text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={includeDescendants}
                onChange={e => setIncludeDescendants(e.target.checked)}
                className="accent-emerald-500"
              />
              {t('pathways.include_descendants', 'Include descendant concepts')}
            </label>

            {/* Source code search */}
            <div className="border-t border-border-subtle pt-3">
              <div className="text-xs font-medium text-text-muted mb-1.5">
                {t('pathways.source_codes', 'Source Codes')}
              </div>
              <input
                className="w-full bg-surface-dark border border-border-subtle rounded px-2 py-1.5 text-sm text-text-bright placeholder-text-dim"
                placeholder={t('pathways.search_source_codes', 'Search by source code or keyword...')}
                value={sourceSearchQuery}
                onChange={e => setSourceSearchQuery(e.target.value)}
              />

              {/* Selected source codes */}
              {selectedSourceCodes.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {selectedSourceCodes.map(code => (
                    <Tag key={code} color="green" closable onClose={() => toggleSourceCode(code)}>
                      {code}
                    </Tag>
                  ))}
                </div>
              )}

              {/* Source search results */}
              {sourceSearchLoading ? (
                <div className="text-xs text-text-dim text-center py-2">{t('common.searching', 'Searching...')}</div>
              ) : sourceSearchResults.length > 0 ? (
                <div className="max-h-36 overflow-y-auto border border-border-subtle rounded bg-surface-darker mt-1.5">
                  {sourceSearchResults.map(r => {
                    const isSelected = selectedSourceCodes.includes(r.source_value);
                    return (
                      <button
                        key={r.source_value}
                        className={`w-full text-left px-2 py-1.5 text-xs border-b border-border-subtle last:border-0 flex items-center justify-between gap-2 ${isSelected ? 'bg-emerald-500/10' : 'hover:bg-surface-dark'}`}
                        onClick={() => toggleSourceCode(r.source_value)}
                      >
                        <span className="truncate text-text-bright">
                          {r.source_name ? `${r.source_value} — ${r.source_name}` : r.source_value}
                        </span>
                        <span className="shrink-0 text-text-dim">{r.n_records.toLocaleString()} rec</span>
                      </button>
                    );
                  })}
                </div>
              ) : sourceSearchQuery.length >= 2 ? (
                <div className="text-xs text-text-dim text-center py-1.5">{t('pathways.no_source_codes', 'No source codes found')}</div>
              ) : null}
            </div>

            {/* Save / Cancel */}
            <div className="flex gap-2">
              <Button
                size="small"
                variant="primary"
                onClick={saveEventCohort}
                disabled={!newName.trim() || (selectedConcepts.length === 0 && selectedSourceCodes.length === 0)}
              >
                {editingIndex !== null ? t('common.update', 'Update') : t('common.add', 'Add')}
              </Button>
              <Button size="small" onClick={resetForm}>
                {t('common.cancel', 'Cancel')}
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

// ──── Main PathwaysPanel ────

export default function PathwaysPanel({ cdmName, criteria, cohortKey = 'draft', cohortId }: Props) {
  const { t } = useTranslation();
  const toast = useToast();

  // State — scoped by cohortKey so each cohort keeps its own results
  const ck = cohortKey;
  const [eventCohorts, setEventCohorts] = useSessionState<PathwaysEventCohort[]>(`cohort:pw:events:${ck}`, []);
  const [result, setResult] = useSessionState<PathwaysResult | null>(`cohort:pw:result:${ck}`, null);
  const [loading, setLoading] = useSessionState(`cohort:pw:loading:${ck}`, false);
  const [taskId, setTaskId] = useSessionState<string | null>(`cohort:pw:taskId:${ck}`, null);
  const [progressCompleted, setProgressCompleted] = useSessionState(`cohort:pw:progDone:${ck}`, 0);
  const [progressTotal, setProgressTotal] = useSessionState(`cohort:pw:progTotal:${ck}`, 0);
  const [currentStep, setCurrentStep] = useSessionState(`cohort:pw:step:${ck}`, '');
  const [error, setError] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [maxDepth, setMaxDepth] = useState(5);
  const [minCellCount, setMinCellCount] = useState(5);
  const [comboWindow, setComboWindow] = useState(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasCriteria =
    criteria.inclusion.criteria.length > 0 ||
    criteria.demographics?.age ||
    criteria.demographics?.gender;

  const canRun = hasCriteria && eventCohorts.length > 0;

  // Polling logic
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback((tid: string) => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const resp = await cohortApi.pathwaysStatus(tid);
        const data = resp.data;
        setProgressCompleted(data.completed || 0);
        setProgressTotal(data.total || 0);
        setCurrentStep(data.current_step || '');

        if (data.status === 'completed' && data.result) {
          setResult(data.result);
          setLoading(false);
          setTaskId(null);
          stopPolling();

          // Auto-save to DB if cohort is saved
          if (cohortId) {
            try { await cohortApi.savePathways(cohortId, data.result); } catch { /* non-blocking */ }
          }
        } else if (data.status === 'error') {
          setError(data.error || 'Analysis failed');
          setLoading(false);
          setTaskId(null);
          stopPolling();
        }
      } catch {
        // Network error — keep polling
      }
    }, 2000);
  }, [stopPolling, cohortId]);

  // Load saved pathways from DB on mount (if cohort is saved and no result in memory)
  const [loadingSaved, setLoadingSaved] = useState(false);
  useEffect(() => {
    if (!cohortId || result || loading) return;
    let cancelled = false;
    setLoadingSaved(true);
    cohortApi.getPathways(cohortId).then(resp => {
      if (cancelled) return;
      if (resp.data.pathways) {
        setResult(resp.data.pathways);
      }
    }).catch(() => {}).finally(() => {
      if (!cancelled) setLoadingSaved(false);
    });
    return () => { cancelled = true; };
  }, [cohortId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Resume polling on remount
  useEffect(() => {
    if (taskId && loading) {
      startPolling(taskId);
    }
    return () => stopPolling();
  }, [taskId, loading, startPolling, stopPolling]);

  const runAnalysis = async () => {
    if (!canRun) return;
    setLoading(true);
    setResult(null);
    setError('');
    setProgressCompleted(0);
    setProgressTotal(0);
    setCurrentStep('');

    try {
      const resp = await cohortApi.pathways(cdmName, criteria, eventCohorts, {
        max_depth: maxDepth,
        min_cell_count: minCellCount,
        combo_window: comboWindow,
      });
      setTaskId(resp.data.task_id);
      startPolling(resp.data.task_id);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to start analysis');
      setLoading(false);
    }
  };

  const cancelAnalysis = async () => {
    if (taskId) {
      try { await cohortApi.pathwaysCancel(taskId); } catch { /* ignore */ }
    }
    stopPolling();
    setLoading(false);
    setTaskId(null);
  };

  // Export CSV
  const exportCsv = () => {
    if (!result) return;
    const lines = ['Pathway,Count,Percent'];
    for (const row of result.pathways_table) {
      lines.push(`"${row.pathway.join(' → ')}",${row.count},${row.pct}`);
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pathways_analysis.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  // Pathways table columns
  const tableColumns: Column<any>[] = [
    {
      title: '#',
      dataIndex: '_rank',
      key: 'rank',
      width: 40,
      render: (_v: any, _r: any, idx: number) => (
        <span className="text-text-dim">{(idx || 0) + 1}</span>
      ),
    },
    {
      title: t('pathways.pathway', 'Pathway'),
      dataIndex: 'pathway',
      key: 'pathway',
      render: (pathway: string[]) => (
        <div className="flex items-center gap-1 flex-wrap">
          {pathway.map((step, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-text-dim">→</span>}
              <Tag
                color={
                  result?.event_colors[step]
                    ? undefined
                    : 'default'
                }
              >
                <span
                  className="inline-block w-2 h-2 rounded-full mr-1"
                  style={{ backgroundColor: result?.event_colors[step] || '#999' }}
                />
                {step}
              </Tag>
            </span>
          ))}
        </div>
      ),
    },
    {
      title: t('pathways.count', 'Count'),
      dataIndex: 'count',
      key: 'count',
      width: 80,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '%',
      dataIndex: 'pct',
      key: 'pct',
      width: 70,
      render: (v: number) => `${v}%`,
    },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card size="small">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-emerald-accent" />
            <span className="font-semibold text-text-bright">
              {t('pathways.title', 'Pathways Analysis')}
            </span>
            <span className="text-xs text-text-muted">
              {t('pathways.subtitle', 'ATLAS-style treatment pathway analysis')}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="text-text-muted hover:text-text-bright"
              title={t('pathways.settings', 'Settings')}
            >
              {showSettings ? <ChevronUp className="h-4 w-4" /> : <Settings2 className="h-4 w-4" />}
            </button>
            {result && (
              <Button size="small" onClick={exportCsv}>
                <Download className="h-3.5 w-3.5 mr-1" />
                CSV
              </Button>
            )}
            {loading ? (
              <Button size="small" variant="danger" onClick={cancelAnalysis}>
                {t('common.cancel', 'Cancel')}
              </Button>
            ) : (
              <Button
                size="small"
                variant="primary"
                onClick={runAnalysis}
                disabled={!canRun}
              >
                <Play className="h-3.5 w-3.5 mr-1" />
                {t('pathways.run', 'Run Analysis')}
              </Button>
            )}
          </div>
        </div>

        {/* Settings panel */}
        {showSettings && (
          <div className="mt-3 pt-3 border-t border-border-subtle grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-text-muted mb-1">
                {t('pathways.max_depth', 'Max Depth (steps)')}
              </label>
              <input
                type="number"
                min={1} max={10}
                value={maxDepth}
                onChange={e => setMaxDepth(Math.min(10, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-full bg-surface-dark border border-border-subtle rounded px-2 py-1 text-sm text-text-bright"
              />
            </div>
            <div>
              <label className="block text-xs text-text-muted mb-1">
                {t('pathways.min_cell_count', 'Min Cell Count')}
              </label>
              <input
                type="number"
                min={1} max={1000}
                value={minCellCount}
                onChange={e => setMinCellCount(Math.min(1000, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-full bg-surface-dark border border-border-subtle rounded px-2 py-1 text-sm text-text-bright"
              />
            </div>
            <div>
              <label className="block text-xs text-text-muted mb-1">
                {t('pathways.combo_window', 'Combo Window (days)')}
              </label>
              <input
                type="number"
                min={0} max={365}
                value={comboWindow}
                onChange={e => setComboWindow(Math.min(365, Math.max(0, parseInt(e.target.value) || 0)))}
                className="w-full bg-surface-dark border border-border-subtle rounded px-2 py-1 text-sm text-text-bright"
              />
            </div>
          </div>
        )}
      </Card>

      {/* Event Cohorts definition */}
      <Card
        size="small"
        title={
          <span className="text-sm font-medium text-text-bright">
            {t('pathways.event_cohorts', 'Event Cohorts')}
            <span className="text-text-muted font-normal ml-2">
              ({eventCohorts.length})
            </span>
          </span>
        }
      >
        {!cdmName ? (
          <Alert type="warning" message={t('cohort.select_cdm', 'Please select a CDM first')} />
        ) : (
          <EventCohortBuilder
            cdmName={cdmName}
            eventCohorts={eventCohorts}
            onChange={setEventCohorts}
          />
        )}
      </Card>

      {/* Loading / Progress */}
      {loading && (
        <Card size="small">
          <div className="flex items-center gap-3">
            <Spinner />
            <div className="flex-1">
              <div className="text-sm text-text-bright">
                {t('pathways.analyzing', 'Analyzing pathways...')}
              </div>
              {progressTotal > 0 && (
                <div className="mt-1">
                  <div className="flex justify-between text-xs text-text-muted mb-1">
                    <span>{currentStep}</span>
                    <span>{progressCompleted}/{progressTotal}</span>
                  </div>
                  <div className="w-full bg-surface-dark rounded-full h-1.5">
                    <div
                      className="bg-emerald-accent h-1.5 rounded-full transition-all"
                      style={{ width: `${(progressCompleted / progressTotal) * 100}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Error */}
      {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}

      {/* Results */}
      {result && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-3 gap-3">
            <Card size="small" className="text-center">
              <div className="text-2xl font-bold text-text-bright">{result.target_size.toLocaleString()}</div>
              <div className="text-xs text-text-muted">{t('pathways.target_size', 'Target Cohort')}</div>
            </Card>
            <Card size="small" className="text-center">
              <div className="text-2xl font-bold text-emerald-accent">{result.persons_with_pathways.toLocaleString()}</div>
              <div className="text-xs text-text-muted">{t('pathways.with_events', 'With Events')}</div>
            </Card>
            <Card size="small" className="text-center">
              <div className="text-2xl font-bold text-text-bright">{result.pathways_table.length}</div>
              <div className="text-xs text-text-muted">{t('pathways.distinct_paths', 'Distinct Pathways')}</div>
            </Card>
          </div>

          {/* Sunburst + Legend */}
          <Card size="small" title={t('pathways.sunburst', 'Treatment Pathways Sunburst')}>
            <div className="flex items-start gap-6 flex-wrap justify-center">
              <Sunburst
                tree={result.sunburst_tree}
                eventColors={result.event_colors}
                size={380}
              />
              {/* Legend */}
              <div className="space-y-1.5 py-2">
                <div className="text-xs text-text-muted font-medium mb-2">
                  {t('pathways.legend', 'Legend')}
                </div>
                {Object.entries(result.event_colors).map(([name, color]) => (
                  <div key={name} className="flex items-center gap-2">
                    <span
                      className="inline-block w-3.5 h-3.5 rounded-sm shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span className="text-sm text-text-bright">{name}</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* Pathways Table */}
          <Card size="small" title={t('pathways.top_pathways', 'Top Pathways')}>
            <Table
              size="small"
              dataSource={result.pathways_table}
              columns={tableColumns}
              rowKey={(r: any) => r.pathway.join('-')}
              pagination={false}
              scroll={{ x: true }}
            />
          </Card>
        </>
      )}

      {/* Empty state */}
      {!loading && !result && !error && (
        <Empty
          description={
            !hasCriteria
              ? t('pathways.define_cohort', 'Define a target cohort first')
              : eventCohorts.length === 0
              ? t('pathways.add_events', 'Add at least one event cohort to analyze pathways')
              : t('pathways.ready', 'Click Run Analysis to compute treatment pathways')
          }
        />
      )}
    </div>
  );
}
