import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorState, detectErrorVariant } from './ErrorState';

// Mock framer-motion
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, className, ...rest }: any) => (
      <div className={className} data-testid="motion-div">{children}</div>
    ),
  },
}));

describe('ErrorState', () => {
  it('renders generic variant by default', () => {
    render(<ErrorState />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('An unexpected error occurred. Please try again.')).toBeInTheDocument();
  });

  it('renders network variant', () => {
    render(<ErrorState variant="network" />);
    expect(screen.getByText('Connection lost')).toBeInTheDocument();
  });

  it('renders server variant', () => {
    render(<ErrorState variant="server" />);
    expect(screen.getByText('Server error')).toBeInTheDocument();
  });

  it('renders forbidden variant', () => {
    render(<ErrorState variant="forbidden" />);
    expect(screen.getByText('Access denied')).toBeInTheDocument();
  });

  it('renders not-found variant', () => {
    render(<ErrorState variant="not-found" />);
    expect(screen.getByText('Not found')).toBeInTheDocument();
  });

  it('overrides title and message', () => {
    render(<ErrorState title="Custom Error" message="Custom message" />);
    expect(screen.getByText('Custom Error')).toBeInTheDocument();
    expect(screen.getByText('Custom message')).toBeInTheDocument();
  });

  it('shows error detail from Error object', () => {
    render(<ErrorState error={new Error('DB connection failed')} />);
    expect(screen.getByText('DB connection failed')).toBeInTheDocument();
  });

  it('shows error detail from string', () => {
    render(<ErrorState error="timeout exceeded" />);
    expect(screen.getByText('timeout exceeded')).toBeInTheDocument();
  });

  it('calls onRetry when retry button is clicked', () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    fireEvent.click(screen.getByText('Try again'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('calls onGoHome when go home button is clicked', () => {
    const onGoHome = vi.fn();
    render(<ErrorState onGoHome={onGoHome} />);
    fireEvent.click(screen.getByText('Go home'));
    expect(onGoHome).toHaveBeenCalledTimes(1);
  });

  it('uses custom retry label', () => {
    render(<ErrorState onRetry={() => {}} retryLabel="Réessayer" />);
    expect(screen.getByText('Réessayer')).toBeInTheDocument();
  });

  it('does not show retry button when onRetry is not provided', () => {
    render(<ErrorState />);
    expect(screen.queryByText('Try again')).not.toBeInTheDocument();
  });

  it('renders compact mode', () => {
    render(<ErrorState compact onRetry={() => {}} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Try again')).toBeInTheDocument();
  });

  it('renders children in full mode', () => {
    render(
      <ErrorState>
        <p>Extra help text</p>
      </ErrorState>
    );
    expect(screen.getByText('Extra help text')).toBeInTheDocument();
  });
});

describe('detectErrorVariant', () => {
  it('returns generic for null/undefined', () => {
    expect(detectErrorVariant(null)).toBe('generic');
    expect(detectErrorVariant(undefined)).toBe('generic');
  });

  it('detects forbidden from response status 403', () => {
    const error = { response: { status: 403 }, message: 'Forbidden' };
    expect(detectErrorVariant(error)).toBe('forbidden');
  });

  it('detects not-found from response status 404', () => {
    const error = { response: { status: 404 }, message: 'Not Found' };
    expect(detectErrorVariant(error)).toBe('not-found');
  });

  it('detects server error from status >= 500', () => {
    expect(detectErrorVariant({ response: { status: 500 }, message: '' })).toBe('server');
    expect(detectErrorVariant({ response: { status: 503 }, message: '' })).toBe('server');
  });

  it('detects network error from message', () => {
    expect(detectErrorVariant(new Error('Network Error'))).toBe('network');
    expect(detectErrorVariant(new Error('ECONNREFUSED'))).toBe('network');
  });

  it('returns generic for unknown errors', () => {
    expect(detectErrorVariant(new Error('something else'))).toBe('generic');
    expect(detectErrorVariant('random string')).toBe('generic');
  });
});
