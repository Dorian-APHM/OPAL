import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Empty } from './Empty';

// Mock framer-motion
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, className, ...rest }: any) => (
      <div className={className} data-testid="motion-div">{children}</div>
    ),
  },
}));

describe('Empty', () => {
  it('renders default variant', () => {
    render(<Empty />);
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
    expect(screen.getByText('No data to display.')).toBeInTheDocument();
  });

  it('renders no-cdm variant', () => {
    render(<Empty variant="no-cdm" />);
    expect(screen.getByText('No database selected')).toBeInTheDocument();
    expect(screen.getByText('Select a CDM database from the navigation bar to get started.')).toBeInTheDocument();
  });

  it('renders no-cohorts variant', () => {
    render(<Empty variant="no-cohorts" />);
    expect(screen.getByText('No cohorts yet')).toBeInTheDocument();
  });

  it('renders no-results variant', () => {
    render(<Empty variant="no-results" />);
    expect(screen.getByText('No results found')).toBeInTheDocument();
  });

  it('renders no-notifications variant', () => {
    render(<Empty variant="no-notifications" />);
    expect(screen.getByText('All caught up')).toBeInTheDocument();
  });

  it('renders no-favorites variant', () => {
    render(<Empty variant="no-favorites" />);
    expect(screen.getByText('No favorites yet')).toBeInTheDocument();
  });

  it('renders no-quality variant', () => {
    render(<Empty variant="no-quality" />);
    expect(screen.getByText('No quality analysis')).toBeInTheDocument();
  });

  it('renders no-mapping variant', () => {
    render(<Empty variant="no-mapping" />);
    expect(screen.getByText('No mappings')).toBeInTheDocument();
  });

  it('renders no-access variant', () => {
    render(<Empty variant="no-access" />);
    expect(screen.getByText('No access')).toBeInTheDocument();
  });

  it('renders no-files variant', () => {
    render(<Empty variant="no-files" />);
    expect(screen.getByText('No files')).toBeInTheDocument();
  });

  it('overrides title when provided', () => {
    render(<Empty variant="no-cdm" title="Custom Title" />);
    expect(screen.getByText('Custom Title')).toBeInTheDocument();
    expect(screen.queryByText('No database selected')).not.toBeInTheDocument();
  });

  it('overrides description when provided', () => {
    render(<Empty variant="no-cdm" description="Custom description" />);
    expect(screen.getByText('Custom description')).toBeInTheDocument();
  });

  it('overrides icon when provided', () => {
    render(<Empty icon={<span data-testid="custom-icon">X</span>} />);
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument();
  });

  it('renders children (action buttons)', () => {
    render(
      <Empty variant="no-cohorts">
        <button>Create Cohort</button>
      </Empty>
    );
    expect(screen.getByText('Create Cohort')).toBeInTheDocument();
  });

  it('applies className', () => {
    render(<Empty className="extra-class" />);
    const wrappers = screen.getAllByTestId('motion-div');
    // The outer motion.div is the first one
    const outerWrapper = wrappers[0];
    expect(outerWrapper.className).toContain('extra-class');
  });
});
