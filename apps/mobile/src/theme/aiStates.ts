/**
 * AI-state → visuals mapping. Mirrors the backend `VoiceState` FSM so any
 * UI component (orb, pill, waveform) can derive consistent colour/glow from
 * a single state id.
 */

import type { AIState } from '../types';
import { colors } from './colors';

export interface AIStateVisual {
  label: string;
  /** Primary surface/highlight colour for this state. */
  color: string;
  /** Soft translucent wash for halos/glows. */
  glow: string;
}

const rgb = (hex: string) => {
  const h = hex.replace('#', '');
  return `${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(
    h.slice(4, 6),
    16,
  )}`;
};

const visual = (label: string, color: string, alpha = 0.22): AIStateVisual => ({
  label,
  color,
  glow: `rgba(${rgb(color)}, ${alpha})`,
});

export const aiStates: Record<AIState, AIStateVisual> = {
  idle: visual('Idle', '#6B7280', 0.12),
  connecting: visual('Connecting', colors.info, 0.16),
  listening: visual('Listening', colors.info, 0.18),
  thinking: visual('Thinking', colors.accent, 0.22),
  speaking: visual('Speaking', colors.success, 0.2),
  executing_tool: visual('Working', colors.warning, 0.18),
  reconnecting: visual('Reconnecting', colors.warning, 0.16),
  failed: visual('Failed', colors.danger, 0.2),
};

/** Fallback for unrecognised/legacy state strings. */
export const aiStateFallback: AIStateVisual = {
  label: 'Idle',
  color: '#6B7280',
  glow: 'rgba(107,114,128,0.12)',
};

export function aiStateVisualOf(state: AIState): AIStateVisual {
  return aiStates[state] ?? aiStateFallback;
}