"""View widgets for the GUI v2 replacement path."""

from __future__ import annotations

__all__ = [
    "ConfigurationGeneralPage",
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

from gui_v2.views.configuration_general_page import ConfigurationGeneralPage
from gui_v2.views.configuration_interface_page import ConfigurationInterfacePage
from gui_v2.views.configuration_observatory_page import ConfigurationObservatoryPage
from gui_v2.views.configuration_paths_page import ConfigurationPathsPage
from gui_v2.views.configuration_planner_deferred_page import ConfigurationPlannerDeferredPage
from gui_v2.views.configuration_planner_preferences_page import ConfigurationPlannerPreferencesPage
from gui_v2.views.configuration_prediction_defaults_page import ConfigurationPredictionDefaultsPage
from gui_v2.views.configuration_tle_page import ConfigurationTlePage
from gui_v2.views.overpass_results_page import OverpassResultsPage
from gui_v2.views.overpass_setup_page import OverpassSetupPage
from gui_v2.views.placeholder_page import PlaceholderPage
from gui_v2.views.planner_diagnostics_page import PlannerDiagnosticsPage
from gui_v2.views.planner_results_page import PlannerResultsPage
from gui_v2.views.planner_setup_generation_page import PlannerSetupGenerationPage
from gui_v2.views.precise_results_page import PreciseResultsPage
from gui_v2.views.precise_setup_page import PreciseSetupPage
from gui_v2.views.workspace_regions import WorkspaceRegionCard
