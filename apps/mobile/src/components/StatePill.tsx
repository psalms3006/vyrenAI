/**
 * StatePill — a compact indicator of the current AI state.
 * Colour/label come from the shared `aiStates` theme.
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { aiStateVisualOf } from '../theme/aiStates';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { AIState } from '../types';

export interface StatePillProps {
  state: AIState;
  /** Custom label overrides the theme label. */
  label?: string;
  compact?: boolean;
}

export function StatePill({ state, label, compact = false }: StatePillProps) {
  const visual = aiStateVisualOf(state);
  return (
    <View style={[styles.pill, compact && styles.compact]}>
      <View style={[styles.dot, { backgroundColor: visual.color }]} />
      <Text style={[styles.label, compact && styles.compactLabel]}>
        {label ?? visual.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(18,18,24,0.5)',
    borderColor: 'rgba(255,255,255,0.08)',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xxs + 1,
  },
  compact: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xxs,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: spacing.xs,
  },
  label: {
    ...typography.label,
    color: 'rgba(245,245,247,0.85)',
  },
  compactLabel: {
    ...typography.caption,
  },
});