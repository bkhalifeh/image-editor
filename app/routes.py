import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.errors import ImageEditorError
from app.core.formats import FORMATS
from app.core.imaging import load_image
from app.core.models import PipelineAdapter
from app.core.pipeline import run_step

router = APIRouter()


@router.post("/process")
async def process(
    file: UploadFile = File(...),
    pipeline: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    format: str = Form("png"),
):
    entry = FORMATS.get(format.lower())
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported format '{format}', pick one of {list(FORMATS)}",
        )
    pillow_format, media_type = entry

    try:
        steps = PipelineAdapter.validate_json(pipeline)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not steps:
        raise HTTPException(status_code=400, detail="pipeline must be non-empty list")

    try:
        image = load_image(await file.read())
        assets = {f.filename: await f.read() for f in files}

        for step in steps:
            image = run_step(image, step, assets)
    except ImageEditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if pillow_format in ("JPEG", "BMP"):
        image = image.convert("RGB")

    buf = io.BytesIO()
    image.save(buf, format=pillow_format)
    buf.seek(0)
    return StreamingResponse(buf, media_type=media_type)
