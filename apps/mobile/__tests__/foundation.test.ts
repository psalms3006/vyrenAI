/**
 * @format
 * Pure-logic tests for the design token system, app config and the
 * server-config store.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  DEFAULT_SERVER_URL,
  KNOWN_MODELS,
  STORAGE_KEYS,
  normalizeServerUrl,
  toWebSocketUrl,
} from '../src/config';
import * as serverConfig from '../src/services/serverConfig';
import {
  aiStateVisualOf,
  aiStates,
  colors,
  elevation,
  motion,
  radius,
  spacing,
  surfaces,
  typography,
} from '../src/theme';
import { AI_STATES, DEFAULT_PREFERENCES } from '../src/types';

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('theme tokens', () => {
  test('exposes all core token groups', () => {
    expect(colors.background).toBeDefined();
    expect(colors.accent).toBeDefined();
    expect(colors.textPrimary).toBeDefined();
    expect(spacing.lg).toBe(16);
    expect(radius.pill).toBe(999);
    expect(elevation.floating.elevation).toBeGreaterThan(0);
    expect(elevation.floating.shadowOpacity).toBeGreaterThan(0);
    expect(motion.duration.normal).toBeGreaterThan(0);
    expect(surfaces.glass.medium.intensity).toBeGreaterThan(0);
    expect(typography.body.fontSize).toBe(15);
    expect(typography.title.fontSize).toBeGreaterThan(typography.body.fontSize);
  });

  test('every AI state resolves a themed visual', () => {
    for (const state of AI_STATES) {
      const visual = aiStateVisualOf(state);
      expect(visual.color).toMatch(/^#/);
      expect(visual.label.length).toBeGreaterThan(0);
      expect(visual.glow.length).toBeGreaterThan(0);
    }
    expect(aiStates.idle.label).toBe('Idle');
  });
});

describe('config', () => {
  test('default server URL is http with the mobile port', () => {
    expect(DEFAULT_SERVER_URL.startsWith('http://')).toBe(true);
    expect(DEFAULT_SERVER_URL.endsWith(':8420')).toBe(true);
  });

  test('normalizeServerUrl handles bare host and trailing slash', () => {
    expect(normalizeServerUrl(' 10.0.2.2:8420 ')).toBe('http://10.0.2.2:8420');
    expect(normalizeServerUrl('https://vyren.local/')).toBe('https://vyren.local');
    expect(normalizeServerUrl('http://localhost:8420/')).toBe('http://localhost:8420');
  });

  test('toWebSocketUrl converts http to ws', () => {
    expect(toWebSocketUrl('http://localhost:8420')).toBe('ws://localhost:8420');
    expect(toWebSocketUrl('https://example.com')).toBe('wss://example.com');
  });

  test('known models are non-empty', () => {
    expect(KNOWN_MODELS.length).toBeGreaterThan(0);
  });
});

describe('serverConfig store', () => {
  test('defaults to the platform URL, then persists an override', async () => {
    expect(await serverConfig.loadServerUrl()).toBe(DEFAULT_SERVER_URL);

    await serverConfig.setServerUrl('http://192.168.1.5:8420');

    expect(serverConfig.getServerUrl()).toBe('http://192.168.1.5:8420');
    // Persisted under the storage key.
    expect(await AsyncStorage.getItem(STORAGE_KEYS.serverUrl)).toBe(
      'http://192.168.1.5:8420',
    );
  });

  test('reset returns to the platform default', async () => {
    await serverConfig.setServerUrl('http://10.0.0.9:8420');
    await serverConfig.resetServerUrl();
    expect(serverConfig.getServerUrl()).toBe(DEFAULT_SERVER_URL);
  });
});

describe('default preferences', () => {
  test('are sensible and stable', () => {
    expect(DEFAULT_PREFERENCES.transcriptAutoScroll).toBe(true);
    expect(DEFAULT_PREFERENCES.haptics).toBe(true);
  });
});