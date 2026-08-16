/**
 * Transcript — the live/chat message surface.
 */

import React, { useRef } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { MessageRole, TranscriptMessage } from '../types';

export interface TranscriptProps {
  messages: TranscriptMessage[];
  /** Latest line is a live (partial) fragment. */
  isStreaming?: boolean;
  /** Auto-follow new messages. Default true. */
  autoScroll?: boolean;
  /** Dense/quiet row layout for overlays like the Live screen. */
  compact?: boolean;
  style?: StyleProp<ViewStyle>;
}

const ROLE_LABEL: Record<MessageRole, string> = {
  user: 'You',
  assistant: 'Vyren',
  tool: 'Tool',
};

function roleColor(role: MessageRole): string {
  switch (role) {
    case 'user':
      return colors.textPrimary;
    case 'assistant':
      return colors.accent;
    case 'tool':
      return colors.warning;
  }
}

function TranscriptRow({
  message,
  compact,
}: {
  message: TranscriptMessage;
  compact: boolean;
}) {
  const label =
    message.role === 'tool'
      ? `Tool · ${message.toolName ?? 'action'}`
      : ROLE_LABEL[message.role];

  return (
    <View style={[styles.row, compact && styles.rowCompact]}>
      <Text
        style={[styles.role, compact && styles.roleCompact, { color: roleColor(message.role) }]}>
        {label}
      </Text>
      <Text
        style={[
          styles.text,
          compact && styles.textCompact,
          message.role === 'user' && styles.userText,
          !message.final && styles.partial,
        ]}>
        {message.text}
      </Text>
    </View>
  );
}

export function Transcript({
  messages,
  isStreaming = false,
  autoScroll = true,
  compact = false,
  style,
}: TranscriptProps) {
  const listRef = useRef<FlatList<TranscriptMessage>>(null);

  const content = isStreaming ? messages : messages;

  if (content.length === 0) {
    return (
      <View style={[styles.empty, style]}>
        <Text style={styles.emptyText}>
          {compact
            ? 'Nothing yet — speak, or say “hello”.'
            : 'Transcript is empty — start speaking to begin.'}
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      ref={listRef}
      style={style}
      data={content}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => <TranscriptRow message={item} compact={compact} />}
      contentContainerStyle={[
        styles.content,
        compact && styles.contentCompact,
      ]}
      showsVerticalScrollIndicator={false}
      onContentSizeChange={
        autoScroll
          ? () => listRef.current?.scrollToEnd({ animated: true })
          : undefined
      }
    />
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  contentCompact: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  row: {
    marginBottom: spacing.md,
  },
  rowCompact: {
    marginBottom: spacing.sm,
  },
  role: {
    ...typography.caption,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.xxs,
  },
  roleCompact: {
    marginBottom: 2,
    fontSize: 9,
  },
  text: {
    ...typography.body,
    color: colors.textPrimary,
  },
  textCompact: {
    fontSize: 13,
    lineHeight: 18,
  },
  userText: {
    color: colors.textSecondary,
  },
  partial: {
    opacity: 0.6,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing['3xl'],
  },
  emptyText: {
    ...typography.body,
    color: colors.textTertiary,
    textAlign: 'center',
  },
});