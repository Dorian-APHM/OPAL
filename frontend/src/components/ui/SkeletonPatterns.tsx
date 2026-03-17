/**
 * Contextual skeleton loaders that match the shape of actual content.
 * These replace generic "lines" skeletons with layout-aware placeholders.
 */

const pulse = 'animate-pulse bg-surface-light rounded';

/** Skeleton matching a Card with title bar + body content */
export function CardSkeleton({ lines = 3, accent = false }: { lines?: number; accent?: boolean }) {
  return (
    <div className={`bg-surface rounded-2xl border border-border-subtle opal-card-shadow overflow-hidden ${accent ? 'border-t-2 border-t-emerald-accent/30' : ''}`}>
      <div className="flex items-center justify-between px-6 py-4 border-b border-glass-border">
        <div className={`${pulse} h-4 w-32`} />
        <div className={`${pulse} h-4 w-16`} />
      </div>
      <div className="p-6 space-y-3">
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} className={`${pulse} h-4`} style={{ width: i === 0 ? '90%' : i === lines - 1 ? '50%' : '100%' }} />
        ))}
      </div>
    </div>
  );
}

/** Skeleton for a stat/metric card */
export function StatSkeleton() {
  return (
    <div className="bg-surface rounded-2xl border border-border-subtle opal-card-shadow p-4">
      <div className={`${pulse} h-3 w-20 mb-3`} />
      <div className={`${pulse} h-8 w-24 mb-2`} />
      <div className={`${pulse} h-3 w-16`} />
    </div>
  );
}

/** Skeleton for a table with header + rows */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-surface rounded-2xl border border-border-subtle opal-card-shadow overflow-hidden">
      {/* Header */}
      <div className="flex gap-4 px-4 py-3 bg-surface-dark border-b border-glass-border">
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className={`${pulse} h-3 flex-1`} style={{ maxWidth: i === 0 ? '30%' : undefined }} />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, ri) => (
        <div key={ri} className="flex gap-4 px-4 py-3 border-b border-border-subtle last:border-0">
          {Array.from({ length: cols }).map((_, ci) => (
            <div key={ci} className={`${pulse} h-4 flex-1`} style={{ maxWidth: ci === 0 ? '30%' : undefined, animationDelay: `${ri * 0.05}s` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Skeleton for the dashboard domain grid */
export function DashboardSkeleton() {
  return (
    <div className="py-3 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-3 mb-1">
        <div className={`${pulse} h-6 w-6 rounded`} />
        <div className={`${pulse} h-6 w-32`} />
        <div className={`${pulse} h-5 w-16 rounded-full`} />
      </div>
      {/* Domain grid */}
      <div className="grid grid-cols-5 xl:grid-cols-9 gap-2">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="bg-surface rounded-2xl border border-border-subtle p-3" style={{ animationDelay: `${i * 0.05}s` }}>
            <div className={`${pulse} h-2.5 w-12 mb-2`} />
            <div className={`${pulse} h-5 w-16 mb-1.5`} />
            <div className={`${pulse} h-2.5 w-10`} />
          </div>
        ))}
      </div>
      {/* Two column cards */}
      <div className="grid grid-cols-2 gap-2">
        <CardSkeleton lines={4} />
        <CardSkeleton lines={4} />
      </div>
    </div>
  );
}

/** Skeleton for a list of items (notifications, favorites, etc.) */
export function ListSkeleton({ items = 4 }: { items?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2.5 rounded-lg" style={{ animationDelay: `${i * 0.06}s` }}>
          <div className={`${pulse} h-8 w-8 rounded-full shrink-0`} />
          <div className="flex-1 space-y-1.5">
            <div className={`${pulse} h-3.5 w-3/4`} />
            <div className={`${pulse} h-2.5 w-1/2`} />
          </div>
          <div className={`${pulse} h-4 w-12 rounded-full`} />
        </div>
      ))}
    </div>
  );
}

/** Inline shimmer effect for a single value (e.g., a badge count loading) */
export function InlineSkeleton({ width = 32, height = 16 }: { width?: number; height?: number }) {
  return <span className={`${pulse} inline-block rounded`} style={{ width, height, verticalAlign: 'middle' }} />;
}
