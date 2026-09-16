# leosat-predictor

Calculate and visualize passes of Low-Earth-Orbit satellites through the production GUI-v2 desktop workflow or web workflow.

## Quick Start

Install the GUI dependencies, then launch the desktop app from the repository root:

```powershell
python -m pip install -r requirements_gui.txt
python scripts\run_gui.py
```

GUI v2 is the active desktop GUI. The legacy GUI v1 source is archived under
`docs/archive/gui_v1_legacy_reference/gui` for reference only.

For documentation authority, current docs, and archived planning history, see [docs/README.md](docs/README.md).

## Web workflow TLS certificate

The Flask web workflow (`src/main.py`) serves over HTTPS using a self-signed
certificate at `certs/localhost.crt` / `certs/localhost.key`. These files are
**not committed** (they are development-only credentials). Generate a local
pair before running the web app:

```powershell
mkdir certs -Force
openssl req -x509 -newkey rsa:2048 -nodes -keyout certs\localhost.key -out certs\localhost.crt -days 365 -subj "/CN=localhost"
```

## Windows GUI distribution

The Windows build supports a fast-start folder distribution and a portable one-file distribution. Both package Python and the required application dependencies, so Python is not required on the target computer.

Build, artifact-inspection, copy, and clean-machine test instructions are documented in [`docs/deployment/windows_gui_distribution.md`](docs/deployment/windows_gui_distribution.md).
