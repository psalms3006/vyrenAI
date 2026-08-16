/**
 * Elevation / depth tokens. Two channels: iOS-style soft shadows and the
 * Android `elevation` value. Shadows are used sparingly (content-first).
 */

import { colors } from './colors';

export type ElevationLevel = 'flat' | 'raised' | 'floating' | 'overlay';

export interface ElevationToken {
  shadowColor: string;
  shadowOpacity: number;
  shadowRadius: number;
  shadowOffset: { width: number; height: number };
  elevation: number;
}

export const elevation = {
  flat: {
    shadowColor: colors.shadow,
    shadowOpacity: 0,
    shadowRadius: 0,
    shadowOffset: { width: 0, height: 0 },
    elevation: 0,
  } as ElevationToken,
  raised: {
    shadowColor: colors.shadow,
    shadowOpacity: 0.18,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  } as ElevationToken,
  floating: {
    shadowColor: colors.shadow,
    shadowOpacity: 0.28,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  } as ElevationToken,
  overlay: {
    shadowColor: colors.shadow,
    shadowOpacity: 0.4,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 10 },
    elevation: 16,
  } as ElevationToken,
} as const;

export type ElevationTokens = typeof elevation;