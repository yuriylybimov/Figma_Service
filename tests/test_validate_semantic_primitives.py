# tests/test_validate_semantic_primitives.py
from validate_semantic_primitives import validate_semantic_primitives


SPACING_SEED = [
    {"name": "spacing/1", "value": 4},
    {"name": "spacing/2", "value": 8},
]
RADIUS_SEED = [
    {"name": "radius/sm", "value": 4},
    {"name": "radius/md", "value": 8},
]

ALL_SEEDS = {
    "spacing": SPACING_SEED,
    "radius": RADIUS_SEED,
}


def test_valid_semantic_mapping():
    semantic = {
        "spacing/component/padding": "spacing/1",
        "radius/component/button": "radius/sm",
    }
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert errors == []


def test_unknown_primitive_reference():
    semantic = {"spacing/component/x": "spacing/99"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("spacing/99" in e for e in errors)


def test_type_mismatch_in_semantic_name():
    # semantic name starts with "spacing" but references a radius primitive
    semantic = {"spacing/component/x": "radius/sm"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("type" in e.lower() or "mismatch" in e.lower() for e in errors)


def test_semantic_name_with_unknown_prefix():
    semantic = {"unknown/x": "spacing/1"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("unknown" in e.lower() or "prefix" in e.lower() for e in errors)


def test_null_values_rejected():
    semantic = {"spacing/component/x": None}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("null" in e.lower() or "none" in e.lower() or "value" in e.lower() for e in errors)


def test_duplicate_semantic_keys_impossible():
    # JSON object keys are deduplicated by python json.loads — test that identical values do not produce false errors
    semantic = {
        "spacing/a": "spacing/1",
        "spacing/b": "spacing/1",
    }
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert errors == []
