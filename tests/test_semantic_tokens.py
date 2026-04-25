"""Tests for semantic token normalize+validate logic (Phase D)."""
import pytest

from plan_colors import _build_and_validate_semantic_normalized

PRIMITIVES = [
    {"final_name": "color/gray/900"},
    {"final_name": "color/gray/500"},
    {"final_name": "color/gray/100"},
]


def build(seed, overrides=None):
    return _build_and_validate_semantic_normalized(seed, PRIMITIVES, overrides or {})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_seed_returns_flat_map():
    seed = {
        "color/text/default": "color/gray/900",
        "color/text/disabled": "color/gray/500",
        "color/surface/default": "color/gray/100",
    }
    result = build(seed)
    assert result == seed


def test_override_wins_over_seed():
    seed = {"color/text/default": "color/gray/500"}
    overrides = {"color/text/default": "color/gray/900"}
    result = build(seed, overrides)
    assert result["color/text/default"] == "color/gray/900"


def test_override_adds_new_entry():
    seed = {"color/text/default": "color/gray/900"}
    overrides = {"color/border/default": "color/gray/500"}
    result = build(seed, overrides)
    assert result["color/border/default"] == "color/gray/500"
    assert result["color/text/default"] == "color/gray/900"


# ---------------------------------------------------------------------------
# Failure: missing primitive
# ---------------------------------------------------------------------------

def test_missing_primitive_fails():
    seed = {"color/text/default": "color/blue/500"}
    with pytest.raises(ValueError, match="not found in primitives"):
        build(seed)


# ---------------------------------------------------------------------------
# Failure: bad role
# ---------------------------------------------------------------------------

def test_bad_role_fails():
    seed = {"color/emotion/default": "color/gray/900"}
    with pytest.raises(ValueError, match="role"):
        build(seed)


# ---------------------------------------------------------------------------
# Failure: bad state
# ---------------------------------------------------------------------------

def test_bad_state_fails():
    seed = {"color/text/pressed": "color/gray/900"}
    with pytest.raises(ValueError, match="state"):
        build(seed)


# ---------------------------------------------------------------------------
# Failure: raw hex value
# ---------------------------------------------------------------------------

def test_raw_hex_value_fails():
    seed = {"color/text/default": "#262626"}
    with pytest.raises(ValueError, match="raw hex"):
        build(seed)


# ---------------------------------------------------------------------------
# Failure: semantic-to-semantic alias
# ---------------------------------------------------------------------------

def test_semantic_to_semantic_alias_fails():
    seed = {
        "color/text/default": "color/gray/900",
        "color/text/disabled": "color/text/default",
    }
    with pytest.raises(ValueError, match="semantic name"):
        build(seed)
