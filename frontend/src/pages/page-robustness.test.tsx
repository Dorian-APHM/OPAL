import { describe, it, expect, vi, beforeAll } from 'vitest';
import { Component, type ReactNode } from 'react';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../components/ui/Toast';
import '../i18n';

/**
 * Regression test for the "white-screen on unexpected/partial API response" bug.
 *
 * Several pages read `res.data.<field>` and immediately called `.length` / `.map` /
 * `Object.values()` on it. When the backend returned a partial body (field missing),
 * those calls threw and the whole page fell through to the ErrorBoundary (blank screen).
 *
 * Here every API call resolves to `{ data: {} }` (the worst-case empty body) and we
 * assert the pages still render without throwing.
 */

// Any api method returns an empty body — the exact shape that used to crash these pages.
const emptyResponse = () => Promise.resolve({ data: {} });
const apiProxy = new Proxy(
  {},
  { get: () => (..._args: unknown[]) => emptyResponse() },
);

vi.mock('../api/client', () => ({
  __esModule: true,
  auditApi: apiProxy,
  adminApi: apiProxy,
  groupApi: apiProxy,
  usersApi: apiProxy,
  mappingApi: apiProxy,
  conceptApi: apiProxy,
  notificationsApi: apiProxy,
  cdmApi: apiProxy,
  cohortApi: apiProxy,
  qualityApi: apiProxy,
  authDownload: () => Promise.resolve(),
  setTokenGetter: () => {},
  default: apiProxy,
}));

beforeAll(() => {
  // jsdom lacks these — provide minimal stubs so hooks/charts can mount.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
  if (!(globalThis as any).ResizeObserver) {
    (globalThis as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

// Captures any render error a page throws, so a "white-screen" turns into a failed assertion.
class Catcher extends Component<{ onError: (e: Error) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { this.props.onError(error); }
  render() { return this.state.failed ? null : this.props.children; }
}

function renderPage(node: React.ReactElement) {
  const errors: Error[] = [];
  render(
    <MemoryRouter>
      <ToastProvider>
        <Catcher onError={(e) => errors.push(e)}>{node}</Catcher>
      </ToastProvider>
    </MemoryRouter>,
  );
  return errors;
}

describe('page robustness against empty/partial API responses', () => {
  it('AuditPage renders without crashing (guards stats.by_user/by_action.length)', async () => {
    const { default: AuditPage } = await import('./AuditPage');
    const errors = renderPage(<AuditPage />);
    await waitFor(() => {});
    expect(errors).toEqual([]);
  });

  it('UserManagementPage renders without crashing (guards users/requests/groups/opalUsers)', async () => {
    const { default: UserManagementPage } = await import('./UserManagementPage');
    const errors = renderPage(<UserManagementPage />);
    await waitFor(() => {});
    expect(errors).toEqual([]);
  });

  it('MappingPage renders without crashing (guards Object.values(decisions))', async () => {
    const { default: MappingPage } = await import('./MappingPage');
    const errors = renderPage(<MappingPage selectedCdm="AuditCDM" />);
    await waitFor(() => {});
    expect(errors).toEqual([]);
  });

  it('ConceptExplorerPage renders without crashing (guards concepts.map)', async () => {
    const { default: ConceptExplorerPage } = await import('./ConceptExplorerPage');
    const errors = renderPage(<ConceptExplorerPage selectedCdm="AuditCDM" />);
    await waitFor(() => {});
    expect(errors).toEqual([]);
  });
});
