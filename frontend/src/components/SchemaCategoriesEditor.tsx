import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Layers } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cdmApi } from '../api/client';
import { Input } from './ui';
import type { OmopSchemaCategory } from '../types';

interface Props {
  /** Current per-category overrides ({ category: schema }). */
  value: Record<string, string>;
  /** Emitted whenever an override changes (only non-empty entries are kept). */
  onChange: (value: Record<string, string>) => void;
  /** Default schema — shown as placeholder when a category has no override. */
  defaultSchema: string;
}

// Fallback category order if the /cdm/categories endpoint is unavailable.
const FALLBACK_CATEGORIES: OmopSchemaCategory[] = [
  'clinical', 'health_system', 'health_economics', 'derived', 'metadata', 'vocabulary',
];

/**
 * Collapsible "advanced" editor letting the user assign a different PostgreSQL
 * schema to each OMOP CDM table category. Empty fields fall back to the default
 * schema, so the common single-schema setup needs no input here.
 */
export default function SchemaCategoriesEditor({ value, onChange, defaultSchema }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [categories, setCategories] = useState<string[]>(FALLBACK_CATEGORIES);
  const [tablesByCategory, setTablesByCategory] = useState<Record<string, string[]>>({});

  useEffect(() => {
    cdmApi.categories()
      .then((res) => {
        setCategories(res.data.categories);
        setTablesByCategory(res.data.tables || {});
      })
      .catch(() => { /* keep fallback */ });
  }, []);

  // Auto-expand when overrides already exist (so the user sees them).
  useEffect(() => {
    if (Object.keys(value).length > 0) setOpen(true);
  }, [value]);

  const setCategory = (category: string, schema: string) => {
    const next = { ...value };
    if (schema.trim()) {
      next[category] = schema.trim();
    } else {
      delete next[category];
    }
    onChange(next);
  };

  const overrideCount = Object.keys(value).length;

  return (
    <div className="border border-border-subtle rounded-lg">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-left"
      >
        <span className="flex items-center gap-2 text-xs font-medium text-text-muted">
          <Layers className="h-4 w-4" />
          {t('cdm.schema_categories', 'Per-category schemas (advanced)')}
          {overrideCount > 0 && (
            <span className="ml-1 px-1.5 py-0.5 rounded bg-emerald-accent/20 text-emerald-accent text-[10px]">
              {overrideCount}
            </span>
          )}
        </span>
        {open ? <ChevronDown className="h-4 w-4 text-text-muted" /> : <ChevronRight className="h-4 w-4 text-text-muted" />}
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3">
          <p className="text-[11px] text-text-dim">
            {t('cdm.schema_categories_help',
              'Leave a field empty to use the default schema. Set a schema to read that category of tables from a different schema (e.g. shared vocabulary).')}
          </p>
          {categories.map((category) => {
            const tables = tablesByCategory[category] || [];
            return (
              <div key={category}>
                <label className="block text-[11px] font-medium text-text-muted mb-1">
                  {t(`cdm.category.${category}`, category)}
                  {tables.length > 0 && (
                    <span className="ml-1 text-text-dim" title={tables.join(', ')}>
                      ({tables.length} {t('cdm.tables', 'tables')})
                    </span>
                  )}
                </label>
                <Input
                  value={value[category] ?? ''}
                  placeholder={defaultSchema || 'omop_cdm'}
                  onChange={(e) => setCategory(category, e.target.value)}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
