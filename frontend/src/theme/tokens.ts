/**
 * OPAL Design Tokens — Emerald Neumorphic Night
 * Centralized design system constants.
 */

// ── Colors ──────────────────────────────────────────────────
export const colors = {
  // Core surfaces
  deepBase: '#0B0F1A',
  surface: '#121826',
  surfaceLight: '#1c2539',
  surfaceDark: '#080b13',
  surfaceHover: '#182035',

  // Brand / Accent (Emerald)
  primary: '#10B981',
  primaryLight: '#34D399',
  primaryDark: '#059669',
  accent: '#10B981',
  accentHover: '#34D399',
  accentLight: 'rgba(16, 185, 129, 0.15)',
  accentMuted: 'rgba(16, 185, 129, 0.10)',
  accentSubtle: 'rgba(16, 185, 129, 0.06)',
  accentGlow: 'rgba(16, 185, 129, 0.4)',

  // Teal secondary
  teal: '#14b8a6',
  tealLight: '#2dd4bf',

  // Sidebar
  sidebarStart: '#0B0F1A',
  sidebarEnd: '#0e1324',
  sidebarBorder: 'rgba(255, 255, 255, 0.06)',
  sidebarText: 'rgba(255, 255, 255, 0.5)',
  sidebarTextBright: 'rgba(255, 255, 255, 0.88)',

  // Surfaces (legacy compat)
  bgLight: '#0B0F1A',
  bgDark: '#0B0F1A',
  cardBg: '#121826',
  cardBgDark: '#121826',

  // Text
  textPrimary: '#F8FAFC',
  textSecondary: '#94A3B8',
  textDisabled: '#475569',
  textDim: '#64748B',

  // Borders
  border: 'rgba(255, 255, 255, 0.03)',
  borderSubtle: 'rgba(255, 255, 255, 0.06)',
  borderGlow: 'rgba(16, 185, 129, 0.15)',
  divider: 'rgba(255, 255, 255, 0.06)',

  // Functional
  success: '#10B981',
  warning: '#F59E0B',
  error: '#EF4444',
  info: '#3B82F6',

  // Charts
  chart: ['#10B981', '#14b8a6', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#6366F1', '#84CC16', '#06B6D4'],
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

// ── Shadows (Neumorphic) ───────────────────────────────────
export const shadows = {
  sm: '2px 2px 4px #080b13, -2px -2px 4px #1c2539',
  md: '5px 5px 10px #080b13, -3px -3px 8px #1c2539',
  lg: '10px 10px 20px #080b13, -5px -5px 15px #1c2539',
  xl: '15px 15px 30px #080b13, -8px -8px 20px #1c2539',
  card: '10px 10px 20px #080b13, -5px -5px 15px #1c2539',
  cardHover: '12px 12px 24px #080b13, -6px -6px 18px #1c2539, 0 0 30px rgba(16, 185, 129, 0.15)',
  sidebar: '2px 0 12px rgba(0, 0, 0, 0.3)',
  glow: '0 0 20px rgba(16, 185, 129, 0.15)',
  glowStrong: '0 0 30px rgba(16, 185, 129, 0.3)',
  inset: 'inset 3px 3px 6px #080b13, inset -2px -2px 4px #1c2539',
} as const;

// ── Radii ───────────────────────────────────────────────────
export const radii = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  xxl: 24,
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
