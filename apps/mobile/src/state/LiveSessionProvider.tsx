/**
 * LiveSessionProvider — app-wide live conversation state.
 *
 * Owns a single `LiveSession` (see `services/live.ts`; Phase D provides the
 * MRP WebSocket transport, Phase C resolves to the isolated preview) and maps
 * its event stream onto reducer state that screens consume. Screens never see
 * a transport object — only status/state/controls.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';

import { createLiveHandle, type LiveEvent, type LiveSession } from '../services/live';
import type { LiveSessionStatus, VisionFrame } from '../services/live';
import { useApp } from './AppContext';
import type { AIState, TranscriptMessage } from '../types';

interface LiveState {
  status: LiveSessionStatus;
  aiState: AIState;
  model: string;
  muted: boolean;
  cameraEnabled: boolean;
  visionEnabled: boolean;
  messages: TranscriptMessage[];
  error: string | null;
  previewMode: boolean;
}

type LiveAction =
  | { type: 'STATUS'; status: LiveSessionStatus }
  | { type: 'AI_STATE'; state: AIState }
  | { type: 'MESSAGE'; message: TranscriptMessage }
  | { type: 'MODEL'; model: string }
  | { type: 'MUTED'; muted: boolean }
  | { type: 'CAMERA'; enabled: boolean }
  | { type: 'VISION'; enabled: boolean }
  | { type: 'ERROR'; message: string }
  | { type: 'PREVIEW'; mode: boolean }
  | { type: 'RESET'; previewMode: boolean };

const MAX_MESSAGES = 200;

function initialLiveState(previewMode: boolean): LiveState {
  return {
    status: 'idle',
    aiState: 'idle',
    model: '',
    muted: false,
    cameraEnabled: false,
    visionEnabled: false,
    messages: [],
    error: null,
    previewMode,
  };
}

function liveReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.type) {
    case 'STATUS':
      return { ...state, status: action.status };
    case 'AI_STATE':
      return { ...state, aiState: action.state };
    case 'MESSAGE': {
      const exists = state.messages.some((m) => m.id === action.message.id);
      if (exists) {
        return state;
      }
      let messages = [...state.messages, action.message];
      if (messages.length > MAX_MESSAGES) {
        messages = messages.slice(-MAX_MESSAGES);
      }
      return { ...state, messages };
    }
    case 'MODEL':
      return { ...state, model: action.model };
    case 'MUTED':
      return { ...state, muted: action.muted };
    case 'CAMERA':
      return { ...state, cameraEnabled: action.enabled };
    case 'VISION':
      return { ...state, visionEnabled: action.enabled };
    case 'ERROR':
      return { ...state, error: action.message, status: 'error' };
    case 'PREVIEW':
      return { ...state, previewMode: action.mode };
    case 'RESET':
      return { ...initialLiveState(action.previewMode) };
    default:
      return state;
  }
}

export interface LiveSessionContextValue {
  status: LiveSessionStatus;
  aiState: AIState;
  model: string;
  muted: boolean;
  cameraEnabled: boolean;
  visionEnabled: boolean;
  messages: TranscriptMessage[];
  error: string | null;
  /** True when backed by the isolated preview simulation. */
  previewMode: boolean;

  start: () => void;
  stop: () => void;
  sendMessage: (text: string) => void;
  interrupt: () => void;
  setModel: (model: string) => void;
  toggleMuted: () => void;
  setCameraEnabled: (enabled: boolean) => void;
  setVisionEnabled: (enabled: boolean) => void;
  /** Phase D: feed mic PCM16 16 kHz mono into the live transport. */
  pushAudio: (pcm: ArrayBuffer) => void;
  /** Phase D: feed a captured frame into the live transport (vision uplink). */
  pushVisionFrame: (frame: VisionFrame) => void;
}

const LiveSessionContext = createContext<LiveSessionContextValue | undefined>(
  undefined,
);

export function LiveSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { state: app } = useApp();
  const previewMode = app.preferences.previewSimulation;
  const serverUrl = app.serverUrl;

  const [state, dispatch] = useReducer(
    liveReducer,
    previewMode,
    initialLiveState,
  );

  const sessionRef = useRef<LiveSession | null>(null);
  const modelRef = useRef(app.model);
  modelRef.current = app.model;
  const previewRef = useRef(previewMode);
  previewRef.current = previewMode;

  const handleEvent = useCallback((event: LiveEvent) => {
    switch (event.type) {
      case 'status':
        dispatch({ type: 'STATUS', status: event.status });
        break;
      case 'aiState':
        dispatch({ type: 'AI_STATE', state: event.state });
        break;
      case 'transcript':
        dispatch({ type: 'MESSAGE', message: event.message });
        break;
      case 'model':
        dispatch({ type: 'MODEL', model: event.model });
        break;
      case 'muted':
        dispatch({ type: 'MUTED', muted: event.muted });
        break;
      case 'cameraEnabled':
        dispatch({ type: 'CAMERA', enabled: event.enabled });
        break;
      case 'visionEnabled':
        dispatch({ type: 'VISION', enabled: event.enabled });
        break;
      case 'error':
        dispatch({ type: 'ERROR', message: event.message });
        break;
    }
  }, []);

  // Create the session when the server is known; recreate only when the
  // server URL or preview flag changes (model switches stay in-session).
  useEffect(() => {
    if (!serverUrl) {
      return;
    }
    const handle = createLiveHandle();
    const session = handle.create({
      serverUrl,
      model: modelRef.current,
      demo: previewRef.current,
    });
    sessionRef.current = session;
    dispatch({ type: 'RESET', previewMode: previewRef.current });

    const off = session.on(handleEvent);
    return () => {
      off();
      session.disconnect();
      sessionRef.current = null;
    };
  }, [serverUrl, previewMode, handleEvent]);

  // Forward model preference changes into the running session.
  useEffect(() => {
    const session = sessionRef.current;
    if (session && app.model && app.model !== session.getModel()) {
      session.setModel(app.model);
    }
  }, [app.model]);

  // Auto-connect once the server status probe reports healthy.
  useEffect(() => {
    const session = sessionRef.current;
    if (session && app.connection === 'connected') {
      session.connect();
    }
  }, [app.connection]);

  const start = useCallback(() => {
    sessionRef.current?.connect();
  }, []);

  const stop = useCallback(() => {
    sessionRef.current?.disconnect();
  }, []);

  const sendMessage = useCallback((text: string) => {
    sessionRef.current?.sendMessage(text);
  }, []);

  const interrupt = useCallback(() => {
    sessionRef.current?.interrupt();
  }, []);

  const setModel = useCallback((model: string) => {
    const session = sessionRef.current;
    if (session) {
      session.setModel(model);
    } else {
      dispatch({ type: 'MODEL', model });
    }
  }, []);

  const toggleMuted = useCallback(() => {
    sessionRef.current?.toggleMuted();
  }, []);

  const setCameraEnabled = useCallback((enabled: boolean) => {
    sessionRef.current?.setCameraEnabled(enabled);
  }, []);

  const setVisionEnabled = useCallback((enabled: boolean) => {
    sessionRef.current?.setVisionEnabled(enabled);
  }, []);

  const pushAudio = useCallback((pcm: ArrayBuffer) => {
    sessionRef.current?.pushAudio(pcm);
  }, []);

  const pushVisionFrame = useCallback((frame: VisionFrame) => {
    sessionRef.current?.pushVisionFrame(frame);
  }, []);

  const value = useMemo<LiveSessionContextValue>(
    () => ({
      status: state.status,
      aiState: state.aiState,
      model: state.model,
      muted: state.muted,
      cameraEnabled: state.cameraEnabled,
      visionEnabled: state.visionEnabled,
      messages: state.messages,
      error: state.error,
      previewMode: state.previewMode,
      start,
      stop,
      sendMessage,
      interrupt,
      setModel,
      toggleMuted,
      setCameraEnabled,
      setVisionEnabled,
      pushAudio,
      pushVisionFrame,
    }),
    [
      state,
      start,
      stop,
      sendMessage,
      interrupt,
      setModel,
      toggleMuted,
      setCameraEnabled,
      setVisionEnabled,
      pushAudio,
      pushVisionFrame,
    ],
  );

  return (
    <LiveSessionContext.Provider value={value}>
      {children}
    </LiveSessionContext.Provider>
  );
}

export function useLiveSession(): LiveSessionContextValue {
  const context = useContext(LiveSessionContext);
  if (!context) {
    throw new Error('useLiveSession must be used within a LiveSessionProvider.');
  }
  return context;
}