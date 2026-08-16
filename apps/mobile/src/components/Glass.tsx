/**
 * Glass surface primitive.
 *
 * Selective by design: `blurred` is opt-in (defaults to false) so we only
 * pay blur cost where glass actually earns it — floating controls, bottom
 * nav, sheets, model selector, selected cards. Everywhere else we render a
 * cheap translucent fill.
 */

import React from 'react';
import {
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { BlurView } from '@react-native-community/blur';

import { elevation, type ElevationLevel } from '../theme/elevation';
import { radius as radiusTokens } from '../theme/radius';
import { surfaces, type GlassLevel } from '../theme/surfaces';

export interface GlassProps {
  children?: React.ReactNode;
  /** Tint/intensity tier. Applied to both fill and (if blurred) the BlurView. */
  level?: GlassLevel;
  /** Enable the native backdrop blur (expensive — opt in deliberately). */
  blurred?: boolean;
  /** Corner radius token key (defaults to `lg`). */
  radius?: keyof typeof radiusTokens | number;
  /** Depth for the surface (applies soft shadow). */
  elevated?: ElevationLevel | boolean;
  style?: StyleProp<ViewStyle>;
}

export function Glass({
  children,
  level = 'medium',
  blurred = false,
  radius = 'lg',
  elevated,
  style,
}: GlassProps) {
  const spec = surfaces.glass[level];
  const corner = typeof radius === 'number' ? radius : radiusTokens[radius];
  const shadow =
    elevated === true
      ? elevation.raised
      : typeof elevated === 'string'
        ? elevation[elevated]
        : null;

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: spec.background,
          borderColor: spec.border,
          borderRadius: corner,
        },
        shadow ? shadowStyle(shadow) : null,
        style,
      ]}>
      {blurred && (
        <BlurView
          style={[StyleSheet.absoluteFill, { borderRadius: corner }]}
          blurType={spec.tint}
          blurAmount={spec.intensity}
          reducedTransparencyFallbackColor={spec.background}
        />
      )}
      {/* Hairline top highlight for a tactile "grounded" edge. */}
      <View
        pointerEvents="none"
        style={[styles.highlight, { borderColor: spec.highlight, borderTopLeftRadius: corner, borderTopRightRadius: corner }]}
      />
      {children}
    </View>
  );
}

function shadowStyle(e: (typeof elevation)[ElevationLevel]) {
  return {
    shadowColor: e.shadowColor,
    shadowOpacity: e.shadowOpacity,
    shadowRadius: e.shadowRadius,
    shadowOffset: e.shadowOffset,
    elevation: e.elevation,
  } as ViewStyle;
}

const styles = StyleSheet.create({
  container: {
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  highlight: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 1,
    borderTopWidth: StyleSheet.hairlineWidth * 2,
  },
});