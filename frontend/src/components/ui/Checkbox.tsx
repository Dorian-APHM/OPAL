import { type ReactNode } from 'react';
import { Check } from 'lucide-react';

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children?: ReactNode;
  disabled?: boolean;
  className?: string;
  indeterminate?: boolean;
}

export function Checkbox({ checked, onChange, children, disabled = false, className = '', indeterminate = false }: CheckboxProps) {
  return (
    <label className={`inline-flex items-center gap-2 cursor-pointer select-none ${disabled ? 'opacity-40 cursor-not-allowed' : ''} ${className}`}>
      <span
        onClick={(e) => { e.preventDefault(); if (!disabled) onChange(!checked); }}
        className={`
          relative flex items-center justify-center w-4 h-4 rounded border transition-all duration-150 shrink-0
          ${checked || indeterminate
            ? 'bg-emerald-accent border-emerald-accent'
            : 'border-glass-border bg-deep-base hover:border-emerald-accent/40'
          }
        `}
      >
        {checked && <Check className="h-3 w-3 text-deep-base" strokeWidth={3} />}
        {indeterminate && !checked && <span className="block w-2 h-0.5 bg-deep-base rounded-full" />}
      </span>
      {children && <span className="text-sm text-text-muted">{children}</span>}
    </label>
  );
}
