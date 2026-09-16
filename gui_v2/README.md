# GUI v2 Replacement Path

`gui_v2` is the clean replacement-path GUI package for the LEO satellite predictor.
It intentionally lives beside the current `gui` package so the existing application
remains the production reference while parity is rebuilt in bounded slices.

## Current status

GUI v2 is the active replacement-path baseline. It provides the dashboard shell,
workflow-stage navigation, shared status/time context surfaces, and the bounded
workflow pages implemented through the Task 44–48 porting slices.

Current baseline coverage includes:

- overpass setup, execution handoff, results, and export surfaces
- precise setup, execution handoff, results, export, and planner handoff surfaces
- Observation Planner setup/generation, results, diagnostics, and results-page export surfaces
- configuration pages for observatory, TLE, prediction defaults, planner defaults, interface, and paths

The existing GUI remains available as the reference implementation:

```text
scripts/run_gui.py
```

The GUI v2 baseline launches with:

```text
scripts/run_gui_v2.py
```

## Architecture

```text
gui_v2/
    app.py                QApplication bootstrap
    composition_root.py   service construction and dependency wiring
    main_window.py        top-level window frame
    shell/                dashboard shell and navigation
    views/                workflow and configuration page widgets
    widgets/              reusable live GUI v2 widgets
    presenters/           workflow presentation coordinators
    state/                Qt-free GUI state objects
    styles/               local dashboard QSS files
```

The package uses final-intent names such as `MainWindow`, `DashboardShell`, and
`NavigationSidebar`.  It avoids `V2` class names so this package can later be
promoted with less naming churn.

## Design rule

The baseline should preserve the intended professional dashboard language:

- grouped operational navigation
- workflow-stage prediction navigation
- explicit expanded/readable rail sidebar behavior
- breadcrumb-safe workspace context
- application header
- styled readable workflow rail
- workspace surface
- card-based workspace regions
- status footer

Deferred or not-yet-active regions must remain explicit and must not show fabricated operational results.


## Task 43E compact-navigation rule

The compact state is a readable workflow rail, not an abbreviated tree.

```text
Expanded mode: full workflow-stage tree
Rail mode:     Overpass / Precise / Planner / Config
```

Rail mode preserves the current page and breadcrumb. Overpass and Precise remain
separately selectable, while stage-level subpages remain in the expanded tree.
The rail does not use memorized abbreviations.

## Task 43G time-context rule

The header includes a real, lightweight time-context widget. It shows local time,
UTC time, and a non-authoritative observatory-time placeholder. Time values use
the v1-compatible `%Y-%m-%d %H:%M:%S` display format without appended timezone
labels. The widget uses a GUI-thread `QTimer` and explicit `start()`, `stop()`,
and `refresh()` lifecycle methods. It does not create workers, run predictions,
generate plans, calculate astronomical observatory time, or claim workflow parity.


## Task 43H status/event strip

GUI v2 now includes a footer-level status/event strip.  The strip is a global,
compact message surface for baseline-safe state changes such as startup, page
selection, and navigation expand/collapse events.

The status strip is intentionally not a workflow log and does not execute
prediction, planner, export, or handoff actions.  Future async reporting remains
reserved for Task 43I.

Implementation files:

```text
gui_v2/state/status_event.py
gui_v2/widgets/status_event_strip.py
```

Supported status vocabulary:

```text
ready
info
success
warning
error
busy
```

`busy` is reserved as vocabulary for later async-task contracts and does not
indicate that GUI v2 currently runs background workflows.


## Task 43I async-task contract

GUI v2 now includes a Qt-free contract for future long-running task reporting.
The contract defines task kind/state vocabulary, immutable task events, progress/result/error summaries, cooperative cancellation requests, allowed lifecycle transitions, and mapping into the Task 43H status strip.

Implementation file:

```text
gui_v2/state/task_contract.py
```

Task 43I deliberately adds no workers, no prediction execution, no planner generation, no export execution, no handoff execution, no multiprocessing, and no alternate event loop. It only defines the reporting boundary that future presenters and worker implementations must use.


Task 43I exported vocabulary includes `TaskKind`, `TaskState`, and `CancellationRequest`. No prediction execution is introduced.

## Planner setup/generation navigation rule

The Observation Planner combines lightweight data-preparation controls with plan-generation controls on one page:

```text
Observation Planner / Setup & Generation
```

The former standalone Data Preparation placeholder was removed because the preparation surface only contains a few loading/readiness controls. Keeping those controls next to generation avoids an unnecessary navigation step while preserving separate pages for results review, diagnostics deep-dive, and results-page export.
