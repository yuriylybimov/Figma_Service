"""Primitive token type registry — maps token kind to Figma variable type and display unit."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PrimitiveTypeDef:
    figma_type: Literal["FLOAT", "STRING"]
    unit: str | None  # informational only, not sent to Figma


PRIMITIVE_TYPES: dict[str, PrimitiveTypeDef] = {
    "spacing":        PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "radius":         PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "stroke-width":   PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "font-family":    PrimitiveTypeDef(figma_type="STRING", unit=None),
    "font-weight":    PrimitiveTypeDef(figma_type="FLOAT", unit=None),
    "font-size":      PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "line-height":    PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "letter-spacing": PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "opacity":        PrimitiveTypeDef(figma_type="FLOAT", unit=None),
}
