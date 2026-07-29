"""Navigation metadata for the replacement-path dashboard shell.

The model is deliberately data-only. Widgets consume this structure, but it has
no PyQt dependency and no workflow logic. Stable page identifiers are separated
from visible labels so the interface can be renamed without breaking routing.

Task 43D uses a generic node tree instead of a fixed section/page pair. This
keeps the navigation scalable enough for operational domains, workflows, and
workflow stages without another model rewrite when parity pages are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence


@dataclass(frozen=True)
class NavigationNode:
    """Node in the GUI navigation tree.

    Parameters
    ----------
    label : str
        User-visible navigation label.
    page_id : str, optional
        Stable routing identifier for selectable leaf pages. Branch nodes do
        not have a page identifier.
    title : str, optional
        Workspace title for leaf pages.
    subtitle : str, optional
        Short description shown in the workspace header for leaf pages.
    regions : tuple of str, optional
        Placeholder card titles defining the intended workspace structure.
    children : tuple of NavigationNode, optional
        Child nodes. A node with children is a navigation branch.
    """

    label: str
    page_id: str | None = None
    title: str = ""
    subtitle: str = ""
    regions: tuple[str, ...] = ()
    children: tuple["NavigationNode", ...] = ()

    @property
    def is_page(self) -> bool:
        """Return whether this node represents a selectable workspace page."""
        return self.page_id is not None and not self.children


@dataclass(frozen=True)
class NavigationDomain:
    """Selectable workflow route used by the compact navigation rail.

    Parameters
    ----------
    label : str
        Readable label shown in the rail.
    short_label : str
        Short readable fallback label if width is limited.
    root_label : str
        Label of the expanded-tree root associated with this route. Multiple
        compact routes may intentionally share one expanded-tree root.
    default_page_id : str
        Page selected when the user chooses this domain from outside it.
    page_ids : tuple of str
        Stable page identifiers contained in this domain.
    tooltip : str
        Supplemental description. The visible label remains primary.
    placement : {"primary", "bottom"}, optional
        Semantic presentation region. Routing remains page-ID based.
    icon_name : str, optional
        Repository icon basename used by expanded and compact navigation.
    """

    label: str
    short_label: str
    root_label: str
    default_page_id: str
    page_ids: tuple[str, ...]
    tooltip: str
    placement: Literal["primary", "bottom"] = "primary"
    icon_name: str = ""

    def contains(self, page_id: str) -> bool:
        """Return whether ``page_id`` belongs to this domain."""
        return page_id in self.page_ids



APPROVED_PAGE_IDS: tuple[str, ...] = (
    "predictions.overpass.setup_run",
    "predictions.overpass.results_visualization",
    "predictions.precise.setup_run",
    "predictions.precise.results_visualization",
    "planner.generate",
    "planner.results",
    "planner.diagnostics",
    "configuration.observatory",
    "configuration.tle",
    "configuration.prediction_defaults",
    "configuration.planner_defaults",
    "configuration.interface",
    "configuration.paths",
)


def build_navigation_tree() -> tuple[NavigationNode, ...]:
    """Return the approved operational navigation hierarchy.

    Returns
    -------
    tuple of NavigationNode
        Immutable navigation tree for the GUI baseline.
    """
    return (
        NavigationNode(
            label="Predictions",
            children=(
                NavigationNode(
                    label="Overpass Prediction",
                    children=(
                        NavigationNode(
                            page_id="predictions.overpass.setup_run",
                            label="Setup & Run",
                            title="Overpass Prediction — Setup & Run",
                            regions=(
                                "Location and observatory context",
                                "Time window and constraints",
                                "Satellite and TLE selection",
                                "Run controls and validation summary",
                            ),
                        ),
                        NavigationNode(
                            page_id="predictions.overpass.results_visualization",
                            label="Results & Visualization",
                            title="Overpass Prediction — Results & Visualization",
                            regions=(
                                "Visibility plot",
                                "Results table preview",
                                "Selected pass details",
                                "Export actions and last export status",
                            ),
                        ),
                    ),
                ),
                NavigationNode(
                    label="Precise Prediction",
                    children=(
                        NavigationNode(
                            page_id="predictions.precise.setup_run",
                            label="Setup & Run",
                            title="Precise Prediction — Setup & Run",
                            regions=(
                                "Location and selected pass context",
                                "Satellite/TLE readiness",
                                "Sampling and time settings",
                                "Run controls and validation summary",
                            ),
                        ),
                        NavigationNode(
                            page_id="predictions.precise.results_visualization",
                            label="Results & Visualization",
                            title="Precise Prediction — Results & Visualization",
                            regions=(
                                "Path / sky plot",
                                "Precise results table preview",
                                "Selected point/pass details",
                                "Planner handoff, TLE-copy readiness, and export status",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        NavigationNode(
            label="Observation Planner",
            children=(
                NavigationNode(
                    page_id="planner.generate",
                    label="Setup & Generation",
                    title="Observation Planner — Setup & Generation",
                    regions=(
                        "Data preparation and readiness",
                        "Generation controls",
                        "Main informative plot",
                        "Diagnostics summary and compact preview",
                    ),
                ),
                NavigationNode(
                    page_id="planner.results",
                    label="Results & Visualization",
                    title="Planner Results",
                    # subtitle="Review the generated observation sequence and selected-row details.",
                    regions=(
                        "Plan table",
                        "Timeline view",
                        "Selected observation details",
                        "Result acceptance and export readiness",
                    ),
                ),
                NavigationNode(
                    page_id="planner.diagnostics",
                    label="Diagnostics",
                    title="Planner Diagnostics",
                    # subtitle="Expanded drill-down diagnostics for optimization behavior and trust analysis.",
                    regions=(
                        "Optimization impact",
                        "Baseline comparison",
                        "Slew/path diagnostics",
                        "Rejected candidates and constraint failures",
                    ),
                ),
            ),
        ),
        NavigationNode(
            label="Configuration",
            children=(
                NavigationNode(
                    page_id="configuration.observatory",
                    label="Observatory Location",
                    title="Observatory Location",
                    # subtitle="Manage observatory/location context for predictions and planning.",
                    regions=(
                        "Saved locations",
                        "Coordinate defaults",
                        "Map selection status",
                        "Validation notes",
                    ),
                ),
                NavigationNode(
                    page_id="configuration.tle",
                    label="TLE Sources & Satellites",
                    title="TLE Sources & Satellites",
                    # subtitle="Review future TLE source and satellite-selection configuration surfaces.",
                    regions=(
                        "Source policy",
                        "Constellation defaults",
                        "Satellite filters",
                        "Refresh status",
                    ),
                ),
                NavigationNode(
                    page_id="configuration.prediction_defaults",
                    label="Prediction Defaults",
                    title="Prediction Defaults",
                    # subtitle="Future defaults for overpass and precise prediction workflows.",
                    regions=(
                        "Time defaults",
                        "Sampling defaults",
                        "Elevation constraints",
                        "Solar constraints",
                    ),
                ),
                NavigationNode(
                    page_id="configuration.planner_defaults",
                    label="Planner Defaults",
                    title="Planner Defaults",
                    # subtitle="Future defaults for observation planning and optimizer behavior.",
                    regions=(
                        "Optimization defaults",
                        "Spacing defaults",
                        "Diagnostics defaults",
                        "Export defaults",
                    ),
                ),
                NavigationNode(
                    page_id="configuration.interface",
                    label="Interface",
                    title="Interface",
                    # subtitle="Future appearance and workspace-behavior configuration.",
                    regions=(
                        "Theme",
                        "Layout density",
                        "Table behavior",
                        "Notification behavior",
                    ),
                ),
                NavigationNode(
                    page_id="configuration.paths",
                    label="Paths & Export",
                    title="Paths & Export",
                    # subtitle="Future file-path and output naming configuration.",
                    regions=(
                        "Default directories",
                        "Filename policy",
                        "TLE copy policy",
                        "Export audit status",
                    ),
                ),
            ),
        ),
    )


def build_navigation_domains(nodes: Sequence[NavigationNode]) -> tuple[NavigationDomain, ...]:
    """Return readable workflow routes for the compact navigation rail.

    The rail exposes prediction methods separately so Overpass and Precise
    remain directly reachable while the full workflow-stage tree is collapsed.
    It avoids abbreviation-based labels and leaves page-level navigation in the
    expanded tree.

    Parameters
    ----------
    nodes : sequence of NavigationNode
        Approved navigation tree roots.

    Returns
    -------
    tuple of NavigationDomain
        Workflow rail entries in display order.
    """
    overpass_pages = _page_ids_for_branch(nodes, ("Predictions", "Overpass Prediction"))
    precise_pages = _page_ids_for_branch(nodes, ("Predictions", "Precise Prediction"))
    planner_pages = _page_ids_for_branch(nodes, ("Observation Planner",))
    configuration_pages = _page_ids_for_branch(nodes, ("Configuration",))
    return (
        NavigationDomain(
            label="Overpass",
            short_label="Overpass",
            root_label="Predictions",
            default_page_id="predictions.overpass.setup_run",
            page_ids=overpass_pages,
            tooltip="Overpass Prediction — setup/run and results/visualization.",
            placement="primary",
            icon_name="signal",
        ),
        NavigationDomain(
            label="Precise",
            short_label="Precise",
            root_label="Predictions",
            default_page_id="predictions.precise.setup_run",
            page_ids=precise_pages,
            tooltip="Precise Prediction — setup/run and results/visualization.",
            placement="primary",
            icon_name="signal",
        ),
        NavigationDomain(
            label="Planner",
            short_label="Plan",
            root_label="Observation Planner",
            default_page_id="planner.generate",
            page_ids=planner_pages,
            tooltip="Observation Planner — setup/generation, results, diagnostics, and results-page export.",
            placement="primary",
            icon_name="widgets",
        ),
        NavigationDomain(
            label="Config",
            short_label="Config",
            root_label="Configuration",
            default_page_id="configuration.observatory",
            page_ids=configuration_pages,
            tooltip="Configuration — observatory, TLE, defaults, interface, and paths.",
            placement="bottom",
            icon_name="settings",
        ),
    )


def _page_ids_for_branch(
    nodes: Sequence[NavigationNode],
    labels: Sequence[str],
) -> tuple[str, ...]:
    """Return selectable page IDs below one label path.

    Parameters
    ----------
    nodes : sequence of NavigationNode
        Nodes available at the first path level.
    labels : sequence of str
        Successive node labels identifying the target branch.

    Returns
    -------
    tuple of str
        Stable page IDs below the branch, or an empty tuple if the path is not
        present.
    """

    level = tuple(nodes)
    branch: NavigationNode | None = None
    for label in labels:
        branch = next((node for node in level if node.label == label), None)
        if branch is None:
            return ()
        level = branch.children
    if branch is None:
        return ()
    return tuple(page.page_id for page in iter_pages((branch,)) if page.page_id)


def domain_for_page(
    domains: Sequence[NavigationDomain],
    page_id: str,
) -> NavigationDomain | None:
    """Return the compact-rail domain containing ``page_id`` if known."""
    for domain in domains:
        if domain.contains(page_id):
            return domain
    return None

def iter_pages(nodes: Sequence[NavigationNode]) -> Iterable[NavigationNode]:
    """Yield selectable leaf pages from a navigation tree.

    Parameters
    ----------
    nodes : sequence of NavigationNode
        Root nodes to traverse.

    Yields
    ------
    NavigationNode
        Selectable leaf pages with stable page IDs.
    """
    for node in nodes:
        if node.is_page:
            yield node
        if node.children:
            yield from iter_pages(node.children)


def breadcrumb_for_page(nodes: Sequence[NavigationNode], page_id: str) -> tuple[str, ...]:
    """Return the label breadcrumb for a page ID.

    Parameters
    ----------
    nodes : sequence of NavigationNode
        Root navigation nodes.
    page_id : str
        Stable page identifier.

    Returns
    -------
    tuple of str
        Breadcrumb labels from root to leaf.
    """
    for node in nodes:
        path = _breadcrumb_for_page(node, page_id, prefix=())
        if path:
            return path
    return (page_id,)


def _breadcrumb_for_page(node: NavigationNode, page_id: str, prefix: tuple[str, ...]) -> tuple[str, ...]:
    current = (*prefix, node.label)
    if node.page_id == page_id:
        return current
    for child in node.children:
        path = _breadcrumb_for_page(child, page_id, current)
        if path:
            return path
    return ()
