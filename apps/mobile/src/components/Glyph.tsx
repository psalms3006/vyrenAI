/**
 * Glyph — a small set of minimal geometric icons drawn with plain Views.
 *
 * Deliberately typeless in the "icon font" sense: thin strokes, single
 * colour, no bundled assets and no SVG dependency, so every tab/control stays
 * discoverable and cheap. Size and colour are props (defaults match the tab
 * bar / control scale).
 *
 * The geometry below is derived from the `size` prop at render time, so
 * inline styles are the idiomatic form here; StyleSheet entries would have to
 * be per-pixel variants for no benefit.
 */

/* eslint-disable react-native/no-inline-styles */

import React from 'react';
import { StyleSheet, View } from 'react-native';

export type GlyphName =
  | 'chat'
  | 'live'
  | 'camera'
  | 'vision'
  | 'mic'
  | 'micOff'
  | 'flip'
  | 'pause'
  | 'play'
  | 'close'
  | 'check'
  | 'chevronRight'
  | 'layers';

export interface GlyphProps {
  name: GlyphName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}

interface Box {
  s: number;
  sw: number;
  color: string;
}

export function Glyph({
  name,
  size = 22,
  color = '#F5F5F7',
  strokeWidth = 1.6,
}: GlyphProps) {
  const box: Box = { s: size, sw: strokeWidth, color };
  return (
    <View
      style={[styles.viewbox, { width: size, height: size }]}
      accessibilityElementsHidden>
      {renderGlyph(name, box)}
    </View>
  );
}

function renderGlyph(name: GlyphName, b: Box) {
  switch (name) {
    case 'chat':
      return <ChatGlyph {...b} />;
    case 'live':
      return <LiveGlyph {...b} />;
    case 'camera':
      return <CameraGlyph {...b} />;
    case 'vision':
      return <VisionGlyph {...b} />;
    case 'mic':
      return <MicGlyph {...b} />;
    case 'micOff':
      return <MicOffGlyph {...b} />;
    case 'flip':
      return <FlipGlyph {...b} />;
    case 'pause':
      return <PauseGlyph {...b} />;
    case 'play':
      return <PlayGlyph {...b} />;
    case 'close':
      return <CloseGlyph {...b} />;
    case 'check':
      return <CheckGlyph {...b} />;
    case 'chevronRight':
      return <ChevronRightGlyph {...b} />;
    case 'layers':
      return <LayersGlyph {...b} />;
  }
}

function ChatGlyph({ s, sw, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: s * 0.16,
          top: s * 0.2,
          width: s * 0.68,
          height: s * 0.56,
          borderWidth: sw,
          borderColor: color,
          borderRadius: s * 0.16,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.28,
          top: s * 0.66,
          width: s * 0.18,
          height: s * 0.18,
          borderLeftWidth: sw,
          borderBottomWidth: sw,
          borderLeftColor: color,
          borderBottomColor: color,
          borderBottomLeftRadius: s * 0.07,
          transform: [{ rotate: '-45deg' }],
        }}
      />
    </>
  );
}

function LiveGlyph({ s, sw, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: s * 0.19,
          top: s * 0.19,
          width: s * 0.62,
          height: s * 0.62,
          borderWidth: sw,
          borderColor: color,
          borderRadius: s,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.36,
          top: s * 0.36,
          width: s * 0.28,
          height: s * 0.28,
          borderRadius: s,
          backgroundColor: color,
        }}
      />
    </>
  );
}

function CameraGlyph({ s, sw, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: s * 0.1,
          top: s * 0.24,
          width: s * 0.8,
          height: s * 0.58,
          borderWidth: sw,
          borderColor: color,
          borderRadius: s * 0.1,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: (s - s * 0.36) / 2,
          top: (s - s * 0.36) / 2,
          width: s * 0.36,
          height: s * 0.36,
          borderWidth: sw * 0.8,
          borderColor: color,
          borderRadius: s,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.16,
          top: s * 0.16,
          width: s * 0.12,
          height: s * 0.16,
          borderWidth: sw,
          borderColor: color,
          borderBottomWidth: 0,
          borderTopLeftRadius: s * 0.05,
          borderTopRightRadius: s * 0.05,
        }}
      />
    </>
  );
}

function VisionGlyph({ s, sw, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: s * 0.05,
          top: s * 0.27,
          width: s * 0.9,
          height: s * 0.46,
          borderWidth: sw,
          borderColor: color,
          borderRadius: s,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: (s - s * 0.26) / 2,
          top: (s - s * 0.26) / 2,
          width: s * 0.26,
          height: s * 0.26,
          borderRadius: s,
          backgroundColor: color,
        }}
      />
    </>
  );
}

function MicGlyph({ s, sw, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: (s - s * 0.34) / 2,
          top: s * 0.12,
          width: s * 0.34,
          height: s * 0.54,
          borderWidth: sw,
          borderColor: color,
          borderRadius: s,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: (s - s * 0.56) / 2,
          top: s * 0.5,
          width: s * 0.56,
          height: s * 0.56,
          borderLeftWidth: sw,
          borderRightWidth: sw,
          borderBottomWidth: sw,
          borderLeftColor: color,
          borderRightColor: color,
          borderBottomColor: color,
          borderBottomLeftRadius: s * 0.28,
          borderBottomRightRadius: s * 0.28,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: (s - s * 0.14) / 2,
          top: s * 0.52,
          width: s * 0.14,
          height: s * 0.18,
          backgroundColor: color,
        }}
      />
    </>
  );
}

function MicOffGlyph(b: Box) {
  return (
    <>
      <MicGlyph {...b} />
      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          left: b.s * 0.08,
          top: b.s * 0.3,
          width: b.s * 0.95,
          height: b.sw * 1.05,
          backgroundColor: b.color,
          transform: [{ rotate: '45deg' }],
        }}
      />
    </>
  );
}

function FlipGlyph({ s, sw, color }: Box) {
  const c = s * 0.3;
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: s * 0.24,
          top: s * 0.1,
          width: c,
          height: c,
          borderTopWidth: sw,
          borderRightWidth: sw,
          borderTopColor: color,
          borderRightColor: color,
          borderTopRightRadius: s * 0.1,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.16,
          top: s * 0.14,
          width: s * 0.3,
          height: sw,
          backgroundColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.46,
          top: s * 0.6,
          width: c,
          height: c,
          borderBottomWidth: sw,
          borderLeftWidth: sw,
          borderBottomColor: color,
          borderLeftColor: color,
          borderBottomLeftRadius: s * 0.1,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: s * 0.54,
          top: s * 0.42,
          width: s * 0.3,
          height: sw,
          backgroundColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
    </>
  );
}

function PauseGlyph({ s: sz, color }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: sz * 0.32,
          top: sz * 0.2,
          width: sz * 0.09,
          height: sz * 0.6,
          borderRadius: 2,
          backgroundColor: color,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: sz * 0.59,
          top: sz * 0.2,
          width: sz * 0.09,
          height: sz * 0.6,
          borderRadius: 2,
          backgroundColor: color,
        }}
      />
    </>
  );
}

function PlayGlyph({ s: sz, color }: Box) {
  return (
    <View
      style={{
        position: 'absolute',
        left: sz * 0.38,
        top: sz * 0.18,
        width: 0,
        height: 0,
        borderTopWidth: sz * 0.32,
        borderBottomWidth: sz * 0.32,
        borderLeftWidth: sz * 0.42,
        borderTopColor: 'transparent',
        borderBottomColor: 'transparent',
        borderLeftColor: color,
      }}
    />
  );
}

function CloseGlyph({ s: sz, color, sw }: Box) {
  return (
    <>
      <View
        style={{
          position: 'absolute',
          left: sz * 0.16,
          top: sz * 0.47,
          width: sz * 0.68,
          height: sw,
          backgroundColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: sz * 0.16,
          top: sz * 0.47,
          width: sz * 0.68,
          height: sw,
          backgroundColor: color,
          transform: [{ rotate: '-45deg' }],
        }}
      />
    </>
  );
}

function CheckGlyph({ s: sz, color, sw }: Box) {
  return (
    <View
      style={{
        position: 'absolute',
        left: sz * 0.24,
        top: sz * 0.3,
        width: sz * 0.54,
        height: sz * 0.3,
        borderLeftWidth: sw,
        borderBottomWidth: sw,
        borderLeftColor: color,
        borderBottomColor: color,
        transform: [{ rotate: '-45deg' }],
      }}
    />
  );
}

function ChevronRightGlyph({ s: sz, color, sw }: Box) {
  return (
    <View
      style={{
        position: 'absolute',
        left: sz * 0.28,
        top: sz * 0.18,
        width: sz * 0.42,
        height: sz * 0.42,
        borderRightWidth: sw,
        borderTopWidth: sw,
        borderRightColor: color,
        borderTopColor: color,
        transform: [{ rotate: '45deg' }],
      }}
    />
  );
}

function LayersGlyph({ s: sz, sw, color }: Box) {
  const back = {
    position: 'absolute' as const,
    left: sz * 0.17,
    top: sz * 0.14,
    width: sz * 0.66,
    height: sz * 0.5,
    borderWidth: sw,
    borderColor: color,
    borderRadius: sz * 0.08,
    opacity: 0.45,
    backgroundColor: 'transparent',
  };
  const front = { ...back, left: sz * 0.25, top: sz * 0.3, opacity: 1 };
  return (
    <>
      <View style={back} />
      <View style={front} />
    </>
  );
}

const styles = StyleSheet.create({
  viewbox: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});