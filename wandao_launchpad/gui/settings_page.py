"""设置页——环境管理（列表/增删/设激活）+ 镜像三件套 + 主题。

环境数据层（environments[] + active_env_id）v0.1 就有，这里补齐 GUI。
"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import Config, ConfigStore, Environment
from ..constants import DEFAULT_GITHUB_PROXY, DEFAULT_HF_MIRROR, PIP_MIRRORS


class SettingsPage(QtWidgets.QWidget):
    saved = QtCore.pyqtSignal()          # 任何配置保存后（含切环境）
    theme_change_requested = QtCore.pyqtSignal(str)

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store
        self._current_env_id: str = ""

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        # ---- 环境管理 ----
        env_box = QtWidgets.QGroupBox("环境（一个环境 = ComfyUI 根目录 + Python；★=当前激活）")
        outer = QtWidgets.QVBoxLayout(env_box)
        self.env_list = QtWidgets.QListWidget()
        self.env_list.setMaximumHeight(140)
        self.env_list.currentRowChanged.connect(self._on_env_selected)
        outer.addWidget(self.env_list)
        row0 = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("新增")
        self.btn_add.clicked.connect(self._add_env)
        self.btn_dup = QtWidgets.QPushButton("复制所选")
        self.btn_dup.clicked.connect(self._dup_env)
        self.btn_del = QtWidgets.QPushButton("删除所选")
        self.btn_del.clicked.connect(self._del_env)
        self.btn_activate = QtWidgets.QPushButton("设为激活")
        self.btn_activate.clicked.connect(self._activate_env)
        for b in (self.btn_add, self.btn_dup, self.btn_del, self.btn_activate):
            row0.addWidget(b)
        row0.addStretch(1)
        outer.addLayout(row0)

        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("名称"), 0, 0)
        self.env_name = QtWidgets.QLineEdit()
        g.addWidget(self.env_name, 0, 1)
        g.addWidget(QtWidgets.QLabel("ComfyUI 根目录"), 1, 0)
        self.env_root = QtWidgets.QLineEdit()
        btn_root = QtWidgets.QPushButton("浏览…")
        btn_root.clicked.connect(lambda: self._pick_dir(self.env_root))
        g.addWidget(self.env_root, 1, 1)
        g.addWidget(btn_root, 1, 2)
        g.addWidget(QtWidgets.QLabel("Python 路径"), 2, 0)
        self.env_python = QtWidgets.QLineEdit()
        self.env_python.setPlaceholderText("空 = 系统 python；便携包填 python_embeded\\python.exe")
        btn_py = QtWidgets.QPushButton("浏览…")
        btn_py.clicked.connect(lambda: self._pick_file(self.env_python))
        g.addWidget(self.env_python, 2, 1)
        g.addWidget(btn_py, 2, 2)
        outer.addLayout(g)
        lay.addWidget(env_box)

        # ---- 镜像三件套 ----
        mirror_box = QtWidgets.QGroupBox("国内加速（镜像三件套）")
        m = QtWidgets.QGridLayout(mirror_box)
        m.addWidget(QtWidgets.QLabel("HuggingFace 镜像"), 0, 0)
        self.mir_hf = QtWidgets.QLineEdit(DEFAULT_HF_MIRROR)
        m.addWidget(self.mir_hf, 0, 1)
        m.addWidget(QtWidgets.QLabel("GitHub 代理"), 1, 0)
        self.mir_gh = QtWidgets.QLineEdit(DEFAULT_GITHUB_PROXY)
        m.addWidget(self.mir_gh, 1, 1)
        m.addWidget(QtWidgets.QLabel("PyPI 镜像"), 2, 0)
        self.mir_pypi = QtWidgets.QComboBox()
        self.mir_pypi.setEditable(True)
        self.mir_pypi.addItems(list(PIP_MIRRORS.keys()))
        m.addWidget(self.mir_pypi, 2, 1)
        lay.addWidget(mirror_box)

        # ---- 外观与窗口 ----
        look_box = QtWidgets.QGroupBox("外观与窗口")
        lk = QtWidgets.QHBoxLayout(look_box)
        lk.addWidget(QtWidgets.QLabel("主题"))
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        lk.addWidget(self.theme_combo)
        lk.addSpacing(16)
        self.close_tray_cb = QtWidgets.QCheckBox("关闭窗口时最小化到托盘")
        self.close_tray_cb.toggled.connect(self._on_close_tray_toggled)
        lk.addWidget(self.close_tray_cb)
        lk.addStretch(1)
        lay.addWidget(look_box)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton("保存设置")
        btn.setObjectName("primary")
        btn.clicked.connect(self._save)
        row.addWidget(btn)
        lay.addLayout(row)
        lay.addStretch(1)

        self.reload()

    # ---------- 环境 ----------

    def reload(self) -> None:
        cfg = self.store.load()
        # 列表
        self.env_list.blockSignals(True)
        self.env_list.clear()
        for env in cfg.environments:
            star = "★ " if env.id == cfg.active_env_id else "    "
            self.env_list.addItem(f"{star}{env.name or env.id}")
        self.env_list.blockSignals(False)
        # 选中当前激活（或保持原选中）
        target = self._current_env_id or cfg.active_env_id
        for i, env in enumerate(cfg.environments):
            if env.id == target:
                self.env_list.setCurrentRow(i)
                break
        else:
            if cfg.environments:
                self.env_list.setCurrentRow(0)
        # 镜像与主题
        self.mir_hf.setText(cfg.mirrors.hf or DEFAULT_HF_MIRROR)
        self.mir_gh.setText(cfg.mirrors.github_proxy or DEFAULT_GITHUB_PROXY)
        idx = self.mir_pypi.findText(cfg.mirrors.pypi)
        if idx >= 0:
            self.mir_pypi.setCurrentIndex(idx)
        elif cfg.mirrors.pypi:
            self.mir_pypi.setEditText(cfg.mirrors.pypi)
        saved_theme = cfg.get_ui_pref("theme", "light")
        ti = self.theme_combo.findData(saved_theme)
        self.theme_combo.setCurrentIndex(max(0, ti))
        self.close_tray_cb.setChecked(cfg.get_ui_pref("close_to_tray") == "1")

    def _selected_env(self, cfg: Config) -> Environment | None:
        row = self.env_list.currentRow()
        if 0 <= row < len(cfg.environments):
            return cfg.environments[row]
        return None

    def _on_env_selected(self, row: int) -> None:
        cfg = self.store.load()
        env = self._selected_env(cfg)
        if env is None:
            return
        self._current_env_id = env.id
        self.env_name.setText(env.name)
        self.env_root.setText(env.comfyui_root)
        self.env_python.setText(env.python_path)

    def _save_env_fields(self, cfg: Config) -> None:
        env = self._selected_env(cfg)
        if env is None:
            return
        env.name = self.env_name.text().strip() or env.id
        env.comfyui_root = self.env_root.text().strip()
        env.python_path = self.env_python.text().strip()

    def _add_env(self) -> None:
        cfg = self.store.load()
        new_id = f"env_{len(cfg.environments) + 1}"
        cfg.environments.append(Environment(id=new_id, name="新环境"))
        if not cfg.active_env_id:
            cfg.active_env_id = new_id
        self._save_env_fields(cfg)
        self.store.save(cfg)
        self._current_env_id = new_id
        self.reload()
        self.saved.emit()

    def _dup_env(self) -> None:
        cfg = self.store.load()
        src = self._selected_env(cfg)
        if src is None:
            return
        new_id = f"{src.id}_copy{sum(1 for e in cfg.environments if e.id.startswith(src.id))}"
        cfg.environments.append(Environment(
            id=new_id, name=f"{self.env_name.text()} 副本",
            comfyui_root=self.env_root.text().strip(),
            python_path=self.env_python.text().strip()))
        self.store.save(cfg)
        self._current_env_id = new_id
        self.reload()
        self.saved.emit()

    def _del_env(self) -> None:
        cfg = self.store.load()
        env = self._selected_env(cfg)
        if env is None:
            return
        if len(cfg.environments) <= 1:
            QtWidgets.QMessageBox.information(self, "不能删除", "至少保留一个环境")
            return
        if QtWidgets.QMessageBox.question(
                self, "删除环境",
                f"删除环境「{env.name}」？（只删启动台里的登记，不动磁盘）") \
                != QtWidgets.QMessageBox.Yes:
            return
        cfg.environments.remove(env)
        if cfg.active_env_id == env.id:
            cfg.active_env_id = cfg.environments[0].id
        self.store.save(cfg)
        self._current_env_id = cfg.active_env_id
        self.reload()
        self.saved.emit()

    def _activate_env(self) -> None:
        cfg = self.store.load()
        env = self._selected_env(cfg)
        if env is None or env.id == cfg.active_env_id:
            return
        cfg.active_env_id = env.id
        self._save_env_fields(cfg)
        self.store.save(cfg)
        self.reload()
        self.saved.emit()

    # ---------- 保存 ----------

    def _save(self) -> None:
        cfg = self.store.load()
        self._save_env_fields(cfg)
        cfg.mirrors.hf = self.mir_hf.text().strip()
        cfg.mirrors.github_proxy = self.mir_gh.text().strip()
        cfg.mirrors.pypi = self.mir_pypi.currentText().strip()
        self.store.save(cfg)
        self.saved.emit()

    # ---------- 主题 ----------

    def _on_theme_changed(self, index: int) -> None:
        name = self.theme_combo.itemData(index) or "light"
        self.theme_change_requested.emit(name)   # 应用与持久化由主窗口统一处理

    def _on_close_tray_toggled(self, checked: bool) -> None:
        cfg = self.store.load()
        cfg.set_ui_pref("close_to_tray", "1" if checked else "0")
        self.store.save(cfg)

    # ---------- 浏览 ----------

    def _pick_dir(self, edit: QtWidgets.QLineEdit) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择目录")
        if d:
            edit.setText(d)

    def _pick_file(self, edit: QtWidgets.QLineEdit) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 python.exe", "", "python (python.exe)")
        if f:
            edit.setText(f)
