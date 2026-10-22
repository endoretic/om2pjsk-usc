import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui.app import ConversionWorker, Om2UscWindow, OszEntry
from src.engines import ENGINE_PROFILES, default_engine_path


class GuiEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        if os.name == "nt" and not QFontDatabase.families():
            # The Windows offscreen platform does not discover system fonts.
            for filename in ("SegUIVar.ttf", "segoeui.ttf", "segoeuib.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))

    def setUp(self):
        self.window = Om2UscWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_target_selection_updates_pack_and_background(self):
        window = self.window
        self.assertEqual(window.target_engine_combo.currentData(), "nextrush")
        self.assertEqual(window.engine_edit.text(), str(default_engine_path("nextrush")))
        self.assertEqual(window.tail_combo.currentData(), "release")
        window.engine_edit.setText("custom-rush.scp")
        window.background_combo.setCurrentIndex(1)
        window.target_engine_combo.setFocus()
        QTest.keyClick(window.target_engine_combo, Qt.Key.Key_Down)
        self.assertEqual(window.target_engine_combo.currentData(), "next-sekai")
        self.assertEqual(window.engine_edit.text(), str(default_engine_path("next-sekai")))
        self.assertEqual(window.background_combo.itemText(0), "Next SEKAI default")
        self.assertEqual(window.background_combo.currentData(), "original")
        window.engine_edit.setText("custom-sekai.scp")
        QTest.keyClick(window.target_engine_combo, Qt.Key.Key_Up)
        self.assertEqual(window.engine_edit.text(), "custom-rush.scp")
        self.assertEqual(window.background_combo.itemText(0), "NextRUSH+ default")
        QTest.keyClick(window.target_engine_combo, Qt.Key.Key_Down)
        self.assertEqual(window.engine_edit.text(), "custom-sekai.scp")

    def test_target_controls_are_locked_during_conversion(self):
        for enabled in (False, True):
            self.window._set_controls_enabled(enabled)
            for control in (self.window.target_engine_combo, self.window.engine_edit,
                            self.window.background_combo, self.window.tail_combo):
                self.assertEqual(control.isEnabled(), enabled)

    def test_layout_keeps_controls_visible_at_supported_sizes(self):
        for width, height in ((1120, 880), (920, 780)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                self.app.processEvents()
                controls = (self.window.target_engine_combo, self.window.engine_edit,
                            self.window.export_combo, self.window.output_edit, self.window.tail_combo,
                            self.window.background_combo, self.window.tinged_columns_checkbox,
                            self.window.convert_button, self.window.progress)
                for control in controls:
                    self.assertTrue(control.isVisible())
                    self.assertGreaterEqual(control.height(), control.fontMetrics().height())
                    self.assertTrue(control.parentWidget().rect().contains(control.geometry()), control)
                self.assertEqual(self.window.width(), width)
                for above, below in zip(controls[:6], controls[1:6]):
                    self.assertGreaterEqual(below.y() - above.geometry().bottom(), 8)

    def test_workers_forward_target_in_both_export_modes(self):
        entries = [OszEntry("one.osz", 1, "One"), OszEntry("two.osz", 1, "Two")]
        with tempfile.TemporaryDirectory() as directory:
            for target in ENGINE_PROFILES:
                for mode, function, count in (("merge", "build_merged_scp", 1), ("one-to-one", "build_scp", 2)):
                    with self.subTest(target=target, mode=mode), patch(f"gui.app.{function}", return_value=0) as build:
                        output = str(Path(directory) / "merged.scp") if mode == "merge" else directory
                        worker = ConversionWorker(entries, str(default_engine_path(target)), output,
                                                  mode, "release", "original", True, target)
                        finished = []
                        worker.signals.finished.connect(lambda *args: finished.append(args))
                        worker.run()
                        self.assertEqual(build.call_count, count)
                        self.assertEqual(finished, [(True, "Conversion finished.")])
                        for call in build.call_args_list:
                            self.assertEqual(call.kwargs["target_engine"], target)
                            self.assertEqual(call.kwargs["background_mode"], "original")


if __name__ == "__main__":
    unittest.main()
