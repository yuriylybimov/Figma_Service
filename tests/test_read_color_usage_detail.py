"""Unit tests for read color-usage-detail — JS template structure and handler registration.

All tests are fully offline (no Playwright, no Figma connection).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_SCRIPT_DIR = Path(__file__).parent.parent / "scripts" / "variables"
_SCRIPT_PATH = _SCRIPT_DIR / "read_color_usage_detail.js"


# ---------------------------------------------------------------------------
# JS template — static structure checks (offline)
# ---------------------------------------------------------------------------

class TestJsTemplateExists:
    def test_script_file_exists(self):
        assert _SCRIPT_PATH.exists(), f"Missing: {_SCRIPT_PATH}"

    def test_script_is_non_empty(self):
        assert _SCRIPT_PATH.stat().st_size > 0


class TestJsTemplateReturnsRequiredFields:
    """The returned object must include all fields defined in the output contract."""

    @pytest.fixture(scope="class")
    def src(self):
        return _SCRIPT_PATH.read_text(encoding="utf-8")

    def test_returns_hex(self, src):
        assert "hex" in src

    def test_returns_use_count(self, src):
        assert "use_count" in src

    def test_returns_sample_nodes(self, src):
        assert "sample_nodes" in src

    def test_returns_sample_pages(self, src):
        assert "sample_pages" in src

    def test_has_return_statement(self, src):
        assert "return " in src


class TestJsTemplateSampleNodeLimit:
    """sample_nodes must be capped at 5 per hex."""

    @pytest.fixture(scope="class")
    def src(self):
        return _SCRIPT_PATH.read_text(encoding="utf-8")

    def test_cap_constant_is_5(self, src):
        # The limit 5 must appear explicitly in the script.
        assert "5" in src

    def test_slice_or_limit_applied(self, src):
        # Script must use .slice() or a counter guard to enforce the cap.
        assert ".slice(" in src or "< 5" in src or "<= 4" in src


class TestJsTemplateNoWrites:
    """The script must never mutate Figma state."""

    @pytest.fixture(scope="class")
    def src(self):
        return _SCRIPT_PATH.read_text(encoding="utf-8")

    def test_no_create_variable(self, src):
        assert "createVariable" not in src

    def test_no_set_value_for_mode(self, src):
        assert "setValueForMode" not in src

    def test_no_figma_notify(self, src):
        assert "figma.notify(" not in src


class TestJsTemplateRgbToHex:
    """Script must include a hex conversion utility (same as summary script)."""

    @pytest.fixture(scope="class")
    def src(self):
        return _SCRIPT_PATH.read_text(encoding="utf-8")

    def test_rgb_to_hex_function_present(self, src):
        assert "rgbToHex" in src

    def test_hex_format_is_six_chars(self, src):
        # padStart(2, "0") is the standard pattern used in this codebase.
        assert 'padStart(2, "0")' in src


# ---------------------------------------------------------------------------
# Handler registration — read_app exposes the new command
# ---------------------------------------------------------------------------

class TestHandlerRegistration:
    @pytest.fixture(scope="class")
    def registered_commands(self):
        import read_handlers
        return {cmd.name for cmd in read_handlers.read_app.registered_commands}

    def test_color_usage_detail_command_registered(self, registered_commands):
        assert "color-usage-detail" in registered_commands


class TestHandlerLoadsScript:
    """Handler must load the JS from the script file, not inline it."""

    def test_handler_references_script_filename(self):
        import read_handlers
        src = Path(read_handlers.__file__).read_text(encoding="utf-8")
        assert "read_color_usage_detail.js" in src
