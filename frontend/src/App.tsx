import { useState, lazy, Suspense, Component, type ReactNode, type ErrorInfo } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout, ConfigProvider, theme as antTheme, Result, Spin, Button } from 'antd';
import Sidebar from './components/layout/Sidebar';
import { useAuth } from './auth/KeycloakContext';

// Lazy-loaded pages for code splitting
const QualityPage = lazy(() => import('./pages/QualityPage'));
const CohortPage = lazy(() => import('./pages/CohortPage'));
const MappingPage = lazy(() => import('./pages/MappingPage'));
const CdmManagementPage = lazy(() => import('./pages/CdmManagementPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ConceptExplorerPage = lazy(() => import('./pages/ConceptExplorerPage'));
const OhdsiPage = lazy(() => import('./pages/OhdsiPage'));
const AuditPage = lazy(() => import('./pages/AuditPage'));
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'));

const { Content } = Layout;

// Error Boundary for catching render errors
interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="Something went wrong"
          subTitle={this.state.error?.message || 'An unexpected error occurred.'}
          extra={
            <Button type="primary" onClick={() => this.setState({ hasError: false })}>
              Try Again
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}

function PageSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spin size="large" /></div>}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </Suspense>
  );
}

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

const ALL_PAGES = ['/quality', '/cohorts', '/mapping', '/concepts', '/ohdsi', '/cdm', '/settings', '/audit', '/users'];

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
                element={<ProtectedRoute path="/quality"><PageSuspense><QualityPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route path="/cdm" element={<ProtectedRoute path="/cdm"><PageSuspense><CdmManagementPage /></PageSuspense></ProtectedRoute>} />
              <Route
                path="/settings"
                element={<ProtectedRoute path="/settings"><PageSuspense><SettingsPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/cohorts"
                element={<ProtectedRoute path="/cohorts"><PageSuspense><CohortPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/mapping"
                element={<ProtectedRoute path="/mapping"><PageSuspense><MappingPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/concepts"
                element={<ProtectedRoute path="/concepts"><PageSuspense><ConceptExplorerPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/ohdsi"
                element={<ProtectedRoute path="/ohdsi"><PageSuspense><OhdsiPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/audit"
                element={<ProtectedRoute path="/audit"><PageSuspense><AuditPage /></PageSuspense></ProtectedRoute>}
              />
              <Route
                path="/users"
                element={<ProtectedRoute path="/users"><PageSuspense><UserManagementPage /></PageSuspense></ProtectedRoute>}
              />
              <Route path="*" element={<ForbiddenPage />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
