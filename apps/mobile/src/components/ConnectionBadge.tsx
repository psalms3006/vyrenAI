/**
 * ConnectionBadge — compact, colour-and-text status for the live session.
 * Communicates state without relying on colour alone (label + dot).
 */

import React, { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { LiveSessionStatus } from '../services/live';

const STATUS_LABEL: Record<LiveSessionStatus, string> = {
  idle: 'Ready',
  connecting: 'Connecting',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  offline: 'Offline',
  error: 'Error',
};

function statusColor(status: LiveSessionStatus): string {
  switch (status) {
    case 'connected':
      return colors.success;
    case 'connecting':
      return colors.info;
    case 'reconnecting':
      return colors.warning;
    case 'error':
      return colors.danger;
    case 'offline':
      return colors.textDisabled;
    case 'idle':
      return colors.textTertiary;
  }
}

function isActiveTransition(status: LiveSessionStatus): boolean {
  return status === 'connecting' || status === 'reconnecting';
}

export interface ConnectionBadgeProps {
  status: LiveSessionStatus;
  /** Preview-simulation chip when the session is the isolated mock. */
  preview?: boolean;
  /** Override the status label (e.g. richer text on the flagship screen). */
  label?: string;
}

export function ConnectionBadge({
  status,
  preview = false,
  label,
}: ConnectionBadgeProps) {
  const pulse = useSharedValue(0);
  const activePulse = isActiveTransition(status);

  useEffect(() => {
    pulse.value = activePulse
      ? withRepeat(withTiming(1, { duration: 1100 }), -1, true)
      : withTiming(0, { duration: 200 });
  }, [activePulse, pulse]);

  const dotStyle = useAnimatedStyle(() => {
    const scale = activePulse ? 1 + pulse.value * 0.35 : 1;
    return { transform: [{ scale }] };
  });

  return (
    <View style={styles.row}>
      <Animated.View
        style={[
          styles.dot,
          { backgroundColor: statusColor(status) },
          activePulse && styles.dotRing,
          dotStyle,
        ]}
      />
      <Text style={styles.label}>{label ?? STATUS_LABEL[status]}</Text>
      {preview ? (
        <View style={styles.preview}>
          <Text style={styles.previewText}>Preview</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: spacing.sm,
  },
  dotRing: {
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.18)',
  },
  label: {
    ...typography.label,
    color: colors.textPrimary,
  },
  preview: {
    marginLeft: spacing.sm,
    backgroundColor: colors.accentSoft,
    borderColor: colors.accentBorder,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: spacing.xs,
    paddingHorizontal: spacing.xs + 2,
    paddingVertical: 2,
  },
  previewText: {
    ...typography.caption,
    color: colors.accent,
    fontSize: 9,
    letterSpacing: 0.8,
    fontWeight: '700',
  },
});