"""Pure reassembly: sentinel list + rid -> decoded wrapper status doc."""
import base64
import hashlib
import json

import pytest

import run


def _build_sentinels(rid: str, payload: dict, chunk_size: int = 2048) -> list[str]:
    """Mirror the wrapper's emission for unit testing."""
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    b64 = base64.b64encode(data).decode("ascii")
    n = max(1, (len(b64) + chunk_size - 1) // chunk_size)
    prefix = f"__FS::{rid}:"
    closing = "::SF__"
    header = json.dumps({
        "version": 2, "chunks": n, "bytes": len(data),
        "sha256": sha, "transport": "chunked_toast",
    }, separators=(",", ":"))
    sentinels = [prefix + "BEGIN:" + header + closing]
    for i in range(n):
        seg = b64[i * chunk_size:(i + 1) * chunk_size]
        sentinels.append(prefix + f"C:{i}:" + seg + closing)
    return sentinels


def test_reassemble_round_trip_small():
    rid = "a" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": 42, "elapsed_ms": 5}
    sentinels = _build_sentinels(rid, payload)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_ignores_other_rids():
    rid = "a" * 16
    other = "b" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "mine", "elapsed_ms": 1}
    sentinels = _build_sentinels(other, {"status": "ok", "version": 2,
                                         "request_id": other, "result": "stale",
                                         "elapsed_ms": 0})
    sentinels += _build_sentinels(rid, payload)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_large_payload():
    rid = "c" * 16
    big = "x" * 50_000  # many chunks
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": big, "elapsed_ms": 100}
    sentinels = _build_sentinels(rid, payload, chunk_size=2048)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_chunk_incomplete():
    rid = "d" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "x" * 10_000, "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload, chunk_size=2048)
    # Drop chunk index 2 (any middle chunk).
    sentinels = [s for s in sentinels if f":C:2:" not in s]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_incomplete"
    assert "missing=2" in exc.value.detail


def test_reassemble_missing_begin():
    rid = "e" * 16
    # No BEGIN; just chunks (shouldn't happen in practice, but must fail cleanly).
    sentinels = [f"__FS::{rid}:C:0:abc::SF__"]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    # No BEGIN means we can't know expected count; surface as chunk_incomplete
    # with a distinguishing detail.
    assert exc.value.kind == "chunk_incomplete"
    assert "stage=no_begin" in exc.value.detail or "missing=begin" in exc.value.detail


def test_reassemble_b64_decode_error():
    rid = "f" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": 1, "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Corrupt chunk 0 with illegal base64.
    sentinels[1] = f"__FS::{rid}:C:0:!!!not-base64!!!::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=b64_decode" in exc.value.detail


def test_reassemble_length_mismatch():
    rid = "g" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "abc", "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Rewrite BEGIN to claim a wrong byte count.
    header_sentinel = sentinels[0]
    header_json = header_sentinel.split(":BEGIN:", 1)[1].rsplit("::SF__", 1)[0]
    data = json.loads(header_json)
    data["bytes"] = 9999
    bad = json.dumps(data, separators=(",", ":"))
    sentinels[0] = f"__FS::{rid}:BEGIN:" + bad + "::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=length_mismatch" in exc.value.detail


def test_reassemble_sha256_mismatch():
    rid = "h" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "abc", "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Rewrite BEGIN with a bogus sha256 of the same length (64 hex chars).
    header_json = sentinels[0].split(":BEGIN:", 1)[1].rsplit("::SF__", 1)[0]
    data = json.loads(header_json)
    data["sha256"] = "0" * 64
    bad = json.dumps(data, separators=(",", ":"))
    sentinels[0] = f"__FS::{rid}:BEGIN:" + bad + "::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=sha256_mismatch" in exc.value.detail


def test_reassemble_json_parse_error():
    rid = "i" * 16
    # Build sentinels where the payload is not valid JSON.
    raw = b"not valid json at all"
    sha = hashlib.sha256(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")
    header = json.dumps({"version": 2, "chunks": 1, "bytes": len(raw),
                         "sha256": sha, "transport": "chunked_toast"},
                        separators=(",", ":"))
    sentinels = [
        f"__FS::{rid}:BEGIN:" + header + "::SF__",
        f"__FS::{rid}:C:0:" + b64 + "::SF__",
    ]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=json_parse" in exc.value.detail
