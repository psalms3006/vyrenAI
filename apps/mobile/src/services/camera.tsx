/**
 * Camera service seam — real Phase D wiring.
 *
 * When the VisionCamera v5 (Nitro) module is present on a native device,
 * `useCameraService()` drives the actual camera: permission state, the live
 * preview surface, still capture (JPEG in-memory), and a ~1 FPS still-poll
 * that hands JPEG frames to the live session's `onFrame` sink for MRP vision
 * uplink. (Continuous Frame-Processor output is unavailable in this install —
 * `react-native-vision-camera-worklets` is not a dependency — so vision frames
 * use periodic photo capture, which matches the MRP 1-2 FPS guidance.)
 *
 * On any other environment it falls back to the isolated preview
 * implementation in `./mocks/cameraMock`, keeping every UI state exercisable
 * in Node/Jest. Screens never import the SDK.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import type { CameraFacing } from '../types';
import { bytesToBase64 } from './binary';
import type { VisionFrame } from './live';
import { usePreviewCameraService } from './mocks/cameraMock';

export interface CapturedPhoto {
  base64: string;
  mime: 'image/jpeg';
  width: number;
  height: number;
}

export interface CameraSurfaceProps {
  facing: CameraFacing;
  /** Drives the preview session on/off. */
  active: boolean;
  /** Phase D: frame callback routed into the live session transport. */
  onFrame?: (frame: VisionFrame) => void;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

export interface CameraServiceHook {
  /** True once the user granted camera permission. */
  hasPermission: boolean;
  /** Can we still ask the OS for permission? */
  canRequestPermission: boolean;
  requestPermission: () => Promise<boolean>;

  facing: CameraFacing;
  flip: () => void;

  active: boolean;
  setActive: (active: boolean) => void;

  /** False when no usable device exists for the current facing. */
  available: boolean;
  /** Capture a still frame; resolves null when unavailable/denied. */
  captureStill: () => Promise<CapturedPhoto | null>;

  /** React element rendering the preview surface. */
  CameraSurface: React.ComponentType<CameraSurfaceProps>;
}

type CameraModule = typeof import('react-native-vision-camera');

const VISION_INTERVAL_MS = 1000;

let cameraModule: CameraModule | null | undefined;

function resolveCameraModule(): CameraModule | null {
  if (cameraModule !== undefined) {
    return cameraModule;
  }
  try {
    // `jest` is defined only inside the test runner; skipping the require there
    // keeps the SDK out of Node/Jest bundles entirely.
    if (typeof jest === 'undefined') {
      const mod = require('react-native-vision-camera') as CameraModule;
      const ready =
        typeof mod.useCameraPermission === 'function' &&
        typeof mod.useCameraDevices === 'function' &&
        typeof mod.usePreviewOutput === 'function' &&
        typeof mod.usePhotoOutput === 'function' &&
        typeof mod.Camera === 'object' &&
        mod.VisionCamera != null &&
        mod.VisionCamera.cameraPermissionStatus != null;
      cameraModule = ready ? mod : null;
    } else {
      cameraModule = null;
    }
  } catch {
    cameraModule = null;
  }
  return cameraModule;
}

function useRealCameraService(initialFacing?: CameraFacing): CameraServiceHook {
  // This hook is only reached when the module resolved successfully.
  const mod = resolveCameraModule()!;

  const permission = mod.useCameraPermission();
  const devices = mod.useCameraDevices();
  const previewOutput = mod.usePreviewOutput();
  const photoOutput = mod.usePhotoOutput({
    targetResolution: mod.CommonResolutions.VGA_4_3,
    containerFormat: 'jpeg',
    quality: 0.7,
    qualityPrioritization: 'speed',
  });

  const [facing, setFacing] = useState<CameraFacing>(initialFacing ?? 'back');
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);

  const flip = useCallback(() => {
    setFacing((current) => (current === 'back' ? 'front' : 'back'));
  }, []);

  const hasPermission = permission.hasPermission;
  const canRequestPermission = permission.canRequestPermission;
  const requestPermission = useCallback(() => permission.requestPermission(), [
    permission,
  ]);
  const available = devices.some((device) => device.position === facing);

  const captureStill = useCallback(async (): Promise<CapturedPhoto | null> => {
    if (!hasPermission || !available || busy) {
      return null;
    }
    setBusy(true);
    try {
      const photo = await photoOutput.capturePhoto(
        { flashMode: 'off', enableShutterSound: false },
        {},
      );
      try {
        const bytes = await photo.getFileDataAsync();
        const captured: CapturedPhoto = {
          base64: bytesToBase64(bytes),
          mime: 'image/jpeg',
          width: photo.width,
          height: photo.height,
        };
        return captured;
      } finally {
        photo.dispose();
      }
    } catch {
      return null;
    } finally {
      setBusy(false);
    }
  }, [hasPermission, available, busy, photoOutput]);

  // Hold the latest onFrame in a ref so the polling interval stays stable
  // across parent re-renders (screens pass inline callbacks).
  const CameraSurface = useMemo(() => {
    return React.memo(function RealCameraSurface({
      facing: surfaceFacing,
      active: surfaceActive,
      onFrame,
      style,
      testID,
    }: CameraSurfaceProps) {
      const onFrameRef = useRef(onFrame);
      onFrameRef.current = onFrame;

      const safeActive = surfaceActive && hasPermission && available;

      useEffect(() => {
        if (!safeActive || !onFrameRef.current) {
          return;
        }
        let disposed = false;
        let inFlight = false;
        const timer = setInterval(async () => {
          if (disposed || inFlight) {
            return;
          }
          inFlight = true;
          try {
            const photo = await photoOutput.capturePhoto(
              { flashMode: 'off', enableShutterSound: false },
              {},
            );
            if (disposed) {
              photo.dispose();
              return;
            }
            try {
              const bytes = await photo.getFileDataAsync();
              onFrameRef.current?.({
                base64: bytesToBase64(bytes),
                mime: 'image/jpeg',
                width: photo.width,
                height: photo.height,
              });
            } finally {
              photo.dispose();
            }
          } catch {
            // Skip a frame; the next tick retries.
          } finally {
            inFlight = false;
          }
        }, VISION_INTERVAL_MS);
        return () => {
          disposed = true;
          clearInterval(timer);
        };
        // `photoOutput` is a stable JSI object, not a reactive dependency.
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [safeActive, photoOutput]);

      return (
        <View style={[styles.surface, style]} testID={testID}>
          <mod.Camera
            device={surfaceFacing}
            isActive={safeActive}
            outputs={[previewOutput, photoOutput]}
            constraints={[{ fps: 15 }]}
            style={StyleSheet.absoluteFill}
            enableNativeZoomGesture
            enableNativeTapToFocusGesture
          />
        </View>
      );
    });
  }, [mod, hasPermission, available, previewOutput, photoOutput]);

  return useMemo<CameraServiceHook>(
    () => ({
      hasPermission,
      canRequestPermission,
      requestPermission,
      facing,
      flip,
      active,
      setActive,
      available,
      captureStill,
      CameraSurface,
    }),
    [
      hasPermission,
      canRequestPermission,
      requestPermission,
      facing,
      flip,
      active,
      available,
      captureStill,
      CameraSurface,
    ],
  );
}

// `mod` is constant for the lifetime of the app, so binding the hook once at
// module load is safe and satisfies the hooks rules (no hooks are called
// conditionally during renders).
const cameraServiceFor = resolveCameraModule() != null
  ? useRealCameraService
  : usePreviewCameraService;

export function useCameraService(initialFacing?: CameraFacing): CameraServiceHook {
  return cameraServiceFor(initialFacing);
}

const styles = StyleSheet.create({
  surface: {
    flex: 1,
    overflow: 'hidden',
  },
});