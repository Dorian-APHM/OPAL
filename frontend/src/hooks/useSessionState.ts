/**
 * In-memory state that survives React component unmount/remount (navigation).
 * Resets on full page refresh (F5), which is the expected behavior.
 *
 * Usage:
 *   const [value, setValue] = useSessionState('quality:selectedDomain', null);
 *
 * The key should be unique across the app (namespace with page name).
 */
import { useState, useCallback, useRef, useEffect } from 'react';

// Global in-memory store — survives component unmounts but not page reloads
const store = new Map<string, unknown>();

export function useSessionState<T>(key: string, initialValue: T): [T, (v: T | ((prev: T) => T)) => void] {
  const prevKeyRef = useRef(key);
  const initialValueRef = useRef(initialValue);

  const [state, setState] = useState<T>(() =>
    store.has(key) ? (store.get(key) as T) : initialValue
  );

  // When the key changes, save current state under old key, then load new key's value
  if (prevKeyRef.current !== key) {
    // Persist current state under the OLD key before switching
    store.set(prevKeyRef.current, state);
    prevKeyRef.current = key;
    initialValueRef.current = initialValue;
    // Read value for the NEW key
    const newValue = store.has(key) ? (store.get(key) as T) : initialValue;
    setState(newValue);
  }

  // Keep store in sync
  useEffect(() => {
    store.set(key, state);
  }, [key, state]);

  const setSessionState = useCallback(
    (valueOrUpdater: T | ((prev: T) => T)) => {
      setState((prev) => {
        const next =
          typeof valueOrUpdater === 'function'
            ? (valueOrUpdater as (prev: T) => T)(prev)
            : valueOrUpdater;
        store.set(key, next);
        return next;
      });
    },
    [key]
  );

  return [state, setSessionState];
}

/**
 * Pre-set a value for a key whose owning component is currently unmounted
 * (e.g. cross-tab navigation: set the target tab's filters, then switch tab —
 * the component reads the value from the store on mount).
 * Has no effect on an already-mounted component.
 */
export function setSessionStateValue<T>(key: string, value: T) {
  store.set(key, value);
}

/** Clear all session state (e.g. on logout) */
export function clearSessionState() {
  store.clear();
}

/** Clear session state for a specific prefix (e.g. 'quality:') */
export function clearSessionStatePrefix(prefix: string) {
  for (const key of store.keys()) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}
