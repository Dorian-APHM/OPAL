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
import {
  Card, Select, InputNumber, Space, Typography,
  Empty, Radio,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import CriteriaGroupEditor, { denormaliseGroup, normaliseGroup } from './CriteriaGroupEditor';
import type {
  CohortCriterion, CriteriaGroup, DemographicConstraints,
  CohortExitCriteria,
} from '../../types';

const { Text } = Typography;
const { Option } = Select;

interface Props {
  inclusion: CriteriaGroup;
  exclusion: CriteriaGroup;
  demographics: DemographicConstraints;
  exitCriteria?: CohortExitCriteria;
  cdmName: string;
  onUpdateInclusion: (group: CriteriaGroup) => void;
  onUpdateExclusion: (group: CriteriaGroup) => void;
  onUpdateDemographics: (demo: DemographicConstraints) => void;
  onUpdateExitCriteria?: (exit: CohortExitCriteria) => void;
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
  inclusion, exclusion, demographics, exitCriteria, cdmName,
  onUpdateInclusion, onUpdateExclusion, onUpdateDemographics, onUpdateExitCriteria,
}: Props) {
  const { t } = useTranslation();

  // Normalise incoming groups so CriteriaGroupEditor always has children[]
  const normInclusion = normaliseGroup(inclusion);
  const normExclusion = normaliseGroup(exclusion);

  // Gather all criteria across both groups for cross-referencing in temporal constraints
  const allCriteria = [
    ...collectAllCriteria(normInclusion),
    ...collectAllCriteria(normExclusion),
  ];

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

      {/* ════════════════════════════════════════════════════════════
          INCLUSION — now rendered via CriteriaGroupEditor (P0-1)
          ════════════════════════════════════════════════════════════ */}
      {hasInclusion && (
        <div style={{ borderLeft: '3px solid #2bc459', borderRadius: 4 }}>
          <div style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 6 }}>
            <CheckCircleOutlined style={{ color: '#2bc459' }} />
            <Text strong style={{ color: '#2bc459', fontSize: 13 }}>
              {t('cohort.inclusion', 'Inclusion Criteria')}
            </Text>
          </div>
          <CriteriaGroupEditor
            group={normInclusion}
            depth={0}
            groupKey="inclusion"
            cdmName={cdmName}
            allCriteria={allCriteria}
            onChange={handleInclusionChange}
          />
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════
          EXCLUSION — same treatment
          ════════════════════════════════════════════════════════════ */}
      {hasExclusion && (
        <div style={{ borderLeft: '3px solid #ff4d4f', borderRadius: 4 }}>
          <div style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 6 }}>
            <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
            <Text strong style={{ color: '#ff4d4f', fontSize: 13 }}>
              {t('cohort.exclusion', 'Exclusion Criteria')}
            </Text>
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
          title={<Space><ClockCircleOutlined /><span style={{ color: '#faad14' }}>{t('cohort.exit_criteria', 'Exit Criteria')}</span></Space>}
          style={{ borderLeft: '3px solid #faad14' }}
        >
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Radio.Group
              value={exitCriteria?.type || 'end_of_observation'}
              onChange={e => onUpdateExitCriteria({ ...exitCriteria, type: e.target.value })}
            >
              <Space direction="vertical" size={4}>
                <Radio value="end_of_observation">
                  <Text style={{ fontSize: 12 }}>{t('cohort.exit_end_obs', 'End of observation period')}</Text>
                </Radio>
                <Radio value="fixed_duration">
                  <Space size={4}>
                    <Text style={{ fontSize: 12 }}>{t('cohort.exit_fixed', 'Fixed duration:')}</Text>
                    {(exitCriteria?.type === 'fixed_duration') && (
                      <InputNumber
                        size="small"
                        min={1}
                        value={exitCriteria?.duration_days ?? 365}
                        onChange={v => onUpdateExitCriteria({ ...exitCriteria!, duration_days: v ?? 365 })}
                        style={{ width: 80 }}
                        addonAfter={t('cohort.days', 'days')}
                      />
                    )}
                  </Space>
                </Radio>
                <Radio value="event_based">
                  <Text style={{ fontSize: 12 }}>{t('cohort.exit_event', 'Event-based (outcome occurrence)')}</Text>
                </Radio>
              </Space>
            </Radio.Group>
          </Space>
        </Card>
      )}

      {isEmpty && (
        <Empty
          description={t('cohort.empty_canvas', 'Add criteria from the left panel to start building your cohort')}
          style={{ padding: 40 }}
        />
      )}
    </div>
  );
}
