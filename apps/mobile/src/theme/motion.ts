/**
 * Motion tokens: durations and shared Reanimated easing curves so
 * animations stay consistent across components.
 */

import { Easing } from 'react-native-reanimated';

export const motion = {
  duration: {
    /** Imperceptible micro-detail (feedback). */
    fast: 120,
    /** Default transitions. */
    normal: 200,
    /** Large-surface / entrance transitions. */
    slow: 320,
    /** Ambient loops (orb breathing, idle waveform). */
    ambient: 1400,
  },
  easings: {
    standard: Easing.bezier(0.2, 0.0, 0.0, 1.0),
    emphasize: Easing.bezier(0.05, 0.0, 0.0, 1.0),
    decelerate: Easing.out(Easing.cubic),
    accelerate: Easing.in(Easing.cubic),
  },
  spring: {
    response: 280,
    damping: 26,
  },
} as const;

export type MotionTokens = typeof motion;