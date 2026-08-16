/**
 * ModelSheet — model selection.
 *
 * Consumes the model catalog through the API seam (`getModelCatalog()`; a
 * future `GET /api/models` publication flows in automatically). Models are
 * grouped by source — LIVE / TEXT / LOCAL — so the distinction is explicit.
 * No invented models, no billing UI. Only selection + the short note are
 * surfaced.
 */

import { useNavigation } from '@react-navigation/native';
import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Glyph } from '../components/Glyph';
import { modelInfoOf, type ModelInfo, type ModelSource } from '../models';
import { getModelCatalog } from '../services/api';
import { useApp } from '../state/AppContext';
import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';

const SOURCE_ORDER: ModelSource[] = ['live', 'text', 'local'];

const SOURCE_TITLE: Record<ModelSource, string> = {
  live: 'LIVE',
  text: 'TEXT',
  local: 'LOCAL',
};

const SOURCE_CAPTION: Record<ModelSource, string> = {
  live: 'Realtime voice + vision sessions',
  text: 'Conventional cloud completion',
  local: 'Served by Ollama on your VYREN server',
};

export function ModelSheet() {
  const navigation = useNavigation();
  const insets = useSafeAreaInsets();
  const { state, setModel } = useApp();

  const [models, setModels] = useState<ModelInfo[]>([]);

  useEffect(() => {
    let active = true;
    getModelCatalog().then((published) => {
      if (active) {
        setModels(published);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // Ensure the current model is always listed even if not in the catalog.
  const grouped = useMemo(() => {
    const all: ModelInfo[] = [...models];
    const current = state.model;
    if (current && !all.some((m) => m.id === current)) {
      all.unshift({
        id: current,
        name: modelInfoOf(current)?.name ?? current,
        source: modelInfoOf(current)?.source ?? 'text',
      });
    }
    return SOURCE_ORDER.map((source) => ({
      source,
      items: all.filter((m) => m.source === source),
    })).filter((group) => group.items.length > 0);
  }, [models, state.model]);

  const choose = (modelId: string) => {
    setModel(modelId);
    navigation.goBack();
  };

  return (
    <View style={[styles.screen, { paddingBottom: insets.bottom }]}>
      <View style={styles.header}>
        <Text style={styles.title}>Model</Text>
        <Text style={styles.subtitle}>The intelligence behind this session.</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}>
        {grouped.map(({ source, items }) => (
          <View key={source} style={styles.group}>
            <Text style={styles.groupTitle}>{SOURCE_TITLE[source]}</Text>
            <Text style={styles.groupCaption}>{SOURCE_CAPTION[source]}</Text>
            <View style={styles.list}>
              {items.map((model) => {
                const active = model.id === state.model;
                return (
                  <Pressable
                    key={model.id}
                    onPress={() => choose(model.id)}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active }}
                    style={({ pressed }) => [
                      styles.row,
                      active && styles.rowActive,
                      pressed && styles.pressed,
                    ]}>
                    <View style={styles.rowText}>
                      <Text style={[styles.rowName, active && styles.rowNameActive]}>
                        {model.name}
                      </Text>
                      {model.note ? (
                        <Text style={styles.rowNote} numberOfLines={2}>
                          {model.note}
                        </Text>
                      ) : null}
                    </View>
                    {active ? (
                      <View style={styles.checkDisc}>
                        <Glyph name="check" size={14} color={colors.accentForeground} />
                      </View>
                    ) : null}
                  </Pressable>
                );
              })}
            </View>
          </View>
        ))}

        {/* Forward note — capabilities the transport will surface later. */}
        <View style={styles.footnote}>
          <Text style={styles.footnoteText}>
            Voice names, sample rates and per-model capabilities attach to the
            live transport in Phase D. Selection here is persisted and honoured
            next session.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing['2xl'],
    paddingTop: spacing['2xl'],
    paddingBottom: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.textPrimary,
    marginBottom: spacing.xs,
  },
  subtitle: {
    ...typography.body,
    color: colors.textSecondary,
  },
  scroll: {
    paddingHorizontal: spacing['2xl'],
    paddingBottom: spacing['3xl'],
  },
  group: {
    marginBottom: spacing['2xl'],
  },
  groupTitle: {
    ...typography.caption,
    color: colors.textSecondary,
    letterSpacing: 2,
    fontWeight: '700',
    marginBottom: spacing.xxs,
  },
  groupCaption: {
    ...typography.caption,
    color: colors.textTertiary,
    marginBottom: spacing.md,
  },
  list: {
    gap: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.lg,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    minHeight: 56,
  },
  rowActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accentBorder,
  },
  pressed: {
    opacity: 0.8,
  },
  rowText: {
    flex: 1,
    marginRight: spacing.md,
  },
  rowName: {
    ...typography.bodyStrong,
    color: colors.textPrimary,
  },
  rowNameActive: {
    color: colors.accent,
  },
  rowNote: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xxs,
  },
  checkDisc: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  footnote: {
    marginTop: spacing.lg,
  },
  footnoteText: {
    ...typography.caption,
    color: colors.textTertiary,
    lineHeight: 18,
  },
});