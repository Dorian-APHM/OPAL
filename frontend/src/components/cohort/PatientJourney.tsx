import { useState, useEffect, useMemo } from 'react';
import { Modal, Spin, Tag, Typography, Empty, Tooltip, Space, Switch } from 'antd';
import {
  UserOutlined, CalendarOutlined,
  HeartOutlined, MedicineBoxOutlined, ExperimentOutlined,
  EyeOutlined, ToolOutlined, HomeOutlined, UsbOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cohortApi } from '../../api/client';
import type { PatientJourneyEvent, PatientJourneyInfo } from '../../types';

const { Text, Title } = Typography;

/** Color and icon per OMOP domain */
const DOMAIN_STYLE: Record<string, { color: string; icon: React.ReactNode }> = {
  Condition:   { color: '#f5222d', icon: <HeartOutlined /> },
  Drug:        { color: '#1890ff', icon: <MedicineBoxOutlined /> },
  Measurement: { color: '#52c41a', icon: <ExperimentOutlined /> },
  Observation: { color: '#faad14', icon: <EyeOutlined /> },
  Procedure:   { color: '#722ed1', icon: <ToolOutlined /> },
  Visit:       { color: '#13c2c2', icon: <HomeOutlined /> },
  Device:      { color: '#eb2f96', icon: <UsbOutlined /> },
  Death:       { color: '#000000', icon: <CloseCircleOutlined /> },
};

function domainColor(domain: string) {
  return DOMAIN_STYLE[domain]?.color || '#8c8c8c';
}

interface Props {
  cdmName: string;
  personId: number | null;
  open: boolean;
  onClose: () => void;
}

export default function PatientJourney({ cdmName, personId, open, onClose }: Props) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [person, setPerson] = useState<PatientJourneyInfo | null>(null);
  const [events, setEvents] = useState<PatientJourneyEvent[]>([]);
  const [activeDomains, setActiveDomains] = useState<Set<string>>(new Set());
  const [groupByDomain, setGroupByDomain] = useState(false);

  useEffect(() => {
    if (!open || !personId) return;
    setLoading(true);
    cohortApi.patientJourney(cdmName, personId)
      .then(resp => {
        setPerson(resp.data.person);
        setEvents(resp.data.events);
        const domains = new Set(resp.data.events.map(e => e.domain));
        setActiveDomains(domains);
      })
      .catch(() => {
        setPerson(null);
        setEvents([]);
      })
      .finally(() => setLoading(false));
  }, [open, personId, cdmName]);

  const filteredEvents = useMemo(
    () => events.filter(e => activeDomains.has(e.domain)),
    [events, activeDomains],
  );

  // Group events by date for the timeline
  const groupedByDate = useMemo(() => {
    const map = new Map<string, PatientJourneyEvent[]>();
    for (const evt of filteredEvents) {
      const key = evt.start_date || 'unknown';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(evt);
    }
    return Array.from(map.entries());
  }, [filteredEvents]);

  // Group events by domain then date
  const groupedByDomain = useMemo(() => {
    const map = new Map<string, PatientJourneyEvent[]>();
    for (const evt of filteredEvents) {
      if (!map.has(evt.domain)) map.set(evt.domain, []);
      map.get(evt.domain)!.push(evt);
    }
    return Array.from(map.entries());
  }, [filteredEvents]);

  const allDomains = useMemo(
    () => [...new Set(events.map(e => e.domain))],
    [events],
  );

  const toggleDomain = (domain: string) => {
    setActiveDomains(prev => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  };

  const formatDate = (d: string | null) => {
    if (!d) return '—';
    return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };

  return (
    <Modal
      title={
        <Space>
          <UserOutlined />
          {t('cohort.patient_journey', 'Patient Journey')}
          {person && <Tag>ID {person.person_id}</Tag>}
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={900}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto', padding: '16px 24px' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : !person ? (
        <Empty description={t('cohort.no_journey', 'No data found')} />
      ) : (
        <>
          {/* Patient header */}
          <div style={{
            display: 'flex', gap: 16, alignItems: 'center',
            marginBottom: 16, padding: '8px 12px',
            background: '#fafafa', borderRadius: 8,
          }}>
            <div>
              <Text type="secondary">{t('cohort.birth_year', 'Birth Year')}: </Text>
              <Text strong>{person.year_of_birth}</Text>
            </div>
            <div>
              <Text type="secondary">{t('quality.gender_distribution', 'Gender')}: </Text>
              <Text strong>{person.gender || '—'}</Text>
            </div>
            {person.observation_period_start_date && (
              <div>
                <CalendarOutlined style={{ marginRight: 4 }} />
                <Text type="secondary">{t('cohort.obs_period', 'Obs. Period')}: </Text>
                <Text>{formatDate(person.observation_period_start_date)} — {formatDate(person.observation_period_end_date)}</Text>
              </div>
            )}
            <div style={{ marginLeft: 'auto' }}>
              <Tag color="blue">{events.length} {t('cohort.events', 'events')}</Tag>
            </div>
          </div>

          {/* Domain filter chips */}
          <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 4 }}>
              {t('cohort.filter_domains', 'Filter')}:
            </Text>
            {allDomains.map(d => (
              <Tag
                key={d}
                color={activeDomains.has(d) ? domainColor(d) : undefined}
                style={{
                  cursor: 'pointer',
                  opacity: activeDomains.has(d) ? 1 : 0.4,
                  userSelect: 'none',
                }}
                onClick={() => toggleDomain(d)}
              >
                {DOMAIN_STYLE[d]?.icon} {t(`domains.${d}`, d)} ({events.filter(e => e.domain === d).length})
              </Tag>
            ))}
            <div style={{ marginLeft: 'auto' }}>
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t('cohort.group_by_domain', 'By domain')}
                </Text>
                <Switch size="small" checked={groupByDomain} onChange={setGroupByDomain} />
              </Space>
            </div>
          </div>

          {filteredEvents.length === 0 ? (
            <Empty description={t('cohort.no_events', 'No events for selected domains')} />
          ) : groupByDomain ? (
            /* ── Swim-lane view: grouped by domain ── */
            <div>
              {groupedByDomain.map(([domain, domEvents]) => (
                <div key={domain} style={{ marginBottom: 16 }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6,
                    borderBottom: `2px solid ${domainColor(domain)}`, paddingBottom: 4,
                  }}>
                    <span style={{ color: domainColor(domain) }}>{DOMAIN_STYLE[domain]?.icon}</span>
                    <Text strong>{t(`domains.${domain}`, domain)}</Text>
                    <Tag>{domEvents.length}</Tag>
                  </div>
                  {domEvents.map((evt, i) => (
                    <EventRow key={i} evt={evt} formatDate={formatDate} />
                  ))}
                </div>
              ))}
            </div>
          ) : (
            /* ── Chronological timeline ── */
            <div style={{ position: 'relative', paddingLeft: 20 }}>
              {/* Vertical line */}
              <div style={{
                position: 'absolute', left: 8, top: 0, bottom: 0,
                width: 2, background: '#e8e8e8',
              }} />
              {groupedByDate.map(([date, dateEvents], gi) => (
                <div key={gi} style={{ marginBottom: 12, position: 'relative' }}>
                  {/* Date marker */}
                  <div style={{
                    position: 'absolute', left: -16, top: 4,
                    width: 10, height: 10, borderRadius: '50%',
                    background: '#1890ff', border: '2px solid #fff',
                    boxShadow: '0 0 0 2px #1890ff33',
                  }} />
                  <Text strong style={{ fontSize: 12, color: '#1890ff' }}>
                    {formatDate(date)}
                  </Text>
                  <div style={{ marginTop: 4 }}>
                    {dateEvents.map((evt, i) => (
                      <EventRow key={i} evt={evt} formatDate={formatDate} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

/** Single event row */
function EventRow({ evt, formatDate }: { evt: PatientJourneyEvent; formatDate: (d: string | null) => string }) {
  const color = domainColor(evt.domain);
  const icon = DOMAIN_STYLE[evt.domain]?.icon;

  const detail = useMemo(() => {
    const parts: string[] = [];
    if (evt.value_as_number != null) {
      parts.push(`${evt.value_as_number}${evt.unit_source_value ? ` ${evt.unit_source_value}` : ''}`);
    }
    if (evt.quantity != null) parts.push(`qty: ${evt.quantity}`);
    if (evt.end_date) parts.push(`→ ${formatDate(evt.end_date)}`);
    return parts.join(' · ');
  }, [evt, formatDate]);

  // Determine if unmapped (concept_id is 0 or concept_name is empty/generic)
  const isUnmapped = !evt.concept_id || evt.concept_id === 0 || !evt.concept_name || evt.concept_name === 'No matching concept';

  // Display label: prefer concept_name when mapped, fall back to source_concept_name, then source_value
  const displayLabel = isUnmapped
    ? (evt.source_concept_name || evt.source_value || `Concept ${evt.concept_id}`)
    : (evt.concept_name || evt.source_concept_name || evt.source_value || `Concept ${evt.concept_id}`);

  return (
    <Tooltip
      title={
        <div>
          <div><b>{evt.domain}</b> — concept_id: {evt.concept_id}</div>
          {evt.concept_name && <div>Standard: {evt.concept_name}</div>}
          {evt.source_concept_name && <div>Source concept: {evt.source_concept_name}</div>}
          {evt.source_value && <div>Source value: {evt.source_value}</div>}
          {detail && <div>{detail}</div>}
        </div>
      }
    >
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '3px 8px', marginBottom: 2,
        borderRadius: 4, cursor: 'default',
        borderLeft: `3px solid ${color}`,
        background: `${color}08`,
        fontSize: 13,
      }}>
        <span style={{ color, flexShrink: 0 }}>{icon}</span>
        <Text ellipsis style={{ flex: 1, fontSize: 13 }}>
          {displayLabel}
        </Text>
        {isUnmapped && (
          <Tag color="orange" style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
            unmapped
          </Tag>
        )}
        {detail && (
          <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>
            {detail}
          </Text>
        )}
      </div>
    </Tooltip>
  );
}
