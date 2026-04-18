"""Protocol v2 Pydantic model invariants."""
import pytest
from pydantic import TypeAdapter, ValidationError

import run


def test_protocol_version_is_2():
    assert run.PROTOCOL_VERSION == 2


def test_exec_ok_inline_defaults_and_required_fields():
    m = run.ExecOkInline(request_id="abc123", result=42, elapsed_ms=10)
    assert m.status == "ok"
    assert m.mode == "inline"
    assert m.version == 2
    assert m.result == 42
    assert m.logs == []


def test_exec_ok_inline_rejects_missing_result():
    # result is required (Any, but must be present)
    with pytest.raises(ValidationError):
        run.ExecOkInline(request_id="abc", elapsed_ms=1)


def test_exec_ok_file_required_fields():
    m = run.ExecOkFile(
        request_id="abc", result_path="/tmp/r.json",
        bytes=10, sha256="a"*64, elapsed_ms=5,
    )
    assert m.mode == "file"
    assert m.bytes == 10
    assert m.sha256 == "a"*64


def test_exec_ok_file_rejects_missing_sha256():
    with pytest.raises(ValidationError):
        run.ExecOkFile(
            request_id="abc", result_path="/tmp/r.json",
            bytes=10, elapsed_ms=5,
        )


def test_discriminated_union_routes_by_mode():
    adapter = TypeAdapter(run.ExecOk)
    inline = adapter.validate_python({
        "status": "ok", "mode": "inline", "version": 2,
        "request_id": "abc", "result": 42, "elapsed_ms": 1,
    })
    assert isinstance(inline, run.ExecOkInline)

    file_m = adapter.validate_python({
        "status": "ok", "mode": "file", "version": 2,
        "request_id": "abc", "result_path": "/tmp/r.json",
        "bytes": 10, "sha256": "a"*64, "elapsed_ms": 1,
    })
    assert isinstance(file_m, run.ExecOkFile)


def test_exec_err_accepts_all_v2_kinds():
    for kind in [
        "user_exception", "payload_too_large", "serialize_failed",
        "timeout", "injection_failed", "scripter_unreachable",
        "chunk_incomplete", "chunk_corrupt",
        "input_read_failed", "output_write_failed",
    ]:
        m = run.ExecErr(kind=kind, message="x")
        assert m.kind == kind
        assert m.version == 2


def test_exec_err_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        run.ExecErr(kind="not_a_real_kind", message="x")


def test_exec_err_request_id_optional():
    m = run.ExecErr(kind="timeout", message="x")
    assert m.request_id is None
    m2 = run.ExecErr(kind="timeout", message="x", request_id="abc")
    assert m2.request_id == "abc"
