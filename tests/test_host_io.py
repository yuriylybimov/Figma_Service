"""Host-side I/O helpers: _read_code_source and _atomic_write."""
import io
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

import run


# --- _read_code_source ---

def test_read_code_source_from_code_arg():
    assert run._read_code_source(code="return 42;", code_file=None) == "return 42;"


def test_read_code_source_from_file(tmp_path):
    p = tmp_path / "snippet.js"
    p.write_text("return 7;", encoding="utf-8")
    assert run._read_code_source(code=None, code_file=str(p)) == "return 7;"


def test_read_code_source_file_missing_raises_input_read_failed(tmp_path):
    p = tmp_path / "nope.js"
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=str(p))
    assert exc.value.kind == "input_read_failed"
    assert f"path={p}" in exc.value.detail
    assert "FileNotFoundError" in exc.value.detail


def test_read_code_source_file_is_directory_raises(tmp_path):
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=str(tmp_path))
    assert exc.value.kind == "input_read_failed"
    assert "IsADirectoryError" in exc.value.detail


def test_read_code_source_stdin_non_tty(monkeypatch):
    fake_stdin = io.StringIO("return stdin_code;")
    fake_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert run._read_code_source(code=None, code_file="-") == "return stdin_code;"


def test_read_code_source_stdin_tty_refuses(monkeypatch):
    fake_stdin = io.StringIO("ignored")
    fake_stdin.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", fake_stdin)
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file="-")
    assert exc.value.kind == "input_read_failed"
    assert "RefuseTTY" in exc.value.detail
    assert "path=-" in exc.value.detail


def test_read_code_source_both_none_raises():
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=None)
    assert exc.value.kind == "input_read_failed"


def test_read_code_source_both_set_raises():
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code="a", code_file="b")
    assert exc.value.kind == "input_read_failed"


# --- _atomic_write ---

def test_atomic_write_success(tmp_path):
    target = tmp_path / "out.json"
    run._atomic_write(target, b'{"a":1}\n')
    assert target.read_bytes() == b'{"a":1}\n'
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_atomic_write_no_tmp_leftovers(tmp_path):
    target = tmp_path / "out.json"
    run._atomic_write(target, b"hello")
    # No .<name>.<pid>.tmp files remain.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{target.name}.")]
    assert leftovers == []


def test_atomic_write_parent_missing_raises(tmp_path):
    target = tmp_path / "nonexistent" / "out.json"
    with pytest.raises(run._BridgeError) as exc:
        run._atomic_write(target, b"x")
    assert exc.value.kind == "output_write_failed"
    assert f"path={target}" in exc.value.detail
    # Stage should be one of the labeled stages.
    assert any(f"stage={s}" in exc.value.detail
               for s in ("open", "write", "fsync", "chmod", "rename"))


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "out.json"
    target.write_bytes(b"old content")
    run._atomic_write(target, b"new content")
    assert target.read_bytes() == b"new content"
