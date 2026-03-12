import { type ReactNode } from 'react';

type BadgeStatus = 'success' | 'error' | 'warning' | 'processing' | 'default';

const dotColors: Record<BadgeStatus, string> = {
  success: 'bg-emerald-400',
  error: 'bg-red-400',
  warning: 'bg-yellow-400',
  processing: 'bg-blue-400 animate-pulse',
  default: 'bg-slate-400',
};

interface BadgeProps {
  status?: BadgeStatus;
  text?: ReactNode;
  count?: number;
  children?: ReactNode;
  className?: string;
}

export function Badge({ status = 'default', text, count, children, className = '' }: BadgeProps) {
  if (children) {
    return (
      <span className={`relative inline-flex ${className}`}>
        {children}
        {count !== undefined && count > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-red-500 text-[10px] font-semibold text-white px-1">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className={`h-2 w-2 rounded-full ${dotColors[status]}`} />
      {text && <span className="text-sm text-text-bright">{text}</span>}
    </span>
  );
}
