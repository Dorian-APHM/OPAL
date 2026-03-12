import { type ReactNode } from 'react';

interface StatisticProps {
  title: ReactNode;
  value: ReactNode;
  prefix?: ReactNode;
  suffix?: ReactNode;
  valueStyle?: React.CSSProperties;
  className?: string;
}

export function Statistic({ title, value, prefix, suffix, valueStyle, className = '' }: StatisticProps) {
  return (
    <div className={className}>
      <div className="text-xs text-text-dim mb-1">{title}</div>
      <div className="flex items-baseline gap-1" style={valueStyle}>
        {prefix && <span className="text-lg">{prefix}</span>}
        <span className="text-2xl font-bold text-text-bright">{value}</span>
        {suffix && <span className="text-sm text-text-muted">{suffix}</span>}
      </div>
    </div>
  );
}
