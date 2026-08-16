/** Spacing scale (4pt base). */

export const spacing = {
  /** 2 */
  xxs: 2,
  /** 4 */
  xs: 4,
  /** 8 */
  sm: 8,
  /** 12 */
  md: 12,
  /** 16 */
  lg: 16,
  /** 20 */
  xl: 20,
  /** 24 */
  '2xl': 24,
  /** 32 */
  '3xl': 32,
  /** 40 */
  '4xl': 40,
  /** 48 */
  '5xl': 48,
} as const;

export type SpacingTokens = typeof spacing;