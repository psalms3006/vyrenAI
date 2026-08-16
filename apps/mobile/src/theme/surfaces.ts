/**
 * Surface tokens: how content surfaces are layered and, where used, how
 * glass surfaces are threaded. Glass is opt-in — components request it via
 * the `surfaces.glass.*` tokens instead of applying blur everywhere.
 */

import type { BlurViewProps } from '@react-native-community/blur';
import { colors } from './colors';

export type GlassLevel = 'weak' | 'medium' | 'strong';

interface GlassSurface {
  /** BlurView tint (iOS semantics; Android ignores tint). */
  tint: NonNullable<BlurViewProps['blurType']>;
  intensity: number;
  blurRadius: number;
  /** Translucent fill shown always (also the Android/fallback fill). */
  background: string;
  border: string;
  highlight: string;
}

export const surfaces = {
  /** Solid layers, from lowest to highest. */
  solid: {
    canvas: colors.canvas,
    background: colors.background,
    surface: colors.surface,
    raised: colors.surfaceRaised,
    sunken: colors.surfaceSunken,
  },

  /** Translucent + blurr. Keep counts of truly-blurred surfaces low. */
  glass: {
    weak: {
      tint: 'dark',
      intensity: 40,
      blurRadius: 12,
      background: colors.glassFillWeak,
      border: colors.borderSubtle,
      highlight: colors.glassHighlight,
    } as GlassSurface,
    medium: {
      tint: 'dark',
      intensity: 60,
      blurRadius: 20,
      background: colors.glassFill,
      border: colors.border,
      highlight: colors.glassHighlight,
    } as GlassSurface,
    strong: {
      tint: 'dark',
      intensity: 80,
      blurRadius: 28,
      background: colors.glassFillStrong,
      border: colors.borderStrong,
      highlight: colors.glassHighlight,
    } as GlassSurface,
  },

  /** Default blur strength for a surface. */
  blurDefault: 20,
} as const;

export type SurfaceTokens = typeof surfaces;