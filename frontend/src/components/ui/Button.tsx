import { type ButtonHTMLAttributes, type ReactNode, forwardRef } from 'react';

type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger' | 'link' | 'text';
type ButtonSize = 'small' | 'middle' | 'large';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
  block?: boolean;
}

const sizeClasses: Record<ButtonSize, string> = {
  small: 'px-3 py-1 text-xs gap-1.5',
  middle: 'px-4 py-2 text-sm gap-2',
  large: 'px-6 py-3 text-base gap-2',
};

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-gradient-to-br from-emerald-accent to-teal-accent text-deep-base font-semibold shadow-[0_4px_12px_rgba(16,185,129,0.3)] hover:shadow-[0_6px_20px_rgba(16,185,129,0.4)] hover:-translate-y-0.5',
  default: 'bg-surface-light border border-glass-border text-text-muted hover:text-emerald-accent hover:border-border-glow',
  ghost: 'border border-emerald-accent/30 bg-emerald-accent/10 text-emerald-accent hover:bg-emerald-accent/20',
  danger: 'bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 hover:text-red-300',
  link: 'text-emerald-accent hover:text-emerald-light underline-offset-2 hover:underline p-0',
  text: 'text-text-muted hover:text-emerald-accent hover:bg-emerald-accent/8',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({
  variant = 'default',
  size = 'middle',
  icon,
  loading,
  block,
  children,
  className = '',
  disabled,
  ...props
}, ref) => {
  return (
    <button
      ref={ref}
      className={`
        inline-flex items-center justify-center rounded-[10px] font-medium
        transition-all duration-200 cursor-pointer
        disabled:opacity-40 disabled:cursor-not-allowed disabled:transform-none
        ${sizeClasses[size]}
        ${variantClasses[variant]}
        ${block ? 'w-full' : ''}
        ${className}
      `.trim()}
      disabled={disabled || loading}
      aria-disabled={disabled || loading || undefined}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : icon ? <span aria-hidden="true">{icon}</span> : null}
      {children && <span>{children}</span>}
    </button>
  );
});

Button.displayName = 'Button';
