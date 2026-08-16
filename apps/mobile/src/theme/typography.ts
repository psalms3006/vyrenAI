/**
 * Typography tokens. System fonts keep the app minimal and fast —
 * no bundled font assets.
 */

import { Platform } from 'react-native';

const family =
  Platform.OS === 'android'
    ? {
        regular: 'sans-serif',
        medium: 'sans-serif-medium',
        semibold: 'sans-serif-medium',
        bold: 'sans-serif',
      }
    : {
        regular: 'System',
        medium: 'System',
        semibold: 'System',
        bold: 'System',
      };

export const typography = {
  family,
  /** Display/logotype. */
  display: {
    fontSize: 34,
    lineHeight: 41,
    fontWeight: '700',
    letterSpacing: -0.5,
  } as const,
  /** Section headers. */
  title: {
    fontSize: 28,
    lineHeight: 34,
    fontWeight: '700',
    letterSpacing: -0.4,
  } as const,
  /** Screen-level headers. */
  heading: {
    fontSize: 21,
    lineHeight: 26,
    fontWeight: '600',
    letterSpacing: -0.2,
  } as const,
  /** Body copy. */
  body: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '400',
  } as const,
  /** Emphasized body. */
  bodyStrong: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '600',
  } as const,
  /** Labels, pills, captions. */
  label: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '500',
    letterSpacing: 0.1,
  } as const,
  /** Fine print / timestamps. */
  caption: {
    fontSize: 11,
    lineHeight: 15,
    fontWeight: '400',
    letterSpacing: 0.2,
  } as const,
  /** Buttons. */
  button: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '600',
    letterSpacing: 0.1,
  } as const,
} as const;

export type TypographyTokens = typeof typography;