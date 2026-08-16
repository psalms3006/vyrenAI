/**
 * HomeScreen — the Chats / home experience.
 *
 * An intelligent presence living in a minimal surface: time-aware greeting,
 * the AI orb + live state, a few real capability entry-points rather than
 * decorative cards, the session transcript and a chat input. Suggestions are
 * structured so a future backend can provide them; today they map to real app
 * destinations (voice live, camera, vision, chat).
 */

import type { CompositeNavigationProp } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import type { StackNavigationProp } from '@react-navigation/stack';
import { useNavigation } from '@react-navigation/native';
import React, { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AIOrb } from '../components/AIOrb';
import { ConnectionBadge } from '../components/ConnectionBadge';
import { Glass } from '../components/Glass';
import { Glyph } from '../components/Glyph';
import { ModelChip } from '../components/ModelChip';
import { SuggestionCard } from '../components/SuggestionCard';
import { StatePill } from '../components/StatePill';
import { Transcript } from '../components/Transcript';
import { useLiveSession } from '../state/LiveSessionProvider';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { MainTabParamList, RootStackParamList } from '../navigation/types';

type HomeNav = CompositeNavigationProp<
  BottomTabNavigationProp<MainTabParamList, 'Home'>,
  StackNavigationProp<RootStackParamList>
>;

interface HomeSuggestion {
  id: string;
  title: string;
  body?: string;
  glyph: 'live' | 'camera' | 'vision' | 'chat';
  onPress: (nav: HomeNav, focusInput: () => void) => void;
}

const HOME_SUGGESTIONS: HomeSuggestion[] = [
  {
    id: 'live-call',
    title: 'Start a live call',
    body: 'Voice conversation with VYREN',
    glyph: 'live',
    onPress: (nav) => nav.navigate('Live'),
  },
  {
    id: 'open-camera',
    title: 'Open camera',
    body: 'Capture and ask about a scene',
    glyph: 'camera',
    onPress: (nav) => nav.navigate('Camera'),
  },
  {
    id: 'vision',
    title: 'Vision',
    body: 'Continuous sight while you talk',
    glyph: 'vision',
    onPress: (nav) => nav.navigate('Vision'),
  },
  {
    id: 'ask',
    title: 'Ask anything',
    body: 'Type to the session',
    glyph: 'chat',
    onPress: (_nav, focus) => focus(),
  },
];

function greetingForHour(hour: number): string {
  if (hour < 5) {
    return 'Still up';
  }
  if (hour < 12) {
    return 'Good morning';
  }
  if (hour < 18) {
    return 'Good afternoon';
  }
  return 'Good evening';
}

export function HomeScreen() {
  const navigation = useNavigation<HomeNav>();
  const insets = useSafeAreaInsets();
  const live = useLiveSession();

  const inputRef = useRef<TextInput>(null);
  const [draft, setDraft] = useState('');

  const focusInput = () => inputRef.current?.focus();

  const hour = new Date().getHours();
  const greeting = greetingForHour(hour);

  const send = () => {
    const text = draft.trim();
    if (!text) {
      return;
    }
    live.sendMessage(text);
    setDraft('');
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View
        style={[
          styles.screen,
          { paddingTop: Math.max(insets.top, spacing.md) },
        ]}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text style={styles.eyebrow}>VYREN</Text>
            <Text style={styles.greeting}>{greeting}</Text>
          </View>
          <Pressable
            onPress={() => navigation.navigate('Settings')}
            accessibilityRole="button"
            accessibilityLabel="Settings"
            hitSlop={8}
            style={({ pressed }) => [styles.settingsButton, pressed && styles.pressed]}>
            <Glyph name="layers" size={20} color={colors.textSecondary} />
          </Pressable>
        </View>

        <ScrollView
          style={styles.flex}
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled">
          {/* Presence */}
          <View style={styles.orbZone}>
            <AIOrb state={live.aiState} size={88} active={live.status === 'connected'} />
            <View style={styles.stateRow}>
              <StatePill state={live.aiState} />
            </View>
            <ConnectionBadge status={live.status} preview={live.previewMode} />
          </View>

          {/* Suggestions */}
          <View style={styles.suggestions}>
            <Text style={styles.sectionLabel}>Try</Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.suggestionRow}>
              {HOME_SUGGESTIONS.map((s) => (
                <SuggestionCard
                  key={s.id}
                  title={s.title}
                  body={s.body}
                  icon={<Glyph name={s.glyph} size={18} color={colors.accent} />}
                  onPress={() => s.onPress(navigation, focusInput)}
                />
              ))}
            </ScrollView>
          </View>

          {/* Conversation */}
          <View style={styles.transcriptBlock}>
            <View style={styles.transcriptHeader}>
              <Text style={styles.sectionLabel}>Conversation</Text>
              <ModelChip />
            </View>
            <Transcript
              messages={live.messages}
              autoScroll={live.previewMode ? true : true}
              style={styles.transcript}
            />
          </View>
        </ScrollView>

        {/* Chat input */}
        <View style={[styles.inputDock, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <Glass level="strong" radius="pill" style={styles.inputBar}>
            <TextInput
              ref={inputRef}
              value={draft}
              onChangeText={setDraft}
              onSubmitEditing={send}
              placeholder="Ask Vyren…"
              placeholderTextColor={colors.textTertiary}
              style={styles.input}
              multiline
              accessibilityLabel="Chat message"
            />
            <Pressable
              onPress={send}
              disabled={!draft.trim()}
              accessibilityRole="button"
              accessibilityLabel="Send"
              style={({ pressed }) => [
                styles.sendButton,
                pressed && styles.pressed,
                !draft.trim() && styles.sendDisabled,
              ]}>
              <View style={styles.sendDisc}>
                <Glyph name="chevronRight" size={16} color={colors.accentForeground} />
              </View>
            </Pressable>
          </Glass>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    paddingHorizontal: spacing['2xl'],
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  headerText: {
    flexShrink: 1,
  },
  eyebrow: {
    ...typography.caption,
    color: colors.accent,
    letterSpacing: 3,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  greeting: {
    ...typography.title,
    color: colors.textPrimary,
  },
  settingsButton: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: -6,
  },
  pressed: {
    opacity: 0.7,
  },
  scroll: {
    paddingHorizontal: spacing['2xl'],
    paddingBottom: spacing['3xl'],
  },
  orbZone: {
    alignItems: 'center',
    paddingTop: spacing.lg,
    paddingBottom: spacing['2xl'],
  },
  stateRow: {
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  sectionLabel: {
    ...typography.caption,
    color: colors.textTertiary,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    marginBottom: spacing.md,
  },
  suggestions: {
    marginBottom: spacing['2xl'],
  },
  suggestionRow: {
    paddingRight: spacing.lg,
    gap: spacing.md,
  },
  transcriptBlock: {
    flex: 1,
  },
  transcriptHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  transcript: {
    flex: 1,
    borderRadius: 0,
  },
  inputDock: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    paddingLeft: spacing.lg,
    paddingRight: spacing.xs,
    minHeight: 52,
  },
  input: {
    flex: 1,
    ...typography.body,
    color: colors.textPrimary,
    maxHeight: 110,
    paddingVertical: spacing.sm,
  },
  sendButton: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendDisabled: {
    opacity: 0.4,
  },
  sendDisc: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
});