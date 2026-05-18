"""PySide6 Windows GUI for the om2usc converter."""

from __future__ import annotations

import io
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QGraphicsOpacityEffect,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from osu_mania_to_scp import filter_valid_charts, parse_all_charts, read_osz
from src.osu_to_usc import TAIL_MODES
from src.scp_writer import build_merged_scp, build_scp


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class OszEntry:
    path: str
    chart_count: int
    title: str
    background: Optional[bytes] = None


class WorkerSignals(QObject):
    progress = Signal(int, int, str)
    message = Signal(str)
    finished = Signal(bool, str)


class ConversionWorker(QRunnable):
    def __init__(
        self,
        entries: List[OszEntry],
        engine_path: str,
        output_path: str,
        export_mode: str,
        tail_mode: str,
        background_mode: str,
        tinged_columns: bool,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.engine_path = engine_path
        self.output_path = output_path
        self.export_mode = export_mode
        self.tail_mode = tail_mode
        self.background_mode = background_mode
        self.tinged_columns = tinged_columns
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            total_charts = max(1, sum(entry.chart_count for entry in self.entries))
            if self.export_mode == "merge":
                status = build_merged_scp(
                    [entry.path for entry in self.entries],
                    self.engine_path,
                    self.output_path,
                    tail_mode=self.tail_mode,
                    background_mode=self.background_mode,
                    tinged_columns=self.tinged_columns,
                    progress_callback=self.signals.progress.emit,
                )
                if status != 0:
                    self.signals.finished.emit(False, "Merge conversion failed.")
                    return
            else:
                out_dir = Path(self.output_path)
                out_dir.mkdir(parents=True, exist_ok=True)
                completed = 0
                used_outputs: set[Path] = set()
                for entry in self.entries:
                    out_file = _unique_output_path(out_dir / f"{Path(entry.path).stem}.scp", used_outputs)
                    self.signals.message.emit(f"Writing {out_file.name}")

                    def report(current: int, total: int, message: str) -> None:
                        del total
                        self.signals.progress.emit(
                            min(total_charts, completed + current),
                            total_charts,
                            message,
                        )

                    status = build_scp(
                        entry.path,
                        self.engine_path,
                        str(out_file),
                        tail_mode=self.tail_mode,
                        background_mode=self.background_mode,
                        tinged_columns=self.tinged_columns,
                        progress_callback=report,
                    )
                    if status != 0:
                        self.signals.finished.emit(False, f"Failed: {Path(entry.path).name}")
                        return
                    completed += max(1, entry.chart_count)
                    self.signals.progress.emit(completed, total_charts, f"Finished {out_file.name}")

            self.signals.finished.emit(True, "Conversion finished.")
        except Exception as exc:  # pragma: no cover - GUI safety boundary
            self.signals.finished.emit(False, str(exc))


class BackgroundWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pixmap: Optional[QPixmap] = None
        self.setAutoFillBackground(False)

    def set_background(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()
        painter.fillRect(rect, QColor(14, 18, 26))

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

        painter.fillRect(rect, QColor(6, 8, 14, 178))
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(255, 170, 205, 42))
        gradient.setColorAt(0.45, QColor(96, 210, 255, 26))
        gradient.setColorAt(1.0, QColor(6, 8, 14, 188))
        painter.fillRect(rect, gradient)


class DropListWidget(QListWidget):
    filesDropped = Signal(list)
    dragStateChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._has_osz_urls(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._has_osz_urls(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        del event
        self._set_drag_active(False)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".osz")
        ]
        self._set_drag_active(False)
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
            return
        event.ignore()

    def _set_drag_active(self, active: bool) -> None:
        if self.property("dragActive") == active:
            return
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.dragStateChanged.emit(active)

    @staticmethod
    def _has_osz_urls(mime_data) -> bool:
        return any(
            url.isLocalFile() and url.toLocalFile().lower().endswith(".osz")
            for url in mime_data.urls()
        )


class Om2UscWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.entries: List[OszEntry] = []
        self.thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("om2usc")
        self.resize(1120, 720)
        self.setMinimumSize(920, 620)
        self.setFont(QFont("Segoe UI Variable", 10))

        self.background = BackgroundWidget()
        self.setCentralWidget(self.background)
        self._build_ui()
        self._apply_style()
        enable_windows_acrylic(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self.background)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        app_title = QLabel("om2usc")
        app_title.setObjectName("AppTitle")
        subtitle = QLabel("osu!mania to NextRUSH+ SCP")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(app_title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self.add_button = QPushButton("Add OSZ")
        self.clear_button = QPushButton("Clear")
        header.addWidget(self.add_button)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(16)
        root.addLayout(content, 1)

        left_panel = QFrame()
        left_panel.setObjectName("AcrylicPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)
        files_label = QLabel("Input packages")
        files_label.setObjectName("SectionTitle")
        self.drop_hint = QLabel("Drop .osz packages here")
        self.drop_hint.setObjectName("DropHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setMaximumHeight(0)
        self.drop_hint_effect = QGraphicsOpacityEffect(self.drop_hint)
        self.drop_hint.setGraphicsEffect(self.drop_hint_effect)
        self.drop_hint_effect.setOpacity(0.0)

        self.drop_hint_animation = QPropertyAnimation(self.drop_hint_effect, b"opacity", self)
        self.drop_hint_animation.setDuration(180)
        self.drop_hint_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drop_hint_height_animation = QPropertyAnimation(self.drop_hint, b"maximumHeight", self)
        self.drop_hint_height_animation.setDuration(180)
        self.drop_hint_height_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.file_list = DropListWidget()
        self.file_list.setObjectName("PackageList")
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setAlternatingRowColors(False)
        self.file_list.viewport().setAutoFillBackground(False)
        left_layout.addWidget(files_label)
        left_layout.addWidget(self.drop_hint)
        left_layout.addWidget(self.file_list, 1)
        content.addWidget(left_panel, 3)

        right_panel = QFrame()
        right_panel.setObjectName("AcrylicPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(14)
        content.addWidget(right_panel, 4)

        options_label = QLabel("Conversion")
        options_label.setObjectName("SectionTitle")
        right_layout.addWidget(options_label)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        right_layout.addLayout(form)

        default_engine = default_engine_path()
        self.engine_edit = QLineEdit(str(default_engine) if default_engine else "")
        self.engine_button = QPushButton("Browse")
        form.addWidget(QLabel("Engine"), 0, 0)
        form.addWidget(self.engine_edit, 0, 1)
        form.addWidget(self.engine_button, 0, 2)

        self.export_combo = QComboBox()
        self.export_combo.setView(QListView())
        self.export_combo.addItem("One SCP per OSZ", "one-to-one")
        self.export_combo.addItem("Merge into one SCP", "merge")
        form.addWidget(QLabel("Export"), 1, 0)
        form.addWidget(self.export_combo, 1, 1, 1, 2)

        self.output_edit = QLineEdit()
        self.output_button = QPushButton("Browse")
        form.addWidget(QLabel("Output"), 2, 0)
        form.addWidget(self.output_edit, 2, 1)
        form.addWidget(self.output_button, 2, 2)

        self.tail_combo = QComboBox()
        self.tail_combo.setView(QListView())
        tail_labels = {
            "release": "Tail Release",
            "trace": "Tail Trace",
        }
        for mode in ["release", "trace"]:
            if mode in TAIL_MODES:
                self.tail_combo.addItem(tail_labels[mode], mode)
        form.addWidget(QLabel("Hold tail"), 3, 0)
        form.addWidget(self.tail_combo, 3, 1, 1, 2)

        self.background_combo = QComboBox()
        self.background_combo.setView(QListView())
        self.background_combo.addItem("NextRUSH+ default", "default")
        self.background_combo.addItem("Original osu background", "original")
        form.addWidget(QLabel("Gameplay BG"), 4, 0)
        form.addWidget(self.background_combo, 4, 1, 1, 2)

        self.tinged_columns_checkbox = QCheckBox("Tinged Columns")
        self.tinged_columns_checkbox.setToolTip(
            "Convert notes on Tinged Columns to critical notes. 4K: lanes 1/4; 5K: lanes 2/4; 6K: lanes 2/5"
        )
        form.addWidget(QLabel("Note color"), 5, 0)
        form.addWidget(self.tinged_columns_checkbox, 5, 1, 1, 2)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("PrimaryButton")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        right_layout.addWidget(self.convert_button)
        right_layout.addWidget(self.progress)

        log_label = QLabel("Status")
        log_label.setObjectName("SectionTitle")
        self.log = QTextEdit()
        self.log.setObjectName("StatusLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        self.log.viewport().setAutoFillBackground(False)
        right_layout.addWidget(log_label)
        right_layout.addWidget(self.log, 1)

        self.add_button.clicked.connect(self.add_osz_files)
        self.clear_button.clicked.connect(self.clear_files)
        self.file_list.filesDropped.connect(self.add_osz_paths)
        self.file_list.dragStateChanged.connect(self.set_drop_animation)
        self.engine_button.clicked.connect(self.choose_engine)
        self.output_button.clicked.connect(self.choose_output)
        self.export_combo.currentIndexChanged.connect(self._sync_output_hint)
        self.convert_button.clicked.connect(self.start_conversion)
        self._sync_output_hint()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QWidget {
                color: rgba(248, 250, 255, 238);
                font-family: "Segoe UI Variable", "Segoe UI", "Yu Gothic UI";
            }
            QLabel {
                background: transparent;
            }
            #AppTitle {
                font-size: 34px;
                font-weight: 700;
                letter-spacing: 0px;
            }
            #Subtitle {
                color: rgba(232, 238, 255, 178);
                font-size: 13px;
            }
            #SectionTitle {
                color: rgba(255, 255, 255, 226);
                font-size: 14px;
                font-weight: 650;
            }
            #AcrylicPanel {
                background: rgba(22, 26, 38, 164);
                border: 1px solid rgba(255, 255, 255, 44);
                border-radius: 8px;
            }
            QLineEdit, QComboBox, QListWidget, QTextEdit {
                background: rgba(7, 10, 18, 126);
                border: 1px solid rgba(255, 255, 255, 42);
                border-radius: 6px;
                padding: 8px 10px;
                selection-background-color: rgba(255, 138, 184, 172);
            }
            QCheckBox {
                background: transparent;
                spacing: 8px;
                padding: 7px 0;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid rgba(255, 255, 255, 80);
                border-radius: 4px;
                background: rgba(7, 10, 18, 118);
            }
            QCheckBox::indicator:checked {
                background: rgba(255, 196, 66, 218);
                border-color: rgba(255, 235, 164, 230);
            }
            #PackageList, #StatusLog {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 34);
            }
            #PackageList QWidget, #StatusLog QWidget {
                background: transparent;
            }
            #PackageList[dragActive="true"] {
                background: rgba(255, 255, 255, 28);
                border: 1px solid rgba(108, 214, 255, 190);
            }
            #DropHint {
                background: rgba(108, 214, 255, 36);
                border: 1px solid rgba(108, 214, 255, 128);
                border-radius: 6px;
                color: rgba(255, 255, 255, 218);
                padding: 8px 10px;
                font-weight: 650;
            }
            QComboBox QAbstractItemView {
                background: rgb(31, 35, 48);
                color: rgb(248, 250, 255);
                border: 1px solid rgba(255, 255, 255, 72);
                selection-background-color: rgba(255, 138, 184, 184);
                selection-color: white;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 6px 10px;
                color: rgb(248, 250, 255);
            }
            QComboBox QAbstractItemView::item:selected {
                color: white;
            }
            QListWidget::item {
                min-height: 46px;
                border-radius: 6px;
                padding: 8px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background: rgba(255, 138, 184, 112);
            }
            QPushButton {
                background: rgba(255, 255, 255, 38);
                border: 1px solid rgba(255, 255, 255, 58);
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 58);
            }
            QPushButton:pressed {
                background: rgba(255, 138, 184, 96);
            }
            #PrimaryButton {
                background: rgba(255, 118, 172, 184);
                border-color: rgba(255, 196, 220, 210);
                color: white;
                padding: 10px 18px;
            }
            #PrimaryButton:hover {
                background: rgba(255, 136, 188, 212);
            }
            QProgressBar {
                background: rgba(8, 10, 18, 148);
                border: 1px solid rgba(255, 255, 255, 44);
                border-radius: 6px;
                min-height: 18px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: rgba(108, 214, 255, 205);
                border-radius: 5px;
            }
        """)

    def _sync_output_hint(self) -> None:
        if self.export_combo.currentData() == "merge":
            self.output_edit.setPlaceholderText("Choose output .scp file")
        else:
            self.output_edit.setPlaceholderText("Choose output folder")

    def add_osz_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add osu!mania packages",
            "",
            "osu! packages (*.osz);;All files (*.*)",
        )
        if not paths:
            return
        self.add_osz_paths(paths)

    @Slot(list)
    def add_osz_paths(self, paths: List[str]) -> None:
        existing = {entry.path for entry in self.entries}
        for path in paths:
            if path in existing:
                continue
            try:
                entry = inspect_osz(path)
            except Exception as exc:
                show_message(
                    self,
                    QMessageBox.Icon.Warning,
                    "Could not load OSZ",
                    f"{Path(path).name}\n{exc}",
                )
                continue
            self.entries.append(entry)
            item = QListWidgetItem(f"{Path(path).name}\n{entry.chart_count} valid chart(s) - {entry.title}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)
        backgrounds = [entry.background for entry in self.entries if entry.background]
        if backgrounds:
            pixmap = pixmap_from_bytes(random.choice(backgrounds))
            if pixmap and not pixmap.isNull():
                self.background.set_background(pixmap)
        self.log_message(f"Loaded {len(self.entries)} package(s).")

    @Slot(bool)
    def set_drop_animation(self, active: bool) -> None:
        self.drop_hint_animation.stop()
        self.drop_hint_height_animation.stop()
        self.drop_hint_animation.setStartValue(self.drop_hint_effect.opacity())
        self.drop_hint_animation.setEndValue(1.0 if active else 0.0)
        self.drop_hint_height_animation.setStartValue(self.drop_hint.maximumHeight())
        self.drop_hint_height_animation.setEndValue(42 if active else 0)
        self.drop_hint_height_animation.start()
        self.drop_hint_animation.start()

    def clear_files(self) -> None:
        self.entries.clear()
        self.file_list.clear()
        self.background.set_background(None)
        self.progress.setValue(0)
        self.log.clear()

    def choose_engine(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose engine.scp",
            self.engine_edit.text() or "",
            "SCP packages (*.scp);;All files (*.*)",
        )
        if path:
            self.engine_edit.setText(path)

    def choose_output(self) -> None:
        if self.export_combo.currentData() == "merge":
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Choose merged SCP",
                self.output_edit.text() or "merged.scp",
                "SCP packages (*.scp);;All files (*.*)",
            )
            if path:
                if not path.lower().endswith(".scp"):
                    path += ".scp"
                self.output_edit.setText(path)
        else:
            path = QFileDialog.getExistingDirectory(
                self,
                "Choose output folder",
                self.output_edit.text() or "",
            )
            if path:
                self.output_edit.setText(path)

    def start_conversion(self) -> None:
        if not self.entries:
            show_message(
                self,
                QMessageBox.Icon.Information,
                "No input",
                "Add at least one .osz package first.",
            )
            return
        engine_path = self.engine_edit.text().strip()
        output_path = self.output_edit.text().strip()
        if not engine_path or not Path(engine_path).exists():
            show_message(
                self,
                QMessageBox.Icon.Warning,
                "Missing engine",
                "Choose a valid engine.scp file.",
            )
            return
        if not output_path:
            show_message(
                self,
                QMessageBox.Icon.Warning,
                "Missing output",
                "Choose an output path.",
            )
            return

        export_mode = self.export_combo.currentData()
        if export_mode == "merge" and Path(output_path).suffix.lower() != ".scp":
            output_path += ".scp"
            self.output_edit.setText(output_path)

        self._set_controls_enabled(False)
        self.progress.setValue(0)
        self.log_message("Starting conversion.")

        worker = ConversionWorker(
            entries=list(self.entries),
            engine_path=engine_path,
            output_path=output_path,
            export_mode=export_mode,
            tail_mode=self.tail_combo.currentData(),
            background_mode=self.background_combo.currentData(),
            tinged_columns=self.tinged_columns_checkbox.isChecked(),
        )
        worker.signals.progress.connect(self.on_progress)
        worker.signals.message.connect(self.log_message)
        worker.signals.finished.connect(self.on_finished)
        self.thread_pool.start(worker)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.add_button,
            self.clear_button,
            self.engine_button,
            self.output_button,
            self.convert_button,
            self.export_combo,
            self.tail_combo,
            self.background_combo,
            self.tinged_columns_checkbox,
            self.file_list,
        ):
            widget.setEnabled(enabled)

    @Slot(int, int, str)
    def on_progress(self, current: int, total: int, message: str) -> None:
        total = max(1, total)
        self.progress.setValue(int((current / total) * 100))
        if message:
            self.log_message(message)

    @Slot(bool, str)
    def on_finished(self, ok: bool, message: str) -> None:
        self._set_controls_enabled(True)
        self.progress.setValue(100 if ok else self.progress.value())
        self.log_message(message)
        if ok:
            show_message(self, QMessageBox.Icon.Information, "om2usc", message)
        else:
            show_message(self, QMessageBox.Icon.Warning, "om2usc", message)

    def log_message(self, message: str) -> None:
        self.log.append(message)


def inspect_osz(path: str) -> OszEntry:
    entries = read_osz(path)
    charts = filter_valid_charts(parse_all_charts(entries))
    title = charts[0].title if charts else "No valid mania chart"
    background = choose_background_bytes(entries, charts)
    return OszEntry(path=path, chart_count=len(charts), title=title, background=background)


def choose_background_bytes(entries: Dict[str, bytes], charts) -> Optional[bytes]:
    candidates: List[bytes] = []
    for chart in charts:
        if chart.background_filename:
            data = find_asset(entries, chart.background_filename)
            if data:
                candidates.append(data)
    if not candidates:
        for name, data in entries.items():
            if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                candidates.append(data)
    return random.choice(candidates) if candidates else None


def find_asset(entries: Dict[str, bytes], filename: str) -> Optional[bytes]:
    filename_lower = filename.lower()
    for path, data in entries.items():
        if Path(path).name.lower() == filename_lower:
            return data
    for path, data in entries.items():
        if filename_lower in Path(path).name.lower():
            return data
    return None


def pixmap_from_bytes(data: bytes) -> Optional[QPixmap]:
    pixmap = QPixmap()
    if pixmap.loadFromData(data):
        return pixmap
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        pixmap = QPixmap()
        if pixmap.loadFromData(buffer.getvalue(), "PNG"):
            return pixmap
    except Exception:
        return None
    return None


def _unique_output_path(path: Path, used: set[Path]) -> Path:
    candidate = path
    index = 2
    while candidate.exists() or candidate in used:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        index += 1
    used.add(candidate)
    return candidate


def default_engine_path() -> Optional[Path]:
    candidates = [
        Path("engine.scp"),
        Path(getattr(sys, "_MEIPASS", "")) / "engine.scp",
        Path(sys.argv[0]).resolve().parent / "engine.scp",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def show_message(
    parent: QWidget,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
) -> None:
    """Show a QMessageBox with explicit colors so app QSS cannot blank it."""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text or title)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setStyleSheet("""
        QMessageBox {
            background-color: rgb(246, 248, 252);
        }
        QMessageBox QLabel {
            color: rgb(24, 29, 40);
            background: transparent;
            min-width: 300px;
        }
        QMessageBox QPushButton {
            color: rgb(24, 29, 40);
            background: rgb(255, 255, 255);
            border: 1px solid rgba(24, 29, 40, 48);
            border-radius: 6px;
            padding: 7px 18px;
            min-width: 72px;
        }
        QMessageBox QPushButton:hover {
            background: rgb(236, 241, 250);
        }
    """)
    box.exec()


def enable_windows_acrylic(window: QMainWindow) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_int),
                ("AnimationId", ctypes.c_int),
            ]

        class WindowCompositionAttribData(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        accent = AccentPolicy()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = 0xB0181010
        data = WindowCompositionAttribData()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)
        hwnd = wintypes.HWND(int(window.winId()))
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        return


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("om2usc")
    app.setOrganizationName("om2usc")
    window = Om2UscWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
