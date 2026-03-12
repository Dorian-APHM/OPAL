import { type ReactNode } from 'react';
import { Inbox } from 'lucide-react';

interface EmptyProps {
  icon?: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function Empty({ icon, description = 'No data', children, className = '' }: EmptyProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 text-center ${className}`}>
      <div className="text-text-dim mb-4">
        {icon || <Inbox className="h-12 w-12 opacity-40" />}
      </div>
      <p className="text-sm text-text-dim mb-4">{description}</p>
      {children}
    </div>
  );
}
