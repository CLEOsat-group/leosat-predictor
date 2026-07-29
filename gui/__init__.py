"""Clean replacement-path GUI package for the LEO satellite predictor.

The package intentionally lives beside the current ``gui`` implementation.  It
uses final-intent names so it can later be promoted without carrying migration
labels through the production codebase.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
