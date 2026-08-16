/**
 * DEVELOPMENT PREVIEW — isolated mock camera controller.
 *
 * Implements the `CameraServiceHook` contract with plain local state and no
 * native module so every UI state (permission, unavailable, flip, capture,
 * preview surface) can be walked through in Node. `services/camera.ts`
 * switches between this preview and the real VisionCamera wiring depending on
 * native availability; consumers never change.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import type { CameraFacing } from '../../types';
import { colors } from '../../theme/colors';
import { radius } from '../../theme/radius';
import type {
  CameraServiceHook,
  CameraSurfaceProps,
  CapturedPhoto,
} from '../camera';

/** 1×1 transparent PNG — lets the captured-image preview + analysis flow
 *  render in preview mode without any real capture. */
const PLACEHOLDER_PHOTO_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

async function capturePreviewStill(): Promise<CapturedPhoto | null> {
  return {
    base64: PLACEHOLDER_PHOTO_BASE64,
    mime: 'image/jpeg',
    width: 1,
    height: 1,
  };
}

/** Preview surface — a quiet, near-black canvas with soft depth. Phase D
 *  renders the real `Camera` here behind the same interface. */
export function PreviewCameraSurface({
  active,
  style,
  testID,
}: CameraSurfaceProps) {
  return (
    <View style={[styles.surface, style]} testID={testID}>
      {/* Vertical falloff — an abstract stand-in for the lens field. */}
      <View style={[styles.falloff, styles.falloffTop]} />
      <View style={[styles.falloff, styles.falloffBottom]} />
      {/* Hairline frame keeps the framing edge readable in dark scenes. */}
      <View style={styles.frame} pointerEvents="none" />
      {active ? <View style={styles.centerReticle} pointerEvents="none" /> : null}
    </View>
  );
}

export function usePreviewCameraService(
  initialFacing?: CameraFacing,
): CameraServiceHook {
  const [granted, setGranted] = useState(false);
  const [canRequest, _setCanRequest] = useState(true);
  const [facing, setFacing] = useState<CameraFacing>(initialFacing ?? 'back');
  const [active, setActive] = useState(false);

  const requestPermission = useCallback(async () => {
    if (granted) {
      return true;
    }
    if (canRequest) {
      setGranted(true);
      setActive(true);
      return true;
    }
    return false;
  }, [granted, canRequest]);

  const flip = useCallback(() => {
    setFacing((current) => (current === 'back' ? 'front' : 'back'));
  }, []);

  const captureStill = useCallback(async (): Promise<CapturedPhoto | null> => {
    if (!granted || !active) {
      return null;
    }
    return capturePreviewStill();
  }, [granted, active]);

  return useMemo<CameraServiceHook>(
    () => ({
      hasPermission: granted,
      canRequestPermission: canRequest,
      requestPermission,
      facing,
      flip,
      active,
      setActive,
      available: true,
      captureStill,
      CameraSurface: PreviewCameraSurface,
    }),
    [granted, canRequest, requestPermission, facing, flip, active, captureStill],
  );
}

const styles = StyleSheet.create({
  surface: {
    flex: 1,
    backgroundColor: colors.canvas,
    overflow: 'hidden',
  },
  falloff: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: '45%',
  },
  falloffTop: {
    top: 0,
    backgroundColor: 'rgba(255,255,255,0.028)',
  },
  falloffBottom: {
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.38)',
  },
  frame: {
    ...StyleSheet.absoluteFill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255,255,255,0.07)',
    borderRadius: radius.xl,
  },
  centerReticle: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    width: 88,
    height: 88,
    marginTop: -44,
    marginLeft: -44,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(167,139,250,0.28)',
    borderRadius: radius.pill,
  },
});