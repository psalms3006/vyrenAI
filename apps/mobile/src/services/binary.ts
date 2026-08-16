/**
 * Binary <-> base64 helpers for the MRP transport.
 *
 * React Native (non-Hermes-safe) environments don't reliably expose a
 * Buffer, so these are implemented with pure JavaScript. Used by:
 *   - camera/photo capture  -> base64 uplink frames (WebSocket \x01 prefix)
 *   - MRP transport         -> decode base64 frames before prefixing
 */

const ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function bytesToBase64(input: ArrayBuffer | Uint8Array): string {
  const bytes =
    input instanceof Uint8Array ? input : new Uint8Array(input);
  let result = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const triplet = (b0 << 16) | (b1 << 8) | b2;
    result += ALPHABET[(triplet >> 18) & 0x3f];
    result += ALPHABET[(triplet >> 12) & 0x3f];
    result += ALPHABET[(triplet >> 6) & 0x3f];
    result += ALPHABET[triplet & 0x3f];
  }
  const remainder = bytes.length % 3;
  if (remainder === 1) {
    result = result.slice(0, -2) + '==';
  } else if (remainder === 2) {
    result = result.slice(0, -1) + '=';
  }
  return result;
}

const REVERSE: Record<string, number> = (() => {
  const map: Record<string, number> = {};
  for (let i = 0; i < ALPHABET.length; i += 1) {
    map[ALPHABET[i]] = i;
  }
  return map;
})();

export function base64ToBytes(input: string): Uint8Array | null {
  const clean = input.replace(/[^A-Za-z0-9+/]/g, '');
  if (clean.length === 0) {
    return null;
  }
  const length = (clean.length * 3) / 4;
  const padded = clean.length % 4 === 0 ? clean : clean + '='.repeat(4 - (clean.length % 4));
  const out = new Uint8Array(Math.floor(length));
  let outIndex = 0;
  let buffer = 0;
  let bits = 0;
  for (let i = 0; i < padded.length; i += 1) {
    const value = REVERSE[padded[i]];
    if (value === undefined) {
      continue;
    }
    buffer = (buffer << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (outIndex < out.length) {
        out[outIndex] = (buffer >> bits) & 0xff;
        outIndex += 1;
      }
    }
  }
  return out.subarray(0, outIndex);
}