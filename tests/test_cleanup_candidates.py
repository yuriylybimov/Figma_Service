"""Unit tests for plan cleanup-candidates — low-use filter only.

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

def _make_proposed_color(hex_, fill=1, stroke=0, status="new_candidate"):
    return {
        "hex": hex_,
        "fill_count": fill,
        "stroke_count": stroke,
        "status": status,
        "primitive_name": None,
        "paint_style_name": None,
        "duplicate_warning": False,
        "examples": [{"page": "P", "node": "N"}],
    }


def _make_detail_entry(hex_, use_count):
    return {
        "hex": hex_,
        "use_count": use_count,
        "sample_nodes": ["NodeA"],
        "sample_pages": ["PageA"],
    }


def _proposed_doc(colors):
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source_usage_file": "/tmp/usage.json",
        "scanned_pages": 1,
        "scanned_nodes": 100,
        "summary": {"unique_node_colors": len(colors), "new_candidates": len(colors),
                     "matched_to_primitives": 0, "from_paint_styles": 0},
        "colors": colors,
    }


def _detail_doc(entries):
    return entries  # usage_detail is a plain list


# ---------------------------------------------------------------------------
# _apply_use_counts
# ---------------------------------------------------------------------------

class TestApplyUseCounts:
    def test_enriches_with_use_count_from_detail(self):
        colors = [_make_proposed_color("#aabbcc", fill=3, stroke=1)]
        detail = [_make_detail_entry("#aabbcc", use_count=7)]
        result = ph._apply_use_counts(colors, detail)
        assert result[0]["use_count"] == 7

    def test_missing_hex_in_detail_gets_zero(self):
        colors = [_make_proposed_color("#000000")]
        detail = []
        result = ph._apply_use_counts(colors, detail)
        assert result[0]["use_count"] == 0

    def test_does_not_mutate_input_list(self):
        colors = [_make_proposed_color("#aabbcc")]
        detail = [_make_detail_entry("#aabbcc", use_count=5)]
        _ = ph._apply_use_counts(colors, detail)
        assert "use_count" not in colors[0]

    def test_preserves_all_original_fields(self):
        colors = [_make_proposed_color("#aabbcc", fill=10, stroke=2)]
        detail = [_make_detail_entry("#aabbcc", use_count=12)]
        result = ph._apply_use_counts(colors, detail)
        entry = result[0]
        assert entry["fill_count"] == 10
        assert entry["stroke_count"] == 2
        assert entry["status"] == "new_candidate"

    def test_multiple_colors_all_enriched(self):
        colors = [
            _make_proposed_color("#111111"),
            _make_proposed_color("#222222"),
            _make_proposed_color("#333333"),
        ]
        detail = [
            _make_detail_entry("#111111", use_count=1),
            _make_detail_entry("#222222", use_count=10),
            _make_detail_entry("#333333", use_count=5),
        ]
        result = ph._apply_use_counts(colors, detail)
        counts = {e["hex"]: e["use_count"] for e in result}
        assert counts == {"#111111": 1, "#222222": 10, "#333333": 5}


# ---------------------------------------------------------------------------
# _cleanup_candidates
# ---------------------------------------------------------------------------

class TestCleanupCandidates:
    def test_above_threshold_tagged_keep(self):
        colors = [{"hex": "#aabbcc", "use_count": 5, "status": "new_candidate"}]
        result = ph._cleanup_candidates(colors, threshold=3)
        assert result[0]["cleanup_tag"] == "keep"

    def test_at_threshold_tagged_keep(self):
        colors = [{"hex": "#aabbcc", "use_count": 3, "status": "new_candidate"}]
        result = ph._cleanup_candidates(colors, threshold=3)
        assert result[0]["cleanup_tag"] == "keep"

    def test_below_threshold_tagged_review_low_use(self):
        colors = [{"hex": "#aabbcc", "use_count": 2, "status": "new_candidate"}]
        result = ph._cleanup_candidates(colors, threshold=3)
        assert result[0]["cleanup_tag"] == "review_low_use"

    def test_zero_use_count_tagged_review_low_use(self):
        colors = [{"hex": "#aabbcc", "use_count": 0, "status": "new_candidate"}]
        result = ph._cleanup_candidates(colors, threshold=3)
        assert result[0]["cleanup_tag"] == "review_low_use"

    def test_threshold_1_keeps_any_used_color(self):
        colors = [{"hex": "#aabbcc", "use_count": 1, "status": "new_candidate"}]
        result = ph._cleanup_candidates(colors, threshold=1)
        assert result[0]["cleanup_tag"] == "keep"

    def test_does_not_mutate_input(self):
        colors = [{"hex": "#aabbcc", "use_count": 1, "status": "new_candidate"}]
        _ = ph._cleanup_candidates(colors, threshold=3)
        assert "cleanup_tag" not in colors[0]

    def test_mixed_results(self):
        colors = [
            {"hex": "#111111", "use_count": 10, "status": "new_candidate"},
            {"hex": "#222222", "use_count": 2, "status": "new_candidate"},
            {"hex": "#333333", "use_count": 3, "status": "new_candidate"},
        ]
        result = ph._cleanup_candidates(colors, threshold=3)
        tags = {e["hex"]: e["cleanup_tag"] for e in result}
        assert tags == {"#111111": "keep", "#222222": "review_low_use", "#333333": "keep"}

    def test_preserves_all_input_fields(self):
        colors = [{"hex": "#aabbcc", "use_count": 5, "status": "new_candidate", "fill_count": 3}]
        result = ph._cleanup_candidates(colors, threshold=3)
        assert result[0]["fill_count"] == 3
        assert result[0]["hex"] == "#aabbcc"


# ---------------------------------------------------------------------------
# CLI: plan cleanup-candidates
# ---------------------------------------------------------------------------

class TestCleanupCandidatesCommand:
    def _write_files(self, tmp_path, colors, detail_entries):
        proposed = tmp_path / "primitives.proposed.json"
        proposed.write_text(json.dumps(_proposed_doc(colors)), encoding="utf-8")
        detail = tmp_path / "usage_detail.json"
        detail.write_text(json.dumps(_detail_doc(detail_entries)), encoding="utf-8")
        return proposed, detail

    def test_writes_cleanup_output_file(self, tmp_path):
        colors = [_make_proposed_color("#aabbcc", fill=5)]
        detail = [_make_detail_entry("#aabbcc", use_count=5)]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        result = runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        assert result.exit_code == 0, result.output
        assert out.exists()

    def test_output_contains_colors_key(self, tmp_path):
        colors = [_make_proposed_color("#aabbcc", fill=5)]
        detail = [_make_detail_entry("#aabbcc", use_count=5)]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        data = json.loads(out.read_text())
        assert "colors" in data

    def test_output_has_cleanup_tag_on_each_entry(self, tmp_path):
        colors = [
            _make_proposed_color("#aabbcc", fill=5),
            _make_proposed_color("#001122", fill=1),
        ]
        detail = [
            _make_detail_entry("#aabbcc", use_count=5),
            _make_detail_entry("#001122", use_count=1),
        ]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        data = json.loads(out.read_text())
        for entry in data["colors"]:
            assert "cleanup_tag" in entry

    def test_default_threshold_tags_low_use_as_remove(self, tmp_path):
        colors = [
            _make_proposed_color("#aabbcc", fill=10),
            _make_proposed_color("#001122", fill=1),
        ]
        detail = [
            _make_detail_entry("#aabbcc", use_count=10),
            _make_detail_entry("#001122", use_count=1),
        ]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        data = json.loads(out.read_text())
        tags = {e["hex"]: e["cleanup_tag"] for e in data["colors"]}
        assert tags["#aabbcc"] == "keep"
        assert tags["#001122"] == "review_low_use"

    def test_custom_threshold_respected(self, tmp_path):
        colors = [_make_proposed_color("#aabbcc", fill=4)]
        detail = [_make_detail_entry("#aabbcc", use_count=4)]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
            "--threshold", "10",
        ])

        data = json.loads(out.read_text())
        assert data["colors"][0]["cleanup_tag"] == "review_low_use"

    def test_output_has_use_count_on_each_entry(self, tmp_path):
        colors = [_make_proposed_color("#aabbcc", fill=5)]
        detail = [_make_detail_entry("#aabbcc", use_count=5)]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        data = json.loads(out.read_text())
        assert data["colors"][0]["use_count"] == 5

    def test_output_has_summary_with_counts(self, tmp_path):
        colors = [
            _make_proposed_color("#aabbcc", fill=5),
            _make_proposed_color("#001122", fill=1),
        ]
        detail = [
            _make_detail_entry("#aabbcc", use_count=5),
            _make_detail_entry("#001122", use_count=1),
        ]
        proposed, det = self._write_files(tmp_path, colors, detail)
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        data = json.loads(out.read_text())
        assert "summary" in data
        assert data["summary"]["keep"] == 1
        assert data["summary"]["review_low_use"] == 1

    def test_missing_proposed_file_exits_nonzero(self, tmp_path):
        detail = tmp_path / "detail.json"
        detail.write_text("[]", encoding="utf-8")

        result = runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(tmp_path / "nonexistent.json"),
            "--detail", str(detail),
            "--out", str(tmp_path / "out.json"),
        ])
        assert result.exit_code != 0

    def test_missing_detail_file_exits_nonzero(self, tmp_path):
        proposed = tmp_path / "proposed.json"
        proposed.write_text(json.dumps(_proposed_doc([])), encoding="utf-8")

        result = runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(tmp_path / "nonexistent.json"),
            "--out", str(tmp_path / "out.json"),
        ])
        assert result.exit_code != 0

    def test_malformed_proposed_file_exits_nonzero(self, tmp_path):
        proposed = tmp_path / "proposed.json"
        proposed.write_text('{"no_colors_key": true}', encoding="utf-8")
        detail = tmp_path / "detail.json"
        detail.write_text("[]", encoding="utf-8")

        result = runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(detail),
            "--out", str(tmp_path / "out.json"),
        ])
        assert result.exit_code != 0

    def test_does_not_modify_proposed_file(self, tmp_path):
        colors = [_make_proposed_color("#aabbcc", fill=5)]
        detail = [_make_detail_entry("#aabbcc", use_count=5)]
        proposed, det = self._write_files(tmp_path, colors, detail)
        original = proposed.read_text()
        out = tmp_path / "primitives.cleanup.json"

        runner.invoke(app, [
            "plan", "cleanup-candidates",
            "--proposed", str(proposed),
            "--detail", str(det),
            "--out", str(out),
        ])

        assert proposed.read_text() == original
