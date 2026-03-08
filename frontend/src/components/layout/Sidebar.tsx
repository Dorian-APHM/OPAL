import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Select, Switch, Tooltip, Tag } from 'antd';
import {
  DashboardOutlined,
  TeamOutlined,
  NodeIndexOutlined,
  DatabaseOutlined,
  SettingOutlined,
  GlobalOutlined,
  BulbOutlined,
  BookOutlined,
  ExperimentOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  LogoutOutlined,
  AuditOutlined,
  TeamOutlined as UsersOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../../api/client';
import type { CdmConfig } from '../../types';
import { useAuth } from '../../auth/KeycloakContext';
import opalLogo from '../../assets/opal-logo.svg';
import { colors, spacing, transitions } from '../../theme/tokens';

const { Sider } = Layout;


interface SidebarProps {
  selectedCdm: string | null;
  onCdmChange: (cdm: string) => void;
  darkMode: boolean;
  onDarkModeToggle: () => void;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

export default function Sidebar({
  selectedCdm,
  onCdmChange,
  darkMode,
  onDarkModeToggle,
  collapsed,
  onCollapse,
}: SidebarProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [cdms, setCdms] = useState<CdmConfig[]>([]);
  const { username, roles, logout, hasPageAccess, authenticated, token } = useAuth();

  useEffect(() => {
    if (authenticated && token) {
      cdmApi.list().then((res) => setCdms(res.data.cdms)).catch(() => {});
    }
  }, [authenticated, token]);

  const allMenuItems = [
    { key: '/quality', icon: <DashboardOutlined />, label: t('app.quality') },
    { key: '/cohorts', icon: <TeamOutlined />, label: t('app.cohorts') },
    { key: '/mapping', icon: <NodeIndexOutlined />, label: t('app.mapping') },
    { key: '/concepts', icon: <BookOutlined />, label: t('app.concepts') },
    { key: '/ohdsi', icon: <ExperimentOutlined />, label: t('app.ohdsi') },
    { key: '/cdm', icon: <DatabaseOutlined />, label: t('cdm.title') },
    { key: '/settings', icon: <SettingOutlined />, label: t('app.settings') },
    { key: '/audit', icon: <AuditOutlined />, label: t('app.audit') },
    { key: '/users', icon: <UsersOutlined />, label: t('app.users') },
  ];

  // Filter menu items based on user's role access
  const menuItems = useMemo(
    () => allMenuItems.filter((item) => hasPageAccess(item.key)),
    [roles, hasPageAccess, i18n.language]
  );

  const toggleLang = () => {
    const newLang = i18n.language === 'fr' ? 'en' : 'fr';
    i18n.changeLanguage(newLang);
    localStorage.setItem('opal-lang', newLang);
  };

  const roleColor = (role: string) => {
    switch (role) {
      case 'admin': return 'red';
      case 'omop-dim': return 'purple';
      case 'chercheur': return 'blue';
      case 'medecin': return 'green';
      default: return 'default';
    }
  };

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      trigger={null}
      width={240}
      collapsedWidth={64}
      className="opal-sidebar"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Logo with glow effect */}
      <div
        className="opal-sidebar-logo"
        style={{
          padding: collapsed ? `${spacing.lg}px ${spacing.sm}px ${spacing.md}px` : `${spacing.xl}px ${spacing.lg}px ${spacing.lg}px`,
          textAlign: 'center',
        }}
      >
        <img
          src={opalLogo}
          alt="OPAL"
          style={{
            width: collapsed ? 48 : 180,
            height: 'auto',
            marginBottom: spacing.sm,
            transition: `width ${transitions.normal}`,
            filter: 'drop-shadow(0 0 12px rgba(43, 196, 89, 0.2))',
          }}
        />
      </div>

      {/* User info + collapse toggle */}
      {!collapsed && username ? (
        <div style={{
          padding: `${spacing.xs}px ${spacing.lg}px ${spacing.sm}px`,
          borderBottom: `1px solid ${colors.sidebarBorder}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: colors.sidebarTextBright, minWidth: 0, flex: 1 }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                background: `linear-gradient(135deg, ${colors.primary}, ${colors.accent})`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                fontSize: 12,
                fontWeight: 600,
                color: '#fff',
              }}>
                {username.charAt(0).toUpperCase()}
              </div>
              <span style={{
                fontSize: 13,
                fontWeight: 500,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                letterSpacing: '0.01em',
              }}>
                {username}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
              <Tooltip title={t('auth.logout', 'Logout')}>
                <LogoutOutlined
                  style={{
                    color: colors.sidebarText,
                    fontSize: 14,
                    cursor: 'pointer',
                    transition: `color ${transitions.fast}`,
                  }}
                  onClick={logout}
                />
              </Tooltip>
              <div
                style={{
                  cursor: 'pointer',
                  color: colors.sidebarText,
                  fontSize: 16,
                  marginLeft: 4,
                  transition: `color ${transitions.fast}`,
                }}
                onClick={() => onCollapse(true)}
              >
                <MenuFoldOutlined />
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 6 }}>
            {roles.map((r) => (
              <Tag
                key={r}
                color={roleColor(r)}
                style={{
                  fontSize: 10,
                  margin: 0,
                  lineHeight: '18px',
                  borderRadius: 4,
                  fontWeight: 500,
                }}
              >
                {r}
              </Tag>
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: `${spacing.xs}px 0 ${spacing.sm}px`,
            textAlign: 'center',
            borderBottom: `1px solid ${colors.sidebarBorder}`,
          }}
        >
          {collapsed && username && (
            <Tooltip title={`${username} (${roles.join(', ')})`} placement="right">
              <div style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                background: `linear-gradient(135deg, ${colors.primary}, ${colors.accent})`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 6px',
                fontSize: 12,
                fontWeight: 600,
                color: '#fff',
                cursor: 'pointer',
              }}>
                {username.charAt(0).toUpperCase()}
              </div>
            </Tooltip>
          )}
          {collapsed && username && (
            <Tooltip title={t('auth.logout', 'Logout')} placement="right">
              <LogoutOutlined
                style={{
                  color: colors.sidebarText,
                  fontSize: 14,
                  cursor: 'pointer',
                  display: 'block',
                  marginBottom: 6,
                }}
                onClick={logout}
              />
            </Tooltip>
          )}
          <div
            style={{
              cursor: 'pointer',
              color: colors.sidebarText,
              fontSize: 16,
              transition: `color ${transitions.fast}`,
            }}
            onClick={() => onCollapse(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
        </div>
      )}

      {/* CDM selector */}
      {!collapsed && (
        <div style={{ padding: `${spacing.sm}px ${spacing.lg}px` }}>
          <div style={{
            fontSize: 10,
            fontWeight: 600,
            textTransform: 'uppercase' as const,
            letterSpacing: '0.08em',
            color: colors.sidebarText,
            marginBottom: 4,
          }}>
            Database
          </div>
          <Select
            placeholder={t('cdm.select_cdm')}
            value={selectedCdm || undefined}
            onChange={onCdmChange}
            style={{ width: '100%' }}
            options={cdms.map((c) => ({ value: c.name, label: c.name }))}
            allowClear
            size="small"
          />
        </div>
      )}

      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[location.pathname]}
        onClick={({ key }) => navigate(key)}
        items={menuItems}
        style={{ flex: 1, background: 'transparent', borderRight: 'none' }}
        inlineCollapsed={collapsed}
      />

      {/* Footer controls */}
      <div style={{
        padding: collapsed ? `${spacing.sm}px ${spacing.xs}px` : `${spacing.sm}px ${spacing.lg}px`,
        borderTop: `1px solid ${colors.sidebarBorder}`,
      }}>
        {collapsed ? (
          <>
            <Tooltip title={i18n.language === 'fr' ? 'Français' : 'English'} placement="right">
              <div
                style={{
                  cursor: 'pointer',
                  textAlign: 'center',
                  color: colors.sidebarText,
                  marginBottom: 8,
                  fontSize: 16,
                  transition: `color ${transitions.fast}`,
                }}
                onClick={toggleLang}
              >
                <GlobalOutlined />
              </div>
            </Tooltip>
            <Tooltip title={darkMode ? 'Dark' : 'Light'} placement="right">
              <div
                style={{
                  textAlign: 'center',
                  color: colors.sidebarText,
                  fontSize: 16,
                  cursor: 'pointer',
                  transition: `color ${transitions.fast}`,
                }}
                onClick={onDarkModeToggle}
              >
                <BulbOutlined />
              </div>
            </Tooltip>
          </>
        ) : (
          <>
            <div
              style={{
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                color: colors.sidebarText,
                marginBottom: 8,
                fontSize: 13,
                transition: `color ${transitions.fast}`,
              }}
              onClick={toggleLang}
            >
              <GlobalOutlined />
              <span>{i18n.language === 'fr' ? 'Français' : 'English'}</span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                color: colors.sidebarText,
                fontSize: 13,
              }}
            >
              <BulbOutlined />
              <Switch
                size="small"
                checked={darkMode}
                onChange={onDarkModeToggle}
                checkedChildren="Dark"
                unCheckedChildren="Light"
              />
            </div>
          </>
        )}
      </div>
    </Sider>
  );
}
