import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../api/client';
import { Card, Button, Input, NumberInput, Alert, useToast } from '../components/ui';

interface Props {
  selectedCdm: string | null;
}

export default function SettingsPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const [loading, setLoading] = useState(false);

  // Form state
  const [omopSchema, setOmopSchema] = useState('');
  const [topUnmappedTerms, setTopUnmappedTerms] = useState<number | null>(null);
  const [topConcepts, setTopConcepts] = useState<number | null>(null);
  const [maxRecordsPerPerson, setMaxRecordsPerPerson] = useState<number | null>(null);
  const [maxObservationMonths, setMaxObservationMonths] = useState<number | null>(null);
  const [comparisonAlertThreshold, setComparisonAlertThreshold] = useState<number | null>(null);

  useEffect(() => {
    if (selectedCdm) {
      cdmApi.getSettings(selectedCdm).then((res) => {
        const data = res.data;
        setOmopSchema(data.omop_schema ?? '');
        setTopUnmappedTerms(data.top_unmapped_terms ?? null);
        setTopConcepts(data.top_concepts ?? null);
        setMaxRecordsPerPerson(data.max_records_per_person ?? null);
        setMaxObservationMonths(data.max_observation_months ?? null);
        setComparisonAlertThreshold(data.comparison_alert_threshold ?? null);
      });
    }
  }, [selectedCdm]);

  const handleSave = async () => {
    if (!selectedCdm) return;
    try {
      setLoading(true);
      await cdmApi.updateSettings(selectedCdm, {
        omop_schema: omopSchema,
        top_unmapped_terms: topUnmappedTerms ?? undefined,
        top_concepts: topConcepts ?? undefined,
        max_records_per_person: maxRecordsPerPerson ?? undefined,
        max_observation_months: maxObservationMonths ?? undefined,
        comparison_alert_threshold: comparisonAlertThreshold ?? undefined,
      });
      toast.success(t('settings.saved'));
    } catch {
      toast.error(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  if (!selectedCdm) {
    return (
      <div>
        <h3 className="text-2xl font-bold text-text-bright mb-4">{t('settings.title')}</h3>
        <Alert message={t('cdm.select_cdm')} type="info" showIcon />
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-2xl font-bold text-text-bright mb-4">
        {t('settings.title')} — {selectedCdm}
      </h3>
      <Card className="max-w-lg">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.omop_schema')} <span className="text-red-400">*</span></label>
            <Input value={omopSchema} onChange={(e) => setOmopSchema(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.top_unmapped_terms')} <span className="text-red-400">*</span></label>
            <NumberInput value={topUnmappedTerms ?? undefined} onChange={(v) => setTopUnmappedTerms(v)} min={1} max={500} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.top_concepts')} <span className="text-red-400">*</span></label>
            <NumberInput value={topConcepts ?? undefined} onChange={(v) => setTopConcepts(v)} min={1} max={500} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.max_records_per_person')} <span className="text-red-400">*</span></label>
            <NumberInput value={maxRecordsPerPerson ?? undefined} onChange={(v) => setMaxRecordsPerPerson(v)} min={10} max={1000} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.max_observation_months')} <span className="text-red-400">*</span></label>
            <NumberInput value={maxObservationMonths ?? undefined} onChange={(v) => setMaxObservationMonths(v)} min={12} max={600} />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1.5">{t('settings.comparison_threshold')} <span className="text-red-400">*</span></label>
            <NumberInput value={comparisonAlertThreshold ?? undefined} onChange={(v) => setComparisonAlertThreshold(v)} min={0.1} max={50} step={0.5} />
          </div>
          <Button variant="primary" onClick={handleSave} loading={loading}>
            {t('common.save')}
          </Button>
        </div>
      </Card>
    </div>
  );
}
