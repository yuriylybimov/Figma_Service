"""Tests for sync primitive-colors-normalized output modes.

Mocks _dispatch_sync and _run_validation so no Playwright/Figma is needed.
Verifies that:
  - default (no flags): human summary only, no JSON, no [info] infra logs
  - --dry-run: label changes to "Dry-run summary"
  - --verbose: per-entry log appended, still no JSON
  - --json: only valid JSON on stdout, no human text
  - --json --verbose: JSON only (verbose ignored)
  - --debug: set_debug(True) called; [info] logs emitted to stderr
  - --debug --json: infra logs to stderr only, stdout remains JSON
  - exit codes unchanged (0 on success)
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import host_io
from sync_handlers import sync_app
from protocol import ExecOkInline

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENTRIES = [
    {"hex": "#ff0000", "candidate_name": "color/candidate/ff0000", "final_name": "color/red/500"},
    {"hex": "#0000ff", "candidate_name": "color/candidate/0000ff", "final_name": "color/blue/500"},
]

_JS_RESULT = {
    "collection": "primitives",
    "mode": "dry-run-mode",
    "dry_run": True,
    "renamed": 0,
    "created": 2,
    "skipped": 0,
    "total": 2,
    "log": [
        {"action": "would-rename-or-create", "candidate_name": "color/candidate/ff0000",
         "final_name": "color/red/500", "hex": "#ff0000",
         "note": "(would check for color/candidate/ff0000)"},
        {"action": "would-rename-or-create", "candidate_name": "color/candidate/0000ff",
         "final_name": "color/blue/500", "hex": "#0000ff",
         "note": "(would check for color/candidate/0000ff)"},
    ],
}

_OK_MODEL = ExecOkInline(
    status="ok",
    mode="inline",
    version=2,
    request_id="testrid0",
    result=_JS_RESULT,
    elapsed_ms=42,
)


@pytest.fixture()
def normalized_file(tmp_path):
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps({"colors": _ENTRIES}), encoding="utf-8")
    return str(p)


def _invoke(normalized_file, *extra_args):
    """Invoke sync primitive-colors-normalized with mocked bridge and validation."""
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_JS_RESULT, _OK_MODEL)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        return runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", normalized_file, *extra_args],
            catch_exceptions=False,
        )


# ---------------------------------------------------------------------------
# Default (human) mode
# ---------------------------------------------------------------------------

def test_default_prints_summary(normalized_file):
    result = _invoke(normalized_file)
    assert result.exit_code == 0
    assert "Sync summary" in result.output


def test_default_no_json_in_output(normalized_file):
    result = _invoke(normalized_file)
    assert result.exit_code == 0
    # The wire-format JSON blob must not appear
    assert '"status"' not in result.output
    assert '"request_id"' not in result.output


def test_default_shows_counts(normalized_file):
    result = _invoke(normalized_file)
    assert "(2 total)" in result.output
    assert "+2 created" in result.output
    assert "~0 renamed" in result.output
    assert "0 skipped" in result.output


# ---------------------------------------------------------------------------
# --dry-run label
# ---------------------------------------------------------------------------

def test_dry_run_label(normalized_file):
    result = _invoke(normalized_file, "--dry-run")
    assert result.exit_code == 0
    assert "Dry-run summary" in result.output
    assert "Sync summary" not in result.output


def test_dry_run_no_json(normalized_file):
    result = _invoke(normalized_file, "--dry-run")
    assert '"status"' not in result.output


# ---------------------------------------------------------------------------
# --verbose (human mode)
# ---------------------------------------------------------------------------

def test_verbose_adds_log(normalized_file):
    result = _invoke(normalized_file, "--verbose")
    assert result.exit_code == 0
    assert "Detailed changes" in result.output
    assert "+ red/500" in result.output


def test_verbose_still_no_json_envelope(normalized_file):
    result = _invoke(normalized_file, "--verbose")
    # Per-entry log lines contain JSON objects, but the wire-format envelope must not appear
    assert '"request_id"' not in result.output
    assert '"elapsed_ms"' not in result.output


def test_verbose_dry_run_combination(normalized_file):
    result = _invoke(normalized_file, "--dry-run", "--verbose")
    assert result.exit_code == 0
    assert "Dry-run summary" in result.output
    assert "Detailed changes" in result.output


# ---------------------------------------------------------------------------
# --json mode
# ---------------------------------------------------------------------------

def test_json_mode_stdout_is_valid_json(normalized_file):
    result = _invoke(normalized_file, "--json")
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"


def test_json_mode_no_human_text(normalized_file):
    result = _invoke(normalized_file, "--json")
    assert "summary" not in result.output.lower()
    assert "total=" not in result.output


def test_json_mode_contains_result(normalized_file):
    result = _invoke(normalized_file, "--json")
    parsed = json.loads(result.output)
    assert parsed["result"]["total"] == 2
    assert parsed["result"]["created"] == 2


def test_json_mode_with_dry_run(normalized_file):
    result = _invoke(normalized_file, "--json", "--dry-run")
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"
    assert "summary" not in result.output.lower()


def test_json_mode_ignores_verbose(normalized_file):
    result = _invoke(normalized_file, "--json", "--verbose")
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"
    assert "Detailed log:" not in result.output


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_default_exit_code_zero(normalized_file):
    result = _invoke(normalized_file)
    assert result.exit_code == 0


def test_json_exit_code_zero(normalized_file):
    result = _invoke(normalized_file, "--json")
    assert result.exit_code == 0


def test_verbose_exit_code_zero(normalized_file):
    result = _invoke(normalized_file, "--verbose")
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# host_io._log unit tests — _DEBUG flag behaviour (no CLI involved)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def reset_host_io_flags():
    """Restore host_io._DEBUG and _QUIET after each test that touches them."""
    orig_debug = host_io._DEBUG
    orig_quiet = host_io._QUIET
    yield
    host_io._DEBUG = orig_debug
    host_io._QUIET = orig_quiet


def test_log_info_suppressed_by_default(reset_host_io_flags):
    host_io._DEBUG = False
    host_io._QUIET = False
    buf = io.StringIO()
    with patch("host_io.sys.stderr", buf):
        host_io._log("info", "launching firefox")
    assert buf.getvalue() == "", "Expected no output: info suppressed when _DEBUG=False"


def test_log_error_always_shown(reset_host_io_flags):
    host_io._DEBUG = False
    host_io._QUIET = False
    buf = io.StringIO()
    with patch("host_io.sys.stderr", buf):
        host_io._log("error", "something went wrong")
    assert "[error]" in buf.getvalue()


def test_log_info_shown_when_debug(reset_host_io_flags):
    host_io._DEBUG = True
    host_io._QUIET = False
    buf = io.StringIO()
    with patch("host_io.sys.stderr", buf):
        host_io._log("info", "launching firefox")
    assert "[info]" in buf.getvalue()
    assert "launching firefox" in buf.getvalue()


def test_log_info_suppressed_when_quiet(reset_host_io_flags):
    host_io._DEBUG = True   # even with debug on, quiet wins for info
    host_io._QUIET = True
    buf = io.StringIO()
    with patch("host_io.sys.stderr", buf):
        host_io._log("info", "launching firefox")
    assert buf.getvalue() == "", "Expected no output: _QUIET suppresses even when _DEBUG=True"


# ---------------------------------------------------------------------------
# --debug CLI flag — set_debug is called correctly
# ---------------------------------------------------------------------------

def test_default_calls_set_debug_false(normalized_file):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_JS_RESULT, _OK_MODEL)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
        patch("sync_handlers.set_debug") as mock_set_debug,
    ):
        runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", normalized_file],
            catch_exceptions=False,
        )
    mock_set_debug.assert_called_once_with(False)


def test_debug_flag_calls_set_debug_true(normalized_file):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_JS_RESULT, _OK_MODEL)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
        patch("sync_handlers.set_debug") as mock_set_debug,
    ):
        runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", normalized_file, "--debug"],
            catch_exceptions=False,
        )
    mock_set_debug.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# --debug + --json: stdout stays JSON-only, infra logs go to stderr only
# ---------------------------------------------------------------------------

def test_debug_json_stdout_is_still_valid_json(normalized_file):
    result = _invoke(normalized_file, "--debug", "--json")
    assert result.exit_code == 0
    # CliRunner merges stderr into output; strip any [info] lines before parsing
    json_lines = [l for l in result.output.splitlines() if l.startswith("{") or l.startswith("[")]
    assert len(json_lines) >= 1
    parsed = json.loads(json_lines[0])
    assert parsed["status"] == "ok"


def test_debug_default_mode_summary_still_present(normalized_file):
    result = _invoke(normalized_file, "--debug")
    assert result.exit_code == 0
    assert "Sync summary" in result.output


def test_debug_exit_code_zero(normalized_file):
    result = _invoke(normalized_file, "--debug")
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Scale sort order — default grouped output and verbose Detailed changes
# ---------------------------------------------------------------------------

_MULTISCALE_LOG = {
    "collection": "primitives",
    "mode": "dry-run-mode",
    "dry_run": True,
    "renamed": 0,
    "created": 3,
    "skipped": 0,
    "total": 3,
    "log": [
        {"action": "would-rename-or-create", "final_name": "color/gray/900", "hex": "#111827"},
        {"action": "would-rename-or-create", "final_name": "color/gray/100", "hex": "#f9fafb"},
        {"action": "would-rename-or-create", "final_name": "color/gray/500", "hex": "#6b7280"},
    ],
}

_MULTISCALE_OK = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="testrid1",
    result=_MULTISCALE_LOG, elapsed_ms=10,
)


@pytest.fixture()
def multiscale_file(tmp_path):
    entries = [
        {"hex": "#111827", "candidate_name": "color/candidate/111827", "final_name": "color/gray/900"},
        {"hex": "#f9fafb", "candidate_name": "color/candidate/f9fafb", "final_name": "color/gray/100"},
        {"hex": "#6b7280", "candidate_name": "color/candidate/6b7280", "final_name": "color/gray/500"},
    ]
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps({"colors": entries}), encoding="utf-8")
    return str(p)


def _invoke_multiscale(multiscale_file, *extra_args):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_MULTISCALE_LOG, _MULTISCALE_OK)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        return runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", multiscale_file, *extra_args],
            catch_exceptions=False,
        )


def test_default_grouped_scales_ascending(multiscale_file):
    result = _invoke_multiscale(multiscale_file)
    lines = [l for l in result.output.splitlines() if l.strip() and l.startswith("    ")]
    scale_values = []
    for l in lines:
        token = l.strip().split()[0]
        if token.isdigit():
            scale_values.append(int(token))
    assert scale_values == sorted(scale_values), f"Expected ascending scales, got {scale_values}"


def test_verbose_detailed_scales_ascending(multiscale_file):
    result = _invoke_multiscale(multiscale_file, "--verbose")
    created_lines = [l for l in result.output.splitlines() if l.strip().startswith("+")]
    # Extract the scale part from "gray/NNN"
    import re
    scales = []
    for l in created_lines:
        m = re.search(r"/(\d+)", l)
        if m:
            scales.append(int(m.group(1)))
    assert scales == sorted(scales), f"Expected ascending scales in verbose, got {scales}"


def test_debug_no_raw_json_in_output(multiscale_file):
    result = _invoke_multiscale(multiscale_file, "--debug")
    assert result.exit_code == 0
    # Raw wire-format keys must not appear in any output channel
    assert '"status"' not in result.output
    assert '"request_id"' not in result.output
    assert '"elapsed_ms"' not in result.output


# ---------------------------------------------------------------------------
# Regression: real JS "created" log entries use name/value, not final_name/hex
# ---------------------------------------------------------------------------

_CREATED_ACTION_LOG = {
    "collection": "primitives",
    "mode": "Value Mode 1",
    "dry_run": False,
    "renamed": 0,
    "created": 3,
    "skipped": 0,
    "total": 3,
    "log": [
        {"action": "created", "name": "color/gray/900", "value": "#111827"},
        {"action": "created", "name": "color/gray/100", "value": "#f9fafb"},
        {"action": "created", "name": "color/gray/500", "value": "#6b7280"},
    ],
}

_CREATED_ACTION_OK = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="testrid-created",
    result=_CREATED_ACTION_LOG, elapsed_ms=10,
)


@pytest.fixture()
def created_action_file(tmp_path):
    entries = [
        {"hex": "#111827", "candidate_name": "color/candidate/111827", "final_name": "color/gray/900"},
        {"hex": "#f9fafb", "candidate_name": "color/candidate/f9fafb", "final_name": "color/gray/100"},
        {"hex": "#6b7280", "candidate_name": "color/candidate/6b7280", "final_name": "color/gray/500"},
    ]
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps({"colors": entries}), encoding="utf-8")
    return str(p)


def _invoke_created_action(created_action_file, *extra_args):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_CREATED_ACTION_LOG, _CREATED_ACTION_OK)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        return runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", created_action_file, *extra_args],
            catch_exceptions=False,
        )


def test_created_action_no_other_group(created_action_file):
    """Regression: action=created uses name/value keys; formatter must not fall back to 'other'."""
    result = _invoke_created_action(created_action_file)
    assert result.exit_code == 0
    assert "other" not in result.output


def test_created_action_group_header_present(created_action_file):
    result = _invoke_created_action(created_action_file)
    assert "gray (3)" in result.output


def test_created_action_rows_visible(created_action_file):
    result = _invoke_created_action(created_action_file)
    assert "#111827" in result.output
    assert "#f9fafb" in result.output
    assert "#6b7280" in result.output


def test_created_action_scales_ascending(created_action_file):
    result = _invoke_created_action(created_action_file)
    lines = [l for l in result.output.splitlines() if l.strip() and l.startswith("    ")]
    scale_values = [int(l.strip().split()[0]) for l in lines if l.strip().split()[0].isdigit()]
    assert scale_values == sorted(scale_values)


# ---------------------------------------------------------------------------
# Fixed-color flattening — white/black must not appear under a "color" header
# ---------------------------------------------------------------------------

_FIXED_COLOR_LOG = {
    "collection": "primitives",
    "mode": "dry-run-mode",
    "dry_run": True,
    "renamed": 0,
    "created": 3,
    "skipped": 0,
    "total": 3,
    "log": [
        {"action": "would-rename-or-create", "final_name": "color/white", "hex": "#ffffff"},
        {"action": "would-rename-or-create", "final_name": "color/black", "hex": "#000000"},
        {"action": "would-rename-or-create", "final_name": "color/gray/500", "hex": "#6b7280"},
    ],
}

_FIXED_COLOR_OK = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="testrid2",
    result=_FIXED_COLOR_LOG, elapsed_ms=10,
)


@pytest.fixture()
def fixed_color_file(tmp_path):
    entries = [
        {"hex": "#ffffff", "candidate_name": "color/candidate/ffffff", "final_name": "color/white"},
        {"hex": "#000000", "candidate_name": "color/candidate/000000", "final_name": "color/black"},
        {"hex": "#6b7280", "candidate_name": "color/candidate/6b7280", "final_name": "color/gray/500"},
    ]
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps({"colors": entries}), encoding="utf-8")
    return str(p)


def _invoke_fixed_color(fixed_color_file, *extra_args):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(_FIXED_COLOR_LOG, _FIXED_COLOR_OK)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        return runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", fixed_color_file, *extra_args],
            catch_exceptions=False,
        )


def test_fixed_colors_no_color_group_header(fixed_color_file):
    result = _invoke_fixed_color(fixed_color_file)
    assert result.exit_code == 0
    assert "color (2)" not in result.output
    assert "color (1)" not in result.output


def test_fixed_colors_white_black_appear_flat(fixed_color_file):
    result = _invoke_fixed_color(fixed_color_file)
    lines = result.output.splitlines()
    assert any("white" in l and "#ffffff" in l for l in lines)
    assert any("black" in l and "#000000" in l for l in lines)


def test_fixed_colors_gray_group_still_present(fixed_color_file):
    result = _invoke_fixed_color(fixed_color_file)
    assert "gray (1)" in result.output


def test_scale_hex_alignment(fixed_color_file):
    result = _invoke_fixed_color(fixed_color_file)
    # All indented token lines (scale or label + hex) must have hex starting at a consistent column
    import re
    hex_cols = []
    for line in result.output.splitlines():
        # Match lines like "    500    #rrggbb" or "  white    #rrggbb"
        m = re.search(r"(#[0-9a-fA-F]{6})", line)
        if m and line.startswith("  ") and not line.strip().startswith("+"):
            hex_cols.append(m.start())
    assert len(set(hex_cols)) == 1, f"Hex values not vertically aligned: columns={hex_cols}"


# ---------------------------------------------------------------------------
# Payload sort order — entries must reach _dispatch_sync sorted by group/scale
# ---------------------------------------------------------------------------

_UNSORTED_ENTRIES = [
    {"hex": "#111827", "candidate_name": "color/candidate/111827", "final_name": "color/gray/900"},
    {"hex": "#f9fafb", "candidate_name": "color/candidate/f9fafb", "final_name": "color/gray/100"},
    {"hex": "#6b7280", "candidate_name": "color/candidate/6b7280", "final_name": "color/gray/500"},
    {"hex": "#3b82f6", "candidate_name": "color/candidate/3b82f6", "final_name": "color/blue/700"},
    {"hex": "#93c5fd", "candidate_name": "color/candidate/93c5fd", "final_name": "color/blue/300"},
    {"hex": "#ffffff", "candidate_name": "color/candidate/ffffff", "final_name": "color/white"},
]


@pytest.fixture()
def unsorted_file(tmp_path):
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps({"colors": _UNSORTED_ENTRIES}), encoding="utf-8")
    return str(p)


def test_payload_entries_sorted_by_group_then_scale(unsorted_file):
    """Entries injected into the JS payload must be sorted group-alphabetically,
    then numerically ascending by scale, so Figma creates variables in order."""
    captured_js: list[str] = []

    def fake_dispatch(user_js, **kwargs):
        captured_js.append(user_js)
        return (_JS_RESULT, _OK_MODEL)

    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", side_effect=fake_dispatch),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        runner.invoke(
            sync_app,
            ["primitive-colors-normalized", "--normalized", unsorted_file],
            catch_exceptions=False,
        )

    assert captured_js, "expected _dispatch_sync to be called"
    js = captured_js[0]

    # Extract the injected JSON array from the JS source
    import re
    m = re.search(r"__NORMALIZED__\s*=\s*(\[.*?\]);", js, re.DOTALL)
    if m is None:
        # fallback: the placeholder was replaced, find the array literal in the JS
        # The replacement is json.dumps(entries), which starts with '[{'
        start = js.index("[{")
        # find matching closing bracket
        depth, end = 0, start
        for i, ch in enumerate(js[start:], start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        injected = json.loads(js[start : end + 1])
    else:
        injected = json.loads(m.group(1))

    def sort_key(e):
        parts = e["final_name"].split("/")
        group = parts[1] if len(parts) >= 2 else ""
        scale_str = parts[2] if len(parts) >= 3 else ""
        scale = int(scale_str) if scale_str.isdigit() else float("inf")
        return (group, scale)

    assert injected == sorted(injected, key=sort_key), (
        "Payload entries not sorted by group/scale:\n"
        + "\n".join(e["final_name"] for e in injected)
    )
