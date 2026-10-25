"""出图归档页——勾选 output 里的新作品，一键只增不删拷进 NAS 作品库。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from ..archive import DEFAULT_ARCHIVE_TARGET, archive_files, list_recent_outputs, output_dir_of
from ..config import ConfigStore
from ..context import build_context
from .workers import FunctionWorker

_COLS = ["", "文件", "大小", "修改时间", "子目录"]


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024:.0f} KB"


class ArchivePage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._items: list[dict] = []

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("出图归档")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.target_label = QtWidgets.QLabel("")
        self.target_label.setObjectName("muted")
        head.addWidget(self.target_label)
        lay.addLayout(head)

        bar = QtWidgets.QHBoxLayout()
        b_refresh = QtWidgets.QPushButton("刷新列表")
        b_refresh.clicked.connect(self.reload)
        b_all = QtWidgets.QPushButton("全选")
        b_all.clicked.connect(lambda: self._set_all_checks(True))
        b_none = QtWidgets.QPushButton("全不选")
        b_none.clicked.connect(lambda: self._set_all_checks(False))
        b_new = QtWidgets.QPushButton("选新增（自上次归档）")
        b_new.clicked.connect(self._select_new)
        for b in (b_refresh, b_all, b_none, b_new):
            bar.addWidget(b)
        bar.addStretch(1)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("muted")
        bar.addWidget(self.count_label)
        lay.addLayout(bar)

        self.table = QtWidgets.QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 380)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 150)
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("只增不删：同名同大小跳过；同名不同大小自动改名续位；按日期分夹落库。")
        hint.setObjectName("muted")
        row.addWidget(hint)
        row.addStretch(1)
        self.go_btn = QtWidgets.QPushButton("📥 归档选中 (0)")
        self.go_btn.setObjectName("primary")
        self.go_btn.clicked.connect(self._archive_selected)
        row.addWidget(self.go_btn)
        lay.addLayout(row)

        QtCore.QTimer.singleShot(0, self.reload)

    # ---------- 数据 ----------

    def _target(self) -> str:
        return self.store.load().get_ui_pref("archive_target", DEFAULT_ARCHIVE_TARGET)

    def reload(self) -> None:
        self.target_label.setText(f"落点：{self._target()}")

        def job():
            ctx = build_context(self.store.load())
            return {"ok": True,
                    "items": list_recent_outputs(output_dir_of(ctx.comfyui_root))}
        self.status_cb("扫描 output 目录…")
        self._run(job, self._on_loaded)

    def _on_loaded(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"扫描失败: {payload.get('error')}")
            return
        self._items = payload["items"]
        self.table.setRowCount(0)
        try:
            last = float(self.store.load().get_ui_pref("last_archive_at", "0"))
        except ValueError:
            logging.getLogger(__name__).debug("last_archive_at 非数值，按 0 处理")
            last = 0.0
        for it in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cb = QtWidgets.QTableWidgetItem()
            cb.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            cb.setCheckState(QtCore.Qt.Checked if it["mtime"] > last
                             else QtCore.Qt.Unchecked)
            self.table.setItem(row, 0, cb)
            mtime = datetime.fromtimestamp(it["mtime"]).strftime("%m-%d %H:%M")
            for col, text in ((1, it["rel"]), (2, _fmt_size(it["size"])),
                              (3, mtime), (4, str(Path(it["rel"]).parent))):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
            self.table.item(row, 1).setData(QtCore.Qt.UserRole, it)
        self._update_count()
        n_new = sum(1 for i in self._items if i["mtime"] > last)
        self.status_cb(f"output 图像 {len(self._items)} 个（新增 {n_new}）")

    # ---------- 选择 ----------

    def _checked_items(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == QtCore.Qt.Checked:
                out.append(self.table.item(row, 1).data(QtCore.Qt.UserRole))
        return out

    def _set_all_checks(self, checked: bool) -> None:
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self._update_count()

    def _select_new(self) -> None:
        try:
            last = float(self.store.load().get_ui_pref("last_archive_at", "0"))
        except ValueError:
            last = 0.0
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 1).data(QtCore.Qt.UserRole)
            self.table.item(row, 0).setCheckState(
                QtCore.Qt.Checked if it["mtime"] > last else QtCore.Qt.Unchecked)
        self._update_count()

    def _update_count(self) -> None:
        n = len(self._checked_items())
        self.go_btn.setText(f"📥 归档选中 ({n})")

    # ---------- 动作 ----------

    def _archive_selected(self) -> None:
        files = self._checked_items()
        if not files:
            QtWidgets.QMessageBox.information(self, "未选择", "先勾选要归档的图像")
            return
        target = self._target()

        def job():
            return {"ok": True, **archive_files(files, target)}
        self.go_btn.setEnabled(False)
        self.status_cb(f"归档 {len(files)} 个 → {target}…")
        self._run(job, self._on_archived)

    def _on_archived(self, ok: bool, payload: dict) -> None:
        self.go_btn.setEnabled(True)
        copied = payload.get("copied", [])
        skipped = payload.get("skipped", [])
        renamed = payload.get("renamed", [])
        failed = payload.get("failed", [])
        if copied:
            cfg = self.store.load()
            cfg.set_ui_pref("last_archive_at", str(datetime.now().timestamp()))
            self.store.save(cfg)
        summary = (f"新增 {len(copied)}　已存在跳过 {len(skipped)}"
                   f"　改名 {len(renamed)}　失败 {len(failed)}\n\n落点：{payload.get('target')}")
        if failed:
            QtWidgets.QMessageBox.warning(
                self, "归档完成（有失败）",
                summary + "\n\n失败明细：\n"
                + "\n".join(f"{f['rel']}: {f['reason']}" for f in failed[:8])
                + ("…" if len(failed) > 8 else ""))
        else:
            QtWidgets.QMessageBox.information(self, "归档完成", summary)
        self.status_cb(f"归档完成：新增 {len(copied)}，跳过 {len(skipped)}，失败 {len(failed)}")
        self.reload()

    # ---------- 基础 ----------

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()
