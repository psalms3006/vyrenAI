/**
 * @format
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import App from '../App';

// Replace the navigation tree with a stub so this test exercises the app
// shell (providers + safe area + gesture root) without the full navigator.
jest.mock('../src/navigation/RootNavigator', () => {
  const R = require('react');
  const { Text, View } = require('react-native');
  return {
    RootNavigator: () =>
      R.createElement(
        View,
        null,
        R.createElement(Text, null, 'navigation-stub'),
      ),
  };
});

// Prevent real network probes from the status effect during render.
jest.mock('../src/services/api', () => ({
  getMobileStatus: jest.fn().mockResolvedValue({
    enabled: false,
    model: 'gemini-3.1-flash-live-preview',
    voice_name: 'Charon',
    capabilities: ['audio'],
    active_sessions: 0,
  }),
  ApiError: class ApiError extends Error {},

  getWsUrl: jest.fn().mockResolvedValue('ws://localhost:8420'),
}));

test('renders the app shell without crashing', async () => {
  let root: ReactTestRenderer.ReactTestRenderer | undefined;
  await ReactTestRenderer.act(async () => {
    root = ReactTestRenderer.create(<App />);
  });
  expect(root).toBeTruthy();
});

test('mounts the navigation stub inside the shell', async () => {
  let root: ReactTestRenderer.ReactTestRenderer | undefined;
  await ReactTestRenderer.act(async () => {
    root = ReactTestRenderer.create(<App />);
  });
  expect(JSON.stringify(root!.toJSON())).toContain('navigation-stub');
});