/**
 * VisionScreen — continuous vision.
 *
 * While vision runs, the camera feed fills the surface behind quiet overlays:
 * connection + AI state, a vision indicator, compact transcript and the
 * minimal controls (pause/resume, flip). Phase D: frames are captured at ~1 FPS
 * by `services/camera.ts` and routed through `onFrame` →
 * `session.pushVisionFrame` into the live transport.
 */

import { useNavigation, type CompositeNavigationProp } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import type { StackNavigationProp } from '@react-navigation/stack';
import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ConnectionBadge } from '../components/ConnectionBadge';
import { ControlButton } from '../components/ControlButton';
import { Glass } from '../components/Glass';
import { Glyph, type GlyphName } from '../components/Glyph';
import { StatePill } from '../components/StatePill';
import { Transcript } from '../components/Transcript';
import { useCameraService } from '../services/camera';
import { useLiveSession } from '../state/LiveSessionProvider';
import { colors } from '../theme/colors';
import { radius } from '../theme/radius';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { RootStackParamList, MainTabParamList } from '../navigation/types';
import { useApp } from '../state/AppContext';

type VisionNav = CompositeNavigationProp<
  BottomTabNavigationProp<MainTabParamList, 'Vision'>,
  StackNavigationProp<RootStackParamList>
>;

export function VisionScreen() {
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<VisionNav>();
  const { state } = useApp();
  const live = useLiveSession();
  const camera = useCameraService(state.preferences.cameraFacing);

  const [running, setRunning] = useState(false);

  // Keep the feed + session flag in sync with the running state.
  useEffect(() => {
    camera.setActive(running);
    live.setVisionEnabled(running);
  }, [running, camera, live]);

  const resume = useCallback(async () => {
    if (!camera.hasPermission) {
      const granted = await camera.requestPermission();
      if (!granted) {
        return;
      }
    }
    setRunning(true);
  }, [camera]);

  const pause = useCallback(() => {
    setRunning(false);
  }, []);

  const canShowFeed = running && camera.hasPermission && camera.available;

  return (
    <View style={styles.screen}>
      {canShowFeed ? (
        <View style={StyleSheet.absoluteFill}>
          <camera.CameraSurface
            facing={camera.facing}
            active={running}
            style={styles.surface}
            onFrame={(frame) => live.pushVisionFrame(frame)}
          />
        </View>
      ) : (
        <View style={[StyleSheet.absoluteFill, styles.surfaceOff]}>
          <View style={styles.surfaceOffCore}>
            <Glyph name="vision" size={36} color={colors.textTertiary} />
            <Text style={styles.surfaceOffTitle}>
              {camera.hasPermission ? 'Vision paused' : 'Vision needs the camera'}
            </Text>
            <Text style={styles.surfaceOffBody}>
              {camera.hasPermission
                ? 'Resume to let VYREN see the room. Frames stream to the live session while connected.'
                : 'Allow camera access so VYREN can see what you see.'}
            </Text>
          </View>
        </View>
      )}

      {/* Status overlays */}
      <View
        style={[
          styles.topBar,
          { marginTop: Math.max(insets.top, spacing.md) },
        ]}>
        <ConnectionBadge status={live.status} preview={live.previewMode} />
        <View style={styles.topRight}>
          <StatePill state={live.aiState} compact />
          <VisionIndicator on={running} paused={!running} />
        </View>
      </View>

      {/* Pause veil */}
      {canShowFeed && !running ? (
        <View style={styles.veil} />
      ) : null}

      {/* Bottom: transcript + controls */}
      <View
        style={[
          styles.dock,
          { paddingBottom: Math.max(insets.bottom, spacing.md) },
        ]}>
        <Glass level="weak" radius="lg" style={styles.transcriptCard}>
          <Transcript messages={live.messages} compact autoScroll style={styles.transcript} />
        </Glass>

        <View style={styles.controlRow}>
          <ControlButton
            glyph={running ? ('pause' as GlyphName) : ('play' as GlyphName)}
            onPress={running ? pause : resume}
            label={running ? 'Pause' : 'Resume'}
            active={running}
          />
          <ControlButton
            glyph="flip"
            onPress={camera.flip}
            label="Flip"
            dimmed={!running}
          />
          <ControlButton
            glyph="camera"
            onPress={() => navigation.navigate('Camera')}
            label="Capture"
            dimmed
          />
        </View>
      </View>
    </View>
  );
}

function VisionIndicator({ on, paused }: { on: boolean; paused: boolean }) {
  return (
    <View
      style={[
        styles.visionTag,
        on && styles.visionTagOn,
        paused && styles.visionTagPaused,
      ]}>
      <View
        style={[
          styles.visionDot,
          on && styles.visionDotOn,
          paused && styles.visionDotPaused,
        ]}
      />
      <Text style={styles.visionText}>{on ? 'Sight on' : 'Sight off'}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.canvas,
  },
  surface: {
    flex: 1,
  },
  surfaceOff: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.canvas,
    padding: spacing['3xl'],
  },
  surfaceOffCore: {
    alignItems: 'center',
    maxWidth: 340,
  },
  surfaceOffTitle: {
    ...typography.heading,
    color: colors.textPrimary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  surfaceOffBody: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 22,
  },
  topBar: {
    position: 'absolute',
    top: 0,
    left: spacing.lg,
    right: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  topRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  veil: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  dock: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  transcriptCard: {
    maxHeight: 150,
  },
  transcript: {
    flexGrow: 0,
    maxHeight: 130,
  },
  controlRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
  },
  visionTag: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(18,18,24,0.55)',
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  visionTagOn: {
    borderColor: colors.accentBorder,
    backgroundColor: colors.accentSoft,
  },
  visionTagPaused: {
    opacity: 0.6,
  },
  visionDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.textDisabled,
    marginRight: spacing.xs,
  },
  visionDotOn: {
    backgroundColor: colors.accent,
  },
  visionDotPaused: {
    backgroundColor: colors.textTertiary,
  },
  visionText: {
    ...typography.caption,
    color: colors.textPrimary,
    fontWeight: '600',
  },
});