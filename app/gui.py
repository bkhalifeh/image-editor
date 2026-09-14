import os
import sys

from PIL import Image
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pydantic import ValidationError

from app.core.errors import ImageEditorError
from app.core.formats import FORMATS
from app.core.imaging import load_image
from app.core.models import (
    AddLogoStep,
    ImageRef,
    MergeStep,
    RemoveBgStep,
    ReplaceBgStep,
    ResizeStep,
    RotateStep,
    Step,
)
from app.core.pipeline import run_step

STEP_TYPES = ["remove_bg", "replace_bg", "resize", "rotate", "add_logo", "merge"]
POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right", "center"]


def describe_step(step: Step) -> str:
    if isinstance(step, RemoveBgStep):
        return "remove_bg"
    if isinstance(step, ReplaceBgStep):
        if step.color:
            return f"replace_bg  color={step.color}"
        return f"replace_bg  background={step.background.name}"
    if isinstance(step, ResizeStep):
        return f"resize  {step.width}x{step.height}"
    if isinstance(step, RotateStep):
        return f"rotate  angle={step.angle} expand={step.expand}"
    if isinstance(step, AddLogoStep):
        return f"add_logo  {step.logo.name} @{step.position} margin={step.margin}"
    if isinstance(step, MergeStep):
        return f"merge  {len(step.images)} tile(s) {step.direction} limit={step.limit}"
    return str(step)


def resolve_name(register_asset, value: str) -> str:
    """File fields hold either a freshly browsed path, or (when editing a
    step) the name of an asset already registered — only read from disk in
    the first case."""
    return register_asset(value) if os.path.isfile(value) else value


def build_ref(name: str, values: dict) -> ImageRef:
    return ImageRef(
        name=name,
        width=int(values["width"]) if values.get("width") else None,
        height=int(values["height"]) if values.get("height") else None,
        angle=float(values["angle"]) if values.get("angle") else None,
    )


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class FormDialog(QDialog):
    """Generic modal form. fields: (key, kind, {label, values?, default?}); kind in
    entry/combobox/checkbox/file/files/color."""

    def __init__(self, parent, title: str, fields: list[tuple[str, str, dict]]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._fields = fields
        self._widgets: dict[str, QWidget] = {}

        form = QFormLayout()
        for key, kind, kw in fields:
            label = kw.get("label", key)
            widget = self._build_field(kind, kw)
            form.addRow(label, widget)
            self._widgets[key] = widget

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _build_field(self, kind: str, kw: dict) -> QWidget:
        if kind == "entry":
            return QLineEdit(kw.get("default", ""))

        if kind == "combobox":
            box = QComboBox()
            box.addItems(kw["values"])
            if kw.get("default") is not None:
                box.setCurrentText(kw["default"])
            return box

        if kind == "checkbox":
            check = QCheckBox()
            check.setChecked(kw.get("default", False))
            return check

        if kind in ("file", "files"):
            return self._browse_row(
                QLineEdit(kw.get("default", "")),
                "Browse...",
                lambda line: self._pick_files(line, multi=(kind == "files")),
            )

        if kind == "color":
            return self._browse_row(
                QLineEdit(kw.get("default", "#ffffff")), "Pick...", self._pick_color
            )

        raise ValueError(f"unknown field kind '{kind}'")

    def _browse_row(self, line: QLineEdit, button_text: str, on_click) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton(button_text)
        button.clicked.connect(lambda: on_click(line))
        row_layout.addWidget(line)
        row_layout.addWidget(button)
        row.line_edit = line
        return row

    def _pick_files(self, line: QLineEdit, multi: bool):
        if multi:
            paths, _ = QFileDialog.getOpenFileNames(self, "Choose image(s)")
            if paths:
                line.setText(";".join(paths))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose image")
            if path:
                line.setText(path)

    def _pick_color(self, line: QLineEdit):
        initial = QColor(line.text()) if line.text() else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self)
        if color.isValid():
            line.setText(color.name())

    def values(self) -> dict:
        result = {}
        for key, kind, _kw in self._fields:
            widget = self._widgets[key]
            if kind == "combobox":
                result[key] = widget.currentText()
            elif kind == "checkbox":
                result[key] = widget.isChecked()
            elif kind in ("file", "files", "color"):
                result[key] = widget.line_edit.text()
            else:
                result[key] = widget.text()
        return result


def ask_form(parent, title: str, fields: list[tuple[str, str, dict]]) -> dict | None:
    dialog = FormDialog(parent, title, fields)
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.values()


def add_remove_bg(parent, register_asset, existing: RemoveBgStep | None = None) -> Step | None:
    return RemoveBgStep(op="remove_bg")


def add_replace_bg(parent, register_asset, existing: ReplaceBgStep | None = None) -> Step | None:
    initial_mode = "image" if (existing and existing.background) else "color"
    choice = ask_form(
        parent,
        "Replace Background",
        [("mode", "combobox", {"label": "Source", "values": ["color", "image"], "default": initial_mode})],
    )
    if choice is None:
        return None

    if choice["mode"] == "color":
        default_color = existing.color if (existing and existing.color) else "#ffffff"
        vals = ask_form(
            parent, "Replace Background - Color", [("color", "color", {"label": "Color", "default": default_color})]
        )
        if vals is None:
            return None
        return ReplaceBgStep(op="replace_bg", color=vals["color"])

    ref = existing.background if (existing and existing.background) else None
    vals = ask_form(
        parent,
        "Replace Background - Image",
        [
            ("file", "file", {"label": "Background image", "default": ref.name if ref else ""}),
            ("width", "entry", {"label": "Width (optional)", "default": str(ref.width or "") if ref else ""}),
            ("height", "entry", {"label": "Height (optional)", "default": str(ref.height or "") if ref else ""}),
            ("angle", "entry", {"label": "Rotate angle (optional)", "default": str(ref.angle or "") if ref else ""}),
        ],
    )
    if vals is None or not vals["file"]:
        return None
    new_ref = build_ref(resolve_name(register_asset, vals["file"]), vals)
    return ReplaceBgStep(op="replace_bg", background=new_ref)


def add_resize(parent, register_asset, existing: ResizeStep | None = None) -> Step | None:
    vals = ask_form(
        parent,
        "Resize",
        [
            ("width", "entry", {"label": "Width", "default": str(existing.width) if existing else ""}),
            ("height", "entry", {"label": "Height", "default": str(existing.height) if existing else ""}),
        ],
    )
    if vals is None:
        return None
    return ResizeStep(op="resize", width=int(vals["width"]), height=int(vals["height"]))


def add_rotate(parent, register_asset, existing: RotateStep | None = None) -> Step | None:
    vals = ask_form(
        parent,
        "Rotate",
        [
            ("angle", "entry", {"label": "Angle (degrees)", "default": str(existing.angle) if existing else ""}),
            (
                "expand",
                "checkbox",
                {"label": "Expand canvas", "default": existing.expand if existing else True},
            ),
        ],
    )
    if vals is None:
        return None
    return RotateStep(op="rotate", angle=float(vals["angle"]), expand=bool(vals["expand"]))


def add_logo(parent, register_asset, existing: AddLogoStep | None = None) -> Step | None:
    ref = existing.logo if existing else None
    vals = ask_form(
        parent,
        "Add Logo",
        [
            ("file", "file", {"label": "Logo image", "default": ref.name if ref else ""}),
            (
                "position",
                "combobox",
                {"label": "Position", "values": POSITIONS, "default": existing.position if existing else None},
            ),
            ("margin", "entry", {"label": "Margin", "default": str(existing.margin) if existing else "10"}),
            ("width", "entry", {"label": "Width (optional)", "default": str(ref.width or "") if ref else ""}),
            ("height", "entry", {"label": "Height (optional)", "default": str(ref.height or "") if ref else ""}),
            ("angle", "entry", {"label": "Rotate angle (optional)", "default": str(ref.angle or "") if ref else ""}),
        ],
    )
    if vals is None or not vals["file"]:
        return None
    new_ref = build_ref(resolve_name(register_asset, vals["file"]), vals)
    return AddLogoStep(op="add_logo", logo=new_ref, position=vals["position"], margin=int(vals["margin"] or 10))


def add_merge(parent, register_asset, existing: MergeStep | None = None) -> Step | None:
    default_files = ";".join(ref.name for ref in existing.images) if existing else ""
    vals = ask_form(
        parent,
        "Merge",
        [
            ("files", "files", {"label": "Images to merge", "default": default_files}),
            (
                "direction",
                "combobox",
                {"label": "Direction", "values": ["horizontal", "vertical"], "default": existing.direction if existing else None},
            ),
            (
                "limit",
                "entry",
                {"label": "Limit per row/column (optional)", "default": str(existing.limit or "") if existing else ""},
            ),
            ("gap", "entry", {"label": "Gap px", "default": str(existing.gap) if existing else "0"}),
            ("background", "color", {"label": "Canvas color", "default": existing.background if existing else "#ffffff"}),
        ],
    )
    if vals is None or not vals["files"]:
        return None
    refs = [ImageRef(name=resolve_name(register_asset, p)) for p in vals["files"].split(";") if p]
    return MergeStep(
        op="merge",
        images=refs,
        direction=vals["direction"],
        limit=int(vals["limit"]) if vals.get("limit") else None,
        gap=int(vals["gap"] or 0),
        background=vals["background"],
    )


STEP_BUILDERS = {
    "remove_bg": add_remove_bg,
    "replace_bg": add_replace_bg,
    "resize": add_resize,
    "rotate": add_rotate,
    "add_logo": add_logo,
    "merge": add_merge,
}


class PipelineWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, source_path: str, steps: list[Step], assets: dict[str, bytes]):
        super().__init__()
        self.source_path = source_path
        self.steps = steps
        self.assets = assets

    def run(self):
        try:
            with open(self.source_path, "rb") as f:
                image = load_image(f.read())
            for step in self.steps:
                image = run_step(image, step, self.assets)
        except ImageEditorError as exc:
            self.error.emit(str(exc))
            return
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(image)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Editor")

        self.source_path: str | None = None
        self.assets: dict[str, bytes] = {}
        self.steps: list[Step] = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.source_label = QLabel("No source image selected")
        top.addWidget(self.source_label, stretch=1)
        choose_btn = QPushButton("Choose Source Image...")
        choose_btn.clicked.connect(self.choose_source)
        top.addWidget(choose_btn)
        layout.addLayout(top)

        add_row = QHBoxLayout()
        self.step_type = QComboBox()
        self.step_type.addItems(STEP_TYPES)
        add_row.addWidget(self.step_type)
        add_btn = QPushButton("Add Step")
        add_btn.clicked.connect(self.add_step)
        add_row.addWidget(add_btn)
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self.edit_step)
        add_row.addWidget(edit_btn)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_step)
        add_row.addWidget(remove_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.edit_step())
        layout.addWidget(self.list_widget, stretch=1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Output format:"))
        self.format_box = QComboBox()
        self.format_box.addItems(list(FORMATS))
        bottom.addWidget(self.format_box)
        bottom.addStretch(1)
        self.run_btn = QPushButton("Run Pipeline")
        self.run_btn.clicked.connect(self.run_pipeline)
        bottom.addWidget(self.run_btn)
        layout.addLayout(bottom)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        layout.addWidget(self.preview_label)

        self.resize(600, 600)

        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._pending_format: str | None = None

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose source image")
        if path:
            self.source_path = path
            self.source_label.setText(os.path.basename(path))

    def register_asset(self, path: str) -> str:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            self.assets[name] = f.read()
        return name

    def add_step(self):
        builder = STEP_BUILDERS[self.step_type.currentText()]
        try:
            step = builder(self, self.register_asset)
        except (ValueError, ValidationError) as exc:
            QMessageBox.critical(self, "Invalid step", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Invalid step", f"{type(exc).__name__}: {exc}")
            return
        if step is not None:
            self.steps.append(step)
            self.list_widget.addItem(describe_step(step))

    def edit_step(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        existing = self.steps[row]
        builder = STEP_BUILDERS[existing.op]
        try:
            step = builder(self, self.register_asset, existing)
        except (ValueError, ValidationError) as exc:
            QMessageBox.critical(self, "Invalid step", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Invalid step", f"{type(exc).__name__}: {exc}")
            return
        if step is not None:
            self.steps[row] = step
            self.list_widget.item(row).setText(describe_step(step))

    def remove_step(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        self.list_widget.takeItem(row)
        del self.steps[row]

    def run_pipeline(self):
        if not self.source_path:
            QMessageBox.critical(self, "Error", "choose a source image first")
            return
        if not self.steps:
            QMessageBox.critical(self, "Error", "add at least one step")
            return
        if self._thread is not None:
            return  # already running

        self._pending_format = self.format_box.currentText()
        self.run_btn.setEnabled(False)
        self.status_label.setText("Processing...")

        self._thread = QThread()
        self._worker = PipelineWorker(self.source_path, list(self.steps), dict(self.assets))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_pipeline_finished)
        self._worker.error.connect(self._on_pipeline_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _cleanup_thread(self):
        self.run_btn.setEnabled(True)
        self.status_label.setText("")
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def _on_pipeline_error(self, message: str):
        QMessageBox.critical(self, "Pipeline error", message)

    def _on_pipeline_finished(self, image: Image.Image):
        fmt = self._pending_format
        pillow_format, _ = FORMATS[fmt]

        if pillow_format in ("JPEG", "BMP"):
            image = image.convert("RGB")

        save_path, _ = QFileDialog.getSaveFileName(self, "Save result", filter=f"*.{fmt}")
        if save_path:
            image.save(save_path, format=pillow_format)
            QMessageBox.information(self, "Done", f"saved to {save_path}")

        preview = image.copy()
        preview.thumbnail((400, 400))
        pixmap = pil_to_pixmap(preview)
        self.preview_label.setPixmap(pixmap)


def _install_excepthook():
    """PySide6 aborts the whole process on an exception that escapes a Qt slot
    uncaught; show it in a dialog instead of crashing."""
    import traceback

    def hook(exc_type, exc_value, exc_tb):
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(message, file=sys.stderr)
        QMessageBox.critical(None, "Unexpected error", message[-4000:])

    sys.excepthook = hook


def run_gui():
    app = QApplication.instance() or QApplication(sys.argv)
    _install_excepthook()
    window = MainWindow()
    window.show()
    app.exec()
