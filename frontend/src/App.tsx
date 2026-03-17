import { useState, lazy, Suspense, Component, useEffect, useRef, type ReactNode, type ErrorInfo } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import TopNav from './components/layout/TopNav';
import { useAuth } from './auth/KeycloakContext';
import { cdmAccessApi } from './api/client';
import { Spinner } from './components/ui/Spinner';
import { ErrorState } from './components/ui/ErrorState';
import { CardSkeleton } from './components/ui/SkeletonPatterns';

// Lazy-loaded pages for code splitting
const HomePage = lazy(() => import('./pages/HomePage'));
const QualityPage = lazy(() => import('./pages/QualityPage'));
const CohortPage = lazy(() => import('./pages/CohortPage'));
const DataManagementPage = lazy(() => import('./pages/DataManagementPage'));
const MappingPage = lazy(() => import('./pages/MappingPage'));
const CdmManagementPage = lazy(() => import('./pages/CdmManagementPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ConceptExplorerPage = lazy(() => import('./pages/ConceptExplorerPage'));
const OhdsiPage = lazy(() => import('./pages/OhdsiPage'));
const AuditPage = lazy(() => import('./pages/AuditPage'));
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));

// Error Boundary with rich error state
interface ErrorBoundaryState { hasError: boolean; error?: Error; }

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
        <ErrorState
          variant="generic"
          error={this.state.error}
          onRetry={() => this.setState({ hasError: false })}
        />
      );
    }
    return this.props.children;
  }
}

function PageSkeleton() {
  return (
    <div className="p-6 space-y-4">
      {/* Header skeleton */}
      <div className="flex items-center gap-3">
        <div className="h-6 w-6 rounded bg-surface-light animate-pulse" />
        <div className="h-6 w-40 rounded bg-surface-light animate-pulse" />
      </div>
      {/* Content skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CardSkeleton lines={4} />
        <CardSkeleton lines={5} />
      </div>
    </div>
  );
}

function PageTransition({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.className = 'opal-page-enter';
    requestAnimationFrame(() => {
      el.className = 'opal-page-active';
    });
  }, [location.pathname]);

  return <div ref={ref} className="opal-page-active">{children}</div>;
}

function PageSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ErrorBoundary>
        <PageTransition>{children}</PageTransition>
      </ErrorBoundary>
    </Suspense>
  );
}

function ForbiddenPage() {
  return (
    <ErrorState variant="forbidden" />
  );
}

function ProtectedRoute({ path, children }: { path: string; children: React.ReactNode }) {
  const { hasPageAccess } = useAuth();
  return hasPageAccess(path) ? <>{children}</> : <ForbiddenPage />;
}

const ALL_PAGES = ['/', '/quality', '/cohorts', '/data-management', '/mapping', '/concepts', '/ohdsi', '/cdm', '/settings', '/audit', '/users'];

function DefaultRedirect() {
  const { hasPageAccess } = useAuth();
  const firstAllowed = ALL_PAGES.find((p) => hasPageAccess(p)) || '/quality';
  return <Navigate to={firstAllowed} replace />;
}

export default function App() {
  const { initialized, authenticated, login, token } = useAuth();
  const [selectedCdm, setSelectedCdm] = useState<string | null>(
    localStorage.getItem('opal-selected-cdm')
  );

  // Validate that the stored CDM is accessible to the current user
  useEffect(() => {
    if (authenticated && token && selectedCdm) {
      cdmAccessApi.getAccessibleCdms()
        .then((res) => {
          if (!res.data.cdms.includes(selectedCdm)) {
            // User doesn't have access to the stored CDM — clear it
            setSelectedCdm(null);
            localStorage.removeItem('opal-selected-cdm');
          }
        })
        .catch(() => {});
    }
  }, [authenticated, token]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCdmChange = (cdm: string) => {
    setSelectedCdm(cdm);
    localStorage.setItem('opal-selected-cdm', cdm);
  };

  if (!initialized) {
    return (
      <div className="flex items-center justify-center h-screen bg-deep-base">
        <Spinner size="large" tip="Connecting to authentication server..." />
      </div>
    );
  }

  if (!authenticated) {
    return (
      <Suspense fallback={<div className="flex items-center justify-center h-screen bg-deep-base"><Spinner size="large" /></div>}>
        <Routes>
          <Route path="*" element={<LoginPage onSignIn={login} />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <div className="h-screen overflow-hidden bg-deep-base">
      <TopNav selectedCdm={selectedCdm} onCdmChange={handleCdmChange} />
      <main className="pt-[56px] h-full overflow-y-auto px-3 lg:px-4 pb-4 max-w-[1920px] mx-auto">
        <Routes>
          <Route path="/" element={<ProtectedRoute path="/"><PageSuspense><HomePage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/quality" element={<ProtectedRoute path="/quality"><PageSuspense><QualityPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/cdm" element={<ProtectedRoute path="/cdm"><PageSuspense><CdmManagementPage /></PageSuspense></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute path="/settings"><PageSuspense><SettingsPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/cohorts" element={<ProtectedRoute path="/cohorts"><PageSuspense><CohortPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/data-management" element={<ProtectedRoute path="/data-management"><PageSuspense><DataManagementPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/mapping" element={<ProtectedRoute path="/mapping"><PageSuspense><MappingPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/concepts" element={<ProtectedRoute path="/concepts"><PageSuspense><ConceptExplorerPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/ohdsi" element={<ProtectedRoute path="/ohdsi"><PageSuspense><OhdsiPage selectedCdm={selectedCdm} /></PageSuspense></ProtectedRoute>} />
          <Route path="/audit" element={<ProtectedRoute path="/audit"><PageSuspense><AuditPage /></PageSuspense></ProtectedRoute>} />
          <Route path="/users" element={<ProtectedRoute path="/users"><PageSuspense><UserManagementPage /></PageSuspense></ProtectedRoute>} />
          <Route path="*" element={<ForbiddenPage />} />
        </Routes>
      </main>
    </div>
  );
}
