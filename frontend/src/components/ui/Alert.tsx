import { type ReactNode } from 'react';
import { AlertCircle, CheckCircle, Info, AlertTriangle, X } from 'lucide-react';

type AlertType = 'info' | 'success' | 'warning' | 'error';

const styles: Record<AlertType, { bg: string; border: string; icon: ReactNode }> = {
  info: { bg: 'bg-blue-500/8', border: 'border-blue-500/20', icon: <Info className="h-5 w-5 text-blue-400 shrink-0" /> },
  success: { bg: 'bg-emerald-500/8', border: 'border-emerald-500/20', icon: <CheckCircle className="h-5 w-5 text-emerald-400 shrink-0" /> },
  warning: { bg: 'bg-yellow-500/8', border: 'border-yellow-500/20', icon: <AlertTriangle className="h-5 w-5 text-yellow-400 shrink-0" /> },
  error: { bg: 'bg-red-500/8', border: 'border-red-500/20', icon: <AlertCircle className="h-5 w-5 text-red-400 shrink-0" /> },
};

interface AlertProps {
  type?: AlertType;
  message: ReactNode;
  description?: ReactNode;
  showIcon?: boolean;
  closable?: boolean;
  onClose?: () => void;
  className?: string;
}

export function Alert({ type = 'info', message, description, showIcon = true, closable, onClose, className = '' }: AlertProps) {
  const s = styles[type];
  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl border ${s.bg} ${s.border} ${className}`}>
      {showIcon && s.icon}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-text-bright">{message}</div>
        {description && <div className="text-xs text-text-muted mt-1">{description}</div>}
      </div>
      {closable && (
        <button onClick={onClose} className="text-text-dim hover:text-text-muted cursor-pointer bg-transparent border-none shrink-0">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
