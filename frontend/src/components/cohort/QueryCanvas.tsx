import { useState } from 'react';
import {
  Card, Tag, Button, Select, InputNumber, Space, Typography,
  Tooltip, Switch, Collapse, Empty, Checkbox, Spin,
} from 'antd';
import {
  DeleteOutlined, SwapOutlined,
  CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { conceptApi } from '../../api/client';
import type {
  CohortCriterion, CriteriaGroup, DemographicConstraints,
  TemporalConstraint, OccurrenceConstraint, ValueConstraint,
} from '../../types';

const { Text } = Typography;
const { Option } = Select;

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

interface Props {
  inclusion: CriteriaGroup;
  exclusion: CriteriaGroup;
  demographics: DemographicConstraints;
  cdmName: string;
  onUpdateInclusion: (group: CriteriaGroup) => void;
  onUpdateExclusion: (group: CriteriaGroup) => void;
  onUpdateDemographics: (demo: DemographicConstraints) => void;
}

export default function QueryCanvas({
  inclusion, exclusion, demographics, cdmName,
  onUpdateInclusion, onUpdateExclusion, onUpdateDemographics,
}: Props) {
  const { t } = useTranslation();

  const removeCriterion = (group: 'inclusion' | 'exclusion', id: string) => {
    const setter = group === 'inclusion' ? onUpdateInclusion : onUpdateExclusion;
    const source = group === 'inclusion' ? inclusion : exclusion;
    setter({ ...source, criteria: source.criteria.filter(c => c.id !== id) });
  };

  const updateCriterion = (group: 'inclusion' | 'exclusion', id: string, updates: Partial<CohortCriterion>) => {
    const setter = group === 'inclusion' ? onUpdateInclusion : onUpdateExclusion;
    const source = group === 'inclusion' ? inclusion : exclusion;
    setter({ ...source, criteria: source.criteria.map(c => c.id === id ? { ...c, ...updates } : c) });
  };

  const moveCriterion = (fromGroup: 'inclusion' | 'exclusion', id: string) => {
    const source = fromGroup === 'inclusion' ? inclusion : exclusion;
    const criterion = source.criteria.find(c => c.id === id);
    if (!criterion) return;
    removeCriterion(fromGroup, id);
    const targetGroup = fromGroup === 'inclusion' ? 'exclusion' : 'inclusion';
    const targetSetter = targetGroup === 'inclusion' ? onUpdateInclusion : onUpdateExclusion;
    const target = targetGroup === 'inclusion' ? inclusion : exclusion;
    targetSetter({ ...target, criteria: [...target.criteria, criterion] });
  };

  const toggleOperatorBetween = (group: 'inclusion' | 'exclusion', idx: number) => {
    const setter = group === 'inclusion' ? onUpdateInclusion : onUpdateExclusion;
    const source = group === 'inclusion' ? inclusion : exclusion;
    const criteria = [...source.criteria];
    const current = criteria[idx].operatorWithNext || 'AND';
    criteria[idx] = { ...criteria[idx], operatorWithNext: current === 'AND' ? 'OR' : 'AND' };
    setter({ ...source, criteria });
  };

  const isEmpty = inclusion.criteria.length === 0 && exclusion.criteria.length === 0;

  return (
    <div style={{ height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Demographics */}
      <Card size="small" title={t('cohort.demographics', 'Demographics')}>
        <Space wrap>
          <Space size={4}>
            <Text style={{ fontSize: 12 }}>{t('cohort.age', 'Age')}:</Text>
            <InputNumber
              size="small" min={0} max={120} placeholder="Min"
              value={demographics.age?.min}
              onChange={v => onUpdateDemographics({ ...demographics, age: { ...demographics.age, min: v ?? undefined } })}
              style={{ width: 60 }}
            />
            <Text style={{ fontSize: 12 }}>-</Text>
            <InputNumber
              size="small" min={0} max={120} placeholder="Max"
              value={demographics.age?.max}
              onChange={v => onUpdateDemographics({ ...demographics, age: { ...demographics.age, max: v ?? undefined } })}
              style={{ width: 60 }}
            />
          </Space>
          <Space size={4}>
            <Text style={{ fontSize: 12 }}>{t('cohort.gender', 'Gender')}:</Text>
            <Select
              size="small" mode="multiple" placeholder="All"
              value={demographics.gender || []}
              onChange={v => onUpdateDemographics({ ...demographics, gender: v.length > 0 ? v : undefined })}
              style={{ minWidth: 120 }}
            >
              <Option value={8507}>Male (8507)</Option>
              <Option value={8532}>Female (8532)</Option>
            </Select>
          </Space>
        </Space>
      </Card>

      {/* Inclusion criteria */}
      <CriteriaListCard
        title={t('cohort.inclusion', 'Inclusion Criteria')}
        color="#2bc459"
        icon={<CheckCircleOutlined />}
        criteria={inclusion.criteria}
        groupKey="inclusion"
        cdmName={cdmName}
        onRemove={(id) => removeCriterion('inclusion', id)}
        onUpdate={(id, updates) => updateCriterion('inclusion', id, updates)}
        onMove={(id) => moveCriterion('inclusion', id)}
        onToggleOperator={(idx) => toggleOperatorBetween('inclusion', idx)}
        sameVisit={inclusion.sameVisit}
        onToggleSameVisit={() => onUpdateInclusion({ ...inclusion, sameVisit: !inclusion.sameVisit })}
      />

      {/* Logic summary */}
      {inclusion.criteria.length > 1 && (
        <LogicSummary criteria={inclusion.criteria} sameVisit={inclusion.sameVisit} />
      )}

      {/* Exclusion criteria */}
      <CriteriaListCard
        title={t('cohort.exclusion', 'Exclusion Criteria')}
        color="#ff4d4f"
        icon={<CloseCircleOutlined />}
        criteria={exclusion.criteria}
        groupKey="exclusion"
        cdmName={cdmName}
        onRemove={(id) => removeCriterion('exclusion', id)}
        onUpdate={(id, updates) => updateCriterion('exclusion', id, updates)}
        onMove={(id) => moveCriterion('exclusion', id)}
        onToggleOperator={(idx) => toggleOperatorBetween('exclusion', idx)}
      />

      {isEmpty && (
        <Empty
          description={t('cohort.empty_canvas', 'Add criteria from the left panel to start building your cohort')}
          style={{ padding: 40 }}
        />
      )}
    </div>
  );
}

// ──── Criteria List Card ────

function CriteriaListCard({
  title, color, icon, criteria, groupKey, cdmName,
  onRemove, onUpdate, onMove, onToggleOperator,
  sameVisit, onToggleSameVisit,
}: {
  title: string;
  color: string;
  icon: React.ReactNode;
  criteria: CohortCriterion[];
  groupKey: 'inclusion' | 'exclusion';
  cdmName: string;
  onRemove: (id: string) => void;
  onUpdate: (id: string, updates: Partial<CohortCriterion>) => void;
  onMove: (id: string) => void;
  onToggleOperator: (idx: number) => void;
  sameVisit?: boolean;
  onToggleSameVisit?: () => void;
}) {
  const { t } = useTranslation();
  if (criteria.length === 0) return null;

  return (
    <Card
      size="small"
      title={<Space>{icon}<span style={{ color }}>{title}</span></Space>}
      extra={onToggleSameVisit && criteria.length > 1 ? (
        <Checkbox checked={sameVisit} onChange={onToggleSameVisit} style={{ fontSize: 11 }}>
          {t('cohort.same_visit', 'Same visit')}
        </Checkbox>
      ) : null}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {criteria.map((criterion, idx) => (
          <div key={criterion.id}>
            {/* Operator between criteria — clickable to toggle */}
            {idx > 0 && (
              <div style={{ textAlign: 'center', padding: '2px 0' }}>
                <Tag
                  style={{ cursor: 'pointer', fontSize: 11, fontWeight: 'bold' }}
                  color={(criteria[idx - 1].operatorWithNext || 'AND') === 'AND' ? 'blue' : 'orange'}
                  onClick={() => onToggleOperator(idx - 1)}
                >
                  {criteria[idx - 1].operatorWithNext || 'AND'} <SwapOutlined />
                </Tag>
              </div>
            )}
            <CriterionCard
              criterion={criterion}
              groupKey={groupKey}
              cdmName={cdmName}
              onRemove={() => onRemove(criterion.id)}
              onUpdate={(updates) => onUpdate(criterion.id, updates)}
              onMove={() => onMove(criterion.id)}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

// ──── Single Criterion Card ────

function CriterionCard({
  criterion, groupKey, cdmName, onRemove, onUpdate, onMove,
}: {
  criterion: CohortCriterion;
  groupKey: string;
  cdmName: string;
  onRemove: () => void;
  onUpdate: (updates: Partial<CohortCriterion>) => void;
  onMove: () => void;
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
      // Deduplicate by concept_id
      const seen = new Set(criterion.concepts.map(c => c.concept_id));
      const unique = allDescs.filter(d => { if (seen.has(d.concept_id)) return false; seen.add(d.concept_id); return true; });
      setDescendants(unique);
      setDescendantsLoaded(true);
      setDescendantsLoading(false);
    });
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

          {/* Included concepts (collapsible, loads descendants on expand) */}
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

          {/* Constraint controls */}
          <Collapse ghost size="small" items={[{
            key: 'constraints',
            label: <Text style={{ fontSize: 11 }}>{t('cohort.constraints', 'Constraints')}</Text>,
            children: (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
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

                {/* Temporal */}
                <Space size={4} wrap>
                  <Text style={{ fontSize: 11 }}>{t('cohort.temporal', 'Time')}:</Text>
                  <Select
                    size="small"
                    value={criterion.temporal.type}
                    onChange={v => onUpdate({ temporal: { ...criterion.temporal, type: v as TemporalConstraint['type'] } })}
                    style={{ width: 140 }}
                  >
                    <Option value="any_time">{t('cohort.any_time', 'Any time')}</Option>
                    <Option value="absolute_window">{t('cohort.absolute_window', 'Date window')}</Option>
                    <Option value="within_days">{t('cohort.within_days', 'Within N days')}</Option>
                  </Select>
                  {criterion.temporal.type === 'within_days' && (
                    <>
                      <InputNumber size="small" min={0} placeholder={t('cohort.days_before', 'Days before')}
                        value={criterion.temporal.days_before}
                        onChange={v => onUpdate({ temporal: { ...criterion.temporal, days_before: v ?? undefined } })}
                        style={{ width: 80 }}
                      />
                      <InputNumber size="small" min={0} placeholder={t('cohort.days_after', 'Days after')}
                        value={criterion.temporal.days_after}
                        onChange={v => onUpdate({ temporal: { ...criterion.temporal, days_after: v ?? undefined } })}
                        style={{ width: 80 }}
                      />
                    </>
                  )}
                  {criterion.temporal.type === 'absolute_window' && (
                    <>
                      <input type="date" value={criterion.temporal.date_from || ''}
                        onChange={e => onUpdate({ temporal: { ...criterion.temporal, date_from: e.target.value || undefined } })}
                        style={{ fontSize: 11 }}
                      />
                      <input type="date" value={criterion.temporal.date_to || ''}
                        onChange={e => onUpdate({ temporal: { ...criterion.temporal, date_to: e.target.value || undefined } })}
                        style={{ fontSize: 11 }}
                      />
                    </>
                  )}
                </Space>

                {/* Occurrence */}
                <Space size={4}>
                  <Text style={{ fontSize: 11 }}>{t('cohort.frequency', 'Frequency')}:</Text>
                  <Select size="small" value={criterion.occurrence.type}
                    onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, type: v as OccurrenceConstraint['type'] } })}
                    style={{ width: 100 }}
                  >
                    <Option value="any">{t('cohort.any', 'Any')}</Option>
                    <Option value="at_least">{t('cohort.at_least', '≥')}</Option>
                    <Option value="exactly">{t('cohort.exactly', '=')}</Option>
                    <Option value="at_most">{t('cohort.at_most', '≤')}</Option>
                  </Select>
                  {criterion.occurrence.type !== 'any' && (
                    <InputNumber size="small" min={1} value={criterion.occurrence.count}
                      onChange={v => onUpdate({ occurrence: { ...criterion.occurrence, count: v ?? 1 } })}
                      style={{ width: 60 }}
                    />
                  )}
                </Space>

                {/* Value constraint (for Measurement) */}
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
          <Tooltip title={groupKey === 'inclusion'
            ? t('cohort.move_to_exclusion', 'Move to exclusion')
            : t('cohort.move_to_inclusion', 'Move to inclusion')}>
            <Button size="small" icon={<SwapOutlined />} onClick={onMove} />
          </Tooltip>
          <Tooltip title={t('common.delete', 'Delete')}>
            <Button size="small" danger icon={<DeleteOutlined />} onClick={onRemove} />
          </Tooltip>
        </Space>
      </div>
    </Card>
  );
}

// ──── Logic Summary ────

function LogicSummary({ criteria, sameVisit }: { criteria: CohortCriterion[]; sameVisit?: boolean }) {
  if (criteria.length < 2) return null;

  const criterionLabel = (c: CohortCriterion) => {
    let items: string[] = [];
    if (c.concepts.length > 0) items.push(...c.concepts.map(con => con.concept_name));
    if (c.source_codes && c.source_codes.length > 0) items.push(...c.source_codes);
    if (items.length === 0) return c.domain;
    if (items.length === 1) return items[0];
    return `(${items.join(' OR ')})`;
  };

  // Group by OR-consecutive
  const groups: string[][] = [[]];
  criteria.forEach((c, i) => {
    groups[groups.length - 1].push(criterionLabel(c));
    if (i < criteria.length - 1) {
      const op = c.operatorWithNext || 'AND';
      if (op === 'AND') groups.push([]);
    }
  });

  const parts = groups.map(g => g.length > 1 ? `(${g.join(' OR ')})` : g[0]);
  const formula = parts.join(' AND ');

  return (
    <Card size="small" bodyStyle={{ padding: '8px 12px' }} style={{ background: '#001529', borderRadius: 6 }}>
      <Text style={{ fontSize: 13, fontFamily: 'monospace', color: '#2bc459', fontWeight: 500 }}>
        {formula}
        {sameVisit && <Tag color="purple" style={{ marginLeft: 8, fontSize: 10 }}>same visit</Tag>}
      </Text>
    </Card>
  );
}
