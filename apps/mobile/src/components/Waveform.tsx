/**
 * Waveform — animated level bars for live audio.
 *
 * Foundation contract: when the audio service (Phase D) has live levels it
 * passes an array of normalised `peaks` (0..1); otherwise the surface pulses
 * a resting idle pattern. Callers never manage the animation themselves.
 */

import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { motion } from '../theme/motion';
import { colors } from '../theme/colors';

export interface WaveformProps {
  /** Normalised amplitude per bar (0..1). Omitting uses a resting pattern. */
  peaks?: number[];
  /** Render an active/pulsing surface (idle animation when no peaks given). */
  active?: boolean;
  barCount?: number;
  color?: string;
  height?: number;
  barWidth?: number;
  gap?: number;
}

const RESTING: number[] = [
  0.12, 0.2, 0.34, 0.24, 0.4, 0.56, 0.32, 0.48, 0.7, 0.44, 0.58, 0.36, 0.5,
  0.3, 0.18, 0.26,
];

export function Waveform({
  peaks,
  active = true,
  barCount = 32,
  color = colors.accent,
  height = 48,
  barWidth = 3,
  gap = 3,
}: WaveformProps) {
  const pulse = useSharedValue(0);

  useEffect(() => {
    if (active) {
      pulse.value = withRepeat(
        withTiming(1, { duration: 900 }),
        -1,
        true,
      );
    } else {
      pulse.value = withTiming(0, { duration: motion.duration.normal });
    }
  }, [active, pulse]);

  const groupStyle = useAnimatedStyle(() => ({
    opacity: 0.7 + pulse.value * 0.3,
    transform: [{ scaleY: 1 + pulse.value * 0.05 }],
  }));

  const resolved = peaks && peaks.length > 0 ? peaks : RESTING;
  const groupStyleProps = { height, gap } as const;

  return (
    <Animated.View
      style={[styles.group, groupStyleProps, groupStyle]}>
      {Array.from({ length: barCount }).map((_, i) => {
        const base = resolved[i % resolved.length];
        const value = peaks?.length ? Math.max(0.06, base) : base * (0.7 + 0.3 * Math.abs(Math.sin((i + 1) * 1.7)));
        return (
          <View
            key={`bar-${i}`}
            style={[
              styles.bar,
              {
                width: barWidth,
                height: Math.max(3, height * value),
                backgroundColor: color,
              },
            ]}
          />
        );
      })}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  group: {
    flexDirection: 'row',
    alignItems: 'center',
    transformOrigin: 'center',
  },
  bar: {
    borderRadius: 2,
  },
});