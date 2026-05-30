import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MultiSelect } from './Select';

/**
 * Regression test for keyboard/screen-reader access: the selected-value chips
 * used to be plain <span onClick>, unreachable by keyboard and unlabeled.
 * They are now real <button> elements with an aria-label.
 */
describe('MultiSelect selected chips accessibility', () => {
  const options = [
    { value: 'a', label: 'Alpha' },
    { value: 'b', label: 'Beta' },
  ];

  it('renders removable chips as focusable buttons with an accessible name', () => {
    render(<MultiSelect options={options} value={['a']} onChange={() => {}} />);
    const chip = screen.getByRole('button', { name: 'Remove Alpha' });
    expect(chip).toBeInTheDocument();
    expect(chip.tagName).toBe('BUTTON');
  });

  it('removes the value when the chip is activated', () => {
    const onChange = vi.fn();
    render(<MultiSelect options={options} value={['a', 'b']} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove Alpha' }));
    expect(onChange).toHaveBeenCalledWith(['b']);
  });
});
