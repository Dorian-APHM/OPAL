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
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../../api/client';
import type { CdmConfig } from '../../types';
import { useAuth } from '../../auth/KeycloakContext';
import opalLogo from '../../assets/opal-logo.svg';

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
      style={{
        background: '#001529',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Logo */}
      <div style={{ padding: collapsed ? '16px 8px 12px' : '20px 16px 16px', textAlign: 'center' }}>
        <img
          src={opalLogo}
          alt="OPAL"
          style={{ width: collapsed ? 48 : 180, height: 'auto', marginBottom: 8, transition: 'width 0.2s' }}
        />
      </div>

      {/* User info + collapse toggle */}
      {!collapsed && username ? (
        <div style={{ padding: '4px 16px 8px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'rgba(255,255,255,0.85)', minWidth: 0, flex: 1 }}>
              <UserOutlined style={{ flexShrink: 0 }} />
              <span style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{username}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
              <Tooltip title={t('auth.logout', 'Logout')}>
                <LogoutOutlined
                  style={{ color: 'rgba(255,255,255,0.45)', fontSize: 14, cursor: 'pointer' }}
                  onClick={logout}
                />
              </Tooltip>
              <div
                style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.65)', fontSize: 16, marginLeft: 4 }}
                onClick={() => onCollapse(true)}
              >
                <MenuFoldOutlined />
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, marginTop: 4 }}>
            {roles.map((r) => (
              <Tag key={r} color={roleColor(r)} style={{ fontSize: 10, margin: 0, lineHeight: '18px' }}>{r}</Tag>
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: '4px 0 8px',
            textAlign: 'center',
            borderBottom: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          {collapsed && username && (
            <Tooltip title={`${username} (${roles.join(', ')})`} placement="right">
              <UserOutlined style={{ color: 'rgba(255,255,255,0.65)', fontSize: 16, display: 'block', marginBottom: 6 }} />
            </Tooltip>
          )}
          {collapsed && username && (
            <Tooltip title={t('auth.logout', 'Logout')} placement="right">
              <LogoutOutlined
                style={{ color: 'rgba(255,255,255,0.45)', fontSize: 14, cursor: 'pointer', display: 'block', marginBottom: 6 }}
                onClick={logout}
              />
            </Tooltip>
          )}
          <div
            style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.65)', fontSize: 16 }}
            onClick={() => onCollapse(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
        </div>
      )}

      {/* CDM selector (hidden when collapsed) */}
      {!collapsed && (
        <div style={{ padding: '0 16px 8px' }}>
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
        style={{ flex: 1 }}
        inlineCollapsed={collapsed}
      />

      {/* Footer controls */}
      <div style={{ padding: collapsed ? '8px 4px' : '8px 16px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
        {collapsed ? (
          <>
            <Tooltip title={i18n.language === 'fr' ? 'Français' : 'English'} placement="right">
              <div
                style={{ cursor: 'pointer', textAlign: 'center', color: 'rgba(255,255,255,0.65)', marginBottom: 8, fontSize: 16 }}
                onClick={toggleLang}
              >
                <GlobalOutlined />
              </div>
            </Tooltip>
            <Tooltip title={darkMode ? 'Dark' : 'Light'} placement="right">
              <div
                style={{ textAlign: 'center', color: 'rgba(255,255,255,0.65)', fontSize: 16, cursor: 'pointer' }}
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
                color: 'rgba(255,255,255,0.65)',
                marginBottom: 8,
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
                color: 'rgba(255,255,255,0.65)',
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
