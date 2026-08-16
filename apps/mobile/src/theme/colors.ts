/**
 * Core color palette + semantic colors.
 * Direction: dark, minimal, premium.
 */

export const palette = {
  /** Near-black canvases. */
  canvas: '#050506',
  background: '#0A0A0C',
  surface: '#121216',
  surfaceRaised: '#1A1A20',
  surfaceSunken: '#08080A',

  /** Neutral text ramps. */
  textPrimary: '#F5F5F7',
  textSecondary: 'rgba(245,245,247,0.64)',
  textTertiary: 'rgba(245,245,247,0.40)',
  textDisabled: 'rgba(245,245,247,0.24)',

  /** Borders. */
  border: 'rgba(255,255,255,0.08)',
  borderStrong: 'rgba(255,255,255,0.14)',
  borderSubtle: 'rgba(255,255,255,0.05)',

  /** Primary brand accent (single, restrained). */
  accent: '#A78BFA',
  accentSoft: 'rgba(167,139,250,0.14)',
  accentBorder: 'rgba(167,139,250,0.32)',
  accentForeground: '#0B0A10',

  /** Semantic states. */
  success: '#34D399',
  danger: '#F87171',
  warning: '#FBBF24',
  info: '#38BDF8',
} as const;

export const colors = {
  ...palette,
  /** Glass overlay — background behind a blur surface. */
  glassFill: 'rgba(18,18,24,0.55)',
  glassFillStrong: 'rgba(18,18,24,0.72)',
  glassFillWeak: 'rgba(24,24,32,0.38)',
  /** Hairline highlight on the top edge of a glass surface. */
  glassHighlight: 'rgba(255,255,255,0.10)',
  shadow: '#000000',
} as const;

export type ColorTokens = typeof colors;
export type SemanticColor =
  | 'accent'
  | 'success'
  | 'danger'
  | 'warning'
  | 'info';