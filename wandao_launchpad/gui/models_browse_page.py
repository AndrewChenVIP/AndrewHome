"""模型浏览页——按类型盘点"我有哪些模型"，双击打开所在文件夹。"""

from __future__ import annotations

from datetime import datetime

from PyQt5 import QtCore, QtWidgets

from ..config import ConfigStore
from ..context import build_context
from ..model_paths import ModelPathsService, scan_installed_models
from .workers import FunctionWorker

_COLS = ["文件", "大小", "修改时间", "来源"]


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{n / 1024:.0f} KB"


class ModelsBrowsePage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._data: dict[str, list[dict]] = {}

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("模型浏览")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("muted")
        head.addWidget(self.count_label)
        b_refresh = QtWidgets.QPushButton("刷新盘点")
        b_refresh.clicked.connect(self.reload)
        head.addWidget(b_refresh)
        lay.addLayout(head)

        body = QtWidgets.QHBoxLayout()
        self.type_list = QtWidgets.QListWidget()
        self.type_list.setFixedWidth(210)
        self.type_list.currentRowChanged.connect(self._on_type_changed)
        body.addWidget(self.type_list)

        right = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 130)
        self.table.doubleClicked.connect(self._open_containing_folder)
        right.addWidget(self.table, 1)
        tip = QtWidgets.QLabel("双击行 → 打开模型所在文件夹")
        tip.setObjectName("muted")
        right.addWidget(tip)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

    # ---------- 数据 ----------

    def reload(self) -> None:
        def job():
            cfg = self.store.load()
            ctx = build_context(cfg)
            libs = ModelPathsService(
                ctx.comfyui_root / "ComfyUI", self.store.config_dir).load_libraries()
            data = scan_installed_models(ctx.comfyui_root, libs)
            total = sum(len(v) for v in data.values())
            return {"ok": True, "data": data, "total": total}
        self.status_cb("盘点模型文件…")
        self._run(job, self._on_loaded)

    def _on_loaded(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"盘点失败: {payload.get('error')}")
            return
        self._data = payload["data"]
        self.type_list.blockSignals(True)
        self.type_list.clear()
        for typ in sorted(self._data, key=lambda t: -len(self._data[t])):
            self.type_list.addItem(f"{typ}  ({len(self._data[typ])})")
        self.type_list.blockSignals(False)
        total = payload.get("total", 0)
        self.count_label.setText(f"{len(self._data)} 类 · 共 {total} 个文件")
        if self._data:
            self.type_list.setCurrentRow(0)
        else:
            self.table.setRowCount(0)
        self.status_cb(f"模型盘点完成：{len(self._data)} 类 / {total} 个")

    def _on_type_changed(self, row: int) -> None:
        types = sorted(self._data, key=lambda t: -len(self._data[t]))
        if not (0 <= row < len(types)):
            return
        files = self._data[types[row]]
        self.table.setRowCount(0)
        for f in files:
            r = self.table.rowCount()
            self.table.insertRow(r)
            mtime = datetime.fromtimestamp(f["mtime"]).strftime("%Y-%m-%d %H:%M")
            for col, text in ((0, f["name"]), (1, _fmt_size(f["size"])),
                              (2, mtime), (3, f["source"])):
                item = QtWidgets.QTableWidgetItem(text)
                if col == 0:
                    item.setToolTip(f["path"])
                    item.setData(QtCore.Qt.UserRole, f["path"])
                self.table.setItem(r, col, item)

    def _open_containing_folder(self, index: QtCore.QModelIndex) -> None:
        path = self.table.item(index.row(), 0).data(QtCore.Qt.UserRole)
        if path:
            QtWidgets.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(Path(path).parent)))

    # ---------- 基础 ----------

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()
