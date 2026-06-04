from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from momentum_hunter.app import APP_LOGO_PATH, MomentumHunterWindow


class BrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_logo_asset_loads_into_main_window(self) -> None:
        self.assertTrue(APP_LOGO_PATH.exists())
        patches = [
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
        ]
        for patcher in patches:
            patcher.start()
        window = MomentumHunterWindow()
        try:
            pixmap = window.brand_logo.pixmap()
            self.assertIsNotNone(pixmap)
            self.assertFalse(pixmap.isNull())
            self.assertFalse(window.windowIcon().isNull())
        finally:
            window.close()
            window.deleteLater()
            for patcher in reversed(patches):
                patcher.stop()


if __name__ == "__main__":
    unittest.main()
