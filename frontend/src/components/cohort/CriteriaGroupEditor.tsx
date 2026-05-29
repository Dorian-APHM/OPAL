/**
 * CriteriaGroupEditor — Recursive component for nested criteria groups.
 *
 * Renders an interactive tree of criteria and sub-groups, each with their own
 * AND/OR operator.  Supports up to MAX_DEPTH levels of nesting.
 *
 * Visual cues:
 *  - Left border color alternates by depth (AND=blue, OR=orange)
 *  - Indentation increases with depth
 *  - Operator badges are clickable to toggle AND <-> OR
 */
import { useState } from 'react';
import {
  Card, Tag, Button, Tooltip, Collapse, Switch, Select, Checkbox, Spinner,
  NumberInput,
} from '../../components/ui';
import {
  Trash2, ArrowLeftRight, Plus, Layers, ChevronDown, ChevronUp,
  Star,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { conceptApi } from '../../api/client';
import type {
  CohortCriterion, CriteriaGroup, CriteriaNode,
  TemporalConstraint, TemporalRelation, OccurrenceConstraint, ValueConstraint,
} from '../../types';

const MAX_DEPTH = 3;

const DOMAIN_COLORS: Record<string, string> = {
  Condition: '#e74c3c',
  Drug: '#3498db',
  Measurement: '#2ecc71',
  Observation: '#f39c12',
  Procedure: '#9b59b6',
  Visit: '#1abc9c',
  Device: '#e67e22',
  Death: '#7f8c8d',
};

const DOMAIN_TAG_COLORS: Record<string, 'red' | 'blue' | 'green' | 'orange' | 'purple' | 'cyan' | 'default'> = {
  Condition: 'red',
  Drug: 'blue',
  Measurement: 'green',
  Observation: 'orange',
  Procedure: 'purple',
  Visit: 'cyan',
  Device: 'orange',
  Death: 'default',
};

const DEPTH_COLORS = ['#1677ff', '#fa8c16', '#722ed1', '#13c2c2'];

/** Labels for temporal relations */
const RELATION_LABELS: Record<TemporalRelation, string> = {
  before: 'occurs before',
  after: 'occurs after',
  starts_before: 'starts before',
  starts_after: 'starts after',
  ends_before: 'ends before',
  ends_after: 'ends after',
  overlaps: 'overlaps with',
  contains: 'contains',
  during: 'occurs during',
};

// -----------------------------------------------------------------
//  Helper: convert between flat criteria[] and ordered children[]
// -----------------------------------------------------------------

/**
 * Normalise a CriteriaGroup so it always uses the `children` array.
 * If `children` is already populated we trust it; otherwise we convert
 * from the legacy `criteria` + `groups` arrays (criteria first, then groups).
 */
export function normaliseGroup(group: CriteriaGroup): CriteriaGroup {
  if (group.children && group.children.length > 0) return group;
  const children: CriteriaNode[] = [
    ...(group.criteria || []).map(c => ({ type: 'criterion' as const, criterion: c })),
    ...(group.groups || []).map(g => ({ type: 'group' as const, group: normaliseGroup(g) })),
  ];
  return { ...group, children, criteria: group.criteria ?? [], groups: group.groups ?? [] };
}

/**
 * Flatten `children` back to legacy `criteria` + `groups` arrays so the
 * backend (which reads criteria[]) can still consume the payload.
 */
export function denormaliseGroup(group: CriteriaGroup): CriteriaGroup {
  const children = group.children ?? [];
  const criteria = children
    .filter((n): n is Extract<CriteriaNode, { type: 'criterion' }> => n.type === 'criterion')
    .map(n => n.criterion);
  const groups = children
    .filter((n): n is Extract<CriteriaNode, { type: 'group' }> => n.type === 'group')
    .map(n => denormaliseGroup(n.group));
  return { operator: group.operator, criteria, groups: groups.length > 0 ? groups : undefined, sameVisit: group.sameVisit };
}

// -----------------------------------------------------------------
//  Main component
// -----------------------------------------------------------------

interface GroupEditorProps {
  group: CriteriaGroup;
  depth: number;
  groupKey: 'inclusion' | 'exclusion';
  cdmName: string;
  /** ID of the criterion designated as the initial/index event */
  initialEventId?: string;
  /** Callback to set/unset a criterion as the initial event */
  onSetInitialEvent?: (criterionId: string | undefined) => void;
  /** Every criterion across all groups -- used for temporal references */
  allCriteria: CohortCriterion[];
  onChange: (updated: CriteriaGroup) => void;
  onRemoveGroup?: () => void; // available for sub-groups
}

export default function CriteriaGroupEditor({
  group, depth, groupKey, cdmName, allCriteria, onChange, onRemoveGroup,
  initialEventId, onSetInitialEvent,
}: GroupEditorProps) {
  const { t } = useTranslation();
  const normalised = normaliseGroup(group);
  const children = normalised.children ?? [];
  const borderColor = DEPTH_COLORS[depth % DEPTH_COLORS.length];
  const isRoot = depth === 0;

  // -- mutations --

  const setChildren = (next: CriteriaNode[]) => {
    onChange({ ...normalised, children: next });
  };

  const toggleOperator = () => {
    onChange({ ...normalised, operator: normalised.operator === 'AND' ? 'OR' : 'AND' });
  };

  const removeChild = (idx: number) => {
    setChildren(children.filter((_, i) => i !== idx));
  };

  const updateCriterion = (idx: number, updates: Partial<CohortCriterion>) => {
    setChildren(children.map((n, i) => {
      if (i !== idx || n.type !== 'criterion') return n;
      return { type: 'criterion', criterion: { ...n.criterion, ...updates } };
    }));
  };

  const updateSubGroup = (idx: number, updated: CriteriaGroup) => {
    setChildren(children.map((n, i) => {
      if (i !== idx || n.type !== 'group') return n;
      return { type: 'group', group: updated };
    }));
  };

  const addSubGroup = () => {
    const newGroup: CriteriaGroup = {
      operator: normalised.operator === 'AND' ? 'OR' : 'AND',
      criteria: [],
      children: [],
    };
    setChildren([...children, { type: 'group', group: newGroup }]);
  };

  const moveChild = (idx: number, dir: -1 | 1) => {
    const next = [...children];
    const target = idx + dir;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    setChildren(next);
  };

  // Per-pair operator: the badge between child idx-1 and idx reflects the operator
  // linking them, stored as `operatorWithNext` on the PRECEDING criterion (falls back
  // to the group operator). Each badge is independent → mix AND/OR: A AND (B OR C).
  const opBefore = (idx: number): 'AND' | 'OR' => {
    const prev = children[idx - 1];
    return prev?.type === 'criterion'
      ? (prev.criterion.operatorWithNext ?? normalised.operator)
      : normalised.operator;
  };
  const toggleOpBefore = (idx: number) => {
    const prev = children[idx - 1];
    if (!prev || prev.type !== 'criterion') { toggleOperator(); return; } // sub-group: group op
    const next = opBefore(idx) === 'AND' ? 'OR' : 'AND';
    setChildren(children.map((n, i) =>
      i === idx - 1 && n.type === 'criterion'
        ? { type: 'criterion', criterion: { ...n.criterion, operatorWithNext: next } }
        : n,
    ));
  };

  // -- render --

  if (children.length === 0 && !isRoot) return null;

  return (
    <Card
      size="small"
      className={depth > 0 ? 'mb-1' : ''}
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: depth === 0 ? undefined : 'rgba(255,255,255,0.02)',
      }}
      title={
        <div className="flex items-center gap-2">
          {!isRoot && <Layers className="h-4 w-4" style={{ color: borderColor }} />}
          <Tag
            color={normalised.operator === 'AND' ? 'blue' : 'orange'}
            className="cursor-pointer font-bold text-xs"
          >
            <span onClick={toggleOperator} className="flex items-center gap-1">
              {normalised.operator} <ArrowLeftRight className="h-2.5 w-2.5" />
            </span>
          </Tag>
          {isRoot && (
            <span className="text-xs" style={{ color: borderColor }}>
              {groupKey === 'inclusion'
                ? t('cohort.inclusion', 'Inclusion Criteria')
                : t('cohort.exclusion', 'Exclusion Criteria')}
            </span>
          )}
          {!isRoot && (
            <span className="text-text-muted text-[11px]">
              {t('cohort.sub_group', 'Sub-group')} (depth {depth})
            </span>
          )}
        </div>
      }
      extra={
        <div className="flex items-center gap-1">
          {isRoot && children.length > 1 && (
            <Checkbox
              checked={!!normalised.sameVisit}
              onChange={() => onChange({ ...normalised, sameVisit: !normalised.sameVisit })}
            >
              <span className="text-[11px]">{t('cohort.same_visit', 'Same visit')}</span>
            </Checkbox>
          )}
          {!isRoot && onRemoveGroup && (
            <Button
              size="small"
              variant="danger"
              icon={<Trash2 className="h-3.5 w-3.5" />}
              onClick={() => {
                if (window.confirm(t('cohort.remove_group_confirm', 'Remove this entire group?'))) {
                  onRemoveGroup();
                }
              }}
            />
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-1">
        {children.map((node, idx) => (
          <div key={idx}>
            {/* Per-pair operator badge between siblings (independent AND/OR) */}
            {idx > 0 && (
              <div className="text-center py-0.5">
                <Tag
                  color={opBefore(idx) === 'AND' ? 'blue' : 'orange'}
                  className="text-[11px] font-bold cursor-pointer"
                >
                  <span onClick={() => toggleOpBefore(idx)}>{opBefore(idx)}</span>
                </Tag>
              </div>
            )}

            {node.type === 'criterion' ? (
              <CriterionCard
                criterion={node.criterion}
                groupKey={groupKey}
                cdmName={cdmName}
                allCriteria={allCriteria}
                onRemove={() => removeChild(idx)}
                onUpdate={(updates) => updateCriterion(idx, updates)}
                canMoveUp={idx > 0}
                canMoveDown={idx < children.length - 1}
                onMoveUp={() => moveChild(idx, -1)}
                onMoveDown={() => moveChild(idx, 1)}
                isInitialEvent={initialEventId === node.criterion.id}
                onToggleInitialEvent={onSetInitialEvent ? () => {
                  onSetInitialEvent(initialEventId === node.criterion.id ? undefined : node.criterion.id);
                } : undefined}
              />
            ) : (
              <CriteriaGroupEditor
                group={node.group}
                depth={depth + 1}
                groupKey={groupKey}
                cdmName={cdmName}
                allCriteria={allCriteria}
                onChange={(updated) => updateSubGroup(idx, updated)}
                onRemoveGroup={() => removeChild(idx)}
                initialEventId={initialEventId}
                onSetInitialEvent={onSetInitialEvent}
              />
            )}
          </div>
        ))}

        {children.length === 0 && (
          <p className="text-text-muted text-xs p-3 text-center">
            {t('cohort.empty_group', 'Drag criteria here or add a sub-group')}
          </p>
        )}
      </div>

      {/* Logic formula summary at root level */}
      {isRoot && children.length > 1 && (
        <div className="mt-2 px-2.5 py-1.5 bg-deep-base rounded-md">
          <span className="text-[13px] font-mono text-emerald-accent font-medium">
            {buildFormula(normalised)}
            {normalised.sameVisit && (
              <Tag color="purple" className="ml-2 text-[10px]">same visit</Tag>
            )}
          </span>
        </div>
      )}
    </Card>
  );
}

// -----------------------------------------------------------------
//  Criterion card with temporal relation UI
// -----------------------------------------------------------------

function CriterionCard({
  criterion, groupKey, cdmName, allCriteria,
  onRemove, onUpdate, canMoveUp, canMoveDown, onMoveUp, onMoveDown,
  isInitialEvent, onToggleInitialEvent,
}: {
  criterion: CohortCriterion;
  groupKey: string;
  cdmName: string;
  allCriteria: CohortCriterion[];
  onRemove: () => void;
  onUpdate: (updates: Partial<CohortCriterion>) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  isInitialEvent?: boolean;
  onToggleInitialEvent?: () => void;
}) {
  const { t } = useTranslation();
  const domainColor = DOMAIN_COLORS[criterion.domain] || '#666';

  const [descendants, setDescendants] = useState<{ concept_id: number; concept_name: string; concept_code: string; vocabulary_id: string }[]>([]);
  const [descendantsLoading, setDescendantsLoading] = useState(false);
  const [descendantsLoaded, setDescendantsLoaded] = useState(false);

  const loadDescendants = () => {
    if (descendantsLoaded || descendantsLoading || !cdmName) return;
    setDescendantsLoading(true);
    const allDescs: typeof descendants = [];
    const promises = criterion.concepts.map(c =>
      conceptApi.hierarchy(cdmName, c.concept_id)
        .then(r => { allDescs.push(...(r.data.descendants || [])); })
        .catch(() => {})
    );
    Promise.all(promises).then(() => {
      const seen = new Set(criterion.concepts.map(c => c.concept_id));
      const unique = allDescs.filter(d => { if (seen.has(d.concept_id)) return false; seen.add(d.concept_id); return true; });
      setDescendants(unique);
      setDescendantsLoaded(true);
      setDescendantsLoading(false);
    });
  };

  // Detect circular temporal references
  const hasCircularRef = (refId: string | undefined): boolean => {
    if (!refId) return false;
    const ref = allCriteria.find(c => c.id === refId);
    if (!ref) return false;
    if (ref.temporal.type === 'relative_to_criterion' && ref.temporal.reference_criterion_id === criterion.id) return true;
    return false;
  };

  return (
    <Card
      size="small"
      hoverable={false}
      className="bg-deep-base"
      style={{ borderLeft: `3px solid ${domainColor}` }}
    >
      <div className="flex justify-between items-start">
        <div className="flex-1">
          {/* Domain & concepts */}
          <div className="flex flex-wrap items-center gap-1 mb-1">
            <Tag color={DOMAIN_TAG_COLORS[criterion.domain] || 'default'}>{t(`domains.${criterion.domain}`, criterion.domain)}</Tag>
            {isInitialEvent && (
              <Tag color="yellow" className="text-[10px]">
                <Star className="h-2.5 w-2.5 fill-current inline" /> Index
              </Tag>
            )}
            {criterion.concepts.length > 1 ? (
              <Tag>{criterion.concepts.length} concepts</Tag>
            ) : criterion.concepts.length === 1 ? (
              <Tooltip title={`${criterion.concepts[0].concept_code} · ${criterion.concepts[0].vocabulary_id}`}>
                <span><Tag>{criterion.concepts[0].concept_name}</Tag></span>
              </Tooltip>
            ) : criterion.source_codes && criterion.source_codes.length > 0 ? (
              criterion.source_codes.map(code => (
                <Tag key={code} color="orange">{code}</Tag>
              ))
            ) : (
              <span className="text-text-muted text-[11px]">
                {t('cohort.any_concept', 'Any concept in domain')}
              </span>
            )}
          </div>

          {/* Descendants (collapsible) */}
          {criterion.concepts.length > 0 && criterion.include_descendants && (
            <DescendantsCollapse
              criterion={criterion}
              descendants={descendants}
              descendantsLoaded={descendantsLoaded}
              descendantsLoading={descendantsLoading}
              loadDescendants={loadDescendants}
              t={t}
            />
          )}

          {/* Constraints */}
          <Collapse
            items={[{
              key: 'constraints',
              label: <ConstraintSummary criterion={criterion} />,
              children: (
                <div className="flex flex-col gap-2 w-full">
                  {/* Include descendants */}
                  <Switch
                    size="small"
                    checked={criterion.include_descendants}
                    onChange={v => onUpdate({ include_descendants: v })}
                    label={t('cohort.include_descendants', 'Include descendants')}
                  />

                  {/* TEMPORAL CONSTRAINTS */}
                  <TemporalEditor
                    temporal={criterion.temporal}
                    criterionId={criterion.id}
                    allCriteria={allCriteria}
                    hasCircularRef={hasCircularRef}
                    onChange={temporal => onUpdate({ temporal })}
                  />

                  {/* Occurrence */}
                  <div className="flex items-center gap-1">
                    <span className="text-[11px] text-text-muted">{t('cohort.frequency', 'Frequency')}:</span>
                    <Select
                      size="small"
                      value={criterion.occurrence.type}
                      onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, type: v as OccurrenceConstraint['type'] } })}
                      className="w-[100px]"
                      options={[
                        { value: 'any', label: t('cohort.any', 'Any') },
                        { value: 'at_least', label: '\u2265' },
                        { value: 'exactly', label: '=' },
                        { value: 'at_most', label: '\u2264' },
                      ]}
                    />
                    {criterion.occurrence.type !== 'any' && (
                      <NumberInput
                        min={1}
                        value={criterion.occurrence.count}
                        onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, count: v ?? 1 } })}
                        className="!w-[60px]"
                      />
                    )}
                  </div>

                  {/* Value constraint (Measurement) */}
                  {criterion.domain === 'Measurement' && (
                    <div className="flex items-center gap-1">
                      <span className="text-[11px] text-text-muted">{t('cohort.value', 'Value')}:</span>
                      <Select
                        size="small"
                        value={criterion.value?.operator || ''}
                        onChange={v => onUpdate({ value: v ? { operator: v as ValueConstraint['operator'], value: criterion.value?.value ?? 0 } : undefined })}
                        allowClear
                        placeholder="—"
                        className="w-[80px]"
                        options={[
                          { value: '>', label: '>' },
                          { value: '<', label: '<' },
                          { value: '>=', label: '>=' },
                          { value: '<=', label: '<=' },
                          { value: '=', label: '=' },
                          { value: 'between', label: 'Between' },
                        ]}
                      />
                      {criterion.value?.operator && (
                        <NumberInput
                          value={criterion.value.value}
                          onChange={v => onUpdate({ value: { ...criterion.value!, value: v ?? 0 } })}
                          className="!w-[70px]"
                        />
                      )}
                      {criterion.value?.operator === 'between' && (
                        <NumberInput
                          value={criterion.value.value_high}
                          onChange={v => onUpdate({ value: { ...criterion.value!, value_high: v ?? undefined } })}
                          className="!w-[70px]"
                          placeholder="Max"
                        />
                      )}
                    </div>
                  )}
                </div>
              ),
            }]}
          />
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-0.5 ml-2">
          {onToggleInitialEvent && groupKey === 'inclusion' && (
            <Tooltip title={isInitialEvent ? t('cohort.unset_index', 'Unset as index event') : t('cohort.set_index', 'Set as index event (cohort entry)')}>
              <span>
                <Button
                  size="small"
                  icon={<Star className={`h-3.5 w-3.5 ${isInitialEvent ? 'text-yellow-400 fill-yellow-400' : ''}`} />}
                  onClick={onToggleInitialEvent}
                  className={isInitialEvent ? '!border-yellow-400' : ''}
                />
              </span>
            </Tooltip>
          )}
          {canMoveUp && (
            <Tooltip title={t('cohort.move_up', 'Move up')}>
              <span><Button size="small" icon={<ChevronUp className="h-3.5 w-3.5" />} onClick={onMoveUp} /></span>
            </Tooltip>
          )}
          {canMoveDown && (
            <Tooltip title={t('cohort.move_down', 'Move down')}>
              <span><Button size="small" icon={<ChevronDown className="h-3.5 w-3.5" />} onClick={onMoveDown} /></span>
            </Tooltip>
          )}
          <Tooltip title={t('common.delete', 'Delete')}>
            <span><Button size="small" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={onRemove} /></span>
          </Tooltip>
        </div>
      </div>
    </Card>
  );
}

// -----------------------------------------------------------------
//  DescendantsCollapse — shows included concepts
// -----------------------------------------------------------------

function DescendantsCollapse({
  criterion, descendants, descendantsLoaded, descendantsLoading, loadDescendants, t,
}: {
  criterion: CohortCriterion;
  descendants: { concept_id: number; concept_name: string; concept_code: string; vocabulary_id: string }[];
  descendantsLoaded: boolean;
  descendantsLoading: boolean;
  loadDescendants: () => void;
  t: any;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mb-1">
      <button
        className="text-[11px] text-text-muted hover:text-text-bright cursor-pointer bg-transparent border-none p-0 underline"
        onClick={() => { setOpen(!open); if (!open) loadDescendants(); }}
      >
        {t('cohort.included_concepts', 'Included concepts')} {descendantsLoaded ? `(${criterion.concepts.length} + ${descendants.length} descendants)` : ''}
      </button>
      {open && (
        descendantsLoading ? (
          <div className="text-center p-2"><Spinner size="small" /></div>
        ) : (
          <div className="max-h-[200px] overflow-auto mt-1">
            <div className="flex flex-wrap gap-1">
              {criterion.concepts.map(c => (
                <Tooltip key={c.concept_id} title={`${c.concept_code} · ${c.vocabulary_id}`}>
                  <span><Tag color="blue" className="text-[11px]">{c.concept_name}</Tag></span>
                </Tooltip>
              ))}
              {descendants.map(d => (
                <Tooltip key={d.concept_id} title={`${d.concept_code} · ${d.vocabulary_id}`}>
                  <span><Tag className="text-[11px] opacity-70">{d.concept_name}</Tag></span>
                </Tooltip>
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}

// -----------------------------------------------------------------
//  TemporalEditor — rich temporal relation UI
// -----------------------------------------------------------------

function TemporalEditor({
  temporal, criterionId, allCriteria, hasCircularRef, onChange,
}: {
  temporal: TemporalConstraint;
  criterionId: string;
  allCriteria: CohortCriterion[];
  hasCircularRef: (refId: string | undefined) => boolean;
  onChange: (t: TemporalConstraint) => void;
}) {
  const { t } = useTranslation();

  const isCircular = temporal.type === 'relative_to_criterion'
    && hasCircularRef(temporal.reference_criterion_id);

  return (
    <div className={`p-2 rounded-md border ${
      temporal.type === 'relative_to_criterion'
        ? 'border-purple-500/50 bg-purple-500/5'
        : 'border-glass-border'
    }`}>
      <div className="flex flex-col gap-1.5 w-full">
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-text-muted">{t('cohort.temporal', 'Time')}:</span>
          <Select
            size="small"
            value={temporal.type}
            onChange={v => onChange({ ...temporal, type: v as TemporalConstraint['type'], relation: undefined })}
            className="w-[180px]"
            options={[
              { value: 'any_time', label: t('cohort.any_time', 'Any time') },
              { value: 'absolute_window', label: t('cohort.absolute_window', 'Date range') },
              { value: 'within_days', label: t('cohort.within_days', 'Within N days of index') },
              { value: 'relative_to_criterion', label: `\u21C4 ${t('cohort.relative_to', 'Relative to another criterion')}` },
            ]}
          />
        </div>

        {/* Absolute window */}
        {temporal.type === 'absolute_window' && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] text-text-muted">{t('cohort.from', 'From')}:</span>
            <input type="date" value={temporal.date_from || ''}
              onChange={e => onChange({ ...temporal, date_from: e.target.value || undefined })}
              className="text-[11px] bg-deep-base border border-glass-border rounded px-1 py-0.5 text-text-bright"
            />
            <span className="text-[11px] text-text-muted">{t('cohort.to', 'To')}:</span>
            <input type="date" value={temporal.date_to || ''}
              onChange={e => onChange({ ...temporal, date_to: e.target.value || undefined })}
              className="text-[11px] bg-deep-base border border-glass-border rounded px-1 py-0.5 text-text-bright"
            />
          </div>
        )}

        {/* Within N days */}
        {temporal.type === 'within_days' && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] text-text-muted">-</span>
            <NumberInput
              min={0}
              placeholder="Days before"
              value={temporal.days_before}
              onChange={v => onChange({ ...temporal, days_before: v ?? undefined })}
              className="!w-[100px]"
            />
            <span className="text-[11px] text-text-muted">+</span>
            <NumberInput
              min={0}
              placeholder="Days after"
              value={temporal.days_after}
              onChange={v => onChange({ ...temporal, days_after: v ?? undefined })}
              className="!w-[100px]"
            />
            <span className="text-text-muted text-[11px]">
              {t('cohort.from_index', 'from index event')}
            </span>
          </div>
        )}

        {/* Relative to criterion (full Allen relations) */}
        {temporal.type === 'relative_to_criterion' && (
          <div className="flex flex-col gap-1.5">
            {/* Row 1: This criterion [relation] [reference criterion] */}
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[11px] font-medium text-text-bright">
                {t('cohort.this_criterion', 'This criterion')}
              </span>
              <Select
                size="small"
                value={temporal.relation || 'before'}
                onChange={v => onChange({ ...temporal, relation: v as TemporalRelation })}
                className="w-[160px]"
                options={Object.entries(RELATION_LABELS).map(([key, label]) => ({
                  value: key,
                  label,
                }))}
              />
              <Select
                size="small"
                placeholder={t('cohort.select_criterion', 'Select criterion...')}
                value={temporal.reference_criterion_id || ''}
                onChange={v => onChange({ ...temporal, reference_criterion_id: v })}
                className="w-[200px]"
                options={allCriteria.filter(c => c.id !== criterionId).map(c => ({
                  value: c.id,
                  label: `${t(`domains.${c.domain}`, c.domain)}: ${c.concepts.length > 0 ? c.concepts[0].concept_name : (c.source_codes?.[0] || t(`domains.${c.domain}`, c.domain))}`,
                }))}
              />
            </div>

            {/* Circular reference warning */}
            {isCircular && (
              <span className="text-red-400 text-[11px]">
                Warning: {t('cohort.circular_ref', 'Circular reference detected -- the referenced criterion also points back to this one.')}
              </span>
            )}

            {/* Row 2: Optional time window */}
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-text-muted text-[11px]">
                {t('cohort.within_window', 'within window')} ({t('cohort.optional', 'optional')}):
              </span>
              <span className="text-[11px] text-text-muted">-</span>
              <NumberInput
                min={0}
                placeholder="days before"
                value={temporal.days_before}
                onChange={v => onChange({ ...temporal, days_before: v ?? undefined })}
                className="!w-[110px]"
              />
              <span className="text-[11px] text-text-muted">+</span>
              <NumberInput
                min={0}
                placeholder="days after"
                value={temporal.days_after}
                onChange={v => onChange({ ...temporal, days_after: v ?? undefined })}
                className="!w-[110px]"
              />
            </div>

            {/* Row 3: Mini timeline visualisation */}
            <TemporalDiagram
              relation={temporal.relation || 'before'}
              daysBefore={temporal.days_before}
              daysAfter={temporal.days_after}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------
//  TemporalDiagram — mini ASCII-like visual of the relation
// -----------------------------------------------------------------

function TemporalDiagram({
  relation, daysBefore, daysAfter,
}: {
  relation: TemporalRelation;
  daysBefore?: number;
  daysAfter?: number;
}) {
  // Visual representation of each relation on a time axis
  const diagrams: Record<TemporalRelation, { a: [number, number]; b: [number, number]; label: string }> = {
    before:        { a: [0, 30], b: [40, 70], label: 'A ---  B ---' },
    after:         { a: [40, 70], b: [0, 30], label: 'B ---  A ---' },
    starts_before: { a: [0, 50], b: [20, 60], label: 'A starts first' },
    starts_after:  { a: [20, 60], b: [0, 50], label: 'A starts later' },
    ends_before:   { a: [0, 40], b: [10, 60], label: 'A ends first' },
    ends_after:    { a: [10, 60], b: [0, 40], label: 'A ends later' },
    overlaps:      { a: [0, 45], b: [25, 70], label: 'A and B overlap' },
    contains:      { a: [0, 70], b: [15, 55], label: 'A contains B' },
    during:        { a: [15, 55], b: [0, 70], label: 'A during B' },
  };

  const d = diagrams[relation];
  const windowLabel = (daysBefore || daysAfter)
    ? ` (${daysBefore ? `-${daysBefore}d` : ''}${daysBefore && daysAfter ? ' / ' : ''}${daysAfter ? `+${daysAfter}d` : ''})`
    : '';

  return (
    <div className="p-1.5 bg-deep-base rounded font-mono text-[11px] leading-[18px]">
      {/* Time axis */}
      <div className="text-text-dim mb-0.5">
        {'─'.repeat(12)} time ──▸
      </div>
      {/* Bar A */}
      <div className="relative h-[18px]">
        <span className="text-blue-400">
          {'·'.repeat(Math.round(d.a[0] / 5))}
          {'█'.repeat(Math.max(1, Math.round((d.a[1] - d.a[0]) / 5)))}
          {'·'.repeat(Math.max(0, Math.round((70 - d.a[1]) / 5)))}
        </span>
        <span className="text-blue-400 ml-2">A (this)</span>
      </div>
      {/* Bar B */}
      <div className="relative h-[18px]">
        <span className="text-orange-400">
          {'·'.repeat(Math.round(d.b[0] / 5))}
          {'█'.repeat(Math.max(1, Math.round((d.b[1] - d.b[0]) / 5)))}
          {'·'.repeat(Math.max(0, Math.round((70 - d.b[1]) / 5)))}
        </span>
        <span className="text-orange-400 ml-2">B (ref)</span>
      </div>
      {/* Description */}
      <div className="text-text-dim mt-0.5">
        {d.label}{windowLabel}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------
//  ConstraintSummary — inline summary of active constraints
// -----------------------------------------------------------------

function ConstraintSummary({ criterion }: { criterion: CohortCriterion }) {
  const parts: string[] = [];

  if (criterion.temporal.type !== 'any_time') {
    if (criterion.temporal.type === 'relative_to_criterion') {
      const rel = criterion.temporal.relation || 'before';
      parts.push(`\u21C4 ${RELATION_LABELS[rel]}`);
    } else if (criterion.temporal.type === 'absolute_window') {
      parts.push('date range');
    } else if (criterion.temporal.type === 'within_days') {
      parts.push(`\u00B1${criterion.temporal.days_before || '?'}/${criterion.temporal.days_after || '?'}d`);
    }
  }

  if (criterion.occurrence.type !== 'any') {
    const sym = { at_least: '\u2265', exactly: '=', at_most: '\u2264' }[criterion.occurrence.type] || '';
    parts.push(`${sym}${criterion.occurrence.count}\u00D7`);
  }

  if (criterion.value?.operator) {
    parts.push(`val ${criterion.value.operator} ${criterion.value.value}`);
  }

  if (!criterion.include_descendants) {
    parts.push('no desc.');
  }

  return (
    <span className="text-[11px] text-text-muted">
      Constraints{parts.length > 0 ? `: ${parts.join(' · ')}` : ''}
    </span>
  );
}

// -----------------------------------------------------------------
//  Formula builder — recursive logic summary
// -----------------------------------------------------------------

function buildFormula(group: CriteriaGroup): string {
  const children = group.children ?? [];
  if (children.length === 0) return '\u2205';

  const label = (node: CriteriaNode) =>
    node.type === 'criterion' ? criterionLabel(node.criterion) : `(${buildFormula(node.group)})`;

  // Interleave per-pair operators (operatorWithNext on the preceding criterion,
  // falling back to the group operator). OR binds tighter than AND (backend groups
  // OR-runs into UNION, then AND into INTERSECT) \u2192 e.g. "A AND B OR C" = A AND (B OR C).
  let out = label(children[0]);
  for (let i = 1; i < children.length; i++) {
    const prev = children[i - 1];
    const op = prev.type === 'criterion' ? (prev.criterion.operatorWithNext ?? group.operator) : group.operator;
    out += ` ${op} ${label(children[i])}`;
  }
  return out;
}

function criterionLabel(c: CohortCriterion): string {
  if (c.concepts.length > 0) {
    const name = c.concepts[0].concept_name;
    return c.concepts.length > 1 ? `${name}+${c.concepts.length - 1}` : name;
  }
  if (c.source_codes && c.source_codes.length > 0) return c.source_codes[0];
  return c.domain;
}
