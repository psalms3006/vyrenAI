/**
 * LiveScreen — the flagship immersive AI conversation surface.
 *
 * A camera/ambient backdrop, the AI orb presence, live waveform, a compact
 * transcript, and floating controls that communicate every state with more
 * than colour (label, glyph, layout). No Zoom-grid: this is a conversation
 * with an intelligence, not a call.
 *
 * Transport stays out of this file: background = `services/camera.ts`
 * (Phase D: VisionCamera), mic = `services/audio.ts`, everything session-side
 * comes through `useLiveSession()`.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AIOrb } from '../components/AIOrb';
import { ConnectionBadge } from '../components/ConnectionBadge';
import { ControlButton } from '../components/ControlButton';
import { Glass } from '../components/Glass';
import { ModelChip } from '../components/ModelChip';
import { StatePill } from '../components/StatePill';
import { Transcript } from '../components/Transcript';
import { Waveform } from '../components/Waveform';
import { createMicrophone } from '../services/audio';
import { useCameraService } from '../services/camera';
import { useLiveSession } from '../state/LiveSessionProvider';
import { aiStateVisualOf } from '../theme/aiStates';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { AIState } from '../types';

const STATE_HINT: Record<AIState, string> = {
  idle: 'Ready — unmute to speak',
  connecting: 'Connecting…',
  listening: 'Listening',
  thinking: 'Thinking…',
  speaking: 'Speaking',
  executing_tool: 'Working…',
  reconnecting: 'Reconnecting…',
  failed: 'Session failed',
};

export function LiveScreen() {
  const insets = useSafeAreaInsets();
  const live = useLiveSession();
  const camera = useCameraService();

  const [cameraOn, setCameraOn] = useState(false);

  // Route mic frames through a ref so the mic effect never re-runs when the
  // live context re-renders (keeps the microphone from churning).
  const pushAudioRef = useRef(live.pushAudio);
  pushAudioRef.current = live.pushAudio;

  useEffect(() => {
    camera.setActive(cameraOn);
    live.setCameraEnabled(cameraOn);
  }, [cameraOn, camera, live]);

  // Microphone lifecycle — follows the muted flag. Feed PCM frames into the
  // live transport only while a real session is actively connected.
  useEffect(() => {
    if (!live.muted && live.status === 'connected') {
      const mic = createMicrophone({
        onAudio: (pcm) => pushAudioRef.current?.(pcm),
      });
      mic.start();
      return () => mic.stop();
    }
  }, [live.muted, live.status]);

  const toggleCamera = async () => {
    if (cameraOn) {
      setCameraOn(false);
      return;
    }
    if (!camera.hasPermission) {
      const granted = await camera.requestPermission();
      if (!granted) {
        return;
      }
    }
    setCameraOn(true);
  };

  const toggleMic = () => {
    if (live.status === 'idle' || live.status === 'error' || live.status === 'offline') {
      live.start();
    }
    live.toggleMuted();
  };

  const toggleVision = () => {
    live.setVisionEnabled(!live.visionEnabled);
  };

  const showCamera = cameraOn && camera.hasPermission && camera.available;

  const visual = aiStateVisualOf(live.aiState);
  const connected = live.status === 'connected';

  const glowStyle = useMemo(
    () => ({
      backgroundColor: visual.glow,
      opacity: connected && !live.muted ? 1 : 0.5,
    }),
    [visual.glow, connected, live.muted],
  );

  return (
    <View style={styles.screen}>
      {/* Backdrop — live camera feed or quiet ambient presence. */}
      {showCamera ? (
        <View style={StyleSheet.absoluteFill}>
          <camera.CameraSurface
            facing={camera.facing}
            active={cameraOn}
            style={styles.cameraSurface}
            onFrame={(frame) => live.pushVisionFrame(frame)}
          />
        </View>
      ) : (
        <View style={[StyleSheet.absoluteFill, styles.ambient]}>
          <View style={[styles.glow, glowStyle]} />
          <View style={styles.ambientGradientBottom} />
        </View>
      )}

      {/* Top status cluster */}
      <View
        style={[
          styles.topBar,
          {
            marginTop: Math.max(insets.top, spacing.md),
          },
        ]}>
        <ConnectionBadge
          status={live.status}
          preview={live.previewMode}
          label={STATE_HINT[live.aiState]}
        />
        <ModelChip />
      </View>

      {/* Presence center */}
      <View style={styles.presence}>
        <AIOrb state={live.aiState} size={132} active={connected} glow={connected} />
        <View style={styles.presenceMeta}>
          <StatePill state={live.aiState} />
          <Text style={styles.stateHint}>{STATE_HINT[live.aiState]}</Text>
        </View>
        <Waveform
          active={connected && !live.muted}
          color={connected ? visual.color : colors.textDisabled}
        />
        {live.muted ? (
          <Text style={styles.mutedHint}>Microphone muted — tap the mic to speak</Text>
        ) : null}
        {!camera.available && cameraOn ? (
          <Text style={styles.mutedHint}>Camera unavailable on this device</Text>
        ) : null}
      </View>

      {/* Compact transcript */}
      <View
        style={[
          styles.transcriptDock,
          { paddingBottom: Math.max(insets.bottom, spacing.sm) + 8 },
        ]}>
        <Glass level="weak" radius="lg" style={styles.transcriptCard}>
          <Transcript
            messages={live.messages}
            compact
            autoScroll
            style={styles.transcript}
          />
        </Glass>

        {/* Controls */}
        <Glass level="weak" radius="xl" style={styles.controlBar}>
          <ControlButton
            glyph="camera"
            onPress={toggleCamera}
            label={cameraOn ? 'Camera' : 'Camera'}
            active={cameraOn}
            dimmed={!cameraOn}
          />
          <ControlButton
            glyph="flip"
            onPress={() => camera.flip()}
            label="Flip"
            dimmed={!cameraOn}
          />
          <ControlButton
            glyph={live.muted ? 'micOff' : 'mic'}
            onPress={toggleMic}
            label={live.muted ? 'Speak' : 'Mute'}
            active={!live.muted}
            size={68}
          />
          <ControlButton
            glyph="vision"
            onPress={toggleVision}
            label="Vision"
            active={live.visionEnabled}
            dimmed={!live.visionEnabled}
          />
        </Glass>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.canvas,
  },
  cameraSurface: {
    flex: 1,
  },
  ambient: {
    backgroundColor: colors.canvas,
    alignItems: 'center',
    justifyContent: 'center',
  },
  glow: {
    position: 'absolute',
    width: 320,
    height: 320,
    borderRadius: 160,
    backgroundColor: colors.accentSoft,
  },
  ambientGradientBottom: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: '45%',
    backgroundColor: 'rgba(0,0,0,0.5)',
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
  presence: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  presenceMeta: {
    alignItems: 'center',
    marginTop: spacing['2xl'],
    marginBottom: spacing.xl,
  },
  stateHint: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  mutedHint: {
    ...typography.caption,
    color: colors.textTertiary,
    marginTop: spacing.lg,
    textAlign: 'center',
  },
  transcriptDock: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  transcriptCard: {
    maxHeight: 180,
  },
  transcript: {
    flexGrow: 0,
    maxHeight: 160,
  },
  controlBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingVertical: spacing.sm,
  },
});