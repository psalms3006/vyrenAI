/**
 * SuggestionCard — a tappable suggestion / action card.
 *
 * The resting state is a flat solid surface (content first); only selected
 * cards switch to the (more prominent) glass surface, keeping glass scarce.
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import { Glass } from './Glass';

export interface SuggestionCardProps {
  title: string;
  body?: string;
  /** Leading glyph (use <Glyph>). */
  icon?: React.ReactNode;
  selected?: boolean;
  onPress?: () => void;
}

export function SuggestionCard({
  title,
  body,
  icon,
  selected = false,
  onPress,
}: SuggestionCardProps) {
  const content = (
    <View style={styles.inner}>
      {icon ? <View style={styles.icon}>{icon}</View> : null}
      <View style={styles.text}>
        <Text style={[styles.title, selected && styles.titleSelected]}>
          {title}
        </Text>
        {body ? <Text style={styles.body}>{body}</Text> : null}
      </View>
    </View>
  );

  if (selected) {
    return (
      <Glass level="medium" blurred elevated="raised" radius="lg" style={styles.card}>
        {content}
      </Glass>
    );
  }

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.card,
        styles.flatCard,
        pressed && styles.pressed,
      ]}>
      {content}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
  flatCard: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
  },
  pressed: {
    opacity: 0.85,
  },
  inner: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    backgroundColor: colors.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.md,
  },
  text: {
    flex: 1,
  },
  title: {
    ...typography.bodyStrong,
    color: colors.textPrimary,
  },
  titleSelected: {
    color: colors.accent,
  },
  body: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xxs,
  },
});