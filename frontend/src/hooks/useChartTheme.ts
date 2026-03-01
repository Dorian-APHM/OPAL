import { useMemo } from 'react';
import { useTheme } from './useTheme';

/** Theme-aware color palette for Recharts charts */
export interface ChartTheme {
  // Axis & grid
  grid: string;
  axis: string;
  // Tooltip
  tooltipBg: string;
  tooltipBorder: string;
  tooltipStyle: { backgroundColor: string; border: string; borderRadius: number };
  // Primary data colors
  blue: string;
  emerald: string;
  red: string;
  orange: string;
  yellow: string;
  purple: string;
  cyan: string;
  // Semantic
  reference: string;
  // Text on chart
  label: string;
}

const darkTheme: ChartTheme = {
  grid: '#1e293b',
  axis: '#64748b',
  tooltipBg: '#0f1629',
  tooltipBorder: '#1e293b',
  tooltipStyle: { backgroundColor: '#0f1629', border: '1px solid #1e293b', borderRadius: 8 },
  blue: '#3B82F6',
  emerald: '#10B981',
  red: '#ef4444',
  orange: '#f59e0b',
  yellow: '#faad14',
  purple: '#8b5cf6',
  cyan: '#06b6d4',
  reference: '#64748B',
  label: '#94a3b8',
};

const lightTheme: ChartTheme = {
  grid: '#B8AF99',
  axis: '#5E6D50',
  tooltipBg: '#F5F0E6',
  tooltipBorder: '#B8AF99',
  tooltipStyle: { backgroundColor: '#F5F0E6', border: '1px solid #B8AF99', borderRadius: 8 },
  blue: '#1D4ED8',
  emerald: '#047857',
  red: '#B91C1C',
  orange: '#B45309',
  yellow: '#92400E',
  purple: '#6D28D9',
  cyan: '#0E7490',
  reference: '#6B7A5C',
  label: '#3D4A2E',
};

export function useChartTheme(): ChartTheme {
  const { theme } = useTheme();
  return useMemo(() => (theme === 'light' ? lightTheme : darkTheme), [theme]);
}
