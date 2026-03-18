/**
 * QueryCanvas — Visual cohort criteria builder.
 *
 * This is the main canvas where users compose inclusion/exclusion criteria.
 * It delegates rendering to CriteriaGroupEditor which supports:
 *  - Nested sub-groups with recursive AND/OR logic  (P0-1)
 *  - Rich temporal relations between criteria        (P0-2)
 *
 * The CriteriaGroupEditor works with a `children` array internally but
 * denormalises back to `criteria[]` + `groups[]` for backend compatibility.
 */
import { useMemo } from 'react';
import { Card, Select, Empty, Tag, NumberInput } from '../../components/ui';
import { Check, X, Clock, Star } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import CriteriaGroupEditor, { denormaliseGroup, normaliseGroup } from './CriteriaGroupEditor';
import CriteriaPanel from './CriteriaPanel';
import type {
  CohortCriterion, CriteriaGroup, DemographicConstraints,
  CohortExitCriteria,
} from '../../types';

interface Props {
  inclusion: CriteriaGroup;
  exclusion: CriteriaGroup;
  demographics: DemographicConstraints;
  exitCriteria?: CohortExitCriteria;
  initialEventId?: string;
  cdmName: string;
  onUpdateInclusion: (group: CriteriaGroup) => void;
  onUpdateExclusion: (group: CriteriaGroup) => void;
  onUpdateDemographics: (demo: DemographicConstraints) => void;
  onUpdateExitCriteria?: (exit: CohortExitCriteria) => void;
  onUpdateInitialEvent?: (criterionId: string | undefined) => void;
}

/** Collect all criteria from a group tree (for temporal references). */
function collectAllCriteria(group: CriteriaGroup): CohortCriterion[] {
  const result: CohortCriterion[] = [...(group.criteria || [])];
  const children = group.children ?? [];
  for (const node of children) {
    if (node.type === 'criterion') {
      // Avoid duplicates if already in criteria[]
      if (!result.some(c => c.id === node.criterion.id)) {
        result.push(node.criterion);
      }
    } else {
      result.push(...collectAllCriteria(node.group));
    }
  }
  for (const sub of (group.groups ?? [])) {
    result.push(...collectAllCriteria(sub));
  }
  return result;
}

export default function QueryCanvas({
  inclusion, exclusion, demographics, exitCriteria, initialEventId, cdmName,
  onUpdateInclusion, onUpdateExclusion, onUpdateDemographics, onUpdateExitCriteria,
  onUpdateInitialEvent,
}: Props) {
  const { t } = useTranslation();

  // Normalise incoming groups so CriteriaGroupEditor always has children[]
  const normInclusion = normaliseGroup(inclusion);
  const normExclusion = normaliseGroup(exclusion);

  // Gather all criteria across both groups for cross-referencing in temporal constraints (memoized — P23 fix)
  const allCriteria = useMemo(
    () => [...collectAllCriteria(normInclusion), ...collectAllCriteria(normExclusion)],
    [normInclusion, normExclusion],
  );

  const handleInclusionChange = (updated: CriteriaGroup) => {
    // Denormalise so the backend receives criteria[] + groups[]
    onUpdateInclusion(denormaliseGroup(updated));
  };

  const handleExclusionChange = (updated: CriteriaGroup) => {
    onUpdateExclusion(denormaliseGroup(updated));
  };

  const hasInclusion = (normInclusion.children?.length ?? 0) > 0
    || normInclusion.criteria.length > 0;
  const hasExclusion = (normExclusion.children?.length ?? 0) > 0
    || normExclusion.criteria.length > 0;
  const isEmpty = !hasInclusion && !hasExclusion;

  const genderOptions = [
    { value: '8507', label: 'Male (8507)' },
    { value: '8532', label: 'Female (8532)' },
  ];

  return (
    <div className="h-full overflow-auto flex flex-col gap-3">
      {/* Demographics */}
      <Card size="small" title={t('cohort.demographics', 'Demographics')}>
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-1">
            <span className="text-xs text-text-muted">{t('cohort.age', 'Age')}:</span>
            <NumberInput
              min={0}
              max={120}
              placeholder="Min"
              value={demographics.age?.min}
              onChange={v => onUpdateDemographics({ ...demographics, age: { ...demographics.age, min: v ?? undefined } })}
              className="!w-[60px]"
            />
            <span className="text-xs text-text-muted">-</span>
            <NumberInput
              min={0}
              max={120}
              placeholder="Max"
              value={demographics.age?.max}
              onChange={v => onUpdateDemographics({ ...demographics, age: { ...demographics.age, max: v ?? undefined } })}
              className="!w-[60px]"
            />
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-text-muted">{t('cohort.gender', 'Gender')}:</span>
            <div className="flex gap-1">
              {genderOptions.map(opt => {
                const selected = (demographics.gender || []).includes(Number(opt.value));
                return (
                  <span
                    key={opt.value}
                    className={`inline-flex items-center px-2 py-0.5 rounded-md border text-xs cursor-pointer select-none transition-colors ${
                      selected
                        ? 'bg-emerald-accent/15 text-emerald-accent border-emerald-accent/30'
                        : 'bg-surface-dark text-text-dim border-glass-border hover:border-emerald-accent/30'
                    }`}
                    onClick={() => {
                      const current = demographics.gender || [];
                      const num = Number(opt.value);
                      const next = current.includes(num)
                        ? current.filter(v => v !== num)
                        : [...current, num];
                      onUpdateDemographics({ ...demographics, gender: next.length > 0 ? next : undefined });
                    }}
                  >
                    {opt.label}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      {/* INCLUSION */}
      {hasInclusion && (
        <div style={{ borderLeft: '3px solid #10B981' }} className="rounded">
          <div className="px-2 py-1 flex items-center gap-1.5">
            <Check className="h-4 w-4 text-emerald-accent" />
            <span className="font-semibold text-emerald-accent text-[13px]">
              {t('cohort.inclusion', 'Inclusion Criteria')}
            </span>
          </div>
          <CriteriaGroupEditor
            group={normInclusion}
            depth={0}
            groupKey="inclusion"
            cdmName={cdmName}
            allCriteria={allCriteria}
            onChange={handleInclusionChange}
            initialEventId={initialEventId}
            onSetInitialEvent={onUpdateInitialEvent}
          />
        </div>
      )}

      {/* EXCLUSION */}
      {hasExclusion && (
        <div style={{ borderLeft: '3px solid #ff4d4f' }} className="rounded">
          <div className="px-2 py-1 flex items-center gap-1.5">
            <X className="h-4 w-4 text-red-400" />
            <span className="font-semibold text-red-400 text-[13px]">
              {t('cohort.exclusion', 'Exclusion Criteria')}
            </span>
          </div>
          <CriteriaGroupEditor
            group={normExclusion}
            depth={0}
            groupKey="exclusion"
            cdmName={cdmName}
            allCriteria={allCriteria}
            onChange={handleExclusionChange}
          />
        </div>
      )}

      {/* Exit Criteria */}
      {onUpdateExitCriteria && hasInclusion && (
        <Card
          size="small"
          title={<div className="flex items-center gap-1"><Clock className="h-4 w-4" /><span className="text-yellow-400">{t('cohort.exit_criteria', 'Exit Criteria')}</span></div>}
          style={{ borderLeft: '3px solid #faad14' }}
        >
          <div className="flex flex-col gap-2 w-full">
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="exit-type"
                  value="end_of_observation"
                  checked={(exitCriteria?.type || 'end_of_observation') === 'end_of_observation'}
                  onChange={() => onUpdateExitCriteria({ ...exitCriteria, type: 'end_of_observation' })}
                  className="text-emerald-accent"
                />
                <span className="text-xs text-text-muted">{t('cohort.exit_end_obs', 'End of observation period')}</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="exit-type"
                  value="fixed_duration"
                  checked={exitCriteria?.type === 'fixed_duration'}
                  onChange={() => onUpdateExitCriteria({ ...exitCriteria, type: 'fixed_duration' })}
                  className="text-emerald-accent"
                />
                <span className="text-xs text-text-muted">{t('cohort.exit_fixed', 'Fixed duration:')}</span>
                {(exitCriteria?.type === 'fixed_duration') && (
                  <div className="flex items-center gap-1">
                    <NumberInput
                      min={1}
                      value={exitCriteria?.duration_days ?? 365}
                      onChange={v => onUpdateExitCriteria({ ...exitCriteria!, duration_days: v ?? 365 })}
                      className="!w-[80px]"
                    />
                    <span className="text-xs text-text-dim">{t('cohort.days', 'days')}</span>
                  </div>
                )}
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="exit-type"
                  value="event_based"
                  checked={exitCriteria?.type === 'event_based'}
                  onChange={() => onUpdateExitCriteria({ ...exitCriteria, type: 'event_based' })}
                  className="text-emerald-accent"
                />
                <span className="text-xs text-text-muted">{t('cohort.exit_event', 'Event-based (outcome occurrence)')}</span>
              </label>
            </div>

            {/* Event-based: inline criteria selector */}
            {exitCriteria?.type === 'event_based' && (
              <div className="mt-1">
                <span className="text-text-muted text-[11px] block mb-1">
                  {t('cohort.exit_event_desc', 'Define the event that ends cohort membership:')}
                </span>
                {exitCriteria.exit_event && exitCriteria.exit_event.criteria && exitCriteria.exit_event.criteria.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {exitCriteria.exit_event.criteria.map((c, i) => (
                      <Tag
                        key={i}
                        color="orange"
                        closable
                        onClose={() => {
                          const newCriteria = exitCriteria.exit_event!.criteria.filter((_, j) => j !== i);
                          onUpdateExitCriteria({
                            ...exitCriteria,
                            exit_event: { ...exitCriteria.exit_event!, criteria: newCriteria },
                          });
                        }}
                      >
                        {t(`domains.${c.domain}`, c.domain)}: {c.concepts?.length > 0 ? c.concepts[0].concept_name || `${c.concepts.length} concepts` : c.source_codes?.[0] || t(`domains.${c.domain}`, c.domain)}
                      </Tag>
                    ))}
                  </div>
                ) : (
                  <CriteriaPanel
                    cdmName={cdmName}
                    onAddCriterion={(criterion) => {
                      const exitEvent = exitCriteria.exit_event || { operator: 'OR' as const, criteria: [] };
                      onUpdateExitCriteria({
                        ...exitCriteria,
                        exit_event: { ...exitEvent, criteria: [...exitEvent.criteria, criterion] },
                      });
                    }}
                  />
                )}
              </div>
            )}
          </div>
        </Card>
      )}

      {isEmpty && (
        <Empty
          description={t('cohort.empty_canvas', 'Add criteria from the left panel to start building your cohort')}
          className="py-10"
        />
      )}
    </div>
  );
}
