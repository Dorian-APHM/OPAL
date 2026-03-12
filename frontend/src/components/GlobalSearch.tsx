import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search, Users, BookOpen, Database,
  Code, GitBranch, Command, SearchX,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/KeycloakContext';
import { searchApi } from '../api/client';
import { Input } from '../components/ui/Input';
import { Spinner } from '../components/ui/Spinner';
import { Tag } from '../components/ui/Tag';

interface Props {
  selectedCdm: string | null;
}

type TagColor = 'blue' | 'green' | 'cyan' | 'purple' | 'orange';

const TYPE_CONFIG: Record<string, {
  icon: React.ReactNode;
  color: TagColor;
  label: string;
  route: string;
}> = {
  cohorts:       { icon: <Users className="h-3.5 w-3.5" />,       color: 'blue',   label: 'Cohort',       route: '/cohorts' },
  concepts:      { icon: <BookOpen className="h-3.5 w-3.5" />,    color: 'green',  label: 'Concept',      route: '/concepts' },
  source_values: { icon: <Database className="h-3.5 w-3.5" />,    color: 'cyan',   label: 'Source Value', route: '/concepts' },
  saved_queries: { icon: <Code className="h-3.5 w-3.5" />,        color: 'purple', label: 'Query',        route: '/cohorts' },
  mappings:      { icon: <GitBranch className="h-3.5 w-3.5" />,   color: 'orange', label: 'Mapping',      route: '/mapping' },
};

export default function GlobalSearch({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Record<string, any[]>>({});
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();
  const { hasPageAccess } = useAuth();

  // Flatten results for keyboard navigation
  const allResults: { type: string; item: any }[] = [];
  for (const [type, items] of Object.entries(results)) {
    for (const item of items) {
      allResults.push({ type, item });
    }
  }

  // Ctrl+K to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
      // Escape to close
      if (e.key === 'Escape' && open) {
        setOpen(false);
        inputRef.current?.blur();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        !inputRef.current?.parentElement?.parentElement?.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    if (open) {
      document.addEventListener('mousedown', handler);
      return () => document.removeEventListener('mousedown', handler);
    }
  }, [open]);

  const doSearch = useCallback(
    (q: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (!q.trim()) {
        setResults({});
        setTotal(0);
        setOpen(false);
        return;
      }
      debounceRef.current = setTimeout(async () => {
        setLoading(true);
        try {
          const res = await searchApi.search(q, selectedCdm || undefined, 8);
          const filtered: Record<string, any[]> = {};
          for (const [type, items] of Object.entries(res.data.results as Record<string, any[]>)) {
            const cfg = TYPE_CONFIG[type];
            if (cfg && hasPageAccess(cfg.route) && items.length > 0) {
              filtered[type] = items;
            }
          }
          setResults(filtered);
          setTotal(Object.values(filtered).reduce((s, arr) => s + arr.length, 0));
          setOpen(true);
        } catch {
          setResults({});
        } finally {
          setLoading(false);
        }
      }, 250);
    },
    [selectedCdm, hasPageAccess],
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setQuery(v);
    setActiveIndex(-1);
    doSearch(v);
  };

  const handleClear = () => {
    setQuery('');
    setResults({});
    setTotal(0);
    setOpen(false);
  };

  const handleNavigate = (type: string, item: any) => {
    setOpen(false);
    setQuery('');
    setResults({});

    switch (type) {
      case 'concepts':
        navigate('/concepts', { state: { searchQuery: item.concept_name || String(item.concept_id) } });
        break;
      case 'cohorts':
        navigate('/cohorts', { state: { openCohortId: item.id } });
        break;
      case 'saved_queries':
        navigate('/cohorts', { state: { tab: 'sql', queryId: item.id } });
        break;
      case 'source_values':
        navigate('/concepts', { state: { searchQuery: item.source_value, searchMode: 'source' } });
        break;
      case 'mappings':
        navigate('/mapping', { state: { searchQuery: item.source_value, domain: item.domain } });
        break;
      default:
        navigate(TYPE_CONFIG[type]?.route || '/');
    }
  };

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open || allResults.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev < allResults.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : allResults.length - 1));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      const { type, item } = allResults[activeIndex];
      handleNavigate(type, item);
    }
  };

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex >= 0 && dropdownRef.current) {
      const items = dropdownRef.current.querySelectorAll('[data-result-item]');
      items[activeIndex]?.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  const isOpen = open && (loading || query.length > 0);

  // Group results by type for rendering with section headers
  const groupedTypes = Object.entries(results);

  // Track cumulative index for keyboard highlight mapping
  let cumulativeIndex = 0;

  return (
    <div className="relative">
      <Input
        ref={inputRef}
        prefix={<Search className="h-4 w-4" />}
        suffix={
          query ? (
            <button
              onClick={handleClear}
              className="text-text-dim hover:text-text-muted transition-colors bg-transparent border-none cursor-pointer p-0"
              tabIndex={-1}
            >
              <SearchX className="h-3.5 w-3.5" />
            </button>
          ) : (
            <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-surface-light border border-glass-border text-[10px] text-text-dim font-mono">
              <Command className="h-2.5 w-2.5" />K
            </kbd>
          )
        }
        placeholder="Search..."
        value={query}
        onChange={handleChange}
        onFocus={() => { if (query.trim()) setOpen(true); }}
        onKeyDown={handleKeyDown}
        className="w-[280px] sm:w-[320px]"
      />

      {isOpen && (
        <div
          ref={dropdownRef}
          className="
            absolute top-full left-0 mt-2 w-[500px] max-h-[400px] overflow-auto z-50
            bg-surface border border-glass-border rounded-xl
            shadow-[0_8px_32px_rgba(0,0,0,0.4),0_0_0_1px_rgba(16,185,129,0.05)]
            backdrop-blur-sm
          "
        >
          {/* Loading state */}
          {loading && (
            <div className="flex items-center justify-center py-6">
              <Spinner size="small" />
            </div>
          )}

          {/* Empty state */}
          {!loading && query && allResults.length === 0 && (
            <div className="flex flex-col items-center py-8 text-text-dim">
              <SearchX className="h-8 w-8 opacity-40 mb-2" />
              <span className="text-sm">No results found</span>
            </div>
          )}

          {/* Results grouped by type */}
          {!loading && allResults.length > 0 && (
            <div className="py-1">
              {groupedTypes.map(([type, items]) => {
                const cfg = TYPE_CONFIG[type];
                if (!cfg) return null;

                const sectionItems = items.map((item, i) => {
                  const idx = cumulativeIndex + i;
                  return (
                    <button
                      key={`${type}-${i}`}
                      data-result-item
                      onClick={() => handleNavigate(type, item)}
                      className={`
                        w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors
                        border-none cursor-pointer bg-transparent
                        ${activeIndex === idx
                          ? 'bg-emerald-500/10 text-text-bright'
                          : 'text-text-muted hover:bg-surface-light hover:text-text-bright'
                        }
                      `}
                    >
                      <span className="shrink-0 text-text-dim">{cfg.icon}</span>
                      <Tag color={cfg.color} className="shrink-0 text-[10px]">
                        {cfg.label}
                      </Tag>
                      <span className="flex-1 text-sm font-medium truncate">
                        {item.name || item.concept_name || item.source_value}
                      </span>
                      {item.concept_code && (
                        <span className="text-[11px] text-text-dim shrink-0">
                          {item.vocabulary_id}:{item.concept_code}
                        </span>
                      )}
                      {item.concept_id && (
                        <span className="text-[11px] text-text-dim shrink-0">
                          #{item.concept_id}
                        </span>
                      )}
                      {item.domain && (
                        <Tag color="default" className="shrink-0 text-[10px]">
                          {String(t(`domains.${item.domain}`, item.domain))}
                        </Tag>
                      )}
                      {item.n_records != null && (
                        <span className="text-[11px] text-text-dim shrink-0">
                          {item.n_records.toLocaleString()} rec.
                        </span>
                      )}
                    </button>
                  );
                });

                cumulativeIndex += items.length;

                return (
                  <div key={type}>
                    <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-dim">
                      {cfg.label}s
                    </div>
                    {sectionItems}
                  </div>
                );
              })}
            </div>
          )}

          {/* Footer with total */}
          {!loading && total > 0 && (
            <div className="px-3 py-2 border-t border-glass-border flex items-center justify-between">
              <span className="text-[11px] text-text-dim">
                {total} result{total > 1 ? 's' : ''}
              </span>
              <span className="text-[10px] text-text-dim flex items-center gap-1">
                <kbd className="px-1 py-0.5 rounded bg-surface-light border border-glass-border font-mono text-[9px]">
                  ↑↓
                </kbd>
                navigate
                <kbd className="px-1 py-0.5 rounded bg-surface-light border border-glass-border font-mono text-[9px] ml-1">
                  ↵
                </kbd>
                select
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
