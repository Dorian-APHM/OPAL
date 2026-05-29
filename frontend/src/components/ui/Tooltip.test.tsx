import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Tooltip } from './Tooltip';

describe('Tooltip accessibility', () => {
  it('shows on keyboard focus and exposes role=tooltip linked via aria-describedby', () => {
    render(
      <Tooltip title="More info">
        <button>Trigger</button>
      </Tooltip>,
    );
    const trigger = screen.getByText('Trigger');
    expect(screen.queryByRole('tooltip')).toBeNull();

    fireEvent.focus(trigger);
    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('More info');
    expect(trigger).toHaveAttribute('aria-describedby', tip.id);

    fireEvent.blur(trigger);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
