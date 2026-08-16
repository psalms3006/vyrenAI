/**
 * Shared domain types used across the mobile app.
 */

/** Mirror of the backend VoiceState FSM (`voice_engine/protocol.py`). */
export type AIState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'executing_tool'
  | 'reconnecting'
  | 'failed';

export const AI_STATES: readonly AIState[] = [
  'idle',
  'connecting',
  'listening',
  'thinking',
  'speaking',
  'executing_tool',
  'reconnecting',
  'failed',
];

export function isAIState(value: string | null | undefined): value is AIState {
  return !!value && (AI_STATES as readonly string[]).includes(value);
}

/** Response of `GET /api/mobile/status`. */
export interface MobileStatus {
  enabled: boolean;
  model: string;
  voice_name: string;
  capabilities: string[];
  active_sessions: number;
}

export type ConnectionState = 'unknown' | 'connecting' | 'connected' | 'error';

export type MessageRole = 'user' | 'assistant' | 'tool';

/** One line in the live transcript surface. */
export interface TranscriptMessage {
  id: string;
  role: MessageRole;
  text: string;
  final: boolean;
  /** Tool name for tool-role messages. */
  toolName?: string;
  timestamp?: number;
}

export interface Suggestion {
  id: string;
  title: string;
  body?: string;
  icon?: string;
}

/** Physical camera facing on device. */
export type CameraFacing = 'front' | 'back';

/** Result of a single-shot image analysis (POST /api/vision/analyze). */
export interface VisionAnalysis {
  summary: string;
  labels: string[];
}

export interface Preferences {
  /** Auto-scroll transcript as new lines arrive. */
  transcriptAutoScroll: boolean;
  /** Feedback style (haptics on interactive controls where supported). */
  haptics: boolean;
  /** Preferred camera facing used by capture/vision surfaces. */
  cameraFacing: CameraFacing;
  /** Preferred assistant voice id (mirrors backend DEFAULT_VOICE_NAME). */
  voiceName: string;
  /** Run the isolated live-session preview simulation (Settings). */
  previewSimulation: boolean;
}

export const DEFAULT_PREFERENCES: Preferences = {
  transcriptAutoScroll: true,
  haptics: true,
  cameraFacing: 'back',
  voiceName: 'Charon',
  previewSimulation: false,
};