import { useState } from 'react';
import { Sparkles, User, ArrowRight } from 'lucide-react';
import { cohortLlmApi } from '../../api/client';
import type { CohortDraft, CohortCriterion, DemographicConstraints } from '../../types';
import { TextArea, Button, Spinner, Alert } from '../ui';
import CriterionReviewCard from './CriterionReviewCard';

interface ApplyPayload {
  inclusion: CohortCriterion[];
  exclusion: CohortCriterion[];
  demographics: DemographicConstraints;
  llm_prompt?: string;
}

interface Props {
  cdmName?: string;
  onApply: (payload: ApplyPayload) => void;
}

const genId = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
const GENDER_CONCEPT = { M: 8507, F: 8532 };

export default function AiAssistantPanel({ cdmName, onApply }: Props) {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<CohortDraft | null>(null);
  // selected source_values per criterion index
  const [selections, setSelections] = useState<Record<number, Set<string>>>({});

  const generate = async () => {
    if (!prompt.trim() || !cdmName) return;
    setLoading(true);
    setError(null);
    setDraft(null);
    try {
      const { data } = await cohortLlmApi.draft(cdmName, prompt);
      setDraft(data);
      // default selection: every code of every group, per criterion
      const init: Record<number, Set<string>> = {};
      data.criteria.forEach((c, i) => {
        const s = new Set<string>();
        c.concept_sets.forEach(g => g.members.forEach(m => s.add(m.source_value)));
        init[i] = s;
      });
      setSelections(init);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Échec de la génération');
    } finally {
      setLoading(false);
    }
  };

  const setCritSelection = (idx: number, next: Set<string>) =>
    setSelections(prev => ({ ...prev, [idx]: next }));

  const removeCriterion = (idx: number) => {
    if (!draft) return;
    setDraft({ ...draft, criteria: draft.criteria.filter((_, i) => i !== idx) });
    setSelections(prev => {
      const out: Record<number, Set<string>> = {};
      draft.criteria.forEach((_, i) => {
        if (i < idx) out[i] = prev[i];
        else if (i > idx) out[i - 1] = prev[i];
      });
      return out;
    });
  };

  const buildAndApply = () => {
    if (!draft) return;
    const inclusion: CohortCriterion[] = [];
    const exclusion: CohortCriterion[] = [];

    draft.criteria.forEach((c, i) => {
      const codes = Array.from(selections[i] || []);
      if (codes.length === 0) return;
      // Same shape as a manually-added criterion (CriteriaPanel) — NO operatorWithNext.
      // The AI only proposes the criteria/codes; the user arranges AND/OR + ordering in
      // the builder exactly as for manual criteria. Setting operatorWithNext here used to
      // flip the backend into per-criterion mode and break the builder's operator links.
      const crit: CohortCriterion = {
        id: genId(),
        domain: c.domain,
        concepts: [],
        include_descendants: false,
        source_codes: codes,
        temporal: c.temporal || { type: 'any_time' },
        occurrence: { type: 'any', count: 1 },
        value: c.value || undefined,
      };
      (c.negation ? exclusion : inclusion).push(crit);
    });

    const d = draft.demographics || {};
    const demographics: DemographicConstraints = {};
    if (d.age_min != null || d.age_max != null) {
      // Age is evaluated at the cohort index event by default (OHDSI standard).
      demographics.age = { at: 'index' };
      if (d.age_min != null) demographics.age.min = d.age_min;
      if (d.age_max != null) demographics.age.max = d.age_max;
    }
    if (d.sex === 'M' || d.sex === 'F') demographics.gender = [GENDER_CONCEPT[d.sex]];

    onApply({ inclusion, exclusion, demographics, llm_prompt: prompt.trim() });
  };

  const totalSelected = Object.values(selections).reduce((n, s) => n + s.size, 0);
  const sex = draft?.demographics?.sex;
  const ageMin = draft?.demographics?.age_min;
  const ageMax = draft?.demographics?.age_max;

  return (
    <div className="flex flex-col gap-3 max-w-4xl mx-auto w-full">
      {/* Input */}
      <div className="flex items-start gap-2">
        <Sparkles className="h-5 w-5 text-emerald-accent mt-2 shrink-0" />
        <div className="flex-1">
          <TextArea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Décrivez votre cohorte en langage naturel — ex : « Femmes de 50 à 70 ans diabétiques de type 2 sous metformine, hospitalisées depuis 2022 »"
            rows={3}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(); }}
          />
        </div>
      </div>
      <div className="flex justify-end">
        <Button variant="primary" onClick={generate} loading={loading}
                disabled={!prompt.trim() || !cdmName} icon={<Sparkles className="h-4 w-4" />}>
          Générer la cohorte
        </Button>
      </div>

      {!cdmName && <Alert type="warning" message="Sélectionnez d'abord un CDM." />}
      {error && <Alert type="error" message={error} />}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-8 text-text-dim">
          <Spinner /> Extraction + recherche des concepts…
        </div>
      )}

      {/* Review */}
      {draft && !loading && (
        <div className="space-y-3">
          {(sex || ageMin != null || ageMax != null) && (
            <div className="flex items-center gap-2 text-sm text-text">
              <User className="h-4 w-4 text-emerald-accent" />
              <span className="font-medium">Démographie :</span>
              {sex && <span>Sexe {sex === 'F' ? 'Femme' : 'Homme'}</span>}
              {(ageMin != null || ageMax != null) && (
                <span>· Âge {ageMin ?? '?'}–{ageMax ?? '?'} ans</span>
              )}
            </div>
          )}

          {draft.criteria.map((c, i) => (
            <CriterionReviewCard
              key={c.id ?? `${c.label}-${i}`}
              criterion={c}
              selected={selections[i] || new Set()}
              onChange={(next) => setCritSelection(i, next)}
              onRemove={() => removeCriterion(i)}
            />
          ))}

          {draft.criteria.length === 0 && (
            <Alert type="info" message="Aucun critère détecté. Reformulez votre description." />
          )}

          <div className="flex items-center justify-between pt-1">
            <span className="text-[12px] text-text-dim">{totalSelected} code(s) sélectionné(s) au total</span>
            <Button variant="primary" onClick={buildAndApply} disabled={totalSelected === 0}
                    icon={<ArrowRight className="h-4 w-4" />}>
              Appliquer à la cohorte
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
