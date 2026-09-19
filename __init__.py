"""Fail-closed core for KVK iXBRL filing preparation.

This package deliberately does not submit to Digipoort. A submission adapter may
only consume a validated, frozen FilingSnapshot.
"""

from .models import FilingSnapshot, Fact, Context, Unit
from .registry import TaxonomyRegistry, TaxonomyRelease
from .service import FilingService, ExportBlocked

__all__ = [
    "Context", "ExportBlocked", "Fact", "FilingService", "FilingSnapshot",
    "TaxonomyRegistry", "TaxonomyRelease", "Unit",
]
