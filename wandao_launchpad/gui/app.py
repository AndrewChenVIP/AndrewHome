"""GUI 入口。QT_QPA_PLATFORM=offscreen 可无头跑（CI/测试用）。"""

from __future__ import annotations

import sys


def run_gui(argv: list[str] | None = None) -> int:
    from PyQt5 import QtWidgets

    from ..config import ConfigStore
    from . import theme
    from .main_window import MainWindow

    app = QtWidgets.QApplication(argv or sys.argv[:1])
    theme.set_theme(ConfigStore().load().get_ui_pref("theme", "light"))
    app.setStyleSheet(theme.build_qss())
    win = MainWindow(ConfigStore())
    win.show()
    return app.exec_()
