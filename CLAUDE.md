# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                               # install deps (pulls PySide6's bundled Qt, rembg's onnxruntime)
uv run fastapi dev main.py            # server, dev, auto-reload
uv run fastapi run main.py            # server, prod
uv run main.py                        # same as `fastapi run` (defaults to server mode)
uv run main.py server --port 9000     # server, custom port
uv run main.py gui                    # desktop app (PySide6)
```

No test suite, linter, or formatter configured in this repo.

## Architecture

Two frontends drive one shared, framework-agnostic pipeline core:

- `app/core/` — no FastAPI or PySide6 imports. This is the part both
  frontends call into.
  - `models.py` — pydantic step models (`RemoveBgStep`, `ReplaceBgStep`,
    `ResizeStep`, `RotateStep`, `AddLogoStep`, `MergeStep`), the
    discriminated `Step` union (on `op`), `PipelineAdapter` (a
    `TypeAdapter(list[Step])` used to parse the JSON pipeline), and
    `ImageRef` — a reference to an extra uploaded/registered image by name,
    with optional `width`/`height`/`angle` applied before use. `ImageRef`
    fields accept either a plain string or the full object (coerced via a
    `BeforeValidator`).
  - `imaging.py` — `load_image` (bytes → PIL RGBA), `resolve_ref` (looks up
    an `ImageRef` in an assets dict and applies its resize/rotate),
    `logo_position`, `build_grid` (the `merge` step's tiling logic).
  - `pipeline.py` — `run_step(image, step, assets) -> image`, the single
    dispatcher (isinstance-checks on the `Step` union) both frontends call
    in a loop to execute a pipeline.
  - `errors.py` — `ImageEditorError`, raised anywhere in core instead of a
    framework-specific exception; each frontend catches it at its own
    boundary and translates it (`HTTPException` for the server,
    `QMessageBox` for the gui).
- `app/main.py` / `app/routes.py` — FastAPI app and its one route,
  `POST /process`. Parses `pipeline` (JSON) via `PipelineAdapter`, reads the
  source `file` plus any extra `files` into an assets dict keyed by
  filename, runs `run_step` in a loop, converts to RGB when the output
  format has no alpha (JPEG/BMP), streams the result back.
- `app/gui.py` — PySide6 desktop app building the exact same `Step` objects
  by hand instead of JSON.
  - `FormDialog` — generic modal form builder driven by a field-spec list
    (`(key, kind, {label, values?, default?})`, kind one of
    entry/combobox/checkbox/file/files/color); used by every per-step
    dialog.
  - `STEP_BUILDERS` — maps each op name to an `add_*` function
    `(parent, register_asset, existing=None) -> Step | None`. Passing
    `existing` prefills the form for in-place editing (double-click a step,
    or "Edit Selected") — same function serves add and edit.
  - `resolve_name` — a file-picker field holds either a freshly browsed
    path or (when editing) the name of an already-registered asset; only
    reads from disk in the first case (`os.path.isfile` check).
  - `PipelineWorker` (`QObject` + `QThread`) — runs `load_image`/`run_step`
    off the main thread so `remove_bg`'s model load/inference doesn't
    freeze the UI; emits `finished(image)` or `error(message)` back to the
    main thread. `run_pipeline` only ever kicks this off; the save dialog
    and preview happen in `_on_pipeline_finished` back on the main thread
    (Qt dialogs aren't thread-safe).
  - A global `sys.excepthook` is installed (`_install_excepthook`) as a
    last-resort net: PySide6 aborts the whole process on an exception that
    escapes a Qt slot uncaught, so anything not already caught locally is
    shown in a dialog instead of crashing.

### Adding a new pipeline step

1. Add a pydantic model in `app/core/models.py` with a literal `op` field;
   add it to the `Step` union.
2. Handle it in `run_step` (`app/core/pipeline.py`).
3. Optional: add an `add_*` builder + entry in `STEP_BUILDERS` (`app/gui.py`)
   so the GUI can build/edit it too.

### Key invariants

- `replace_bg` composites the new background *behind* the current image
  (`Image.alpha_composite(bg, image)`). If the image is still fully opaque
  (no `remove_bg` step ran first), the new background is completely
  hidden and the output looks unchanged — this is a common pipeline-order
  mistake, not a bug.
- File/image references (`replace_bg.background`, `add_logo.logo`,
  `merge.images[]`) are resolved by filename against an assets dict built
  fresh per request/run — server side from the `files` upload field, gui
  side from `MainWindow.assets` (populated via `register_asset` whenever a
  file is browsed).
