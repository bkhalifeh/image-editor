from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter, model_validator


class ImageRef(BaseModel):
    """Reference to an uploaded file in the `files` field, with optional resize/rotate applied before use."""

    name: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    angle: float | None = None


def _coerce_ref(v):
    return {"name": v} if isinstance(v, str) else v


ImageRefField = Annotated[ImageRef, BeforeValidator(_coerce_ref)]


class RemoveBgStep(BaseModel):
    op: Literal["remove_bg"]


class ReplaceBgStep(BaseModel):
    op: Literal["replace_bg"]
    color: str | None = None
    background: ImageRefField | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.color) == bool(self.background):
            raise ValueError("give exactly one of 'color' or 'background'")
        return self


class ResizeStep(BaseModel):
    op: Literal["resize"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RotateStep(BaseModel):
    op: Literal["rotate"]
    angle: float
    expand: bool = True


class AddLogoStep(BaseModel):
    op: Literal["add_logo"]
    logo: ImageRefField
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = (
        "top-left"
    )
    margin: int = Field(default=10, ge=0)


class MergeStep(BaseModel):
    op: Literal["merge"]
    images: list[ImageRefField] = Field(min_length=1)
    direction: Literal["horizontal", "vertical"] = "horizontal"
    limit: int | None = Field(
        default=None,
        gt=0,
        description="max tiles per row (horizontal) or per column (vertical) before wrapping",
    )
    gap: int = Field(default=0, ge=0)
    background: str = "#ffffff"


Step = Annotated[
    Union[RemoveBgStep, ReplaceBgStep, ResizeStep, RotateStep, AddLogoStep, MergeStep],
    Field(discriminator="op"),
]
PipelineAdapter = TypeAdapter(list[Step])
