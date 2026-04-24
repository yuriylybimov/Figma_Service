"""Unit tests for plan deduplicate-primitives — HSL-delta grouping.

All tests are fully offline (no Playwright, no Figma).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import plan_handlers as ph
from typer.testing import CliRunner
from run import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _color(hex_, use_count=1, cleanup_tag="keep"):
    return {"hex": hex_, "use_count": use_count, "cleanup_tag": cleanup_tag}


def _cleanup_doc(colors):
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source_proposed_file": "/tmp/proposed.json",
        "source_detail_file": "/tmp/detail.json",
        "threshold": 3,
        "summary": {"total": len(colors), "keep": len(colors), "review_low_use": 0},
        "colors": colors,
    }


# ---------------------------------------------------------------------------
# _hsl_delta
# ---------------------------------------------------------------------------

class TestHslDelta:
    def test_identical_colors_have_zero_delta(self):
        assert ph._hsl_delta("#ff0000", "#ff0000") == pytest.approx(0.0)

    def test_black_and_white_have_large_delta(self):
        delta = ph._hsl_delta("#000000", "#ffffff")
        assert delta > 0.4

    def test_near_identical_grays_have_small_delta(self):
        # #1a1a1a vs #1b1b1b — one step apart
        delta = ph._hsl_delta("#1a1a1a", "#1b1b1b")
        assert delta < 0.02

    def test_hue_wraps_correctly(self):
        # Red at opposite ends of the hue wheel should be close
        delta_wrap = ph._hsl_delta("#ff0000", "#ff0010")
        delta_direct = ph._hsl_delta("#000000", "#ffffff")
        assert delta_wrap < delta_direct

    def test_symmetry(self):
        assert ph._hsl_delta("#aabbcc", "#112233") == pytest.approx(
            ph._hsl_delta("#112233", "#aabbcc")
        )


# ---------------------------------------------------------------------------
# _group_near_duplicates
# ---------------------------------------------------------------------------

class TestGroupNearDuplicates:
    def test_single_color_produces_one_singleton_group(self):
        colors = [_color("#ff0000")]
        groups = ph._group_near_duplicates(colors, threshold=0.04)
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_two_very_different_colors_stay_separate(self):
        colors = [_color("#000000"), _color("#ffffff")]
        groups = ph._group_near_duplicates(colors, threshold=0.04)
        assert len(groups) == 2

    def test_two_near_identical_grays_merge(self):
        colors = [_color("#1a1a1a"), _color("#1b1b1b")]
        groups = ph._group_near_duplicates(colors, threshold=0.04)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_three_colors_two_close_one_far(self):
        colors = [_color("#1a1a1a"), _color("#1b1b1b"), _color("#ffffff")]
        groups = ph._group_near_duplicates(colors, threshold=0.04)
        assert len(groups) == 2
        sizes = sorted(len(g) for g in groups)
        assert sizes == [1, 2]

    def test_threshold_zero_never_merges(self):
        colors = [_color("#1a1a1a"), _color("#1a1a1a")]  # same hex, delta == 0
        # delta == 0 is NOT < 0, so even identical hexes don't merge at threshold=0
        groups = ph._group_near_duplicates(colors, threshold=0.0)
        assert len(groups) == 2

    def test_empty_input_returns_empty(self):
        assert ph._group_near_duplicates([], threshold=0.04) == []


# ---------------------------------------------------------------------------
# _deduplicate_primitives
# ---------------------------------------------------------------------------

class TestDeduplicatePrimitives:
    def test_singleton_has_keep_recommendation(self):
        colors = [_color("#ff0000", use_count=5)]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert len(result) == 1
        assert result[0]["recommendation"] == "keep"
        assert result[0]["canonical_hex"] == "#ff0000"

    def test_near_duplicates_get_merge_recommendation(self):
        colors = [_color("#1a1a1a", use_count=3), _color("#1b1b1b", use_count=7)]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert len(result) == 1
        assert result[0]["recommendation"] == "merge"

    def test_canonical_is_highest_use_count(self):
        colors = [_color("#1a1a1a", use_count=3), _color("#1b1b1b", use_count=7)]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert result[0]["canonical_hex"] == "#1b1b1b"

    def test_canonical_tie_broken_by_hex_string(self):
        # Same use_count — higher hex string wins (max of strings)
        colors = [_color("#1a1a1a", use_count=5), _color("#1b1b1b", use_count=5)]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert result[0]["canonical_hex"] == "#1b1b1b"

    def test_members_sorted_by_use_count_descending(self):
        colors = [_color("#1a1a1a", use_count=1), _color("#1b1b1b", use_count=9)]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        counts = [m["use_count"] for m in result[0]["members"]]
        assert counts == sorted(counts, reverse=True)

    def test_members_include_cleanup_tag(self):
        colors = [_color("#1a1a1a", use_count=2, cleanup_tag="review_low_use")]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert result[0]["members"][0]["cleanup_tag"] == "review_low_use"

    def test_input_not_mutated(self):
        original = [_color("#1a1a1a", use_count=3), _color("#1b1b1b", use_count=7)]
        import copy
        snapshot = copy.deepcopy(original)
        ph._deduplicate_primitives(original, threshold=0.04)
        assert original == snapshot

    def test_merge_groups_sorted_before_singletons(self):
        colors = [
            _color("#ffffff", use_count=10),   # isolated
            _color("#1a1a1a", use_count=3),
            _color("#1b1b1b", use_count=7),    # these two merge
        ]
        result = ph._deduplicate_primitives(colors, threshold=0.04)
        assert result[0]["recommendation"] == "merge"

    def test_empty_input_returns_empty(self):
        assert ph._deduplicate_primitives([], threshold=0.04) == []


# ---------------------------------------------------------------------------
# CLI: plan deduplicate-primitives
# ---------------------------------------------------------------------------

class TestDeduplicatePrimitivesCommand:
    def _write_cleanup(self, tmp_path, colors):
        p = tmp_path / "primitives.cleanup.json"
        p.write_text(json.dumps(_cleanup_doc(colors)), encoding="utf-8")
        return p

    def test_exit_code_zero_on_valid_input(self, tmp_path):
        cleanup = self._write_cleanup(tmp_path, [_color("#ff0000", use_count=5)])
        out = tmp_path / "primitives.dedup.json"
        result = runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
        ])
        assert result.exit_code == 0, result.output

    def test_output_file_created(self, tmp_path):
        cleanup = self._write_cleanup(tmp_path, [_color("#ff0000", use_count=5)])
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
        ])
        assert out.exists()

    def test_output_has_groups_key(self, tmp_path):
        cleanup = self._write_cleanup(tmp_path, [_color("#ff0000", use_count=5)])
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
        ])
        data = json.loads(out.read_text())
        assert "groups" in data

    def test_output_has_summary_key(self, tmp_path):
        cleanup = self._write_cleanup(tmp_path, [_color("#ff0000", use_count=5)])
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
        ])
        data = json.loads(out.read_text())
        assert "summary" in data
        assert "merge_groups" in data["summary"]
        assert "singletons" in data["summary"]

    def test_near_duplicates_produce_merge_group_in_output(self, tmp_path):
        colors = [_color("#1a1a1a", use_count=3), _color("#1b1b1b", use_count=7)]
        cleanup = self._write_cleanup(tmp_path, colors)
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
        ])
        data = json.loads(out.read_text())
        assert data["summary"]["merge_groups"] == 1
        assert data["groups"][0]["recommendation"] == "merge"
        assert data["groups"][0]["canonical_hex"] == "#1b1b1b"

    def test_custom_threshold_respected(self, tmp_path):
        # #1a1a1a vs #ffffff are far apart regardless of threshold direction;
        # use a threshold of 1.0 (max) to force everything to merge
        colors = [_color("#1a1a1a", use_count=3), _color("#ffffff", use_count=7)]
        cleanup = self._write_cleanup(tmp_path, colors)
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
            "--threshold", "1.0",
        ])
        data = json.loads(out.read_text())
        assert data["summary"]["merge_groups"] == 1

    def test_missing_cleanup_file_exits_nonzero(self, tmp_path):
        out = tmp_path / "primitives.dedup.json"
        result = runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(tmp_path / "nonexistent.json"),
            "--out", str(out),
        ])
        assert result.exit_code != 0

    def test_output_records_threshold_used(self, tmp_path):
        cleanup = self._write_cleanup(tmp_path, [_color("#ff0000", use_count=5)])
        out = tmp_path / "primitives.dedup.json"
        runner.invoke(app, [
            "plan", "deduplicate-primitives",
            "--cleanup", str(cleanup),
            "--out", str(out),
            "--threshold", "0.07",
        ])
        data = json.loads(out.read_text())
        assert data["hsl_delta_threshold"] == pytest.approx(0.07)
