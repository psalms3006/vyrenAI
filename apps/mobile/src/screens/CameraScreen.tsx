/**
 * CameraScreen — single-shot capture + analysis.
 *
 * Permission, unavailable, preview, capture, captured-image preview and an
 * analysis result area are all implemented. Analysis posts to
 * `POST /api/vision/analyze` via the API layer; until the backend ships that
 * endpoint the screen renders an explicit "analysis unavailable" state rather
 * than inventing a response.
 *
 * The capture surface itself comes from `services/camera.ts` (Phase D:
 * VisionCamera); the screen never touches the SDK.
 */

import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ControlButton } from '../components/ControlButton';
import { Glass } from '../components/Glass';
import { GlassButton } from '../components/GlassButton';
import { Glyph } from '../components/Glyph';
import { analyzeVisionImage, ApiError } from '../services/api';
import { useCameraService } from '../services/camera';
import type { CapturedPhoto } from '../services/camera';
import { useApp } from '../state/AppContext';
import { colors } from '../theme/colors';
import { spacing } from '../theme/spacing';
import { typography } from '../theme/typography';
import type { VisionAnalysis } from '../types';

export function CameraScreen() {
  const insets = useSafeAreaInsets();
  const { state } = useApp();
  const camera = useCameraService(state.preferences.cameraFacing);

  const [capture, setCapture] = useState<CapturedPhoto | null>(null);
  const [analysis, setAnalysis] = useState<VisionAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  // Keep the preview active while the screen is focused.
  useEffect(() => {
    if (camera.hasPermission) {
      camera.setActive(true);
    }
  }, [camera, camera.hasPermission]);

  const requestPermission = async () => {
    await camera.requestPermission();
  };

  const captureStill = async () => {
    const photo = await camera.captureStill();
    if (photo) {
      setCapture(photo);
      setAnalysis(null);
      setAnalysisError(null);
    }
  };

  const retake = () => {
    setCapture(null);
    setAnalysis(null);
    setAnalysisError(null);
  };

  const runAnalysis = async () => {
    if (!capture || analyzing) {
      return;
    }
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const result = await analyzeVisionImage({
        base64: capture.base64,
        mime: capture.mime,
      });
      setAnalysis(result);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Analysis could not be completed.';
      setAnalysisError(message);
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <View style={styles.screen}>
      {/* Capture surface */}
      {camera.hasPermission && camera.available ? (
        <View style={StyleSheet.absoluteFill}>
          <camera.CameraSurface
            facing={camera.facing}
            active={camera.active}
            style={styles.surface}
          />
          {capture ? (
            <View style={styles.captureOverlay}>
              <Image
                source={{ uri: `data:image/jpeg;base64,${capture.base64}` }}
                style={styles.capturedImage}
                resizeMode="contain"
              />
            </View>
          ) : null}

          {/* Overlay controls */}
          <View
            style={[
              styles.topRow,
              { marginTop: Math.max(insets.top, spacing.md) },
            ]}>
            <ControlButton glyph="flip" onPress={camera.flip} label="Flip" size={44} />
          </View>
        </View>
      ) : (
        <View style={styles.permissionShell}>
          {camera.available ? (
            <PermissionGate
              canRequest={camera.canRequestPermission}
              onRequest={requestPermission}
            />
          ) : (
            <View style={styles.unavailable}>
              <Glyph name="camera" size={36} color={colors.textTertiary} />
              <Text style={styles.unavailableTitle}>No camera available</Text>
              <Text style={styles.unavailableBody}>
                This device reports no capture session. Vision will activate
                once a camera is reachable.
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Bottom: capture control + analysis area */}
      <View
        style={[
          styles.dock,
          { paddingBottom: Math.max(insets.bottom, spacing.md) },
        ]}>
        {capture ? (
          <Glass level="medium" radius="lg" style={styles.analysisCard}>
            {analyzing ? (
              <View style={styles.analysisRow}>
                <ActivityIndicator color={colors.accent} size="small" />
                <Text style={styles.analysisText}>Analysing the frame…</Text>
              </View>
            ) : analysis ? (
              <View style={styles.analysisRow}>
                <View style={styles.analysisTextWrap}>
                  <Text style={styles.analysisTitle}>What I see</Text>
                  <Text style={styles.analysisText}>{analysis.summary}</Text>
                  {analysis.labels.length > 0 ? (
                    <View style={styles.labelRow}>
                      {analysis.labels.slice(0, 4).map((label) => (
                        <View key={label} style={styles.labelChip}>
                          <Text style={styles.labelChipText}>{label}</Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                </View>
              </View>
            ) : analysisError ? (
              <View style={styles.analysisRow}>
                <Text style={styles.analysisTitle}>Analysis unavailable</Text>
                <Text style={styles.analysisError}>{analysisError}</Text>
                <Text style={styles.analysisCaption}>
                  The VYREN server has not shipped POST /api/vision/analyze yet.
                  The UI is ready to receive its response.
                </Text>
              </View>
            ) : (
              <View style={styles.analysisRow}>
                <Text style={styles.analysisTitle}>Captured frame</Text>
                <Text style={styles.analysisText}>Tap “Analyse” to ask VYREN about it.</Text>
              </View>
            )}
          </Glass>
        ) : null}

        {capture ? (
          <View style={styles.captureActions}>
            <GlassButton label="Retake" variant="ghost" onPress={retake} />
            <GlassButton
              label="Analyse"
              variant="primary"
              loading={analyzing}
              disabled={!!analysisError}
              onPress={runAnalysis}
            />
          </View>
        ) : (
          <View style={styles.captureButtonRow}>
            <ControlButton
              glyph="camera"
              onPress={captureStill}
              label="Capture"
              active={camera.hasPermission && camera.available}
              size={64}
            />
          </View>
        )}
      </View>
    </View>
  );
}

function PermissionGate({
  canRequest,
  onRequest,
}: {
  canRequest: boolean;
  onRequest: () => void;
}) {
  return (
    <View style={styles.permission}>
      <View style={styles.permissionGlyph}>
        <Glyph name="camera" size={34} color={colors.textPrimary} />
      </View>
      <Text style={styles.permissionTitle}>Camera access</Text>
      <Text style={styles.permissionBody}>
        VYREN captures and analyses a frame only when you tap Capture —
        nothing is streamed from here.
      </Text>
      {canRequest ? (
        <GlassButton label="Enable camera" onPress={onRequest} style={styles.permissionButton} />
      ) : (
        <Text style={styles.permissionHint}>
          Permission was denied. Enable it for VyrenMobile in Settings.
        </Text>
      )}
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
  topRow: {
    position: 'absolute',
    top: 0,
    left: spacing.lg,
    right: spacing.lg,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  captureOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: 'rgba(0,0,0,0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing['3xl'],
  },
  capturedImage: {
    width: '100%',
    height: '100%',
  },
  permissionShell: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing['3xl'],
  },
  permission: {
    alignItems: 'center',
    maxWidth: 360,
  },
  permissionGlyph: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing['2xl'],
  },
  permissionTitle: {
    ...typography.title,
    color: colors.textPrimary,
    marginBottom: spacing.sm,
  },
  permissionBody: {
    ...typography.body,
    color: colors.textSecondary,
    lineHeight: 22,
    textAlign: 'center',
  },
  permissionHint: {
    ...typography.caption,
    color: colors.textTertiary,
    marginTop: spacing.lg,
    textAlign: 'center',
  },
  permissionButton: {
    marginTop: spacing['2xl'],
  },
  unavailable: {
    alignItems: 'center',
    maxWidth: 320,
  },
  unavailableTitle: {
    ...typography.heading,
    color: colors.textPrimary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  unavailableBody: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 22,
  },
  dock: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    gap: spacing.md,
  },
  analysisCard: {
    padding: spacing.lg,
  },
  analysisRow: {
    gap: spacing.xs,
  },
  analysisTitle: {
    ...typography.label,
    color: colors.accent,
    marginBottom: spacing.xxs,
  },
  analysisTextWrap: {
    gap: spacing.xs,
  },
  analysisText: {
    ...typography.body,
    color: colors.textPrimary,
  },
  analysisError: {
    ...typography.body,
    color: colors.danger,
  },
  analysisCaption: {
    ...typography.caption,
    color: colors.textTertiary,
    marginTop: spacing.xs,
  },
  labelRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  labelChip: {
    backgroundColor: colors.accentSoft,
    borderRadius: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  labelChipText: {
    ...typography.caption,
    color: colors.accent,
  },
  captureActions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  captureButtonRow: {
    alignItems: 'center',
  },
});