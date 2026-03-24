import { type ReactNode, type HTMLAttributes } from 'react';

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  children: ReactNode;
  title?: ReactNode;
  extra?: ReactNode;
  size?: 'default' | 'small';
  accent?: 'top' | 'left' | false;
  hoverable?: boolean;
  bodyClassName?: string;
}

export function Card({ children, title, extra, size = 'default', accent = false, hoverable = true, bodyClassName, className = '', ...props }: CardProps) {
  const accentClass = accent === 'top' ? 'border-t-2 border-t-emerald-accent' : accent === 'left' ? 'border-l-3 border-l-emerald-accent' : '';
  const isFlex = className.includes('flex-col');

  return (
    <div
      className={`
        bg-surface rounded-2xl border border-border-subtle
        opal-card-shadow
        ${hoverable ? 'transition-all duration-300 opal-card-hoverable hover:border-border-glow' : ''}
        ${accentClass} ${className}
      `.trim()}
      {...props}
    >
      {(title || extra) && (
        <div className={`flex items-center justify-between border-b border-glass-border flex-shrink-0 ${size === 'small' ? 'px-4 py-2.5' : 'px-6 py-4'}`}>
          <div className="text-sm font-semibold text-text-bright">{title}</div>
          {extra && <div>{extra}</div>}
        </div>
      )}
      <div className={`${size === 'small' ? 'p-4' : 'p-6'} ${isFlex ? 'flex-1 min-h-0 flex flex-col' : ''} ${bodyClassName || ''}`}>
        {children}
      </div>
    </div>
  );
}
