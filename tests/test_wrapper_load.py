"""Verify the wrapper loads from wrapper.js and _wrap_exec substitutes markers."""
import run


def test_wrapper_template_loaded_from_file():
    # Template is loaded at import; must contain the expected markers.
    assert "__SENTINEL__" in run._WRAPPER_TEMPLATE
    assert "__CLOSING__" in run._WRAPPER_TEMPLATE
    assert "__CAP__" in run._WRAPPER_TEMPLATE
    assert "/*__USER_JS__*/" in run._WRAPPER_TEMPLATE


def test_wrap_exec_substitutes_all_markers():
    out = run._wrap_exec("return 42;")
    assert "__SENTINEL__" not in out
    assert "__CLOSING__" not in out
    assert "__CAP__" not in out
    assert "/*__USER_JS__*/" not in out
    assert "return 42;" in out
    assert run.SENTINEL in out
    assert run.CLOSING in out
    assert str(run.PAYLOAD_CAP_BYTES) in out
