"""Styled hierarchical navigation sidebar for GUI."""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from gui.shell.navigation_model import (
    NavigationDomain,
    NavigationNode,
    build_navigation_domains,
    domain_for_page,
)
from gui.styles import repolish
from gui.styles.icon_provider import (
    register_icon_host,
    set_themed_icon,
    themed_icon,
)


_logger = logging.getLogger(__name__)

_WIDTH_ANIMATION_DURATION_MS = 220
_WIDTH_ANIMATION_EASING = QEasingCurve.Type.InOutCubic

_PAGE_ID_ROLE = Qt.ItemDataRole.UserRole
_FULL_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1
_IS_PAGE_ROLE = Qt.ItemDataRole.UserRole + 2
_DEFAULT_PAGE_ID_ROLE = Qt.ItemDataRole.UserRole + 3


class NavigationSidebar(QWidget):
    """Navigation control that emits selected stable page IDs.

    The expanded mode uses separate primary and bottom tree surfaces so
    Configuration remains anchored below the operational workflows without
    introducing fake navigation items. Compact mode projects the same routes
    onto a readable workflow-level rail, including separate Overpass and
    Precise controls.
    """

    pageSelected = pyqtSignal(str)

    def __init__(self, nodes: tuple[NavigationNode, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiNavigationRail")
        self._nodes = nodes
        self._domains: tuple[NavigationDomain, ...] = build_navigation_domains(nodes)
        self._placement_by_root: dict[str, str] = {}
        self._icon_by_root: dict[str, str] = {}
        for domain in self._domains:
            self._placement_by_root.setdefault(domain.root_label, domain.placement)
            if domain.icon_name:
                self._icon_by_root.setdefault(domain.root_label, domain.icon_name)
        self._rail_mode = False
        self._current_page_id: str | None = None
        self._tree_items: list[QTreeWidgetItem] = []
        self._root_items: dict[str, QTreeWidgetItem] = {}
        self._page_items: dict[str, QTreeWidgetItem] = {}
        self._page_trees: dict[str, QTreeWidget] = {}
        self._domain_buttons: dict[str, QPushButton] = {}

        self._title = QLabel("NAVIGATION", self)
        self._title.setObjectName("guiNavigationTitle")

        self._primary_tree = self._create_tree("guiNavigationTree")
        self._bottom_tree = self._create_tree("guiNavigationBottomTree")
        # Retain the historical attribute as an alias for the primary tree.
        self._tree = self._primary_tree

        self._expanded = QWidget(self)
        self._expanded.setObjectName("guiExpandedNavigation")
        expanded_layout = QGridLayout(self._expanded)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setHorizontalSpacing(0)
        expanded_layout.setVerticalSpacing(10)
        expanded_layout.addWidget(self._primary_tree, 0, 0)

        self._separator = QFrame(self._expanded)
        self._separator.setObjectName("guiNavigationSeparator")
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setFixedHeight(1)
        self._separator.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        expanded_layout.addWidget(self._separator, 1, 0)

        self._bottom_tree.setMinimumHeight(82)
        self._bottom_tree.setMaximumHeight(300)
        self._bottom_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        expanded_layout.addWidget(self._bottom_tree, 2, 0)
        expanded_layout.setColumnStretch(0, 1)
        expanded_layout.setRowStretch(0, 1)
        expanded_layout.setRowStretch(1, 0)
        expanded_layout.setRowStretch(2, 0)

        self._rail = QWidget(self)
        self._rail.setObjectName("guiDomainRail")
        rail_layout = QGridLayout(self._rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setHorizontalSpacing(0)
        rail_layout.setVerticalSpacing(8)

        primary_domains = [domain for domain in self._domains if domain.placement == "primary"]
        bottom_domains = [domain for domain in self._domains if domain.placement == "bottom"]
        for row, domain in enumerate(primary_domains):
            rail_layout.addWidget(self._create_domain_button(domain), row, 0)

        stretch_row = len(primary_domains)
        rail_layout.setRowStretch(stretch_row, 1)
        for offset, domain in enumerate(bottom_domains, start=1):
            rail_layout.addWidget(
                self._create_domain_button(domain),
                stretch_row + offset,
                0,
            )
        rail_layout.setColumnStretch(0, 1)

        self._stack = QStackedWidget(self)
        self._stack.setObjectName("guiNavigationModeStack")
        self._stack.addWidget(self._expanded)
        self._stack.addWidget(self._rail)

        layout = QGridLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(10)
        layout.addWidget(self._title, 0, 0)
        layout.addWidget(self._stack, 1, 0)
        layout.setColumnStretch(0, 1)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)

        self._min_width_animation = QPropertyAnimation(self, b"minimumWidth", self)
        self._min_width_animation.setDuration(_WIDTH_ANIMATION_DURATION_MS)
        self._min_width_animation.setEasingCurve(_WIDTH_ANIMATION_EASING)
        self._max_width_animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._max_width_animation.setDuration(_WIDTH_ANIMATION_DURATION_MS)
        self._max_width_animation.setEasingCurve(_WIDTH_ANIMATION_EASING)
        self._width_animation_group = QParallelAnimationGroup(self)
        self._width_animation_group.addAnimation(self._min_width_animation)
        self._width_animation_group.addAnimation(self._max_width_animation)
        self._suppress_width_animation = True

        self._populate(nodes)
        register_icon_host(self)
        self.refresh_theme_icons()
        self.set_rail_mode(False)
        self._suppress_width_animation = False

    @property
    def is_compact(self) -> bool:
        """Return whether the sidebar is in readable rail mode."""

        return self._rail_mode

    @property
    def is_rail_mode(self) -> bool:
        """Return whether the readable workflow rail is active."""

        return self._rail_mode

    def set_compact(self, compact: bool) -> None:
        """Compatibility wrapper for switching expanded/rail modes."""

        self.set_rail_mode(compact)

    def set_rail_mode(self, enabled: bool) -> None:
        """Switch between expanded tree mode and readable workflow rail mode."""

        self._rail_mode = bool(enabled)
        _logger.debug("Navigation mode: %s", "rail" if self._rail_mode else "expanded")
        self.setProperty("compact", self._rail_mode)
        self.setProperty("railMode", self._rail_mode)
        self._title.setText("Workflows" if self._rail_mode else "Navigation")
        target_min_width = 140 if self._rail_mode else 260
        target_max_width = 190 if self._rail_mode else 360
        if self._suppress_width_animation:
            self.setMinimumWidth(target_min_width)
            self.setMaximumWidth(target_max_width)
        else:
            self._width_animation_group.stop()
            current_width = self.width()
            self._min_width_animation.setStartValue(current_width)
            self._min_width_animation.setEndValue(target_min_width)
            self._max_width_animation.setStartValue(current_width)
            self._max_width_animation.setEndValue(target_max_width)
            self._width_animation_group.start()
        self._stack.setCurrentWidget(self._rail if self._rail_mode else self._expanded)
        self._update_domain_buttons()
        self._refresh_style()

    def select_page(self, page_id: str) -> None:
        """Select a page by stable page ID and emit the selection."""

        _logger.debug("Selecting page: %s", page_id)
        self.set_current_page_context(page_id)
        self.pageSelected.emit(page_id)

    def set_current_page_context(self, page_id: str) -> None:
        """Update both navigation surfaces without emitting a new selection."""

        self._current_page_id = page_id
        item = self._page_items.get(page_id)
        target_tree = self._page_trees.get(page_id)
        if item is not None and target_tree is not None:
            trees = (self._primary_tree, self._bottom_tree)
            previous_states = [tree.blockSignals(True) for tree in trees]
            try:
                for tree in trees:
                    tree.clearSelection()
                    if tree is not target_tree:
                        tree.setCurrentItem(None)
                self._expand_parent_chain(item)
                target_tree.setCurrentItem(item)
                target_tree.scrollToItem(item)
            finally:
                for tree, previous in zip(trees, previous_states, strict=True):
                    tree.blockSignals(previous)
        self._update_domain_buttons()

    def refresh_theme_icons(self) -> None:
        """Refresh tree and compact-rail icons for the active theme."""

        for domain in self._domains:
            if domain.icon_name:
                button = self._domain_buttons.get(domain.label)
                if button is not None:
                    set_themed_icon(button, domain.icon_name, size=18)
        for root_label, icon_name in self._icon_by_root.items():
            root_item = self._root_items.get(root_label)
            if root_item is not None:
                root_item.setIcon(0, themed_icon(icon_name))

    def _create_tree(self, object_name: str) -> QTreeWidget:
        """Create one configured expanded-navigation tree surface."""

        tree = QTreeWidget(self)
        tree.setObjectName(object_name)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        tree.setIndentation(16)
        tree.setIconSize(QSize(18, 18))
        tree.currentItemChanged.connect(
            lambda current, previous, source=tree: self._handle_current_item_changed(
                source,
                current,
                previous,
            )
        )
        return tree

    def _create_domain_button(self, domain: NavigationDomain) -> QPushButton:
        """Create one compact-rail domain control."""

        button = QPushButton(domain.label, self._rail)
        button.setObjectName("guiRailButton")
        button.setCheckable(True)
        button.setToolTip(domain.tooltip)
        button.clicked.connect(
            lambda _checked=False, selected=domain: self._handle_domain_clicked(selected)
        )
        if domain.icon_name:
            set_themed_icon(button, domain.icon_name, size=18)
        self._domain_buttons[domain.label] = button
        return button

    def _populate(self, nodes: tuple[NavigationNode, ...]) -> None:
        """Populate primary and bottom trees from semantic domain placement."""

        for node in nodes:
            target = (
                self._bottom_tree
                if self._placement_by_root.get(node.label) == "bottom"
                else self._primary_tree
            )
            item = self._create_item(node, path=(node.label,), tree=target)
            target.addTopLevelItem(item)
            self._root_items[node.label] = item

    def _create_item(
        self,
        node: NavigationNode,
        path: tuple[str, ...],
        tree: QTreeWidget,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.label])
        item.setData(0, _FULL_LABEL_ROLE, node.label)
        item.setData(0, _IS_PAGE_ROLE, node.is_page)
        item.setToolTip(0, " / ".join(path))
        if node.page_id:
            item.setData(0, _PAGE_ID_ROLE, node.page_id)
            self._page_items[node.page_id] = item
            self._page_trees[node.page_id] = tree
        else:
            default_page_id = self._first_descendant_page_id(node)
            if default_page_id:
                item.setData(0, _DEFAULT_PAGE_ID_ROLE, default_page_id)
        if not node.is_page:
            item.setExpanded(True)
        self._tree_items.append(item)
        for child in node.children:
            child_item = self._create_item(child, path=(*path, child.label), tree=tree)
            item.addChild(child_item)
        return item

    @staticmethod
    def _expand_parent_chain(item: QTreeWidgetItem) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    @staticmethod
    def _first_descendant_page_id(node: NavigationNode) -> str | None:
        """Return the first selectable descendant page for a branch node.

        Branch entries such as ``Overpass Prediction`` and
        ``Observation Planner`` act as readable workflow shortcuts. Selecting a
        branch should therefore open the first concrete child page instead of
        leaving the workspace unchanged.
        """

        for child in node.children:
            if child.page_id:
                return child.page_id
            descendant_page_id = NavigationSidebar._first_descendant_page_id(child)
            if descendant_page_id:
                return descendant_page_id
        return None

    def _handle_current_item_changed(
        self,
        source_tree: QTreeWidget,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return

        other_tree = self._bottom_tree if source_tree is self._primary_tree else self._primary_tree
        blocked = other_tree.blockSignals(True)
        try:
            other_tree.clearSelection()
            other_tree.setCurrentItem(None)
        finally:
            other_tree.blockSignals(blocked)

        page_id = current.data(0, _PAGE_ID_ROLE) or current.data(0, _DEFAULT_PAGE_ID_ROLE)
        if page_id:
            page_id_text = str(page_id)
            self._current_page_id = page_id_text
            self._update_domain_buttons()
            self.pageSelected.emit(page_id_text)

    def _handle_domain_clicked(self, domain: NavigationDomain) -> None:
        current = self._current_page_id
        target_page_id = current if current and domain.contains(current) else domain.default_page_id
        self.set_current_page_context(target_page_id)
        self.pageSelected.emit(target_page_id)

    def _update_domain_buttons(self) -> None:
        active_domain = domain_for_page(self._domains, self._current_page_id or "")
        active_label = active_domain.label if active_domain else ""
        for domain in self._domains:
            button = self._domain_buttons[domain.label]
            is_active = domain.label == active_label
            button.setChecked(is_active)
            button.setProperty("active", is_active)
            repolish(button)

    def _refresh_style(self) -> None:
        for widget in (
            self,
            self._primary_tree,
            self._bottom_tree,
            self._expanded,
            self._separator,
            self._rail,
            self._stack,
        ):
            repolish(widget)
