import { Fragment, type ReactNode } from 'react';
import { Listbox, ListboxButton, ListboxOption, ListboxOptions, Transition } from '@headlessui/react';
import { ChevronDown, Check, X } from 'lucide-react';

function labelToString(label: ReactNode): string {
  if (typeof label === 'string') return label;
  if (typeof label === 'number') return String(label);
  return '';
}

export interface SelectOption {
  value: string;
  label: ReactNode;
  description?: string;
  disabled?: boolean;
}

interface SelectProps {
  options: SelectOption[];
  value?: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  allowClear?: boolean;
  size?: 'small' | 'middle';
  className?: string;
  disabled?: boolean;
  label?: string;
}

export function Select({
  options,
  value,
  onChange,
  placeholder = 'Select...',
  allowClear = false,
  size = 'middle',
  className = '',
  disabled = false,
  label,
}: SelectProps) {
  const selected = options.find((o) => o.value === value);
  const py = size === 'small' ? 'py-1.5' : 'py-2';

  return (
    <div className={`relative ${className}`}>
      {label && <label className="block text-xs font-medium text-text-muted mb-1.5">{label}</label>}
      <Listbox value={value ?? ''} onChange={onChange} disabled={disabled}>
        <div className="relative">
          <ListboxButton
            className={`
              relative w-full bg-deep-base border border-glass-border rounded-[10px] pl-3 pr-8 ${py} text-left
              text-sm transition-all duration-200 cursor-pointer
              focus:outline-none focus:border-emerald-accent/40 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.1)]
              disabled:opacity-40 disabled:cursor-not-allowed
            `}
          >
            <span className={`block truncate ${selected ? 'text-text-bright' : 'text-text-dim'}`} title={selected ? labelToString(selected.label) : undefined}>
              {selected ? selected.label : placeholder}
            </span>
            <span className="absolute inset-y-0 right-0 flex items-center pr-2 gap-1">
              {allowClear && value && (
                <span
                  className="text-text-dim hover:text-text-muted cursor-pointer"
                  onClick={(e) => { e.stopPropagation(); onChange('' as any); }}
                >
                  <X className="h-3.5 w-3.5" />
                </span>
              )}
              <ChevronDown className="h-4 w-4 text-text-dim" />
            </span>
          </ListboxButton>

          <Transition
            as={Fragment}
            leave="transition ease-in duration-100"
            leaveFrom="opacity-100"
            leaveTo="opacity-0"
          >
            <ListboxOptions
              anchor="bottom start"
              className="z-[9999] mt-1 max-h-60 min-w-[var(--button-width)] w-max max-w-[320px] overflow-auto rounded-xl bg-surface border border-glass-border shadow-[0_8px_32px_rgba(0,0,0,0.4)] py-1 text-sm focus:outline-none"
            >
              {options.map((option) => (
                <ListboxOption
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className={({ focus, selected }) => `
                    relative cursor-pointer select-none py-2 pl-3 pr-9 mx-1 rounded-lg
                    transition-colors duration-100
                    ${focus ? 'bg-emerald-accent/8 text-text-bright' : 'text-text-muted'}
                    ${selected ? 'bg-emerald-accent/15 text-emerald-accent font-medium' : ''}
                    ${option.disabled ? 'opacity-40 cursor-not-allowed' : ''}
                  `}
                >
                  {({ selected }) => (
                    <>
                      <span className="block truncate" title={labelToString(option.label)}>{option.label}</span>
                      {option.description && (
                        <span className="block text-xs text-text-dim mt-0.5">{option.description}</span>
                      )}
                      {selected && (
                        <span className="absolute inset-y-0 right-0 flex items-center pr-3 text-emerald-accent">
                          <Check className="h-4 w-4" />
                        </span>
                      )}
                    </>
                  )}
                </ListboxOption>
              ))}
            </ListboxOptions>
          </Transition>
        </div>
      </Listbox>
    </div>
  );
}

// Multi-select variant
interface MultiSelectProps {
  options: SelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  className?: string;
  label?: string;
}

export function MultiSelect({ options, value, onChange, placeholder = 'Select...', className = '', label }: MultiSelectProps) {
  const toggle = (v: string) => {
    if (value.includes(v)) {
      onChange(value.filter((x) => x !== v));
    } else {
      onChange([...value, v]);
    }
  };

  return (
    <div className={className}>
      {label && <label className="block text-xs font-medium text-text-muted mb-1.5">{label}</label>}
      <div className="flex flex-wrap gap-1.5">
        {value.length === 0 && <span className="text-xs text-text-dim">{placeholder}</span>}
        {options
          .filter((o) => value.includes(o.value))
          .map((o) => (
            <span
              key={o.value}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-accent/15 text-emerald-accent text-xs font-medium cursor-pointer hover:bg-emerald-accent/25"
              onClick={() => toggle(o.value)}
            >
              {o.label}
              <X className="h-3 w-3" />
            </span>
          ))}
      </div>
    </div>
  );
}
