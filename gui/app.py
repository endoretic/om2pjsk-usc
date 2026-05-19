"""PySide6 Windows GUI for the om2usc converter."""

from __future__ import annotations

import io
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QEasingCurve, QObject, QPoint, QPropertyAnimation, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from osu_mania_to_scp import filter_valid_charts, parse_all_charts, read_osz
from src.osu_to_usc import TAIL_MODES
from src.scp_writer import build_merged_scp, build_scp


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
APP_USER_MODEL_ID = "om2usc.converter.gui"


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


class InspectSignals(QObject):
    loaded = Signal(object)
    failed = Signal(str, str)
    finished = Signal()


class OszInspectWorker(QRunnable):
    def __init__(self, paths: List[str]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = InspectSignals()

    @Slot()
    def run(self) -> None:
        for path in self.paths:
            try:
                self.signals.loaded.emit(inspect_osz(path))
            except Exception as exc:  # pragma: no cover - GUI safety boundary
                self.signals.failed.emit(path, str(exc))
        self.signals.finished.emit()


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
        sparse_hidden_ticks: bool,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.engine_path = engine_path
        self.output_path = output_path
        self.export_mode = export_mode
        self.tail_mode = tail_mode
        self.background_mode = background_mode
        self.tinged_columns = tinged_columns
        self.sparse_hidden_ticks = sparse_hidden_ticks
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
                    sparse_hidden_ticks=self.sparse_hidden_ticks,
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
                        sparse_hidden_ticks=self.sparse_hidden_ticks,
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


class HoverTipBubble(QWidget):
    """Tooltip bubble with a manually painted translucent rounded background."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(340)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("""
            QLabel {
                color: rgba(248, 250, 255, 238);
                font-size: 12px;
                line-height: 18px;
                background: transparent;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setBrush(QColor(16, 20, 31, 230))
        painter.setPen(QColor(255, 255, 255, 58))
        painter.drawRoundedRect(rect, 8, 8)


class HoverTip(QObject):
    """Fast custom hover tip for compact option explanations."""

    def __init__(self, parent: QWidget, delay_ms: int = 180) -> None:
        super().__init__(parent)
        self._texts: Dict[QWidget, str] = {}
        self._target: Optional[QWidget] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show_current)
        self._bubble = HoverTipBubble()

    def bind(self, widget: QWidget, text: str) -> None:
        widget.setToolTip("")
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        self._texts[widget] = text

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QWidget) and watched in self._texts:
            if event.type() == QEvent.Type.Enter:
                self._target = watched
                self._timer.start()
            elif event.type() in (
                QEvent.Type.Leave,
                QEvent.Type.Hide,
                QEvent.Type.MouseButtonPress,
            ):
                if self._target is watched:
                    self._target = None
                self._timer.stop()
                self._bubble.hide()
        return super().eventFilter(watched, event)

    def _show_current(self) -> None:
        target = self._target
        if target is None or not target.isVisible() or not target.isEnabled():
            return

        self._bubble.set_text(self._texts[target])
        size = self._bubble.size()
        pos = target.mapToGlobal(QPoint(0, target.height() + 8))

        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            x = min(max(pos.x(), geometry.left() + 8), geometry.right() - size.width() - 8)
            y = pos.y()
            if y + size.height() + 8 > geometry.bottom():
                y = target.mapToGlobal(QPoint(0, -size.height() - 8)).y()
            pos = QPoint(x, y)

        self._bubble.move(pos)
        self._bubble.show()


class Om2UscWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.entries: List[OszEntry] = []
        self.loading_paths: set[str] = set()
        self.pending_items: Dict[str, QListWidgetItem] = {}
        self.thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("om2usc")
        self.resize(1120, 820)
        self.setMinimumSize(920, 720)
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
        subtitle = QLabel("Osu!Mania to ProSekai SCP")
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
        form.setVerticalSpacing(16)
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
            "none": "Tail None",
            "release": "Tail Release",
            "trace": "Tail Trace",
        }
        for mode in ["release", "trace", "none"]:
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
        self.sparse_hidden_ticks_checkbox = QCheckBox("Sparse hidden ticks (For LN)")
        self.option_tip = HoverTip(self)
        self.option_tip.bind(
            self.tinged_columns_checkbox,
            "Marks configured columns as gold critical notes. 4K uses lanes 1/4, 5K uses lanes 2/4, and 6K uses lanes 2/5.",
        )
        self.option_tip.bind(
            self.sparse_hidden_ticks_checkbox,
            "Reduces slide body hidden ticks from every 0.5 beat to every 1.0 beat. Use this for dense LN charts that over-penalize slide body misses.",
        )
        note_options = QHBoxLayout()
        note_options.setContentsMargins(0, 0, 0, 0)
        note_options.setSpacing(18)
        note_options.addWidget(self.tinged_columns_checkbox)
        note_options.addWidget(self.sparse_hidden_ticks_checkbox)
        note_options.addStretch(1)
        form.addWidget(QLabel("Options"), 5, 0)
        form.addLayout(note_options, 5, 1, 1, 2)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("PrimaryButton")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        right_layout.addWidget(self.convert_button)
        right_layout.addWidget(self.progress)
        right_layout.addSpacing(10)

        log_label = QLabel("Status")
        log_label.setObjectName("SectionTitle")
        self.log = QTextEdit()
        self.log.setObjectName("StatusLog")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(132)
        self.log.viewport().setAutoFillBackground(False)
        right_layout.addWidget(log_label)
        right_layout.addWidget(self.log)

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
                selection-background-color: rgba(255, 138, 184, 172);
            }
            QLineEdit, QComboBox {
                min-height: 40px;
                padding: 0px 12px;
                font-size: 14px;
            }
            QTextEdit, QListWidget {
                padding: 8px 10px;
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
                min-height: 40px;
                padding: 0px 16px;
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
                min-height: 44px;
                padding: 0px 18px;
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
        existing = {normalize_path(entry.path) for entry in self.entries}
        queued: List[str] = []

        for path in paths:
            normalized = normalize_path(path)
            if normalized in existing or normalized in self.loading_paths:
                continue
            self.loading_paths.add(normalized)
            queued.append(normalized)
            item = QListWidgetItem(f"{Path(normalized).name}\nLoading...")
            item.setData(Qt.ItemDataRole.UserRole, normalized)
            self.pending_items[normalized] = item
            self.file_list.addItem(item)

        if not queued:
            return

        self.log_message(f"Loading {len(queued)} package(s).")
        worker = OszInspectWorker(queued)
        worker.signals.loaded.connect(self.on_osz_loaded)
        worker.signals.failed.connect(self.on_osz_load_failed)
        worker.signals.finished.connect(self.on_osz_load_finished)
        self.thread_pool.start(worker)

    @Slot(object)
    def on_osz_loaded(self, entry: OszEntry) -> None:
        path = normalize_path(entry.path)
        if path not in self.loading_paths:
            return

        self.loading_paths.discard(path)
        entry.path = path
        self.entries.append(entry)

        item = self.pending_items.pop(path, None)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)
        item.setText(f"{Path(path).name}\n{entry.chart_count} valid chart(s) - {entry.title}")

        if entry.background:
            QTimer.singleShot(
                0,
                lambda data=entry.background, entry_path=path: self._set_background_from_bytes(entry_path, data),
            )
        self.log_message(f"Loaded {Path(path).name}.")

    @Slot(str, str)
    def on_osz_load_failed(self, path: str, message: str) -> None:
        normalized = normalize_path(path)
        self.loading_paths.discard(normalized)
        item = self.pending_items.pop(normalized, None)
        if item is not None:
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
        self.log_message(f"Could not load {Path(normalized).name}: {message}")

    @Slot()
    def on_osz_load_finished(self) -> None:
        if not self.loading_paths:
            self.log_message(f"Ready. {len(self.entries)} package(s) loaded.")

    def _set_background_from_bytes(self, path: str, data: bytes) -> None:
        if all(normalize_path(entry.path) != path for entry in self.entries):
            return
        pixmap = pixmap_from_bytes(data)
        if pixmap and not pixmap.isNull():
            self.background.set_background(pixmap)

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
        self.loading_paths.clear()
        self.pending_items.clear()
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
        if self.loading_paths:
            show_message(
                self,
                QMessageBox.Icon.Information,
                "Packages loading",
                "Wait for the selected .osz packages to finish loading.",
            )
            return
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
            sparse_hidden_ticks=self.sparse_hidden_ticks_checkbox.isChecked(),
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
            self.sparse_hidden_ticks_checkbox,
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


def normalize_path(path: str) -> str:
    return str(Path(path).resolve())


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


def app_icon_path() -> Optional[Path]:
    roots: List[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    roots.extend([
        Path.cwd(),
        Path(sys.argv[0]).resolve().parent,
    ])

    relative_paths = [Path("icon") / "om2usc.ico"]
    for root in roots:
        for relative_path in relative_paths:
            candidate = root / relative_path
            if candidate.exists():
                return candidate.resolve()
    return None


def load_app_icon() -> QIcon:
    icon_path = app_icon_path()
    return QIcon(str(icon_path)) if icon_path is not None else QIcon()


def show_message(
    parent: QWidget,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
) -> None:
    """Show a compact message dialog with stable sizing and app icon."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    app_icon = QApplication.instance().windowIcon() if QApplication.instance() else QIcon()
    if not app_icon.isNull():
        dialog.setWindowIcon(app_icon)
    dialog.setModal(True)
    dialog.setFixedWidth(420)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(20, 18, 20, 16)
    root.setSpacing(16)

    content = QHBoxLayout()
    content.setSpacing(14)
    icon_label = QLabel()
    icon_label.setFixedSize(36, 36)
    icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
    icon_label.setPixmap(_message_icon(icon).pixmap(32, 32))

    text_label = QLabel(text or title)
    text_label.setWordWrap(True)
    text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    text_label.setObjectName("MessageText")
    content.addWidget(icon_label)
    content.addWidget(text_label, 1)
    root.addLayout(content)

    button_row = QHBoxLayout()
    button_row.addStretch(1)
    ok_button = QPushButton("OK")
    ok_button.setObjectName("DialogOkButton")
    ok_button.setDefault(True)
    ok_button.clicked.connect(dialog.accept)
    button_row.addWidget(ok_button)
    root.addLayout(button_row)

    dialog.setStyleSheet("""
        QDialog {
            background-color: rgb(246, 248, 252);
        }
        QLabel {
            color: rgb(24, 29, 40);
            background: transparent;
        }
        #MessageText {
            font-size: 14px;
            line-height: 20px;
        }
        QPushButton#DialogOkButton {
            color: rgb(24, 29, 40);
            background: rgb(255, 255, 255);
            border: 1px solid rgba(24, 29, 40, 48);
            border-radius: 6px;
            padding: 7px 22px;
            min-width: 78px;
        }
        QPushButton#DialogOkButton:hover {
            background: rgb(236, 241, 250);
        }
    """)
    dialog.exec()


def _message_icon(icon: QMessageBox.Icon) -> QIcon:
    style = QApplication.style()
    if icon == QMessageBox.Icon.Warning:
        return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
    if icon == QMessageBox.Icon.Critical:
        return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
    if icon == QMessageBox.Icon.Question:
        return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion)
    return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)


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


def set_windows_app_user_model_id() -> None:
    """Give Windows taskbar/app switcher a stable app identity and icon group."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        return


def main() -> int:
    set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("om2usc")
    app.setOrganizationName("om2usc")
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = Om2UscWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
