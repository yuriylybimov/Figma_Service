(/*SCRIPTER*/async function __scripter_script_main(){
const RID = "__RID__";
const SP = "__SENTINEL_PREFIX__";
const SC = "__SENTINEL_CLOSING__";
const INLINE_CAP = __INLINE_CAP__;
const CHUNK = __CHUNK_B64_BYTES__;
const T0 = Date.now();

// --- Sandbox polyfills ---------------------------------------------------
// Scripter's runtime lacks TextEncoder, btoa, and crypto.subtle. We inline
// UTF-8 encoding, base64, and SHA-256 so the wrapper has no external deps.

const utf8Encode = (str) => {
  const bytes = [];
  for (let i = 0; i < str.length; i++) {
    let c = str.charCodeAt(i);
    if (c < 0x80) {
      bytes.push(c);
    } else if (c < 0x800) {
      bytes.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
    } else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
      const c2 = str.charCodeAt(i + 1);
      if (c2 >= 0xdc00 && c2 <= 0xdfff) {
        const cp = 0x10000 + ((c & 0x3ff) << 10) + (c2 & 0x3ff);
        bytes.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3f),
          0x80 | ((cp >> 6) & 0x3f),
          0x80 | (cp & 0x3f),
        );
        i++;
      } else {
        bytes.push(0xef, 0xbf, 0xbd);
      }
    } else {
      bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    }
  }
  return new Uint8Array(bytes);
};

const B64_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const b64encode = (bytes) => {
  let out = "";
  const len = bytes.length;
  let i = 0;
  while (i + 3 <= len) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    out += B64_ALPHA[(n >> 18) & 63]
         + B64_ALPHA[(n >> 12) & 63]
         + B64_ALPHA[(n >> 6) & 63]
         + B64_ALPHA[n & 63];
    i += 3;
  }
  const rem = len - i;
  if (rem === 1) {
    const n = bytes[i] << 16;
    out += B64_ALPHA[(n >> 18) & 63] + B64_ALPHA[(n >> 12) & 63] + "==";
  } else if (rem === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    out += B64_ALPHA[(n >> 18) & 63]
         + B64_ALPHA[(n >> 12) & 63]
         + B64_ALPHA[(n >> 6) & 63]
         + "=";
  }
  return out;
};

const toHex = (buf) => {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += b[i].toString(16).padStart(2, "0");
  return s;
};

const sha256 = (bytes) => {
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const H = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const L = bytes.length;
  const bitLen = L * 8;
  const totalLen = (Math.floor((L + 9 + 63) / 64)) * 64;
  const padded = new Uint8Array(totalLen);
  padded.set(bytes);
  padded[L] = 0x80;
  const hi = Math.floor(bitLen / 0x100000000);
  const lo = bitLen >>> 0;
  padded[totalLen - 8] = (hi >>> 24) & 0xff;
  padded[totalLen - 7] = (hi >>> 16) & 0xff;
  padded[totalLen - 6] = (hi >>> 8) & 0xff;
  padded[totalLen - 5] = hi & 0xff;
  padded[totalLen - 4] = (lo >>> 24) & 0xff;
  padded[totalLen - 3] = (lo >>> 16) & 0xff;
  padded[totalLen - 2] = (lo >>> 8) & 0xff;
  padded[totalLen - 1] = lo & 0xff;

  const W = new Uint32Array(64);
  const rotr = (x, n) => ((x >>> n) | (x << (32 - n))) >>> 0;
  for (let block = 0; block < totalLen; block += 64) {
    for (let t = 0; t < 16; t++) {
      const o = block + t * 4;
      W[t] = ((padded[o] << 24) | (padded[o + 1] << 16) | (padded[o + 2] << 8) | padded[o + 3]) >>> 0;
    }
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(W[t - 15], 7) ^ rotr(W[t - 15], 18) ^ (W[t - 15] >>> 3);
      const s1 = rotr(W[t - 2], 17) ^ rotr(W[t - 2], 19) ^ (W[t - 2] >>> 10);
      W[t] = (W[t - 16] + s0 + W[t - 7] + s1) >>> 0;
    }
    let a = H[0], b = H[1], c = H[2], d = H[3];
    let e = H[4], f = H[5], g = H[6], h = H[7];
    for (let t = 0; t < 64; t++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ ((~e) & g);
      const T1 = (h + S1 + ch + K[t] + W[t]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const mj = (a & b) ^ (a & c) ^ (b & c);
      const T2 = (S0 + mj) >>> 0;
      h = g; g = f; f = e;
      e = (d + T1) >>> 0;
      d = c; c = b; b = a;
      a = (T1 + T2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0;
    H[1] = (H[1] + b) >>> 0;
    H[2] = (H[2] + c) >>> 0;
    H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0;
    H[5] = (H[5] + f) >>> 0;
    H[6] = (H[6] + g) >>> 0;
    H[7] = (H[7] + h) >>> 0;
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 8; i++) {
    out[i * 4]     = (H[i] >>> 24) & 0xff;
    out[i * 4 + 1] = (H[i] >>> 16) & 0xff;
    out[i * 4 + 2] = (H[i] >>> 8) & 0xff;
    out[i * 4 + 3] = H[i] & 0xff;
  }
  return out;
};

// --- Emit ---------------------------------------------------------------

const emit = async (statusDoc) => {
  statusDoc.elapsed_ms = Date.now() - T0;
  let json;
  try {
    json = JSON.stringify(statusDoc);
  } catch (e) {
    json = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "serialize_failed",
      message: String(e && e.message || e),
      elapsed_ms: Date.now() - T0,
    });
  }
  let bytes = utf8Encode(json);

  // Payload cap check — fires before chunked transport begins.
  // UTF-8 byte count of the serialized ok status doc vs. the command's cap
  // (500 B for exec-inline; 65 536 B for exec in Phase 1.5). Err payloads bypass.
  if (bytes.byteLength > INLINE_CAP && statusDoc.status === "ok") {
    const err = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "payload_too_large",
      message: `result ${bytes.byteLength}B exceeds cap ${INLINE_CAP}B`,
      detail: `bytes=${bytes.byteLength} cap=${INLINE_CAP}`,
      elapsed_ms: Date.now() - T0,
    });
    bytes = utf8Encode(err);
  }

  const sha256Hex = toHex(sha256(bytes));
  const b64 = b64encode(bytes);
  const N = Math.max(1, Math.ceil(b64.length / CHUNK));
  const header = JSON.stringify({
    version: 2, chunks: N, bytes: bytes.byteLength,
    sha256: sha256Hex, transport: "console_log",
  });
  console.log(SP + RID + ":BEGIN:" + header + SC);
  for (let i = 0; i < N; i++) {
    const seg = b64.slice(i * CHUNK, (i + 1) * CHUNK);
    console.log(SP + RID + ":C:" + i + ":" + seg + SC);
  }
};

try {
  const R = await (async () => {
/*__USER_JS__*/
  })();
  await emit({
    status: "ok", version: 2, request_id: RID,
    result: R === undefined ? null : R,
  });
} catch (e) {
  await emit({
    status: "error", version: 2, request_id: RID,
    kind: "user_exception",
    message: String(e && e.message || e),
    detail: e && e.stack ? String(e.stack).slice(0, 2000) : null,
  });
}
})()/*SCRIPTER*/
