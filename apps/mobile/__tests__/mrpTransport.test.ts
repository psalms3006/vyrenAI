/**
 * Unit tests for the MRP transport framing/handshake/reconnect logic.
 * Uses a fake socket so nothing here touches real network or native code.
 */

import {
  AUDIO_HIGH_WATER_BYTES,
  INITIAL_BACKOFF_MS,
  MAX_BACKOFF_MS,
  MAX_CONSECUTIVE_FAILURES,
  PING_INTERVAL_MS,
  PREFIX_AUDIO,
  PREFIX_VISION,
  VISION_HIGH_WATER_BYTES,
  MrpTransport,
  type MrpSocket,
} from '../src/services/mrpTransport';

type RawEvent =
  | { kind: 'open' }
  | { kind: 'close'; code: number; reason?: string; wasClean?: boolean }
  | { kind: 'message'; data: string | ArrayBuffer | Blob };

class FakeSocket implements MrpSocket {
  binaryType: 'arraybuffer' | 'blob' = 'arraybuffer';
  bufferedAmount = 0;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason?: string; wasClean?: boolean }) => void) | null =
    null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer | Blob }) => void) | null = null;

  sent: (string | ArrayBuffer)[] = [];
  closedWith: { code?: number; reason?: string } | null = null;

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }

  close(code = 1000, reason = ''): void {
    this.closedWith = { code, reason };
    this.readyState = 3;
    this.onclose?.({ code, reason, wasClean: true });
  }

  /** Test driver: raise handshake/message events. */
  drive(event: RawEvent): void {
    if (event.kind === 'open') {
      this.readyState = 1;
      this.onopen?.();
    } else if (event.kind === 'close') {
      this.readyState = 3;
      this.onclose?.({ code: event.code, reason: event.reason, wasClean: event.wasClean });
    } else {
      this.onmessage?.({ data: event.data });
    }
  }
}

function setup() {
  jest.useFakeTimers();
  const created: FakeSocket[] = [];
  const states: string[] = [];
  const texts: Record<string, unknown>[] = [];
  const audio: ArrayBuffer[] = [];
  const factory = (url: string) => {
    expect(url).toBe(EXPECTED_URL);
    const socket = new FakeSocket();
    created.push(socket);
    return socket;
  };
  const transport = new MrpTransport(
    { url: EXPECTED_URL, model: 'gemini-3.1-flash-live-preview', socketFactory: factory },
    {
      onState: (state, wasConnected) => {
        states.push(`${state}:${wasConnected}`);
      },
      onMessage: (msg) => texts.push(msg),
      onAudio: (pcm) => audio.push(pcm),
    },
  );
  return { transport, created, states, texts, audio, factory };
}

const EXPECTED_URL = 'ws://host:8420/ws/live/mobile';

afterEach(() => {
  jest.useRealTimers();
});

function firstText(socket: FakeSocket): Record<string, unknown> {
  const sent = socket.sent[0];
  expect(typeof sent).toBe('string');
  return JSON.parse(sent as string) as Record<string, unknown>;
}

describe('MrpTransport', () => {
  it('performs the init handshake and reports connected', () => {
    const { transport, created, states } = setup();
    transport.connect();
    const socket = created[0];
    expect(socket).toBeDefined();
    expect(socket.binaryType).toBe('arraybuffer');
    expect(states).toContain('connecting:false');

    socket.drive({ kind: 'open' });
    const init = firstText(socket);
    expect(init).toEqual({
      type: 'init',
      client: 'mobile',
      version: '1.0',
      session_id: '',
      model: 'gemini-3.1-flash-live-preview',
    });
    expect(states).toContain('connected:false');
    expect(transport.isOpen()).toBe(true);
  });

  it('pings every 15 seconds while open', () => {
    const { transport, created } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });
    socket.sent.length = 0;

    jest.advanceTimersByTime(PING_INTERVAL_MS);
    expect(JSON.parse(socket.sent[0] as string)).toEqual({ type: 'ping' });
    jest.advanceTimersByTime(PING_INTERVAL_MS);
    expect(socket.sent.length).toBe(2);
  });

  it('frames uplink audio with \\x00 and vision with \\x01', () => {
    const { transport, created } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });
    socket.sent.length = 0;

    const audioBytes = new ArrayBuffer(4);
    new Uint8Array(audioBytes).set([1, 2, 3, 4]);
    expect(transport.sendAudio(audioBytes)).toBe(true);
    const audioFrame = new Uint8Array(socket.sent[0] as ArrayBuffer);
    expect(audioFrame[0]).toBe(PREFIX_AUDIO);
    expect(Array.from(audioFrame.subarray(1))).toEqual([1, 2, 3, 4]);

    const visionBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0]);
    expect(transport.sendVision(visionBytes)).toBe(true);
    const visionFrame = new Uint8Array(socket.sent[1] as ArrayBuffer);
    expect(visionFrame[0]).toBe(PREFIX_VISION);
    expect(Array.from(visionFrame.subarray(1))).toEqual([0xff, 0xd8, 0xff, 0xe0]);
  });

  it('drops vision under backpressure before audio', () => {
    const { transport, created } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });

    socket.bufferedAmount = VISION_HIGH_WATER_BYTES + 1;
    expect(transport.sendVision(new Uint8Array([1]))).toBe(false);

    socket.bufferedAmount = AUDIO_HIGH_WATER_BYTES + 1;
    expect(transport.sendAudio(new ArrayBuffer(2))).toBe(false);

    socket.bufferedAmount = VISION_HIGH_WATER_BYTES - 1;
    expect(transport.sendVision(new Uint8Array([1]))).toBe(true);
    socket.bufferedAmount = AUDIO_HIGH_WATER_BYTES - 1;
    expect(transport.sendAudio(new ArrayBuffer(2))).toBe(true);
  });

  it('rejects malformed vision payloads', () => {
    const { transport, created } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });
    expect(transport.sendVision(new Uint8Array(0))).toBe(false);
  });

  it('routes inbound text to onMessage and binary to onAudio', () => {
    const { transport, created, texts, audio } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });

    socket.drive({ kind: 'message', data: '{"type":"init_ack","model":"m1"}' });
    expect(texts).toEqual([{ type: 'init_ack', model: 'm1' }]);

    const pcm = new Uint8Array([9, 9, 9]).buffer;
    socket.drive({ kind: 'message', data: pcm });
    expect(audio).toHaveLength(1);
    expect(new Uint8Array(audio[0])).toEqual(new Uint8Array([9, 9, 9]));
  });

  it('reconnects with exponential backoff and goes offline after the cap', () => {
    const { transport, created, states } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });

    socket.drive({ kind: 'close', code: 1006, wasClean: false });
    expect(states).toContain('reconnecting:true');

    let linked: FakeSocket = socket;
    for (let failure = 1; failure <= MAX_CONSECUTIVE_FAILURES; failure += 1) {
      jest.advanceTimersByTime(INITIAL_BACKOFF_MS * 2 ** (failure - 1));
      linked = created[created.length - 1];
      expect(linked).not.toBe(socket);
      linked.drive({ kind: 'open' });
      linked.drive({ kind: 'close', code: 1006, wasClean: false });
    }
    // The (max+1)-th failure flips the transport to offline.
    expect(states).toContain('offline:true');
    expect(transport.isOpen()).toBe(false);
  });

  it('graceful disconnect sends terminate and closes without reconnect', () => {
    const { transport, created, states } = setup();
    transport.connect();
    const socket = created[0];
    socket.drive({ kind: 'open' });
    socket.sent.length = 0;

    transport.disconnect('user_exit');
    expect(JSON.parse(socket.sent[0] as string)).toEqual({
      type: 'terminate',
      reason: 'user_exit',
    });
    expect(socket.closedWith?.code).toBe(1000);
    expect(states).toContain('closed:false');
  });

  it('sync factory failure retries then falls to offline', () => {
    jest.useFakeTimers();
    const states: string[] = [];
    let calls = 0;
    const transport = new MrpTransport(
      { url: EXPECTED_URL, socketFactory: () => {
        calls += 1;
        throw new Error('no websocket here');
      } },
      { onState: (state) => states.push(state), onMessage: () => {}, onAudio: () => {} },
    );

    transport.connect();
    expect(states).toContain('reconnecting');
    for (let attempt = 1; attempt <= MAX_CONSECUTIVE_FAILURES; attempt += 1) {
      jest.advanceTimersByTime(MAX_BACKOFF_MS);
    }
    expect(states).toContain('offline');
    expect(transport.isOpen()).toBe(false);
    // connect() attempt #1 + one retry per backoff tick = the full cap.
    expect(calls).toBe(MAX_CONSECUTIVE_FAILURES + 1);
  });
});