/**
 * Server configuration store.
 *
 * The VYREN server URL lives here (memory cache + AsyncStorage persistence)
 * so both the REST/WS services and the UI read a single source of truth.
 */

import { DEFAULT_SERVER_URL, STORAGE_KEYS } from '../config';
import { getItem, setItem } from './storage';

let resolved: string | null = null;

/** Load the persisted server URL (cached in memory). First return is the default. */
export async function loadServerUrl(): Promise<string> {
  if (resolved == null) {
    const stored = await getItem(STORAGE_KEYS.serverUrl);
    resolved = stored && stored.length > 0 ? stored : DEFAULT_SERVER_URL;
  }
  return resolved;
}

/** Synchronous view of the current value (valid after first load). */
export function getServerUrl(): string {
  return resolved ?? DEFAULT_SERVER_URL;
}

/** Persist a new server URL and update the in-memory value. */
export async function setServerUrl(url: string): Promise<void> {
  const next = url.trim() || DEFAULT_SERVER_URL;
  resolved = next;
  await setItem(STORAGE_KEYS.serverUrl, next);
}

/** Forget the persisted value and return to the platform default. */
export async function resetServerUrl(): Promise<void> {
  resolved = DEFAULT_SERVER_URL;
  await setItem(STORAGE_KEYS.serverUrl, DEFAULT_SERVER_URL);
}