import { useState, useEffect, useMemo } from 'react';
import { Modal, Tag, Empty, Tooltip, Switch, Spinner } from '../../components/ui';
import {
  Users, Calendar, Activity, Eye, Settings, Hash,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cohortApi } from '../../api/client';
import type { PatientJourneyEvent, PatientJourneyInfo } from '../../types';

/** Color and icon per OMOP domain */
const DOMAIN_STYLE: Record<string, { color: string; icon: React.ReactNode }> = {
  Condition:   { color: '#f5222d', icon: <Activity className="h-3.5 w-3.5" /> },
  Drug:        { color: '#1890ff', icon: <Hash className="h-3.5 w-3.5" /> },
  Measurement: { color: '#52c41a', icon: <Activity className="h-3.5 w-3.5" /> },
  Observation: { color: '#faad14', icon: <Eye className="h-3.5 w-3.5" /> },
  Procedure:   { color: '#722ed1', icon: <Settings className="h-3.5 w-3.5" /> },
  Visit:       { color: '#13c2c2', icon: <Calendar className="h-3.5 w-3.5" /> },
  Device:      { color: '#eb2f96', icon: <Hash className="h-3.5 w-3.5" /> },
  Death:       { color: '#000000', icon: <Activity className="h-3.5 w-3.5" /> },
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
  const groupedByDomainData = useMemo(() => {
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
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          {t('cohort.patient_journey', 'Patient Journey')}
          {person && <Tag>ID {person.person_id}</Tag>}
        </div>
      }
      open={open}
      onClose={onClose}
      width="max-w-4xl"
    >
      <div className="max-h-[70vh] overflow-y-auto">
        {loading ? (
          <div className="text-center py-16"><Spinner size="large" /></div>
        ) : !person ? (
          <Empty description={t('cohort.no_journey', 'No data found')} />
        ) : (
          <>
            {/* Patient header */}
            <div className="flex gap-4 items-center mb-4 px-3 py-2 bg-surface-dark rounded-lg">
              <div>
                <span className="text-text-dim text-xs">{t('cohort.birth_year', 'Birth Year')}: </span>
                <span className="text-text-bright font-semibold text-sm">{person.year_of_birth}</span>
              </div>
              <div>
                <span className="text-text-dim text-xs">{t('quality.gender_distribution', 'Gender')}: </span>
                <span className="text-text-bright font-semibold text-sm">{person.gender || '—'}</span>
              </div>
              {person.observation_period_start_date && (
                <div>
                  <Calendar className="h-3.5 w-3.5 inline mr-1 text-text-dim" />
                  <span className="text-text-dim text-xs">{t('cohort.obs_period', 'Obs. Period')}: </span>
                  <span className="text-text-bright text-sm">{formatDate(person.observation_period_start_date)} — {formatDate(person.observation_period_end_date)}</span>
                </div>
              )}
              <div className="ml-auto">
                <Tag color="blue">{events.length} {t('cohort.events', 'events')}</Tag>
              </div>
            </div>

            {/* Domain filter chips */}
            <div className="mb-3 flex flex-wrap gap-1.5 items-center">
              <span className="text-text-muted text-xs mr-1">
                {t('cohort.filter_domains', 'Filter')}:
              </span>
              {allDomains.map(d => (
                <span
                  key={d}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-medium cursor-pointer select-none transition-opacity"
                  style={{
                    borderColor: domainColor(d),
                    color: activeDomains.has(d) ? domainColor(d) : undefined,
                    opacity: activeDomains.has(d) ? 1 : 0.4,
                    backgroundColor: activeDomains.has(d) ? `${domainColor(d)}15` : undefined,
                  }}
                  onClick={() => toggleDomain(d)}
                >
                  {DOMAIN_STYLE[d]?.icon} {t(`domains.${d}`, d)} ({events.filter(e => e.domain === d).length})
                </span>
              ))}
              <div className="ml-auto flex items-center gap-1">
                <span className="text-text-muted text-[11px]">
                  {t('cohort.group_by_domain', 'By domain')}
                </span>
                <Switch size="small" checked={groupByDomain} onChange={setGroupByDomain} />
              </div>
            </div>

            {filteredEvents.length === 0 ? (
              <Empty description={t('cohort.no_events', 'No events for selected domains')} />
            ) : groupByDomain ? (
              /* Swim-lane view: grouped by domain */
              <div>
                {groupedByDomainData.map(([domain, domEvents]) => (
                  <div key={domain} className="mb-4">
                    <div className="flex items-center gap-1.5 mb-1.5 pb-1" style={{ borderBottom: `2px solid ${domainColor(domain)}` }}>
                      <span style={{ color: domainColor(domain) }}>{DOMAIN_STYLE[domain]?.icon}</span>
                      <span className="text-text-bright font-semibold text-sm">{t(`domains.${domain}`, domain)}</span>
                      <Tag>{domEvents.length}</Tag>
                    </div>
                    {domEvents.map((evt, i) => (
                      <EventRow key={i} evt={evt} formatDate={formatDate} />
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              /* Chronological timeline */
              <div className="relative pl-5">
                {/* Vertical line */}
                <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-glass-border" />
                {groupedByDate.map(([date, dateEvents], gi) => (
                  <div key={gi} className="mb-3 relative">
                    {/* Date marker */}
                    <div
                      className="absolute -left-3 top-1 w-2.5 h-2.5 rounded-full bg-blue-500 border-2 border-surface"
                      style={{ boxShadow: '0 0 0 2px rgba(59,130,246,0.2)' }}
                    />
                    <span className="text-xs font-semibold text-blue-400">
                      {formatDate(date)}
                    </span>
                    <div className="mt-1">
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
      </div>
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
    if (evt.end_date) parts.push(`-> ${formatDate(evt.end_date)}`);
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
        <div className="text-xs">
          <div><strong>{evt.domain}</strong> — concept_id: {evt.concept_id}</div>
          {evt.concept_name && <div>Standard: {evt.concept_name}</div>}
          {evt.source_concept_name && <div>Source concept: {evt.source_concept_name}</div>}
          {evt.source_value && <div>Source value: {evt.source_value}</div>}
          {detail && <div>{detail}</div>}
        </div>
      }
    >
      <div
        className="flex items-center gap-2 px-2 py-0.5 mb-0.5 rounded cursor-default text-[13px]"
        style={{
          borderLeft: `3px solid ${color}`,
          background: `${color}08`,
        }}
      >
        <span className="shrink-0" style={{ color }}>{icon}</span>
        <span className="flex-1 truncate text-text-bright text-[13px]">
          {displayLabel}
        </span>
        {isUnmapped && (
          <Tag color="orange" className="text-[10px] leading-4 !m-0">
            unmapped
          </Tag>
        )}
        {detail && (
          <span className="text-text-muted text-[11px] shrink-0">
            {detail}
          </span>
        )}
      </div>
    </Tooltip>
  );
}
