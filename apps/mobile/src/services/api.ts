/**
 * REST API client for the VYREN backend.
 *
 * The base URL is resolved from the centralised server config so callers
 * never hardcode an endpoint. Axios is used for consistent timeout, error
 * and header handling.
 */

import axios, { AxiosError, type AxiosInstance } from 'axios';
import { toWebSocketUrl } from '../config';
import type { MobileStatus, VisionAnalysis } from '../types';
import { MODEL_CATALOG, type ModelInfo } from '../models';
import { getServerUrl, loadServerUrl } from './serverConfig';

export class ApiError extends Error {
  readonly code:
    | 'network'
    | 'timeout'
    | 'http'
    | 'malformed'
    | 'unconfigured';
  readonly status?: number;

  constructor(
    code: ApiError['code'],
    message: string,
    status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/** Build a configured axios client for the current server URL. */
export function buildClient(): AxiosInstance {
  return axios.create({
    baseURL: getServerUrl(),
    timeout: 5000,
    headers: { Accept: 'application/json' },
  });
}

/** Resolve a WebSocket URL for the current server. */
export async function getWsUrl(): Promise<string> {
  await loadServerUrl();
  return toWebSocketUrl(getServerUrl());
}

function mapAxiosError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  const axiosError = error as AxiosError;
  if (axiosError?.code === 'ECONNABORTED') {
    return new ApiError('timeout', 'The server took too long to respond.');
  }
  if (!axiosError?.response) {
    return new ApiError('network', `Cannot reach VYREN server (${axiosError?.message ?? 'network error'}).`);
  }
  return new ApiError('http', `Server responded with ${axiosError.response.status}.`, axiosError.response.status);
}

/** Fetch `GET /api/mobile/status`. */
export async function getMobileStatus(): Promise<MobileStatus> {
  await loadServerUrl();
  const client = buildClient();
  let data: unknown;
  try {
    const response = await client.get<unknown>('/api/mobile/status');
    data = response.data;
  } catch (error) {
    throw mapAxiosError(error);
  }

  if (
    typeof data !== 'object' ||
    data === null ||
    typeof (data as { enabled?: unknown }).enabled !== 'boolean'
  ) {
    throw new ApiError('malformed', 'Malformed /api/mobile/status response.');
  }

  const raw = data as Partial<MobileStatus>;
  return {
    enabled: raw.enabled ?? false,
    model: raw.model ?? 'unknown',
    voice_name: raw.voice_name ?? '',
    capabilities: Array.isArray(raw.capabilities) ? raw.capabilities : [],
    active_sessions: typeof raw.active_sessions === 'number' ? raw.active_sessions : 0,
  };
}

/** Cheap reachability probe. */
export async function ping(): Promise<boolean> {
  try {
    await getMobileStatus();
    return true;
  } catch {
    return false;
  }
}

/**
 * Model catalog for the app.
 *
 * Phase D: fetch `GET /api/models` (when the backend ships it) and fold the
 * result into `mergeModelCatalog(...)`. For now the static catalog is the
 * single authoritative source so the selector works offline and never invents
 * models.
 */
export async function getModelCatalog(): Promise<ModelInfo[]> {
  return [...MODEL_CATALOG];
}

/**
 * Prepare for single-shot image analysis.
 *
 * `POST /api/vision/analyze` — accepted payload `{ image_base64, mime_type }`,
 * returns `{ summary: string, labels?: string[] }`. The endpoint does not
 * exist yet on the backend, so callers must handle `ApiError` (the camera
 * screen already renders an explicit "analysis unavailable" state).
 * No server behaviour is invented here.
 */
export async function analyzeVisionImage(input: {
  base64: string;
  mime: string;
}): Promise<VisionAnalysis> {
  await loadServerUrl();
  const client = buildClient();
  let data: unknown;
  try {
    const response = await client.post<unknown>('/api/vision/analyze', {
      image_base64: input.base64,
      mime_type: input.mime,
    });
    data = response.data;
  } catch (error) {
    throw mapAxiosError(error);
  }

  if (
    typeof data !== 'object' ||
    data === null ||
    typeof (data as { summary?: unknown }).summary !== 'string'
  ) {
    throw new ApiError('malformed', 'Malformed /api/vision/analyze response.');
  }

  const raw = data as Partial<VisionAnalysis>;
  return {
    summary: raw.summary ?? '',
    labels: Array.isArray(raw.labels)
      ? raw.labels.filter((label): label is string => typeof label === 'string')
      : [],
  };
}