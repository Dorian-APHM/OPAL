import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Home, LayoutDashboard, Users, GitCompareArrows, BookOpen, FlaskConical,
  Database, Settings, Globe, LogOut, Shield, ClipboardList, HardDrive,
  Menu, X, ChevronDown, Bell, Sun, Moon, Search, GitBranch,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi, cdmAccessApi, notificationsApi, ohdsiApi } from '../../api/client';
import type { CdmConfig } from '../../types';
import { useAuth } from '../../auth/KeycloakContext';
import { useNotificationWs } from '../../hooks/useNotificationWs';
import { Select } from '../ui/Select';
import { Tag } from '../ui/Tag';
import { Tooltip } from '../ui/Tooltip';
import GlobalSearch from '../GlobalSearch';
import NotificationCenter from '../NotificationCenter';
import { useTheme } from '../../hooks/useTheme';
import { useToast } from '../ui/Toast';

interface TopNavProps {
  selectedCdm: string | null;
  onCdmChange: (cdm: string) => void;
}

/* Main nav: shown in the top bar with icon + short label */
const mainNav = [
  { key: '/', icon: Home, labelKey: 'app.home', labelDefault: 'Home', short: 'Home' },
  { key: '/quality', icon: LayoutDashboard, labelKey: 'app.quality', short: 'Quality' },
  { key: '/cohorts', icon: Users, labelKey: 'app.cohorts', short: 'Cohorts' },
  { key: '/data-management', icon: HardDrive, labelKey: 'app.data_management', labelDefault: 'Data Export', short: 'Data Export' },
  { key: '/mapping', icon: GitCompareArrows, labelKey: 'app.mapping', short: 'Mapping' },
  { key: '/concepts', icon: BookOpen, labelKey: 'app.concepts', short: 'Concepts' },
  { key: '/ohdsi', icon: FlaskConical, labelKey: 'app.ohdsi', labelDefault: 'OHDSI', short: 'OHDSI' },
  { key: '/lineage', icon: GitBranch, labelKey: 'app.lineage', labelDefault: 'Lineage', short: 'Lineage' },
];

/* Admin nav: shown inside the user dropdown */
const adminNav = [
  { key: '/cdm', icon: Database, labelKey: 'cdm.title' },
  { key: '/settings', icon: Settings, labelKey: 'app.settings' },
  { key: '/audit', icon: ClipboardList, labelKey: 'app.audit' },
  { key: '/users', icon: Shield, labelKey: 'app.users' },
];

/* Map backend notification tab names → route keys */
const TAB_TO_ROUTE: Record<string, string> = {
  quality: '/quality',
  cohorts: '/cohorts',
  mapping: '/mapping',
  users: '/users',
  data: '/data-management',
};

const roleColors: Record<string, 'red' | 'purple' | 'blue' | 'green' | 'default'> = {
  admin: 'red',
  'data-manager': 'purple',
  chercheur: 'blue',
  medecin: 'green',
};

/** Small red dot with optional count */
function NotifDot({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white shadow-[0_0_6px_rgba(239,68,68,0.5)] leading-none">
      {count > 99 ? '99+' : count}
    </span>
  );
}

export default function TopNav({ selectedCdm, onCdmChange }: TopNavProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [notifCenterOpen, setNotifCenterOpen] = useState(false);
  const { username, roles, logout, hasPageAccess, authenticated, token } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();

  // --- WebSocket for real-time notifications ---
  useNotificationWs(!!authenticated && !!token);
  const toast = useToast();

  // --- Global toast for background analysis notifications ---
  useEffect(() => {
    const handler = (e: Event) => {
      const notif = (e as CustomEvent).detail;
      if (!notif?.title) return;
      if (notif.type === 'quality_done' || notif.type === 'conformity_done') {
        toast.success(notif.title);
      }
    };
    window.addEventListener('opal:notification', handler);
    return () => window.removeEventListener('opal:notification', handler);
  }, [toast]);

  // --- Notification badges ---
  const [badges, setBadges] = useState<Record<string, number>>({});
  const fetchingBadges = useRef(false);

  const refreshBadges = useCallback(() => {
    if (fetchingBadges.current || !authenticated || !token) return;
    fetchingBadges.current = true;
    notificationsApi.badges()
      .then(res => setBadges(res.data.badges || {}))
      .catch(() => {})
      .finally(() => { fetchingBadges.current = false; });
  }, [authenticated, token]);

  useEffect(() => {
    refreshBadges();
    const onRefresh = () => refreshBadges();
    window.addEventListener('opal:badges-refresh', onRefresh);
    // Refresh only when user returns to the tab (no polling — WS is real-time)
    window.addEventListener('focus', onRefresh);
    return () => {
      window.removeEventListener('opal:badges-refresh', onRefresh);
      window.removeEventListener('focus', onRefresh);
    };
  }, [refreshBadges]);

  // Build route → count map from backend tab-based badges
  const routeBadges = useMemo(() => {
    const map: Record<string, number> = {};
    for (const [tab, count] of Object.entries(badges)) {
      const route = TAB_TO_ROUTE[tab];
      if (route && count > 0) map[route] = (map[route] || 0) + count;
    }
    return map;
  }, [badges]);

  // Admin routes that live in the user dropdown — sum their badges for the avatar dot
  const adminBadgeTotal = useMemo(() => {
    return adminNav.reduce((sum, item) => sum + (routeBadges[item.key] || 0), 0);
  }, [routeBadges]);

  useEffect(() => {
    if (authenticated && token) {
      // Use CDM access control: non-admin users only see CDMs they have access to
      cdmAccessApi.getAccessibleCdms()
        .then((res) => setCdms(res.data.cdms.map((name: string) => ({ name } as CdmConfig))))
        .catch(() => {
          // Fallback to full list if access control endpoint fails
          cdmApi.list().then((r) => setCdms(r.data.cdms)).catch(() => {});
        });
    }
  }, [authenticated, token]);

  // OHDSI is opt-in (server-side OHDSI_MODE). Hide its nav item unless enabled.
  const [ohdsiEnabled, setOhdsiEnabled] = useState(false);
  useEffect(() => {
    if (authenticated && token) {
      ohdsiApi.config()
        .then((res) => setOhdsiEnabled(!!res.data.enabled))
        .catch(() => setOhdsiEnabled(false));
    }
  }, [authenticated, token]);

  // /ohdsi is shown only when the server reports OHDSI enabled.
  const isVisible = useCallback(
    (key: string) => hasPageAccess(key) && (key !== '/ohdsi' || ohdsiEnabled),
    [hasPageAccess, ohdsiEnabled]
  );

  const mainItems = useMemo(
    () => mainNav.filter((item) => isVisible(item.key)),
    [roles, isVisible, i18n.language]
  );

  const adminItems = useMemo(
    () => adminNav.filter((item) => hasPageAccess(item.key)),
    [roles, hasPageAccess, i18n.language]
  );

  const allItems = useMemo(
    () => [...mainNav, ...adminNav].filter((item) => isVisible(item.key)),
    [roles, isVisible, i18n.language]
  );

  const toggleLang = () => {
    const newLang = i18n.language === 'fr' ? 'en' : 'fr';
    i18n.changeLanguage(newLang);
    localStorage.setItem('opal-lang', newLang);
  };

  const isActive = (key: string) =>
    key === '/' ? location.pathname === '/' : location.pathname.startsWith(key);

  return (
    <nav className="glass-nav fixed top-0 left-0 right-0 z-50 px-3 lg:px-4 py-2">
      <div className="mx-auto flex items-center gap-2 lg:gap-3 max-w-[1920px]">
        {/* Logo */}
        <a href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }} className="flex items-center no-underline shrink-0">
          <img src="/opal-logo.svg" alt="OPAL" className="h-12 w-12 object-contain" />
        </a>

        <div className="w-px h-5 bg-glass-border hidden lg:block shrink-0" />

        {/* CDM Selector */}
        <div className="hidden lg:block shrink-0 w-56">
          <Select
            placeholder={t('cdm.select_cdm')}
            value={selectedCdm}
            onChange={onCdmChange}
            options={cdms.map((c) => ({ value: c.name, label: c.name }))}
            allowClear
            size="small"
          />
        </div>

        {/* Desktop Navigation — icon + short label for main items */}
        <div className="hidden lg:flex items-center gap-0 flex-1 justify-center min-w-0">
          {mainItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.key);
            const badge = routeBadges[item.key] || 0;

            return (
              <Tooltip key={item.key} title={item.short} placement="bottom">
                <button
                  onClick={() => navigate(item.key)}
                  className={`
                    relative flex items-center gap-1 px-1.5 py-1.5 rounded-lg text-[13px] font-medium
                    transition-all duration-200 cursor-pointer bg-transparent border-none whitespace-nowrap shrink-0
                    ${active
                      ? 'text-emerald-accent bg-emerald-accent/10'
                      : 'text-text-dim hover:text-emerald-accent hover:bg-surface-light'
                    }
                  `}
                >
                  <span className="relative">
                    <Icon className={`h-4 w-4 shrink-0 ${active ? 'drop-shadow-[0_0_6px_rgba(16,185,129,0.5)]' : ''}`} />
                    <NotifDot count={badge} />
                  </span>
                  <span className="hidden 2xl:inline">{item.short}</span>
                  {active && (
                    <span className="absolute bottom-0 left-1 right-1 h-0.5 rounded-full bg-emerald-accent shadow-[0_0_6px_rgba(16,185,129,0.4)]" />
                  )}
                </button>
              </Tooltip>
            );
          })}
        </div>

        {/* Right side: search trigger + lang + user */}
        <div className="flex items-center gap-3 shrink-0 ml-auto lg:ml-0">
          {/* Search trigger button — opens via Ctrl+K */}
          <Tooltip title="Search (⌘K)" placement="bottom">
            <button
              onClick={() => {
                // Dispatch Ctrl+K to trigger GlobalSearch focus
                window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
              }}
              className="text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none p-1.5"
            >
              <Search className="h-4 w-4" />
            </button>
          </Tooltip>

          {/* Language toggle */}
          <Tooltip title={i18n.language === 'fr' ? 'Français' : 'English'} placement="bottom">
            <button onClick={toggleLang} className="hidden sm:block text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none p-1.5">
              <Globe className="h-4 w-4" />
            </button>
          </Tooltip>

          {/* Theme toggle */}
          <Tooltip title={theme === 'dark' ? 'Light mode' : 'Dark mode'} placement="bottom">
            <button onClick={toggleTheme} className="hidden sm:block text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none p-1.5">
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </Tooltip>

          {/* Notification bell with ring animation on new notifs */}
          <Tooltip title="Notifications" placement="bottom">
            <button
              onClick={() => setNotifCenterOpen(true)}
              className="relative text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none p-1.5"
            >
              <Bell className={`h-4 w-4 ${Object.values(badges).reduce((a, b) => a + b, 0) > 0 ? 'opal-bell-ring' : ''}`} />
              <NotifDot count={Object.values(badges).reduce((a, b) => a + b, 0)} />
            </button>
          </Tooltip>

          {/* User menu — includes admin nav items */}
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              aria-label="User menu"
              aria-expanded={userMenuOpen}
              className="flex items-center gap-1.5 cursor-pointer bg-transparent border-none text-text-muted hover:text-text-bright transition-colors"
            >
              <span className="relative">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-accent to-teal-accent flex items-center justify-center text-xs font-semibold text-deep-base">
                  {username?.charAt(0).toUpperCase() ?? '?'}
                </div>
                <NotifDot count={adminBadgeTotal} />
              </span>
              <ChevronDown className="h-3 w-3 hidden sm:block" />
            </button>

            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div className="absolute right-0 mt-2 w-56 rounded-xl bg-surface border border-glass-border shadow-[0_8px_32px_rgba(0,0,0,0.4)] z-50 py-2">
                  {/* User info */}
                  <div className="px-4 py-2 border-b border-glass-border mb-1">
                    <div className="text-sm font-medium text-text-bright">{username}</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {roles.map((r) => (
                        <Tag key={r} color={roleColors[r] || 'default'} style={{ fontSize: 10 }}>{r}</Tag>
                      ))}
                    </div>
                  </div>

                  {/* Admin navigation items */}
                  {adminItems.length > 0 && (
                    <>
                      {adminItems.map((item) => {
                        const Icon = item.icon;
                        const active = isActive(item.key);
                        const badge = routeBadges[item.key] || 0;
                        return (
                          <button
                            key={item.key}
                            onClick={() => { setUserMenuOpen(false); navigate(item.key); }}
                            className={`w-full flex items-center gap-2 px-4 py-2 text-sm transition-colors cursor-pointer bg-transparent border-none text-left ${
                              active
                                ? 'text-emerald-accent bg-emerald-accent/6'
                                : 'text-text-muted hover:bg-emerald-accent/6 hover:text-emerald-accent'
                            }`}
                          >
                            <span className="relative">
                              <Icon className="h-4 w-4" />
                              <NotifDot count={badge} />
                            </span>
                            {t(item.labelKey)}
                          </button>
                        );
                      })}
                      <div className="my-1 border-t border-glass-border" />
                    </>
                  )}

                  {/* Logout */}
                  <button
                    onClick={() => { setUserMenuOpen(false); logout(); }}
                    className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-400 hover:bg-red-500/8 transition-colors cursor-pointer bg-transparent border-none text-left"
                  >
                    <LogOut className="h-4 w-4" />
                    {t('auth.logout', 'Logout')}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
            className="lg:hidden text-text-muted cursor-pointer bg-transparent border-none p-1"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Navigation Drawer — all items */}
      {mobileOpen && (
        <div className="lg:hidden mt-3 pt-3 border-t border-glass-border">
          <div className="mb-3">
            <Select
              placeholder={t('cdm.select_cdm')}
              value={selectedCdm}
              onChange={onCdmChange}
              options={cdms.map((c) => ({ value: c.name, label: c.name }))}
              allowClear
              size="small"
            />
          </div>
          <div className="grid grid-cols-2 gap-1">
            {allItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.key);
              const fallback = 'labelDefault' in item ? (item as any).labelDefault : undefined;
              const label = String(t(item.labelKey, fallback));
              const badge = routeBadges[item.key] || 0;

              return (
                <button
                  key={item.key}
                  onClick={() => { navigate(item.key); setMobileOpen(false); }}
                  className={`
                    flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium
                    transition-colors cursor-pointer bg-transparent border-none text-left
                    ${active ? 'text-emerald-accent bg-emerald-accent/10' : 'text-text-muted hover:text-emerald-accent'}
                  `}
                >
                  <span className="relative">
                    <Icon className="h-4 w-4" />
                    <NotifDot count={badge} />
                  </span>
                  {label}
                </button>
              );
            })}
          </div>
          {/* Lang & theme toggles for small screens */}
          <div className="flex items-center gap-3 mt-3 pt-3 border-t border-glass-border sm:hidden">
            <button onClick={toggleLang} className="flex items-center gap-2 text-sm text-text-muted hover:text-emerald-accent cursor-pointer bg-transparent border-none">
              <Globe className="h-4 w-4" /> {i18n.language === 'fr' ? 'Français' : 'English'}
            </button>
            <button onClick={toggleTheme} className="flex items-center gap-2 text-sm text-text-muted hover:text-emerald-accent cursor-pointer bg-transparent border-none">
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>
      )}

      {/* Global Search command palette (renders only when active) */}
      <GlobalSearch selectedCdm={selectedCdm} />

      {/* Notification Center Drawer */}
      <NotificationCenter open={notifCenterOpen} onClose={() => setNotifCenterOpen(false)} />
    </nav>
  );
}
