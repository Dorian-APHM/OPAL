import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Tabs } from './Tabs';

const items = [
  { key: 'a', label: 'Alpha', children: <div>Panel A</div> },
  { key: 'b', label: 'Beta', children: <div>Panel B</div> },
];

describe('Tabs accessibility', () => {
  it('exposes the ARIA tablist / tab / tabpanel roles', () => {
    render(<Tabs items={items} />);
    expect(screen.getByRole('tablist')).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'tab-a');
  });

  it('moves between tabs with the arrow keys', () => {
    render(<Tabs items={items} />);
    const [first] = screen.getAllByRole('tab');
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    const tabs = screen.getAllByRole('tab');
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Panel B')).toBeInTheDocument();
  });
});
