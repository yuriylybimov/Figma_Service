"""v2 wire format: sentinels, caps, Pydantic status docs, chunk reassembly.

No I/O, no Playwright — pure marshaling. Used by the transport layer and the
command handlers. Every `_BridgeError` surfaces with a `kind` drawn from the
ExecErr enum so callers can build a valid status doc without guessing.
"""

import base64
import hashlib
import json
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


PROTOCOL_VERSION = 2
SENTINEL_PREFIX = "__FS::"
SENTINEL_CLOSING = "::SF__"
INLINE_CAP_BYTES = 500      # exec-inline hard cap (UTF-8 bytes of the full status doc)
EXEC_CAP_BYTES = 65536      # exec hard cap (Phase 1.5 — chunked console-log reliability ceiling)
CHUNK_B64_BYTES = 32768     # 32 KB base64 per C:<i> console-log line


class ExecOkInline(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["inline"] = "inline"
    version: int = PROTOCOL_VERSION
    request_id: str
    result: Any
    elapsed_ms: int
    logs: list[str] = Field(default_factory=list)


class ExecOkFile(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["file"] = "file"
    version: int = PROTOCOL_VERSION
    request_id: str
    result_path: str
    bytes: int
    sha256: str
    elapsed_ms: int
    logs: list[str] = Field(default_factory=list)


ExecOk = Annotated[Union[ExecOkInline, ExecOkFile], Field(discriminator="mode")]


class ExecErr(BaseModel):
    status: Literal["error"] = "error"
    version: int = PROTOCOL_VERSION
    request_id: str | None = None
    kind: Literal[
        "user_exception", "payload_too_large", "serialize_failed",
        "timeout", "injection_failed", "scripter_unreachable",
        "chunk_incomplete", "chunk_corrupt",
        "input_read_failed", "output_write_failed",
    ]
    message: str
    detail: str | None = None
    elapsed_ms: int | None = None


class _BridgeError(Exception):
    def __init__(self, kind: str, message: str, detail: str | None = None) -> None:
        self.kind, self.message, self.detail = kind, message, detail


_SP = re.escape(SENTINEL_PREFIX)
_SC = re.escape(SENTINEL_CLOSING)
_BEGIN_RE = re.compile(rf"{_SP}([0-9a-zA-Z]+):BEGIN:(\{{.*?\}}){_SC}")
_CHUNK_RE = re.compile(rf"{_SP}([0-9a-zA-Z]+):C:(\d+):(.*?){_SC}")


def _reassemble_chunks(sentinels: list[str], rid: str) -> dict:
    """Parse a list of sentinel strings for a given rid; return decoded status doc.

    Raises _BridgeError with kind='chunk_incomplete' or 'chunk_corrupt'.
    """
    # 1. Find BEGIN for this rid (most recent wins).
    header: dict | None = None
    for s in sentinels:
        m = _BEGIN_RE.search(s)
        if m and m.group(1) == rid:
            try:
                header = json.loads(m.group(2))
            except json.JSONDecodeError as e:
                raise _BridgeError(
                    "chunk_corrupt",
                    f"BEGIN header not JSON: {e}",
                    detail=f"stage=json_parse bytes_got=0 bytes_want=0",
                ) from e
    if header is None:
        raise _BridgeError(
            "chunk_incomplete",
            "no BEGIN sentinel seen for request_id",
            detail=f"stage=no_begin got=0 expected=? missing=begin",
        )

    expected_n = int(header["chunks"])
    expected_bytes = int(header["bytes"])
    expected_sha = str(header["sha256"])

    # 2. Collect chunks for this rid.
    chunks: dict[int, str] = {}
    for s in sentinels:
        m = _CHUNK_RE.search(s)
        if m and m.group(1) == rid:
            idx = int(m.group(2))
            chunks[idx] = m.group(3)

    missing = [i for i in range(expected_n) if i not in chunks]
    if missing:
        sample = ",".join(str(i) for i in missing[:10])
        if len(missing) > 10:
            sample += f",…(+{len(missing) - 10})"
        raise _BridgeError(
            "chunk_incomplete",
            f"missing {len(missing)}/{expected_n} chunks",
            detail=f"got={len(chunks)} expected={expected_n} missing={sample}",
        )

    # 3. Reassemble in order.
    b64 = "".join(chunks[i] for i in range(expected_n))
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:
        raise _BridgeError(
            "chunk_corrupt",
            f"base64 decode failed: {e}",
            detail=f"stage=b64_decode",
        ) from e

    if len(raw) != expected_bytes:
        raise _BridgeError(
            "chunk_corrupt",
            f"reassembled length {len(raw)} != header.bytes {expected_bytes}",
            detail=f"stage=length_mismatch bytes_got={len(raw)} bytes_want={expected_bytes}",
        )

    got_sha = hashlib.sha256(raw).hexdigest()
    if got_sha != expected_sha:
        raise _BridgeError(
            "chunk_corrupt",
            "sha256 mismatch",
            detail=f"stage=sha256_mismatch sha256_got={got_sha} sha256_want={expected_sha}",
        )

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _BridgeError(
            "chunk_corrupt",
            f"payload not JSON: {e}",
            detail=f"stage=json_parse bytes_got={len(raw)} bytes_want={expected_bytes}",
        ) from e
