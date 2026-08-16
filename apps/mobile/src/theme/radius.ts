/** Corner radii. */

export const radius = {
  /** 6 */
  sm: 6,
  /** 12 */
  md: 12,
  /** 16 */
  lg: 16,
  /** 24 */
  xl: 24,
  /** 999 — pill/circle. */
  pill: 999,
} as const;

export type RadiusTokens = typeof radius;