"""Validates a primitive token seed list against the type registry."""

from primitive_types import PRIMITIVE_TYPES


def validate_primitive_seed(type_key: str, entries: list[dict]) -> list[str]:
    """Return a list of error strings; empty means valid."""
    errors: list[str] = []

    if type_key not in PRIMITIVE_TYPES:
        errors.append(f"Unknown type key '{type_key}'. Valid: {sorted(PRIMITIVE_TYPES.keys())}")
        return errors

    td = PRIMITIVE_TYPES[type_key]
    seen_names: set[str] = set()

    for i, entry in enumerate(entries):
        label = f"Entry {i}"

        if "name" not in entry:
            errors.append(f"{label}: missing 'name' field")
            continue
        if "value" not in entry:
            errors.append(f"{label}: missing 'value' field")
            continue

        name: str = entry["name"]
        value = entry["value"]
        label = f"Entry '{name}'"

        if not name.startswith(f"{type_key}/"):
            errors.append(f"{label}: name must start with '{type_key}/', got '{name}'")

        if name in seen_names:
            errors.append(f"Duplicate name: '{name}'")
        seen_names.add(name)

        if td.figma_type == "FLOAT":
            if not isinstance(value, (int, float)) or isinstance(value, bool):  # bool subclasses int
                errors.append(
                    f"{label}: value must be a number for type '{type_key}', "
                    f"got {type(value).__name__}"
                )
            elif type_key == "opacity" and not (0.0 <= float(value) <= 1.0):
                errors.append(f"{label}: opacity value must be in range [0, 1], got {value}")
        elif td.figma_type == "STRING":
            if not isinstance(value, str):
                errors.append(
                    f"{label}: value must be a string for type '{type_key}', "
                    f"got {type(value).__name__}"
                )

    return errors
