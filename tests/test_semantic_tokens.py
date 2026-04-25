"""Tests for semantic token normalize+validate logic."""
import pytest

from plan_colors import _build_and_validate_semantic_normalized, _suggest_semantic_tokens

PRIMITIVES = [
    {"final_name": "color/gray/900"},
    {"final_name": "color/gray/500"},
    {"final_name": "color/gray/100"},
]


def build(seed, overrides=None):
    return _build_and_validate_semantic_normalized(seed, PRIMITIVES, overrides or {})


def test_valid_seed_returns_flat_map():
    seed = {
        "color/text/primary": "color/gray/900",
        "color/text/disabled": "color/gray/500",
        "color/surface/primary": "color/gray/100",
    }
    result = build(seed)
    assert result == seed


def test_override_wins_over_seed():
    seed = {"color/text/primary": "color/gray/500"}
    overrides = {"color/text/primary": "color/gray/900"}
    result = build(seed, overrides)
    assert result["color/text/primary"] == "color/gray/900"


def test_override_adds_new_entry():
    seed = {"color/text/primary": "color/gray/900"}
    overrides = {"color/border/primary": "color/gray/500"}
    result = build(seed, overrides)
    assert result["color/border/primary"] == "color/gray/500"
    assert result["color/text/primary"] == "color/gray/900"


def test_missing_primitive_fails():
    seed = {"color/text/primary": "color/blue/500"}
    with pytest.raises(ValueError, match="not found in primitives"):
        build(seed)


def test_bad_role_fails():
    seed = {"color/emotion/primary": "color/gray/900"}
    with pytest.raises(ValueError, match="role"):
        build(seed)


def test_bad_state_fails():
    seed = {"color/text/pressed": "color/gray/900"}
    with pytest.raises(ValueError, match="state"):
        build(seed)


def test_raw_hex_value_fails():
    seed = {"color/text/primary": "#262626"}
    with pytest.raises(ValueError, match="raw hex"):
        build(seed)


def test_semantic_to_semantic_alias_fails():
    seed = {
        "color/text/primary": "color/gray/900",
        "color/text/disabled": "color/text/primary",
    }
    with pytest.raises(ValueError, match="semantic name"):
        build(seed)


# ── _suggest_semantic_tokens ──────────────────────────────────────────────────

GRAY_PRIMITIVES = [
    {"final_name": "color/gray/900", "hex": "#1a1a1a"},  # darkest
    {"final_name": "color/gray/500", "hex": "#737373"},  # mid
    {"final_name": "color/gray/300", "hex": "#b0b0b0"},  # light-mid
    {"final_name": "color/gray/100", "hex": "#f5f5f5"},  # lightest
]


def test_suggest_canvas_primary_is_lightest():
    result = _suggest_semantic_tokens(GRAY_PRIMITIVES)
    assert result["color/canvas/primary"] == "color/gray/100"


def test_suggest_surface_primary_is_next_lightest():
    result = _suggest_semantic_tokens(GRAY_PRIMITIVES)
    assert result["color/surface/primary"] == "color/gray/300"


def test_suggest_text_primary_is_darkest():
    result = _suggest_semantic_tokens(GRAY_PRIMITIVES)
    assert result["color/text/primary"] == "color/gray/900"


def test_suggest_surface_primary_skipped_when_only_one_gray():
    primitives = [{"final_name": "color/gray/500", "hex": "#737373"}]
    result = _suggest_semantic_tokens(primitives)
    assert "color/surface/primary" not in result


def test_suggest_canvas_primary_present_when_only_one_gray():
    primitives = [{"final_name": "color/gray/500", "hex": "#737373"}]
    result = _suggest_semantic_tokens(primitives)
    assert result["color/canvas/primary"] == "color/gray/500"


def test_suggest_duplicate_values_allowed_across_roles():
    # text/disabled and border/primary may resolve to the same primitive
    primitives = [
        {"final_name": "color/gray/900", "hex": "#1a1a1a"},
        {"final_name": "color/gray/100", "hex": "#f5f5f5"},
    ]
    result = _suggest_semantic_tokens(primitives)
    # Both should be present even if they share a value
    assert "color/text/disabled" in result
    assert "color/border/primary" in result


def test_suggest_accent_primary_from_saturated_non_gray():
    primitives = GRAY_PRIMITIVES + [
        {"final_name": "color/blue/500", "hex": "#3b82f6"},
    ]
    result = _suggest_semantic_tokens(primitives)
    assert result["color/accent/primary"] == "color/blue/500"


def test_suggest_no_accent_when_only_grays():
    result = _suggest_semantic_tokens(GRAY_PRIMITIVES)
    assert "color/accent/primary" not in result


def test_suggest_fixed_colors_excluded_from_accent():
    primitives = [
        {"final_name": "color/gray/500", "hex": "#737373"},
        {"final_name": "color/white", "hex": "#ffffff"},
        {"final_name": "color/black", "hex": "#000000"},
    ]
    result = _suggest_semantic_tokens(primitives)
    assert "color/accent/primary" not in result


def test_suggest_all_keys_are_valid_semantic_names():
    from plan_colors import _validate_semantic_name
    result = _suggest_semantic_tokens(GRAY_PRIMITIVES)
    for name in result:
        assert _validate_semantic_name(name) is None, f"{name!r} failed validation"


def test_suggest_empty_primitives_returns_empty():
    assert _suggest_semantic_tokens([]) == {}


# ── Palette scaling: 9-stop gray ramp ────────────────────────────────────────
# Palette: gray/50 (near-white) … gray/900 (near-black), no chromatic colours.
# Verifies that heuristics remain correct when the gray ramp is denser and that
# icon/accent roles are never auto-suggested (they are reserved for explicit use).

_NINE_STOP_GRAYS = [
    {"final_name": "color/gray/50",  "hex": "#fafafa"},  # lightest
    {"final_name": "color/gray/100", "hex": "#f5f5f5"},
    {"final_name": "color/gray/200", "hex": "#e5e5e5"},
    {"final_name": "color/gray/300", "hex": "#d4d4d4"},
    {"final_name": "color/gray/400", "hex": "#a3a3a3"},
    {"final_name": "color/gray/500", "hex": "#737373"},  # ≈ mid-scale
    {"final_name": "color/gray/600", "hex": "#525252"},
    {"final_name": "color/gray/700", "hex": "#404040"},
    {"final_name": "color/gray/900", "hex": "#171717"},  # darkest
]


def test_scale_text_primary_is_darkest_gray():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    assert result["color/text/primary"] == "color/gray/900"


def test_scale_text_disabled_is_nearest_lighter_than_text_primary():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    # gray/700 is the next step above gray/900 in the ramp
    assert result["color/text/disabled"] == "color/gray/700"


def test_scale_canvas_primary_is_lightest_gray():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    assert result["color/canvas/primary"] == "color/gray/50"


def test_scale_surface_primary_is_second_lightest_gray():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    assert result["color/surface/primary"] == "color/gray/100"


def test_scale_border_primary_is_mid_scale_gray():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    # gray/400 (#a3a3a3, lum≈0.366) is closest to L=0.50 in this ramp;
    # gray/500 (#737373, lum≈0.171) is farther away despite the name suggesting "mid"
    assert result["color/border/primary"] == "color/gray/400"


def test_scale_no_icon_suggestion():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    assert not any(k.startswith("color/icon/") for k in result)


def test_scale_no_accent_suggestion():
    result = _suggest_semantic_tokens(_NINE_STOP_GRAYS)
    assert "color/accent/primary" not in result


# ── Contract test: frozen exact mapping for 9-stop palette ───────────────────
# Asserts the specific primitive each semantic role resolves to.
# If any assertion fails, the heuristic changed — update invariants comment too.

_CONTRACT_PALETTE = [
    {"final_name": "color/gray/50",  "hex": "#fafafa"},
    {"final_name": "color/gray/100", "hex": "#f5f5f5"},
    {"final_name": "color/gray/200", "hex": "#e5e5e5"},
    {"final_name": "color/gray/300", "hex": "#d4d4d4"},
    {"final_name": "color/gray/400", "hex": "#a3a3a3"},
    {"final_name": "color/gray/500", "hex": "#737373"},
    {"final_name": "color/gray/600", "hex": "#525252"},
    {"final_name": "color/gray/700", "hex": "#404040"},
    {"final_name": "color/gray/900", "hex": "#171717"},
]


def test_semantic_mapping_contract_9_palette():
    result = _suggest_semantic_tokens(_CONTRACT_PALETTE)
    assert result["color/text/primary"]   == "color/gray/900"
    assert result["color/text/disabled"]  == "color/gray/700"
    assert result["color/canvas/primary"] == "color/gray/50"
    assert result["color/surface/primary"] == "color/gray/100"
    assert result["color/border/primary"] == "color/gray/400"
