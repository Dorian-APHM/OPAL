import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Input, TextArea, NumberInput } from './Input';

describe('Input', () => {
  it('renders with label', () => {
    render(<Input label="Username" />);
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
  });

  it('shows red asterisk when required with label', () => {
    const { container } = render(<Input label="Name" required />);
    const asterisk = container.querySelector('.text-red-400');
    expect(asterisk).toBeInTheDocument();
    expect(asterisk?.textContent).toBe('*');
  });

  it('does not show asterisk when not required', () => {
    const { container } = render(<Input label="Name" />);
    const asterisk = container.querySelector('.text-red-400');
    expect(asterisk).toBeNull();
  });

  it('shows error message and applies error styling', () => {
    render(<Input label="Email" error="Invalid email" />);
    expect(screen.getByText('Invalid email')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid email');
  });

  it('sets aria-invalid when error is present', () => {
    render(<Input label="Email" error="Required" />);
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not set aria-invalid when no error', () => {
    render(<Input label="Email" />);
    expect(screen.getByLabelText('Email')).not.toHaveAttribute('aria-invalid');
  });

  it('renders prefix and suffix', () => {
    render(<Input prefix={<span data-testid="prefix">@</span>} suffix={<span data-testid="suffix">.com</span>} />);
    expect(screen.getByTestId('prefix')).toBeInTheDocument();
    expect(screen.getByTestId('suffix')).toBeInTheDocument();
  });
});

describe('TextArea', () => {
  it('renders with label', () => {
    render(<TextArea label="Description" />);
    expect(screen.getByLabelText('Description')).toBeInTheDocument();
  });

  it('shows red asterisk when required', () => {
    const { container } = render(<TextArea label="Notes" required />);
    const asterisk = container.querySelector('.text-red-400');
    expect(asterisk).toBeInTheDocument();
  });

  it('shows error message', () => {
    render(<TextArea label="Bio" error="Too short" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Too short');
  });
});

describe('NumberInput', () => {
  it('renders with label', () => {
    render(<NumberInput label="Age" />);
    expect(screen.getByLabelText('Age')).toBeInTheDocument();
  });

  it('shows red asterisk when required', () => {
    const { container } = render(<NumberInput label="Count" required />);
    const asterisk = container.querySelector('.text-red-400');
    expect(asterisk).toBeInTheDocument();
  });

  it('calls onChange with number value', () => {
    let val: number | null = null;
    render(<NumberInput label="Qty" onChange={(v) => { val = v; }} />);
    fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '42' } });
    expect(val).toBe(42);
  });

  it('calls onChange with null for empty input', () => {
    let val: number | null = 99;
    render(<NumberInput label="Qty" value={5} onChange={(v) => { val = v; }} />);
    fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '' } });
    expect(val).toBeNull();
  });
});
