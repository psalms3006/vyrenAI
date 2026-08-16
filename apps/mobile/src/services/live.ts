/**
 * Live session service seam.
 *
 * Screens and the live provider depend ONLY on the interfaces in this file —
 * never on a transport. `createLiveHandle()` resolves to the isolated
 * development preview (`./mocks/liveMock`) when `demo` is enabled, and to the
 * real Mobile Realtime Protocol session otherwise (WS /ws/live/mobile, per
 * `runtime/mobile_live.py` + `docs/mobile-realtime-protocol.md`).
 */

import type { AIState, TranscriptMessage } from '../types';
import { isAIState } from '../types';
import { toWebSocketUrl } from '../config';
import { base64ToBytes } from './binary';
import { createAudioOutput } from './audio';
import {
  MrpTransport,
  type MrpTransportState,
} from './mrpTransport';

/** High-level session status (transport + permissions), distinct from AIState. */
export type LiveSessionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'offline'
  | 'error';

/** A single vision frame handed to the transport or a viewer. */
export interface VisionFrame {
  base64: string;
  mime: 'image/jpeg' | 'image/png' | 'image/webp';
  width: number;
  height: number;
}

export type LiveEvent =
  | { type: 'status'; status: LiveSessionStatus }
  | { type: 'aiState'; state: AIState }
  | { type: 'transcript'; message: TranscriptMessage }
  | { type: 'model'; model: string }
  | { type: 'muted'; muted: boolean }
  | { type: 'cameraEnabled'; enabled: boolean }
  | { type: 'visionEnabled'; enabled: boolean }
  | { type: 'error'; code: string; message: string };

export interface LiveSession {
  readonly id: string;
  /** uid of the demo instance backing this session (empty for real). */
  readonly previewMode: boolean;

  connect(): Promise<void>;
  disconnect(): Promise<void>;

  /** Enqueue a text message as a user turn. */
  sendMessage(text: string): void;
  /** Interrupt the current assistant turn in flight. */
  interrupt(): void;

  setModel(model: string): void;
  setMuted(muted: boolean): void;
  toggleMuted(): void;
  setCameraEnabled(enabled: boolean): void;
  setVisionEnabled(enabled: boolean): void;

  /** Mic PCM16 16 kHz uplink (binary \x00 prefix). No-op in the preview. */
  pushAudio(pcm: ArrayBuffer): void;
  /** Vision frame uplink (binary \x01 prefix). No-op in the preview. */
  pushVisionFrame(frame: VisionFrame): void;

  on(listener: (event: LiveEvent) => void): () => void;

  getStatus(): LiveSessionStatus;
  getAiState(): AIState;
  getModel(): string;
  getMuted(): boolean;
  getCameraEnabled(): boolean;
  getVisionEnabled(): boolean;
}

export interface LiveSessionHandle {
  create(config: {
    serverUrl: string;
    model: string;
    sessionId?: string;
    /** Enable the isolated preview simulation (never default in prod). */
    demo?: boolean;
  }): LiveSession;
}

const VISION_MAX_BYTES = 2 << 20;

let counter = 0;
function nextId(prefix: string): string {
  return `${prefix}-${Date.now()}-${counter++}`;
}

function isAIStateValue(value: unknown): value is AIState {
  return typeof value === 'string' && isAIState(value);
}

/**
 * Real MRP session over a WebSocket. Mirrors `voice/mobile_session.py`
 * semantics exactly — it never invents protocol fields or endpoints.
 */
export function createRealLiveSession(config: {
  serverUrl: string;
  model?: string;
  sessionId?: string;
}): LiveSession {
  const url = `${toWebSocketUrl(config.serverUrl)}/ws/live/mobile`;
  let sessionId = config.sessionId || '';
  let model = config.model || 'gemini-3.1-flash-live-preview';
  let status: LiveSessionStatus = 'idle';
  let aiState: AIState = 'idle';
  let muted = false;
  let cameraEnabled = false;
  let visionEnabled = false;
  let disconnected = false;
  let lastUserPartial = '';

  const listeners = new Set<(event: LiveEvent) => void>();
  const output = createAudioOutput();

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

  const setAiState = (next: AIState) => {
    if (aiState === next) {
      return;
    }
    aiState = next;
    emit({ type: 'aiState', state: next });
  };

  const addMessage = (message: TranscriptMessage) => {
    emit({ type: 'transcript', message });
  };

  const handleServerMessage = (msg: Record<string, unknown>) => {
    switch (msg.type) {
      case 'init_ack': {
        if (!sessionId && typeof msg.session_id === 'string') {
          sessionId = msg.session_id;
        }
        if (typeof msg.model === 'string' && msg.model) {
          model = msg.model;
          emit({ type: 'model', model });
        }
        if (isAIStateValue(msg.voice_state)) {
          setAiState(msg.voice_state);
        }
        break;
      }
      case 'connected':
        setStatus('connected');
        setAiState('idle');
        break;
      case 'state_change': {
        if (isAIStateValue(msg.state)) {
          setAiState(msg.state);
        }
        break;
      }
      case 'transcription': {
        const user = typeof msg.user === 'string' ? msg.user : '';
        const modelText = typeof msg.model === 'string' ? msg.model : '';
        const isFinal = msg.final === true;
        if (isFinal) {
          if (user) {
            addMessage({
              id: nextId('user'),
              role: 'user',
              text: user,
              final: true,
              timestamp: Date.now(),
            });
          }
          if (modelText) {
            addMessage({
              id: nextId('assistant'),
              role: 'assistant',
              text: modelText,
              final: true,
              timestamp: Date.now(),
            });
          }
          lastUserPartial = '';
        } else if (user && user !== lastUserPartial) {
          // Stream the user's own partial words live; model partials are
          // skipped to keep the transcript from flickering between captures.
          lastUserPartial = user;
          addMessage({
            id: nextId('user'),
            role: 'user',
            text: user,
            final: false,
            timestamp: Date.now(),
          });
        }
        break;
      }
      case 'tool_call': {
        const name = typeof msg.name === 'string' ? msg.name : 'tool';
        if (msg.status !== 'done') {
          addMessage({
            id: nextId('tool'),
            role: 'tool',
            text: `Running ${name}…`,
            final: true,
            toolName: name,
            timestamp: Date.now(),
          });
        }
        break;
      }
      case 'tool_result': {
        const name = typeof msg.name === 'string' ? msg.name : 'tool';
        const result =
          typeof msg.result === 'string' && msg.result
            ? `→ ${msg.result}`
            : 'Done';
        addMessage({
          id: nextId('tool'),
          role: 'tool',
          text: result,
          final: true,
          toolName: name,
          timestamp: Date.now(),
        });
        break;
      }
      case 'turn_complete':
        break;
      case 'model_changed': {
        if (typeof msg.model === 'string' && msg.model) {
          model = msg.model;
          emit({ type: 'model', model });
        }
        break;
      }
      case 'terminate_ack':
        setStatus('idle');
        break;
      case 'error': {
        const code = typeof msg.code === 'string' ? msg.code : 'error';
        const message =
          typeof msg.message === 'string'
            ? msg.message
            : 'The server reported an error.';
        // Terminal-ish protocol errors surface as a failed session state so
        // the UI stops treating the socket as live.
        if (
          code === 'bad_init' ||
          code === 'no_api_key' ||
          code === 'bad_model'
        ) {
          setStatus('error');
        }
        emit({ type: 'error', code, message });
        break;
      }
    }
  };

  const transport = new MrpTransport({ url, sessionId, model }, {
    onState(state: MrpTransportState, wasConnected: boolean) {
      if (disconnected) {
        return;
      }
      switch (state) {
        case 'connecting':
          setStatus('connecting');
          break;
        case 'connected':
          // Session-level "connected" waits for the server `connected` frame.
          break;
        case 'reconnecting':
          setStatus(wasConnected ? 'reconnecting' : 'connecting');
          break;
        case 'offline':
          setStatus('offline');
          break;
        case 'closed':
          if (status === 'connected' || status === 'connecting' || status === 'reconnecting') {
            setStatus('idle');
          }
          break;
      }
    },
    onAudio(pcm: ArrayBuffer) {
      if (status !== 'connected') {
        return;
      }
      output.play(pcm);
    },
    onMessage: handleServerMessage,
  });

  return {
    id: sessionId || nextId('live'),
    previewMode: false,

    async connect() {
      if (disconnected) {
        return;
      }
      if (status === 'connected' || status === 'connecting' || status === 'reconnecting') {
        return;
      }
      setStatus('connecting');
      transport.connect();
    },

    async disconnect() {
      if (disconnected) {
        return;
      }
      disconnected = true;
      transport.disconnect();
      output.clear();
      setStatus('idle');
    },

    sendMessage(text: string) {
      const clean = (text ?? '').trim();
      if (!clean) {
        return;
      }
      // MRP has no text-message uplink — voice is the input modality. Record
      // the turn locally so the transcript stays coherent; nothing is invented
      // on the wire.
      addMessage({
        id: nextId('user'),
        role: 'user',
        text: clean,
        final: true,
        timestamp: Date.now(),
      });
    },

    interrupt() {
      output.clear();
      transport.sendText({ type: 'interrupt' });
    },

    setModel(next: string) {
      const clean = (next ?? '').trim();
      if (!clean || clean === model) {
        return;
      }
      transport.sendText({ type: 'model_request', model: clean });
    },

    setMuted(next: boolean) {
      if (muted === next) {
        return;
      }
      muted = next;
      if (muted) {
        // Stop any assistant audio the moment the user mutes.
        output.clear();
        transport.sendText({ type: 'interrupt' });
      }
      emit({ type: 'muted', muted });
    },

    toggleMuted() {
      this.setMuted(!muted);
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

    pushAudio(pcm: ArrayBuffer) {
      if (status !== 'connected') {
        return;
      }
      transport.sendAudio(pcm);
    },

    pushVisionFrame(frame: VisionFrame) {
      if (status !== 'connected') {
        return;
      }
      // MRP optimization: only send vision when the engine can consume it.
      if (aiState === 'speaking') {
        return;
      }
      const bytes = base64ToBytes(frame.base64);
      if (!bytes || bytes.byteLength <= 0 || bytes.byteLength > VISION_MAX_BYTES) {
        return;
      }
      transport.sendVision(bytes);
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

import { createMockLiveSession } from './mocks/liveMock';

export function createLiveHandle(): LiveSessionHandle {
  return {
    create(config) {
      if (config.demo === true) {
        return createMockLiveSession(config);
      }
      return createRealLiveSession(config);
    },
  };
}

export type { AIState, TranscriptMessage };