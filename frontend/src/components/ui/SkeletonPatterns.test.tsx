import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  CardSkeleton,
  StatSkeleton,
  TableSkeleton,
  DashboardSkeleton,
  ListSkeleton,
  InlineSkeleton,
} from './SkeletonPatterns';

describe('CardSkeleton', () => {
  it('renders with default lines', () => {
    const { container } = render(<CardSkeleton />);
    // Header bar + 3 body lines
    const pulseElements = container.querySelectorAll('.animate-pulse');
    expect(pulseElements.length).toBeGreaterThanOrEqual(4);
  });

  it('renders with custom line count', () => {
    const { container } = render(<CardSkeleton lines={5} />);
    // 2 header elements + 5 body lines = 7
    const pulseElements = container.querySelectorAll('.animate-pulse');
    expect(pulseElements.length).toBe(7);
  });

  it('applies accent border when accent=true', () => {
    const { container } = render(<CardSkeleton accent />);
    const card = container.firstElementChild;
    expect(card?.className).toContain('border-t-2');
  });
});

describe('StatSkeleton', () => {
  it('renders skeleton elements', () => {
    const { container } = render(<StatSkeleton />);
    const pulseElements = container.querySelectorAll('.animate-pulse');
    expect(pulseElements.length).toBe(3);
  });
});

describe('TableSkeleton', () => {
  it('renders correct number of rows and columns', () => {
    const { container } = render(<TableSkeleton rows={3} cols={2} />);
    // 1 header row with 2 columns
    const headerCols = container.querySelectorAll('.bg-surface-dark .animate-pulse');
    expect(headerCols.length).toBe(2);
    // 3 data rows × 2 cols = at least 6 pulse elements in body
    const bodyCells = container.querySelectorAll('.border-b .animate-pulse');
    expect(bodyCells.length).toBeGreaterThanOrEqual(6);
  });

  it('uses default rows=5 cols=4', () => {
    const { container } = render(<TableSkeleton />);
    const headerCols = container.querySelectorAll('.bg-surface-dark .animate-pulse');
    expect(headerCols.length).toBe(4);
  });
});

describe('DashboardSkeleton', () => {
  it('renders without crashing', () => {
    const { container } = render(<DashboardSkeleton />);
    // Should have domain grid (9 items) + header + card skeletons
    expect(container.firstElementChild).toBeInTheDocument();
  });

  it('contains domain grid skeleton items', () => {
    const { container } = render(<DashboardSkeleton />);
    // 9 domain items in the grid
    const gridItems = container.querySelectorAll('.grid.grid-cols-5 > div');
    expect(gridItems.length).toBe(9);
  });
});

describe('ListSkeleton', () => {
  it('renders correct number of items', () => {
    const { container } = render(<ListSkeleton items={3} />);
    const items = container.querySelectorAll('.rounded-lg');
    expect(items.length).toBe(3);
  });

  it('defaults to 4 items', () => {
    const { container } = render(<ListSkeleton />);
    const items = container.querySelectorAll('.rounded-lg');
    expect(items.length).toBe(4);
  });
});

describe('InlineSkeleton', () => {
  it('renders with default size', () => {
    const { container } = render(<InlineSkeleton />);
    const el = container.querySelector('.animate-pulse');
    expect(el).toBeInTheDocument();
    expect((el as HTMLElement).style.width).toBe('32px');
    expect((el as HTMLElement).style.height).toBe('16px');
  });

  it('renders with custom size', () => {
    const { container } = render(<InlineSkeleton width={64} height={24} />);
    const el = container.querySelector('.animate-pulse');
    expect((el as HTMLElement).style.width).toBe('64px');
    expect((el as HTMLElement).style.height).toBe('24px');
  });
});
