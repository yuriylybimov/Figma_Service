(/*SCRIPTER*/async function __scripter_script_main(){
const RID = "__RID__";
const SP = "__SENTINEL_PREFIX__";
const SC = "__SENTINEL_CLOSING__";
const INLINE_CAP = __INLINE_CAP__;
const CHUNK = __CHUNK_B64_BYTES__;
const T0 = Date.now();

const toHex = (buf) => {
  const b = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += b[i].toString(16).padStart(2, "0");
  return s;
};

const b64encode = (bytes) => {
  // Chunk-wise to avoid stack overflow on large Uint8Arrays.
  let out = "";
  const STEP = 0x8000;
  for (let i = 0; i < bytes.length; i += STEP) {
    out += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP));
  }
  return btoa(out);
};

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
  let bytes = new TextEncoder().encode(json);

  // Inline cap check — only for the initial ok payload, matching v1 semantics.
  if (bytes.byteLength > INLINE_CAP && statusDoc.status === "ok") {
    const err = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "payload_too_large",
      message: `result ${bytes.byteLength}B exceeds cap ${INLINE_CAP}B`,
      elapsed_ms: Date.now() - T0,
    });
    bytes = new TextEncoder().encode(err);
  }

  // sha256 of the wire payload (transport integrity).
  let sha256Hex = "";
  try {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    sha256Hex = toHex(digest);
  } catch (e) {
    // crypto.subtle missing — emit injection_failed immediately, single-chunk.
    const errJson = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "injection_failed",
      message: "crypto.subtle.digest unavailable in sandbox",
      detail: String(e && e.message || e),
      elapsed_ms: Date.now() - T0,
    });
    const errBytes = new TextEncoder().encode(errJson);
    const errB64 = b64encode(errBytes);
    const header = JSON.stringify({
      version: 2, chunks: 1, bytes: errBytes.byteLength,
      sha256: "0".repeat(64), transport: "chunked_toast",
    });
    figma.notify(SP + RID + ":BEGIN:" + header + SC);
    figma.notify(SP + RID + ":C:0:" + errB64 + SC);
    return;
  }

  const b64 = b64encode(bytes);
  const N = Math.max(1, Math.ceil(b64.length / CHUNK));
  const header = JSON.stringify({
    version: 2, chunks: N, bytes: bytes.byteLength,
    sha256: sha256Hex, transport: "chunked_toast",
  });
  figma.notify(SP + RID + ":BEGIN:" + header + SC);
  for (let i = 0; i < N; i++) {
    const seg = b64.slice(i * CHUNK, (i + 1) * CHUNK);
    figma.notify(SP + RID + ":C:" + i + ":" + seg + SC);
    // Yield to the event loop so Figma's UI can process each notify before the next.
    await new Promise((r) => setTimeout(r, 0));
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
