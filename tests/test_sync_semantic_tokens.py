"""Tests for sync semantic-tokens output modes and error handling.

Mocks _run_validation and _dispatch_sync — no Playwright/Figma needed.
Verifies:
  - dry-run prints summary
  - dry-run --verbose shows alias lines
  - real run prints sync summary
  - --json outputs valid JSON
  - missing primitive in normalized file exits 1 before dispatch
  - JS errored/ok:false exits 1
  - input files are not modified
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_handlers import sync_app
from protocol import ExecOkInline

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_PRIMITIVE_COLORS = [
    {"hex": "#111827", "candidate_name": "color/candidate/111827", "final_name": "color/gray/900"},
    {"hex": "#f9fafb", "candidate_name": "color/candidate/f9fafb", "final_name": "color/gray/100"},
    {"hex": "#6b7280", "candidate_name": "color/candidate/6b7280", "final_name": "color/gray/500"},
]

_SEMANTICS = {
    "color/text/primary": "color/gray/900",
    "color/surface/default": "color/gray/100",
}

_JS_RESULT_DRY = {
    "ok": True,
    "dry_run": True,
    "created": 2,
    "updated": 0,
    "skipped": 0,
    "total": 2,
    "errored": 0,
    "log": [
        {"action": "would-create-alias", "semantic_name": "color/surface/default", "primitive_name": "color/gray/100"},
        {"action": "would-create-alias", "semantic_name": "color/text/primary", "primitive_name": "color/gray/900"},
    ],
}

_JS_RESULT_REAL = {
    "ok": True,
    "dry_run": False,
    "created": 2,
    "updated": 0,
    "skipped": 0,
    "total": 2,
    "errored": 0,
    "log": [
        {"action": "created", "semantic_name": "color/surface/default", "primitive_name": "color/gray/100"},
        {"action": "created", "semantic_name": "color/text/primary", "primitive_name": "color/gray/900"},
    ],
}

_OK_MODEL_DRY = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="sem-dry-0",
    result=_JS_RESULT_DRY, elapsed_ms=42,
)

_OK_MODEL_REAL = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="sem-real-0",
    result=_JS_RESULT_REAL, elapsed_ms=55,
)


@pytest.fixture()
def token_files(tmp_path):
    sem = tmp_path / "semantics.normalized.json"
    prim = tmp_path / "primitives.normalized.json"
    sem.write_text(json.dumps(_SEMANTICS), encoding="utf-8")
    prim.write_text(json.dumps({"colors": _PRIMITIVE_COLORS}), encoding="utf-8")
    return str(sem), str(prim)


def _invoke(sem_file, prim_file, js_result, ok_model, *extra_args):
    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", return_value=(js_result, ok_model)),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        return runner.invoke(
            sync_app,
            ["semantic-tokens",
             "--semantics", sem_file,
             "--primitives", prim_file,
             *extra_args],
            catch_exceptions=False,
        )


# ---------------------------------------------------------------------------
# dry-run prints summary
# ---------------------------------------------------------------------------

def test_dry_run_prints_summary(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_DRY, _OK_MODEL_DRY, "--dry-run")
    assert result.exit_code == 0
    assert "Dry-run summary" in result.output
    assert "Sync summary" not in result.output


def test_dry_run_shows_counts(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_DRY, _OK_MODEL_DRY, "--dry-run")
    assert "+2 created" in result.output
    assert "(2 total)" in result.output


# ---------------------------------------------------------------------------
# dry-run --verbose shows alias lines
# ---------------------------------------------------------------------------

def test_dry_run_verbose_shows_alias_lines(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_DRY, _OK_MODEL_DRY, "--dry-run", "--verbose")
    assert result.exit_code == 0
    assert "Detailed changes" in result.output
    # alias lines use "+" prefix and "→" arrow
    lines = result.output.splitlines()
    alias_lines = [l for l in lines if l.strip().startswith("+") and "→" in l]
    assert len(alias_lines) == 2
    assert any("color/gray/900" in l for l in alias_lines)
    assert any("color/gray/100" in l for l in alias_lines)


def test_dry_run_verbose_no_json_envelope(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_DRY, _OK_MODEL_DRY, "--dry-run", "--verbose")
    assert '"request_id"' not in result.output
    assert '"elapsed_ms"' not in result.output


# ---------------------------------------------------------------------------
# real run prints sync summary
# ---------------------------------------------------------------------------

def test_real_run_prints_sync_summary(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL)
    assert result.exit_code == 0
    assert "Sync summary" in result.output
    assert "Dry-run summary" not in result.output


def test_real_run_shows_counts(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL)
    assert "+2 created" in result.output
    assert "(2 total)" in result.output


# ---------------------------------------------------------------------------
# --json outputs valid JSON
# ---------------------------------------------------------------------------

def test_json_mode_stdout_is_valid_json(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL, "--json")
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"


def test_json_mode_no_human_text(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL, "--json")
    assert "summary" not in result.output.lower()
    assert "Detailed changes" not in result.output


def test_json_mode_contains_result(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL, "--json")
    parsed = json.loads(result.output)
    assert parsed["result"]["total"] == 2
    assert parsed["result"]["created"] == 2


# ---------------------------------------------------------------------------
# missing primitive in normalized file exits 1 before dispatch
# ---------------------------------------------------------------------------

def test_missing_primitive_exits_1_before_dispatch(tmp_path):
    sem = tmp_path / "semantics.normalized.json"
    prim = tmp_path / "primitives.normalized.json"
    # semantic references a primitive that does not exist in primitives file
    sem.write_text(json.dumps({"color/text/primary": "color/DOES_NOT_EXIST/999"}), encoding="utf-8")
    prim.write_text(json.dumps({"colors": _PRIMITIVE_COLORS}), encoding="utf-8")

    dispatch_called = []

    def fake_dispatch(user_js, **kwargs):
        dispatch_called.append(True)
        return (_JS_RESULT_REAL, _OK_MODEL_REAL)

    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch("sync_handlers._dispatch_sync", side_effect=fake_dispatch),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        result = runner.invoke(
            sync_app,
            ["semantic-tokens", "--semantics", str(sem), "--primitives", str(prim)],
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert not dispatch_called, "_dispatch_sync must not be called when primitives are missing"


def test_missing_primitive_error_message(tmp_path):
    sem = tmp_path / "semantics.normalized.json"
    prim = tmp_path / "primitives.normalized.json"
    sem.write_text(json.dumps({"color/text/primary": "color/DOES_NOT_EXIST/999"}), encoding="utf-8")
    prim.write_text(json.dumps({"colors": _PRIMITIVE_COLORS}), encoding="utf-8")

    with (
        patch("sync_handlers._run_validation", return_value=None),
        patch.dict("os.environ", {"FIGMA_FILE_URL": "https://figma.com/file/fake/test"}),
    ):
        result = runner.invoke(
            sync_app,
            ["semantic-tokens", "--semantics", str(sem), "--primitives", str(prim)],
            catch_exceptions=False,
        )

    assert "color/DOES_NOT_EXIST/999" in result.output + (result.stderr or "")


# ---------------------------------------------------------------------------
# JS errored / ok:false exits 1
# ---------------------------------------------------------------------------

_JS_RESULT_ERRORED = {
    "ok": False,
    "dry_run": False,
    "created": 0,
    "updated": 0,
    "skipped": 0,
    "total": 2,
    "errored": 1,
    "log": [],
}

_OK_MODEL_ERRORED = ExecOkInline(
    status="ok", mode="inline", version=2, request_id="sem-err-0",
    result=_JS_RESULT_ERRORED, elapsed_ms=10,
)


def test_js_ok_false_exits_1(token_files):
    sem, prim = token_files
    result = _invoke(sem, prim, _JS_RESULT_ERRORED, _OK_MODEL_ERRORED)
    assert result.exit_code == 1


def test_js_ok_false_with_missing_primitives_reports_them(token_files):
    sem, prim = token_files
    js_result = {
        **_JS_RESULT_ERRORED,
        "missing_primitives": ["color/gray/999"],
    }
    ok_model = ExecOkInline(
        status="ok", mode="inline", version=2, request_id="sem-err-1",
        result=js_result, elapsed_ms=10,
    )
    result = _invoke(sem, prim, js_result, ok_model)
    assert result.exit_code == 1
    assert "color/gray/999" in result.output + (result.stderr or "")


# ---------------------------------------------------------------------------
# input files are not modified
# ---------------------------------------------------------------------------

def test_input_files_not_modified(token_files):
    sem, prim = token_files
    sem_before = Path(sem).read_text(encoding="utf-8")
    prim_before = Path(prim).read_text(encoding="utf-8")

    _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL)
    _invoke(sem, prim, _JS_RESULT_DRY, _OK_MODEL_DRY, "--dry-run")
    _invoke(sem, prim, _JS_RESULT_REAL, _OK_MODEL_REAL, "--json")

    assert Path(sem).read_text(encoding="utf-8") == sem_before, "semantics file was modified"
    assert Path(prim).read_text(encoding="utf-8") == prim_before, "primitives file was modified"
