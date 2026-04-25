from primitive_types import PRIMITIVE_TYPES, PrimitiveTypeDef


def test_registry_contains_expected_types():
    expected = {
        "spacing", "radius", "stroke-width",
        "font-family", "font-weight", "font-size",
        "line-height", "letter-spacing", "opacity",
    }
    assert set(PRIMITIVE_TYPES.keys()) == expected


def test_each_type_has_required_fields():
    for name, td in PRIMITIVE_TYPES.items():
        assert isinstance(td, PrimitiveTypeDef), name
        assert td.figma_type in ("FLOAT", "STRING"), name
        assert isinstance(td.unit, (str, type(None))), name


def test_figma_type_assignments():
    assert PRIMITIVE_TYPES["font-family"].figma_type == "STRING"
    float_keys = {"spacing", "radius", "stroke-width", "font-weight", "font-size",
                  "line-height", "letter-spacing", "opacity"}
    for key in float_keys:
        assert PRIMITIVE_TYPES[key].figma_type == "FLOAT", key
