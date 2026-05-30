import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ToastProvider, useToast } from './Toast';

// Mock framer-motion
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, className, role, ...rest }: any) => (
      <div className={className} role={role} data-testid="toast-item">{children}</div>
    ),
    span: ({ children, ...rest }: any) => <span>{children}</span>,
  },
  AnimatePresence: ({ children }: any) => <>{children}</>,
}));

function ToastTrigger() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success('Success!')}>Success</button>
      <button onClick={() => toast.error('Error!')}>Error</button>
      <button onClick={() => toast.info('Info!')}>Info</button>
      <button onClick={() => toast.warning('Warning!')}>Warn</button>
    </div>
  );
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('renders children', () => {
    render(
      <ToastProvider>
        <span>App content</span>
      </ToastProvider>
    );
    expect(screen.getByText('App content')).toBeInTheDocument();
  });

  it('shows success toast', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    expect(screen.getByText('Success!')).toBeInTheDocument();
  });

  it('shows error toast', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Error'));
    expect(screen.getByText('Error!')).toBeInTheDocument();
  });

  it('shows info toast', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Info'));
    expect(screen.getByText('Info!')).toBeInTheDocument();
  });

  it('shows warning toast', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Warn'));
    expect(screen.getByText('Warning!')).toBeInTheDocument();
  });

  it('auto-dismisses toast after 4 seconds', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    expect(screen.getByText('Success!')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4100);
    });

    expect(screen.queryByText('Success!')).not.toBeInTheDocument();
  });

  it('removes toast on close button click', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    expect(screen.getByText('Success!')).toBeInTheDocument();

    const closeBtn = screen.getByLabelText('Close notification');
    fireEvent.click(closeBtn);
    expect(screen.queryByText('Success!')).not.toBeInTheDocument();
  });

  it('can show multiple toasts', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    fireEvent.click(screen.getByText('Error'));
    expect(screen.getByText('Success!')).toBeInTheDocument();
    expect(screen.getByText('Error!')).toBeInTheDocument();
  });

  it('clears the auto-dismiss timer when a toast is closed manually (no leak)', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout');
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    fireEvent.click(screen.getByLabelText('Close notification'));
    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });

  it('clears pending auto-dismiss timers on unmount (no setState-after-unmount leak)', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout');
    const { unmount } = render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    const before = clearSpy.mock.calls.length;
    unmount();
    expect(clearSpy.mock.calls.length).toBeGreaterThan(before);
    clearSpy.mockRestore();
  });

  it('has correct role=alert for accessibility', () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText('Success'));
    const alerts = screen.getAllByRole('alert');
    expect(alerts.length).toBeGreaterThanOrEqual(1);
  });
});

describe('useToast outside provider', () => {
  it('throws when used outside ToastProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => {
      render(<ToastTrigger />);
    }).toThrow('useToast must be used within ToastProvider');
    spy.mockRestore();
  });
});
