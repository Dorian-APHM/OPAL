import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Users, Star, Database, Activity, ArrowRight, Trash2,
  LayoutDashboard, Clock, Heart, Code, FolderOpen,
  BookOpen, GitMerge, FileText, Layers, TrendingUp,
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Card, Button, Tag, Empty, Tooltip as UiTooltip, FadeIn, CountUp, DashboardSkeleton, useToast } from '../components/ui';
import { qualityApi, favoritesApi, recentApi } from '../api/client';
import { useAuth } from '../auth/KeycloakContext';
import { useChartTheme } from '../hooks/useChartTheme';

// ── Types ──

interface Props { selectedCdm: string | null; }

interface RecentItem {
  id: string;
  label: string;
  type: 'cohort' | 'mapping';
  timestamp: string;
  onClick: () => void;
}

// ── Constants ──

const RECENT_TYPE_ICON: Record<RecentItem['type'], React.ReactNode> = {
  cohort: <Users className="h-4 w-4" />,
  mapping: <FolderOpen className="h-4 w-4" />,
};

const QUICK_ACTION_CONFIG = [
  { key: 'new_cohort',       i18nKey: 'dashboard.new_cohort',       fallback: 'New Cohort',       Icon: Users,      route: '/cohorts',         navState: undefined },
  { key: 'sql_editor',       i18nKey: 'dashboard.sql_editor',       fallback: 'SQL Editor',       Icon: Code,       route: '/cohorts',         navState: { tab: 'sql' } },
  { key: 'run_quality',      i18nKey: 'dashboard.run_quality',      fallback: 'Quality Analysis', Icon: Activity,   route: '/quality',         navState: undefined },
  { key: 'extract_data',     i18nKey: 'dashboard.extract_data',     fallback: 'Extract Dataset',  Icon: FolderOpen, route: '/data-management', navState: undefined },
  { key: 'mapping',          i18nKey: 'dashboard.mapping',          fallback: 'Mapping',          Icon: GitMerge,   route: '/mapping',         navState: undefined },
  { key: 'explore_concepts', i18nKey: 'dashboard.explore_concepts', fallback: 'Explore Concepts', Icon: BookOpen,   route: '/concepts',        navState: undefined },
] as const;

// ── Helpers ──

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

function pctColor(pct: number): [number, number, number] {
  // Red stays red longer (0-40%), yellow narrow band (40-60%), green from 60%+
  if (pct <= 40) {
    // Pure red → slight orange
    const t = pct / 40;
    return [
      239,
      Math.round(68 + t * 60),   // 68 → 128
      Math.round(68 - t * 40),   // 68 → 28
    ];
  }
  if (pct <= 60) {
    // Orange → yellow
    const t = (pct - 40) / 20;
    return [
      Math.round(239 - t * 5),   // 239 → 234
      Math.round(128 + t * 51),  // 128 → 179
      Math.round(28 - t * 20),   // 28 → 8
    ];
  }
  // Yellow → green
  const t = (pct - 60) / 40;
  return [
    Math.round(234 - t * 200),   // 234 → 34
    Math.round(179 + t * 18),    // 179 → 197
    Math.round(8 + t * 86),      // 8 → 94
  ];
}

function BarGradientShape(props: any) {
  const { x, y, width, height, pct } = props;
  const c = pctColor(pct);
  // Opacity scales with pct: low pct = faint, high pct = vivid
  const opStart = 0.3 + (pct / 100) * 0.3;  // 0.3 → 0.6
  const opEnd = 0.5 + (pct / 100) * 0.4;    // 0.5 → 0.9
  const id = `bar-g-${Math.round(x)}-${Math.round(y)}`;
  return (
    <g>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={`rgb(${c[0]},${c[1]},${c[2]})`} stopOpacity={opStart} />
          <stop offset="100%" stopColor={`rgb(${c[0]},${c[1]},${c[2]})`} stopOpacity={opEnd} />
        </linearGradient>
      </defs>
      <rect x={x} y={y} width={width} height={height} rx={6} ry={6} fill={`url(#${id})`} />
    </g>
  );
}

// ── KPI Card ──

function KpiCard({ icon, label, value, sub }: {
  icon: React.ReactNode; label: string; value: React.ReactNode; sub?: string;
}) {
  return (
    <div className="flex flex-col justify-center px-4 py-3 rounded-2xl bg-surface border border-border-subtle opal-card-shadow h-full">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-[10px] uppercase tracking-wider text-text-dim">{label}</span>
      </div>
      <div className="text-xl font-bold text-text-bright leading-tight">{value}</div>
      {sub && <div className="text-[10px] text-text-dim mt-0.5">{sub}</div>}
    </div>
  );
}

// ── Main Component ──

export default function HomePage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const { hasPageAccess } = useAuth();
  const ct = useChartTheme();

  const [favorites, setFavorites] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [qualitySummary, setQualitySummary] = useState<any>(null);
  const [recentItems, setRecentItems] = useState<RecentItem[]>([]);

  useEffect(() => {
    if (!selectedCdm) return;
    setLoading(true);
    Promise.all([
      favoritesApi.list()
        .then(r => setFavorites(r.data.favorites))
        .catch(() => toast.error(t('dashboard.load_failed', 'Failed to load favorites'))),
      qualityApi.getLatestSnapshot(selectedCdm, 'Dashboard')
        .then(r => setQualitySummary(r.data.results))
        .catch(() => setQualitySummary(null)),
      recentApi.list(selectedCdm)
        .then(r => setRecentItems(
          r.data.items.map(item => ({
            id: `${item.type}-${item.timestamp}`,
            label: item.label,
            type: item.type,
            timestamp: item.timestamp,
            onClick: () => navigate(item.route, item.nav_state ? { state: item.nav_state } : undefined),
          }))
        ))
        .catch(() => setRecentItems([])),
    ]).finally(() => setLoading(false));
  }, [selectedCdm]);

  const removeFavorite = async (id: number) => {
    try {
      await favoritesApi.remove(id);
      setFavorites(prev => prev.filter(f => f.id !== id));
    } catch {
      toast.error(t('common.error', 'An error occurred'));
    }
  };

  const navigateToFavorite = (f: any) => {
    switch (f.item_type) {
      case 'cohort':  navigate('/cohorts', { state: { openCohortId: Number(f.item_id) } }); break;
      case 'query':   navigate('/cohorts', { state: { tab: 'sql' } }); break;
      case 'concept': navigate('/concepts', { state: { conceptId: f.item_id } }); break;
    }
  };

  // ── Derived data ──

  const dashData = qualitySummary?.summary;
  const domains: any[] = dashData?.domains || [];
  const visibleActions = QUICK_ACTION_CONFIG.filter(a => hasPageAccess(a.route));

  const kpis = useMemo(() => {
    if (!dashData) return null;
    const totalPersons = dashData.total_persons || 0;
    const totalRecords = domains.reduce((s: number, d: any) => s + (d.total_records || 0), 0);
    const totalTerms = domains.reduce((s: number, d: any) => s + (d.total_terms || 0), 0);
    const mappedTerms = domains.reduce((s: number, d: any) => s + (d.mapped_terms || 0), 0);
    const unmappedTerms = totalTerms - mappedTerms;
    const mappingRate = totalTerms > 0 ? Math.round(mappedTerms / totalTerms * 100) : 0;
    const activeDomains = domains.filter((d: any) => d.total_records > 0).length;
    const recordsPerPerson = totalPersons > 0 ? Math.round(totalRecords / totalPersons) : 0;
    return { totalRecords, mappingRate, mappedTerms, unmappedTerms, activeDomains, totalDomains: domains.length, recordsPerPerson };
  }, [dashData, domains]);

  const mappingChartData = useMemo(
    () => domains
      .filter((d: any) => d.total_records > 0)
      .map((d: any) => ({ name: d.domain, pct: Math.round(d.pct_terms_mapped ?? 0) }))
      .sort((a: any, b: any) => b.pct - a.pct),
    [domains],
  );

  // ── Empty CDM state ──

  if (!selectedCdm) {
    return (
      <div className="flex items-center justify-center" style={{ height: 'calc(100vh - 56px - 32px)' }}>
        <Empty variant="no-cdm">
          <Button variant="primary" size="middle" icon={<Database className="h-4 w-4" />} onClick={() => {}}>
            {t('dashboard.select_cdm', 'Select a CDM database')}
          </Button>
        </Empty>
      </div>
    );
  }

  // ── Render ──

  return (
    <div className="py-3 flex flex-col overflow-y-auto gap-3" style={{ height: 'calc(100vh - 56px - 16px)' }}>

      {/* Header */}
      <div className="flex items-center gap-3 flex-shrink-0">
        <LayoutDashboard className="h-6 w-6 text-emerald-accent" />
        <h3 className="text-xl font-semibold text-text-bright m-0">{t('dashboard.title', 'Dashboard')}</h3>
        <Tag color="blue">{selectedCdm}</Tag>
      </div>

      {loading ? <DashboardSkeleton /> : (
        <div className="flex flex-col flex-1 min-h-0 gap-3">

          {/* ── Row 1 : 4 KPI cards ── */}
          {kpis && (
            <FadeIn className="flex-shrink-0">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <KpiCard
                  icon={<Users className="h-4 w-4 text-emerald-accent" />}
                  label={t('dashboard.total_persons', 'Total Persons')}
                  value={dashData.total_persons != null
                    ? <CountUp end={dashData.total_persons} format={(n: number) => n.toLocaleString()} />
                    : '---'}
                />
                <KpiCard
                  icon={<FileText className="h-4 w-4 text-blue-400" />}
                  label={t('dashboard.total_records', 'Total Records')}
                  value={<CountUp end={kpis.totalRecords} format={(n: number) => n.toLocaleString()} />}
                />
                <KpiCard
                  icon={<TrendingUp className="h-4 w-4 text-orange-400" />}
                  label={t('dashboard.records_per_person', 'Records / Person')}
                  value={<CountUp end={kpis.recordsPerPerson} format={(n: number) => n.toLocaleString()} />}
                  sub={t('dashboard.data_density', 'data density')}
                />
                <KpiCard
                  icon={<Layers className="h-4 w-4 text-purple-400" />}
                  label={t('dashboard.active_domains', 'Active Domains')}
                  value={`${kpis.activeDomains} / ${kpis.totalDomains}`}
                />
              </div>
            </FadeIn>
          )}

          {/* ── Row 2 : Mapping chart (2/3) + Mapping stats (1/3) ── */}
          <FadeIn delay={0.1} className="flex-shrink-0">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3" style={{ minHeight: 260 }}>

              {/* Horizontal bar chart — mapping % per domain */}
              <Card
                size="small"
                className="md:col-span-2 flex flex-col"
                bodyClassName="!p-3 !pt-1 flex-1"
                title={
                  <span className="inline-flex items-center gap-2">
                    <GitMerge className="h-4 w-4 text-emerald-accent" />
                    {t('dashboard.mapping_by_domain', 'Mapping by Domain')}
                  </span>
                }
              >
                {mappingChartData.length === 0 ? (
                  <Empty variant="no-data" className="py-6" />
                ) : (
                  <ResponsiveContainer width="100%" height={Math.max(mappingChartData.length * 32, 120)}>
                    <BarChart data={mappingChartData} layout="vertical" margin={{ left: 10, right: 30, top: 4, bottom: 4 }}>
                      <XAxis type="number" domain={[0, 100]} tick={{ fill: ct.axis, fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="name" width={110} tick={{ fill: ct.label, fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip
                        cursor={false}
                        contentStyle={{ ...ct.tooltipStyle, color: '#fff' }}
                        labelStyle={{ color: '#fff' }}
                        itemStyle={{ color: '#fff' }}
                        formatter={(v: number) => [`${v}%`, 'Mapped']}
                      />
                      <Bar
                        dataKey="pct"
                        barSize={18}
                        shape={(props: any) => <BarGradientShape {...props} pct={props.pct ?? props.payload?.pct ?? 0} />}
                        activeBar={(props: any) => {
                          const grow = 10;
                          return <BarGradientShape {...props} y={props.y - grow / 2} height={props.height + grow} pct={props.pct ?? props.payload?.pct ?? 0} />;
                        }}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </Card>

              {/* Domain Overview */}
              <Card
                size="small"
                className="flex flex-col overflow-hidden"
                bodyClassName="!p-0 flex-1 overflow-auto"
                title={
                  <span className="inline-flex items-center gap-2">
                    <Layers className="h-4 w-4 text-blue-400" />
                    {t('dashboard.domain_overview', 'Domain Overview')}
                    <span className="text-[10px] text-text-dim font-normal">{t('dashboard.sorted_by_records', 'Sorted by records desc')}</span>
                  </span>
                }
              >
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-subtle text-text-muted">
                      <th className="text-left px-2.5 py-1.5 font-medium">{t('dashboard.domain', 'Domain')}</th>
                      <th className="text-right px-2.5 py-1.5 font-medium">{t('dashboard.records', 'Records')}</th>
                      <th className="text-right px-2.5 py-1.5 font-medium">{t('dashboard.persons', 'Persons')}</th>
                      <th className="text-right px-2.5 py-1.5 font-medium">{t('dashboard.mapped_pct', 'Mapped %')}</th>
                      <th className="text-center px-2.5 py-1.5 font-medium">{t('dashboard.status', 'Status')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...domains]
                      .filter((d: any) => d.total_records > 0)
                      .sort((a: any, b: any) => (b.total_records || 0) - (a.total_records || 0))
                      .map((d: any) => {
                        const pct = Math.round(d.pct_terms_mapped ?? 0);
                        const status = pct >= 80 ? 'OK' : pct >= 50 ? 'WARN' : 'CRIT';
                        const statusColor = status === 'OK' ? 'text-emerald-400' : status === 'WARN' ? 'text-yellow-400' : 'text-red-400';
                        const statusBg = status === 'OK' ? 'bg-emerald-400/10' : status === 'WARN' ? 'bg-yellow-400/10' : 'bg-red-400/10';
                        return (
                          <tr key={d.domain} className="border-b border-border-subtle/50 hover:bg-surface-dark/50 transition-colors">
                            <td className="px-2.5 py-1.5 text-text-bright font-medium">{d.domain}</td>
                            <td className="px-2.5 py-1.5 text-right text-text-muted tabular-nums">{(d.total_records || 0).toLocaleString()}</td>
                            <td className="px-2.5 py-1.5 text-right text-text-muted tabular-nums">{(d.distinct_persons || 0).toLocaleString()}</td>
                            <td className="px-2.5 py-1.5 text-right tabular-nums" style={{ color: `rgb(${pctColor(pct).join(',')})` }}>{pct}%</td>
                            <td className="px-2.5 py-1.5 text-center">
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${statusColor} ${statusBg}`}>
                                {status}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </Card>
            </div>
          </FadeIn>

          {/* ── Row 3 : Quick Actions + Favorites + Recent ── */}
          <FadeIn delay={0.2} className="grid grid-cols-1 md:grid-cols-3 gap-3 flex-shrink-0">

            {/* Quick Actions */}
            <Card
              size="small"
              bodyClassName="!p-3 !pt-2"
              title={
                <span className="inline-flex items-center gap-2">
                  <Activity className="h-4 w-4 text-emerald-accent" />
                  {t('dashboard.quick_actions', 'Quick Actions')}
                </span>
              }
            >
              {visibleActions.length === 0 ? (
                <Empty variant="no-data" />
              ) : (
                <div className="grid grid-cols-1 gap-1.5">
                  {visibleActions.map(({ key, i18nKey, fallback, Icon, route, navState }) => (
                    <Button
                      key={key}
                      variant="ghost"
                      size="small"
                      icon={<Icon className="h-4 w-4" />}
                      onClick={() => navigate(route, navState ? { state: navState } : undefined)}
                      className="justify-start"
                    >
                      {t(i18nKey, fallback)}
                    </Button>
                  ))}
                </div>
              )}
            </Card>

            {/* Favorites */}
            <Card
              size="small"
              bodyClassName="!p-3 !pt-2"
              title={
                <span className="inline-flex items-center gap-2">
                  <Star className="h-4 w-4 text-yellow-400" />
                  {t('dashboard.favorites_title', 'Favorites')}
                </span>
              }
            >
              {favorites.length === 0 ? (
                <Empty variant="no-favorites" />
              ) : (
                favorites.slice(0, 10).map(f => (
                  <div
                    key={f.id}
                    className="flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer hover:bg-emerald-accent/5 transition-colors"
                    onClick={() => navigateToFavorite(f)}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <span className="text-text-dim flex-shrink-0">
                        {f.item_type === 'cohort' ? <Users className="h-4 w-4" /> :
                         f.item_type === 'query'  ? <Code className="h-4 w-4" /> :
                         <Heart className="h-4 w-4" />}
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-text-bright truncate">{f.item_label || f.item_id}</div>
                        <span className="text-xs text-text-dim">{f.item_type}</span>
                      </div>
                    </div>
                    <UiTooltip title="Remove">
                      <Button
                        variant="danger"
                        size="small"
                        icon={<Trash2 className="h-3.5 w-3.5" />}
                        onClick={e => { e.stopPropagation(); removeFavorite(f.id); }}
                      />
                    </UiTooltip>
                  </div>
                ))
              )}
            </Card>

            {/* Recent */}
            <Card
              size="small"
              bodyClassName="!p-3 !pt-2"
              title={
                <span className="inline-flex items-center gap-2">
                  <Clock className="h-4 w-4 text-emerald-accent" />
                  {t('dashboard.recent', 'Recent')}
                </span>
              }
            >
              {recentItems.length === 0 ? (
                <Empty variant="no-data" />
              ) : (
                recentItems.map(item => (
                  <div
                    key={item.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer hover:bg-emerald-accent/5 transition-colors"
                    onClick={item.onClick}
                  >
                    <span className="text-text-dim flex-shrink-0">{RECENT_TYPE_ICON[item.type]}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-text-bright truncate">{item.label}</div>
                      <span className="text-xs text-text-dim capitalize">{item.type}</span>
                    </div>
                    <span className="text-[10px] text-text-dim flex-shrink-0">{timeAgo(item.timestamp)}</span>
                    <ArrowRight className="h-3 w-3 text-text-dim opacity-40 flex-shrink-0" />
                  </div>
                ))
              )}
            </Card>
          </FadeIn>

        </div>
      )}
    </div>
  );
}
