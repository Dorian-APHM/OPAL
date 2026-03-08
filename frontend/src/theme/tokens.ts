/**
 * OPAL Design Tokens
 * Centralized design system constants.
 */

// ── Colors ──────────────────────────────────────────────────
export const colors = {
  // Brand
  primary: '#1f77b4',
  primaryLight: '#3a8fc7',
  primaryDark: '#155a8a',

  // Accent (green)
  accent: '#2bc459',
  accentHover: '#24a34a',
  accentLight: '#e8f8ee',
  accentMuted: 'rgba(43, 196, 89, 0.15)',
  accentSubtle: 'rgba(43, 196, 89, 0.08)',
  accentGlow: 'rgba(43, 196, 89, 0.4)',

  // Sidebar
  sidebarStart: '#001529',
  sidebarEnd: '#001f3d',
  sidebarBorder: 'rgba(255, 255, 255, 0.08)',
  sidebarText: 'rgba(255, 255, 255, 0.65)',
  sidebarTextBright: 'rgba(255, 255, 255, 0.88)',

  // Surfaces
  bgLight: '#f0f2f5',
  bgDark: '#141414',
  cardBg: '#ffffff',
  cardBgDark: '#1f1f1f',

  // Functional
  success: '#2bc459',
  warning: '#faad14',
  error: '#ff4d4f',
  info: '#1f77b4',

  // Neutrals
  textPrimary: 'rgba(0, 0, 0, 0.88)',
  textSecondary: 'rgba(0, 0, 0, 0.45)',
  textDisabled: 'rgba(0, 0, 0, 0.25)',
  border: 'rgba(0, 0, 0, 0.06)',
  divider: 'rgba(0, 0, 0, 0.06)',

  // Charts
  chart: ['#1f77b4', '#2bc459', '#ff7f0e', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'],
} as const;

// ── Typography ──────────────────────────────────────────────
export const typography = {
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMono: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace",
  fontSize: {
    xs: 11,
    sm: 12,
    base: 14,
    md: 16,
    lg: 20,
    xl: 24,
    xxl: 30,
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  lineHeight: {
    tight: 1.3,
    normal: 1.5,
    relaxed: 1.7,
  },
} as const;

// ── Spacing ─────────────────────────────────────────────────
export const spacing = {
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 48,
} as const;

// ── Shadows ─────────────────────────────────────────────────
export const shadows = {
  sm: '0 1px 2px rgba(0, 0, 0, 0.04)',
  md: '0 2px 8px rgba(0, 0, 0, 0.06)',
  lg: '0 4px 16px rgba(0, 0, 0, 0.08)',
  xl: '0 8px 32px rgba(0, 0, 0, 0.12)',
  card: '0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.06)',
  cardHover: '0 4px 12px rgba(0, 0, 0, 0.08)',
  sidebar: '2px 0 8px rgba(0, 0, 0, 0.15)',
  glow: `0 0 20px rgba(43, 196, 89, 0.15)`,
} as const;

// ── Radii ───────────────────────────────────────────────────
export const radii = {
  sm: 4,
  md: 6,
  lg: 8,
  xl: 12,
  round: 9999,
} as const;

// ── Transitions ─────────────────────────────────────────────
export const transitions = {
  fast: '0.15s ease',
  normal: '0.2s ease',
  slow: '0.3s ease',
  spring: '0.4s cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const;

// ── Z-Index ─────────────────────────────────────────────────
export const zIndex = {
  sidebar: 100,
  header: 90,
  modal: 1000,
  tooltip: 1100,
} as const;

// ── Layout ──────────────────────────────────────────────────
export const layout = {
  sidebarWidth: 240,
  sidebarCollapsedWidth: 64,
  contentPadding: spacing.lg,
  headerHeight: 48,
} as const;
