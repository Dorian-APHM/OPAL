import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Users, GitCompareArrows, BookOpen, FlaskConical,
  Database, Settings, Globe, LogOut, Shield, ClipboardList,
  Menu, X, ChevronDown,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../../api/client';
import type { CdmConfig } from '../../types';
import { useAuth } from '../../auth/KeycloakContext';
import { Select } from '../ui/Select';
import { Tag } from '../ui/Tag';
import { Tooltip } from '../ui/Tooltip';

interface TopNavProps {
  selectedCdm: string | null;
  onCdmChange: (cdm: string) => void;
}

const menuConfig = [
  { key: '/quality', icon: LayoutDashboard, labelKey: 'app.quality' },
  { key: '/cohorts', icon: Users, labelKey: 'app.cohorts' },
  { key: '/mapping', icon: GitCompareArrows, labelKey: 'app.mapping' },
  { key: '/concepts', icon: BookOpen, labelKey: 'app.concepts' },
  { key: '/ohdsi', icon: FlaskConical, labelKey: 'app.ohdsi', labelDefault: 'OHDSI' },
  { key: '/cdm', icon: Database, labelKey: 'cdm.title' },
  { key: '/settings', icon: Settings, labelKey: 'app.settings' },
  { key: '/audit', icon: ClipboardList, labelKey: 'app.audit' },
  { key: '/users', icon: Shield, labelKey: 'app.users' },
];

const roleColors: Record<string, 'red' | 'purple' | 'blue' | 'green' | 'default'> = {
  admin: 'red',
  'omop-dim': 'purple',
  chercheur: 'blue',
  medecin: 'green',
};

export default function TopNav({ selectedCdm, onCdmChange }: TopNavProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const { username, roles, logout, hasPageAccess, authenticated, token } = useAuth();

  useEffect(() => {
    if (authenticated && token) {
      cdmApi.list().then((res) => setCdms(res.data.cdms)).catch(() => {});
    }
  }, [authenticated, token]);

  const menuItems = useMemo(
    () => menuConfig.filter((item) => hasPageAccess(item.key)),
    [roles, hasPageAccess, i18n.language]
  );

  const toggleLang = () => {
    const newLang = i18n.language === 'fr' ? 'en' : 'fr';
    i18n.changeLanguage(newLang);
    localStorage.setItem('opal-lang', newLang);
  };

  return (
    <nav className="glass-nav fixed top-0 left-0 right-0 z-50 px-4 lg:px-6 py-3">
      <div className="mx-auto flex items-center justify-between max-w-[1600px]">
        {/* Logo */}
        <div className="flex items-center gap-6">
          <a href="/" className="flex items-center gap-2.5 no-underline shrink-0">
            <div className="relative w-8 h-8 flex items-center justify-center">
              <div className="w-6 h-6 rounded-full border-2 border-emerald-accent flex items-center justify-center">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-accent shadow-[0_0_10px_rgba(16,185,129,0.5)]" />
              </div>
            </div>
            <span className="text-lg font-bold text-text-bright tracking-tight">OPAL</span>
          </a>

          {/* CDM Selector */}
          <div className="hidden md:block w-44">
            <Select
              placeholder={t('cdm.select_cdm')}
              value={selectedCdm}
              onChange={onCdmChange}
              options={cdms.map((c) => ({ value: c.name, label: c.name }))}
              allowClear
              size="small"
            />
          </div>
        </div>

        {/* Desktop Navigation */}
        <div className="hidden lg:flex items-center gap-1">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.key;
            const label = t(item.labelKey, item.labelDefault ?? '');

            return (
              <button
                key={item.key}
                onClick={() => navigate(item.key)}
                className={`
                  relative flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium
                  transition-all duration-200 cursor-pointer bg-transparent border-none
                  ${active
                    ? 'text-emerald-accent'
                    : 'text-text-muted hover:text-emerald-accent'
                  }
                `}
              >
                <Icon className={`h-4 w-4 ${active ? 'drop-shadow-[0_0_6px_rgba(16,185,129,0.5)]' : ''}`} />
                <span className="hidden xl:inline">{label}</span>
                {active && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-emerald-accent shadow-[0_0_6px_rgba(16,185,129,0.4)]" />
                )}
              </button>
            );
          })}
        </div>

        {/* Right side: user + lang */}
        <div className="flex items-center gap-3">
          {/* Language toggle */}
          <Tooltip title={i18n.language === 'fr' ? 'Français' : 'English'}>
            <button onClick={toggleLang} className="text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none p-1.5">
              <Globe className="h-4 w-4" />
            </button>
          </Tooltip>

          {/* User menu */}
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="flex items-center gap-2 cursor-pointer bg-transparent border-none text-text-muted hover:text-text-bright transition-colors"
            >
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-accent to-teal-accent flex items-center justify-center text-xs font-semibold text-deep-base">
                {username?.charAt(0).toUpperCase() ?? '?'}
              </div>
              <span className="hidden sm:inline text-sm font-medium">{username}</span>
              <ChevronDown className="h-3.5 w-3.5" />
            </button>

            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div className="absolute right-0 mt-2 w-56 rounded-xl bg-surface border border-glass-border shadow-[0_8px_32px_rgba(0,0,0,0.4)] z-50 py-2">
                  <div className="px-4 py-2 border-b border-glass-border mb-1">
                    <div className="text-sm font-medium text-text-bright">{username}</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {roles.map((r) => (
                        <Tag key={r} color={roleColors[r] || 'default'} style={{ fontSize: 10 }}>{r}</Tag>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={() => { setUserMenuOpen(false); navigate('/settings'); }}
                    className="w-full flex items-center gap-2 px-4 py-2 text-sm text-text-muted hover:bg-emerald-accent/6 hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none text-left"
                  >
                    <Settings className="h-4 w-4" />
                    {t('app.settings')}
                  </button>
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
            className="lg:hidden text-text-muted cursor-pointer bg-transparent border-none p-1"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Navigation Drawer */}
      {mobileOpen && (
        <div className="lg:hidden mt-3 pt-3 border-t border-glass-border">
          {/* Mobile CDM selector */}
          <div className="mb-3 md:hidden">
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
            {menuItems.map((item) => {
              const Icon = item.icon;
              const active = location.pathname === item.key;
              const label = t(item.labelKey, item.labelDefault ?? '');

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
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </nav>
  );
}
