import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/react';
import { ChevronRight } from 'lucide-react';
import { type ReactNode } from 'react';

interface CollapseItem {
  key: string;
  label: ReactNode;
  children: ReactNode;
}

interface CollapseProps {
  items: CollapseItem[];
  className?: string;
}

export function Collapse({ items, className = '' }: CollapseProps) {
  return (
    <div className={`rounded-xl border border-glass-border overflow-hidden divide-y divide-glass-border ${className}`}>
      {items.map((item) => (
        <Disclosure key={item.key}>
          {({ open }) => (
            <>
              <DisclosureButton className="flex items-center justify-between w-full px-4 py-3 text-left text-sm font-medium text-text-bright bg-surface hover:text-emerald-accent transition-colors cursor-pointer border-none">
                <span>{item.label}</span>
                <ChevronRight className={`h-4 w-4 text-text-dim transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
              </DisclosureButton>
              <DisclosurePanel className="px-4 py-3 text-sm text-text-muted bg-surface-dark">
                {item.children}
              </DisclosurePanel>
            </>
          )}
        </Disclosure>
      ))}
    </div>
  );
}
