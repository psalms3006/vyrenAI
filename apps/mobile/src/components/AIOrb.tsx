/**
 * AIOrb — the ambient indicator that reflects the current AI state.
 *
 * Colour + glow are derived from the shared `aiStates` theme so the orb
 * never hardcodes state colours. It is a decorative, animated surface:
 * halo (soft glow) + rotating ring + core.
 */

import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { motion } from '../theme/motion';
import { aiStateVisualOf } from '../theme/aiStates';
import type { AIState } from '../types';

export interface AIOrbProps {
  state: AIState;
  /** Diameter of the orb core (px). */
  size?: number;
  /** Drives idle breathing; when false the orb sits still. */
  active?: boolean;
  /** Show the soft glow halo. Default true. */
  glow?: boolean;
}

export function AIOrb({
  state,
  size = 96,
  active = true,
  glow = true,
}: AIOrbProps) {
  const visual = aiStateVisualOf(state);
  const breath = useSharedValue(0);

  useEffect(() => {
    if (active) {
      breath.value = 0;
      breath.value = withRepeat(
        withTiming(1, { duration: motion.duration.ambient, easing: Easing.inOut(Easing.sin) }),
        -1,
        true,
      );
    } else {
      breath.value = withTiming(0, { duration: motion.duration.normal });
    }
  }, [active, breath]);

  const haloStyle = useAnimatedStyle(() => {
    const scale = 1 + breath.value * 0.06;
    return { transform: [{ scale }], opacity: 0.32 + breath.value * 0.18 };
  });

  const ringSpin = useSharedValue(0);
  useEffect(() => {
    ringSpin.value = 0;
    ringSpin.value = withRepeat(
      withTiming(360, { duration: 5200, easing: Easing.linear }),
      -1,
    );
  }, [ringSpin]);

  const coreStyle = useAnimatedStyle(() => {
    const scale = 1 + breath.value * 0.04;
    return { transform: [{ scale }] };
  });

  const ringStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${ringSpin.value}deg` }],
  }));

  return (
    <View
      style={[
        { width: size + (glow ? 24 : 0), height: size + (glow ? 24 : 0) },
        styles.wrap,
      ]}
      pointerEvents="none">
      {glow && (
        <Animated.View
          style={[
            styles.halo,
            {
              width: size,
              height: size,
              borderRadius: size / 2,
              backgroundColor: visual.glow,
            },
            haloStyle,
          ]}
        />
      )}
      <View
        style={[
          styles.stage,
          { width: size, height: size, borderRadius: size / 2 },
        ]}>
        <Animated.View
          style={[
            styles.ring,
            { width: size * 0.92, height: size * 0.92, borderRadius: (size * 0.92) / 2 },
            { borderColor: visual.glow },
            ringStyle,
          ]}>
          <View
            style={[styles.gem, { backgroundColor: visual.color }]}
          />
        </Animated.View>
        <Animated.View
          style={[
            styles.core,
            { width: size * 0.5, height: size * 0.5, borderRadius: (size * 0.5) / 2 },
            { backgroundColor: visual.color },
            coreStyle,
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  halo: {
    position: 'absolute',
  },
  stage: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  ring: {
    position: 'absolute',
    borderWidth: 1.5,
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingLeft: 6,
  },
  gem: {
    width: 5,
    height: 5,
    borderRadius: 3,
  },
  core: {
    // Layered translucent fill gives a soft radial falloff without a gradient lib.
    shadowColor: 'rgba(255,255,255,0.35)',
    shadowOpacity: 0.4,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 },
  },
});