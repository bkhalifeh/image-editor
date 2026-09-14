# image-editor

Image editing pipelines: run ordered steps (remove background, replace
background, resize, rotate, add logo, merge) over an image, get result back
in whatever format wanted. Two frontends share the same pipeline core:

- **server** — FastAPI, single `POST /process` route.
- **gui** — PySide6 (Qt) desktop app, build the same pipeline by clicking
  through forms instead of writing JSON.

## Setup

Requires Python >=3.13, [uv](https://docs.astral.sh/uv/). `uv sync` pulls in
PySide6's bundled Qt too — no system Tk/Qt packages needed.

```bash
uv sync
```

## Run

```bash
uv run fastapi dev main.py            # server, dev, auto-reload
uv run fastapi run main.py            # server, prod
uv run main.py                        # same as above (defaults to server)
uv run main.py server --port 9000     # server, custom port
uv run main.py gui                    # desktop app
```

Server mode listens on `http://localhost:8000` by default. Interactive docs
at `/docs`.

## GUI mode

Pick a source image, add steps one at a time from the dropdown (each opens a
small form for that step's options — e.g. `replace_bg` asks for a color or
lets you browse for a background image, `merge` lets you multi-select
files). Double-click a step (or select it and hit **Edit Selected**) to
reopen that same form pre-filled with its current values and change them in
place. Pick an output format, then **Run Pipeline** to save the result and
preview it. Files picked for `replace_bg`/`add_logo`/`merge` are read
straight off disk — no manual filename bookkeeping like the API needs.

## API

Single route: `POST /process`, `multipart/form-data`.

| field      | type        | required | notes                                          |
|------------|-------------|----------|-------------------------------------------------|
| `file`     | file        | yes      | source image                                   |
| `pipeline` | text (JSON) | yes      | array of step objects, run in order            |
| `files`    | file(s)     | no       | extra images, referenced by name from any step |
| `format`   | text        | no       | output format, default `png`                   |

Response: image bytes, `Content-Type` matching `format`.

### File references

Steps that need an extra image (`replace_bg`'s `background`, `add_logo`'s
`logo`, `merge`'s `images`) reference one by the `filename` it was uploaded
with in `files`. A reference is either:

- a plain string — `"logo.png"`
- an object, to resize and/or rotate that file before it's used —
  `{"name": "logo.png", "width": 80, "height": 80, "angle": 15}`
  - `width`/`height`: give both for exact resize, either alone to scale
    keeping aspect ratio.
  - `angle`: degrees, rotates (canvas expands to fit, same as the `rotate`
    step).

### Steps

- `{"op": "remove_bg"}` — strip background via rembg.
- `{"op": "replace_bg", "color": "#00ff00"}` — solid color background.
- `{"op": "replace_bg", "background": <ref>}` — image background, fit to the
  current image's size. Exactly one of `color`/`background` required.
- `{"op": "resize", "width": 800, "height": 600}` — resizes the pipeline
  image itself.
- `{"op": "rotate", "angle": 45, "expand": true}` — rotates the pipeline
  image itself; `expand` (default `true`) grows canvas to fit instead of
  cropping.
- `{"op": "add_logo", "logo": <ref>, "position": "top-left", "margin": 10}`
  — `position`: `top-left` (default), `top-right`, `bottom-left`,
  `bottom-right`, `center`. Use the ref's `width`/`height`/`angle` to size or
  rotate the logo.
- `{"op": "merge", "images": [<ref>, ...], "direction": "horizontal", "limit": 2, "gap": 10, "background": "#ffffff"}`
  — tiles the current pipeline image plus each ref into a grid, in that
  order (current image first). `direction`: `horizontal` (default, fills
  left-to-right) or `vertical` (fills top-to-bottom). `limit` caps tiles per
  row (horizontal) or per column (vertical) before wrapping to the next
  line; omit for a single row/column. `gap` px between tiles, `background`
  fills the canvas (and any leftover cell space, since tiles are centered in
  equally sized cells). Use each ref's `width`/`height`/`angle` to resize or
  rotate individual tiles before laying out the grid.

### Output formats

`png` (default, keeps alpha), `jpeg`/`jpg`, `webp`, `bmp`, `tiff`. `jpeg` and
`bmp` flatten to RGB (no alpha channel).

## Examples

Remove background, put on green:

```bash
curl -F "file=@in.png" \
  -F 'pipeline=[{"op":"remove_bg"},{"op":"replace_bg","color":"#00ff00"}]' \
  http://localhost:8000/process -o out.png
```

Remove background, composite onto uploaded (rotated) image:

```bash
curl -F "file=@in.png" \
  -F "files=@sky.jpg" \
  -F 'pipeline=[{"op":"remove_bg"},{"op":"replace_bg","background":{"name":"sky.jpg","angle":5}}]' \
  http://localhost:8000/process -o out.png
```

Full pipeline, output as JPEG:

```bash
curl -F "file=@in.png" \
  -F "files=@brand.png" \
  -F 'pipeline=[
        {"op":"remove_bg"},
        {"op":"replace_bg","color":"#ffffff"},
        {"op":"resize","width":800,"height":600},
        {"op":"add_logo","logo":{"name":"brand.png","width":100},"position":"bottom-right","margin":20}
      ]' \
  -F "format=jpeg" \
  http://localhost:8000/process -o out.jpg
```

Merge two extra images with the source, side by side, one resized:

```bash
curl -F "file=@a.png" -F "files=@b.png" -F "files=@c.png" \
  -F 'pipeline=[{"op":"merge","images":["b.png",{"name":"c.png","width":200,"height":200}],"direction":"horizontal","limit":2,"gap":10}]' \
  http://localhost:8000/process -o grid.png
```

## Project layout

```
main.py          entrypoint, dispatches to server or gui mode
app/
  main.py        FastAPI() app, mounts router                 (server)
  routes.py      POST /process endpoint                       (server)
  gui.py         PySide6 app, builds the same Step objects     (gui)
  core/
    models.py    pydantic step models, Step union, PipelineAdapter
    imaging.py   load_image, resolve_ref, logo_position, build_grid
    pipeline.py  run_step dispatcher
    formats.py   output format table
    errors.py    ImageEditorError — raised by core, translated to
                 HTTPException (server) or a message box (gui)
```

`app/core` has no FastAPI or PySide6 imports — it's the shared pipeline both
frontends drive.

## Adding a new step

1. Add a pydantic model in `app/core/models.py` with a literal `op` field,
   add it to the `Step` union.
2. Handle it in `run_step` (`app/core/pipeline.py`).
3. Optional: add a step builder + entry in `STEP_BUILDERS` (`app/gui.py`) so
   the GUI can build it too.
