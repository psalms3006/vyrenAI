/**
 * Model catalog for the app.
 *
 * The current source of truth is the static catalog below (the known VYREN
 * models). A future backend endpoint (`GET /api/models`) can publish the
 * live catalog; `getModelCatalog()` in `services/api.ts` already resolves
 * through that seam and merges the static set as a fallback, so the UI never
 * depends on a hardcoded transport.
 *
 * Sources are intentionally coarse:
 *   - live  — realtime (streaming) voice/vision sessions (Gemini Live)
 *   - text  — conventional cloud text/tool completion
 *   - local — served by Ollama on the VYREN server machine
 */

import { KNOWN_MODELS } from './config';

export type ModelSource = 'live' | 'text' | 'local';

export interface ModelInfo {
  id: string;
  /** Human-friendly short name. */
  name: string;
  source: ModelSource;
  /** One-line note for the selector. */
  note?: string;
}

const MODEL_LABEL: Record<string, string> = {
  'gemini-3.1-flash-live-preview': 'Gemini 3.1 Flash Live',
  'gemini-2.5-flash': 'Gemini 2.5 Flash',
  'llama3.1': 'Llama 3.1',
  mistral: 'Mistral',
  tinyllama: 'TinyLlama',
};

const MODEL_NOTE: Record<string, string> = {
  'gemini-3.1-flash-live-preview': 'Realtime voice + vision',
  'gemini-2.5-flash': 'Fast cloud text',
  'llama3.1': 'Runs on your server (Ollama)',
  mistral: 'Runs on your server (Ollama)',
  tinyllama: 'Runs on your server (Ollama)',
};

const LIVE_IDS = new Set(['gemini-3.1-flash-live-preview']);
const LOCAL_IDS = new Set(['llama3.1', 'mistral', 'tinyllama']);

function sourceOf(id: string): ModelSource {
  if (LOCAL_IDS.has(id)) {
    return 'local';
  }
  if (LIVE_IDS.has(id)) {
    return 'live';
  }
  return 'text';
}

export const MODEL_CATALOG: readonly ModelInfo[] = KNOWN_MODELS.map((id) => ({
  id,
  name: MODEL_LABEL[id] ?? id,
  source: sourceOf(id),
  note: MODEL_NOTE[id],
}));

export function modelInfoOf(id: string | undefined): ModelInfo | undefined {
  if (!id) {
    return undefined;
  }
  return MODEL_CATALOG.find((m) => m.id === id);
}

export function modelLabel(id: string): string {
  return modelInfoOf(id)?.name ?? id;
}

/** Coarse category label used by chips and the selector. */
export function sourceLabel(source: ModelSource): string {
  switch (source) {
    case 'live':
      return 'LIVE';
    case 'local':
      return 'LOCAL';
    case 'text':
      return 'TEXT';
  }
}

/** Fold in backend-published models that aren't in the static catalog. */
export function mergeModelCatalog(published: readonly ModelInfo[]): ModelInfo[] {
  const byId = new Map<string, ModelInfo>(MODEL_CATALOG.map((m) => [m.id, m]));
  for (const model of published) {
    if (model && model.id) {
      byId.set(model.id, {
        id: model.id,
        name: model.name || model.id,
        source: model.source,
        note: model.note,
      });
    }
  }
  return Array.from(byId.values());
}