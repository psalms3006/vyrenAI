/**
 * Design-token entry point. Import `theme` (or individual groups) from
 * anywhere in the app.
 */

export { colors, type ColorTokens } from './colors';
export { surfaces, type SurfaceTokens, type GlassLevel } from './surfaces';
export { typography, type TypographyTokens } from './typography';
export { spacing, type SpacingTokens } from './spacing';
export { radius, type RadiusTokens } from './radius';
export {
  elevation,
  type ElevationTokens,
  type ElevationLevel,
} from './elevation';
export { motion, type MotionTokens } from './motion';
export {
  aiStates,
  aiStateFallback,
  aiStateVisualOf,
  type AIStateVisual,
} from './aiStates';

import { colors } from './colors';
import { surfaces } from './surfaces';
import { typography } from './typography';
import { spacing } from './spacing';
import { radius } from './radius';
import { elevation } from './elevation';
import { motion } from './motion';
import { aiStates } from './aiStates';

/** Composite theme object for one-import access. */
export const theme = {
  colors,
  surfaces,
  typography,
  spacing,
  radius,
  elevation,
  motion,
  aiStates,
} as const;

export type Theme = typeof theme;