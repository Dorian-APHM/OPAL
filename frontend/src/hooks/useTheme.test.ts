import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTheme } from './useTheme';

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.classList.remove('opal-theme-transitioning');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to dark theme', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('reads initial theme from localStorage', () => {
    localStorage.setItem('opal-theme', 'light');
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');
  });

  it('toggles from dark to light', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(localStorage.getItem('opal-theme')).toBe('light');
  });

  it('toggles from light to dark', () => {
    localStorage.setItem('opal-theme', 'light');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('dark');
  });

  it('setTheme updates state and DOM', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme('light'));
    expect(result.current.theme).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('adds transitioning class when toggling', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(document.documentElement.classList.contains('opal-theme-transitioning')).toBe(true);
  });

  it('does not add transitioning class on initial mount', () => {
    renderHook(() => useTheme());
    expect(document.documentElement.classList.contains('opal-theme-transitioning')).toBe(false);
  });

  it('ignores invalid localStorage values', () => {
    localStorage.setItem('opal-theme', 'invalid');
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
  });
});
