"""Verify the wrapper loads from wrapper.js and _wrap_exec substitutes v2 markers."""
from pathlib import Path

import run


def test_wrapper_template_loaded_from_file():
    assert "__RID__" in run._WRAPPER_TEMPLATE
    assert "__INLINE_CAP__" in run._WRAPPER_TEMPLATE
    assert "__SENTINEL_PREFIX__" in run._WRAPPER_TEMPLATE
    assert "__SENTINEL_CLOSING__" in run._WRAPPER_TEMPLATE
    assert "__CHUNK_B64_BYTES__" in run._WRAPPER_TEMPLATE
    assert "/*__USER_JS__*/" in run._WRAPPER_TEMPLATE


def test_wrap_exec_substitutes_all_markers():
    out = run._wrap_exec("return 42;", rid="abcdef0123456789", inline_cap=500)
    assert "__RID__" not in out
    assert "__INLINE_CAP__" not in out
    assert "__SENTINEL_PREFIX__" not in out
    assert "__SENTINEL_CLOSING__" not in out
    assert "__CHUNK_B64_BYTES__" not in out
    assert "/*__USER_JS__*/" not in out
    assert "return 42;" in out
    assert "abcdef0123456789" in out
    assert "__FS::" in out
    assert "::SF__" in out


def test_wrap_exec_inline_cap_is_substituted():
    inline = run._wrap_exec("return 1;", rid="a"*16, inline_cap=500)
    assert "500" in inline
    exec_mode = run._wrap_exec("return 1;", rid="a"*16, inline_cap=float("inf"))
    # Python's float('inf') stringifies as 'inf'; wrapper accepts Infinity.
    # We substitute the token "Infinity" for any non-finite cap.
    assert "Infinity" in exec_mode


def test_wrapper_does_not_use_figma_notify():
    """Channel regression guard: wrapper must emit via console.log, not toasts."""
    assert "figma.notify(" not in run._WRAPPER_TEMPLATE
    assert "console.log(" in run._WRAPPER_TEMPLATE


def test_transport_has_no_hardcoded_sentinel_literals():
    """Sentinel-consistency guard: `__FS::` / `::SF__` must live in protocol.py only."""
    transport_src = (Path(run.__file__).parent / "transport.py").read_text(encoding="utf-8")
    # Strip comments and docstrings before scanning — they're allowed to mention
    # the sentinels for human readers without constituting a duplicated spelling.
    lines = [
        line for line in transport_src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    # Drop triple-quoted docstrings and double-quoted strings that only contain
    # the literal as documentation isn't enough: the concern is *runtime* use.
    # Pragmatic check: no literal `"__FS::"` or `"::SF__"` as Python strings.
    code_only = "\n".join(lines)
    assert '"__FS::"' not in code_only
    assert '"::SF__"' not in code_only
    assert "'__FS::'" not in code_only
    assert "'::SF__'" not in code_only
