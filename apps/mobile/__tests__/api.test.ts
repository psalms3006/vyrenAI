/**
 * @format
 * Tests for the REST API layer (axios mocked to avoid network).
 */

import axios from 'axios';

import { getMobileStatus, getWsUrl } from '../src/services/api';

jest.mock('axios', () => {
  const create = jest.fn();
  return {
    __esModule: true,
    default: { create },
    AxiosError: class AxiosError extends Error {
      code?: string;
      response?: unknown;
      isAxiosError = true;
      constructor(message?: string, code?: string) {
        super(message);
        this.code = code;
      }
    },
  };
});

const mockedCreate = axios.create as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
});

test('maps a valid /api/mobile/status response', async () => {
  const client = {
    get: jest.fn().mockResolvedValue({
      data: {
        enabled: true,
        model: 'gemini-3.1-flash-live-preview',
        voice_name: 'Charon',
        capabilities: ['audio', 'vision', 'model_switch', 'resumption'],
        active_sessions: 2,
      },
    }),
  };
  mockedCreate.mockReturnValue(client);

  const status = await getMobileStatus();
  expect(client.get).toHaveBeenCalledWith('/api/mobile/status');
  expect(status).toMatchObject({
    enabled: true,
    model: 'gemini-3.1-flash-live-preview',
    capabilities: expect.arrayContaining(['audio', 'vision']),
    active_sessions: 2,
  });
});

test('throws malformed when enabled is not a boolean', async () => {
  const client = { get: jest.fn().mockResolvedValue({ data: { whatever: 1 } }) };
  mockedCreate.mockReturnValue(client);
  await expect(getMobileStatus()).rejects.toMatchObject({ code: 'malformed' });
});

test('maps a timeout (ECONNABORTED)', async () => {
  const client = { get: jest.fn().mockRejectedValue({ code: 'ECONNABORTED' }) };
  mockedCreate.mockReturnValue(client);
  await expect(getMobileStatus()).rejects.toMatchObject({ code: 'timeout' });
});

test('maps a network error', async () => {
  const client = {
    get: jest.fn().mockRejectedValue({ isAxiosError: true, message: 'Network Error' }),
  };
  mockedCreate.mockReturnValue(client);
  await expect(getMobileStatus()).rejects.toMatchObject({ code: 'network' });
});

test('maps an HTTP error with status', async () => {
  const client = {
    get: jest.fn().mockRejectedValue({
      isAxiosError: true,
      response: { status: 500 },
    }),
  };
  mockedCreate.mockReturnValue(client);
  await expect(getMobileStatus()).rejects.toMatchObject({ code: 'http', status: 500 });
});

test('resolves a ws:// URL from the configured server', async () => {
  await expect(getWsUrl()).resolves.toBe('ws://localhost:8420');
});