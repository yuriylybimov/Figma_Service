from suggest_primitives import suggest_primitive_entries, _count_and_rank, _group_with_raw, _sanitize_family_name


def test_count_and_rank_basic():
    result = _count_and_rank([4, 8, 4, 16, 8, 4])
    # 4→3, 8→2, 16→1
    assert result[4.0] == 3
    assert result[8.0] == 2
    assert result[16.0] == 1


def test_count_and_rank_rounds_to_half():
    result = _count_and_rank([4.1, 4.2, 8.0], round_to=0.5)
    # 4.1 and 4.2 both round to 4.0
    assert result[4.0] == 2
    assert result[8.0] == 1


def test_count_and_rank_opacity_rounds_to_two_decimals():
    result = _count_and_rank([0.501, 0.499, 0.1], round_to=0.01)
    assert result[0.50] == 2
    assert result[0.1] == 1


def test_sanitize_family_name():
    assert _sanitize_family_name("Inter") == "inter"
    assert _sanitize_family_name("SF Pro Display") == "sf-pro-display"
    assert _sanitize_family_name("JetBrains Mono") == "jetbrains-mono"


# ---------------------------------------------------------------------------
# raw_values — present on all FLOAT entries
# ---------------------------------------------------------------------------

def test_suggest_entries_include_raw_values():
    raw = {"spacing": [4, 8, 4, 16]}
    result = suggest_primitive_entries("spacing", raw)
    for e in result:
        assert "raw_values" in e, f"raw_values missing on {e}"
        assert isinstance(e["raw_values"], list)


def test_suggest_raw_values_are_sorted():
    raw = {"spacing": [8, 4, 4]}
    result = suggest_primitive_entries("spacing", raw)
    for e in result:
        assert e["raw_values"] == sorted(e["raw_values"])


def test_suggest_raw_values_contain_original_values():
    # 4.0 and 4.1 round to the same bucket; raw_values must list both originals
    raw = {"spacing": [4.0, 4.1, 8.0]}
    result = suggest_primitive_entries("spacing", raw)
    bucket_4 = next(e for e in result if e["value"] == 4.0)
    assert sorted(bucket_4["raw_values"]) == [4.0, 4.1]
    bucket_8 = next(e for e in result if e["value"] == 8.0)
    assert bucket_8["raw_values"] == [8.0]


def test_suggest_raw_values_use_count_matches_length():
    raw = {"spacing": [4, 4, 4, 8, 8, 16]}
    result = suggest_primitive_entries("spacing", raw)
    for e in result:
        assert e["use_count"] == len(e["raw_values"])


def test_suggest_font_family_has_no_raw_values():
    # STRING type — raw_values field not added
    raw = {"font_family": ["Inter", "Inter"]}
    result = suggest_primitive_entries("font-family", raw)
    for e in result:
        assert "raw_values" not in e


# ---------------------------------------------------------------------------
# _group_with_raw helper
# ---------------------------------------------------------------------------

def test_group_with_raw_basic():
    groups = _group_with_raw([4, 8, 4, 16], round_to=0.5)
    assert groups[4.0]["count"] == 2
    assert sorted(groups[4.0]["raw"]) == [4.0, 4.0]
    assert groups[8.0]["count"] == 1
    assert groups[16.0]["count"] == 1


def test_group_with_raw_merges_near_values():
    groups = _group_with_raw([3.9, 4.1, 8.0], round_to=0.5)
    # both 3.9 and 4.1 round to 4.0
    assert 4.0 in groups
    assert groups[4.0]["count"] == 2
    assert sorted(groups[4.0]["raw"]) == [3.9, 4.1]


# ---------------------------------------------------------------------------
# 4px normalization for spacing / radius / line-height
# ---------------------------------------------------------------------------

def test_spacing_4px_normalization():
    # 3 and 5 both round to 4 under 4px grid
    raw = {"spacing": [3, 4, 5, 8]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert 4.0 in values
    assert 8.0 in values
    assert 3.0 not in values
    assert 5.0 not in values


def test_spacing_4px_raw_values_preserved():
    # 4 and 5 both round to 4 under 4px grid; raw_values must list both originals.
    # (3 is excluded by SPACING_MIN; 6 rounds to 8, not 4.)
    raw = {"spacing": [4, 5, 8]}
    result = suggest_primitive_entries("spacing", raw)
    bucket_4 = next(e for e in result if e["value"] == 4.0)
    assert sorted(bucket_4["raw_values"]) == [4.0, 5.0]


def test_radius_4px_normalization():
    raw = {"radius": [3, 4, 5, 8, 12]}
    result = suggest_primitive_entries("radius", raw)
    values = [e["value"] for e in result]
    assert 4.0 in values
    assert 8.0 in values
    assert 12.0 in values
    assert 3.0 not in values
    assert 5.0 not in values


def test_line_height_4px_normalization():
    raw = {"line_height": [19, 20, 21, 24]}
    result = suggest_primitive_entries("line-height", raw)
    values = [e["value"] for e in result]
    assert 20.0 in values
    assert 24.0 in values
    assert 19.0 not in values
    assert 21.0 not in values


def test_line_height_4px_raw_values_preserved():
    raw = {"line_height": [19, 20, 21, 24]}
    result = suggest_primitive_entries("line-height", raw)
    bucket_20 = next(e for e in result if e["value"] == 20.0)
    assert sorted(bucket_20["raw_values"]) == [19.0, 20.0, 21.0]
    bucket_24 = next(e for e in result if e["value"] == 24.0)
    assert bucket_24["raw_values"] == [24.0]


def test_stroke_width_not_4px_normalized():
    # stroke-width uses 0.5 step — 1.3 rounds to 1.5, not to 0 or 4
    raw = {"stroke_width": [1.3, 2.0]}
    result = suggest_primitive_entries("stroke-width", raw)
    values = [e["value"] for e in result]
    assert 1.5 in values
    assert 2.0 in values


# ---------------------------------------------------------------------------
# Full-radius candidate marker
# ---------------------------------------------------------------------------

def test_full_radius_candidate_marker_present():
    raw = {"radius": [0, 4, 9999, 10000]}
    result = suggest_primitive_entries("radius", raw)
    full = [e for e in result if e.get("value", 0) >= 9999]
    assert len(full) == 2
    for e in full:
        assert e.get("candidate") == "full-radius", f"marker missing on {e}"


def test_normal_radius_has_no_candidate_marker():
    raw = {"radius": [0, 4, 8, 12]}
    result = suggest_primitive_entries("radius", raw)
    for e in result:
        assert "candidate" not in e


def test_full_radius_raw_values_included():
    raw = {"radius": [9999, 9999, 10000]}
    result = suggest_primitive_entries("radius", raw)
    bucket = next(e for e in result if e["value"] == 9999.0)
    assert 9999 in bucket["raw_values"] or 9999.0 in bucket["raw_values"]


# ---------------------------------------------------------------------------
# Existing behaviour (unchanged)
# ---------------------------------------------------------------------------

def test_suggest_spacing_entries():
    raw = {"spacing": [4, 8, 4, 16]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert values == sorted(values)  # ascending
    assert 4.0 in values
    assert 8.0 in values
    assert 16.0 in values
    for e in result:
        assert e["name"].startswith("spacing/")
        assert "use_count" in e


def test_suggest_spacing_names_are_sequential():
    raw = {"spacing": [4, 8, 16]}
    result = suggest_primitive_entries("spacing", raw)
    names = [e["name"] for e in result]
    assert names == ["spacing/1", "spacing/2", "spacing/3"]


def test_suggest_font_family_uses_sanitized_name():
    raw = {"font_family": ["Inter", "Inter", "SF Pro Display"]}
    result = suggest_primitive_entries("font-family", raw)
    names = [e["name"] for e in result]
    assert "font-family/inter" in names
    assert "font-family/sf-pro-display" in names


def test_suggest_font_family_values_are_strings():
    raw = {"font_family": ["Inter"]}
    result = suggest_primitive_entries("font-family", raw)
    assert result[0]["value"] == "Inter"


def test_suggest_returns_empty_for_empty_input():
    raw = {"spacing": []}
    result = suggest_primitive_entries("spacing", raw)
    assert result == []


def test_suggest_unknown_type_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown type"):
        suggest_primitive_entries("color", {})


def test_suggest_opacity_values_capped_at_1():
    raw = {"opacity": [0.5, 0.5, 1.0, 0.1]}
    result = suggest_primitive_entries("opacity", raw)
    for e in result:
        assert 0.0 <= e["value"] <= 1.0


def test_suggest_deduplicates_after_rounding():
    # 4.0 and 4.1 both round to 4.0; should appear only once
    raw = {"spacing": [4.0, 4.1, 8.0]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert values.count(4.0) == 1
    assert len(values) == 2


def test_suggest_large_radius_preserved():
    # >= 9999 treated as full-radius candidate; value must appear as-is
    raw = {"radius": [0, 4, 9999, 10000]}
    result = suggest_primitive_entries("radius", raw)
    values = [e["value"] for e in result]
    assert 9999.0 in values
    assert 10000.0 in values
    assert 0.0 in values
    assert 4.0 in values


def test_spacing_below_min_excluded():
    # Values < 4 are not design-system spacing — dropped before grouping.
    raw = {"spacing": [1, 2, 3, 8]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert 8.0 in values
    # 1, 2, 3 must not appear in any bucket
    assert all(v >= 4.0 for v in values)


def test_spacing_above_max_excluded():
    # Values > 128 are likely layout dimensions, not spacing tokens.
    raw = {"spacing": [8, 16, 129, 256]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert 8.0 in values
    assert 16.0 in values
    assert all(v <= 128.0 for v in values)


def test_spacing_at_boundaries_included():
    # 4 and 128 are exactly at the bounds and must be kept.
    raw = {"spacing": [4, 128]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert 4.0 in values
    assert 128.0 in values


def test_spacing_range_does_not_affect_other_types():
    # The SPACING_MIN/MAX filter must not apply to font-size or other FLOAT types.
    raw = {"font_size": [2, 11, 13, 200]}
    result = suggest_primitive_entries("font-size", raw)
    values = [e["value"] for e in result]
    assert 2.0 in values
    assert 200.0 in values


def test_suggest_use_count_correct():
    raw = {"spacing": [4, 4, 4, 8, 8, 16]}
    result = suggest_primitive_entries("spacing", raw)
    by_value = {e["value"]: e["use_count"] for e in result}
    assert by_value[4.0] == 3
    assert by_value[8.0] == 2
    assert by_value[16.0] == 1


def test_suggest_values_sorted_ascending():
    raw = {"font_size": [24, 13, 15, 32, 11]}
    result = suggest_primitive_entries("font-size", raw)
    values = [e["value"] for e in result]
    assert values == sorted(values)


def test_suggest_letter_spacing_zero_included():
    raw = {"letter_spacing": [0, 0, -0.5]}
    result = suggest_primitive_entries("letter-spacing", raw)
    values = [e["value"] for e in result]
    assert 0.0 in values
    assert -0.5 in values
