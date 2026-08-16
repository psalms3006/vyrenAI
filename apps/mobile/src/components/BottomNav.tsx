/**
 * BottomNav — floating glass tab bar.
 *
 * Router-agnostic: takes items + active key and calls back `onSelect`. The
 * tab navigator adapter (`navigation/BottomTabBar.tsx`) maps React Navigation
 * state onto it. Active state pairs an accent glyph with a small underline
 * indicator so selection is readable beyond colour.
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Glyph, type GlyphName } from './Glyph';
import { Glass } from './Glass';
import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

export interface BottomNavItem {
  key: string;
  label: string;
  /** Named glyph (preferred). */
  glyph?: GlyphName;
  /** Legacy freeform node slot (still supported). */
  icon?: React.ReactNode;
}

export interface BottomNavProps {
  items: BottomNavItem[];
  activeKey: string;
  onSelect: (key: string) => void;
  /** Glass bar (true) vs solid surface. Default true. */
  glass?: boolean;
  /** Layered on top of content (absolute + margins) vs an inline slot. */
  floating?: boolean;
}

export function BottomNav({
  items,
  activeKey,
  onSelect,
  glass = true,
  floating = false,
}: BottomNavProps) {
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        floating ? styles.floatingWrap : styles.inlineWrap,
        floating ? { bottom: Math.max(insets.bottom, spacing.lg) } : null,
      ]}>
      <Glass
        level="strong"
        blurred={glass}
        elevated="floating"
        radius="xl"
        style={styles.bar}>
        {items.map((item) => {
          const active = item.key === activeKey;
          return (
            <TabItem key={item.key} item={item} active={active} onSelect={onSelect} />
          );
        })}
      </Glass>
    </View>
  );
}

function TabItem({
  item,
  active,
  onSelect,
}: {
  item: BottomNavItem;
  active: boolean;
  onSelect: (key: string) => void;
}) {
  const indicator = useSharedValue(active ? 1 : 0);

  const indicatorStyle = useAnimatedStyle(() => ({
    opacity: withTiming(indicator.value, { duration: 160 }),
    transform: [{ scale: withTiming(0.4 + indicator.value * 0.6, { duration: 160 }) }],
  }));

  return (
    <Pressable
      key={item.key}
      onPress={() => onSelect(item.key)}
      accessibilityRole="tab"
      accessibilityState={{ selected: active }}
      accessibilityLabel={item.label}
      style={({ pressed }) => [styles.item, pressed && styles.pressed]}>
      <View style={styles.glyphSlot}>
        {item.glyph ? (
          <Glyph
            name={item.glyph}
            size={21}
            color={active ? colors.accent : colors.textSecondary}
          />
        ) : (
          item.icon
        )}
      </View>
      <Text style={[styles.label, active && styles.labelActive]} numberOfLines={1}>
        {item.label}
      </Text>
      <Animated.View
        style={[styles.indicator, active && styles.indicatorActive, indicatorStyle]}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  floatingWrap: {
    position: 'absolute',
    left: radius.lg,
    right: radius.lg,
    alignItems: 'center',
  },
  inlineWrap: {
    marginHorizontal: radius.lg,
    alignItems: 'center',
  },
  bar: {
    flexDirection: 'row',
    paddingVertical: spacing.xs,
    width: '100%',
    maxWidth: 520,
    paddingHorizontal: spacing.sm,
  },
  item: {
    flex: 1,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xs,
    overflow: 'hidden',
  },
  pressed: {
    opacity: 0.75,
  },
  glyphSlot: {
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 2,
  },
  label: {
    ...typography.caption,
    color: colors.textTertiary,
  },
  labelActive: {
    color: colors.textPrimary,
    fontWeight: '600',
  },
  indicator: {
    position: 'absolute',
    bottom: 3,
    width: 14,
    height: 3,
    borderRadius: 2,
    backgroundColor: 'transparent',
    opacity: 0,
  },
  indicatorActive: {
    backgroundColor: colors.accent,
  },
});