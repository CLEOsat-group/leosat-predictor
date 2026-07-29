# leosat-predictor

PyQt6 desktop app for Low-Earth-Orbit satellite pass prediction and
observation planning — fetch TLEs, compute visible passes over an observing
site, and generate optimized observation plans.

> **A Flask web app** with the same workflow is maintained separately and
> will be added to this repository once it reaches feature parity with the
> desktop GUI.

## Repository layout

```
gui/                      Desktop GUI (PyQt6) — presenters, views, widgets, dialogs
src/
  prediction_core/        Orbital propagation & pass prediction
  observation_planner/    Observation planning / optimization
  models/                 Domain models (locations, formatting, prediction thread)
  services/               Shared services (TLE, satellite proxy, observatory catalog)
  utils/                  Shared utilities
scripts/                  Entry point (run_gui.py)
config/, data/            Configuration and shipped example data
packaging/                Windows GUI packaging (PyInstaller)
```

## Quick start

```powershell
python -m pip install -r requirements_gui.txt
python scripts\run_gui.py
```

## Requirements files

| File | Purpose |
|------|---------|
| `requirements_gui.txt` | Desktop GUI (PyQt6) runtime dependencies |
| `requirements_gui_build.txt` | Adds PyInstaller for building the Windows GUI distribution |

## License

Released under the **GNU General Public License v3.0** — see [LICENSE](LICENSE).
