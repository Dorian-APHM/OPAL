import { useState } from 'react';
import { ChevronDown, ChevronRight, X, AlertTriangle, Calendar, Activity } from 'lucide-react';
import type { DraftCriterion, ConceptSetGroup } from '../../types';
import { Checkbox } from '../ui';

interface Props {
  criterion: DraftCriterion;
  selected: Set<string>;                       // selected source_values
  onChange: (next: Set<string>) => void;
  onRemove: () => void;
}

const DOMAIN_LABEL: Record<string, string> = {
  Condition: 'Condition', Drug: 'Médicament', Procedure: 'Acte', Measurement: 'Mesure', Visit: 'Séjour',
};

function formatTemporal(t: DraftCriterion['temporal']): string | null {
  if (!t) return null;
  if (t.type === 'absolute_window') {
    if (t.date_from && t.date_to) return `${t.date_from} → ${t.date_to}`;
    if (t.date_from) return `depuis ${t.date_from}`;
    if (t.date_to) return `jusqu'au ${t.date_to}`;
  }
  if (t.type === 'within_days') {
    const parts = [];
    if (t.days_before) parts.push(`≤ ${t.days_before} j avant`);
    if (t.days_after) parts.push(`≤ ${t.days_after} j après`);
    return parts.join(', ') + ' (index)';
  }
  if (t.type === 'relative_to_criterion') {
    return `${t.relation || 'before'} (±${t.days_after || t.days_before || 0} j)`;
  }
  return null;
}

function formatValue(v: DraftCriterion['value']): string | null {
  if (!v) return null;
  if (v.operator === 'between' && v.value_high != null) return `${v.value}–${v.value_high}`;
  return `${v.operator} ${v.value}${(v as any).unit ? ' ' + (v as any).unit : ''}`;
}

export default function CriterionReviewCard({ criterion, selected, onChange, onRemove }: Props) {
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  // "Molécule exacte" (Drug): keep only members that matched the molecule by name,
  // dropping the ATC siblings pulled in by group expansion (e.g. kétoprofène under
  // ibuprofène). Only offered when a group actually carries such siblings.
  const [exactOnly, setExactOnly] = useState(false);
  const isDrug = criterion.domain === 'Drug';
  const hasSiblings = criterion.concept_sets.some(g => g.members.some(m => m.matched === false));
  const memsOf = (g: ConceptSetGroup) =>
    exactOnly ? g.members.filter(m => m.matched !== false) : g.members;

  const temporal = formatTemporal(criterion.temporal);
  const value = formatValue(criterion.value);
  const totalCodes = criterion.concept_sets.reduce((n, g) => n + memsOf(g).length, 0);

  const toggleCode = (sv: string) => {
    const next = new Set(selected);
    next.has(sv) ? next.delete(sv) : next.add(sv);
    onChange(next);
  };

  const groupState = (g: ConceptSetGroup): { all: boolean; some: boolean } => {
    const mems = memsOf(g);
    const inSel = mems.filter(m => selected.has(m.source_value)).length;
    return { all: inSel === mems.length && inSel > 0, some: inSel > 0 && inSel < mems.length };
  };

  const toggleGroup = (g: ConceptSetGroup, checked: boolean) => {
    const next = new Set(selected);
    memsOf(g).forEach(m => checked ? next.add(m.source_value) : next.delete(m.source_value));
    onChange(next);
  };

  // Turning "exact" on deselects the ATC siblings so the selection follows the view.
  const toggleExact = (checked: boolean) => {
    setExactOnly(checked);
    if (checked) {
      const next = new Set(selected);
      criterion.concept_sets.forEach(g =>
        g.members.forEach(m => { if (m.matched === false) next.delete(m.source_value); }));
      onChange(next);
    }
  };

  const toggleOpen = (key: string) => {
    const next = new Set(openGroups);
    next.has(key) ? next.delete(key) : next.add(key);
    setOpenGroups(next);
  };

  return (
    <div className="rounded-lg border border-white/10 bg-surface-1/60 p-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <span className="font-medium text-text-bright truncate">{criterion.label}</span>
          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-accent/15 text-emerald-accent">
            {DOMAIN_LABEL[criterion.domain] || criterion.domain}
          </span>
          {criterion.negation && (
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-red-500/15 text-red-400">exclusion</span>
          )}
          {temporal && (
            <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-text-dim">
              <Calendar className="h-3 w-3" />{temporal}
            </span>
          )}
          {value && (
            <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-text-dim">
              <Activity className="h-3 w-3" />{value}
            </span>
          )}
        </div>
        <button onClick={onRemove} className="text-text-dim hover:text-red-400 shrink-0" title="Retirer ce critère" aria-label="Retirer ce critère">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* No match warning */}
      {criterion.no_match || criterion.concept_sets.length === 0 ? (
        <div className="mt-2 flex items-center gap-2 text-[12px] text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          Aucun code trouvé pour « {criterion.label} » — à affiner manuellement dans le Builder.
        </div>
      ) : (
        <div className="mt-2 space-y-1.5">
          <div className="flex items-center justify-between gap-2 text-[11px] text-text-dim">
            <span>{criterion.concept_sets.length} groupe(s) · {totalCodes} code(s) · {selected.size} sélectionné(s)</span>
            {isDrug && hasSiblings && (
              <label className="flex items-center gap-1.5 cursor-pointer shrink-0" title="Ne garder que la molécule demandée (retire les molécules voisines de la même classe ATC)">
                <Checkbox checked={exactOnly} onChange={toggleExact} />
                <span>Molécule exacte</span>
              </label>
            )}
          </div>
          {criterion.concept_sets.map((g) => {
            const key = `${g.domain}:${g.group_key}`;
            const mems = memsOf(g);
            if (mems.length === 0) return null;
            const st = groupState(g);
            const open = openGroups.has(key);
            return (
              <div key={key} className="rounded border border-white/5 bg-black/20">
                <div className="flex items-center gap-2 px-2 py-1.5">
                  <Checkbox checked={st.all} indeterminate={st.some} onChange={(c) => toggleGroup(g, c)} />
                  <button onClick={() => toggleOpen(key)} aria-label={open ? 'Réduire' : 'Développer'} aria-expanded={open} className="flex items-center gap-1 text-text-dim hover:text-text-bright">
                    {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  </button>
                  <span className="text-[12px] font-mono text-emerald-accent">{g.group_key}</span>
                  <span className="text-[12px] text-text truncate flex-1">{g.rep_label}</span>
                  <span className="text-[11px] text-text-dim shrink-0">{mems.length} code(s)</span>
                </div>
                {open && (
                  <div className="px-2 pb-2 pl-8 space-y-1 max-h-56 overflow-y-auto">
                    {mems.map((m) => (
                      <label key={m.source_value} className="flex items-center gap-2 text-[12px] cursor-pointer"
                             onClick={(e) => { e.preventDefault(); toggleCode(m.source_value); }}>
                        <Checkbox checked={selected.has(m.source_value)} onChange={() => toggleCode(m.source_value)} />
                        <span className="font-mono text-text-dim w-20 shrink-0">{m.source_value}</span>
                        <span className="text-text truncate">{m.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
