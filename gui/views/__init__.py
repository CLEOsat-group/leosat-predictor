"""View widgets for the GUI replacement path."""

from __future__ import annotations

__all__ = [
    "ConfigurationInterfacePage",
    "ConfigurationObservatoryPage",
    "ConfigurationPathsPage",
    "ConfigurationPlannerPreferencesPage",
    "ConfigurationPlannerDeferredPage",
    "ConfigurationPredictionDefaultsPage",
    "ConfigurationTlePage",
    "OverpassResultsPage",
    "OverpassSetupPage",
    "PlaceholderPage",
    "PlannerDiagnosticsPage",
    "PlannerResultsPage",
    "PlannerSetupGenerationPage",
    "PreciseResultsPage",
    "PreciseSetupPage",
    "WorkspaceRegionCard",
]

from gui.views.configuration_interface_page import ConfigurationInterfacePage
from gui.views.configuration_observatory_page import ConfigurationObservatoryPage
from gui.views.configuration_paths_page import ConfigurationPathsPage
from gui.views.configuration_planner_deferred_page import ConfigurationPlannerDeferredPage
from gui.views.configuration_planner_preferences_page import ConfigurationPlannerPreferencesPage
from gui.views.configuration_prediction_defaults_page import ConfigurationPredictionDefaultsPage
from gui.views.configuration_tle_page import ConfigurationTlePage
from gui.views.overpass_results_page import OverpassResultsPage
from gui.views.overpass_setup_page import OverpassSetupPage
from gui.views.placeholder_page import PlaceholderPage
from gui.views.planner_diagnostics_page import PlannerDiagnosticsPage
from gui.views.planner_results_page import PlannerResultsPage
from gui.views.planner_setup_generation_page import PlannerSetupGenerationPage
from gui.views.precise_results_page import PreciseResultsPage
from gui.views.precise_setup_page import PreciseSetupPage
from gui.views.workspace_regions import WorkspaceRegionCard
