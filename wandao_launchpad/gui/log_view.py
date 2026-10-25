"""日志视图——5000 行上限 + 批量追加 + 跟随/暂停。"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

MAX_BLOCKS = 5000


class LogView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        bar = QtWidgets.QHBoxLayout()
        self.btn_follow = QtWidgets.QPushButton("暂停滚动")
        self.btn_follow.setCheckable(True)
        self.btn_follow.clicked.connect(self._toggle_follow)
        self.btn_clear = QtWidgets.QPushButton("清空显示")
        self.btn_clear.clicked.connect(lambda: self.view.clear())
        self.btn_open = QtWidgets.QPushButton("打开日志文件")
        self.btn_open.clicked.connect(self._open_file)
        self.path_label = QtWidgets.QLabel("")
        self.path_label.setObjectName("muted")
        bar.addWidget(self.btn_follow)
        bar.addWidget(self.btn_clear)
        bar.addWidget(self.btn_open)
        bar.addStretch(1)
        bar.addWidget(self.path_label)
        lay.addLayout(bar)

        self.view = QtWidgets.QPlainTextEdit()
        self.view.setObjectName("logview")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_BLOCKS)
        lay.addWidget(self.view)

        self._paused = False
        self._pending: list[str] = []
        self._pending_cap = 50000

    # ---------- 对外接口 ----------

    def set_path(self, path: str) -> None:
        self.path_label.setText(path)

    def append_batch(self, lines: list[str]) -> None:
        if self._paused:
            self._pending.extend(lines)
            over = len(self._pending) - self._pending_cap
            if over > 0:
                self._pending = self._pending[over:]
            self.btn_follow.setText(f"继续滚动（+{len(self._pending)}）")
            return
        for line in lines:
            self.view.appendPlainText(line)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    # ---------- 内部 ----------

    def _toggle_follow(self) -> None:
        if self._paused:
            # 恢复：先倒掉积压（保留最近 MAX_BLOCKS 由控件自砍）
            for line in self._pending[-MAX_BLOCKS:]:
                self.view.appendPlainText(line)
            self._pending.clear()
            self._paused = False
            self.btn_follow.setText("暂停滚动")
        else:
            self._paused = True
            self.btn_follow.setText("继续滚动")

    def _open_file(self) -> None:
        path = self.path_label.text()
        if path:
            QtWidgets.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
