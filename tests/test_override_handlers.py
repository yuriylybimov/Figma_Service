"""Unit tests for override set / override list commands.

All tests are fully offline (no Playwright, no Figma).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import override_handlers as oh
from typer.testing import CliRunner
from run import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _overrides_path(tmp_path: Path) -> Path:
    return tmp_path / "overrides.normalized.json"


def _invoke_set(tmp_path, hex_, name):
    return runner.invoke(app, [
        "override", "set", hex_, name,
        "--overrides", str(_overrides_path(tmp_path)),
    ])


def _invoke_list(tmp_path):
    return runner.invoke(app, [
        "override", "list",
        "--overrides", str(_overrides_path(tmp_path)),
    ])


def _read_overrides(tmp_path):
    return json.loads(_overrides_path(tmp_path).read_text())


# ---------------------------------------------------------------------------
# _validate_hex
# ---------------------------------------------------------------------------

class TestValidateHex:
    def test_valid_lowercase(self):
        assert oh._validate_hex("#1a2b3c") == "#1a2b3c"

    def test_valid_uppercase(self):
        assert oh._validate_hex("#AABBCC") == "#AABBCC"

    def test_missing_hash_raises(self):
        with pytest.raises(Exception):
            oh._validate_hex("1a2b3c")

    def test_too_short_raises(self):
        with pytest.raises(Exception):
            oh._validate_hex("#1a2b3")

    def test_too_long_raises(self):
        with pytest.raises(Exception):
            oh._validate_hex("#1a2b3c00")


# ---------------------------------------------------------------------------
# _validate_final_name
# ---------------------------------------------------------------------------

class TestValidateFinalName:
    def test_valid_name(self):
        assert oh._validate_final_name("color/brand/navy") == "color/brand/navy"

    def test_does_not_start_with_color_raises(self):
        with pytest.raises(Exception):
            oh._validate_final_name("brand/navy")

    def test_candidate_prefix_raises(self):
        with pytest.raises(Exception):
            oh._validate_final_name("color/candidate/1a2b3c")

    def test_color_slash_only_is_valid(self):
        # Minimal valid name — starts with "color/" and not "color/candidate/"
        assert oh._validate_final_name("color/x") == "color/x"


# ---------------------------------------------------------------------------
# CLI: override set
# ---------------------------------------------------------------------------

class TestOverrideSet:
    def test_creates_file_on_first_set(self, tmp_path):
        result = _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        assert result.exit_code == 0, result.output
        assert _overrides_path(tmp_path).exists()

    def test_written_value_is_correct(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        data = _read_overrides(tmp_path)
        assert data["#1a2b3c"] == "color/brand/navy"

    def test_second_set_replaces_value(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/midnight")
        data = _read_overrides(tmp_path)
        assert data["#1a2b3c"] == "color/brand/midnight"
        assert len(data) == 1

    def test_multiple_hexes_stored_independently(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        _invoke_set(tmp_path, "#ffffff", "color/neutral/white")
        data = _read_overrides(tmp_path)
        assert data["#1a2b3c"] == "color/brand/navy"
        assert data["#ffffff"] == "color/neutral/white"

    def test_invalid_hex_exits_nonzero(self, tmp_path):
        result = _invoke_set(tmp_path, "1a2b3c", "color/brand/navy")
        assert result.exit_code != 0

    def test_name_without_color_prefix_exits_nonzero(self, tmp_path):
        result = _invoke_set(tmp_path, "#1a2b3c", "brand/navy")
        assert result.exit_code != 0

    def test_candidate_name_exits_nonzero(self, tmp_path):
        result = _invoke_set(tmp_path, "#1a2b3c", "color/candidate/1a2b3c")
        assert result.exit_code != 0

    def test_output_says_set_on_new_entry(self, tmp_path):
        result = _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        assert "Set:" in result.output

    def test_output_says_updated_on_existing_entry(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        result = _invoke_set(tmp_path, "#1a2b3c", "color/brand/midnight")
        assert "Updated:" in result.output

    def test_works_when_overrides_file_does_not_exist(self, tmp_path):
        # File absent — should create it cleanly
        result = _invoke_set(tmp_path, "#aabbcc", "color/neutral/100")
        assert result.exit_code == 0
        assert _read_overrides(tmp_path)["#aabbcc"] == "color/neutral/100"

    def test_file_is_sorted_json(self, tmp_path):
        _invoke_set(tmp_path, "#ffffff", "color/neutral/white")
        _invoke_set(tmp_path, "#000000", "color/neutral/black")
        raw = _overrides_path(tmp_path).read_text()
        data = json.loads(raw)
        keys = list(data.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# CLI: override list
# ---------------------------------------------------------------------------

class TestOverrideList:
    def test_empty_file_prints_no_overrides_message(self, tmp_path):
        result = _invoke_list(tmp_path)
        assert result.exit_code == 0
        assert "No overrides" in result.output

    def test_missing_file_prints_no_overrides_message(self, tmp_path):
        # Non-existent file is treated the same as empty
        result = _invoke_list(tmp_path)
        assert result.exit_code == 0
        assert "No overrides" in result.output

    def test_lists_set_overrides(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        result = _invoke_list(tmp_path)
        assert result.exit_code == 0
        assert "#1a2b3c" in result.output
        assert "color/brand/navy" in result.output

    def test_lists_all_overrides(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        _invoke_set(tmp_path, "#ffffff", "color/neutral/white")
        result = _invoke_list(tmp_path)
        assert "#1a2b3c" in result.output
        assert "#ffffff" in result.output

    def test_shows_count(self, tmp_path):
        _invoke_set(tmp_path, "#1a2b3c", "color/brand/navy")
        _invoke_set(tmp_path, "#ffffff", "color/neutral/white")
        result = _invoke_list(tmp_path)
        assert "2" in result.output


# ---------------------------------------------------------------------------
# Helpers: override apply-merge-proposal
# ---------------------------------------------------------------------------

_VALID_MERGE_MAP = {
    "#f1f1f1": "#f8f8f8",
    "#262626": "#2f2f2f",
    "#aaaaaa": "#9d9d9d",
}

_VALID_PROPOSAL = {
    "generated_at": "2026-04-24T14:52:25+00:00",
    "summary": {"groups_analyzed": 7, "merges_suggested": 3},
    "merges": [],
    "merge_map": _VALID_MERGE_MAP,
}


def _write_proposal(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _proposal_path(tmp_path: Path) -> Path:
    return tmp_path / "overrides.merge.proposed.json"


def _output_path(tmp_path: Path) -> Path:
    return tmp_path / "overrides.merge.json"


def _invoke_apply(tmp_path: Path, extra_args: list[str] | None = None):
    args = [
        "override", "apply-merge-proposal",
        "--proposal", str(_proposal_path(tmp_path)),
        "--out", str(_output_path(tmp_path)),
    ]
    if extra_args:
        args += extra_args
    return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# CLI: override apply-merge-proposal
# ---------------------------------------------------------------------------

class TestOverrideApplyMergeProposal:
    def test_creates_output_file(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        result = _invoke_apply(tmp_path)
        assert result.exit_code == 0, result.output
        assert _output_path(tmp_path).exists()

    def test_output_contains_only_merge_map(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        _invoke_apply(tmp_path)
        data = json.loads(_output_path(tmp_path).read_text())
        assert data == _VALID_MERGE_MAP

    def test_output_is_sorted_json(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        _invoke_apply(tmp_path)
        data = json.loads(_output_path(tmp_path).read_text())
        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_summary_printed(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        result = _invoke_apply(tmp_path)
        assert "3" in result.output
        assert "merge" in result.output.lower()

    def test_each_pair_printed(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        result = _invoke_apply(tmp_path)
        for src, canonical in _VALID_MERGE_MAP.items():
            assert src in result.output
            assert canonical in result.output

    def test_fails_if_output_exists_without_force(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        _invoke_apply(tmp_path)
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0
        assert "--force" in result.output or "--force" in (result.stderr or "")

    def test_force_overwrites_existing_output(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        _invoke_apply(tmp_path)
        result = _invoke_apply(tmp_path, ["--force"])
        assert result.exit_code == 0, result.output
        data = json.loads(_output_path(tmp_path).read_text())
        assert data == _VALID_MERGE_MAP

    def test_missing_proposal_file_exits_nonzero(self, tmp_path):
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_missing_merge_map_key_exits_nonzero(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), {"summary": {}})
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_empty_merge_map_exits_nonzero(self, tmp_path):
        _write_proposal(_proposal_path(tmp_path), {**_VALID_PROPOSAL, "merge_map": {}})
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_invalid_hex_key_exits_nonzero(self, tmp_path):
        bad = {"f1f1f1": "#f8f8f8"}  # missing leading #
        _write_proposal(_proposal_path(tmp_path), {**_VALID_PROPOSAL, "merge_map": bad})
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_invalid_hex_value_exits_nonzero(self, tmp_path):
        bad = {"#f1f1f1": "f8f8f8"}  # missing leading #
        _write_proposal(_proposal_path(tmp_path), {**_VALID_PROPOSAL, "merge_map": bad})
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_malformed_json_exits_nonzero(self, tmp_path):
        _proposal_path(tmp_path).write_text("not json", encoding="utf-8")
        result = _invoke_apply(tmp_path)
        assert result.exit_code != 0

    def test_does_not_touch_normalized_overrides(self, tmp_path):
        normalized = tmp_path / "overrides.normalized.json"
        normalized.write_text(json.dumps({"#000000": "color/neutral/black"}), encoding="utf-8")
        _write_proposal(_proposal_path(tmp_path), _VALID_PROPOSAL)
        _invoke_apply(tmp_path)
        assert json.loads(normalized.read_text()) == {"#000000": "color/neutral/black"}
