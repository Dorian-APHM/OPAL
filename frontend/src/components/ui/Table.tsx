import { type ReactNode, useState, useMemo } from 'react';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';

export interface Column<T> {
  key: string;
  title: ReactNode;
  dataIndex?: string;
  render?: (value: any, record: T, index: number) => ReactNode;
  sorter?: (a: T, b: T) => number;
  width?: string | number;
  ellipsis?: boolean;
  align?: 'left' | 'center' | 'right';
}

interface TableProps<T> {
  columns: Column<T>[];
  dataSource: T[];
  rowKey: string | ((record: T) => string);
  loading?: boolean;
  size?: 'small' | 'middle';
  scroll?: { x?: boolean | number; y?: number };
  onRow?: (record: T) => { onClick?: () => void; className?: string };
  emptyText?: ReactNode;
  pagination?: false | { pageSize: number; current?: number; total?: number; onChange?: (page: number) => void };
  className?: string;
}

function getNestedValue(obj: any, path: string): any {
  return path.split('.').reduce((acc, key) => acc?.[key], obj);
}

export function Table<T extends Record<string, any>>({
  columns,
  dataSource,
  rowKey,
  loading = false,
  size = 'middle',
  scroll,
  onRow,
  emptyText = 'No data',
  pagination,
  className = '',
}: TableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const pageSize = pagination ? pagination.pageSize : dataSource.length;

  const getKey = (record: T): string => {
    if (typeof rowKey === 'function') return rowKey(record);
    return String(record[rowKey]);
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return dataSource;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sorter) return dataSource;
    const sorted = [...dataSource].sort(col.sorter);
    return sortDir === 'desc' ? sorted.reverse() : sorted;
  }, [dataSource, sortKey, sortDir, columns]);

  const paginatedData = useMemo(() => {
    if (pagination === false || !pagination) return sortedData;
    const start = (page - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, page, pageSize, pagination]);

  const totalPages = pagination ? Math.ceil((pagination.total ?? dataSource.length) / pageSize) : 1;

  const handleSort = (col: Column<T>) => {
    if (!col.sorter) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(col.key);
      setSortDir('asc');
    }
  };

  const py = size === 'small' ? 'py-2' : 'py-3';
  const px = size === 'small' ? 'px-3' : 'px-4';

  return (
    <div className={`w-full ${className}`}>
      <div className={`overflow-auto ${scroll?.y ? `max-h-[${scroll.y}px]` : ''}`} style={scroll?.y ? { maxHeight: scroll.y } : undefined}>
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`${px} ${py} text-left text-xs font-semibold uppercase tracking-wider text-text-muted bg-surface-dark border-b border-glass-border sticky top-0 ${col.sorter ? 'cursor-pointer select-none hover:text-emerald-accent' : ''}`}
                  style={{ width: col.width, textAlign: col.align }}
                  onClick={() => handleSort(col)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.title}
                    {col.sorter && (
                      <span className="text-text-dim">
                        {sortKey === col.key ? (
                          sortDir === 'asc' ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronsUpDown className="h-3.5 w-3.5" />
                        )}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col.key} className={`${px} ${py} border-b border-border-subtle`}>
                      <div className="h-4 rounded bg-surface-light animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : paginatedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="py-12 text-center text-sm text-text-dim">
                  {emptyText}
                </td>
              </tr>
            ) : (
              paginatedData.map((record, index) => {
                const rowProps = onRow?.(record) ?? {};
                return (
                  <tr
                    key={getKey(record)}
                    className={`border-b border-border-subtle hover:bg-emerald-accent/4 transition-colors ${rowProps.onClick ? 'cursor-pointer' : ''} ${rowProps.className || ''}`}
                    onClick={rowProps.onClick}
                  >
                    {columns.map((col) => {
                      const value = col.dataIndex ? getNestedValue(record, col.dataIndex) : undefined;
                      return (
                        <td
                          key={col.key}
                          className={`${px} ${py} text-sm text-text-bright ${col.ellipsis ? 'truncate max-w-0' : ''}`}
                          style={{ width: col.width, textAlign: col.align }}
                        >
                          {col.render ? col.render(value, record, index) : (value ?? '—')}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pagination && totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-border-subtle">
          <span className="text-xs text-text-dim">
            {((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, pagination.total ?? dataSource.length)} of {pagination.total ?? dataSource.length}
          </span>
          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(totalPages, 7) }).map((_, i) => {
              const pageNum = i + 1;
              return (
                <button
                  key={pageNum}
                  onClick={() => { setPage(pageNum); pagination.onChange?.(pageNum); }}
                  className={`min-w-[32px] h-8 px-2 rounded-lg text-xs font-medium transition-colors cursor-pointer border ${
                    page === pageNum
                      ? 'bg-emerald-accent/12 border-emerald-accent text-emerald-accent'
                      : 'bg-surface-light border-glass-border text-text-muted hover:border-border-glow hover:text-emerald-accent'
                  }`}
                >
                  {pageNum}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
