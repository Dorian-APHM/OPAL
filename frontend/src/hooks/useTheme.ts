import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';

const STORAGE_KEY = 'opal-theme';

function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'dark';
}

function applyTheme(theme: Theme, animate = true) {
  const root = document.documentElement;
  if (animate) {
    // Add transition class for smooth theme switch
    root.classList.add('opal-theme-transitioning');
    root.setAttribute('data-theme', theme);
    // Remove transition class after animation completes
    const cleanup = () => {
      root.classList.remove('opal-theme-transitioning');
      root.removeEventListener('transitionend', cleanup);
    };
    root.addEventListener('transitionend', cleanup);
    // Failsafe: remove after 600ms regardless
    setTimeout(() => root.classList.remove('opal-theme-transitioning'), 600);
  } else {
    root.setAttribute('data-theme', theme);
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);

  // Apply on mount (no animation for initial load)
  useEffect(() => {
    applyTheme(theme, false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t, true);
    setThemeState(t);
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  return { theme, setTheme, toggle } as const;
}
