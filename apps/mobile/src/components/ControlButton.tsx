/**
 * ControlButton — a round floating control (mic, camera, flip, pause…).
 *
 * Press feedback is a short, springy scale (Reanimated). When `active`, the
 * surface lifts to the accent fill so state is readable beyond colour changes.
 * Touch target is ≥44pt; the visible disc can be smaller than the hit area.
 *
 * Most geometry (disc radius, hit area, surface scale) derives from the `size`
 * prop at render time, so inline styles are the idiomatic form here.
 */

/* eslint-disable react-native/no-inline-styles */

import React, { useCallback } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { Glyph, type GlyphName } from './Glyph';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

export interface ControlButtonProps {
  glyph: GlyphName;
  onPress?: () => void;
  /** Accent-filled / emphasised state (e.g. mic live, playing). */
  active?: boolean;
  /** Renders a quiet "off" state instead of the default translucent one. */
  dimmed?: boolean;
  label?: string;
  size?: number;
  disabled?: boolean;
}

export function ControlButton({
  glyph,
  onPress,
  active = false,
  dimmed = false,
  label,
  size = 56,
  disabled = false,
}: ControlButtonProps) {
  const pressedScale = useSharedValue(1);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pressedScale.value }],
  }));

  const handlePressIn = useCallback(() => {
    pressedScale.value = withSpring(0.92, { damping: 18, stiffness: 300 });
  }, [pressedScale]);

  const handlePressOut = useCallback(() => {
    pressedScale.value = withSpring(1, { damping: 16, stiffness: 260 });
  }, [pressedScale]);

  const glyphColor = active
    ? colors.accentForeground
    : dimmed
      ? colors.textDisabled
      : colors.textPrimary;

  const backgroundColor = active
    ? colors.accent
    : dimmed
      ? 'rgba(255,255,255,0.04)'
      : 'rgba(30,30,38,0.55)';

  const borderColor = active
    ? colors.accentBorder
    : dimmed
      ? 'rgba(255,255,255,0.05)'
      : colors.border;

  return (
    <View style={{ alignItems: 'center' }}>
      <Animated.View style={animatedStyle}>
        <Pressable
          onPress={disabled ? undefined : onPress}
          onPressIn={handlePressIn}
          onPressOut={handlePressOut}
          accessibilityRole="button"
          accessibilityLabel={label}
          accessibilityState={{ selected: active, disabled: disabled || undefined }}
          style={({ pressed }) => [
            styles.hitArea,
            { width: Math.max(size, 44), height: Math.max(size, 44) },
            pressed && styles.dimmedPress,
          ]}>
          <View
            style={[
              styles.disc,
              {
                width: size,
                height: size,
                borderRadius: size / 2,
                backgroundColor,
                borderColor,
                opacity: disabled ? 0.4 : 1,
              },
            ]}>
            <Glyph name={glyph} size={size * 0.44} color={glyphColor} />
          </View>
        </Pressable>
      </Animated.View>
      {label ? (
        <Text style={[styles.caption, active && styles.captionActive]}>
          {label}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  hitArea: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  dimmedPress: {
    opacity: 0.8,
  },
  disc: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  caption: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xs,
    textAlign: 'center',
  },
  captionActive: {
    color: colors.accent,
  },
});