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

// ── Light Mode Colors (Crème Sauge) ────────────────────────
export const lightColors = {
  deepBase: '#EDE7D9',
  surface: '#E0D9C8',
  surfaceLight: '#E8E2D3',
  surfaceDark: '#CFC8B6',
  surfaceHover: '#D8D1C0',

  primary: '#8FAE6B',
  primaryLight: '#A8C484',
  primaryDark: '#6B9E5A',
  accent: '#8FAE6B',
  accentHover: '#A8C484',
  accentLight: 'rgba(143, 174, 107, 0.15)',
  accentMuted: 'rgba(143, 174, 107, 0.10)',
  accentSubtle: 'rgba(143, 174, 107, 0.06)',
  accentGlow: 'rgba(143, 174, 107, 0.25)',

  teal: '#6B9E5A',
  tealLight: '#8BB87A',

  textPrimary: '#2D3B1E',
  textSecondary: '#5E6D50',
  textDisabled: '#A8B49C',
  textDim: '#8B9A7D',

  border: 'rgba(45, 59, 30, 0.08)',
  borderSubtle: 'rgba(45, 59, 30, 0.10)',
  borderGlow: 'rgba(143, 174, 107, 0.30)',
  divider: 'rgba(45, 59, 30, 0.10)',

  success: '#5A9E6F',
  warning: '#D4A04A',
  error: '#C75C5C',
  info: '#5B8DB8',

  chart: ['#8FAE6B', '#6B9E5A', '#5B8DB8', '#8B7EC8', '#D4A04A', '#C75C5C', '#D17BA5', '#6366F1', '#84CC16', '#06B6D4'],
} as const;

export const lightShadows = {
  sm: '2px 2px 4px #CFC8B6, -2px -2px 4px #E8E2D3',
  md: '3px 3px 8px #CFC8B6, -2px -2px 6px #E8E2D3',
  lg: '4px 4px 12px #CFC8B6, -3px -3px 8px #E8E2D3',
  xl: '6px 6px 16px #CFC8B6, -4px -4px 10px #E8E2D3',
  card: '3px 3px 10px #CFC8B6, -2px -2px 6px #E8E2D3',
  cardHover: '4px 4px 16px #C5BEAC, -3px -3px 8px #E8E2D3, 0 0 20px rgba(143, 174, 107, 0.10)',
  sidebar: '2px 0 12px rgba(45, 59, 30, 0.06)',
  glow: '0 0 20px rgba(143, 174, 107, 0.15)',
  glowStrong: '0 0 30px rgba(143, 174, 107, 0.25)',
  inset: 'inset 2px 2px 4px #CFC8B6, inset -2px -2px 4px #E8E2D3',
} as const;
