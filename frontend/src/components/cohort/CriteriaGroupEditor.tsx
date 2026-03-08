/**
 * CriteriaGroupEditor — Recursive component for nested criteria groups.
 *
 * Renders an interactive tree of criteria and sub-groups, each with their own
 * AND/OR operator.  Supports up to MAX_DEPTH levels of nesting.
 *
 * Visual cues:
 *  - Left border color alternates by depth (AND=blue, OR=orange)
 *  - Indentation increases with depth
 *  - Operator badges are clickable to toggle AND ⇄ OR
 */
import { useState } from 'react';
import {
  Card, Tag, Button, Space, Typography, Tooltip, Collapse, Switch,
  Select, InputNumber, Checkbox, Spin, Popconfirm,
} from 'antd';
import {
  DeleteOutlined, SwapOutlined, PlusOutlined,
  GroupOutlined, ArrowDownOutlined, ArrowUpOutlined,
  StarOutlined, StarFilled,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { conceptApi } from '../../api/client';
import type {
  CohortCriterion, CriteriaGroup, CriteriaNode,
  TemporalConstraint, TemporalRelation, OccurrenceConstraint, ValueConstraint,
} from '../../types';

const { Text } = Typography;
const { Option } = Select;

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

// ─────────────────────────────────────────────────────────────────
//  Helper: convert between flat criteria[] and ordered children[]
// ─────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────
//  Main component
// ─────────────────────────────────────────────────────────────────

interface GroupEditorProps {
  group: CriteriaGroup;
  depth: number;
  groupKey: 'inclusion' | 'exclusion';
  cdmName: string;
  /** ID of the criterion designated as the initial/index event */
  initialEventId?: string;
  /** Callback to set/unset a criterion as the initial event */
  onSetInitialEvent?: (criterionId: string | undefined) => void;
  /** Every criterion across all groups — used for temporal references */
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

  // ── mutations ──

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

  // ── render ──

  if (children.length === 0 && !isRoot) return null;

  return (
    <Card
      size="small"
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: depth === 0 ? undefined : 'rgba(255,255,255,0.02)',
        marginBottom: depth > 0 ? 4 : 0,
      }}
      title={
        <Space size={8}>
          {!isRoot && <GroupOutlined style={{ color: borderColor }} />}
          <Tag
            color={normalised.operator === 'AND' ? 'blue' : 'orange'}
            style={{ cursor: 'pointer', fontWeight: 'bold', fontSize: 12 }}
            onClick={toggleOperator}
          >
            {normalised.operator} <SwapOutlined style={{ fontSize: 10 }} />
          </Tag>
          {isRoot && (
            <Text style={{ fontSize: 12, color: borderColor }}>
              {groupKey === 'inclusion'
                ? t('cohort.inclusion', 'Inclusion Criteria')
                : t('cohort.exclusion', 'Exclusion Criteria')}
            </Text>
          )}
          {!isRoot && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {t('cohort.sub_group', 'Sub-group')} (depth {depth})
            </Text>
          )}
        </Space>
      }
      extra={
        <Space size={4}>
          {isRoot && children.length > 1 && (
            <Checkbox
              checked={normalised.sameVisit}
              onChange={() => onChange({ ...normalised, sameVisit: !normalised.sameVisit })}
              style={{ fontSize: 11 }}
            >
              {t('cohort.same_visit', 'Same visit')}
            </Checkbox>
          )}
          {depth < MAX_DEPTH && (
            <Tooltip title={t('cohort.add_sub_group', 'Add sub-group')}>
              <Button size="small" icon={<GroupOutlined />} onClick={addSubGroup}>
                {t('cohort.sub_group', 'Sub-group')}
              </Button>
            </Tooltip>
          )}
          {!isRoot && onRemoveGroup && (
            <Popconfirm
              title={t('cohort.remove_group_confirm', 'Remove this entire group?')}
              onConfirm={onRemoveGroup}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {children.map((node, idx) => (
          <div key={idx}>
            {/* Operator badge between siblings */}
            {idx > 0 && (
              <div style={{ textAlign: 'center', padding: '2px 0' }}>
                <Tag
                  color={normalised.operator === 'AND' ? 'blue' : 'orange'}
                  style={{ fontSize: 11, fontWeight: 'bold', cursor: 'pointer' }}
                  onClick={toggleOperator}
                >
                  {normalised.operator}
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
          <Text type="secondary" style={{ fontSize: 12, padding: 12, textAlign: 'center' }}>
            {t('cohort.empty_group', 'Drag criteria here or add a sub-group')}
          </Text>
        )}
      </div>

      {/* Logic formula summary at root level */}
      {isRoot && children.length > 1 && (
        <div style={{ marginTop: 8, padding: '6px 10px', background: '#001529', borderRadius: 6 }}>
          <Text style={{ fontSize: 13, fontFamily: 'monospace', color: '#2bc459', fontWeight: 500 }}>
            {buildFormula(normalised)}
            {normalised.sameVisit && (
              <Tag color="purple" style={{ marginLeft: 8, fontSize: 10 }}>same visit</Tag>
            )}
          </Text>
        </div>
      )}
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────
//  Criterion card with temporal relation UI
// ─────────────────────────────────────────────────────────────────

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
      style={{ borderLeft: `3px solid ${domainColor}`, background: '#001529', color: '#ffffffd9' }}
      bodyStyle={{ padding: 8 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          {/* Domain & concepts */}
          <Space size={4} style={{ marginBottom: 4 }} wrap>
            <Tag color={domainColor}>{criterion.domain}</Tag>
            {isInitialEvent && (
              <Tag color="gold" style={{ fontSize: 10 }}>
                <StarFilled style={{ fontSize: 9 }} /> Index
              </Tag>
            )}
            {criterion.concepts.length > 1 ? (
              <Tag>{criterion.concepts.length} concepts</Tag>
            ) : criterion.concepts.length === 1 ? (
              <Tooltip title={`${criterion.concepts[0].concept_code} · ${criterion.concepts[0].vocabulary_id}`}>
                <Tag>{criterion.concepts[0].concept_name}</Tag>
              </Tooltip>
            ) : criterion.source_codes && criterion.source_codes.length > 0 ? (
              criterion.source_codes.map(code => (
                <Tag key={code} color="orange">{code}</Tag>
              ))
            ) : (
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('cohort.any_concept', 'Any concept in domain')}
              </Text>
            )}
          </Space>

          {/* Descendants (collapsible) */}
          {criterion.concepts.length > 0 && criterion.include_descendants && (
            <Collapse ghost size="small" onChange={(keys) => { if (keys.length > 0) loadDescendants(); }} items={[{
              key: 'descendants',
              label: <Text style={{ fontSize: 11 }}>{t('cohort.included_concepts', 'Included concepts')} {descendantsLoaded ? `(${criterion.concepts.length} + ${descendants.length} descendants)` : ''}</Text>,
              children: descendantsLoading ? (
                <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /></div>
              ) : (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  <Space size={[4, 4]} wrap>
                    {criterion.concepts.map(c => (
                      <Tooltip key={c.concept_id} title={`${c.concept_code} · ${c.vocabulary_id}`}>
                        <Tag color="blue" style={{ fontSize: 11 }}>{c.concept_name}</Tag>
                      </Tooltip>
                    ))}
                    {descendants.map(d => (
                      <Tooltip key={d.concept_id} title={`${d.concept_code} · ${d.vocabulary_id}`}>
                        <Tag style={{ fontSize: 11, opacity: 0.7 }}>{d.concept_name}</Tag>
                      </Tooltip>
                    ))}
                  </Space>
                </div>
              ),
            }]} />
          )}

          {/* Constraints */}
          <Collapse ghost size="small" items={[{
            key: 'constraints',
            label: <ConstraintSummary criterion={criterion} />,
            children: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {/* Include descendants */}
                <Space size={4}>
                  <Switch
                    size="small"
                    checked={criterion.include_descendants}
                    onChange={v => onUpdate({ include_descendants: v })}
                  />
                  <Text style={{ fontSize: 11 }}>
                    {t('cohort.include_descendants', 'Include descendants')}
                  </Text>
                </Space>

                {/* ════════════════════════════════════════════════════
                    TEMPORAL CONSTRAINTS — enhanced with relations
                    ════════════════════════════════════════════════════ */}
                <TemporalEditor
                  temporal={criterion.temporal}
                  criterionId={criterion.id}
                  allCriteria={allCriteria}
                  hasCircularRef={hasCircularRef}
                  onChange={temporal => onUpdate({ temporal })}
                />

                {/* Occurrence */}
                <Space size={4}>
                  <Text style={{ fontSize: 11 }}>{t('cohort.frequency', 'Frequency')}:</Text>
                  <Select size="small" value={criterion.occurrence.type}
                    onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, type: v as OccurrenceConstraint['type'] } })}
                    style={{ width: 100 }}
                  >
                    <Option value="any">{t('cohort.any', 'Any')}</Option>
                    <Option value="at_least">≥</Option>
                    <Option value="exactly">=</Option>
                    <Option value="at_most">≤</Option>
                  </Select>
                  {criterion.occurrence.type !== 'any' && (
                    <InputNumber size="small" min={1} value={criterion.occurrence.count}
                      onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, count: v ?? 1 } })}
                      style={{ width: 60 }}
                    />
                  )}
                </Space>

                {/* Value constraint (Measurement) */}
                {criterion.domain === 'Measurement' && (
                  <Space size={4}>
                    <Text style={{ fontSize: 11 }}>{t('cohort.value', 'Value')}:</Text>
                    <Select size="small" value={criterion.value?.operator || undefined}
                      onChange={v => onUpdate({ value: v ? { operator: v as ValueConstraint['operator'], value: criterion.value?.value ?? 0 } : undefined })}
                      allowClear placeholder="—" style={{ width: 80 }}
                    >
                      <Option value=">">{'>'}</Option>
                      <Option value="<">{'<'}</Option>
                      <Option value=">=">{'>='}</Option>
                      <Option value="<=">{'<='}</Option>
                      <Option value="=">=</Option>
                      <Option value="between">Between</Option>
                    </Select>
                    {criterion.value?.operator && (
                      <InputNumber size="small" value={criterion.value.value}
                        onChange={v => onUpdate({ value: { ...criterion.value!, value: v ?? 0 } })}
                        style={{ width: 70 }}
                      />
                    )}
                    {criterion.value?.operator === 'between' && (
                      <InputNumber size="small" value={criterion.value.value_high}
                        onChange={v => onUpdate({ value: { ...criterion.value!, value_high: v ?? undefined } })}
                        style={{ width: 70 }} placeholder="Max"
                      />
                    )}
                  </Space>
                )}
              </Space>
            ),
          }]} />
        </div>

        {/* Actions */}
        <Space direction="vertical" size={2}>
          {onToggleInitialEvent && groupKey === 'inclusion' && (
            <Tooltip title={isInitialEvent ? t('cohort.unset_index', 'Unset as index event') : t('cohort.set_index', 'Set as index event (cohort entry)')}>
              <Button
                size="small"
                icon={isInitialEvent ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                onClick={onToggleInitialEvent}
                style={isInitialEvent ? { borderColor: '#faad14' } : undefined}
              />
            </Tooltip>
          )}
          {canMoveUp && (
            <Tooltip title={t('cohort.move_up', 'Move up')}>
              <Button size="small" icon={<ArrowUpOutlined />} onClick={onMoveUp} />
            </Tooltip>
          )}
          {canMoveDown && (
            <Tooltip title={t('cohort.move_down', 'Move down')}>
              <Button size="small" icon={<ArrowDownOutlined />} onClick={onMoveDown} />
            </Tooltip>
          )}
          <Tooltip title={t('common.delete', 'Delete')}>
            <Button size="small" danger icon={<DeleteOutlined />} onClick={onRemove} />
          </Tooltip>
        </Space>
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────
//  TemporalEditor — the P0-2 feature: rich temporal relation UI
// ─────────────────────────────────────────────────────────────────

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
    <div style={{
      padding: 8,
      borderRadius: 6,
      border: temporal.type === 'relative_to_criterion' ? '1px solid #722ed1' : '1px solid #303030',
      background: temporal.type === 'relative_to_criterion' ? 'rgba(114, 46, 209, 0.06)' : undefined,
    }}>
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        <Space size={4} wrap>
          <Text style={{ fontSize: 11 }}>{t('cohort.temporal', 'Time')}:</Text>
          <Select
            size="small"
            value={temporal.type}
            onChange={v => onChange({ ...temporal, type: v as TemporalConstraint['type'], relation: undefined })}
            style={{ width: 180 }}
          >
            <Option value="any_time">{t('cohort.any_time', 'Any time')}</Option>
            <Option value="absolute_window">{t('cohort.absolute_window', 'Date range')}</Option>
            <Option value="within_days">{t('cohort.within_days', 'Within N days of index')}</Option>
            <Option value="relative_to_criterion">
              ⇄ {t('cohort.relative_to', 'Relative to another criterion')}
            </Option>
          </Select>
        </Space>

        {/* ── Absolute window ── */}
        {temporal.type === 'absolute_window' && (
          <Space size={4}>
            <Text style={{ fontSize: 11 }}>{t('cohort.from', 'From')}:</Text>
            <input type="date" value={temporal.date_from || ''}
              onChange={e => onChange({ ...temporal, date_from: e.target.value || undefined })}
              style={{ fontSize: 11 }}
            />
            <Text style={{ fontSize: 11 }}>{t('cohort.to', 'To')}:</Text>
            <input type="date" value={temporal.date_to || ''}
              onChange={e => onChange({ ...temporal, date_to: e.target.value || undefined })}
              style={{ fontSize: 11 }}
            />
          </Space>
        )}

        {/* ── Within N days ── */}
        {temporal.type === 'within_days' && (
          <Space size={4}>
            <InputNumber size="small" min={0} placeholder="Days before"
              value={temporal.days_before}
              onChange={v => onChange({ ...temporal, days_before: v ?? undefined })}
              style={{ width: 100 }}
              addonBefore="−"
            />
            <InputNumber size="small" min={0} placeholder="Days after"
              value={temporal.days_after}
              onChange={v => onChange({ ...temporal, days_after: v ?? undefined })}
              style={{ width: 100 }}
              addonBefore="+"
            />
            <Text type="secondary" style={{ fontSize: 11 }}>
              {t('cohort.from_index', 'from index event')}
            </Text>
          </Space>
        )}

        {/* ── Relative to criterion (P0-2: full Allen relations) ── */}
        {temporal.type === 'relative_to_criterion' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {/* Row 1: This criterion [relation] [reference criterion] */}
            <Space size={4} wrap>
              <Text style={{ fontSize: 11, fontWeight: 500 }}>
                {t('cohort.this_criterion', 'This criterion')}
              </Text>
              <Select
                size="small"
                value={temporal.relation || 'before'}
                onChange={v => onChange({ ...temporal, relation: v as TemporalRelation })}
                style={{ width: 160 }}
                popupMatchSelectWidth={200}
              >
                {(Object.entries(RELATION_LABELS) as [TemporalRelation, string][]).map(([key, label]) => (
                  <Option key={key} value={key}>{label}</Option>
                ))}
              </Select>
              <Select
                size="small"
                placeholder={t('cohort.select_criterion', 'Select criterion…')}
                value={temporal.reference_criterion_id}
                onChange={v => onChange({ ...temporal, reference_criterion_id: v })}
                style={{ width: 200 }}
              >
                {allCriteria.filter(c => c.id !== criterionId).map(c => (
                  <Option key={c.id} value={c.id}>
                    <Tag color={DOMAIN_COLORS[c.domain] || '#666'} style={{ fontSize: 10 }}>
                      {c.domain}
                    </Tag>
                    {c.concepts.length > 0 ? c.concepts[0].concept_name : (c.source_codes?.[0] || c.domain)}
                  </Option>
                ))}
              </Select>
            </Space>

            {/* Circular reference warning */}
            {isCircular && (
              <Text type="danger" style={{ fontSize: 11 }}>
                ⚠ {t('cohort.circular_ref', 'Circular reference detected — the referenced criterion also points back to this one.')}
              </Text>
            )}

            {/* Row 2: Optional time window */}
            <Space size={4} wrap>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('cohort.within_window', 'within window')} ({t('cohort.optional', 'optional')}):
              </Text>
              <InputNumber size="small" min={0} placeholder="days before"
                value={temporal.days_before}
                onChange={v => onChange({ ...temporal, days_before: v ?? undefined })}
                style={{ width: 110 }}
                addonBefore="−"
                addonAfter={t('cohort.d', 'd')}
              />
              <InputNumber size="small" min={0} placeholder="days after"
                value={temporal.days_after}
                onChange={v => onChange({ ...temporal, days_after: v ?? undefined })}
                style={{ width: 110 }}
                addonBefore="+"
                addonAfter={t('cohort.d', 'd')}
              />
            </Space>

            {/* Row 3: Mini timeline visualisation */}
            <TemporalDiagram
              relation={temporal.relation || 'before'}
              daysBefore={temporal.days_before}
              daysAfter={temporal.days_after}
            />
          </div>
        )}
      </Space>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
//  TemporalDiagram — mini ASCII-like visual of the relation
// ─────────────────────────────────────────────────────────────────

function TemporalDiagram({
  relation, daysBefore, daysAfter,
}: {
  relation: TemporalRelation;
  daysBefore?: number;
  daysAfter?: number;
}) {
  // Visual representation of each relation on a time axis
  const diagrams: Record<TemporalRelation, { a: [number, number]; b: [number, number]; label: string }> = {
    before:        { a: [0, 30], b: [40, 70], label: 'A ▬▬▬  B ▬▬▬' },
    after:         { a: [40, 70], b: [0, 30], label: 'B ▬▬▬  A ▬▬▬' },
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
    ? ` (${daysBefore ? `−${daysBefore}d` : ''}${daysBefore && daysAfter ? ' / ' : ''}${daysAfter ? `+${daysAfter}d` : ''})`
    : '';

  return (
    <div style={{
      padding: '6px 8px',
      background: '#0d1117',
      borderRadius: 4,
      fontFamily: 'monospace',
      fontSize: 11,
      lineHeight: '18px',
    }}>
      {/* Time axis */}
      <div style={{ color: '#484f58', marginBottom: 2 }}>
        {'─'.repeat(12)} time ──▸
      </div>
      {/* Bar A */}
      <div style={{ position: 'relative', height: 18 }}>
        <span style={{ color: '#58a6ff' }}>
          {'·'.repeat(Math.round(d.a[0] / 5))}
          {'█'.repeat(Math.max(1, Math.round((d.a[1] - d.a[0]) / 5)))}
          {'·'.repeat(Math.max(0, Math.round((70 - d.a[1]) / 5)))}
        </span>
        <span style={{ color: '#58a6ff', marginLeft: 8 }}>A (this)</span>
      </div>
      {/* Bar B */}
      <div style={{ position: 'relative', height: 18 }}>
        <span style={{ color: '#f78166' }}>
          {'·'.repeat(Math.round(d.b[0] / 5))}
          {'█'.repeat(Math.max(1, Math.round((d.b[1] - d.b[0]) / 5)))}
          {'·'.repeat(Math.max(0, Math.round((70 - d.b[1]) / 5)))}
        </span>
        <span style={{ color: '#f78166', marginLeft: 8 }}>B (ref)</span>
      </div>
      {/* Description */}
      <div style={{ color: '#8b949e', marginTop: 2 }}>
        {d.label}{windowLabel}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
//  ConstraintSummary — inline summary of active constraints
// ─────────────────────────────────────────────────────────────────

function ConstraintSummary({ criterion }: { criterion: CohortCriterion }) {
  const parts: string[] = [];

  if (criterion.temporal.type !== 'any_time') {
    if (criterion.temporal.type === 'relative_to_criterion') {
      const rel = criterion.temporal.relation || 'before';
      parts.push(`⇄ ${RELATION_LABELS[rel]}`);
    } else if (criterion.temporal.type === 'absolute_window') {
      parts.push('📅 date range');
    } else if (criterion.temporal.type === 'within_days') {
      parts.push(`±${criterion.temporal.days_before || '?'}/${criterion.temporal.days_after || '?'}d`);
    }
  }

  if (criterion.occurrence.type !== 'any') {
    const sym = { at_least: '≥', exactly: '=', at_most: '≤' }[criterion.occurrence.type] || '';
    parts.push(`${sym}${criterion.occurrence.count}×`);
  }

  if (criterion.value?.operator) {
    parts.push(`val ${criterion.value.operator} ${criterion.value.value}`);
  }

  if (!criterion.include_descendants) {
    parts.push('no desc.');
  }

  return (
    <Text style={{ fontSize: 11 }}>
      Constraints{parts.length > 0 ? `: ${parts.join(' · ')}` : ''}
    </Text>
  );
}

// ─────────────────────────────────────────────────────────────────
//  Formula builder — recursive logic summary
// ─────────────────────────────────────────────────────────────────

function buildFormula(group: CriteriaGroup): string {
  const children = group.children ?? [];
  if (children.length === 0) return '∅';

  const parts = children.map(node => {
    if (node.type === 'criterion') {
      return criterionLabel(node.criterion);
    } else {
      const inner = buildFormula(node.group);
      return `(${inner})`;
    }
  });

  return parts.join(` ${group.operator} `);
}

function criterionLabel(c: CohortCriterion): string {
  if (c.concepts.length > 0) {
    const name = c.concepts[0].concept_name;
    return c.concepts.length > 1 ? `${name}+${c.concepts.length - 1}` : name;
  }
  if (c.source_codes && c.source_codes.length > 0) return c.source_codes[0];
  return c.domain;
}
