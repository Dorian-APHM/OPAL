interface SpinnerProps {
  size?: 'small' | 'default' | 'large';
  className?: string;
  tip?: string;
}

const sizeMap = { small: 'h-4 w-4', default: 'h-8 w-8', large: 'h-12 w-12' };

export function Spinner({ size = 'default', className = '', tip }: SpinnerProps) {
  return (
    <div className={`flex flex-col items-center gap-3 ${className}`} role="status" aria-live="polite">
      <svg className={`animate-spin ${sizeMap[size]} text-emerald-accent`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      {tip ? <span className="text-sm text-text-muted">{tip}</span> : <span className="sr-only">Loading</span>}
    </div>
  );
}

// Full page loading
export function PageLoader({ tip }: { tip?: string }) {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <Spinner size="large" tip={tip} />
    </div>
  );
}

// Skeleton loader
export function Skeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-3 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-surface-light animate-pulse"
          style={{ width: i === 0 ? '40%' : i === lines - 1 ? '60%' : '100%' }}
        />
      ))}
    </div>
  );
}
