import { describe, it, expect } from 'vitest';
import en from './en.json';
import fr from './fr.json';

/** Flatten a nested translation object into a set of dotted keys. */
function flatten(obj: Record<string, unknown>, prefix = '', out = new Set<string>()): Set<string> {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') flatten(v as Record<string, unknown>, key, out);
    else out.add(key);
  }
  return out;
}

// Eagerly load every source file as raw text (Vite feature — no Node builtins needed).
const sources = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Extract every t('key' | "key" | `key`) usage from the source tree (excluding tests). */
function collectUsedKeys(): Set<string> {
  const keys = new Set<string>();
  // `t(` not preceded by an identifier char (avoids e.g. `format(`), then a literal key.
  const re = /[^a-zA-Z0-9_]t\(\s*['"`]([a-zA-Z0-9_.]+)['"`]/g;
  for (const [path, content] of Object.entries(sources)) {
    if (/\.test\.(ts|tsx)$/.test(path)) continue;
    let m: RegExpExecArray | null;
    while ((m = re.exec(content)) !== null) keys.add(m[1]);
  }
  return keys;
}

const enKeys = flatten(en as Record<string, unknown>);
const frKeys = flatten(fr as Record<string, unknown>);
const usedKeys = collectUsedKeys();

describe('i18n completeness', () => {
  it('exposes the same set of keys in en.json and fr.json', () => {
    const onlyEn = [...enKeys].filter((k) => !frKeys.has(k));
    const onlyFr = [...frKeys].filter((k) => !enKeys.has(k));
    expect({ onlyEn, onlyFr }).toEqual({ onlyEn: [], onlyFr: [] });
  });

  it('defines every t() key used in the codebase in en.json', () => {
    const missing = [...usedKeys].filter((k) => !enKeys.has(k));
    expect(missing).toEqual([]);
  });

  it('defines every t() key used in the codebase in fr.json (no English fallback leaks in FR)', () => {
    const missing = [...usedKeys].filter((k) => !frKeys.has(k));
    expect(missing).toEqual([]);
  });
});
