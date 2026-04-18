"""Host-side I/O: logging, code-source resolution, atomic writes.

Touches the filesystem and stdio. Depends only on the protocol layer for
`_BridgeError` (so failures surface with a known `kind`).
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from protocol import _BridgeError


_QUIET = False


def set_quiet(value: bool) -> None:
    """Toggle the module-level QUIET flag used by `_log`."""
    global _QUIET
    _QUIET = value


def _log(level: str, msg: str) -> None:
    if _QUIET and level != "error":
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def _trim(s: str | None, n: int = 2000) -> str | None:
    """Cap detail strings to match the JS wrapper's own 2KB stack slice."""
    if s is None:
        return None
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n}B truncated)"


def _read_code_source(code: str | None, code_file: str | None) -> str:
    """Resolve --code / --code-file into a JS string. Raises _BridgeError on failure."""
    if (code is None) == (code_file is None):
        # Both None or both set — misuse.
        _log("error", "stage=hostio kind=input_read_failed reason=both_or_neither_of_--code/--code-file")
        raise _BridgeError(
            "input_read_failed",
            "exactly one of --code or --code-file is required",
            detail="path=<none> error=ArgError: exactly one of --code/--code-file must be set",
        )
    if code is not None:
        return code
    # code_file branch
    if code_file == "-":
        if sys.stdin.isatty():
            _log("error", "stage=hostio kind=input_read_failed reason=tty_stdin")
            raise _BridgeError(
                "input_read_failed",
                "refusing to read code from interactive TTY",
                detail="path=- error=RefuseTTY: refusing to read code from interactive TTY; pipe input or use --code",
            )
        try:
            return sys.stdin.read()
        except Exception as e:
            _log("error", f"stage=hostio kind=input_read_failed path=- error={type(e).__name__}")
            raise _BridgeError(
                "input_read_failed",
                f"stdin read failed: {e}",
                detail=f"path=- error={type(e).__name__}: {e}",
            ) from e
    try:
        return Path(code_file).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
        _log("error", f"stage=hostio kind=input_read_failed path={code_file} error={type(e).__name__}")
        raise _BridgeError(
            "input_read_failed",
            f"cannot read --code-file: {e}",
            detail=f"path={code_file} error={type(e).__name__}: {e}",
        ) from e


def _atomic_write(path: Path, payload: bytes) -> None:
    """Atomic, mode-0o600 write. Raises _BridgeError(kind='output_write_failed') on any stage failure."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    stage = "open"
    try:
        with open(tmp, "wb") as f:
            stage = "write"
            f.write(payload)
            stage = "fsync"
            f.flush()
            os.fsync(f.fileno())
        stage = "chmod"
        os.chmod(tmp, 0o600)
        stage = "rename"
        os.replace(tmp, path)
    except Exception as e:
        # Clean up any partial tmp so we don't leak it.
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        _log("error",
             f"stage=hostio kind=output_write_failed path={path} "
             f"inner_stage={stage} error={type(e).__name__}")
        raise _BridgeError(
            "output_write_failed",
            f"atomic write failed at stage {stage}: {e}",
            detail=f"path={path} stage={stage} error={type(e).__name__}: {e}",
        ) from e
