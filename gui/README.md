# Desktop GUI (`gui`)

`gui` is the production PyQt6 desktop application for the LEO satellite
predictor. It provides the dashboard shell, workflow-stage navigation, shared
status/time-context surfaces, and the workflow pages.

## Running

```text
scripts/run_gui.py
```

## Coverage

- Overpass: setup, execution handoff, results, and export surfaces
- Precise: setup, execution handoff, results, export, and planner handoff surfaces
- Observation Planner: setup/generation, results, diagnostics, and results-page export surfaces
- Configuration pages for observatory, TLE, prediction defaults, planner defaults, interface, and paths

## Architecture

```text
gui/
    app.py                QApplication bootstrap
    composition_root.py   service construction and dependency wiring
    main_window.py        top-level window frame
    shell/                dashboard shell and navigation
    views/                workflow and configuration page widgets
    widgets/              reusable live widgets
    presenters/           workflow presentation coordinators
    state/                Qt-free GUI state objects
    styles/               dashboard QSS files (dashboard.qss.in is the source; dark/light are generated)
```

The shared prediction and observation-planning logic lives in `src/` and is
consumed by both this GUI and the Flask web application; the GUI layer stays a
thin set of view adapters over those services.

## Design language

The dashboard preserves a consistent professional layout:

- grouped operational navigation with workflow-stage prediction navigation
- an expanded workflow tree that collapses to a readable Overpass / Precise /
  Planner / Config rail (not an abbreviated tree); rail mode preserves the
  current page and breadcrumb, and stage-level subpages remain in the expanded tree
- a breadcrumb-safe workspace context, application header, card-based workspace
  regions, and a footer status strip

Deferred or not-yet-active regions remain explicit and never show fabricated
operational results.

## Header time context

The header shows a lightweight time-context widget (local time, UTC, and a
non-authoritative observatory-time placeholder) using a GUI-thread `QTimer` with
explicit `start()` / `stop()` / `refresh()` lifecycle methods. Time values use
the `%Y-%m-%d %H:%M:%S` display format without appended timezone labels.

## Status strip and task contract

A footer-level status/event strip surfaces compact state changes (startup, page
selection, navigation expand/collapse). Its vocabulary is `ready`, `info`,
`success`, `warning`, `error`, and `busy`.

`gui/state/task_contract.py` defines a Qt-free contract for long-running task
reporting — task kind/state vocabulary, immutable task events, progress/result/
error summaries, cooperative cancellation, and mapping into the status strip —
that presenters and worker implementations use.

## Observation Planner setup/generation

The Observation Planner combines lightweight data-preparation controls with
plan-generation controls on a single page (`Observation Planner / Setup &
Generation`), keeping preparation next to generation while preserving separate
pages for results review, diagnostics, and results-page export.
