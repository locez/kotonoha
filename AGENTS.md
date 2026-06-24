# Repository Guidelines

## Project Structure & Module Organization

- `src/kotonoha/`: Python package and CLI entry point (`kotonoha.main:entry_point`).
- `tests/`: Python tests for the root package.
- `plugins/cider/lyrics/`: Cider lyrics probe plugin built with Vite and TypeScript.
- `plugins/cider/lyrics/src/probe/`: Cider playback, TTML parsing, payload, and plugin state logic.
- `plugins/cider/lyrics/src/__tests__/`: Vitest tests for the Cider probe.

Keep generated output out of version control. Python caches, `node_modules/`, Cider `dist/`, and npm/yarn lockfiles under `plugins/cider/` are ignored.

## Build, Test, and Development Commands

Root Python project:

- `uv sync --extra test`: install the package and test tooling.
- `uv run kotonoha`: run the current Python app entry point.
- `uv run pytest`: run Python tests.
- `uv run ruff check .`: lint Python code.
- `uv run ty check`: run Python type checks.

Cider plugin:

- `cd plugins/cider/lyrics && pnpm install`: install Node dependencies using the package manager declared in `package.json`.
- `pnpm dev`: start the Vite dev server for plugin development.
- `pnpm build`: type-check and build the plugin into `dist/dev.locez.kotonoha.cider.lyrics/`.
- `pnpm test`: run Vitest.
- `pnpm receive`: start the local lyrics receiver test endpoint.

## Coding Style & Naming Conventions

Python is async-first: design receivers, player bridges, polling, and network I/O as `async` services from the start; keep only the Qt widget boundary synchronous. Use qasync to integrate the event loop, keep GUI work on the UI thread, and make background tasks cancellable. Target Python 3.10+, Ruff's 120-character line length, typed public functions, `pathlib.Path` for paths, and `dataclass` or small typed objects for structured data. Catch narrow exceptions with useful context; avoid broad `except Exception` except at logging boundaries. Use snake_case for modules, functions, and variables; PascalCase for classes.

TypeScript uses ES modules, strict compiler settings, and camelCase identifiers. Keep probe logic in `src/probe/`, and use `.test.ts` for Vitest files.

## Testing Guidelines

Add Python tests under `tests/` with names like `test_scaffold.py`. Add Cider probe tests under `plugins/cider/lyrics/src/__tests__/` with names like `ttml.test.ts`. New parsing, payload, or playback behavior should include focused tests.

## Commit & Pull Request Guidelines

Use Conventional Commits with an optional scope and an imperative summary, for example `fix(tui): keep cockpit panes bounded`, `feat(cider): add lyrics receiver`, or `test(lyrics): cover TTML offsets`.

Pull requests should describe the user-facing change, list validation commands run, and note any Cider-specific manual testing. Include screenshots only for overlay or UI changes.
