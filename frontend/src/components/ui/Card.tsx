import { type ReactNode, type HTMLAttributes } from 'react';

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  children: ReactNode;
  title?: ReactNode;
  extra?: ReactNode;
  size?: 'default' | 'small';
  accent?: 'top' | 'left' | false;
  hoverable?: boolean;
}

export function Card({ children, title, extra, size = 'default', accent = false, hoverable = true, className = '', ...props }: CardProps) {
  const accentClass = accent === 'top' ? 'border-t-2 border-t-emerald-accent' : accent === 'left' ? 'border-l-3 border-l-emerald-accent' : '';

  return (
    <div
      className={`
        bg-surface rounded-2xl border border-border-subtle
        shadow-[10px_10px_20px_#080b13,-5px_-5px_15px_#1c2539]
        ${hoverable ? 'transition-all duration-300 hover:shadow-[12px_12px_24px_#080b13,-6px_-6px_18px_#1c2539,0_0_25px_rgba(16,185,129,0.1)] hover:border-border-glow' : ''}
        ${accentClass} ${className}
      `.trim()}
      {...props}
    >
      {(title || extra) && (
        <div className={`flex items-center justify-between border-b border-glass-border ${size === 'small' ? 'px-4 py-2.5' : 'px-6 py-4'}`}>
          <div className="text-sm font-semibold text-text-bright">{title}</div>
          {extra && <div>{extra}</div>}
        </div>
      )}
      <div className={size === 'small' ? 'p-4' : 'p-6'}>
        {children}
      </div>
    </div>
  );
}
