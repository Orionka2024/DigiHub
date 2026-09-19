"""KVK_v2 taxonomy engine.

This package provides the full XBRL taxonomy parsing stack for the Dutch
Nationale Taxonomie (NT).
"""
from .concept import ConceptMetadata
from .rules import RulesEngine, ValidationRule

__all__ = ["ConceptMetadata", "RulesEngine", "ValidationRule"]
