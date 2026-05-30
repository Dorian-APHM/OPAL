import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../components/ui/Toast';
import { clearSessionState } from '../hooks/useSessionState';
import '../i18n';

/**
 * Regression test for the "unguarded numeric value" crashes: pages called
 * `.toFixed()` directly on values that the backend can legitimately return as
 * null (person_years, incidence_rate, ci_lower/ci_upper...). A null then threw
 * `Cannot read properties of null (reading 'toFixed')` and blanked the page.
 */

const compute = vi.fn();

vi.mock('../api/client', () => {
  const ok = (data: unknown) => Promise.resolve({ data });
  return {
    __esModule: true,
    cohortApi: { list: () => ok({ cohorts: [{ id: 1, name: 'Cohorte Alpha', patient_count: 100 }] }) },
    incidenceApi: { compute: (...args: unknown[]) => compute(...args) },
    setTokenGetter: () => {},
  };
});

beforeEach(() => {
  clearSessionState();
  compute.mockReset();
});

describe('IncidencePage numeric guards', () => {
  it('renders a result whose numeric fields are all null without crashing', async () => {
    // Backend returns a "valid" result but with null metrics.
    compute.mockResolvedValue({
      data: {
        target_count: null,
        outcome_count: null,
        person_years: null,
        incidence_rate: null,
        ci_lower: null,
        ci_upper: null,
        strata: [],
      },
    });

    const { default: IncidencePage } = await import('./IncidencePage');
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ToastProvider>
          <IncidencePage selectedCdm="CDM" />
        </ToastProvider>
      </MemoryRouter>,
    );

    // Pick target + outcome cohort (Headless UI Listbox).
    await user.click(await screen.findByText('Select target cohort...'));
    await user.click(await screen.findByRole('option', { name: 'Cohorte Alpha (100)' }));
    await user.click(await screen.findByText('Select outcome cohort...'));
    await user.click(await screen.findByRole('option', { name: 'Cohorte Alpha (100)' }));

    // Compute (FR label, since i18n defaults to 'fr').
    await user.click(screen.getByRole('button', { name: 'Calculer' }));

    // The Person-Years stat must render its guarded value ("0.0") rather than crash.
    await waitFor(() => expect(compute).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('0.0')).toBeInTheDocument();
  });
});
