import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Users, GitCompareArrows, BookOpen, FlaskConical,
  Database, Settings, Globe, LogOut, ChevronLeft, ChevronRight,
  Shield, ClipboardList,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi, cdmAccessApi } from '../../api/client';
import type { CdmConfig } from '../../types';
import { useAuth } from '../../auth/KeycloakContext';
import { Select } from '../ui/Select';
import { Tooltip } from '../ui/Tooltip';
import { Tag } from '../ui/Tag';

interface SidebarProps {
  selectedCdm: string | null;
  onCdmChange: (cdm: string) => void;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

const menuConfig = [
  { key: '/quality', icon: LayoutDashboard, labelKey: 'app.quality' },
  { key: '/cohorts', icon: Users, labelKey: 'app.cohorts' },
  { key: '/mapping', icon: GitCompareArrows, labelKey: 'app.mapping' },
  { key: '/concepts', icon: BookOpen, labelKey: 'app.concepts' },
  { key: '/ohdsi', icon: FlaskConical, labelKey: 'app.ohdsi', labelDefault: 'OHDSI Tools' },
  { key: '/cdm', icon: Database, labelKey: 'cdm.title' },
  { key: '/settings', icon: Settings, labelKey: 'app.settings' },
  { key: '/audit', icon: ClipboardList, labelKey: 'app.audit' },
  { key: '/users', icon: Shield, labelKey: 'app.users' },
];

const roleColors: Record<string, 'red' | 'purple' | 'blue' | 'green' | 'default'> = {
  admin: 'red',
  'data-manager': 'purple',
  chercheur: 'blue',
  medecin: 'green',
};

export default function Sidebar({ selectedCdm, onCdmChange, collapsed, onCollapse }: SidebarProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const { username, roles, logout, hasPageAccess, authenticated, token } = useAuth();

  useEffect(() => {
    if (authenticated && token) {
      cdmAccessApi.getAccessibleCdms()
        .then((res) => setCdms(res.data.cdms.map((name: string) => ({ name } as CdmConfig))))
        .catch(() => cdmApi.list().then((r) => setCdms(r.data.cdms)).catch(() => {}));
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
    <aside
      className={`
        flex flex-col h-screen shrink-0 overflow-hidden
        bg-gradient-to-b from-deep-base to-[#0e1324]
        border-r border-glass-border
        shadow-[2px_0_12px_rgba(0,0,0,0.3)]
        transition-all duration-300
        ${collapsed ? 'w-16' : 'w-60'}
      `}
    >
      {/* Logo */}
      <div className={`relative ${collapsed ? 'px-2 py-4' : 'px-4 py-5'}`}>
        <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-2.5 px-1'}`}>
          <div className="relative w-9 h-9 flex items-center justify-center shrink-0">
            <div className="w-7 h-7 rounded-full border-2 border-emerald-accent flex items-center justify-center">
              <div className="w-2 h-2 rounded-full bg-emerald-accent shadow-[0_0_12px_rgba(16,185,129,0.4)]" />
            </div>
          </div>
          {!collapsed && (
            <span className="text-xl font-bold text-text-bright tracking-tight">OPAL</span>
          )}
        </div>
        {/* Glow separator */}
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[60%] h-px bg-gradient-to-r from-transparent via-emerald-accent/30 to-transparent" />
      </div>

      {/* User info */}
      <div className={`border-b border-glass-border ${collapsed ? 'py-2 px-1' : 'px-4 py-2'}`}>
        {!collapsed && username ? (
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-accent to-teal-accent flex items-center justify-center shrink-0 text-xs font-semibold text-deep-base">
                  {username.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm font-medium text-text-bright truncate">{username}</span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={logout} className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none p-1">
                  <LogOut className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => onCollapse(true)} className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none p-1">
                  <ChevronLeft className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {roles.map((r) => (
                <Tag key={r} color={roleColors[r] || 'default'} style={{ fontSize: 10 }}>{r}</Tag>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1.5">
            {username && (
              <Tooltip title={`${username} (${roles.join(', ')})`} placement="right">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-accent to-teal-accent flex items-center justify-center text-xs font-semibold text-deep-base cursor-pointer">
                  {username.charAt(0).toUpperCase()}
                </div>
              </Tooltip>
            )}
            {username && (
              <Tooltip title="Logout" placement="right">
                <button onClick={logout} className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none p-1">
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </Tooltip>
            )}
            <button onClick={() => onCollapse(!collapsed)} className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none p-1">
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </button>
          </div>
        )}
      </div>

      {/* CDM selector */}
      {!collapsed && (
        <div className="px-4 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-text-dim mb-1">Database</div>
          <Select
            placeholder={t('cdm.select_cdm')}
            value={selectedCdm}
            onChange={onCdmChange}
            options={cdms.map((c) => ({ value: c.name, label: c.name }))}
            allowClear
            size="small"
          />
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const active = location.pathname === item.key;
          const label = t(item.labelKey, item.labelDefault ?? '');

          const btn = (
            <button
              key={item.key}
              onClick={() => navigate(item.key)}
              className={`
                relative w-full flex items-center gap-3 rounded-[10px] transition-all duration-200
                cursor-pointer bg-transparent border-none text-left
                ${collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'}
                ${active
                  ? 'bg-emerald-accent/12 text-emerald-accent'
                  : 'text-text-dim hover:bg-emerald-accent/6 hover:text-emerald-accent'
                }
              `}
            >
              {active && (
                <span className="absolute left-0 top-[20%] h-[60%] w-[3px] rounded-r bg-emerald-accent shadow-[0_0_8px_rgba(16,185,129,0.4)]" />
              )}
              <Icon className={`h-[18px] w-[18px] shrink-0 ${active ? 'drop-shadow-[0_0_8px_rgba(16,185,129,0.6)]' : ''}`} />
              {!collapsed && <span className="text-sm font-medium truncate">{label}</span>}
            </button>
          );

          return collapsed ? (
            <Tooltip key={item.key} title={label} placement="right">
              {btn}
            </Tooltip>
          ) : btn;
        })}
      </nav>

      {/* Footer */}
      <div className={`border-t border-glass-border ${collapsed ? 'py-2 px-1' : 'px-4 py-2'}`}>
        {collapsed ? (
          <Tooltip title={i18n.language === 'fr' ? 'Français' : 'English'} placement="right">
            <button onClick={toggleLang} className="w-full flex justify-center text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none py-1">
              <Globe className="h-4 w-4" />
            </button>
          </Tooltip>
        ) : (
          <button onClick={toggleLang} className="flex items-center gap-2 text-text-dim hover:text-emerald-accent transition-colors cursor-pointer bg-transparent border-none text-sm py-1">
            <Globe className="h-4 w-4" />
            <span>{i18n.language === 'fr' ? 'Français' : 'English'}</span>
          </button>
        )}
      </div>
    </aside>
  );
}
