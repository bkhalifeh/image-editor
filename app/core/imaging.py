import io

from PIL import Image

from app.core.errors import ImageEditorError
from app.core.models import ImageRef


def load_image(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        raise ImageEditorError("invalid image file")


def resolve_ref(ref: ImageRef, assets: dict[str, bytes]) -> Image.Image:
    data = assets.get(ref.name)
    if data is None:
        raise ImageEditorError(f"file '{ref.name}' not uploaded")
    img = load_image(data)

    if ref.width and ref.height:
        img = img.resize((ref.width, ref.height))
    elif ref.width:
        img = img.resize((ref.width, round(img.height * ref.width / img.width)))
    elif ref.height:
        img = img.resize((round(img.width * ref.height / img.height), ref.height))

    if ref.angle:
        img = img.rotate(ref.angle, expand=True)

    return img


def logo_position(
    image_size: tuple[int, int], logo_size: tuple[int, int], position: str, margin: int
) -> tuple[int, int]:
    iw, ih = image_size
    lw, lh = logo_size
    x = {"left": margin, "right": iw - lw - margin, "center": (iw - lw) // 2}
    y = {"top": margin, "bottom": ih - lh - margin, "center": (ih - lh) // 2}
    if position == "center":
        return x["center"], y["center"]
    v, h = position.split("-")
    return x[h], y[v]


def build_grid(
    images: list[Image.Image], direction: str, limit: int | None, gap: int, background: str
) -> Image.Image:
    n = len(images)
    primary = limit or n
    if direction == "horizontal":
        cols, rows = primary, -(-n // primary)
    else:
        rows, cols = primary, -(-n // primary)

    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    canvas_w = cols * cell_w + (cols - 1) * gap
    canvas_h = rows * cell_h + (rows - 1) * gap
    try:
        canvas = Image.new("RGBA", (canvas_w, canvas_h), background)
    except ValueError:
        raise ImageEditorError("invalid background color")

    for idx, im in enumerate(images):
        r, c = divmod(idx, cols) if direction == "horizontal" else divmod(idx, rows)[::-1]
        x = c * (cell_w + gap) + (cell_w - im.width) // 2
        y = r * (cell_h + gap) + (cell_h - im.height) // 2
        canvas.alpha_composite(im, (x, y))
    return canvas
