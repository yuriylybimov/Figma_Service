"""Tests for `sync primitive-tokens` command."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from run import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_VALID_FONT_SIZE_SEED = [
    {"name": "font-size/font-size-12", "value": 12},
    {"name": "font-size/font-size-14", "value": 14},
    {"name": "font-size/font-size-16", "value": 16},
]

_VALID_FONT_FAMILY_SEED = [
    {"name": "font-family/inter", "value": "Inter"},
]

_FIGMA_URL = "https://figma.com/file/fake/test"

def _ok(result_dict):
    """Wrap a result dict in the wire envelope that ExecOkInline requires."""
    return {
        "status": "ok",
        "version": 2,
        "mode": "inline",
        "request_id": "test-rid-0000",
        "elapsed_ms": 1,
        "result": result_dict,
    }


# Stub: pretend validate_runtime_context passes, then sync returns ok result.
def _fake_bridge_exec(url, user_js, rid, *, inline_cap, timeout_s, mount_timeout_s):
    # validate_runtime_context call (first call per command)
    if "validate_runtime_context" in user_js or "create_variable_api" in user_js:
        return _ok({
            "ok": True,
            "checks": [
                {"name": "figma_api",           "passed": True, "detail": "ok"},
                {"name": "variables_api",        "passed": True, "detail": "ok"},
                {"name": "current_page",         "passed": True, "detail": "Design"},
                {"name": "create_variable_api",  "passed": True, "detail": "ok"},
            ],
        })
    # sync_primitive_tokens call
    return _ok({
        "collection": "primitives",
        "mode": "dry-run-mode",
        "dry_run": True,
        "figma_type": "FLOAT",
        "created": 3,
        "skipped": 0,
        "errored": 0,
        "total": 3,
        "log": [
            {"action": "would-create", "name": "font-size/font-size-12", "value": 12, "figma_type": "FLOAT"},
            {"action": "would-create", "name": "font-size/font-size-14", "value": 14, "figma_type": "FLOAT"},
            {"action": "would-create", "name": "font-size/font-size-16", "value": 16, "figma_type": "FLOAT"},
        ],
    })


def _write_seed(tmp_path, type_key, data):
    p = tmp_path / f"{type_key}.seed.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Command presence
# ---------------------------------------------------------------------------

def test_command_exists_in_sync_subapp():
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
    assert "primitive-tokens" in result.output


def test_help_lists_valid_types():
    result = runner.invoke(app, ["sync", "primitive-tokens", "--help"])
    assert result.exit_code == 0
    assert "font-size" in result.output or "spacing" in result.output


# ---------------------------------------------------------------------------
# Argument / option validation
# ---------------------------------------------------------------------------

def test_missing_type_arg_exits_nonzero():
    result = runner.invoke(app, ["sync", "primitive-tokens"],
                           env={"FIGMA_FILE_URL": _FIGMA_URL})
    assert result.exit_code != 0


def test_invalid_type_exits_nonzero(tmp_path):
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "not-a-real-type", "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output or "ERROR" in (result.stderr or "")


def test_missing_seed_file_exits_nonzero(tmp_path):
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", str(tmp_path / "missing.seed.json"),
         "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output or "ERROR" in (result.stderr or "")


# ---------------------------------------------------------------------------
# Seed validation blocks sync
# ---------------------------------------------------------------------------

def test_validation_failure_blocks_sync_wrong_prefix(tmp_path):
    bad_seed = [{"name": "spacing/size-8", "value": 8}]  # wrong prefix for font-size
    seed_path = _write_seed(tmp_path, "font-size", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output or "ERROR" in (result.stderr or "")


def test_validation_failure_blocks_sync_wrong_value_type(tmp_path):
    bad_seed = [{"name": "font-size/font-size-14", "value": "14px"}]  # STRING not FLOAT
    seed_path = _write_seed(tmp_path, "font-size", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


def test_validation_failure_blocks_sync_duplicate_name(tmp_path):
    bad_seed = [
        {"name": "font-size/font-size-14", "value": 14},
        {"name": "font-size/font-size-14", "value": 14},
    ]
    seed_path = _write_seed(tmp_path, "font-size", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


def test_validation_failure_blocks_sync_missing_name_field(tmp_path):
    bad_seed = [{"value": 14}]
    seed_path = _write_seed(tmp_path, "font-size", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


def test_validation_failure_blocks_sync_missing_value_field(tmp_path):
    bad_seed = [{"name": "font-size/font-size-14"}]
    seed_path = _write_seed(tmp_path, "font-size", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


def test_validation_failure_blocks_sync_opacity_out_of_range(tmp_path):
    bad_seed = [{"name": "opacity/opacity-200", "value": 2.5}]
    seed_path = _write_seed(tmp_path, "opacity", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "opacity",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


def test_validation_failure_blocks_sync_font_family_wrong_type(tmp_path):
    bad_seed = [{"name": "font-family/inter", "value": 123}]  # should be string
    seed_path = _write_seed(tmp_path, "font-family", bad_seed)
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-family",
         "--seed-file", seed_path, "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Dry-run succeeds with valid seed
# ---------------------------------------------------------------------------

def test_dry_run_exits_zero_with_valid_seed(tmp_path):
    seed_path = _write_seed(tmp_path, "font-size", _VALID_FONT_SIZE_SEED)
    with patch("sync_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        result = runner.invoke(
            app,
            ["sync", "primitive-tokens", "font-size",
             "--seed-file", seed_path, "--dry-run"],
            env={"FIGMA_FILE_URL": _FIGMA_URL},
        )
    assert result.exit_code == 0


def test_dry_run_output_contains_summary(tmp_path):
    seed_path = _write_seed(tmp_path, "font-size", _VALID_FONT_SIZE_SEED)
    with patch("sync_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        result = runner.invoke(
            app,
            ["sync", "primitive-tokens", "font-size",
             "--seed-file", seed_path, "--dry-run"],
            env={"FIGMA_FILE_URL": _FIGMA_URL},
        )
    assert "Dry-run summary" in result.output
    assert "font-size" in result.output


def test_dry_run_verbose_lists_entries(tmp_path):
    seed_path = _write_seed(tmp_path, "font-size", _VALID_FONT_SIZE_SEED)
    with patch("sync_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        result = runner.invoke(
            app,
            ["sync", "primitive-tokens", "font-size",
             "--seed-file", seed_path, "--dry-run", "--verbose"],
            env={"FIGMA_FILE_URL": _FIGMA_URL},
        )
    assert result.exit_code == 0
    assert "font-size/font-size-12" in result.output


def test_dry_run_string_type_exits_zero(tmp_path):
    """font-family uses STRING — verify the type path works."""
    seed_path = _write_seed(tmp_path, "font-family", _VALID_FONT_FAMILY_SEED)

    def _string_bridge(url, user_js, rid, *, inline_cap, timeout_s, mount_timeout_s):
        if "create_variable_api" in user_js or "validate_runtime_context" in user_js:
            return _ok({
                "ok": True, "checks": [
                    {"name": "figma_api",           "passed": True, "detail": "ok"},
                    {"name": "variables_api",        "passed": True, "detail": "ok"},
                    {"name": "current_page",         "passed": True, "detail": "Design"},
                    {"name": "create_variable_api",  "passed": True, "detail": "ok"},
                ]
            })
        return _ok({
            "collection": "primitives", "mode": "dry-run-mode",
            "dry_run": True, "figma_type": "STRING",
            "created": 1, "skipped": 0, "errored": 0, "total": 1,
            "log": [{"action": "would-create", "name": "font-family/inter", "value": "Inter", "figma_type": "STRING"}],
        })

    with patch("sync_handlers._bridge_exec", side_effect=_string_bridge):
        result = runner.invoke(
            app,
            ["sync", "primitive-tokens", "font-family",
             "--seed-file", seed_path, "--dry-run"],
            env={"FIGMA_FILE_URL": _FIGMA_URL},
        )
    assert result.exit_code == 0
    assert "STRING" in result.output


# ---------------------------------------------------------------------------
# Default seed path resolution
# ---------------------------------------------------------------------------

def test_default_seed_path_resolves_to_tokens_dir():
    """Verify the command reads from tokens/<type>.seed.json by default.

    We don't mock the bridge here — we just confirm the error message when
    the default seed is absent tells us which file it looked for.
    """
    result = runner.invoke(
        app,
        ["sync", "primitive-tokens", "font-size", "--dry-run"],
        env={"FIGMA_FILE_URL": _FIGMA_URL},
    )
    # The real tokens/font-size.seed.json exists in the project, so this
    # call will fail at the bridge (no real Figma) — but the error must NOT
    # be "Seed file not found", which would mean the path resolution broke.
    assert "Seed file not found" not in (result.output or "")


# ---------------------------------------------------------------------------
# Guard: seed files must not be modified
# ---------------------------------------------------------------------------

_SEED_NAMES = [
    "font-size.seed.json",
    "font-family.seed.json",
    "font-weight.seed.json",
    "letter-spacing.seed.json",
    "line-height.seed.json",
    "primitives-semantic.seed.json",
]
_TOKENS_DIR = Path(__file__).parent.parent / "tokens"


def _read_seed_checksums():
    result = {}
    for name in _SEED_NAMES:
        p = _TOKENS_DIR / name
        if p.exists():
            result[name] = p.read_bytes()
    return result


def test_no_seed_files_modified(tmp_path):
    before = _read_seed_checksums()
    seed_path = _write_seed(tmp_path, "font-size", _VALID_FONT_SIZE_SEED)
    with patch("sync_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["sync", "primitive-tokens", "font-size",
             "--seed-file", seed_path, "--dry-run"],
            env={"FIGMA_FILE_URL": _FIGMA_URL},
        )
    after = _read_seed_checksums()
    for name, content in before.items():
        assert after[name] == content, f"Seed file was modified: {name}"
