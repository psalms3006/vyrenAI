/**
 * App-wide constants. The VYREN server base URL is centralised here and can
 * be overridden at runtime by the user (persisted via AsyncStorage) — it is
 * never hardcoded inside screens or components.
 */

import { Platform } from 'react-native';

/** Standalone VYREN backend port (server.py). */
export const DEFAULT_SERVER_PORT = 8420;

/**
 * Default base URL. Android emulators reach the host machine via
 * 10.0.2.2; iOS simulators can use localhost.
 */
export const DEFAULT_SERVER_URL = ((): string => {
  const host = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';
  return `http://${host}:${DEFAULT_SERVER_PORT}`;
})();

/** AsyncStorage keys. */
export const STORAGE_KEYS = {
  serverUrl: 'vyren.serverUrl',
  model: 'vyren.model',
  preferences: 'vyren.preferences',
} as const;

/** `ws://` URL for a given `http://` base. */
export function toWebSocketUrl(httpBaseUrl: string): string {
  return httpBaseUrl.replace(/^http/, 'ws');
}

/** Trim/validate a user-entered server URL. */
export function normalizeServerUrl(input: string): string {
  const trimmed = input.trim().replace(/\/+$/, '');
  if (!trimmed) {
    return trimmed;
  }
  return /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

/** Model IDs offered by the app (fallback catalog; backend can publish more). */
export const KNOWN_MODELS: readonly string[] = [
  'gemini-3.1-flash-live-preview',
  'gemini-2.5-flash',
  'llama3.1',
  'mistral',
  'tinyllama',
];