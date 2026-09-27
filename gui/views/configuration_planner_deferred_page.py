"""Compatibility alias for the Task 50A planner-preferences page.

The active GUI planner-default route now uses
:class:`ConfigurationPlannerPreferencesPage`.  The legacy deferred class name is
kept only to avoid breaking historical imports while older planning material is
being retired.
"""

from __future__ import annotations

from .configuration_planner_preferences_page import ConfigurationPlannerPreferencesPage


class ConfigurationPlannerDeferredPage(ConfigurationPlannerPreferencesPage):
    """Backward-compatible alias for the editable planner preferences page."""


__all__ = ("ConfigurationPlannerDeferredPage",)
