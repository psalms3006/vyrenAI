/**
 * DEVELOPMENT PREVIEW — isolated mock `LiveSession`.
 *
 * This implements the exact `LiveSession` contract so the Phase C UI can be
 * walked through without a server or WebSocket. What it does and does NOT do:
 *
 *   - Connects:  simulates the MRP handshake as local state (no network).
 *   - Controls:  mute / camera / vision / model switches update state and
 *                re-emit, mirroring `mobile_live.py` message semantics.
 *   - AI output: never fabricated. `sendMessage()` records the caller's own
 *                text and posts an explicit, tagged note so nobody mistakes
 *                the preview for a real assistant turn.
 *   - Simulation: when `demo` is enabled, the connection/voice states cycle so
 *                every surface is reviewable. It is OFF by default.
 *
 * Production wiring replaces this file via `services/live.ts`.
 */

import type {
  AIState,
  LiveEvent,
  LiveSession,
  LiveSessionStatus,
  TranscriptMessage,
  VisionFrame,
} from '../live';

const stateOrder: AIState[] = [
  'idle',
  'listening',
  'thinking',
  'speaking',
  'executing_tool',
  'idle',
];

const PREVIEW_NOTE: TranscriptMessage = {
  id: 'preview-note',
  role: 'tool',
  text: 'Preview session — nothing is transmitted. Real audio + vision transport arrives with the live WebSocket service.',
  final: true,
  toolName: 'preview',
};

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${counter++}`;

export function createMockLiveSession(config: {
  serverUrl: string;
  model: string;
  sessionId?: string;
  demo?: boolean;
}): LiveSession {
  const id = config.sessionId || nextId('preview');
  const demo = config.demo === true;

  let status: LiveSessionStatus = 'idle';
  let aiState: AIState = 'idle';
  let model = config.model || 'gemini-3.1-flash-live-preview';
  let muted = false;
  let cameraEnabled = false;
  let visionEnabled = false;

  const listeners = new Set<(event: LiveEvent) => void>();
  let timeline: ReturnType<typeof setTimeout> | null = null;
  let stateStep = 0;
  let disconnected = false;

  const emit = (event: LiveEvent) => {
    listeners.forEach((listener) => listener(event));
  };

  const setStatus = (next: LiveSessionStatus) => {
    if (status === next) {
      return;
    }
    status = next;
    emit({ type: 'status', status });
  };

  const startTimeline = () => {
    if (!demo || timeline) {
      return;
    }
    timeline = setInterval(() => {
      if (disconnected) {
        return;
      }
      const next = stateOrder[stateStep % stateOrder.length];
      stateStep += 1;
      if (aiState !== next) {
        aiState = next;
        emit({ type: 'aiState', state: next });
      }
    }, 3200);
  };

  const clearTimeline = () => {
    if (timeline) {
      clearInterval(timeline);
      timeline = null;
    }
  };

  return {
    id,
    previewMode: true,

    async connect() {
      if (disconnected) {
        return;
      }
      if (status === 'connected' || status === 'connecting') {
        return;
      }
      setStatus('connecting');
      await Promise.resolve();
      if (disconnected) {
        return;
      }
      setStatus('connected');
      aiState = 'idle';
      emit({ type: 'aiState', state: aiState });
      startTimeline();
    },

    async disconnect() {
      if (disconnected) {
        return;
      }
      disconnected = true;
      clearTimeline();
      listeners.clear();
      setStatus('idle');
    },

    sendMessage(text: string) {
      const clean = (text ?? '').trim();
      if (!clean) {
        return;
      }
      emit({
        type: 'transcript',
        message: {
          id: nextId('user'),
          role: 'user',
          text: clean,
          final: true,
          timestamp: Date.now(),
        },
      });
      emit({
        type: 'transcript',
        message: { ...PREVIEW_NOTE, id: nextId('tool') },
      });
    },

    interrupt() {
      if (aiState === 'speaking' || aiState === 'thinking') {
        aiState = 'idle';
        emit({ type: 'aiState', state: aiState });
      }
    },

    setModel(next: string) {
      const clean = (next ?? '').trim();
      if (!clean || clean === model) {
        return;
      }
      model = clean;
      emit({ type: 'model', model });
    },

    setMuted(next: boolean) {
      if (muted === next) {
        return;
      }
      muted = next;
      emit({ type: 'muted', muted });
    },

    toggleMuted() {
      muted = !muted;
      emit({ type: 'muted', muted });
    },

    setCameraEnabled(enabled: boolean) {
      if (cameraEnabled === enabled) {
        return;
      }
      cameraEnabled = enabled;
      emit({ type: 'cameraEnabled', enabled });
    },

    setVisionEnabled(enabled: boolean) {
      if (visionEnabled === enabled) {
        return;
      }
      visionEnabled = enabled;
      emit({ type: 'visionEnabled', enabled });
    },

    pushAudio(_pcm: ArrayBuffer) {
      // Transport lands in Phase D.
    },

    pushVisionFrame(_frame: VisionFrame) {
      // Transport lands in Phase D.
    },

    on(listener: (event: LiveEvent) => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    getStatus: () => status,
    getAiState: () => aiState,
    getModel: () => model,
    getMuted: () => muted,
    getCameraEnabled: () => cameraEnabled,
    getVisionEnabled: () => visionEnabled,
  };
}