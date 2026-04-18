"""Verify the wrapper loads from wrapper.js and _wrap_exec substitutes v2 markers."""
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
