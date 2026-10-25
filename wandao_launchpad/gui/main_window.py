"""主窗口——薄壳：侧边导航 + 页面路由 + 启停编排。业务逻辑全在核心层。

刻意保持小（对标 Mie 5829 行上帝类）：本文件只做"把信号接到控件上"。
"""

from __future__ import annotations

import logging
import webbrowser

from PyQt5 import QtCore, QtWidgets

from .. import APP_NAME, __version__
from ..config import ConfigStore
from ..context import build_context
from .launch_form import LaunchForm
from .log_view import LogView
from .settings_page import SettingsPage
from .workers import LogTailWorker, StartWorker, StatusWorker, StopWorker

logger = logging.getLogger(__name__)

NAV_ITEMS = [("🚀 启动", "launch"), ("📋 日志", "logs"), ("🧩 插件", "plugins"),
             ("🧬 内核", "kernel"), ("📂 模型库", "models"), ("⚙️ 设置", "settings"),
             ("ℹ️ 关于", "about")]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.setWindowTitle(f"万道启动台 WandaoLaunchpad v{__version__}")
        self.resize(1000, 680)
        self.setMinimumSize(920, 640)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 侧边栏（品牌头部 + 导航）
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("sidebarwrap")
        side_lay = QtWidgets.QVBoxLayout(sidebar)
        side_lay.setContentsMargins(10, 16, 10, 12)
        side_lay.setSpacing(6)
        brand = QtWidgets.QLabel(APP_NAME)
        brand.setObjectName("sidebar_title")
        ver = QtWidgets.QLabel(f"WandaoLaunchpad v{__version__}")
        ver.setObjectName("sidebar_version")
        side_lay.addWidget(brand)
        side_lay.addWidget(ver)
        side_lay.addSpacing(10)
        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName("sidebar")
        for label, _ in NAV_ITEMS:
            self.nav.addItem(label)
        side_lay.addWidget(self.nav, 1)
        sidebar.setFixedWidth(190)
        root.addWidget(sidebar)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("content")
        root.addWidget(self.stack, 1)

        # 页面
        self.launch_page = self._build_launch_page()
        self.log_page = LogView()
        from .plugins_page import PluginsPage
        from .kernel_page import KernelPage
        from .models_page import ModelsPage
        status = self.statusBar().showMessage
        self.plugins_page = PluginsPage(store, status_cb=lambda m: status(m, 5000))
        self.kernel_page = KernelPage(store, status_cb=lambda m: status(m, 5000))
        self.models_page = ModelsPage(store, status_cb=lambda m: status(m, 5000))
        self.settings_page = SettingsPage(store)
        self.settings_page.saved.connect(self._on_settings_saved)
        self.settings_page.theme_change_requested.connect(self._apply_theme)
        self.about_page = self._build_about_page()
        for page in (self.launch_page, self.log_page, self.plugins_page,
                     self.kernel_page, self.models_page, self.settings_page,
                     self.about_page):
            self.stack.addWidget(page)

        self._loaded_pages: set[int] = set()
        self.nav.currentRowChanged.connect(self._on_nav_changed)
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
        self._support_worker = None
        self._state = "idle"  # idle | starting | running | stopping
        self._really_quit = False
        self._build_tray()

        QtCore.QTimer.singleShot(0, self._initial_status)

    def _on_nav_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        # 首次进入的页面自动拉数据（插件/内核；模型库自带定时器）
        if row not in self._loaded_pages:
            self._loaded_pages.add(row)
            page = self.stack.widget(row)
            if page is self.plugins_page or page is self.kernel_page:
                page.reload()

    # ---------- 启动页 ----------

    def _build_launch_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("ComfyUI 一键启动")
        title.setObjectName("title")
        self.env_combo = QtWidgets.QComboBox()
        self.env_combo.setMinimumWidth(220)
        self.env_combo.currentIndexChanged.connect(self._on_env_switched)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.env_combo)
        lay.addLayout(head)

        self.form = LaunchForm(self.store)
        self.form.changed.connect(lambda: self.statusBar().showMessage("配置已保存", 1500))
        lay.addWidget(self.form, 1)

        # 运行信息卡（只读，当前环境摘要）
        info_box = QtWidgets.QGroupBox("运行信息")
        ig = QtWidgets.QGridLayout()
        ig.setHorizontalSpacing(18)
        ig.setVerticalSpacing(8)
        self.info_fields: dict[str, QtWidgets.QLabel] = {}
        for i, (label, key) in enumerate((
                ("环境目录", "root"), ("Python", "python"),
                ("服务地址", "url"), ("日志文件", "log"))):
            ig.addWidget(QtWidgets.QLabel(label), i // 2, (i % 2) * 2)
            val = QtWidgets.QLabel("—")
            val.setObjectName("muted")
            ig.addWidget(val, i // 2, (i % 2) * 2 + 1)
            self.info_fields[key] = val
        info_box.setLayout(ig)
        lay.addWidget(info_box)

        self.big_btn = QtWidgets.QPushButton("🚀 一键启动")
        self.big_btn.setObjectName("primary")
        self.big_btn.clicked.connect(self._on_big_btn)
        lay.addWidget(self.big_btn)

        # 快捷目录 + 支持包
        quick = QtWidgets.QHBoxLayout()
        for label, key in (("根目录", "root"), ("输出", "output"), ("输入", "input"),
                           ("模型", "models"), ("插件", "nodes"), ("日志", "log")):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _=False, k=key: self._open_quick_dir(k))
            quick.addWidget(b)
        quick.addStretch(1)
        btn_support = QtWidgets.QPushButton("📦 打包支持包")
        btn_support.clicked.connect(self._make_support_zip)
        quick.addWidget(btn_support)
        btn_doctor = QtWidgets.QPushButton("🩺 体检")
        btn_doctor.clicked.connect(self._run_doctor)
        quick.addWidget(btn_doctor)
        lay.addLayout(quick)

        self.state_label = QtWidgets.QLabel("")
        self.state_label.setObjectName("muted")
        lay.addWidget(self.state_label)
        return page

    def _build_about_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)
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
            self.env_combo.blockSignals(True)
            self.env_combo.clear()
            for env in cfg.environments:
                self.env_combo.addItem(env.name or env.id, env.id)
            idx = self.env_combo.findData(cfg.active_env_id)
            self.env_combo.setCurrentIndex(max(0, idx))
            self.env_combo.blockSignals(False)
            # 运行信息卡
            try:
                ctx = build_context(cfg)
                f = self.info_fields
                f["root"].setText(str(ctx.comfyui_root))
                f["python"].setText(ctx.python_exe)
                f["url"].setText(ctx.base_url)
                f["log"].setText(str(ctx.comfyui_log))
                for val in f.values():
                    val.setToolTip(val.text())
            except LookupError:
                for val in self.info_fields.values():
                    val.setText("—（未配置环境）")
        except Exception:
            logger.warning("环境列表刷新失败", exc_info=True)

    def _on_env_switched(self, index: int) -> None:
        env_id = self.env_combo.itemData(index)
        if not env_id:
            return
        cfg = self.store.load()
        if env_id == cfg.active_env_id:
            return
        # 护栏：本启动台管理的实例在跑时不切（pidfile 定点判断，不误伤外部实例）
        from .. import pidfile as pf
        from ..constants import pidfile_path
        rec = pf.read(pidfile_path(self.store.config_dir))
        if rec and pf.is_alive(rec):
            QtWidgets.QMessageBox.warning(
                self, "先停止再切换",
                f"环境「{rec.env_id}」的 ComfyUI 还在跑（PID={rec.pid}）。\n"
                "先停止当前实例，再切换环境。")
            self._refresh_env_label()
            return
        cfg.active_env_id = env_id
        self.store.save(cfg)
        self._refresh_env_label()
        self._poll_once()
        self.statusBar().showMessage(f"已切换到环境: {env_id}", 3000)

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
        if self._tray is not None:
            label = "运行中" if st.get("running") else "未运行"
            if st.get("external"):
                label += "（外部实例）"
            self._tray_status.setText(f"状态：{label}")
            self._tray.setToolTip(f"万道启动台 · {label}")
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
        if res.get("preflight"):
            fails = res.get("fail", [])
            lines = "\n".join(f"✗ {f['name']}: {f['detail']}" for f in fails)
            QtWidgets.QMessageBox.warning(
                self, "启动前体检未通过", "以下问题必须先解决：\n\n" + lines)
            self._set_state("idle", "体检未通过，未启动")
            return
        if ok:
            self._set_state("running", f"运行中 {res.get('url')} (PID={res.get('pid')})")
            self._start_tail(self._current_log_path())
            if self._want_browser():
                self._open_browser(res.get("url", "http://127.0.0.1:8188"))
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

    def _apply_theme(self, name: str) -> None:
        from . import theme
        theme.set_theme(name)
        QtWidgets.QApplication.instance().setStyleSheet(theme.build_qss())
        # 持久化在唯一写入方这里（设置页只发信号）
        cfg = self.store.load()
        cfg.set_ui_pref("theme", name)
        self.store.save(cfg)
        self.statusBar().showMessage(f"主题已切换: {'深色' if name == 'dark' else '浅色'}", 2000)

    def _open_browser(self, url: str) -> None:
        browser = self.store.load().launch.browser_path.strip()
        if browser:
            import subprocess
            try:
                subprocess.Popen([browser, url])
                return
            except OSError:
                logger.warning("指定浏览器启动失败，退默认: %s", browser, exc_info=True)
        webbrowser.open(url)

    # ---------- 快捷目录 / 支持包 ----------

    def _quick_paths(self) -> dict[str, Path]:
        try:
            ctx = build_context(self.store.load())
            comfy = ctx.comfyui_root / "ComfyUI"
            return {"root": ctx.comfyui_root, "output": comfy / "output",
                    "input": comfy / "input", "models": comfy / "models",
                    "nodes": comfy / "custom_nodes", "log": ctx.comfyui_log}
        except Exception:
            logger.debug("快捷目录解析失败（未配置环境？）", exc_info=True)
            return {}

    def _open_quick_dir(self, key: str) -> None:
        path = self._quick_paths().get(key)
        if path is None or not path.exists():
            QtWidgets.QMessageBox.information(self, "未找到", f"路径不存在：{path or key}")
            return
        QtWidgets.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _make_support_zip(self) -> None:
        from ..support import build_support_zip

        def job():
            from ..context import build_context as bc
            from ..constants import pidfile_path as pfp
            cfg = self.store.load()
            path = build_support_zip(bc(cfg), pfp(self.store.config_dir))
            return {"ok": True, "zip_path": str(path)}
        self.statusBar().showMessage("打包支持包…")
        from .workers import FunctionWorker
        self._support_worker = FunctionWorker(job, self)
        self._support_worker.finished_sig.connect(self._on_support_done)
        self._support_worker.start()

    def _on_support_done(self, ok: bool, payload: dict) -> None:
        if ok:
            path = payload.get("zip_path", "")
            self.statusBar().showMessage(f"支持包: {path}", 5000)
            QtWidgets.QMessageBox.information(self, "支持包已生成", path)
        else:
            QtWidgets.QMessageBox.warning(self, "打包失败", str(payload.get("error")))

    def _run_doctor(self) -> None:
        from ..constants import pidfile_path as pfp
        from .workers import FunctionWorker

        def job():
            from .. import doctor
            from ..context import build_context as bc
            cfg = self.store.load()
            checks = doctor.run_checks(bc(cfg), config_dir=self.store.config_dir)
            nf, nw = doctor.summarize(checks)
            return {"ok": nf == 0, "checks": checks, "fail": nf, "warn": nw}
        self.statusBar().showMessage("体检中…")
        self._doctor_worker = FunctionWorker(job, self)
        self._doctor_worker.finished_sig.connect(self._on_doctor_done)
        self._doctor_worker.start()

    def _on_doctor_done(self, ok: bool, payload: dict) -> None:
        if not ok and "checks" not in payload:
            QtWidgets.QMessageBox.warning(self, "体检失败", str(payload.get("error")))
            return
        icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}
        lines = [f"{icon.get(c['level'], '·')} {c['name']}：{c['detail']}"
                 for c in payload.get("checks", [])]
        nf, nw = payload.get("fail", 0), payload.get("warn", 0)
        tail = "无阻塞项，可以启动。" if nf == 0 else f"有 {nf} 项阻塞，先解决再启动！"
        QtWidgets.QMessageBox.information(
            self, f"体检结果（✗{nf} ⚠{nw}）", "\n".join(lines) + "\n\n" + tail)
        self.statusBar().showMessage(f"体检完成：✗{nf} ⚠{nw}", 5000)

    # ---------- 系统托盘 ----------

    def _build_tray(self) -> None:
        self._tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        # 程序化生成托盘图标（紫底"万"字），不依赖资源文件
        from PyQt5 import QtGui
        pix = QtGui.QPixmap(64, 64)
        pix.fill(QtGui.QColor("#7f56d9"))
        painter = QtGui.QPainter(pix)
        painter.setPen(QtGui.QColor("white"))
        font = painter.font()
        font.setPixelSize(40)
        painter.setFont(font)
        painter.drawText(pix.rect(), QtCore.Qt.AlignCenter, "万")
        painter.end()
        icon = QtGui.QIcon(pix)

        self._tray = QtWidgets.QSystemTrayIcon(icon, self)
        self._tray.setToolTip("万道启动台")
        menu = QtWidgets.QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_from_tray)
        self._tray_status = menu.addAction("状态：未知")
        self._tray_status.setEnabled(False)
        act_probe = menu.addAction("立即探测")
        act_probe.triggered.connect(self._poll_once)
        menu.addSeparator()
        act_stop_quit = menu.addAction("退出并关闭 ComfyUI")
        act_stop_quit.triggered.connect(self._quit_with_stop)
        act_quit = menu.addAction("退出启动台")
        act_quit.triggered.connect(self._quit_app)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._show_from_tray()
            if reason == QtWidgets.QSystemTrayIcon.DoubleClick else None)
        self._tray.show()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _quit_with_stop(self) -> None:
        self._set_state("stopping", "退出并停止 ComfyUI…")
        self._stop_worker = StopWorker(self.store, self)

        def on_stopped(ok: bool, res: dict) -> None:
            self._quit_app()
        self._stop_worker.finished_sig.connect(on_stopped)
        self._stop_worker.start()

    def _quit_app(self) -> None:
        self._really_quit = True
        self.close()
        QtWidgets.QApplication.quit()

    def closeEvent(self, event) -> None:
        # 关闭到托盘（偏好开启且非真退出）：藏窗口不退出
        if (not self._really_quit
                and self.store.load().get_ui_pref("close_to_tray") == "1"
                and self._tray is not None):
            event.ignore()
            self.hide()
            return
        self.form.flush()
        self._stop_tail()
        self._poll.stop()
        for worker in (self._status_worker, self._start_worker, self._stop_worker,
                       self._support_worker, getattr(self, "_doctor_worker", None)):
            if worker is not None and worker.isRunning():
                worker.wait(2000)
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
