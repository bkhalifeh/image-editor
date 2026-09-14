from PIL import Image
from rembg import remove

from app.core.errors import ImageEditorError
from app.core.imaging import build_grid, logo_position, resolve_ref
from app.core.models import (
    AddLogoStep,
    MergeStep,
    RemoveBgStep,
    ReplaceBgStep,
    ResizeStep,
    RotateStep,
    Step,
)


def run_step(image: Image.Image, step: Step, assets: dict[str, bytes]) -> Image.Image:
    if isinstance(step, RemoveBgStep):
        return remove(image)

    if isinstance(step, ReplaceBgStep):
        if step.background is not None:
            bg = resolve_ref(step.background, assets).resize(image.size)
        else:
            try:
                bg = Image.new("RGBA", image.size, step.color)
            except ValueError:
                raise ImageEditorError("invalid color")
        return Image.alpha_composite(bg, image)

    if isinstance(step, ResizeStep):
        return image.resize((step.width, step.height))

    if isinstance(step, RotateStep):
        return image.rotate(step.angle, expand=step.expand)

    if isinstance(step, AddLogoStep):
        logo = resolve_ref(step.logo, assets)
        pos = logo_position(image.size, logo.size, step.position, step.margin)
        result = image.copy()
        result.alpha_composite(logo, pos)
        return result

    if isinstance(step, MergeStep):
        tiles = [image] + [resolve_ref(ref, assets) for ref in step.images]
        return build_grid(tiles, step.direction, step.limit, step.gap, step.background)
