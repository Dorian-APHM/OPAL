import { useState, type ReactNode } from 'react';

export interface TabItem {
  key: string;
  label: ReactNode;
  children: ReactNode;
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  activeKey?: string;
  onChange?: (key: string) => void;
  extra?: ReactNode;
  className?: string;
}

export function Tabs({ items, activeKey, onChange, extra, className = '' }: TabsProps) {
  const [internalKey, setInternalKey] = useState(items[0]?.key || '');
  const current = activeKey ?? internalKey;

  const handleChange = (key: string) => {
    if (onChange) onChange(key);
    else setInternalKey(key);
  };

  const activeTab = items.find((t) => t.key === current);

  return (
    <div className={className}>
      <div className="flex items-center justify-between border-b border-glass-border mb-4">
        <div className="flex gap-0 -mb-px">
          {items.map((tab) => (
            <button
              key={tab.key}
              onClick={() => !tab.disabled && handleChange(tab.key)}
              disabled={tab.disabled}
              className={`
                relative px-4 py-2.5 text-sm font-medium transition-colors duration-200 cursor-pointer
                bg-transparent border-none
                ${tab.disabled ? 'opacity-40 cursor-not-allowed' : ''}
                ${current === tab.key
                  ? 'text-emerald-accent'
                  : 'text-text-dim hover:text-emerald-accent'
                }
              `}
            >
              {tab.label}
              {current === tab.key && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-accent shadow-[0_0_8px_rgba(16,185,129,0.4)]" />
              )}
            </button>
          ))}
        </div>
        {extra && <div className="pb-2">{extra}</div>}
      </div>
      <div>{activeTab?.children}</div>
    </div>
  );
}
