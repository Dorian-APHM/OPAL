import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, AlertCircle, Info, XCircle, X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'info' | 'warning';

const TOAST_DURATION = 4000;

interface Toast {
  id: number;
  type: ToastType;
  message: string;
  createdAt: number;
}

interface ToastContextType {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
  warning: (msg: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

let nextId = 0;

const icons: Record<ToastType, ReactNode> = {
  success: <CheckCircle className="h-5 w-5 text-emerald-400" />,
  error: <XCircle className="h-5 w-5 text-red-400" />,
  info: <Info className="h-5 w-5 text-blue-400" />,
  warning: <AlertCircle className="h-5 w-5 text-yellow-400" />,
};

const borderColors: Record<ToastType, string> = {
  success: 'border-l-emerald-500',
  error: 'border-l-red-500',
  info: 'border-l-blue-500',
  warning: 'border-l-yellow-500',
};

const progressColors: Record<ToastType, string> = {
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  info: 'bg-blue-500',
  warning: 'bg-yellow-500',
};

/** Countdown progress bar that shrinks from 100% to 0% */
function ToastProgress({ type, duration }: { type: ToastType; duration: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Force reflow before starting animation
    el.style.width = '100%';
    requestAnimationFrame(() => {
      el.style.transition = `width ${duration}ms linear`;
      el.style.width = '0%';
    });
  }, [duration]);

  return (
    <div className="absolute bottom-0 left-0 right-0 h-[2px] overflow-hidden rounded-b-xl">
      <div ref={ref} className={`h-full ${progressColors[type]} opacity-60`} />
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Track auto-dismiss timers so they can be cleared on manual close / unmount
  // (otherwise they fire setState after the provider has unmounted).
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const remove = useCallback((id: number) => {
    const tm = timers.current.get(id);
    if (tm) { clearTimeout(tm); timers.current.delete(id); }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, type, message, createdAt: Date.now() }]);
    const tm = setTimeout(() => {
      timers.current.delete(id);
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, TOAST_DURATION);
    timers.current.set(id, tm);
  }, []);

  // Clear any pending timers when the provider unmounts.
  useEffect(() => {
    const map = timers.current;
    return () => { map.forEach(clearTimeout); map.clear(); };
  }, []);

  const ctx: ToastContextType = {
    success: (msg) => addToast('success', msg),
    error: (msg) => addToast('error', msg),
    info: (msg) => addToast('info', msg),
    warning: (msg) => addToast('warning', msg),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      <div className="fixed top-4 right-4 z-[2000] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, x: 50, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 50, scale: 0.95 }}
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              role="alert"
              aria-live="assertive"
              className={`
                pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl relative overflow-hidden
                bg-surface border border-glass-border border-l-4 ${borderColors[toast.type]}
                shadow-[0_8px_32px_rgba(0,0,0,0.4)]
                min-w-[300px] max-w-[420px]
              `}
            >
              <motion.span
                initial={{ scale: 0, rotate: -180 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 20, delay: 0.1 }}
                aria-hidden="true"
              >
                {icons[toast.type]}
              </motion.span>
              <span className="flex-1 text-sm text-text-bright">{toast.message}</span>
              <button
                onClick={() => remove(toast.id)}
                className="text-text-dim hover:text-text-muted transition-colors cursor-pointer bg-transparent border-none shrink-0"
                aria-label="Close notification"
              >
                <X className="h-4 w-4" />
              </button>
              <ToastProgress type={toast.type} duration={TOAST_DURATION} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
