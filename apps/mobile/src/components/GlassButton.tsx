/**
 * GlassButton — the primary pressable surface.
 *
 * Variants: `primary` is a solid accent surface (no glass — content first),
 * while `secondary` / `ghost` are translucent (glass where appropriate).
 * Purely decorative glass is avoided.
 */

import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { Glass } from './Glass';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface GlassButtonProps {
  label: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  /** Optional trailing/leading icon node (rendered before the label). */
  leadingIcon?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}

const HEIGHT: Record<ButtonSize, number> = { sm: 34, md: 44, lg: 52 };

function variantColors(variant: ButtonVariant) {
  switch (variant) {
    case 'primary':
      return {
        background: colors.accent,
        foreground: colors.accentForeground,
        border: colors.accentBorder,
        blurred: false,
      };
    case 'secondary':
      return {
        background: colors.glassFillWeak,
        foreground: colors.textPrimary,
        border: colors.border,
        blurred: true,
      };
    case 'ghost':
      return {
        background: 'transparent',
        foreground: colors.textSecondary,
        border: 'transparent',
        blurred: false,
      };
    case 'danger':
      return {
        background: colors.glassFillWeak,
        foreground: colors.danger,
        border: colors.border,
        blurred: true,
      };
  }
}

export function GlassButton({
  label,
  onPress,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  leadingIcon,
  style,
}: GlassButtonProps) {
  const palette = variantColors(variant);
  const height = HEIGHT[size];
  const inactive = disabled || loading;

  return (
    <Pressable
      onPress={disabled || loading ? undefined : onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: inactive, busy: loading }}
      style={({ pressed }) => [
        { height, opacity: inactive ? 0.5 : pressed ? 0.85 : 1 },
        style,
      ]}>
      <Glass
        level="medium"
        blurred={palette.blurred}
        radius="pill"
        style={[
          styles.base,
          {
            backgroundColor: palette.background,
            borderColor: palette.border,
          },
        ]}>
        {loading ? (
          <ActivityIndicator color={palette.foreground} size="small" />
        ) : (
          <Text style={[styles.label, { color: palette.foreground }]}>
            {leadingIcon}
            {label}
          </Text>
        )}
      </Glass>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    borderWidth: StyleSheet.hairlineWidth,
  },
  label: {
    ...typography.button,
    textAlign: 'center',
    includeFontPadding: false,
  },
});