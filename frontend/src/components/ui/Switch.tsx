import { Switch as HeadlessSwitch } from '@headlessui/react';

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  size?: 'small' | 'default';
  disabled?: boolean;
  className?: string;
}

export function Switch({ checked, onChange, label, size = 'default', disabled = false, className = '' }: SwitchProps) {
  const w = size === 'small' ? 'w-8' : 'w-11';
  const h = size === 'small' ? 'h-4' : 'h-6';
  const dot = size === 'small' ? 'h-3 w-3' : 'h-5 w-5';
  const translate = size === 'small' ? 'translate-x-4' : 'translate-x-5';

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <HeadlessSwitch
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className={`
          ${w} ${h} relative inline-flex shrink-0 cursor-pointer rounded-full
          border-2 border-transparent transition-colors duration-200 ease-in-out
          focus:outline-none focus:ring-2 focus:ring-emerald-accent/30 focus:ring-offset-2 focus:ring-offset-deep-base
          ${checked ? 'bg-emerald-accent' : 'bg-surface-light'}
          ${disabled ? 'opacity-40 cursor-not-allowed' : ''}
        `}
      >
        <span
          className={`
            ${dot} pointer-events-none inline-block transform rounded-full bg-white shadow-lg
            ring-0 transition duration-200 ease-in-out
            ${checked ? translate : 'translate-x-0'}
          `}
        />
      </HeadlessSwitch>
      {label && <span className="text-sm text-text-muted">{label}</span>}
    </div>
  );
}
