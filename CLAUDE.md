# Working on Metadata Comparer

Read the README first: setup, WSL, versions, performance and layout are described there.

## Workflow

- Commit each tested step without asking; push only when asked. Branch: `master`.
- Before committing, run tests and lint on Windows *and* in WSL:
  - Windows: `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/ruff check .`,
    `.venv/Scripts/ruff format .`
  - WSL (from Git Bash): `MSYS_NO_PATHCONV=1 wsl.exe -e bash -lc 'cd /mnt/c/_projects/metadata-comparer && QT_QPA_PLATFORM=offscreen UV_PROJECT_ENVIRONMENT=$HOME/.venvs/metadata-comparer ~/.local/bin/uv run pytest -q'`
- If a Windows run is unusually slow and UI tests time out, rerun before debugging.
- Windows Smart App Control can block exiv2's native module at times; then use WSL.

## Rules

- Raise `CACHE_VERSION` in `metadata/cache.py` with every change to the cache, and note it
  in the comment above it.
- The app version lives only in `src/metadata_comparer/__init__.py`.
- The user runs the app in WSL on OneDrive folders under `/mnt/c`, where per-file I/O is
  slow. Avoid a `stat()` or whole-file read per image; measure on a copy of a real folder.
- Never write `.mcs-cache` (or anything else) into the user's real photo folders from
  scripts or tests. Tests use temp folders; `conftest.py` keeps windows out of Pictures.
