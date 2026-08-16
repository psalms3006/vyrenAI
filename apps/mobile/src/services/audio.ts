/**
 * Audio service seam — real Phase D wiring.
 *
 * When a native audio runtime is available (react-native-audio-api), this
 * module:
 *   - captures the mic as PCM16 16 kHz mono in ~50ms chunks,
 *   - plays the AI response (PCM16 24 kHz) through a queued audio graph.
 *
 * Otherwise it returns the inert handles so the UI stays fully exercisable in
 * Node/Jest and on unsupported platforms. Screens never import the SDK.
 *
 * The native module is loaded lazily (guarded `require`) so this file can be
 * imported anywhere without pulling native code into non-native tests.
 */

import { Platform } from 'react-native';
import type {
  AudioBuffer as NativeAudioBuffer,
  AudioBufferQueueSourceNode as NativeQueueSource,
  AudioContext as NativeAudioContext,
  AudioRecorder as NativeAudioRecorder,
} from 'react-native-audio-api';

export interface AudioLevel {
  /** Root-mean-square amplitude (0..1) of the current mic frame. */
  rms: number;
  /** Peak amplitude (0..1) of the current mic frame. */
  peak: number;
}

export interface MicrophoneHandle {
  start(): Promise<void>;
  stop(): void;
  /** Subscribe to per-frame levels (UI waveform). Returns unsubscribe. */
  addLevelListener(listener: (level: AudioLevel) => void): () => void;
}

export interface AudioOutputHandle {
  /** Enqueue a 24 kHz PCM16 chunk of AI speech for playback. */
  play(pcm: ArrayBuffer): void;
  clear(): void;
}

export interface MicrophoneOptions {
  /** Called with each captured PCM16 16 kHz mono chunk (~50 ms). */
  onAudio?: (pcm: ArrayBuffer) => void;
}

type AudioApiModule = typeof import('react-native-audio-api');
type OnAudioReadyEvent = Parameters<NativeAudioRecorder['onAudioReady']>[1];

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_SAMPLES = 800; // 50 ms @ 16 kHz
const PLAYBACK_SAMPLE_RATE = 24000;

const SILENCE: AudioLevel = { rms: 0, peak: 0 };

let audioApiModule: AudioApiModule | null | undefined;

function nativeAudioAvailable(): boolean {
  if (Platform.OS !== 'android' && Platform.OS !== 'ios') {
    return false;
  }
  const globalApi = globalThis as unknown as {
    createAudioContext?: unknown;
    createAudioRecorder?: unknown;
    createAudioBuffer?: unknown;
  };
  return (
    typeof globalApi.createAudioContext === 'function' &&
    typeof globalApi.createAudioRecorder === 'function' &&
    typeof globalApi.createAudioBuffer === 'function'
  );
}

function loadAudioApi(): AudioApiModule | null {
  if (audioApiModule !== undefined) {
    return audioApiModule;
  }
  try {
    audioApiModule = nativeAudioAvailable()
      ? (require('react-native-audio-api') as AudioApiModule)
      : null;
  } catch {
    audioApiModule = null;
  }
  return audioApiModule;
}

/** Nearest-sample/linear resampler — simple and cheap enough for voice. */
function resample(
  src: Float32Array,
  srcRate: number,
  dstRate: number,
): Float32Array {
  if (srcRate === dstRate || src.length === 0) {
    return new Float32Array(src);
  }
  const ratio = srcRate / dstRate;
  const outLength = Math.floor(src.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, src.length - 1);
    const frac = pos - i0;
    out[i] = src[i0] * (1 - frac) + src[i1] * frac;
  }
  return out;
}

function floatToPcm16(samples: Float32Array): Int16Array<ArrayBuffer> {
  const out = new Int16Array(new ArrayBuffer(samples.length * Int16Array.BYTES_PER_ELEMENT));
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
  }
  return out;
}

function levelsOf(samples: Float32Array): AudioLevel {
  let sum = 0;
  let peak = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const a = Math.abs(samples[i]);
    sum += a * a;
    if (a > peak) {
      peak = a;
    }
  }
  const rms = samples.length > 0 ? Math.sqrt(sum / samples.length) : 0;
  // Scale up so quiet microphones still drive the waveform visibly.
  return {
    rms: Math.min(1, rms * 4),
    peak: Math.min(1, peak * 4),
  };
}

/** Preview implementation — captures nothing, emits silence levels. */
export function createMicrophone(options?: MicrophoneOptions): MicrophoneHandle {
  const api = loadAudioApi();
  if (!api) {
    const levelListeners = new Set<(level: AudioLevel) => void>();
    return {
      async start() {},
      stop() {
        levelListeners.clear();
      },
      addLevelListener(listener) {
        levelListeners.add(listener);
        listener(SILENCE);
        return () => {
          levelListeners.delete(listener);
        };
      },
    };
  }

  let recorder: NativeAudioRecorder | null = null;
  let running = false;
  let stopped = false;
  let pending: Float32Array[] = [];
  let pendingLength = 0;
  const levelListeners = new Set<(level: AudioLevel) => void>();
  const notifyLevels = (level: AudioLevel) => {
    levelListeners.forEach((listener) => listener(level));
  };

  const flush = () => {
    if (!options?.onAudio) {
      pending = [];
      pendingLength = 0;
      return;
    }
    const out = new Float32Array(CHUNK_SAMPLES);
    while (pendingLength >= CHUNK_SAMPLES) {
      let written = 0;
      while (written < CHUNK_SAMPLES && pending.length > 0) {
        const next = pending[0];
        const take = Math.min(next.length, CHUNK_SAMPLES - written);
        out.set(next.subarray(0, take), written);
        written += take;
        if (take < next.length) {
          pending[0] = next.subarray(take);
        } else {
          pending.shift();
        }
      }
      pendingLength -= CHUNK_SAMPLES;
      notifyLevels(levelsOf(out));
      options.onAudio(floatToPcm16(out).buffer);
    }
  };

  const onChunk = (event: Parameters<OnAudioReadyEvent>[0]) => {
    if (stopped || !running || !event?.buffer) {
      return;
    }
    const buffer = event.buffer as NativeAudioBuffer;
    if (buffer.numberOfChannels < 1) {
      return;
    }
    const channel = buffer.getChannelData(0);
    if (channel.length === 0) {
      return;
    }
    const resampled = resample(channel, buffer.sampleRate, TARGET_SAMPLE_RATE);
    pending.push(resampled);
    pendingLength += resampled.length;
    flush();
  };

  return {
    async start() {
      if (running) {
        return;
      }
      const activeApi = loadAudioApi();
      if (!activeApi) {
        return;
      }
      try {
        await activeApi.AudioManager.requestRecordingPermissions();
      } catch {
        // Permission prompt failed; still attempt the recorder.
      }
      try {
        await activeApi.AudioManager.setAudioSessionActivity(true);
      } catch {
        // Session management is best-effort.
      }
      const rec = new activeApi.AudioRecorder();
      recorder = rec;
      try {
        rec.onAudioReady(
          {
            sampleRate: TARGET_SAMPLE_RATE,
            bufferLength: CHUNK_SAMPLES,
            channelCount: 1,
          },
          onChunk as OnAudioReadyEvent,
        );
      } catch {
        // Callback registration failed — no capture.
      }
      const result = await rec.start();
      running = result?.status !== 'error';
    },

    stop() {
      stopped = true;
      running = false;
      pending = [];
      pendingLength = 0;
      if (recorder) {
        try {
          recorder.clearOnAudioReady();
        } catch {
          // Ignore teardown errors.
        }
        recorder = null;
      }
      levelListeners.clear();
    },

    addLevelListener(listener) {
      levelListeners.add(listener);
      listener(SILENCE);
      return () => {
        levelListeners.delete(listener);
      };
    },
  };
}

/** Preview implementation — discards AI audio. */
export function createAudioOutput(): AudioOutputHandle {
  const api = loadAudioApi();
  if (!api) {
    return {
      play(_pcm: ArrayBuffer) {},
      clear() {},
    };
  }

  let context: NativeAudioContext | null = null;
  let queueSource: NativeQueueSource | null = null;
  let started = false;

  const ensureContext = (activeApi: AudioApiModule): boolean => {
    if (context && queueSource) {
      return true;
    }
    try {
      const ctx = new activeApi.AudioContext({
        sampleRate: PLAYBACK_SAMPLE_RATE,
      });
      const source = ctx.createBufferQueueSource();
      source.connect(ctx.destination);
      activeApi.AudioManager.setAudioSessionActivity(true).catch(() => {});
      ctx.resume().catch(() => {});
      context = ctx;
      queueSource = source;
      return true;
    } catch {
      return false;
    }
  };

  return {
    /** Enqueue a 24 kHz PCM16 chunk of AI speech for playback. */
    play(pcm: ArrayBuffer) {
      const activeApi = loadAudioApi();
      if (!activeApi || !ensureContext(activeApi) || !context || !queueSource) {
        return;
      }
      try {
        const int16 = new Int16Array(pcm);
        if (int16.length === 0) {
          return;
        }
        const f32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i += 1) {
          f32[i] = int16[i] / 32768;
        }
        const buffer = context.createBuffer(1, f32.length, PLAYBACK_SAMPLE_RATE);
        buffer.copyToChannel(f32, 0);
        queueSource.enqueueBuffer(buffer);
        if (!started) {
          queueSource.start();
          started = true;
        }
      } catch {
        // Drop a chunk on playback failure; the stream keeps going.
      }
    },

    clear() {
      if (queueSource) {
        try {
          queueSource.clearBuffers();
        } catch {
          // Ignore teardown errors.
        }
      }
    },
  };
}