/**
 * SettingsScreen — server connection, preferences and about.
 *
 * Server URL + model + preferences persist via the existing AsyncStorage
 * service (through AppContext). Nothing here invents backend behaviour: the
 * voice row only lists the voice the server reports, and camera/audio rows
 * persist local preferences.
 */

import { useNavigation, type NavigationProp } from '@react-navigation/native';
import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { GlassButton } from '../components/GlassButton';
import { Glyph } from '../components/Glyph';
import { DEFAULT_SERVER_URL, normalizeServerUrl } from '../config';
import { useApp } from '../state/AppContext';
import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { RootStackParamList } from '../navigation/types';

type SettingsNav = NavigationProp<RootStackParamList>;

interface SettingRowProps {
  title: string;
  caption?: string;
  onPress?: () => void;
  right?: React.ReactNode;
}

function SettingRow({ title, caption, onPress, right }: SettingRowProps) {
  const content = (
    <View style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{title}</Text>
        {caption ? <Text style={styles.rowCaption}>{caption}</Text> : null}
      </View>
      {right ?? null}
    </View>
  );
  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        style={({ pressed }) => [styles.rowWrap, pressed && styles.pressed]}>
        {content}
      </Pressable>
    );
  }
  return <View style={styles.rowWrap}>{content}</View>;
}

export function SettingsScreen() {
  const navigation = useNavigation<SettingsNav>();
  const insets = useSafeAreaInsets();
  const { state, setServerUrl, updatePreferences } = useApp();

  const [url, setUrl] = useState(state.serverUrl || DEFAULT_SERVER_URL);
  const [saved, setSaved] = useState(false);

  const onSave = async () => {
    await setServerUrl(normalizeServerUrl(url));
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  const status = state.status;
  const connectionLabel =
    state.connection === 'connected'
      ? 'Connected'
      : state.connection === 'error'
        ? 'Unreachable'
        : state.connection === 'connecting'
          ? 'Connecting…'
          : 'Not checked yet';

  const voiceLabel = state.preferences.voiceName || status?.voice_name || '—';

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        style={styles.flex}
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: Math.max(insets.bottom, spacing['2xl']) },
        ]}
        keyboardShouldPersistTaps="handled">
        {/* Server */}
        <Text style={styles.sectionLabel}>Server</Text>
        <View style={styles.section}>
          <Text style={styles.fieldLabel}>VYREN server URL</Text>
          <TextInput
            style={styles.input}
            value={url}
            onChangeText={(v) => {
              setUrl(v);
              setSaved(false);
            }}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder="http://10.0.2.2:8420"
            placeholderTextColor={colors.textTertiary}
          />
          <Text style={styles.fieldHint}>
            Persisted locally; every API and WebSocket call uses it.
          </Text>
          <GlassButton
            label={saved ? 'Saved' : 'Save'}
            variant={saved ? 'secondary' : 'primary'}
            onPress={onSave}
            style={styles.save}
          />
        </View>

        {/* Connection info */}
        <Text style={styles.sectionLabel}>Connection</Text>
        <View style={styles.section}>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>State</Text>
            <Text style={styles.statusValue}>{connectionLabel}</Text>
          </View>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>Enabled by server</Text>
            <Text style={styles.statusValue}>{status ? String(status.enabled) : '—'}</Text>
          </View>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>Active sessions</Text>
            <Text style={styles.statusValue}>
              {status ? String(status.active_sessions) : '—'}
            </Text>
          </View>
          {status && status.capabilities.length > 0 ? (
            <View style={styles.capRow}>
              {status.capabilities.map((cap) => (
                <View key={cap} style={styles.capChip}>
                  <Text style={styles.capText}>{cap}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>

        {/* Model + voice */}
        <Text style={styles.sectionLabel}>Assistant</Text>
        <View style={styles.section}>
          <SettingRow
            title="Model"
            caption={state.model || 'Not set'}
            onPress={() => navigation.navigate('ModelSheet')}
            right={<Glyph name="chevronRight" size={16} color={colors.textTertiary} />}
          />
          <SettingRow
            title="Voice"
            caption={voiceLabel}
            right={<Text style={styles.voiceFixed}>Fixed by server</Text>}
          />
        </View>

        {/* Camera / audio */}
        <Text style={styles.sectionLabel}>Camera & audio</Text>
        <View style={styles.section}>
          <SettingRow
            title="Preferred lens"
            caption={
              state.preferences.cameraFacing === 'front'
                ? 'Front camera'
                : 'Back camera'
            }
            onPress={() =>
              updatePreferences({
                cameraFacing:
                  state.preferences.cameraFacing === 'front' ? 'back' : 'front',
              })
            }
            right={
              <Glyph name="chevronRight" size={16} color={colors.textTertiary} />
            }
          />
          <SettingRow
            title="Haptics on controls"
            caption="Subtle feedback when tapping controls"
            right={
              <Switch
                value={state.preferences.haptics}
                onValueChange={(v) => updatePreferences({ haptics: v })}
                trackColor={{ true: colors.accent }}
                thumbColor={colors.surfaceRaised}
              />
            }
          />
          <SettingRow
            title="Auto-scroll transcript"
            caption="Follow new lines automatically"
            right={
              <Switch
                value={state.preferences.transcriptAutoScroll}
                onValueChange={(v) => updatePreferences({ transcriptAutoScroll: v })}
                trackColor={{ true: colors.accent }}
                thumbColor={colors.surfaceRaised}
              />
            }
          />
          <SettingRow
            title="Preview simulation"
            caption="Isolated dev mock — never transmits anything"
            right={
              <Switch
                value={state.preferences.previewSimulation}
                onValueChange={(v) => updatePreferences({ previewSimulation: v })}
                trackColor={{ true: colors.accent }}
                thumbColor={colors.surfaceRaised}
              />
            }
          />
        </View>

        {/* About */}
        <Text style={styles.sectionLabel}>About</Text>
        <View style={styles.section}>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>VYREN Mobile</Text>
            <Text style={styles.statusValue}>Phase D</Text>
          </View>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>Protocol</Text>
            <Text style={styles.statusValue}>MRP · /ws/live/mobile</Text>
          </View>
          <View style={styles.statusLine}>
            <Text style={styles.rowTitle}>Transport</Text>
            <Text style={styles.statusValue}>WSS · audio+vision</Text>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  scroll: {
    padding: spacing['2xl'],
    gap: spacing['2xl'],
  },
  sectionLabel: {
    ...typography.caption,
    color: colors.textTertiary,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    marginBottom: spacing.sm,
  },
  section: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  fieldLabel: {
    ...typography.label,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surfaceSunken,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    color: colors.textPrimary,
    ...typography.body,
  },
  fieldHint: {
    ...typography.caption,
    color: colors.textTertiary,
    marginTop: spacing.xs,
  },
  save: {
    marginTop: spacing.lg,
  },
  rowWrap: {
    paddingVertical: spacing.xs,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  rowText: {
    flex: 1,
    marginRight: spacing.md,
  },
  rowTitle: {
    ...typography.bodyStrong,
    color: colors.textPrimary,
  },
  rowCaption: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xxs,
  },
  pressed: {
    opacity: 0.75,
  },
  statusLine: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  statusValue: {
    ...typography.label,
    color: colors.textSecondary,
  },
  capRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  capChip: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accentBorder,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  capText: {
    ...typography.caption,
    color: colors.accent,
  },
  voiceFixed: {
    ...typography.caption,
    color: colors.textTertiary,
  },
});