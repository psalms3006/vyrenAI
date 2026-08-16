/**
 * ModelChip — shows the active model (name + source tag) and opens the model
 * sheet. Tappable shortcut used from Home / Live / Settings.
 */

import { useNavigation, type NavigationProp } from '@react-navigation/native';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Glyph } from './Glyph';
import { modelInfoOf, sourceLabel } from '../models';
import type { RootStackParamList } from '../navigation/types';
import { useApp } from '../state/AppContext';
import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

type RootNav = NavigationProp<RootStackParamList>;

export function ModelChip() {
  const navigation = useNavigation<RootNav>();
  const { state } = useApp();
  const info = modelInfoOf(state.model || undefined);

  return (
    <Pressable
      onPress={() => navigation.navigate('ModelSheet')}
      accessibilityRole="button"
      accessibilityLabel={`Model: ${info?.name ?? 'unset'}`}
      style={({ pressed }) => [styles.chip, pressed && styles.pressed]}>
      {info ? (
        <View
          style={[styles.tag, { backgroundColor: sourceColor(info.source) }]}>
          <Text style={styles.tagText}>{sourceLabel(info.source)}</Text>
        </View>
      ) : null}
      <Text style={styles.label} numberOfLines={1}>
        {info?.name ?? 'Choose model'}
      </Text>
      <Glyph name="chevronRight" size={14} color={colors.textTertiary} />
    </Pressable>
  );
}

function sourceColor(source: 'live' | 'text' | 'local'): string {
  switch (source) {
    case 'live':
      return colors.accentSoft;
    case 'local':
      return 'rgba(251,191,36,0.12)';
    case 'text':
      return 'rgba(56,189,248,0.1)';
  }
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(30,30,38,0.55)',
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingVertical: spacing.xs,
    paddingLeft: spacing.xs,
    paddingRight: spacing.md,
    maxWidth: 220,
  },
  pressed: {
    opacity: 0.75,
  },
  tag: {
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    marginRight: spacing.xs,
  },
  tagText: {
    ...typography.caption,
    color: colors.textPrimary,
    fontWeight: '700',
    letterSpacing: 0.6,
    fontSize: 9,
  },
  label: {
    ...typography.label,
    color: colors.textPrimary,
    flexShrink: 1,
    marginRight: spacing.xs,
  },
});