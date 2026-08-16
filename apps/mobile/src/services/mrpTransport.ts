/**
 * Internal MRP WebSocket transport (framing only).
 *
 * This module is deliberately NOT part of the public service seam (see
 * `services/live.ts`). It owns the wire concerns of the Mobile Realtime
 * Protocol:
 *
 *   - first-frame `init` handshake (with optional `session_id` resumption)
 *   - 15s text `ping` keep-alive
 *   - binary uplink framing: `\x00` PCM16 16kHz mic audio, `\x01` vision frame
 *   - client-side backpressure via `bufferedAmount` (drop vision first)
 *   - exponential-backoff reconnect (1s -> 60s, capped at 5 failures)
 *
 * It knows nothing about the AI state machine or the LiveSession interface —
 * both live in `services/live.ts`. The socket is injected through a factory so
 * the framing logic is testable in Node without a WebSocket implementation.
 */

export interface MrpSocket {
  binaryType: 'arraybuffer' | 'blob';
  bufferedAmount: number;
  readyState: number;
  onopen: (() => void) | null;
  onclose: ((event: { code: number; reason?: string; wasClean?: boolean }) => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: { data: string | ArrayBuffer | Blob }) => void) | null;
  send(data: string | ArrayBuffer): void;
  close(code?: number, reason?: string): void;
}

export type MrpTransportState =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'offline'
  | 'closed';

export interface MrpTransportCallbacks {
  /** Transport-level state changes (`connected` only after a full open). */
  onState(state: MrpTransportState, wasConnected: boolean): void;
  /** Every inbound text frame (including init_ack/state_change/error/...). */
  onMessage(msg: Record<string, unknown>): void;
  /** Inbound binary frame — always AI audio (PCM16 24kHz), no prefix. */
  onAudio(pcm: ArrayBuffer): void;
}

export interface MrpTransportConfig {
  /** Full `ws[s]://.../ws/live/mobile` endpoint. */
  url: string;
  /** Optional previous session id for MRP resumption. */
  sessionId?: string;
  /** Initial model requested in the init frame. */
  model?: string;
  /** Injectable socket constructor (defaults to global WebSocket). */
  socketFactory?: (url: string) => MrpSocket;
}

export const PING_INTERVAL_MS = 15000;
export const MAX_CONSECUTIVE_FAILURES = 5;
export const INITIAL_BACKOFF_MS = 1000;
export const MAX_BACKOFF_MS = 60000;
/** Redline above which audio is dropped too (network is effectively stalled). */
export const AUDIO_HIGH_WATER_BYTES = 1 << 20;
/** Vision is dropped well before that — it is the first casualty of congestion. */
export const VISION_HIGH_WATER_BYTES = 256 << 10;

export const PREFIX_AUDIO = 0x00;
export const PREFIX_VISION = 0x01;

function bufferedAmountOf(socket: MrpSocket | null): number {
  if (!socket || typeof socket.bufferedAmount !== 'number') {
    return 0;
  }
  return socket.bufferedAmount;
}

function toArrayBuffer(data: string | ArrayBuffer | Blob): ArrayBuffer {
  if (typeof data === 'string') {
    // Text frames are routed separately; this should not happen.
    throw new TypeError('Expected a binary frame.');
  }
  if (data instanceof ArrayBuffer) {
    return data;
  }
  if (ArrayBuffer.isView(data)) {
    const view = data as ArrayBufferView;
    return view.buffer.slice(
      view.byteOffset,
      view.byteOffset + view.byteLength,
    ) as ArrayBuffer;
  }
  return data as unknown as ArrayBuffer;
}

export class MrpTransport {
  private readonly config: MrpTransportConfig;
  private readonly callbacks: MrpTransportCallbacks;
  private socket: MrpSocket | null = null;
  private sessionId: string;
  private state: MrpTransportState = 'offline';
  private closedByUs = false;
  private consecutiveFailures = 0;
  private backoffMs = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  constructor(config: MrpTransportConfig, callbacks: MrpTransportCallbacks) {
    this.config = config;
    this.callbacks = callbacks;
    this.sessionId = config.sessionId || '';
  }

  getSessionId(): string {
    return this.sessionId;
  }

  isOpen(): boolean {
    return !!this.socket && this.socket.readyState === 1;
  }

  /** Open a new session (idempotent while one is in flight). */
  connect(): void {
    if (this.socket || this.reconnectTimer) {
      return;
    }
    this.closedByUs = false;
    this.open();
  }

  /** Graceful shutdown: terminate, close, and cancel any reconnect. */
  disconnect(reason = 'user_exit'): void {
    this.closedByUs = true;
    this.clearTimers();
    const socket = this.socket;
    if (socket && socket.readyState === 1) {
      try {
        socket.send(JSON.stringify({ type: 'terminate', reason }));
      } catch {
        // Ignore — closing below is what matters.
      }
    }
    if (socket) {
      try {
        socket.close(1000, 'terminate');
      } catch {
        // Ignore.
      }
    }
    this.socket = null;
    if (this.state !== 'closed') {
      this.setState('closed', false);
    }
  }

  sendText(msg: Record<string, unknown>): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== 1) {
      return false;
    }
    try {
      socket.send(JSON.stringify(msg));
      return true;
    } catch {
      return false;
    }
  }

  /** Uplink mic PCM16 16 kHz mono. Returns false when dropped (backpressure). */
  sendAudio(pcm: ArrayBuffer): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== 1) {
      return false;
    }
    if (bufferedAmountOf(socket) > AUDIO_HIGH_WATER_BYTES) {
      return false;
    }
    const body = toArrayBuffer(pcm);
    const frame = new Uint8Array(body.byteLength + 1);
    frame[0] = PREFIX_AUDIO;
    frame.set(new Uint8Array(body), 1);
    try {
      socket.send(frame.buffer);
      return true;
    } catch {
      return false;
    }
  }

  /** Uplink vision frame (JPEG/WebP/PNG bytes). Returns false when dropped. */
  sendVision(bytes: Uint8Array): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== 1) {
      return false;
    }
    if (bufferedAmountOf(socket) > VISION_HIGH_WATER_BYTES) {
      return false;
    }
    if (bytes.byteLength <= 0) {
      return false;
    }
    const frame = new Uint8Array(bytes.byteLength + 1);
    frame[0] = PREFIX_VISION;
    frame.set(bytes, 1);
    try {
      socket.send(frame.buffer);
      return true;
    } catch {
      return false;
    }
  }

  // --------------------------------------------------------------------
  // Internals
  // --------------------------------------------------------------------

  private open(): void {
    const factory =
      this.config.socketFactory ??
      ((url: string) => {
        if (typeof WebSocket === 'undefined') {
          throw new Error('WebSocket is not available in this environment.');
        }
        return new WebSocket(url) as unknown as MrpSocket;
      });

    let socket: MrpSocket;
    try {
      socket = factory(this.config.url);
    } catch {
      this.consecutiveFailures += 1;
      if (this.consecutiveFailures > MAX_CONSECUTIVE_FAILURES) {
        this.setState('offline', this.state === 'connected');
        return;
      }
      // Synchronous factory failure counts as an attempt: schedule a retry.
      this.setState('reconnecting', this.state === 'connected');
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => this.handleOpen();
    socket.onmessage = (event) => this.handleMessage(event.data);
    socket.onerror = () => {};
    socket.onclose = (event) => this.handleClose(event);
    this.setState('connecting', false);
  }

  private handleOpen(): void {
    // First frame MUST be an init (per runtime/mobile_live.py).
    this.sendText({
      type: 'init',
      client: 'mobile',
      version: '1.0',
      session_id: this.sessionId,
      model: this.config.model,
    });
    this.setState('connected', false);
    this.clearTimers();
    this.pingTimer = setInterval(() => {
      if (this.isOpen()) {
        this.sendText({ type: 'ping' });
      }
    }, PING_INTERVAL_MS);
  }

  private handleMessage(data: string | ArrayBuffer | Blob): void {
    if (typeof data === 'string') {
      let msg: unknown;
      try {
        msg = JSON.parse(data);
      } catch {
        return;
      }
      if (msg && typeof msg === 'object') {
        this.callbacks.onMessage(msg as Record<string, unknown>);
      }
      return;
    }
    if (
      typeof Blob !== 'undefined' &&
      typeof FileReader === 'function' &&
      data instanceof Blob
    ) {
      const reader = new FileReader();
      reader.onload = () => {
        this.callbacks.onAudio(reader.result as ArrayBuffer);
      };
      reader.readAsArrayBuffer(data);
      return;
    }
    try {
      this.callbacks.onAudio(toArrayBuffer(data));
    } catch {
      // Drop malformed binary frames.
    }
  }

  private handleClose(
    _event: { code: number; reason?: string; wasClean?: boolean },
  ): void {
    this.clearTimers();
    this.socket = null;
    const wasConnected = this.state === 'connected' || this.state === 'reconnecting';
    if (this.closedByUs) {
      this.setState('closed', false);
      return;
    }
    this.consecutiveFailures += 1;
    if (this.consecutiveFailures > MAX_CONSECUTIVE_FAILURES) {
      this.setState('offline', wasConnected);
      return;
    }
    this.setState('reconnecting', wasConnected);
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closedByUs) {
      return;
    }
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.closedByUs) {
        return;
      }
      this.open();
    }, delay);
  }

  private setState(state: MrpTransportState, wasConnected: boolean): void {
    if (this.state === state) {
      return;
    }
    this.state = state;
    this.callbacks.onState(state, wasConnected);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}