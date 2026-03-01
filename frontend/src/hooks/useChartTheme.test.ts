import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useChartTheme } from './useChartTheme';
import { useTheme } from './useTheme';

describe('useChartTheme', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.classList.remove('opal-theme-transitioning');
  });

  it('returns dark chart theme by default', () => {
    const { result } = renderHook(() => useChartTheme());
    expect(result.current.grid).toBe('#1e293b');
    expect(result.current.blue).toBe('#3B82F6');
    expect(result.current.emerald).toBe('#10B981');
    expect(result.current.tooltipStyle.backgroundColor).toBe('#0f1629');
  });

  it('returns light chart theme when theme is light', () => {
    localStorage.setItem('opal-theme', 'light');
    const { result } = renderHook(() => useChartTheme());
    expect(result.current.grid).toBe('#B8AF99');
    expect(result.current.blue).toBe('#1D4ED8');
    expect(result.current.emerald).toBe('#047857');
    expect(result.current.tooltipStyle.backgroundColor).toBe('#F5F0E6');
  });

  it('has different colors for dark and light themes', () => {
    // Dark
    const { result: darkResult } = renderHook(() => useChartTheme());
    const darkBlue = darkResult.current.blue;
    const darkGrid = darkResult.current.grid;

    // Switch to light
    localStorage.setItem('opal-theme', 'light');
    const { result: lightResult } = renderHook(() => useChartTheme());

    expect(lightResult.current.blue).not.toBe(darkBlue);
    expect(lightResult.current.grid).not.toBe(darkGrid);
  });

  it('returns different palettes based on stored theme', () => {
    // Dark by default
    const { result: dark } = renderHook(() => useChartTheme());
    expect(dark.current.blue).toBe('#3B82F6');

    // Set light and re-render
    localStorage.setItem('opal-theme', 'light');
    document.documentElement.setAttribute('data-theme', 'light');
    const { result: light } = renderHook(() => useChartTheme());
    expect(light.current.blue).toBe('#1D4ED8');
  });

  it('tooltipStyle has consistent structure in both themes', () => {
    const { result } = renderHook(() => useChartTheme());
    const style = result.current.tooltipStyle;
    expect(style).toHaveProperty('backgroundColor');
    expect(style).toHaveProperty('border');
    expect(style).toHaveProperty('borderRadius');
    expect(typeof style.borderRadius).toBe('number');
  });

  it('all color values are valid hex strings', () => {
    const { result } = renderHook(() => useChartTheme());
    const hexRegex = /^#[0-9a-fA-F]{6}$/;
    const colorKeys = ['grid', 'axis', 'blue', 'emerald', 'red', 'orange', 'yellow', 'purple', 'cyan', 'reference', 'label'];
    for (const key of colorKeys) {
      expect((result.current as any)[key]).toMatch(hexRegex);
    }
  });
});
