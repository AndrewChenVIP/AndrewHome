"""启动参数表单——改动自动保存（500ms 防抖），没有保存按钮。

教训对策（Mie 每敲一字全量写盘）：QTimer 单例防抖 + editingFinished，
端口/数字用 QSpinBox 自带约束。
"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import ConfigStore
from ..models import (ATTENTION_CHOICES, MODE_CHOICES, VRAM_CHOICES,
                      LaunchOptions)


class LaunchForm(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()  # 供状态栏提示"已保存"

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = True  # 装载期不发防抖

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        box1 = QtWidgets.QGroupBox("运行")
        g1 = QtWidgets.QGridLayout(box1)
        g1.addWidget(QtWidgets.QLabel("运行模式"), 0, 0)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(list(MODE_CHOICES))
        g1.addWidget(self.mode, 0, 1)
        g1.addWidget(QtWidgets.QLabel("端口"), 0, 2)
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1, 65535)
        g1.addWidget(self.port, 0, 3)
        self.listen_lan = QtWidgets.QCheckBox("允许局域网访问")
        g1.addWidget(self.listen_lan, 0, 4, 1, 2)

        box2 = QtWidgets.QGroupBox("性能（显存 / 注意力）")
        g2 = QtWidgets.QGridLayout(box2)
        g2.addWidget(QtWidgets.QLabel("显存策略"), 0, 0)
        self.vram = QtWidgets.QComboBox()
        self.vram.addItem("由 ComfyUI 决定（推荐）", "auto")
        self.vram.addItem("高", "high")
        self.vram.addItem("中", "normal")
        self.vram.addItem("低", "low")
        self.vram.addItem("极低", "lowest")
        g2.addWidget(self.vram, 0, 1)
        g2.addWidget(QtWidgets.QLabel("注意力优化"), 0, 2)
        self.attention = QtWidgets.QComboBox()
        self.attention.addItem("自动", "auto")
        self.attention.addItem("SDPA (PyTorch)", "sdpa")
        self.attention.addItem("Flash", "flash")
        self.attention.addItem("Sage", "sage")
        self.attention.addItem("Split", "split")
        self.attention.addItem("Quad", "quad")
        g2.addWidget(self.attention, 0, 3)
        g2.addWidget(QtWidgets.QLabel("GPU 序号"), 0, 4)
        self.gpu = QtWidgets.QSpinBox()
        self.gpu.setRange(-1, 15)
        self.gpu.setSpecialValueText("自动")
        g2.addWidget(self.gpu, 0, 5)

        box3 = QtWidgets.QGroupBox("杂项")
        g3 = QtWidgets.QGridLayout(box3)
        self.fast_fp16 = QtWidgets.QCheckBox("快速 FP16 累加（快一点，精度略降）")
        g3.addWidget(self.fast_fp16, 0, 0, 1, 2)
        self.disable_nodes = QtWidgets.QCheckBox("禁用全部插件（排障用）")
        g3.addWidget(self.disable_nodes, 0, 2, 1, 2)
        self.open_browser = QtWidgets.QCheckBox("启动后打开浏览器")
        g3.addWidget(self.open_browser, 1, 0, 1, 2)
        g3.addWidget(QtWidgets.QLabel("额外参数"), 1, 2)
        self.extra_args = QtWidgets.QLineEdit()
        self.extra_args.setPlaceholderText("例: --disable-smart-memory --fp16-vae")
        g3.addWidget(self.extra_args, 1, 3, 1, 3)

        for box in (box1, box2, box3):
            root.addWidget(box)
        root.addStretch(1)

        # 防抖定时器：任何改动 500ms 后落盘一次
        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._save_now)

        for w in (self.mode, self.vram, self.attention):
            w.currentIndexChanged.connect(self._touch)
        for w in (self.port, self.gpu):
            w.valueChanged.connect(self._touch)
        for w in (self.listen_lan, self.fast_fp16, self.disable_nodes, self.open_browser):
            w.toggled.connect(self._touch)
        self.extra_args.textEdited.connect(self._touch)

        self.reload()
        self._loading = False

    # ---------- 装载 / 保存 ----------

    def reload(self) -> None:
        opts: LaunchOptions = self.store.load().launch
        self._loading = True
        self.mode.setCurrentText(opts.mode)
        self.port.setValue(opts.port)
        self.listen_lan.setChecked(bool(opts.listen_lan))
        idx = self.vram.findData(opts.vram)
        self.vram.setCurrentIndex(max(0, idx))
        idx = self.attention.findData(opts.attention)
        self.attention.setCurrentIndex(max(0, idx))
        self.gpu.setValue(-1 if opts.gpu_index is None else opts.gpu_index)
        self.fast_fp16.setChecked(bool(opts.fast_fp16_accumulation))
        self.disable_nodes.setChecked(bool(opts.disable_custom_nodes))
        self.open_browser.setChecked(bool(opts.auto_open_browser))
        self.extra_args.setText(opts.extra_args)
        self._loading = False

    def _touch(self, *_) -> None:
        if not self._loading:
            self._debounce.start()

    def _save_now(self) -> None:
        def mutate(o: LaunchOptions) -> None:
            o.mode = self.mode.currentText()
            o.port = self.port.value()
            o.listen_lan = self.listen_lan.isChecked()
            o.vram = self.vram.currentData() or "auto"
            o.attention = self.attention.currentData() or "auto"
            o.gpu_index = None if self.gpu.value() < 0 else self.gpu.value()
            o.fast_fp16_accumulation = self.fast_fp16.isChecked()
            o.disable_custom_nodes = self.disable_nodes.isChecked()
            o.auto_open_browser = self.open_browser.isChecked()
            o.extra_args = self.extra_args.text().strip()
        self.store.update_launch(mutate)
        self.changed.emit()

    def flush(self) -> None:
        """退出前调用：未到期的防抖立即落盘。"""
        if self._debounce.isActive():
            self._debounce.stop()
            self._save_now()
