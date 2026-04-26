from primitive_types import PRIMITIVE_TYPES


def validate_semantic_primitives(
    semantic: dict[str, str | None],
    primitive_seeds: dict[str, list[dict]],
) -> list[str]:
    errors: list[str] = []

    # Build lookup: type_key → set of names
    primitives_by_type: dict[str, set[str]] = {
        tk: {e["name"] for e in entries}
        for tk, entries in primitive_seeds.items()
    }

    for semantic_name, primitive_ref in semantic.items():
        if semantic_name.startswith("_"):
            continue  # skip comment keys

        if primitive_ref is None:
            errors.append(f"'{semantic_name}': value is null — replace with a primitive name before validating")
            continue

        # Infer expected type from semantic name prefix
        semantic_prefix = semantic_name.split("/")[0]
        if semantic_prefix not in PRIMITIVE_TYPES:
            errors.append(f"'{semantic_name}': prefix '{semantic_prefix}' is not a known primitive type")
            continue

        # Infer type from primitive reference prefix
        ref_prefix = primitive_ref.split("/")[0]
        if ref_prefix != semantic_prefix:
            errors.append(
                f"'{semantic_name}': type mismatch — semantic prefix is '{semantic_prefix}' "
                f"but reference '{primitive_ref}' starts with '{ref_prefix}'"
            )
            continue

        if ref_prefix not in primitives_by_type:
            errors.append(f"'{semantic_name}': no seed loaded for type '{ref_prefix}'")
            continue

        if primitive_ref not in primitives_by_type[ref_prefix]:
            errors.append(f"'{semantic_name}': references '{primitive_ref}' which does not exist in the {ref_prefix} seed")

    return errors
