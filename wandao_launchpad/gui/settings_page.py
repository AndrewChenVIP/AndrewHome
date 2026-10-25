"""设置页——环境（ComfyUI 根目录 / Python）与镜像三件套。"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import Config, ConfigStore, Environment
from ..constants import DEFAULT_GITHUB_PROXY, DEFAULT_HF_MIRROR, PIP_MIRRORS


class SettingsPage(QtWidgets.QWidget):
    saved = QtCore.pyqtSignal()

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)

        env_box = QtWidgets.QGroupBox("环境（一个环境 = ComfyUI 根目录 + Python）")
        g = QtWidgets.QGridLayout(env_box)
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
        lay.addWidget(env_box)

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

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn = QtWidgets.QPushButton("保存设置")
        btn.setObjectName("primary")
        btn.clicked.connect(self._save)
        row.addWidget(btn)
        lay.addLayout(row)
        lay.addStretch(1)

        self.reload()

    def reload(self) -> None:
        cfg = self.store.load()
        env = cfg.active_env()
        self.env_name.setText(env.name if env else "")
        self.env_root.setText(env.comfyui_root if env else "")
        self.env_python.setText(env.python_path if env else "")
        self.mir_hf.setText(cfg.mirrors.hf or DEFAULT_HF_MIRROR)
        self.mir_gh.setText(cfg.mirrors.github_proxy or DEFAULT_GITHUB_PROXY)
        idx = self.mir_pypi.findText(cfg.mirrors.pypi)
        if idx >= 0:
            self.mir_pypi.setCurrentIndex(idx)
        elif cfg.mirrors.pypi:
            self.mir_pypi.setEditText(cfg.mirrors.pypi)

    def _save(self) -> None:
        cfg: Config = self.store.load()
        name = self.env_name.text().strip() or "默认环境"
        env = cfg.active_env()
        if env is None:
            env = Environment(id="env_default", name=name)
            cfg.environments.append(env)
            cfg.active_env_id = env.id
        env.name = name
        env.comfyui_root = self.env_root.text().strip()
        env.python_path = self.env_python.text().strip()
        cfg.mirrors.hf = self.mir_hf.text().strip()
        cfg.mirrors.github_proxy = self.mir_gh.text().strip()
        cfg.mirrors.pypi = self.mir_pypi.currentText().strip()
        self.store.save(cfg)
        self.saved.emit()

    def _pick_dir(self, edit: QtWidgets.QLineEdit) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择目录")
        if d:
            edit.setText(d)

    def _pick_file(self, edit: QtWidgets.QLineEdit) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 python.exe", "", "python (python.exe)")
        if f:
            edit.setText(f)
