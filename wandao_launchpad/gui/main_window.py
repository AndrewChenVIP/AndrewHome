"""主窗口——薄壳：侧边导航 + 页面路由 + 启停编排。业务逻辑全在核心层。

刻意保持小（对标 Mie 5829 行上帝类）：本文件只做"把信号接到控件上"。
"""

from __future__ import annotations

import logging
import webbrowser

from PyQt5 import QtCore, QtWidgets

from .. import __version__
from ..config import ConfigStore
from ..context import build_context
from .launch_form import LaunchForm
from .log_view import LogView
from .settings_page import SettingsPage
from .workers import LogTailWorker, StartWorker, StatusWorker, StopWorker

logger = logging.getLogger(__name__)

NAV_ITEMS = [("🚀 启动", "launch"), ("📋 日志", "logs"), ("⚙️ 设置", "settings"), ("ℹ️ 关于", "about")]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.setWindowTitle(f"万道启动台 WandaoLaunchpad v{__version__}")
        self.resize(920, 640)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 侧边导航
        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(170)
        for label, _ in NAV_ITEMS:
            self.nav.addItem(label)
        root.addWidget(self.nav)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("content")
        root.addWidget(self.stack, 1)

        # 页面
        self.launch_page = self._build_launch_page()
        self.log_page = LogView()
        self.settings_page = SettingsPage(store)
        self.settings_page.saved.connect(self._on_settings_saved)
        self.about_page = self._build_about_page()
        for page in (self.launch_page, self.log_page, self.settings_page, self.about_page):
            self.stack.addWidget(page)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.statusBar().showMessage("就绪")

        # 状态定时器：只在"运行中"轮询（3s）；空闲不轮询
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(3000)
        self._poll.timeout.connect(self._poll_once)

        self._start_worker = None
        self._stop_worker = None
        self._status_worker = None
        self._tail_worker = None
        self._state = "idle"  # idle | starting | running | stopping

        QtCore.QTimer.singleShot(0, self._initial_status)

    # ---------- 启动页 ----------

    def _build_launch_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(16, 12, 16, 12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("ComfyUI 一键启动")
        title.setObjectName("title")
        self.env_label = QtWidgets.QLabel("")
        self.env_label.setObjectName("muted")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.env_label)
        lay.addLayout(head)

        self.form = LaunchForm(self.store)
        self.form.changed.connect(lambda: self.statusBar().showMessage("配置已保存", 1500))
        lay.addWidget(self.form, 1)

        self.big_btn = QtWidgets.QPushButton("🚀 一键启动")
        self.big_btn.setObjectName("primary")
        self.big_btn.clicked.connect(self._on_big_btn)
        lay.addWidget(self.big_btn)

        self.state_label = QtWidgets.QLabel("")
        self.state_label.setObjectName("muted")
        lay.addWidget(self.state_label)
        return page

    def _build_about_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addWidget(QtWidgets.QLabel(f"万道启动台 WandaoLaunchpad v{__version__}"))
        lay.addWidget(QtWidgets.QLabel(
            "万道自研 ComfyUI 启动器：只做编排器，不分叉内核。\n"
            "GUI 与 CLI 同体；退出码契约见 AGENTS.md。\n\n"
            "Apache-2.0"))
        lay.addStretch(1)
        return page

    # ---------- 状态机 ----------

    def _set_state(self, state: str, note: str = "") -> None:
        self._state = state
        if state == "idle":
            self.big_btn.setText("🚀 一键启动")
            self.big_btn.setObjectName("primary")
            self._poll.stop()
        elif state == "starting":
            self.big_btn.setText("⏳ 启动中…")
            self.big_btn.setEnabled(False)
        elif state == "running":
            self.big_btn.setText("⏹ 停止")
            self.big_btn.setObjectName("stop")
            self.big_btn.setEnabled(True)
            self._poll.start()
        elif state == "stopping":
            self.big_btn.setText("⏳ 停止中…")
            self.big_btn.setEnabled(False)
        self.big_btn.style().unpolish(self.big_btn)
        self.big_btn.style().polish(self.big_btn)
        self.state_label.setText(note)
        self.statusBar().showMessage(note or "就绪")

    def _refresh_env_label(self) -> None:
        try:
            cfg = self.store.load()
            ctx = build_context(cfg)
            self.env_label.setText(f"{ctx.env.name}  ·  {ctx.env.comfyui_root}")
        except Exception:
            self.env_label.setText("未配置环境 → 去「设置」填写")

    def _initial_status(self) -> None:
        self._refresh_env_label()
        self._poll_once()

    def _poll_once(self) -> None:
        if self._status_worker is not None and self._status_worker.isRunning():
            return  # 上一发还没回来，跳过本拍（不堆积）
        self._status_worker = StatusWorker(self.store, self)
        self._status_worker.finished_sig.connect(self._on_status)
        self._status_worker.start()

    def _on_status(self, ok: bool, st: dict) -> None:
        if not ok:
            self._set_state("idle", f"状态查询失败: {st.get('error')}")
            return
        if st.get("running"):
            if self._state != "running":
                self._set_state("running", f"运行中 {st.get('url')}")
                self._start_tail(st.get("log_path", ""))
        else:
            if self._state == "running":
                self._set_state("idle", "ComfyUI 已退出")
                self._stop_tail()

    # ---------- 启停 ----------

    def _on_big_btn(self) -> None:
        if self._state == "running":
            self._do_stop()
        elif self._state == "idle":
            self._do_start()

    def _do_start(self) -> None:
        self.form.flush()
        self._set_state("starting", "正在启动 ComfyUI…")
        self._start_worker = StartWorker(self.store, self)
        self._start_worker.finished_sig.connect(self._on_started)
        self._start_worker.start()

    def _on_started(self, ok: bool, res: dict) -> None:
        if ok:
            self._set_state("running", f"运行中 {res.get('url')} (PID={res.get('pid')})")
            self._start_tail(self._current_log_path())
            if self._want_browser():
                webbrowser.open(res.get("url", "http://127.0.0.1:8188"))
        elif res.get("already_running"):
            self._set_state("running", f"已有实例在跑（env={res.get('already_running')}）")
            self._start_tail(self._current_log_path())
        else:
            self._set_state("idle", f"启动失败: {res.get('error')}")
            QtWidgets.QMessageBox.warning(self, "启动失败", str(res.get("error")))

    def _do_stop(self) -> None:
        self._set_state("stopping", "正在停止…")
        self._stop_worker = StopWorker(self.store, self)
        self._stop_worker.finished_sig.connect(self._on_stopped)
        self._stop_worker.start()

    def _on_stopped(self, ok: bool, res: dict) -> None:
        self._stop_tail()
        if ok:
            self._set_state("idle", f"已停止 (PID={res.get('pid')})" if res.get("pid") else "无实例在跑")
        else:
            self._set_state("running", f"停止失败: {res.get('error')}")

    def _want_browser(self) -> bool:
        return self.store.load().launch.auto_open_browser

    def _current_log_path(self) -> str:
        try:
            return str(build_context(self.store.load()).comfyui_log)
        except Exception:
            return ""

    # ---------- 日志跟随 ----------

    def _start_tail(self, path: str) -> None:
        if not path:
            return
        self._stop_tail()
        self.log_page.set_path(path)
        self._tail_worker = LogTailWorker(path, self)
        self._tail_worker.batch_sig.connect(self.log_page.append_batch)
        self._tail_worker.start()

    def _stop_tail(self) -> None:
        if self._tail_worker is not None:
            self._tail_worker.stop()
            self._tail_worker.wait(2000)
            self._tail_worker = None

    # ---------- 其他 ----------

    def _on_settings_saved(self) -> None:
        self._refresh_env_label()
        self.form.reload()
        self.statusBar().showMessage("设置已保存", 2000)

    def closeEvent(self, event) -> None:
        self.form.flush()
        self._stop_tail()
        self._poll.stop()
        super().closeEvent(event)
