/**
 * ErrorState — rich error display with illustration, message, and retry action.
 * Replaces bare "Something went wrong" with context-aware error screens.
 */
import { type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, WifiOff, ServerCrash, ShieldX, RefreshCw, Home } from 'lucide-react';
import { Button } from './Button';

type ErrorVariant = 'generic' | 'network' | 'server' | 'forbidden' | 'not-found';

interface ErrorStateProps {
  variant?: ErrorVariant;
  title?: string;
  message?: string;
  error?: Error | string | null;
  onRetry?: () => void;
  onGoHome?: () => void;
  retryLabel?: string;
  children?: ReactNode;
  compact?: boolean;
  className?: string;
}

const variantConfig: Record<ErrorVariant, { icon: ReactNode; title: string; message: string; color: string }> = {
  generic: {
    icon: <AlertTriangle className="h-10 w-10" />,
    title: 'Something went wrong',
    message: 'An unexpected error occurred. Please try again.',
    color: 'text-red-400/70',
  },
  network: {
    icon: <WifiOff className="h-10 w-10" />,
    title: 'Connection lost',
    message: 'Unable to reach the server. Check your connection and try again.',
    color: 'text-orange-400/70',
  },
  server: {
    icon: <ServerCrash className="h-10 w-10" />,
    title: 'Server error',
    message: 'The server encountered an error. Our team has been notified.',
    color: 'text-red-400/70',
  },
  forbidden: {
    icon: <ShieldX className="h-10 w-10" />,
    title: 'Access denied',
    message: 'You do not have permission to perform this action.',
    color: 'text-yellow-400/70',
  },
  'not-found': {
    icon: <AlertTriangle className="h-10 w-10" />,
    title: 'Not found',
    message: 'The requested resource could not be found.',
    color: 'text-text-dim/70',
  },
};

/** Detect error variant from an Error or HTTP status */
export function detectErrorVariant(error: unknown): ErrorVariant {
  if (!error) return 'generic';
  const msg = typeof error === 'string' ? error : (error as any)?.message || '';
  const status = (error as any)?.response?.status;
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not-found';
  if (status >= 500) return 'server';
  if (msg.includes('Network Error') || msg.includes('fetch') || msg.includes('ECONNREFUSED')) return 'network';
  return 'generic';
}

export function ErrorState({
  variant = 'generic',
  title,
  message,
  error,
  onRetry,
  onGoHome,
  retryLabel = 'Try again',
  children,
  compact = false,
  className = '',
}: ErrorStateProps) {
  const config = variantConfig[variant];
  const displayTitle = title || config.title;
  const displayMessage = message || config.message;
  const errorDetail = typeof error === 'string' ? error : (error as any)?.message;

  if (compact) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/6 border border-red-500/15 ${className}`}
      >
        <span className={config.color}><AlertTriangle className="h-5 w-5" /></span>
        <div className="flex-1 min-w-0">
          <span className="text-sm text-text-bright">{displayTitle}</span>
          {errorDetail && <span className="text-xs text-text-dim ml-2">— {errorDetail}</span>}
        </div>
        {onRetry && (
          <Button variant="ghost" size="small" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>
            {retryLabel}
          </Button>
        )}
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className={`flex flex-col items-center justify-center py-12 text-center ${className}`}
    >
      {/* Animated icon with shake on appear */}
      <motion.div
        initial={{ rotate: -5 }}
        animate={{ rotate: [0, -3, 3, -2, 0] }}
        transition={{ duration: 0.5, delay: 0.2 }}
        className={`relative mb-5 ${config.color}`}
      >
        {config.icon}
        <div className="absolute inset-0 -m-3 rounded-full bg-red-500/5 blur-md" />
      </motion.div>

      <h4 className="text-base font-semibold text-text-bright mb-1">{displayTitle}</h4>
      <p className="text-sm text-text-muted max-w-[320px] mb-2">{displayMessage}</p>

      {errorDetail && (
        <p className="text-xs text-text-dim/60 max-w-[400px] mb-4 font-mono break-all">{errorDetail}</p>
      )}

      <div className="flex items-center gap-2 mt-2">
        {onRetry && (
          <Button variant="primary" size="middle" icon={<RefreshCw className="h-4 w-4" />} onClick={onRetry}>
            {retryLabel}
          </Button>
        )}
        {onGoHome && (
          <Button variant="default" size="middle" icon={<Home className="h-4 w-4" />} onClick={onGoHome}>
            Go home
          </Button>
        )}
      </div>

      {children}
    </motion.div>
  );
}
