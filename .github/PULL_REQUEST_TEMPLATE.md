## Summary

What does this change do, and why?

## Validation

This project has no unit-test framework — validation means running the real, affected production path (see [docs/development/VALIDATION_WORKFLOW.md](docs/development/VALIDATION_WORKFLOW.md)). Describe what you actually ran:

- [ ] `python -m compileall -q src gui_v2 scripts tools/dev`
- [ ] Ran the affected desktop GUI workflow (`python scripts/run_gui.py`) end-to-end
- [ ] Ran the affected web route/workflow end-to-end
- [ ] Rebuilt and launched the Windows GUI artifact (only if packaging/`gui_v2` changed — see [docs/deployment/windows_gui_distribution.md](docs/deployment/windows_gui_distribution.md))
- [ ] Other (describe):

## Documentation

- [ ] Updated relevant docs under `docs/` if behavior, contracts, or setup steps changed (see [docs/DOCS_AUTHORITY.md](docs/DOCS_AUTHORITY.md) for where new docs belong)
- [ ] Added a `CHANGELOG.md` entry under `[Unreleased]` if this is user-visible
