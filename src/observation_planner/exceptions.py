"""Shared Observation Planner exceptions."""

from __future__ import annotations


class ObservationPlanGenerationCancelled(Exception):
    """Raised when cooperative observation-plan generation is canceled."""
