interface ProgressProps {
  percent: number;
  size?: 'small' | 'default';
  status?: 'active' | 'success' | 'error';
  showLabel?: boolean;
  className?: string;
  strokeColor?: string;
}

export function Progress({ percent, size = 'default', status = 'active', showLabel = true, className = '', strokeColor }: ProgressProps) {
  const h = size === 'small' ? 'h-1.5' : 'h-2.5';
  const color = strokeColor
    ? ''
    : status === 'error'
    ? 'bg-red-500'
    : status === 'success' || percent >= 100
    ? 'bg-emerald-accent'
    : 'bg-gradient-to-r from-emerald-accent to-teal-accent';

  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <div className={`flex-1 ${h} rounded-full bg-surface-light overflow-hidden`}>
        <div
          className={`${h} rounded-full transition-all duration-500 ease-out ${color} ${status === 'active' && percent < 100 ? 'animate-pulse' : ''}`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%`, background: strokeColor }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-text-muted tabular-nums shrink-0">{Math.round(percent)}%</span>
      )}
    </div>
  );
}

// Circular progress
interface CircularProgressProps {
  percent: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export function CircularProgress({ percent, size = 48, strokeWidth = 3, className = '' }: CircularProgressProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - percent / 100);

  return (
    <div className={`relative inline-flex items-center justify-center ${className}`}>
      <svg className="-rotate-90" width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(16,185,129,0.1)" strokeWidth={strokeWidth} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#10B981"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <span className="absolute text-[10px] font-semibold text-emerald-accent">{Math.round(percent)}%</span>
    </div>
  );
}
