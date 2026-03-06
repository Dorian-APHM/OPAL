import { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout, ConfigProvider, theme as antTheme, Result, Spin } from 'antd';
import Sidebar from './components/layout/Sidebar';
import QualityPage from './pages/QualityPage';
import CohortPage from './pages/CohortPage';
import MappingPage from './pages/MappingPage';
import CdmManagementPage from './pages/CdmManagementPage';
import SettingsPage from './pages/SettingsPage';
import ConceptExplorerPage from './pages/ConceptExplorerPage';
import OhdsiPage from './pages/OhdsiPage';
import { useAuth } from './auth/KeycloakContext';

const { Content } = Layout;

function ForbiddenPage() {
  return (
    <Result
      status="403"
      title="403"
      subTitle="You do not have permission to access this page."
    />
  );
}

function ProtectedRoute({ path, children }: { path: string; children: React.ReactNode }) {
  const { hasPageAccess } = useAuth();
  return hasPageAccess(path) ? <>{children}</> : <ForbiddenPage />;
}

const ALL_PAGES = ['/quality', '/cohorts', '/mapping', '/concepts', '/ohdsi', '/cdm', '/settings'];

function DefaultRedirect() {
  const { hasPageAccess } = useAuth();
  const firstAllowed = ALL_PAGES.find((p) => hasPageAccess(p)) || '/quality';
  return <Navigate to={firstAllowed} replace />;
}

export default function App() {
  const { initialized, authenticated } = useAuth();
  const [selectedCdm, setSelectedCdm] = useState<string | null>(
    localStorage.getItem('opal-selected-cdm')
  );
  const [darkMode, setDarkMode] = useState(
    localStorage.getItem('opal-dark-mode') === 'true'
  );
  const [collapsed, setCollapsed] = useState(false);

  const handleCdmChange = (cdm: string) => {
    setSelectedCdm(cdm);
    localStorage.setItem('opal-selected-cdm', cdm);
  };

  const handleDarkModeToggle = () => {
    const next = !darkMode;
    setDarkMode(next);
    localStorage.setItem('opal-dark-mode', String(next));
  };

  if (!initialized) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="Connecting to authentication server..." />
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Result status="error" title="Authentication Failed" subTitle="Unable to authenticate. Please try again." />
      </div>
    );
  }

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#1f77b4',
          colorSuccess: '#2bc459',
          colorLink: '#1f77b4',
          borderRadius: 6,
        },
        components: {
          Switch: {
            colorPrimary: '#2bc459',
            colorPrimaryHover: '#24a34a',
          },
          Tabs: {
            inkBarColor: '#2bc459',
            itemActiveColor: '#2bc459',
            itemHoverColor: '#24a34a',
            itemSelectedColor: '#2bc459',
          },
          Progress: {
            defaultColor: '#2bc459',
          },
          Checkbox: {
            colorPrimary: '#2bc459',
            colorPrimaryHover: '#24a34a',
          },
          Tag: {
            colorSuccess: '#2bc459',
            colorSuccessBg: '#f0faf3',
            colorSuccessBorder: '#b7ebc5',
          },
        },
        algorithm: darkMode ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Sidebar
          selectedCdm={selectedCdm}
          onCdmChange={handleCdmChange}
          darkMode={darkMode}
          onDarkModeToggle={handleDarkModeToggle}
          collapsed={collapsed}
          onCollapse={setCollapsed}
        />
        <Layout>
          <Content
            style={{
              padding: 16,
              margin: 0,
              background: darkMode ? '#141414' : '#f5f5f5',
              overflow: 'auto',
            }}
          >
            <Routes>
              <Route path="/" element={<DefaultRedirect />} />
              <Route
                path="/quality"
                element={<ProtectedRoute path="/quality"><QualityPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route path="/cdm" element={<ProtectedRoute path="/cdm"><CdmManagementPage /></ProtectedRoute>} />
              <Route
                path="/settings"
                element={<ProtectedRoute path="/settings"><SettingsPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route
                path="/cohorts"
                element={<ProtectedRoute path="/cohorts"><CohortPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route
                path="/mapping"
                element={<ProtectedRoute path="/mapping"><MappingPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route
                path="/concepts"
                element={<ProtectedRoute path="/concepts"><ConceptExplorerPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route
                path="/ohdsi"
                element={<ProtectedRoute path="/ohdsi"><OhdsiPage selectedCdm={selectedCdm} /></ProtectedRoute>}
              />
              <Route path="*" element={<ForbiddenPage />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
