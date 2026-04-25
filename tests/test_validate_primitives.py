from validate_primitives import validate_primitive_seed


def test_valid_spacing_seed():
    entries = [
        {"name": "spacing/1", "value": 4.0},
        {"name": "spacing/2", "value": 8.0},
    ]
    errors = validate_primitive_seed("spacing", entries)
    assert errors == []


def test_wrong_type_key_rejected():
    errors = validate_primitive_seed("color", [])
    assert any("unknown type" in e.lower() for e in errors)


def test_float_type_rejects_string_value():
    entries = [{"name": "spacing/1", "value": "4px"}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("value" in e.lower() for e in errors)


def test_string_type_accepts_string_value():
    entries = [{"name": "font-family/sans", "value": "Inter"}]
    errors = validate_primitive_seed("font-family", entries)
    assert errors == []


def test_string_type_rejects_float_value():
    entries = [{"name": "font-family/sans", "value": 14.0}]
    errors = validate_primitive_seed("font-family", entries)
    assert any("value" in e.lower() for e in errors)


def test_name_must_start_with_type_key():
    entries = [{"name": "wrong/1", "value": 4.0}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("name" in e.lower() for e in errors)


def test_duplicate_names_rejected():
    entries = [
        {"name": "spacing/1", "value": 4.0},
        {"name": "spacing/1", "value": 8.0},
    ]
    errors = validate_primitive_seed("spacing", entries)
    assert any("duplicate" in e.lower() for e in errors)


def test_missing_name_field_rejected():
    entries = [{"value": 4.0}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("name" in e.lower() for e in errors)


def test_missing_value_field_rejected():
    entries = [{"name": "spacing/1"}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("value" in e.lower() for e in errors)


def test_opacity_range_1_0_is_valid():
    entries = [{"name": "opacity/subtle", "value": 0.5}]
    errors = validate_primitive_seed("opacity", entries)
    assert errors == []


def test_opacity_above_1_rejected():
    entries = [{"name": "opacity/full", "value": 1.5}]
    errors = validate_primitive_seed("opacity", entries)
    assert any("opacity" in e.lower() or "range" in e.lower() for e in errors)
