import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Users, Star, Database, Activity, ArrowRight, Trash2,
  LayoutDashboard, Clock, Heart, Code, FolderOpen,
  Bell, CheckCheck, ExternalLink,
} from 'lucide-react';
import { Card, Button, Tag, Spinner, Empty, Tooltip } from '../components/ui';
import { cohortApi, qualityApi, favoritesApi, notificationsApi } from '../api/client';
import type { CohortSummary } from '../types';

interface Props {
  selectedCdm: string | null;
}

const TYPE_ICONS: Record<string, string> = {
  mapping_review: '🗺️',
  mapping_applied: '🗺️',
  quality_done: '✅',
  cohort_shared: '👥',
  cohort_deleted: '🗑️',
  cohort_updated: '✏️',
  access_request: '🔑',
  access_granted: '🔓',
  access_revoked: '🔒',
  cdm_created: '🗄️',
  cdm_updated: '⚙️',
  cdm_deleted: '🗑️',
  extraction_done: '📦',
  group_added: '👥',
  group_removed: '👤',
};

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

export default function HomePage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [favorites, setFavorites] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [qualitySummary, setQualitySummary] = useState<any>(null);
  const [notifications, setNotifications] = useState<any[]>([]);

  useEffect(() => {
    if (!selectedCdm) return;
    setLoading(true);
    Promise.all([
      cohortApi.list(selectedCdm).then(r => setCohorts(r.data.cohorts.slice(0, 5))).catch(() => {}),
      favoritesApi.list().then(r => setFavorites(r.data.favorites)).catch(() => {}),
      qualityApi.getLatestSnapshot(selectedCdm, 'Dashboard')
        .then(r => setQualitySummary(r.data.results))
        .catch(() => setQualitySummary(null)),
      notificationsApi.list(false, 10)
        .then(r => setNotifications(r.data.notifications))
        .catch(() => setNotifications([])),
    ]).finally(() => setLoading(false));
  }, [selectedCdm]);

  const removeFavorite = async (id: number) => {
    try {
      await favoritesApi.remove(id);
      setFavorites(prev => prev.filter(f => f.id !== id));
    } catch {
      // silently fail
    }
  };

  // Real-time: prepend new notifications from WebSocket
  useEffect(() => {
    const onNotif = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail) {
        setNotifications(prev => [detail, ...prev].slice(0, 20));
      }
    };
    window.addEventListener('opal:notification', onNotif);
    return () => window.removeEventListener('opal:notification', onNotif);
  }, []);

  const markNotifRead = async (id: number) => {
    try {
      await notificationsApi.markRead(id);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
      window.dispatchEvent(new Event('opal:badges-refresh'));
    } catch {}
  };

  const markAllNotifsRead = async () => {
    try {
      await notificationsApi.markAllRead();
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
      window.dispatchEvent(new Event('opal:badges-refresh'));
    } catch {}
  };

  const navigateToFavorite = (f: any) => {
    switch (f.item_type) {
      case 'cohort':
        navigate('/cohorts', { state: { openCohortId: Number(f.item_id) } });
        break;
      case 'query':
        navigate('/cohorts', { state: { tab: 'sql' } });
        break;
      case 'concept':
        navigate('/concepts', { state: { conceptId: f.item_id } });
        break;
      default:
        break;
    }
  };

  const navigateToNotif = (n: any) => {
    if (!n.read) markNotifRead(n.id);
    if (n.link) navigate(n.link);
  };

  if (!selectedCdm) {
    return (
      <div className="flex flex-col items-center justify-center text-center mt-20 px-6">
        <Database className="h-16 w-16 text-text-dim mb-4" />
        <h3 className="text-xl font-semibold text-text-bright mb-2">
          {t('dashboard.welcome', 'Welcome to OPAL')}
        </h3>
        <p className="text-text-muted">
          {t('dashboard.select_cdm', 'Select a CDM database from the sidebar to get started.')}
        </p>
      </div>
    );
  }

  const dashData = qualitySummary?.summary;
  const unreadCount = notifications.filter(n => !n.read).length;

  return (
    <div className="py-3 flex flex-col" style={{ height: 'calc(100vh - 56px - 16px)' }}>
      {/* Header */}
      <div className="flex items-center gap-3 mb-3 flex-shrink-0">
        <LayoutDashboard className="h-6 w-6 text-emerald-accent" />
        <h3 className="text-xl font-semibold text-text-bright m-0">
          {t('dashboard.title', 'Dashboard')}
        </h3>
        <Tag color="blue">{selectedCdm}</Tag>
      </div>

      {loading ? (
        <div className="flex items-center justify-center flex-1">
          <Spinner size="large" />
        </div>
      ) : (
        <div className="flex flex-col flex-1 min-h-0 gap-3">
          {/* Domain Overview — prominent grid */}
          {dashData?.domains && (
            <div className="flex-shrink-0">
              <div className="grid grid-cols-5 xl:grid-cols-9 gap-2">
                {/* Total persons — highlighted */}
                <div className="flex flex-col justify-center px-4 py-3 rounded-2xl bg-surface border border-emerald-accent/30 shadow-[0_0_15px_rgba(16,185,129,0.08)]">
                  <div className="flex items-center gap-2 mb-1">
                    <Users className="h-4 w-4 text-emerald-accent" />
                    <span className="text-[10px] uppercase tracking-wider text-text-dim">Total</span>
                  </div>
                  <div className="text-xl font-bold text-text-bright leading-tight">{dashData.total_persons?.toLocaleString() ?? '---'}</div>
                  <div className="text-[10px] text-text-dim mt-0.5">persons</div>
                </div>
                {/* Domain cards */}
                {dashData.domains.map((d: any) => (
                  <div
                    key={d.domain}
                    className="flex flex-col justify-center px-3 py-3 rounded-2xl bg-surface border border-border-subtle cursor-pointer hover:border-border-glow hover:bg-emerald-accent/5 transition-all"
                    onClick={() => navigate('/quality')}
                  >
                    <div className="text-[10px] uppercase tracking-wider text-text-dim mb-1">{String(t(`domains.${d.domain}`, d.domain))}</div>
                    <div className="text-base font-bold text-text-bright leading-tight">{d.distinct_persons?.toLocaleString()}</div>
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className="text-[9px] text-text-dim">{d.total_records?.toLocaleString()} rec.</span>
                      {d.pct_terms_mapped != null && (
                        <Tag
                          color={d.pct_terms_mapped > 80 ? 'green' : d.pct_terms_mapped > 50 ? 'orange' : 'red'}
                          style={{ fontSize: 8, padding: '0 4px', lineHeight: '16px' }}
                        >
                          {d.pct_terms_mapped}%
                        </Tag>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Main content: 2 columns — capped height so overview breathes */}
          <div className="grid grid-cols-2 gap-2 min-h-0" style={{ flex: '1 1 0', maxHeight: 'calc(100vh - 56px - 16px - 160px)' }}>
            {/* Left column: Recent Cohorts + Favorites */}
            <div className="flex flex-col gap-2 min-h-0">
              <Card
                size="small"
                className="flex flex-col overflow-hidden flex-1 min-h-0"
                bodyClassName="!p-3 !pt-2"
                title={
                  <span className="inline-flex items-center gap-2">
                    <Users className="h-4 w-4 text-emerald-accent" />
                    {t('dashboard.recent_cohorts', 'Recent Cohorts')}
                  </span>
                }
                extra={
                  <Button variant="link" size="small" onClick={() => navigate('/cohorts')}>
                    {t('dashboard.view_all', 'View All')} <ArrowRight className="h-3 w-3" />
                  </Button>
                }
              >
                {cohorts.length === 0 ? (
                  <Empty description={t('dashboard.no_cohorts', 'No cohorts yet')}>
                    <Button variant="primary" size="small" onClick={() => navigate('/cohorts')}>
                      {t('dashboard.create_cohort', 'Create a Cohort')}
                    </Button>
                  </Empty>
                ) : (
                  <div className="overflow-y-auto flex-1">
                    {cohorts.map((c) => (
                      <div
                        key={c.id}
                        className="flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer hover:bg-emerald-accent/5 transition-colors"
                        onClick={() => navigate('/cohorts', { state: { openCohortId: c.id } })}
                      >
                        <div>
                          <div className="text-sm font-medium text-text-bright">{c.name}</div>
                          <div className="flex items-center gap-1.5 text-xs text-text-dim">
                            <Clock className="h-3 w-3" />
                            <span>v{c.latest_version}</span>
                          </div>
                        </div>
                        {c.patient_count != null && (
                          <Tag color="blue">{c.patient_count.toLocaleString()} pts</Tag>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card
                size="small"
                className="flex flex-col overflow-hidden flex-1 min-h-0"
                bodyClassName="!p-3 !pt-2"
                title={
                  <span className="inline-flex items-center gap-2">
                    <Star className="h-4 w-4 text-yellow-400" />
                    {t('dashboard.favorites_title', 'Favorites')}
                  </span>
                }
              >
                {favorites.length === 0 ? (
                  <Empty
                    description={t('dashboard.no_favorites', 'No favorites yet. Star items from other pages.')}
                  />
                ) : (
                  <div className="overflow-y-auto flex-1">
                    {favorites.slice(0, 10).map((f) => (
                      <div
                        key={f.id}
                        className="flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer hover:bg-emerald-accent/5 transition-colors"
                        onClick={() => navigateToFavorite(f)}
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="text-text-dim">
                            {f.item_type === 'cohort' ? <Users className="h-4 w-4" /> :
                             f.item_type === 'query' ? <Code className="h-4 w-4" /> :
                             <Heart className="h-4 w-4" />}
                          </span>
                          <div>
                            <div className="text-sm font-medium text-text-bright">
                              {f.item_label || f.item_id}
                            </div>
                            <span className="text-xs text-text-dim">{f.item_type}</span>
                          </div>
                        </div>
                        <Tooltip title="Remove">
                          <Button
                            variant="danger"
                            size="small"
                            icon={<Trash2 className="h-3.5 w-3.5" />}
                            onClick={(e) => { e.stopPropagation(); removeFavorite(f.id); }}
                          />
                        </Tooltip>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            {/* Right column: Quick Actions (compact) + Notifications (flex) */}
            <div className="flex flex-col gap-2 min-h-0">
              {/* Quick Actions */}
              <Card
                size="small"
                className="flex-shrink-0"
                bodyClassName="!p-3 !pt-2"
                title={
                  <span className="inline-flex items-center gap-2">
                    <Activity className="h-4 w-4 text-emerald-accent" />
                    {t('dashboard.quick_actions', 'Quick Actions')}
                  </span>
                }
              >
                <div className="grid grid-cols-2 gap-1.5">
                  <Button variant="ghost" size="small" icon={<Users className="h-4 w-4" />} onClick={() => navigate('/cohorts')} className="justify-start">
                    {t('dashboard.new_cohort', 'New Cohort')}
                  </Button>
                  <Button variant="ghost" size="small" icon={<Activity className="h-4 w-4" />} onClick={() => navigate('/quality')} className="justify-start">
                    {t('dashboard.run_quality', 'Quality Analysis')}
                  </Button>
                  <Button variant="ghost" size="small" icon={<FolderOpen className="h-4 w-4" />} onClick={() => navigate('/data-management')} className="justify-start">
                    {t('dashboard.extract_data', 'Extract Dataset')}
                  </Button>
                  <Button variant="ghost" size="small" icon={<Code className="h-4 w-4" />} onClick={() => navigate('/cohorts')} className="justify-start">
                    {t('dashboard.sql_editor', 'SQL Editor')}
                  </Button>
                </div>
              </Card>

              {/* Notifications — scrollable */}
              <Card
                size="small"
                className="flex flex-col overflow-hidden flex-1 min-h-0"
                bodyClassName="!p-3 !pt-2"
                title={
                  <span className="inline-flex items-center gap-2">
                    <Bell className="h-4 w-4 text-emerald-accent" />
                    Notifications
                    {unreadCount > 0 && (
                      <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-none">
                        {unreadCount}
                      </span>
                    )}
                  </span>
                }
                extra={
                  unreadCount > 0 ? (
                    <Tooltip title="Mark all read">
                      <Button variant="link" size="small" icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={markAllNotifsRead} />
                    </Tooltip>
                  ) : null
                }
              >
                {notifications.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-4 text-text-dim text-xs">
                    <Bell className="h-8 w-8 mb-2 opacity-30" />
                    No notifications
                  </div>
                ) : (
                  <div className="overflow-y-auto flex-1">
                    {notifications.map((n) => (
                      <div
                        key={n.id}
                        className={`flex items-start gap-2 px-2.5 py-1.5 rounded-lg transition-colors text-xs ${
                          n.link ? 'cursor-pointer hover:bg-emerald-accent/5' : ''
                        } ${!n.read ? 'bg-emerald-accent/[0.03]' : ''}`}
                        onClick={() => n.link && navigateToNotif(n)}
                      >
                        <div className="flex-shrink-0 mt-1.5">
                          {!n.read ? (
                            <span className="block w-2 h-2 rounded-full bg-red-500" />
                          ) : (
                            <span className="block w-2 h-2" />
                          )}
                        </div>
                        <span className="flex-shrink-0 mt-0.5 text-sm">
                          {TYPE_ICONS[n.type] || '📌'}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className={`font-medium truncate ${!n.read ? 'text-text-bright' : 'text-text-muted'}`}>
                            {n.title}
                          </div>
                          {n.message && (
                            <div className="text-text-dim truncate text-[11px]">{n.message}</div>
                          )}
                        </div>
                        <div className="flex-shrink-0 flex items-center gap-1 text-text-dim">
                          {n.created_at && (
                            <span className="text-[10px]">{timeAgo(n.created_at)}</span>
                          )}
                          {n.link && <ExternalLink className="h-3 w-3 opacity-40" />}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </div>        </div>
      )}
    </div>
  );
}
