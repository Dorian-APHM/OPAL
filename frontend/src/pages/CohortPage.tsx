import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Save, FolderOpen, Trash2, Plus, PlayCircle, User, Table2,
  ArrowLeftRight, Code, Download, AppWindow, BarChart3, LineChart,
  Star, Share2, Globe, Users, UserPlus, X, GitBranch,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/KeycloakContext';
import {
  Card, Button, Input, TextArea, Table, Tabs, Tag, Modal, Confirm,
  Empty, Alert, Spinner, Switch, Select,
} from '../components/ui';
import { useToast } from '../components/ui';
import CriteriaPanel from '../components/cohort/CriteriaPanel';
import QueryCanvas from '../components/cohort/QueryCanvas';
import ResultsPanel from '../components/cohort/ResultsPanel';
import CharacterizationPanel from '../components/cohort/CharacterizationPanel';
import CohortComparisonPanel from '../components/cohort/CohortComparisonPanel';
import PathwaysPanel from '../components/cohort/PathwaysPanel';
import PatientJourney from '../components/cohort/PatientJourney';
import ConceptSetPage from './ConceptSetPage';
import IncidencePage from './IncidencePage';
import EstimationPage from './EstimationPage';
import { cohortApi, cohortSharingApi, usersApi, groupApi, favoritesApi } from '../api/client';
import SqlEditor from '../components/SqlEditor';
import { useNotifDots } from '../hooks/useNotifDots';
import { useSessionState } from '../hooks/useSessionState';
import type {
  CohortCriterion,
  CohortCriteria, CohortSummary, CohortShareInfo,
} from '../types';

function emptyCriteria(): CohortCriteria {
  return {
    inclusion: { operator: 'AND', criteria: [], groups: [] },
    exclusion: { operator: 'OR', criteria: [], groups: [] },
    demographics: {},
  };
}

interface Props {
  selectedCdm: string | null;
}

export default function CohortPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const { roles } = useAuth();
  const toast = useToast();
  const location = useLocation();
  const canDelete = roles.includes('admin') || roles.includes('data-manager');

  // Cohort state (persisted across navigation)
  const [cohortName, setCohortName] = useSessionState('cohort:name', '');
  const [cohortDesc, setCohortDesc] = useSessionState('cohort:desc', '');
  const [criteria, setCriteria] = useSessionState<CohortCriteria>('cohort:criteria', emptyCriteria());
  const [savedCohortId, setSavedCohortId] = useSessionState<number | undefined>('cohort:savedId', undefined as number | undefined);

  // Saved cohorts list
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [showList, setShowList] = useSessionState('cohort:showList', false);
  const [saving, setSaving] = useState(false);

  // Delete confirm state
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  // Favorites state
  const [favoriteCohortIds, setFavoriteCohortIds] = useState<Set<string>>(new Set());
  const [favoritesMap, setFavoritesMap] = useState<Record<string, number>>({});

  // Sharing state
  const [shareModalCohortId, setShareModalCohortId] = useState<number | null>(null);
  const [shareInfo, setShareInfo] = useState<CohortShareInfo | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [allUsers, setAllUsers] = useState<string[]>([]);
  const [allGroups, setAllGroups] = useState<string[]>([]);
  const [shareTarget, setShareTarget] = useState<string | null>(null);
  const [shareType, setShareType] = useState<string | null>('user');

  // Notification dots for shared cohorts — dot on Load button, cleared when opening list
  const { markAllReadForType: markAllCohortRead, count: cohortNotifCount } = useNotifDots('cohort_shared');

  const loadCohorts = useCallback(async () => {
    if (!selectedCdm) return;
    try {
      const resp = await cohortApi.list(selectedCdm);
      setCohorts(resp.data.cohorts);
    } catch {
      // ignore
    }
  }, [selectedCdm]);

  // Load favorites on mount
  const loadFavorites = useCallback(async () => {
    try {
      const resp = await favoritesApi.list('cohort');
      const favIds = new Set<string>();
      const favMap: Record<string, number> = {};
      for (const fav of resp.data.favorites) {
        favIds.add(fav.item_id);
        favMap[fav.item_id] = fav.id;
      }
      setFavoriteCohortIds(favIds);
      setFavoritesMap(favMap);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadCohorts();
    loadFavorites();
  }, [loadCohorts, loadFavorites]);

  // Auto-open cohort from dashboard navigation
  useEffect(() => {
    const state = location.state as { openCohortId?: number } | null;
    if (state?.openCohortId) {
      handleLoad(state.openCohortId);
      // Clear the state so it doesn't re-trigger
      window.history.replaceState({}, document.title);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  // Reset only when CDM actually changes (not on remount)
  const prevCdmRef = useRef(selectedCdm);
  useEffect(() => {
    if (prevCdmRef.current !== selectedCdm) {
      prevCdmRef.current = selectedCdm;
      setCriteria(emptyCriteria());
      setSavedCohortId(undefined);
      setCohortName('');
      setCohortDesc('');
    }
  }, [selectedCdm]);

  const [addMode, setAddMode] = useSessionState<'inclusion' | 'exclusion'>('cohort:addMode', 'inclusion');

  const handleAddCriterion = (criterion: CohortCriterion) => {
    setCriteria(prev => ({
      ...prev,
      [addMode]: {
        ...prev[addMode],
        criteria: [...prev[addMode].criteria, criterion],
      },
    }));
  };

  const handleSave = async () => {
    if (!selectedCdm || !cohortName.trim()) {
      toast.warning(t('cohort.enter_name', 'Please enter a cohort name'));
      return;
    }
    setSaving(true);
    try {
      // Prepare criteria for backend (strip client-side fields)
      const backendCriteria = toBackendCriteria(criteria);

      if (savedCohortId) {
        await cohortApi.update(savedCohortId, {
          name: cohortName,
          description: cohortDesc,
          criteria: backendCriteria,
        });
        toast.success(t('cohort.saved', 'Cohort saved (new version)'));
      } else {
        const resp = await cohortApi.create({
          cdm_name: selectedCdm,
          name: cohortName,
          description: cohortDesc,
          criteria: backendCriteria,
        });
        setSavedCohortId(resp.data.id);
        toast.success(t('cohort.created', 'Cohort created'));
      }
      loadCohorts();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleLoad = async (cohortId: number) => {
    try {
      const resp = await cohortApi.get(cohortId);
      const detail = resp.data;
      setCohortName(detail.name);
      setCohortDesc(detail.description);
      setSavedCohortId(detail.id);

      const latestVersion = detail.versions[0];
      if (latestVersion) {
        const loaded = fromBackendCriteria(latestVersion.criteria_json);
        setCriteria(loaded);
      }
      setShowList(false);
    } catch (e: any) {
      toast.error('Failed to load cohort');
    }
  };

  const handleDelete = async (cohortId: number) => {
    try {
      await cohortApi.delete(cohortId);
      toast.success(t('common.deleted', 'Deleted'));
      if (savedCohortId === cohortId) {
        setSavedCohortId(undefined);
        setCohortName('');
        setCriteria(emptyCriteria());
      }
      loadCohorts();
    } catch {
      toast.error('Delete failed');
    }
  };

  const handleNew = () => {
    setCriteria(emptyCriteria());
    setSavedCohortId(undefined);
    setCohortName('');
    setCohortDesc('');
    setSamplePatients([]);
    setSampleColumns([]);
  };

  // Toggle favorite
  const toggleFavorite = async (cohortId: number, cohortName: string) => {
    const key = String(cohortId);
    if (favoriteCohortIds.has(key)) {
      const favId = favoritesMap[key];
      if (favId) {
        try {
          await favoritesApi.remove(favId);
          setFavoriteCohortIds(prev => {
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
          setFavoritesMap(prev => {
            const next = { ...prev };
            delete next[key];
            return next;
          });
        } catch {
          toast.error('Failed to remove favorite');
        }
      }
    } else {
      try {
        const resp = await favoritesApi.add({
          item_type: 'cohort',
          item_id: key,
          item_label: cohortName,
        });
        setFavoriteCohortIds(prev => new Set(prev).add(key));
        setFavoritesMap(prev => ({ ...prev, [key]: resp.data.id }));
      } catch {
        toast.error('Failed to add favorite');
      }
    }
  };

  // Sharing helpers
  const openShareModal = async (cohortId: number) => {
    setShareModalCohortId(cohortId);
    setShareLoading(true);
    setShareTarget(null);
    setShareType('user');
    try {
      const [sharesResp, usersResp, groupsResp] = await Promise.all([
        cohortSharingApi.listShares(cohortId),
        usersApi.listOpalUsers(),
        groupApi.list(),
      ]);
      setShareInfo(sharesResp.data);
      setAllUsers(usersResp.data.users);
      setAllGroups(groupsResp.data.groups.map(g => g.name));
    } catch {
      toast.error('Failed to load sharing info');
      setShareModalCohortId(null);
    } finally {
      setShareLoading(false);
    }
  };

  const handleTogglePublic = async (checked: boolean) => {
    if (!shareModalCohortId) return;
    try {
      if (checked) {
        await cohortSharingApi.share(shareModalCohortId, 'all');
      } else {
        await cohortSharingApi.unshare(shareModalCohortId, 'all');
      }
      setShareInfo(prev => prev ? { ...prev, shared_with_all: checked } : prev);
      loadCohorts();
    } catch {
      toast.error('Failed to update sharing');
    }
  };

  const handleAddShare = async () => {
    if (!shareModalCohortId || !shareTarget || !shareType) return;
    try {
      await cohortSharingApi.share(shareModalCohortId, shareType, shareTarget);
      // Refresh shares
      const resp = await cohortSharingApi.listShares(shareModalCohortId);
      setShareInfo(resp.data);
      setShareTarget(null);
      toast.success(t('cohort.shared_success', 'Shared successfully'));
    } catch (e: any) {
      toast.error(e.message || 'Failed to share');
    }
  };

  const handleUnshare = async (type: string, target: string) => {
    if (!shareModalCohortId) return;
    try {
      await cohortSharingApi.unshare(shareModalCohortId, type, target);
      const resp = await cohortSharingApi.listShares(shareModalCohortId);
      setShareInfo(resp.data);
      toast.success(t('cohort.unshared', 'Share removed'));
    } catch {
      toast.error('Failed to remove share');
    }
  };

  // Active tab (builder vs characterization)
  const [activeTab, setActiveTab] = useState<string>('builder');

  // Detailed sample state
  const [samplePatients, setSamplePatients] = useState<Record<string, any>[]>([]);
  const [sampleColumns, setSampleColumns] = useState<{ key: string; label: string; domain: string }[]>([]);
  const [sampleLoading, setSampleLoading] = useState(false);

  // Patient journey state
  const [journeyPersonId, setJourneyPersonId] = useState<number | null>(null);

  const runDetailedSample = async () => {
    if (!selectedCdm) return;
    const backendCriteria = toBackendCriteria(criteria);
    setSampleLoading(true);
    try {
      const resp = await cohortApi.sampleDetailed(selectedCdm, backendCriteria, 10);
      setSamplePatients(resp.data.patients);
      setSampleColumns(resp.data.columns);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Sampling failed');
    } finally {
      setSampleLoading(false);
    }
  };

  if (!selectedCdm) {
    return (
      <Empty description={t('cohort.select_cdm', 'Select a CDM connection to start building cohorts')} />
    );
  }

  return (
    <div className="min-h-[calc(100vh-60px)] lg:h-[calc(100vh-60px)] flex flex-col">
      {/* Header */}
      <Card size="small" className="mb-2" hoverable={false}>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            placeholder={t('cohort.cohort_name', 'Cohort name...')}
            value={cohortName}
            onChange={e => setCohortName(e.target.value)}
            className="w-full sm:!w-[250px]"
          />
          <Input
            placeholder={t('cohort.description', 'Description (optional)')}
            value={cohortDesc}
            onChange={e => setCohortDesc(e.target.value)}
            className="flex-1 min-w-[150px]"
          />
          <div className="flex items-center gap-2">
          <Button icon={<Plus className="h-3.5 w-3.5" />} size="small" onClick={handleNew}>
            {t('cohort.new', 'New')}
          </Button>
          <Button
            icon={<Save className="h-3.5 w-3.5" />}
            variant="primary"
            size="small"
            onClick={handleSave}
            loading={saving}
          >
            {t('common.save', 'Save')}
          </Button>
          <Button icon={<FolderOpen className="h-3.5 w-3.5" />} size="small" onClick={() => { setShowList(true); markAllCohortRead(); }}>
            <span className="inline-flex items-center gap-1.5">
              {t('cohort.load', 'Load')} ({cohorts.length})
              {cohortNotifCount > 0 && (
                <span className="inline-block w-2 h-2 rounded-full bg-red-500 shrink-0" />
              )}
            </span>
          </Button>
          </div>
        </div>
      </Card>

      {/* Three-panel layout */}
      <div className="flex flex-col lg:grid lg:grid-cols-12 gap-2 flex-1">
        {/* Left: Criteria Panel */}
        <div className="lg:col-span-2 h-full overflow-auto flex flex-col gap-1">
          {/* Inclusion / Exclusion toggle */}
          <div className="flex rounded-lg overflow-hidden border border-glass-border shrink-0">
            <button
              className={`flex-1 py-1.5 text-xs font-medium transition-colors border-none cursor-pointer ${
                addMode === 'inclusion'
                  ? 'bg-emerald-accent/15 text-emerald-accent'
                  : 'bg-surface-dark text-text-dim hover:text-text-muted'
              }`}
              onClick={() => setAddMode('inclusion')}
            >
              + {t('cohort.inclusion', 'Inclusion')}
            </button>
            <button
              className={`flex-1 py-1.5 text-xs font-medium transition-colors border-none border-l border-glass-border cursor-pointer ${
                addMode === 'exclusion'
                  ? 'bg-red-500/15 text-red-400'
                  : 'bg-surface-dark text-text-dim hover:text-text-muted'
              }`}
              onClick={() => setAddMode('exclusion')}
            >
              - {t('cohort.exclusion', 'Exclusion')}
            </button>
          </div>
          <CriteriaPanel
            cdmName={selectedCdm}
            onAddCriterion={handleAddCriterion}
          />
        </div>

        {/* Center: Tabs — Builder / Characterization */}
        <div className="lg:col-span-8 h-full overflow-auto">
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: 'builder',
                label: t('cohort.query_builder', 'Query Builder'),
                children: (
                  <>
                    <QueryCanvas
                      inclusion={criteria.inclusion}
                      exclusion={criteria.exclusion}
                      demographics={criteria.demographics || {}}
                      exitCriteria={criteria.exit_criteria}
                      initialEventId={criteria.initial_event_criterion_id}
                      cdmName={selectedCdm || ''}
                      onUpdateInclusion={inc => setCriteria(prev => ({ ...prev, inclusion: inc }))}
                      onUpdateExclusion={exc => setCriteria(prev => ({ ...prev, exclusion: exc }))}
                      onUpdateDemographics={demo => setCriteria(prev => ({ ...prev, demographics: demo }))}
                      onUpdateExitCriteria={exit => setCriteria(prev => ({ ...prev, exit_criteria: exit }))}
                      onUpdateInitialEvent={id => setCriteria(prev => ({ ...prev, initial_event_criterion_id: id }))}
                    />

                    {/* Detailed Sample */}
                    <Card
                      size="small"
                      className="mt-2"
                      title={
                        <div className="flex items-center gap-1.5">
                          <User className="h-4 w-4" />
                          <span>{t('cohort.sample_patients', 'Sample Patients')}</span>
                        </div>
                      }
                      extra={
                        <Button
                          size="small"
                          onClick={runDetailedSample}
                          loading={sampleLoading}
                          disabled={criteria.inclusion.criteria.length === 0}
                        >
                          {t('cohort.sample', 'Sample')}
                        </Button>
                      }
                    >
                      {sampleLoading ? (
                        <div className="text-center py-5"><Spinner /></div>
                      ) : samplePatients.length > 0 ? (
                        <Table
                          size="small"
                          dataSource={samplePatients}
                          rowKey={(r) => JSON.stringify(r).slice(0, 100)}
                          pagination={false}
                          scroll={{ x: true }}
                          columns={[
                            {
                              title: 'Person ID', dataIndex: 'person_id', key: 'pid', width: 90,
                              render: (v: number) => (
                                <a
                                  onClick={() => setJourneyPersonId(v)}
                                  title={t('cohort.view_journey', 'View patient journey')}
                                  className="text-emerald-accent hover:underline cursor-pointer"
                                >
                                  {v}
                                </a>
                              ),
                            },
                            { title: t('cohort.birth_year', 'Birth Year'), dataIndex: 'year_of_birth', key: 'yob', width: 80 },
                            ...sampleColumns.map(col => ({
                              title: col.label,
                              dataIndex: col.key,
                              key: col.key,
                              width: col.key === 'visit_occurrence_id' ? 90 : 150,
                              ellipsis: true,
                              render: (v: any) => v != null ? String(v) : '—',
                            })),
                          ]}
                        />
                      ) : (
                        <span className="text-text-muted text-xs">
                          {t('cohort.click_sample', 'Click Sample to see random patients')}
                        </span>
                      )}
                    </Card>
                  </>
                ),
              },
              {
                key: 'characterization',
                label: (
                  <div className="flex items-center gap-1">
                    <Table2 className="h-3.5 w-3.5" />
                    <span>Table 1</span>
                  </div>
                ),
                children: (
                  <CharacterizationPanel
                    cdmName={selectedCdm || ''}
                    criteria={toBackendCriteria(criteria)}
                    cohortId={savedCohortId}
                  />
                ),
              },
              {
                key: 'comparison',
                label: (
                  <div className="flex items-center gap-1">
                    <ArrowLeftRight className="h-3.5 w-3.5" />
                    <span>{t('cohort.compare', 'Compare')}</span>
                  </div>
                ),
                children: (
                  <CohortComparisonPanel
                    cdmName={selectedCdm || ''}
                    cohorts={cohorts}
                  />
                ),
              },
              {
                key: 'pathways',
                label: (
                  <div className="flex items-center gap-1">
                    <GitBranch className="h-3.5 w-3.5" />
                    <span>{t('cohort.pathways', 'Pathways')}</span>
                  </div>
                ),
                children: (
                  <PathwaysPanel
                    cdmName={selectedCdm || ''}
                    criteria={toBackendCriteria(criteria)}
                  />
                ),
              },
              {
                key: 'sql',
                label: (
                  <div className="flex items-center gap-1">
                    <Code className="h-3.5 w-3.5" />
                    <span>SQL</span>
                  </div>
                ),
                children: (
                  <SqlEditorPanel cdmName={selectedCdm || ''} />
                ),
              },
              {
                key: 'concept-sets',
                label: (
                  <div className="flex items-center gap-1">
                    <AppWindow className="h-3.5 w-3.5" />
                    <span>{t('app.concept_sets', 'Concept Sets')}</span>
                  </div>
                ),
                children: <ConceptSetPage selectedCdm={selectedCdm} />,
              },
              {
                key: 'incidence',
                label: (
                  <div className="flex items-center gap-1">
                    <BarChart3 className="h-3.5 w-3.5" />
                    <span>{t('app.incidence', 'Incidence')}</span>
                  </div>
                ),
                children: <IncidencePage selectedCdm={selectedCdm} />,
              },
              {
                key: 'estimation',
                label: (
                  <div className="flex items-center gap-1">
                    <LineChart className="h-3.5 w-3.5" />
                    <span>{t('app.estimation', 'Estimation')}</span>
                  </div>
                ),
                children: <EstimationPage selectedCdm={selectedCdm} />,
              },
            ]}
          />
        </div>

        {/* Right: Results Panel */}
        <div className="lg:col-span-2 h-full overflow-auto">
          <ResultsPanel
            cdmName={selectedCdm}
            criteria={toBackendCriteria(criteria)}
            savedCohortId={savedCohortId}
          />
        </div>
      </div>

      {/* Patient Journey modal */}
      <PatientJourney
        cdmName={selectedCdm || ''}
        personId={journeyPersonId}
        open={journeyPersonId !== null}
        onClose={() => setJourneyPersonId(null)}
      />

      {/* Load modal */}
      <Modal
        title={t('cohort.saved_cohorts', 'Saved Cohorts')}
        open={showList}
        onClose={() => setShowList(false)}
        width="max-w-xl"
      >
        {cohorts.length === 0 ? (
          <p className="text-sm text-text-dim text-center py-4">
            {t('cohort.no_cohorts', 'No saved cohorts')}
          </p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {cohorts.map(c => (
              <li key={c.id} className="py-3 flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* Favorite star */}
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleFavorite(c.id, c.name); }}
                      className="shrink-0 hover:scale-110 transition-transform"
                      title={favoriteCohortIds.has(String(c.id)) ? t('cohort.unfavorite', 'Remove from favorites') : t('cohort.favorite', 'Add to favorites')}
                    >
                      <Star
                        className={`h-4 w-4 ${favoriteCohortIds.has(String(c.id)) ? 'fill-yellow-400 text-yellow-400' : 'text-text-muted hover:text-yellow-400'}`}
                      />
                    </button>
                    <span className="text-sm font-medium text-text-bright">{c.name}</span>
                    <Tag>v{c.latest_version}</Tag>
                    {c.patient_count != null && (
                      <Tag color="green">{c.patient_count.toLocaleString()} patients</Tag>
                    )}
                    {c.shared_with_all && (
                      <Tag color="blue">
                        <Globe className="h-3 w-3 inline mr-0.5" />
                        {t('cohort.public', 'Public')}
                      </Tag>
                    )}
                  </div>
                  <span className="text-text-muted text-xs">
                    {c.description || '—'} · {c.updated_at?.substring(0, 10)}
                    {c.created_by && (
                      <> · <span className="text-text-dim">{t('cohort.by', 'by')} {c.created_by}</span></>
                    )}
                  </span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button size="small" variant="link" onClick={() => handleLoad(c.id)}>
                    {t('cohort.load', 'Load')}
                  </Button>
                  <Button
                    size="small"
                    variant="link"
                    onClick={() => openShareModal(c.id)}
                    title={t('cohort.share', 'Share')}
                  >
                    <Share2 className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="small" variant="link" onClick={() => {
                    if (c.id) {
                      cohortApi.execute(c.id).then(resp => {
                        toast.success(`Count: ${resp.data.patient_count}`);
                        loadCohorts();
                      }).catch(() => toast.error('Execution failed'));
                    }
                  }}>
                    <PlayCircle className="h-3.5 w-3.5" />
                  </Button>
                  {canDelete && (
                    <Button
                      size="small"
                      variant="danger"
                      onClick={() => setDeleteConfirmId(c.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Modal>

      {/* Share modal */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />
            <span>{t('cohort.share_cohort', 'Share Cohort')}</span>
          </div>
        }
        open={shareModalCohortId !== null}
        onClose={() => setShareModalCohortId(null)}
        width="max-w-md"
      >
        {shareLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : shareInfo ? (
          <div className="space-y-4">
            {/* Public toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-surface-raised">
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-blue-400" />
                <span className="text-sm text-text-bright">{t('cohort.public_access', 'Public (visible to all users)')}</span>
              </div>
              <Switch
                checked={shareInfo.shared_with_all}
                onChange={handleTogglePublic}
                size="small"
              />
            </div>

            {/* Add share */}
            <div className="space-y-2">
              <label className="text-xs font-medium text-text-muted">{t('cohort.share_with', 'Share with...')}</label>
              <div className="flex items-center gap-2">
                <Select
                  options={[
                    { value: 'user', label: t('cohort.user', 'User') },
                    { value: 'group', label: t('cohort.group', 'Group') },
                  ]}
                  value={shareType}
                  onChange={v => { setShareType(v); setShareTarget(null); }}
                  size="small"
                  className="w-24"
                />
                <Select
                  options={
                    shareType === 'user'
                      ? allUsers.map(u => ({ value: u, label: u }))
                      : allGroups.map(g => ({ value: g, label: g }))
                  }
                  value={shareTarget}
                  onChange={setShareTarget}
                  placeholder={shareType === 'user' ? t('cohort.select_user', 'Select user...') : t('cohort.select_group', 'Select group...')}
                  size="small"
                  className="flex-1"
                />
                <Button
                  size="small"
                  variant="primary"
                  icon={<UserPlus className="h-3.5 w-3.5" />}
                  onClick={handleAddShare}
                  disabled={!shareTarget}
                >
                  {t('cohort.add', 'Add')}
                </Button>
              </div>
            </div>

            {/* Current shares */}
            {shareInfo.shares.length > 0 && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-text-muted">{t('cohort.current_shares', 'Current shares')}</label>
                <ul className="divide-y divide-border-subtle">
                  {shareInfo.shares.map((s, i) => (
                    <li key={i} className="py-2 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {s.type === 'user' ? (
                          <User className="h-3.5 w-3.5 text-text-muted" />
                        ) : (
                          <Users className="h-3.5 w-3.5 text-text-muted" />
                        )}
                        <span className="text-sm text-text-bright">{s.target}</span>
                        <Tag>{s.type}</Tag>
                        <span className="text-xs text-text-dim">
                          {t('cohort.shared_by', 'by')} {s.shared_by}
                        </span>
                      </div>
                      <button
                        onClick={() => handleUnshare(s.type, s.target)}
                        className="text-red-400 hover:text-red-300 p-1"
                        title={t('cohort.unshare', 'Remove share')}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}
      </Modal>

      {/* Delete confirmation */}
      <Confirm
        open={deleteConfirmId !== null}
        onClose={() => setDeleteConfirmId(null)}
        onConfirm={() => {
          if (deleteConfirmId !== null) handleDelete(deleteConfirmId);
        }}
        title={t('common.confirm_delete', 'Delete?')}
        confirmText="Delete"
        danger
      />
    </div>
  );
}

// ──── SQL Editor Panel ────

function SqlEditorPanel({ cdmName }: { cdmName: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [sql, setSql] = useState('SELECT * FROM omop_cdm.person LIMIT 10');
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowCount, setRowCount] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [schema, setSchema] = useState<Record<string, string[]> | undefined>();
  const [schemaName, setSchemaName] = useState<string | undefined>();

  // Load schema for autocomplete
  useEffect(() => {
    if (!cdmName) return;
    cohortApi.sqlSchema(cdmName).then(res => {
      setSchema(res.data.tables);
      setSchemaName(res.data.schema);
    }).catch(() => {});
  }, [cdmName]);

  const handleExecute = async () => {
    if (!sql.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await cohortApi.executeSql(cdmName, sql);
      setColumns(resp.data.columns);
      setRows(resp.data.rows);
      setRowCount(resp.data.row_count);
      setTruncated(resp.data.truncated);
    } catch (e: any) {
      setError(e.message || 'Query failed');
      setColumns([]);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!sql.trim()) return;
    try {
      const resp = await cohortApi.exportSql(cdmName, sql);
      const blob = new Blob([resp.data], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'sql_export.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    } catch (e: any) {
      toast.error(e.message || 'Export failed');
    }
  };

  return (
    <div>
      <Card size="small" className="mb-2">
        <SqlEditor
          value={sql}
          onChange={setSql}
          onExecute={handleExecute}
          schema={schema}
          schemaName={schemaName}
          height="200px"
          placeholder="SELECT * FROM omop_cdm.person LIMIT 10"
        />
        <div className="mt-2 flex items-center gap-2">
          <Button
            variant="primary"
            icon={<PlayCircle className="h-3.5 w-3.5" />}
            onClick={handleExecute}
            loading={loading}
          >
            {t('cohort.run_sql', 'Execute')} (Ctrl+Enter)
          </Button>
          <Button
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={handleExport}
            disabled={!sql.trim()}
          >
            CSV
          </Button>
          <span className="text-text-muted text-xs">
            {t('cohort.sql_readonly', 'Read-only queries only (SELECT/WITH)')}
          </span>
          {schema && (
            <Tag color="green" className="ml-auto" style={{ fontSize: 11 }}>
              {Object.keys(schema).length} tables
            </Tag>
          )}
        </div>
      </Card>

      {error && (
        <Alert message={error} type="error" showIcon closable onClose={() => setError(null)} className="mb-2" />
      )}

      {rows.length > 0 && (
        <Card size="small">
          <div className="mb-2 flex items-center gap-2">
            <Tag color="blue">{rowCount?.toLocaleString()} {t('cohort.sql_rows', 'rows')}</Tag>
            {truncated && <Tag color="orange">{t('cohort.sql_truncated', 'Truncated (add LIMIT to control)')}</Tag>}
          </div>
          <Table
            size="small"
            dataSource={rows}
            rowKey={(r) => JSON.stringify(r).slice(0, 100)}
            pagination={{ pageSize: 50 }}
            scroll={{ x: true }}
            columns={columns.map(col => ({
              title: col,
              dataIndex: col,
              key: col,
              ellipsis: true,
              width: 150,
              render: (v: any) => v != null ? String(v) : <span className="text-text-muted">NULL</span>,
            }))}
          />
        </Card>
      )}
    </div>
  );
}

// ──── Helpers to convert between frontend and backend criteria ────

function mapGroupToBackend(group: import('../types').CriteriaGroup): import('../types').CriteriaGroup {
  const mapCriterion = (c: CohortCriterion) => ({
    ...c,
    concepts: c.concepts.map(con => ({
      concept_id: con.concept_id,
      concept_name: con.concept_name,
      concept_code: con.concept_code,
      domain_id: con.domain_id,
      vocabulary_id: con.vocabulary_id,
      concept_class_id: con.concept_class_id,
      standard_concept: con.standard_concept,
    })),
  });
  return {
    operator: group.operator,
    criteria: (group.criteria || []).map(mapCriterion),
    groups: group.groups?.map(mapGroupToBackend),
    sameVisit: group.sameVisit,
  };
}

function toBackendCriteria(criteria: CohortCriteria): CohortCriteria {
  return {
    inclusion: mapGroupToBackend(criteria.inclusion),
    exclusion: mapGroupToBackend(criteria.exclusion),
    demographics: criteria.demographics,
    exit_criteria: criteria.exit_criteria,
    initial_event_criterion_id: criteria.initial_event_criterion_id,
  };
}

function mapGroupFromBackend(group: any): import('../types').CriteriaGroup {
  const mapCriteria = (criteria: any[]) =>
    (criteria || []).map((c: any) => ({
      id: c.id || Math.random().toString(36).slice(2) + Date.now().toString(36),
      domain: c.domain,
      concepts: (c.concepts || []).map((cid: any) =>
        typeof cid === 'object' && cid !== null
          ? { concept_id: cid.concept_id, concept_name: cid.concept_name || `Concept ${cid.concept_id}`, concept_code: cid.concept_code || '', domain_id: cid.domain_id || c.domain, vocabulary_id: cid.vocabulary_id || '', concept_class_id: cid.concept_class_id || '', standard_concept: cid.standard_concept ?? null }
          : { concept_id: cid, concept_name: `Concept ${cid}`, concept_code: '', domain_id: c.domain, vocabulary_id: '', concept_class_id: '', standard_concept: null }
      ),
      include_descendants: c.include_descendants ?? true,
      source_codes: c.source_codes || [],
      operatorWithNext: c.operatorWithNext,
      temporal: c.temporal || { type: 'any_time' },
      occurrence: c.occurrence || { type: 'any', count: 1 },
      value: c.value,
    }));

  return {
    operator: group?.operator || 'AND',
    criteria: mapCriteria(group?.criteria),
    groups: group?.groups?.map(mapGroupFromBackend),
    sameVisit: group?.sameVisit,
  };
}

function fromBackendCriteria(backendCriteria: any): CohortCriteria {
  return {
    inclusion: mapGroupFromBackend(backendCriteria.inclusion),
    exclusion: mapGroupFromBackend(backendCriteria.exclusion || { operator: 'OR', criteria: [] }),
    demographics: backendCriteria.demographics || {},
    exit_criteria: backendCriteria.exit_criteria,
    initial_event_criterion_id: backendCriteria.initial_event_criterion_id,
  };
}
